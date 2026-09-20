"""PDF text extractor using PyMuPDF. DEV-014, DEV-015.

Fallback chain:
    PyMuPDF native text
        ↓ (if quality insufficient)
    OCR (delegated to OCRProcessor — DEV-016)

Does NOT OCR every document automatically.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import pymupdf as fitz

from qbank.processing.interfaces import (
    ExtractedDocument,
    ExtractionChecker,
    Extractor,
    PageText,
)

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)

# Minimum characters per page to consider text "sufficient"
_MIN_CHARS_PER_PAGE = 50
# Minimum ratio of printable characters in extracted text
_MIN_PRINTABLE_RATIO = 0.6


class TextQualityChecker(ExtractionChecker):
    """Heuristic text quality checker. DEV-015.

    Scores based on:
      - Character count
      - Ratio of printable vs total characters
      - Presence of common garbage patterns from bad PDF extraction
    """

    def score(self, text: str) -> float:
        if not text or len(text) < 5:
            return 0.0

        total = len(text)
        printable = sum(1 for c in text if c.isprintable() or c in "\n\t ")
        printable_ratio = printable / total

        # Penalise for garbage unicode replacement characters
        garbage = text.count("\ufffd") + text.count("\x00")
        garbage_ratio = garbage / total

        # Base score from printable ratio, penalised by garbage
        score = max(0.0, printable_ratio - garbage_ratio * 2)

        # Boost if text looks like real content (letters + spaces)
        alpha_count = sum(1 for c in text if c.isalpha())
        if total > 0 and alpha_count / total > 0.3:
            score = min(1.0, score * 1.2)

        return round(min(1.0, max(0.0, score)), 3)

    def is_sufficient(self, page: PageText) -> bool:
        if len(page.text.strip()) < _MIN_CHARS_PER_PAGE:
            return False
        return page.quality_score >= _MIN_PRINTABLE_RATIO


class PyMuPDFExtractor(Extractor):
    """Primary PDF text extractor using PyMuPDF. DEV-014.

    Extracts text page-by-page. Each page gets a quality score.
    Pages below threshold are flagged for OCR fallback (DEV-015).
    """

    def __init__(self, quality_checker: ExtractionChecker | None = None) -> None:
        self._checker = quality_checker or TextQualityChecker()

    def extract(self, pdf_bytes: bytes) -> ExtractedDocument:
        """Extract text from all pages. Track quality per page."""
        try:
            doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        except Exception as exc:
            logger.error("Failed to open PDF: %s", exc)
            return ExtractedDocument(
                pages=[],
                extraction_method="failed",
                overall_quality=0.0,
                page_count=0,
            )

        pages: list[PageText] = []
        needs_ocr_count = 0

        for page_num in range(len(doc)):
            page = doc[page_num]
            try:
                text = page.get_text("text")  # type: ignore[attr-defined]
            except Exception as exc:
                logger.warning("Page %d extraction failed: %s", page_num + 1, exc)
                text = ""

            quality = self._checker.score(text)
            page_text = PageText(
                page_number=page_num + 1,
                text=text,
                extraction_method="native",
                quality_score=quality,
            )

            if not self._checker.is_sufficient(page_text):
                needs_ocr_count += 1
                page_text = PageText(
                    page_number=page_num + 1,
                    text=text,
                    extraction_method="native_low_quality",
                    quality_score=quality,
                )

            pages.append(page_text)

        doc.close()

        if not pages:
            return ExtractedDocument(
                pages=[],
                extraction_method="failed",
                overall_quality=0.0,
                page_count=0,
            )

        overall_quality = sum(p.quality_score for p in pages) / len(pages)

        if needs_ocr_count == 0:
            method = "native"
        elif needs_ocr_count == len(pages):
            method = "ocr_required"  # all pages need OCR
        else:
            method = "hybrid_required"  # some pages need OCR

        return ExtractedDocument(
            pages=pages,
            extraction_method=method,
            overall_quality=overall_quality,
            page_count=len(pages),
        )

    def get_page_image(self, pdf_bytes: bytes, page_number: int, dpi: int = 150) -> bytes:
        """Render a single page to PNG bytes for OCR. 1-indexed page_number."""
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        page = doc[page_number - 1]
        mat = fitz.Matrix(dpi / 72, dpi / 72)
        pix = page.get_pixmap(matrix=mat, colorspace=fitz.csRGB)  # type: ignore[attr-defined]
        png_bytes = pix.tobytes("png")
        doc.close()
        return png_bytes
