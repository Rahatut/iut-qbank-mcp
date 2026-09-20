"""Async SQLAlchemy engine and session factory."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from qbank.infrastructure.config import get_settings


def make_engine() -> AsyncEngine:
    settings = get_settings()
    return create_async_engine(
        settings.postgres_dsn,
        echo=(settings.environment.value == "dev"),
        pool_pre_ping=True,
        pool_size=10,
        max_overflow=20,
    )


def make_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)


# Module-level singletons — call make_engine() / make_session_factory()
# from your application startup code rather than importing these directly.
