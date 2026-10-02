"""Tesseract OCR fallback processor. DEV-016.

Page-level OCR for scanned question papers.
Preserves page numbers, records OCR status.
Failed pages are retryable (ProcessingJobRow.attempt).
"""

from __future__ import annotations

import io
import logging

from PIL import Image

from qbank.infrastructure.config import get_settings
from qbank.processing.interfaces import (
    ExtractedDocument,
    Extractor,
    OCRProcessor,
    PageText,
)

logger = logging.getLogger(__name__)


class TesseractOCRProcessor(OCRProcessor):
    """OCR using Tesseract via pytesseract. DEV-016.

    Requires: tesseract-ocr system package + pytesseract Python package.
    """

    def __init__(self, language: str | None = None) -> None:
        settings = get_settings()
        self._language = language or settings.ocr_language
        self._enabled = settings.ocr_enabled

    def ocr_page(self, page_image: bytes, page_number: int) -> PageText:
        """Run Tesseract on a page image (PNG/JPEG bytes).

        Returns PageText with extraction_method="ocr".
        On failure, returns a PageText with empty text and quality_score=0.0
        so the caller can retry (DEV-048).
        """
        if not self._enabled:
            logger.debug("OCR is disabled; skipping page %d", page_number)
            return PageText(
                page_number=page_number,
                text="",
                extraction_method="ocr_disabled",
                quality_score=0.0,
            )

        try:
            import pytesseract  # imported here so OCR is only required when enabled
        except ImportError:
            logger.error("pytesseract not installed. Install it with: pip install pytesseract")
            return PageText(
                page_number=page_number,
                text="",
                extraction_method="ocr_unavailable",
                quality_score=0.0,
            )

        try:
            image = Image.open(io.BytesIO(page_image))
            text: str = pytesseract.image_to_string(image, lang=self._language)
            quality = min(1.0, len(text.strip()) / 500)  # rough heuristic
            return PageText(
                page_number=page_number,
                text=text,
                extraction_method="ocr",
                quality_score=quality,
            )
        except Exception as exc:
            logger.error("OCR failed for page %d: %s", page_number, exc)
            return PageText(
                page_number=page_number,
                text="",
                extraction_method="ocr_failed",
                quality_score=0.0,
            )

    def ocr_document(
        self,
        extractor: Extractor,
        pdf_bytes: bytes,
        extracted: ExtractedDocument,
    ) -> tuple[list[PageText], int]:
        """OCR every page of a document that lacked a usable text layer.

        Scanned question papers return zero native characters, so without this
        pass they produce no chunks and nothing reaches the vector index.

        Native text is preferred where it exists: OCR is only applied to pages
        the quality checker already rejected.

        Returns (pages, failed_count).
        """
        pages: list[PageText] = []
        failed = 0
        pending = [p for p in extracted.pages if p.extraction_method != "native"]
        total = len(pending)

        for position, page in enumerate(extracted.pages, start=1):
            if page.extraction_method == "native":
                pages.append(page)
                continue

            try:
                image = extractor.get_page_image(pdf_bytes, page.page_number)
            except Exception as exc:
                logger.error("Could not render page %d for OCR: %s", page.page_number, exc)
                failed += 1
                pages.append(page)
                continue

            ocr_page = self.ocr_page(image, page.page_number)
            if not ocr_page.text.strip():
                failed += 1
                # Keep the native text: even poor native text beats nothing.
                pages.append(page)
            else:
                pages.append(ocr_page)

            # OCR dominates ingestion wall-clock for scanned papers; log
            # progress so a long document is visibly moving, not hung.
            if position % 10 == 0 or position == len(extracted.pages):
                logger.info(
                    "  ↳ OCR progress: %d/%d pages (%d to OCR, %d failed)",
                    position,
                    len(extracted.pages),
                    total,
                    failed,
                )

        return pages, failed
