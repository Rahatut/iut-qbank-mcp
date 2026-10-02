"""Processing pipeline interfaces. DEV-050.

Each stage of the pipeline is independently replaceable:
    Extractor          → DEV-014
    ExtractionChecker  → DEV-015
    OCRProcessor       → DEV-016
    MetadataExtractor  → DEV-017
    Classifier         → DEV-018
    Chunker            → DEV-019
    EmbeddingProvider  → DEV-022
    Indexer            → DEV-023

No stage depends on another's implementation — only on its interface.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

# ── Shared data structures ────────────────────────────────────────────────────


@dataclass
class PageText:
    """Text extracted from a single PDF page."""

    page_number: int  # 1-indexed
    text: str
    extraction_method: str  # "native" | "ocr"
    quality_score: float  # 0.0-1.0


@dataclass
class ExtractedDocument:
    """Result of running Extractor + OCRProcessor on a PDF."""

    pages: list[PageText]
    extraction_method: str  # "native" | "ocr" | "hybrid" | "failed"
    overall_quality: float  # 0.0-1.0
    page_count: int
    needs_ocr: bool = False  # native text insufficient, OCR recommended

    @property
    def full_text(self) -> str:
        return "\n\n".join(p.text for p in self.pages if p.text.strip())

    def with_pages(self, pages: list[PageText]) -> ExtractedDocument:
        """Return a copy with replaced pages and recomputed summary fields.

        Used after OCR replaces low-quality native pages: extraction_method and
        overall_quality must reflect the new text, not the pre-OCR scan.
        """
        if any(p.text.strip() for p in pages):
            ocr_pages = sum(1 for p in pages if p.extraction_method == "ocr")
            if ocr_pages == len(pages):
                method = "ocr"
            elif ocr_pages:
                method = "hybrid"
            else:
                method = "native"
        else:
            method = "failed"
        quality = sum(p.quality_score for p in pages) / len(pages) if pages else 0.0
        return ExtractedDocument(
            pages=pages,
            extraction_method=method,
            overall_quality=round(quality, 3),
            page_count=len(pages),
            needs_ocr=False,
        )


@dataclass
class NormalizedMetadata:
    """Metadata extracted and normalized for a document. DEV-017."""

    course_code: str | None = None
    department: str | None = None
    year: int | None = None
    semester: str | None = None
    exam_type: str | None = None  # "final", "midterm", "quiz"
    document_type: str | None = None
    language: str | None = None
    confidence: float = 0.0  # 0.0-1.0; do not require perfect before indexing


@dataclass
class ChunkData:
    """A single chunk produced by the Chunker. DEV-019, DEV-020."""

    text: str
    page: int | None
    chunk_index: int
    token_count: int
    question_number: str | None = None


# ── Stage interfaces ──────────────────────────────────────────────────────────


class Extractor(ABC):
    """Extracts text from a PDF. DEV-014.

    Primary: PyMuPDF native text.
    Fallback chain: alternative parser → OCR (managed by ExtractionChecker).
    """

    @abstractmethod
    def extract(self, pdf_bytes: bytes) -> ExtractedDocument:
        """Extract text from raw PDF bytes. Returns all pages."""
        ...

    def get_page_image(self, pdf_bytes: bytes, page_number: int) -> bytes:
        """Render one page to image bytes for OCR. 1-indexed page_number.

        Optional: OCRProcessor implementations that do not need page images
        may leave this unsupported.
        """
        raise NotImplementedError(f"{type(self).__name__} cannot render page images")


class ExtractionChecker(ABC):
    """Determines whether extracted text meets quality threshold. DEV-015.

    Drives the OCR fallback decision:
        extract → quality_check → sufficient? continue : OCR
    """

    @abstractmethod
    def is_sufficient(self, page: PageText) -> bool:
        """Return True if page text quality is good enough without OCR."""
        ...

    @abstractmethod
    def score(self, text: str) -> float:
        """Return a quality score 0.0-1.0 for the given text."""
        ...


class OCRProcessor(ABC):
    """Performs OCR on a PDF page image. DEV-016.

    Page-level OCR; preserves page numbers; records OCR status.
    """

    @abstractmethod
    def ocr_page(self, page_image: bytes, page_number: int) -> PageText:
        """Run OCR on a page image (PNG/JPEG bytes) and return extracted text + metadata."""
        ...

    def ocr_document(
        self,
        extractor: Extractor,
        pdf_bytes: bytes,
        extracted: ExtractedDocument,
    ) -> tuple[list[PageText], int]:
        """OCR every page of a document lacking a usable text layer.

        Returns (pages, failed_count). Implementations may override with a
        faster or batched strategy; the default is page-by-page.
        """
        pages: list[PageText] = []
        failed = 0
        for page in extracted.pages:
            result = self.ocr_page(
                extractor.get_page_image(pdf_bytes, page.page_number),
                page.page_number,
            )
            if not result.text.strip():
                failed += 1
            pages.append(result)
        return pages, failed


class MetadataExtractor(ABC):
    """Extracts and normalizes document metadata. DEV-017.

    Layered extraction order:
        repository metadata → directory/path → filename →
        PDF metadata → extracted text → classifier
    """

    @abstractmethod
    def extract(
        self,
        *,
        repository_metadata: dict[str, Any] | None = None,
        filename: str | None = None,
        pdf_metadata: dict[str, Any] | None = None,
        text_sample: str | None = None,
    ) -> NormalizedMetadata:
        """Extract and normalize metadata. Returns best-effort result with confidence."""
        ...


class Classifier(ABC):
    """Classifies a document into a DocumentType. DEV-018.

    Kept replaceable so an ML/LLM classifier can replace the rule-based
    implementation without touching ingestion.
    """

    @abstractmethod
    def classify(
        self,
        filename: str | None,
        text_sample: str | None,
        repository_metadata: dict[str, Any] | None = None,
    ) -> tuple[str, float]:
        """Return (document_type, confidence). document_type matches DocumentType enum values."""
        ...


class Chunker(ABC):
    """Splits extracted text into chunks. DEV-019.

    For question papers, should preserve:
        page, question number, sub-question, question boundaries.
    """

    @abstractmethod
    def chunk(self, extracted: ExtractedDocument) -> list[ChunkData]:
        """Split the extracted document into chunks."""
        ...


class EmbeddingProvider(ABC):
    """Computes vector embeddings. DEV-022.

    Application must not depend directly on sentence-transformers or any
    specific model. Swap providers without changing callers.
    """

    @abstractmethod
    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        """Return one embedding vector per text (batch)."""
        ...

    @abstractmethod
    def embed_query(self, text: str) -> list[float]:
        """Return the embedding for a single query string."""
        ...

    @property
    @abstractmethod
    def model_name(self) -> str:
        """The model identifier used for this provider."""
        ...

    @property
    @abstractmethod
    def dimension(self) -> int:
        """Embedding vector dimension."""
        ...
