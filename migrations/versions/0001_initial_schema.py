"""Initial schema migration. DEV-007.

Creates all V1 tables:
    departments, courses, sources, documents, document_versions,
    document_chunks, questions, sync_runs, processing_jobs

Generated manually (no live DB at generation time).
Revision: 0001_initial_schema
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0001_initial_schema"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── departments ───────────────────────────────────────────────────────────
    op.create_table(
        "departments",
        sa.Column("department_id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column("code", sa.String(20), nullable=False, unique=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("tenant_id", sa.String(50), nullable=False, server_default="IUT"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_index("ix_departments_tenant_code", "departments", ["tenant_id", "code"])

    # ── courses ───────────────────────────────────────────────────────────────
    op.create_table(
        "courses",
        sa.Column("course_id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column("course_code", sa.String(20), nullable=False),
        sa.Column("title", sa.String(255), nullable=False, server_default=""),
        sa.Column(
            "department_id",
            postgresql.UUID(as_uuid=False),
            sa.ForeignKey("departments.department_id"),
            nullable=True,
        ),
        sa.Column(
            "aliases",
            postgresql.ARRAY(sa.String),
            nullable=False,
            server_default="{}",
        ),
        sa.Column("tenant_id", sa.String(50), nullable=False, server_default="IUT"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.UniqueConstraint("tenant_id", "course_code", name="uq_courses_tenant_code"),
    )
    op.create_index("ix_courses_tenant_code", "courses", ["tenant_id", "course_code"])

    # ── sources ───────────────────────────────────────────────────────────────
    op.create_table(
        "sources",
        sa.Column("source_id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column("source_type", sa.String(50), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("base_url", sa.Text, nullable=False, server_default=""),
        sa.Column("repository_url", sa.Text, nullable=False, server_default=""),
        sa.Column("tenant_id", sa.String(50), nullable=False, server_default="IUT"),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default="true"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("last_synced_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default="{}",
        ),
    )

    # ── documents ─────────────────────────────────────────────────────────────
    op.create_table(
        "documents",
        sa.Column("document_id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column(
            "source_id",
            postgresql.UUID(as_uuid=False),
            sa.ForeignKey("sources.source_id"),
            nullable=False,
        ),
        sa.Column("remote_id", sa.Text, nullable=False, server_default=""),
        sa.Column("title", sa.Text, nullable=False, server_default=""),
        sa.Column("document_url", sa.Text, nullable=False, server_default=""),
        sa.Column("original_filename", sa.Text, nullable=True),
        sa.Column("document_type", sa.String(50), nullable=False, server_default="other"),
        sa.Column(
            "course_id",
            postgresql.UUID(as_uuid=False),
            sa.ForeignKey("courses.course_id"),
            nullable=True,
        ),
        sa.Column("course_code", sa.String(20), nullable=True),
        sa.Column("department", sa.String(20), nullable=True),
        sa.Column("year", sa.Integer, nullable=True),
        sa.Column("semester", sa.String(20), nullable=True),
        sa.Column("language", sa.String(10), nullable=False, server_default="en"),
        sa.Column("tenant_id", sa.String(50), nullable=False, server_default="IUT"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default="{}",
        ),
        sa.UniqueConstraint("source_id", "remote_id", name="uq_documents_source_remote"),
    )
    op.create_index("ix_documents_course_code", "documents", ["course_code"])
    op.create_index("ix_documents_year_semester", "documents", ["year", "semester"])
    op.create_index("ix_documents_tenant", "documents", ["tenant_id"])

    # ── document_versions ─────────────────────────────────────────────────────
    op.create_table(
        "document_versions",
        sa.Column("version_id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column(
            "document_id",
            postgresql.UUID(as_uuid=False),
            sa.ForeignKey("documents.document_id"),
            nullable=False,
        ),
        sa.Column("version_hash", sa.String(64), nullable=False),
        sa.Column("file_size_bytes", sa.BigInteger, nullable=False, server_default="0"),
        sa.Column("storage_key", sa.Text, nullable=False, server_default=""),
        sa.Column(
            "extraction_status",
            sa.String(20),
            nullable=False,
            server_default="pending",
        ),
        sa.Column("extraction_method", sa.String(20), nullable=True),
        sa.Column("text_quality_score", sa.Float, nullable=True),
        sa.Column("page_count", sa.Integer, nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default="{}",
        ),
        sa.UniqueConstraint("document_id", "version_hash", name="uq_versions_doc_hash"),
    )
    op.create_index("ix_versions_document_id", "document_versions", ["document_id"])

    # ── document_chunks ───────────────────────────────────────────────────────
    op.create_table(
        "document_chunks",
        sa.Column("chunk_id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column(
            "document_id",
            postgresql.UUID(as_uuid=False),
            sa.ForeignKey("documents.document_id"),
            nullable=False,
        ),
        sa.Column(
            "version_id",
            postgresql.UUID(as_uuid=False),
            sa.ForeignKey("document_versions.version_id"),
            nullable=False,
        ),
        sa.Column("page", sa.Integer, nullable=True),
        sa.Column("chunk_index", sa.Integer, nullable=False, server_default="0"),
        sa.Column("text", sa.Text, nullable=False, server_default=""),
        sa.Column("token_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("question_number", sa.String(50), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_index("ix_chunks_document_id", "document_chunks", ["document_id"])
    op.create_index("ix_chunks_version_id", "document_chunks", ["version_id"])

    # ── questions ─────────────────────────────────────────────────────────────
    op.create_table(
        "questions",
        sa.Column("question_id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column(
            "chunk_id",
            postgresql.UUID(as_uuid=False),
            sa.ForeignKey("document_chunks.chunk_id"),
            nullable=False,
        ),
        sa.Column(
            "document_id",
            postgresql.UUID(as_uuid=False),
            sa.ForeignKey("documents.document_id"),
            nullable=False,
        ),
        sa.Column(
            "version_id",
            postgresql.UUID(as_uuid=False),
            sa.ForeignKey("document_versions.version_id"),
            nullable=False,
        ),
        sa.Column("question_number", sa.String(50), nullable=False, server_default=""),
        sa.Column("text", sa.Text, nullable=False, server_default=""),
        sa.Column("marks", sa.Integer, nullable=True),
        sa.Column("page", sa.Integer, nullable=True),
        sa.Column(
            "course_id",
            postgresql.UUID(as_uuid=False),
            sa.ForeignKey("courses.course_id"),
            nullable=True,
        ),
        sa.Column("course_code", sa.String(20), nullable=True),
        sa.Column("year", sa.Integer, nullable=True),
        sa.Column("semester", sa.String(20), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_index("ix_questions_document_id", "questions", ["document_id"])
    op.create_index("ix_questions_course_code", "questions", ["course_code"])

    # ── sync_runs ─────────────────────────────────────────────────────────────
    op.create_table(
        "sync_runs",
        sa.Column("run_id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column(
            "source_id",
            postgresql.UUID(as_uuid=False),
            sa.ForeignKey("sources.source_id"),
            nullable=False,
        ),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="running"),
        sa.Column("documents_discovered", sa.Integer, nullable=False, server_default="0"),
        sa.Column("documents_downloaded", sa.Integer, nullable=False, server_default="0"),
        sa.Column("documents_skipped", sa.Integer, nullable=False, server_default="0"),
        sa.Column("documents_failed", sa.Integer, nullable=False, server_default="0"),
        sa.Column("error_summary", sa.Text, nullable=True),
    )
    op.create_index("ix_sync_runs_source_id", "sync_runs", ["source_id"])
    op.create_index("ix_sync_runs_started_at", "sync_runs", ["started_at"])

    # ── processing_jobs ───────────────────────────────────────────────────────
    op.create_table(
        "processing_jobs",
        sa.Column("job_id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column(
            "version_id",
            postgresql.UUID(as_uuid=False),
            sa.ForeignKey("document_versions.version_id"),
            nullable=False,
        ),
        sa.Column("stage", sa.String(50), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("attempt", sa.Integer, nullable=False, server_default="1"),
        sa.Column("error", sa.Text, nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_index("ix_jobs_version_stage", "processing_jobs", ["version_id", "stage"])
    op.create_index("ix_jobs_status", "processing_jobs", ["status"])


def downgrade() -> None:
    op.drop_table("processing_jobs")
    op.drop_table("sync_runs")
    op.drop_table("questions")
    op.drop_table("document_chunks")
    op.drop_table("document_versions")
    op.drop_table("documents")
    op.drop_table("sources")
    op.drop_table("courses")
    op.drop_table("departments")
