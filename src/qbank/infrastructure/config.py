"""Centralized configuration using pydantic-settings.

All settings are loaded from environment variables.
No secrets or configuration is hardcoded in source.
"""
from __future__ import annotations

import os
from enum import StrEnum
from functools import lru_cache

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Environment(StrEnum):
    DEV = "dev"
    TEST = "test"
    PROD = "prod"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── Environment ──────────────────────────────────────────────────────────
    environment: Environment = Field(default=Environment.DEV, alias="APP_ENV")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")

    # ── PostgreSQL ────────────────────────────────────────────────────────────
    postgres_host: str = Field(default="localhost", alias="POSTGRES_HOST")
    postgres_port: int = Field(default=5432, alias="POSTGRES_PORT")
    postgres_db: str = Field(default="qbank", alias="POSTGRES_DB")
    postgres_user: str = Field(default="qbank", alias="POSTGRES_USER")
    postgres_password: str = Field(default="", alias="POSTGRES_PASSWORD")

    @property
    def postgres_dsn(self) -> str:
        return (
            f"postgresql+asyncpg://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    @property
    def postgres_dsn_sync(self) -> str:
        """Synchronous DSN for Alembic migrations."""
        return (
            f"postgresql+psycopg2://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    # ── Qdrant ────────────────────────────────────────────────────────────────
    qdrant_host: str = Field(default="localhost", alias="QDRANT_HOST")
    qdrant_port: int = Field(default=6333, alias="QDRANT_PORT")
    qdrant_api_key: str | None = Field(default=None, alias="QDRANT_API_KEY")
    qdrant_active_collection: str = Field(
        default="iut_qbank_chunks_v1", alias="QDRANT_ACTIVE_COLLECTION"
    )

    # ── Object Storage ────────────────────────────────────────────────────────
    # Backend: local | s3 | minio
    storage_backend: str = Field(default="local", alias="STORAGE_BACKEND")
    storage_local_path: str = Field(default="./data/storage", alias="STORAGE_LOCAL_PATH")
    storage_bucket: str = Field(default="qbank-documents", alias="STORAGE_BUCKET")
    storage_endpoint_url: str | None = Field(default=None, alias="STORAGE_ENDPOINT_URL")
    storage_access_key: str | None = Field(default=None, alias="STORAGE_ACCESS_KEY")
    storage_secret_key: str | None = Field(default=None, alias="STORAGE_SECRET_KEY")

    # ── Embedding ─────────────────────────────────────────────────────────────
    embedding_provider: str = Field(
        default="sentence_transformers", alias="EMBEDDING_PROVIDER"
    )
    embedding_model: str = Field(
        default="BAAI/bge-small-en-v1.5", alias="EMBEDDING_MODEL"
    )
    embedding_dimension: int = Field(default=384, alias="EMBEDDING_DIMENSION")
    embedding_batch_size: int = Field(default=32, alias="EMBEDDING_BATCH_SIZE")

    # ── MCP Transport ─────────────────────────────────────────────────────────
    # Transport: stdio | http
    mcp_transport: str = Field(default="stdio", alias="MCP_TRANSPORT")
    mcp_host: str = Field(default="0.0.0.0", alias="MCP_HOST")
    # Render injects PORT; fall back to MCP_PORT, then 8000.
    mcp_port: int = Field(default=8000, alias="MCP_PORT")

    @field_validator("mcp_port", mode="before")
    @classmethod
    def resolve_render_port(cls, v: object) -> object:
        """Prefer Render's PORT env var over MCP_PORT."""
        render_port = os.environ.get("PORT")
        if render_port:
            return int(render_port)
        return v

    # ── Ingestion ─────────────────────────────────────────────────────────────
    dspace_base_url: str = Field(
        default="https://repository.iutoic-dhaka.edu", alias="DSPACE_BASE_URL"
    )
    dspace_community_id: str = Field(
        default="cdf3c86c-6c9e-4def-a892-0b7b0591280f", alias="DSPACE_COMMUNITY_ID"
    )
    dspace_api_version: str = Field(default="7", alias="DSPACE_API_VERSION")
    ingestion_max_concurrent_downloads: int = Field(
        default=4, alias="INGESTION_MAX_CONCURRENT_DOWNLOADS"
    )
    ingestion_download_timeout_secs: int = Field(
        default=120, alias="INGESTION_DOWNLOAD_TIMEOUT_SECS"
    )
    ocr_enabled: bool = Field(default=True, alias="OCR_ENABLED")
    ocr_language: str = Field(default="eng", alias="OCR_LANGUAGE")

    # ── Multi-tenancy ─────────────────────────────────────────────────────────
    # Future: IUT | BUET | KUET | DU — see DEV-052
    tenant_id: str = Field(default="IUT", alias="TENANT_ID")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return a cached singleton Settings instance."""
    return Settings()
