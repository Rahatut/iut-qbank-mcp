"""FastMCP server dependency injection and lifespan management. DEV-030.

Provides a single ApplicationContainer that wires up infrastructure
and injects the RetrievalService into MCP tool handlers.

The container is built once at server startup and torn down on shutdown.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from qbank.application.retrieval_service import RetrievalService
from qbank.infrastructure.config import Settings, get_settings
from qbank.infrastructure.db.engine import make_engine
from qbank.infrastructure.storage.object_storage import ObjectStorage, make_storage
from qbank.infrastructure.vector.qdrant_store import QdrantStore
from qbank.processing.embedding import SentenceTransformerProvider
from qbank.processing.interfaces import EmbeddingProvider

logger = logging.getLogger(__name__)


@dataclass
class AppContainer:
    """Holds all application-wide singletons for injection into MCP tools."""

    settings: Settings
    embedding_provider: EmbeddingProvider
    qdrant_store: QdrantStore
    retrieval_service: RetrievalService
    storage: ObjectStorage
    engine: AsyncEngine

    async def check_health(self) -> dict[str, Any]:
        """Perform comprehensive health checks across all components: DEV-042."""
        status: dict[str, Any] = {
            "status": "healthy",
            "postgres": "unknown",
            "qdrant": "unknown",
            "storage": "unknown",
        }

        # 1. PostgreSQL check
        try:
            async with self.engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
            status["postgres"] = "healthy"
        except Exception as exc:
            status["postgres"] = f"unhealthy: {exc}"
            status["status"] = "unhealthy"

        # 2. Qdrant check
        try:
            is_qdrant_healthy = await self.qdrant_store.health()
            status["qdrant"] = "healthy" if is_qdrant_healthy else "unhealthy"
            if not is_qdrant_healthy:
                status["status"] = "unhealthy"
        except Exception as exc:
            status["qdrant"] = f"unhealthy: {exc}"
            status["status"] = "unhealthy"

        # 3. Storage check
        try:
            test_key = ".health_check"
            await self.storage.put(test_key, b"ok")
            exists = await self.storage.exists(test_key)
            await self.storage.delete(test_key)
            status["storage"] = "healthy" if exists else "unhealthy"
        except Exception as exc:
            status["storage"] = f"unhealthy: {exc}"
            status["status"] = "unhealthy"

        return status


_container: AppContainer | None = None


def get_container() -> AppContainer:
    """Return the current application container. Raises if not initialised."""
    if _container is None:
        raise RuntimeError(
            "Application container is not initialised. Ensure the MCP server lifespan has started."
        )
    return _container


@asynccontextmanager
async def lifespan() -> AsyncIterator[AppContainer]:
    """Async context manager for server startup / shutdown.

    Usage in FastMCP:
        mcp = FastMCP("qbank", lifespan=lifespan)

    Startup:
      - Load settings
      - Initialise embedding provider
      - Connect to Qdrant; ensure collection exists
      - Build RetrievalService

    Shutdown:
      - Log teardown (future: close DB sessions, HTTP clients, etc.)
    """
    global _container

    settings = get_settings()
    logger.info("Starting IUT QBank MCP server (env=%s)", settings.environment)

    # Embedding provider — lazy model loading
    embedding_provider: EmbeddingProvider = SentenceTransformerProvider(
        model_name=settings.embedding_model,
        batch_size=settings.embedding_batch_size,
    )

    # Qdrant vector store
    qdrant_store = QdrantStore()
    try:
        await qdrant_store.ensure_collection()
        logger.info("Qdrant collection ready: %s", qdrant_store.collection)
    except Exception as exc:
        logger.warning(
            "Could not reach Qdrant at startup: %s. Search will fail until Qdrant is available.",
            exc,
        )

    # Object storage
    storage = make_storage(
        settings.storage_backend,
        local_path=settings.storage_local_path,
    )

    # Database engine
    engine = make_engine()

    retrieval_service = RetrievalService(
        embedding_provider=embedding_provider,
        qdrant_store=qdrant_store,
    )

    _container = AppContainer(
        settings=settings,
        embedding_provider=embedding_provider,
        qdrant_store=qdrant_store,
        retrieval_service=retrieval_service,
        storage=storage,
        engine=engine,
    )

    logger.info("IUT QBank MCP server ready")
    try:
        yield _container
    finally:
        logger.info("Shutting down IUT QBank MCP server")
        await engine.dispose()
        _container = None
