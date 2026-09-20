"""Repository interfaces (abstract base classes). DEV-008.

Application services depend on these interfaces rather than directly
querying PostgreSQL. Infrastructure implementations live in:
    src/qbank/infrastructure/repositories/

This keeps the domain and application layers independent of the ORM.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Sequence
from typing import Any

from qbank.domain.models import (
    Chunk,
    Course,
    Document,
    DocumentVersion,
    Question,
    Source,
    SyncRun,
)


class SourceRepository(ABC):
    """Persistence interface for Source aggregates."""

    @abstractmethod
    async def get_by_id(self, source_id: str) -> Source | None: ...

    @abstractmethod
    async def get_all_active(self) -> Sequence[Source]: ...

    @abstractmethod
    async def save(self, source: Source) -> None: ...

    @abstractmethod
    async def update_last_synced(self, source_id: str) -> None: ...


class DocumentRepository(ABC):
    """Persistence interface for Document aggregates."""

    @abstractmethod
    async def get_by_id(self, document_id: str) -> Document | None: ...

    @abstractmethod
    async def get_by_remote_id(self, source_id: str, remote_id: str) -> Document | None: ...

    @abstractmethod
    async def get_by_course(
        self,
        course_code: str,
        year: int | None = None,
        semester: str | None = None,
        limit: int = 50,
    ) -> Sequence[Document]: ...

    @abstractmethod
    async def save(self, document: Document) -> None: ...

    @abstractmethod
    async def upsert(self, document: Document) -> Document: ...

    @abstractmethod
    async def list_by_source(
        self,
        source_id: str,
        limit: int = 100,
        offset: int = 0,
    ) -> Sequence[Document]: ...


class DocumentVersionRepository(ABC):
    """Persistence interface for DocumentVersion aggregates."""

    @abstractmethod
    async def get_by_id(self, version_id: str) -> DocumentVersion | None: ...

    @abstractmethod
    async def get_latest(self, document_id: str) -> DocumentVersion | None: ...

    @abstractmethod
    async def get_by_hash(self, document_id: str, version_hash: str) -> DocumentVersion | None: ...

    @abstractmethod
    async def save(self, version: DocumentVersion) -> None: ...

    @abstractmethod
    async def mark_processed(
        self,
        version_id: str,
        extraction_method: str,
        text_quality_score: float | None = None,
    ) -> None: ...


class ChunkRepository(ABC):
    """Persistence interface for Chunk aggregates."""

    @abstractmethod
    async def get_by_id(self, chunk_id: str) -> Chunk | None: ...

    @abstractmethod
    async def get_by_version(self, version_id: str) -> Sequence[Chunk]: ...

    @abstractmethod
    async def bulk_insert(self, chunks: Sequence[Chunk]) -> None: ...

    @abstractmethod
    async def delete_by_version(self, version_id: str) -> int: ...


class CourseRepository(ABC):
    """Persistence interface for Course aggregates."""

    @abstractmethod
    async def get_by_id(self, course_id: str) -> Course | None: ...

    @abstractmethod
    async def get_by_code(self, course_code: str) -> Course | None: ...

    @abstractmethod
    async def get_all(self, tenant_id: str = "IUT") -> Sequence[Course]: ...

    @abstractmethod
    async def save(self, course: Course) -> None: ...

    @abstractmethod
    async def upsert(self, course: Course) -> Course: ...

    @abstractmethod
    async def search_by_alias(self, raw_code: str) -> Course | None: ...


class QuestionRepository(ABC):
    """Persistence interface for Question aggregates."""

    @abstractmethod
    async def get_by_id(self, question_id: str) -> Question | None: ...

    @abstractmethod
    async def get_by_document(self, document_id: str) -> Sequence[Question]: ...

    @abstractmethod
    async def bulk_insert(self, questions: Sequence[Question]) -> None: ...

    @abstractmethod
    async def search(self, filters: dict[str, Any], limit: int = 20) -> Sequence[Question]: ...


class SyncRunRepository(ABC):
    """Persistence interface for SyncRun tracking (DEV-013)."""

    @abstractmethod
    async def get_by_id(self, run_id: str) -> SyncRun | None: ...

    @abstractmethod
    async def get_latest_for_source(self, source_id: str) -> SyncRun | None: ...

    @abstractmethod
    async def save(self, run: SyncRun) -> None: ...

    @abstractmethod
    async def update(self, run: SyncRun) -> None: ...
