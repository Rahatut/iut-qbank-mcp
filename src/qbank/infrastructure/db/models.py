"""SQLAlchemy ORM table definitions. DEV-007.

Defines all V1 relational tables. Domain models in qbank.domain.models
remain independent — these are purely infrastructure mapping classes.

Tables:
    departments
    courses
    sources
    documents
    document_versions
    document_chunks
    questions
    sync_runs
    processing_jobs
"""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy.sql import func


class Base(DeclarativeBase):
    pass


def _uuid() -> str:
    return str(uuid.uuid4())


# ── departments ───────────────────────────────────────────────────────────────

class DepartmentRow(Base):
    __tablename__ = "departments"

    department_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=_uuid
    )
    code: Mapped[str] = mapped_column(String(20), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    tenant_id: Mapped[str] = mapped_column(String(50), nullable=False, default="IUT")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    courses: Mapped[list[CourseRow]] = relationship("CourseRow", back_populates="department")

    __table_args__ = (
        Index("ix_departments_tenant_code", "tenant_id", "code"),
    )


# ── courses ───────────────────────────────────────────────────────────────────

class CourseRow(Base):
    """Canonical courses. Aliases stored as a PostgreSQL text array. DEV-005."""
    __tablename__ = "courses"

    course_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=_uuid
    )
    course_code: Mapped[str] = mapped_column(String(20), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    department_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=False), ForeignKey("departments.department_id"), nullable=True
    )
    aliases: Mapped[list[str]] = mapped_column(
        ARRAY(String), nullable=False, server_default="{}"
    )
    tenant_id: Mapped[str] = mapped_column(String(50), nullable=False, default="IUT")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    department: Mapped[DepartmentRow | None] = relationship(
        "DepartmentRow", back_populates="courses"
    )
    documents: Mapped[list[DocumentRow]] = relationship("DocumentRow", back_populates="course")

    __table_args__ = (
        UniqueConstraint("tenant_id", "course_code", name="uq_courses_tenant_code"),
        Index("ix_courses_tenant_code", "tenant_id", "course_code"),
    )


# ── sources ───────────────────────────────────────────────────────────────────

class SourceRow(Base):
    __tablename__ = "sources"

    source_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=_uuid
    )
    source_type: Mapped[str] = mapped_column(String(50), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    base_url: Mapped[str] = mapped_column(Text, nullable=False, default="")
    repository_url: Mapped[str] = mapped_column(Text, nullable=False, default="")
    tenant_id: Mapped[str] = mapped_column(String(50), nullable=False, default="IUT")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    metadata_: Mapped[dict] = mapped_column("metadata", JSONB, nullable=False, default=dict)

    documents: Mapped[list[DocumentRow]] = relationship("DocumentRow", back_populates="source")
    sync_runs: Mapped[list[SyncRunRow]] = relationship("SyncRunRow", back_populates="source")


# ── documents ─────────────────────────────────────────────────────────────────

class DocumentRow(Base):
    __tablename__ = "documents"

    document_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=_uuid
    )
    source_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("sources.source_id"), nullable=False
    )
    remote_id: Mapped[str] = mapped_column(Text, nullable=False, default="")
    title: Mapped[str] = mapped_column(Text, nullable=False, default="")
    document_url: Mapped[str] = mapped_column(Text, nullable=False, default="")
    original_filename: Mapped[str | None] = mapped_column(Text, nullable=True)
    document_type: Mapped[str] = mapped_column(String(50), nullable=False, default="other")
    course_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=False), ForeignKey("courses.course_id"), nullable=True
    )
    course_code: Mapped[str | None] = mapped_column(String(20), nullable=True)
    department: Mapped[str | None] = mapped_column(String(20), nullable=True)
    year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    semester: Mapped[str | None] = mapped_column(String(20), nullable=True)
    language: Mapped[str] = mapped_column(String(10), nullable=False, default="en")
    tenant_id: Mapped[str] = mapped_column(String(50), nullable=False, default="IUT")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
    metadata_: Mapped[dict] = mapped_column("metadata", JSONB, nullable=False, default=dict)

    source: Mapped[SourceRow] = relationship("SourceRow", back_populates="documents")
    course: Mapped[CourseRow | None] = relationship("CourseRow", back_populates="documents")
    versions: Mapped[list[DocumentVersionRow]] = relationship(
        "DocumentVersionRow", back_populates="document"
    )
    chunks: Mapped[list[DocumentChunkRow]] = relationship(
        "DocumentChunkRow", back_populates="document"
    )

    __table_args__ = (
        UniqueConstraint("source_id", "remote_id", name="uq_documents_source_remote"),
        Index("ix_documents_course_code", "course_code"),
        Index("ix_documents_year_semester", "year", "semester"),
        Index("ix_documents_tenant", "tenant_id"),
    )


# ── document_versions ─────────────────────────────────────────────────────────

class DocumentVersionRow(Base):
    """Tracks each unique version of a document by content hash. DEV-012."""
    __tablename__ = "document_versions"

    version_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=_uuid
    )
    document_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("documents.document_id"), nullable=False
    )
    version_hash: Mapped[str] = mapped_column(String(64), nullable=False)  # SHA-256
    file_size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    storage_key: Mapped[str] = mapped_column(Text, nullable=False, default="")
    extraction_status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    extraction_method: Mapped[str | None] = mapped_column(String(20), nullable=True)
    text_quality_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    page_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    metadata_: Mapped[dict] = mapped_column("metadata", JSONB, nullable=False, default=dict)

    document: Mapped[DocumentRow] = relationship("DocumentRow", back_populates="versions")
    chunks: Mapped[list[DocumentChunkRow]] = relationship(
        "DocumentChunkRow", back_populates="version"
    )

    __table_args__ = (
        UniqueConstraint("document_id", "version_hash", name="uq_versions_doc_hash"),
        Index("ix_versions_document_id", "document_id"),
    )


# ── document_chunks ───────────────────────────────────────────────────────────

class DocumentChunkRow(Base):
    """Segments of text indexed in Qdrant. DEV-020."""
    __tablename__ = "document_chunks"

    chunk_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=_uuid
    )
    document_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("documents.document_id"), nullable=False
    )
    version_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("document_versions.version_id"), nullable=False
    )
    page: Mapped[int | None] = mapped_column(Integer, nullable=True)
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    token_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    question_number: Mapped[str | None] = mapped_column(String(50), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    document: Mapped[DocumentRow] = relationship("DocumentRow", back_populates="chunks")
    version: Mapped[DocumentVersionRow] = relationship(
        "DocumentVersionRow", back_populates="chunks"
    )

    __table_args__ = (
        Index("ix_chunks_document_id", "document_id"),
        Index("ix_chunks_version_id", "version_id"),
    )


# ── questions ─────────────────────────────────────────────────────────────────

class QuestionRow(Base):
    """Structured questions extracted from chunks. DEV-021."""
    __tablename__ = "questions"

    question_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=_uuid
    )
    chunk_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("document_chunks.chunk_id"), nullable=False
    )
    document_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("documents.document_id"), nullable=False
    )
    version_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("document_versions.version_id"), nullable=False
    )
    question_number: Mapped[str] = mapped_column(String(50), nullable=False, default="")
    text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    marks: Mapped[int | None] = mapped_column(Integer, nullable=True)
    page: Mapped[int | None] = mapped_column(Integer, nullable=True)
    course_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=False), ForeignKey("courses.course_id"), nullable=True
    )
    course_code: Mapped[str | None] = mapped_column(String(20), nullable=True)
    year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    semester: Mapped[str | None] = mapped_column(String(20), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        Index("ix_questions_document_id", "document_id"),
        Index("ix_questions_course_code", "course_code"),
    )


# ── sync_runs ─────────────────────────────────────────────────────────────────

class SyncRunRow(Base):
    """Tracks each synchronization run from a source. DEV-013."""
    __tablename__ = "sync_runs"

    run_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=_uuid
    )
    source_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("sources.source_id"), nullable=False
    )
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="running")
    documents_discovered: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    documents_downloaded: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    documents_skipped: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    documents_failed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_summary: Mapped[str | None] = mapped_column(Text, nullable=True)

    source: Mapped[SourceRow] = relationship("SourceRow", back_populates="sync_runs")

    __table_args__ = (
        Index("ix_sync_runs_source_id", "source_id"),
        Index("ix_sync_runs_started_at", "started_at"),
    )


# ── processing_jobs ───────────────────────────────────────────────────────────

class ProcessingJobRow(Base):
    """Tracks per-document processing state for retries and monitoring."""
    __tablename__ = "processing_jobs"

    job_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=_uuid
    )
    version_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("document_versions.version_id"), nullable=False
    )
    stage: Mapped[str] = mapped_column(String(50), nullable=False)
    # e.g. extract | ocr | metadata | chunk | embed | index
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    attempt: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    __table_args__ = (
        Index("ix_jobs_version_stage", "version_id", "stage"),
        Index("ix_jobs_status", "status"),
    )
