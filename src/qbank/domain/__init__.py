"""Domain package — core knowledge model.

Exports the full set of domain models, value objects, enumerations,
and repository interfaces.

This package must remain independent of:
  - SQLAlchemy / PostgreSQL
  - Qdrant
  - FastMCP
  - any infrastructure library
"""
from qbank.domain.course_normalization import (
    CourseCodeIndex,
    codes_are_equivalent,
    normalize_course_code,
)
from qbank.domain.models import (
    Chunk,
    Course,
    Department,
    Document,
    DocumentType,
    DocumentVersion,
    ExtractionMethod,
    ExtractionStatus,
    Language,
    Provenance,
    Question,
    Semester,
    Source,
    SourceType,
    SyncRun,
    SyncStatus,
)
from qbank.domain.repositories import (
    ChunkRepository,
    CourseRepository,
    DocumentRepository,
    DocumentVersionRepository,
    QuestionRepository,
    SourceRepository,
    SyncRunRepository,
)

__all__ = [
    # Models
    "Chunk",
    "ChunkRepository",
    "Course",
    "CourseRepository",
    "CourseCodeIndex",
    "CourseRef",
    "Department",
    "Document",
    "DocumentRepository",
    "DocumentType",
    "DocumentVersion",
    "DocumentVersionRepository",
    "ExtractionMethod",
    "ExtractionStatus",
    "Language",
    "Provenance",
    "Question",
    "QuestionRepository",
    "Semester",
    "Source",
    "SourceRepository",
    "SourceType",
    "SyncRun",
    "SyncRunRepository",
    "SyncStatus",
    # Course normalization
    "codes_are_equivalent",
    "normalize_course_code",
]
