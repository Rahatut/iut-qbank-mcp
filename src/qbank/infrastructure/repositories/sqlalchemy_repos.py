"""SQLAlchemy async repository implementations. DEV-008.

Concrete implementations of the domain repository interfaces.
All methods use async SQLAlchemy sessions passed from the outside
(unit-of-work pattern — callers manage session lifecycle).

Hierarchy:
    domain/repositories.py (ABC)
        ↓
    infrastructure/repositories/sqlalchemy_repos.py (this file)
"""
from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from qbank.domain.models import (
    Chunk,
    Course,
    Document,
    DocumentType,
    DocumentVersion,
    ExtractionMethod,
    ExtractionStatus,
    Language,
    Question,
    Semester,
    Source,
    SourceType,
    SyncRun,
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
from qbank.infrastructure.db.models import (
    CourseRow,
    DocumentChunkRow,
    DocumentRow,
    DocumentVersionRow,
    QuestionRow,
    SourceRow,
    SyncRunRow,
)

# ── Mapping helpers ───────────────────────────────────────────────────────────

def _row_to_source(row: SourceRow) -> Source:
    return Source(
        source_id=row.source_id,
        source_type=SourceType(row.source_type),
        name=row.name,
        base_url=row.base_url,
        repository_url=row.repository_url,
        tenant_id=row.tenant_id,
        is_active=row.is_active,
        created_at=row.created_at,
        last_synced_at=row.last_synced_at,
        metadata=dict(row.metadata_),
    )


def _row_to_document(row: DocumentRow) -> Document:
    return Document(
        document_id=row.document_id,
        source_id=row.source_id,
        remote_id=row.remote_id,
        title=row.title,
        document_url=row.document_url,
        original_filename=row.original_filename,
        document_type=DocumentType(row.document_type),
        course_id=row.course_id,
        course_code=row.course_code,
        department=row.department,
        year=row.year,
        semester=Semester(row.semester) if row.semester else None,
        language=Language(row.language),
        tenant_id=row.tenant_id,
        created_at=row.created_at,
        updated_at=row.updated_at,
        metadata=dict(row.metadata_),
    )


def _row_to_version(row: DocumentVersionRow) -> DocumentVersion:
    return DocumentVersion(
        version_id=row.version_id,
        document_id=row.document_id,
        version_hash=row.version_hash,
        file_size_bytes=row.file_size_bytes,
        storage_key=row.storage_key,
        extraction_status=ExtractionStatus(row.extraction_status),
        extraction_method=ExtractionMethod(row.extraction_method) if row.extraction_method else None,
        text_quality_score=row.text_quality_score,
        page_count=row.page_count,
        created_at=row.created_at,
        processed_at=row.processed_at,
        metadata=dict(row.metadata_),
    )


def _row_to_chunk(row: DocumentChunkRow) -> Chunk:
    return Chunk(
        chunk_id=row.chunk_id,
        document_id=row.document_id,
        version_id=row.version_id,
        page=row.page,
        chunk_index=row.chunk_index,
        text=row.text,
        token_count=row.token_count,
        question_number=row.question_number,
        created_at=row.created_at,
    )


def _row_to_course(row: CourseRow) -> Course:
    return Course(
        course_id=row.course_id,
        course_code=row.course_code,
        title=row.title,
        department_id=row.department_id or "",
        aliases=list(row.aliases or []),
        tenant_id=row.tenant_id,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _row_to_question(row: QuestionRow) -> Question:
    return Question(
        question_id=row.question_id,
        chunk_id=row.chunk_id,
        document_id=row.document_id,
        version_id=row.version_id,
        question_number=row.question_number,
        text=row.text,
        marks=row.marks,
        page=row.page,
        course_id=row.course_id,
        course_code=row.course_code,
        year=row.year,
        semester=Semester(row.semester) if row.semester else None,
        created_at=row.created_at,
    )


def _row_to_sync_run(row: SyncRunRow) -> SyncRun:
    return SyncRun(
        run_id=row.run_id,
        source_id=row.source_id,
        started_at=row.started_at,
        finished_at=row.finished_at,
        status=row.status,
        documents_discovered=row.documents_discovered,
        documents_downloaded=row.documents_downloaded,
        documents_skipped=row.documents_skipped,
        documents_failed=row.documents_failed,
        error_summary=row.error_summary,
    )


# ── Repository implementations ────────────────────────────────────────────────

class SqlSourceRepository(SourceRepository):
    """SQLAlchemy async implementation of SourceRepository."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_id(self, source_id: str) -> Source | None:
        row = await self._session.get(SourceRow, source_id)
        return _row_to_source(row) if row else None

    async def get_all_active(self) -> Sequence[Source]:
        result = await self._session.execute(
            select(SourceRow).where(SourceRow.is_active.is_(True))
        )
        return [_row_to_source(r) for r in result.scalars().all()]

    async def save(self, source: Source) -> None:
        existing = await self._session.get(SourceRow, source.source_id)
        if existing:
            existing.source_type = source.source_type.value
            existing.name = source.name
            existing.base_url = source.base_url
            existing.repository_url = source.repository_url
            existing.is_active = source.is_active
            existing.last_synced_at = source.last_synced_at
            existing.metadata_ = source.metadata
        else:
            self._session.add(
                SourceRow(
                    source_id=source.source_id,
                    source_type=source.source_type.value,
                    name=source.name,
                    base_url=source.base_url,
                    repository_url=source.repository_url,
                    tenant_id=source.tenant_id,
                    is_active=source.is_active,
                    last_synced_at=source.last_synced_at,
                    metadata_=source.metadata,
                )
            )

    async def update_last_synced(self, source_id: str) -> None:
        await self._session.execute(
            update(SourceRow)
            .where(SourceRow.source_id == source_id)
            .values(last_synced_at=datetime.now(UTC))
        )


class SqlDocumentRepository(DocumentRepository):
    """SQLAlchemy async implementation of DocumentRepository."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_id(self, document_id: str) -> Document | None:
        row = await self._session.get(DocumentRow, document_id)
        return _row_to_document(row) if row else None

    async def get_by_remote_id(self, source_id: str, remote_id: str) -> Document | None:
        result = await self._session.execute(
            select(DocumentRow).where(
                DocumentRow.source_id == source_id,
                DocumentRow.remote_id == remote_id,
            )
        )
        row = result.scalar_one_or_none()
        return _row_to_document(row) if row else None

    async def get_by_course(
        self,
        course_code: str,
        year: int | None = None,
        semester: str | None = None,
        limit: int = 50,
    ) -> Sequence[Document]:
        q = select(DocumentRow).where(DocumentRow.course_code == course_code)
        if year is not None:
            q = q.where(DocumentRow.year == year)
        if semester is not None:
            q = q.where(DocumentRow.semester == semester)
        q = q.limit(limit).order_by(DocumentRow.year.desc())  # type: ignore[arg-type]
        result = await self._session.execute(q)
        return [_row_to_document(r) for r in result.scalars().all()]

    async def save(self, document: Document) -> None:
        existing = await self._session.get(DocumentRow, document.document_id)
        if existing:
            self._update_row(existing, document)
        else:
            self._session.add(self._to_row(document))

    async def upsert(self, document: Document) -> Document:
        existing = await self.get_by_remote_id(document.source_id, document.remote_id)
        if existing:
            row = await self._session.get(DocumentRow, existing.document_id)
            if row:
                self._update_row(row, document)
            return existing
        self._session.add(self._to_row(document))
        return document

    async def list_by_source(
        self,
        source_id: str,
        limit: int = 100,
        offset: int = 0,
    ) -> Sequence[Document]:
        result = await self._session.execute(
            select(DocumentRow)
            .where(DocumentRow.source_id == source_id)
            .limit(limit)
            .offset(offset)
        )
        return [_row_to_document(r) for r in result.scalars().all()]

    def _to_row(self, doc: Document) -> DocumentRow:
        return DocumentRow(
            document_id=doc.document_id,
            source_id=doc.source_id,
            remote_id=doc.remote_id,
            title=doc.title,
            document_url=doc.document_url,
            original_filename=doc.original_filename,
            document_type=doc.document_type.value,
            course_id=doc.course_id,
            course_code=doc.course_code,
            department=doc.department,
            year=doc.year,
            semester=doc.semester.value if doc.semester else None,
            language=doc.language.value,
            tenant_id=doc.tenant_id,
            metadata_=doc.metadata,
        )

    def _update_row(self, row: DocumentRow, doc: Document) -> None:
        row.title = doc.title
        row.document_url = doc.document_url
        row.document_type = doc.document_type.value
        row.course_id = doc.course_id
        row.course_code = doc.course_code
        row.department = doc.department
        row.year = doc.year
        row.semester = doc.semester.value if doc.semester else None
        row.language = doc.language.value
        row.metadata_ = doc.metadata


class SqlDocumentVersionRepository(DocumentVersionRepository):
    """SQLAlchemy async implementation of DocumentVersionRepository."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_id(self, version_id: str) -> DocumentVersion | None:
        row = await self._session.get(DocumentVersionRow, version_id)
        return _row_to_version(row) if row else None

    async def get_latest(self, document_id: str) -> DocumentVersion | None:
        result = await self._session.execute(
            select(DocumentVersionRow)
            .where(DocumentVersionRow.document_id == document_id)
            .order_by(DocumentVersionRow.created_at.desc())  # type: ignore[arg-type]
            .limit(1)
        )
        row = result.scalar_one_or_none()
        return _row_to_version(row) if row else None

    async def get_by_hash(
        self, document_id: str, version_hash: str
    ) -> DocumentVersion | None:
        result = await self._session.execute(
            select(DocumentVersionRow).where(
                DocumentVersionRow.document_id == document_id,
                DocumentVersionRow.version_hash == version_hash,
            )
        )
        row = result.scalar_one_or_none()
        return _row_to_version(row) if row else None

    async def save(self, version: DocumentVersion) -> None:
        existing = await self._session.get(DocumentVersionRow, version.version_id)
        if existing:
            existing.extraction_status = version.extraction_status.value
            existing.extraction_method = (
                version.extraction_method.value if version.extraction_method else None
            )
            existing.text_quality_score = version.text_quality_score
            existing.page_count = version.page_count
            existing.processed_at = version.processed_at
            existing.storage_key = version.storage_key
        else:
            self._session.add(
                DocumentVersionRow(
                    version_id=version.version_id,
                    document_id=version.document_id,
                    version_hash=version.version_hash,
                    file_size_bytes=version.file_size_bytes,
                    storage_key=version.storage_key,
                    extraction_status=version.extraction_status.value,
                    extraction_method=(
                        version.extraction_method.value
                        if version.extraction_method
                        else None
                    ),
                    text_quality_score=version.text_quality_score,
                    page_count=version.page_count,
                    processed_at=version.processed_at,
                    metadata_=version.metadata,
                )
            )

    async def mark_processed(
        self,
        version_id: str,
        extraction_method: str,
        text_quality_score: float | None = None,
    ) -> None:
        await self._session.execute(
            update(DocumentVersionRow)
            .where(DocumentVersionRow.version_id == version_id)
            .values(
                extraction_status=ExtractionStatus.SUCCEEDED.value,
                extraction_method=extraction_method,
                text_quality_score=text_quality_score,
                processed_at=datetime.now(UTC),
            )
        )


class SqlChunkRepository(ChunkRepository):
    """SQLAlchemy async implementation of ChunkRepository."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_id(self, chunk_id: str) -> Chunk | None:
        row = await self._session.get(DocumentChunkRow, chunk_id)
        return _row_to_chunk(row) if row else None

    async def get_by_version(self, version_id: str) -> Sequence[Chunk]:
        result = await self._session.execute(
            select(DocumentChunkRow)
            .where(DocumentChunkRow.version_id == version_id)
            .order_by(DocumentChunkRow.chunk_index)
        )
        return [_row_to_chunk(r) for r in result.scalars().all()]

    async def bulk_insert(self, chunks: Sequence[Chunk]) -> None:
        for chunk in chunks:
            self._session.add(
                DocumentChunkRow(
                    chunk_id=chunk.chunk_id,
                    document_id=chunk.document_id,
                    version_id=chunk.version_id,
                    page=chunk.page,
                    chunk_index=chunk.chunk_index,
                    text=chunk.text,
                    token_count=chunk.token_count,
                    question_number=chunk.question_number,
                )
            )

    async def delete_by_version(self, version_id: str) -> int:
        result = await self._session.execute(
            select(DocumentChunkRow).where(DocumentChunkRow.version_id == version_id)
        )
        rows = result.scalars().all()
        count = len(rows)
        for row in rows:
            await self._session.delete(row)
        return count


class SqlCourseRepository(CourseRepository):
    """SQLAlchemy async implementation of CourseRepository."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_id(self, course_id: str) -> Course | None:
        row = await self._session.get(CourseRow, course_id)
        return _row_to_course(row) if row else None

    async def get_by_code(self, course_code: str) -> Course | None:
        result = await self._session.execute(
            select(CourseRow).where(CourseRow.course_code == course_code)
        )
        row = result.scalar_one_or_none()
        return _row_to_course(row) if row else None

    async def get_all(self, tenant_id: str = "IUT") -> Sequence[Course]:
        result = await self._session.execute(
            select(CourseRow)
            .where(CourseRow.tenant_id == tenant_id)
            .order_by(CourseRow.course_code)
        )
        return [_row_to_course(r) for r in result.scalars().all()]

    async def save(self, course: Course) -> None:
        existing = await self._session.get(CourseRow, course.course_id)
        if existing:
            existing.course_code = course.course_code
            existing.title = course.title
            existing.aliases = course.aliases
        else:
            self._session.add(
                CourseRow(
                    course_id=course.course_id,
                    course_code=course.course_code,
                    title=course.title,
                    department_id=course.department_id or None,
                    aliases=course.aliases,
                    tenant_id=course.tenant_id,
                )
            )

    async def upsert(self, course: Course) -> Course:
        existing = await self.get_by_code(course.course_code)
        if existing:
            row = await self._session.get(CourseRow, existing.course_id)
            if row:
                row.title = course.title
                row.aliases = list(set(list(row.aliases or []) + course.aliases))
            return existing
        self._session.add(
            CourseRow(
                course_id=course.course_id,
                course_code=course.course_code,
                title=course.title,
                department_id=course.department_id or None,
                aliases=course.aliases,
                tenant_id=course.tenant_id,
            )
        )
        return course

    async def search_by_alias(self, raw_code: str) -> Course | None:
        """Search courses by alias using PostgreSQL array contains."""
        from sqlalchemy import any_ as sa_any_
        result = await self._session.execute(
            select(CourseRow).where(
                raw_code == sa_any_(CourseRow.aliases)  # type: ignore[arg-type]
            )
        )
        row = result.scalar_one_or_none()
        return _row_to_course(row) if row else None


class SqlQuestionRepository(QuestionRepository):
    """SQLAlchemy async implementation of QuestionRepository."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_id(self, question_id: str) -> Question | None:
        row = await self._session.get(QuestionRow, question_id)
        return _row_to_question(row) if row else None

    async def get_by_document(self, document_id: str) -> Sequence[Question]:
        result = await self._session.execute(
            select(QuestionRow).where(QuestionRow.document_id == document_id)
        )
        return [_row_to_question(r) for r in result.scalars().all()]

    async def bulk_insert(self, questions: Sequence[Question]) -> None:
        for q in questions:
            self._session.add(
                QuestionRow(
                    question_id=q.question_id,
                    chunk_id=q.chunk_id,
                    document_id=q.document_id,
                    version_id=q.version_id,
                    question_number=q.question_number,
                    text=q.text,
                    marks=q.marks,
                    page=q.page,
                    course_id=q.course_id,
                    course_code=q.course_code,
                    year=q.year,
                    semester=q.semester.value if q.semester else None,
                )
            )

    async def search(self, filters: dict[str, Any], limit: int = 20) -> Sequence[Question]:
        q = select(QuestionRow)
        if cc := filters.get("course_code"):
            q = q.where(QuestionRow.course_code == cc)
        if yr := filters.get("year"):
            q = q.where(QuestionRow.year == yr)
        if sem := filters.get("semester"):
            q = q.where(QuestionRow.semester == sem)
        result = await self._session.execute(q.limit(limit))
        return [_row_to_question(r) for r in result.scalars().all()]


class SqlSyncRunRepository(SyncRunRepository):
    """SQLAlchemy async implementation of SyncRunRepository."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_id(self, run_id: str) -> SyncRun | None:
        row = await self._session.get(SyncRunRow, run_id)
        return _row_to_sync_run(row) if row else None

    async def get_latest_for_source(self, source_id: str) -> SyncRun | None:
        result = await self._session.execute(
            select(SyncRunRow)
            .where(SyncRunRow.source_id == source_id)
            .order_by(SyncRunRow.started_at.desc())  # type: ignore[arg-type]
            .limit(1)
        )
        row = result.scalar_one_or_none()
        return _row_to_sync_run(row) if row else None

    async def save(self, run: SyncRun) -> None:
        self._session.add(
            SyncRunRow(
                run_id=run.run_id,
                source_id=run.source_id,
                started_at=run.started_at,
                finished_at=run.finished_at,
                status=run.status,
                documents_discovered=run.documents_discovered,
                documents_downloaded=run.documents_downloaded,
                documents_skipped=run.documents_skipped,
                documents_failed=run.documents_failed,
                error_summary=run.error_summary,
            )
        )

    async def update(self, run: SyncRun) -> None:
        await self._session.execute(
            update(SyncRunRow)
            .where(SyncRunRow.run_id == run.run_id)
            .values(
                finished_at=run.finished_at,
                status=run.status,
                documents_discovered=run.documents_discovered,
                documents_downloaded=run.documents_downloaded,
                documents_skipped=run.documents_skipped,
                documents_failed=run.documents_failed,
                error_summary=run.error_summary,
            )
        )
