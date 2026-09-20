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
from qbank.processing.interfaces import OCRProcessor, PageText

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
