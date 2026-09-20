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

# ── Shared data structures ────────────────────────────────────────────────────

@dataclass
class PageText:
    """Text extracted from a single PDF page."""
    page_number: int        # 1-indexed
    text: str
    extraction_method: str  # "native" | "ocr"
    quality_score: float    # 0.0-1.0


@dataclass
class ExtractedDocument:
    """Result of running Extractor + OCRProcessor on a PDF."""
    pages: list[PageText]
    extraction_method: str   # "native" | "ocr" | "hybrid" | "failed"
    overall_quality: float   # 0.0-1.0
    page_count: int

    @property
    def full_text(self) -> str:
        return "\n\n".join(p.text for p in self.pages if p.text.strip())


@dataclass
class NormalizedMetadata:
    """Metadata extracted and normalized for a document. DEV-017."""
    course_code: str | None = None
    department: str | None = None
    year: int | None = None
    semester: str | None = None
    exam_type: str | None = None        # "final", "midterm", "quiz"
    document_type: str | None = None
    language: str | None = None
    confidence: float = 0.0             # 0.0-1.0; do not require perfect before indexing


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
        """Run OCR on a page image and return extracted text with metadata."""
        ...


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
        repository_metadata: dict | None = None,
        filename: str | None = None,
        pdf_metadata: dict | None = None,
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
        repository_metadata: dict | None = None,
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
