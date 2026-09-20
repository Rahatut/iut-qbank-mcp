"""Core domain models for the IUT Question Bank.

These models are completely independent of PostgreSQL, Qdrant, and MCP.
They represent the canonical knowledge model.

Hierarchy:
    Source → Document → DocumentVersion → Chunk → Question

DEV-004, DEV-006
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any


def _utcnow() -> datetime:
    return datetime.now(UTC)


# ── Enumerations ──────────────────────────────────────────────────────────────


class DocumentType(StrEnum):
    """Broad classification of a document's purpose. See DEV-018."""

    QUESTION_PAPER = "question_paper"
    SYLLABUS = "syllabus"
    LECTURE_MATERIAL = "lecture_material"
    TUTORIAL = "tutorial"
    ASSIGNMENT = "assignment"
    OTHER = "other"


class ExtractionMethod(StrEnum):
    """How text was extracted from a PDF. See DEV-014, DEV-015."""

    NATIVE = "native"  # PyMuPDF text layer
    OCR = "ocr"  # Tesseract
    HYBRID = "hybrid"  # Some pages native, some OCR
    FAILED = "failed"


class ExtractionStatus(StrEnum):
    PENDING = "pending"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class SyncStatus(StrEnum):
    """Status of a document as determined by incremental sync. See DEV-012."""

    NEW = "new"
    CHANGED = "changed"
    UNCHANGED = "unchanged"
    DELETED = "deleted"
    UNAVAILABLE = "unavailable"


class Semester(StrEnum):
    SPRING = "Spring"
    SUMMER = "Summer"
    FALL = "Fall"
    WINTER = "Winter"


class Language(StrEnum):
    ENGLISH = "en"
    BANGLA = "bn"
    UNKNOWN = "unknown"


class SourceType(StrEnum):
    DSPACE = "dspace"
    GITHUB = "github"
    UPLOAD = "upload"
    GOOGLE_DRIVE = "google_drive"
    ADMIN_IMPORT = "admin_import"


# ── Value Objects ─────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class CourseRef:
    """Immutable reference to a canonical course. See DEV-005."""

    course_id: str
    course_code: str  # canonical form e.g. "CSE3101"
    title: str = ""
    department: str = ""


@dataclass(frozen=True)
class Provenance:
    """Complete lineage of a retrieved item. DEV-006 — core, not optional.

    Every chunk/question must carry full provenance traceable back to:
      source → document → document_version → page → chunk
    """

    source_id: str
    source_type: SourceType
    source_url: str

    document_id: str
    document_url: str
    document_title: str

    version_id: str
    version_hash: str

    page: int | None = None
    original_filename: str | None = None
    repository_url: str | None = None


# ── Aggregate Roots ───────────────────────────────────────────────────────────


@dataclass
class Department:
    """An academic department. Root of the course hierarchy."""

    department_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    code: str = ""  # e.g. "CSE"
    name: str = ""  # e.g. "Computer Science and Engineering"
    tenant_id: str = "IUT"  # DEV-052 multi-university readiness
    created_at: datetime = field(default_factory=_utcnow)


@dataclass
class Course:
    """A canonical academic course. See DEV-005 for normalization rules."""

    course_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    course_code: str = ""  # canonical e.g. "CSE3101"
    title: str = ""
    department_id: str = ""
    aliases: list[str] = field(default_factory=list)  # "CSE 3101", "CSE-3101"
    tenant_id: str = "IUT"
    created_at: datetime = field(default_factory=_utcnow)
    updated_at: datetime = field(default_factory=_utcnow)


@dataclass
class Source:
    """A content repository that documents are discovered from.

    Examples: IUT DSpace, GitHub repo, upload endpoint.
    """

    source_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    source_type: SourceType = SourceType.DSPACE
    name: str = ""
    base_url: str = ""
    repository_url: str = ""
    tenant_id: str = "IUT"
    is_active: bool = True
    created_at: datetime = field(default_factory=_utcnow)
    last_synced_at: datetime | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class Document:
    """A discovered academic document within a Source.

    A document may have multiple versions over time (see DocumentVersion).
    """

    document_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    source_id: str = ""
    remote_id: str = ""  # DSpace item UUID or similar
    title: str = ""
    document_url: str = ""
    original_filename: str | None = None
    document_type: DocumentType = DocumentType.OTHER
    course_id: str | None = None
    course_code: str | None = None  # denormalized for query performance
    department: str | None = None
    year: int | None = None
    semester: Semester | None = None
    language: Language = Language.ENGLISH
    tenant_id: str = "IUT"
    created_at: datetime = field(default_factory=_utcnow)
    updated_at: datetime = field(default_factory=_utcnow)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class DocumentVersion:
    """A specific version of a Document, identified by its content hash.

    Enables incremental sync (DEV-012): only changed documents are re-processed.
    """

    version_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    document_id: str = ""
    version_hash: str = ""  # SHA-256 of raw file content
    file_size_bytes: int = 0
    storage_key: str = ""  # path/key in object storage (DEV-010)
    extraction_status: ExtractionStatus = ExtractionStatus.PENDING
    extraction_method: ExtractionMethod | None = None
    text_quality_score: float | None = None  # 0.0-1.0, DEV-015
    page_count: int | None = None
    created_at: datetime = field(default_factory=_utcnow)
    processed_at: datetime | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class Chunk:
    """A segment of text extracted from a DocumentVersion.

    Chunks are the unit indexed in Qdrant (DEV-009, DEV-020).
    Each carries full provenance (DEV-006).
    """

    chunk_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    document_id: str = ""
    version_id: str = ""
    page: int | None = None
    chunk_index: int = 0  # position within the document
    text: str = ""
    token_count: int = 0
    question_number: str | None = None  # e.g. "3", "3a", "Q3(b)"
    provenance: Provenance | None = None
    created_at: datetime = field(default_factory=_utcnow)


@dataclass
class Question:
    """A structured question extracted from a Chunk.

    Exists alongside generic chunks — see DEV-021.
    """

    question_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    chunk_id: str = ""
    document_id: str = ""
    version_id: str = ""
    question_number: str = ""  # e.g. "3(a)"
    text: str = ""
    marks: int | None = None
    page: int | None = None
    course_id: str | None = None
    course_code: str | None = None
    year: int | None = None
    semester: Semester | None = None
    provenance: Provenance | None = None
    created_at: datetime = field(default_factory=_utcnow)


# ── Sync Tracking ─────────────────────────────────────────────────────────────


@dataclass
class SyncRun:
    """Records a single synchronization run from a Source. DEV-013."""

    run_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    source_id: str = ""
    started_at: datetime = field(default_factory=_utcnow)
    finished_at: datetime | None = None
    status: str = "running"  # running | completed | failed
    documents_discovered: int = 0
    documents_downloaded: int = 0
    documents_skipped: int = 0
    documents_failed: int = 0
    error_summary: str | None = None
