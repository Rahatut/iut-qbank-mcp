"""Placeholder — replace with real tests as modules are implemented."""
import os

import pytest


@pytest.mark.unit
def test_package_importable() -> None:
    """The qbank package should be importable without errors."""
    import qbank  # noqa: F401


@pytest.mark.unit
def test_settings_loads() -> None:
    """Settings should load from environment without crashing."""
    os.environ.setdefault("POSTGRES_PASSWORD", "test")
    from qbank.infrastructure.config import get_settings

    settings = get_settings()
    assert settings.tenant_id == "IUT"
    assert settings.qdrant_active_collection == "iut_qbank_chunks_v1"
    assert settings.embedding_model == "BAAI/bge-small-en-v1.5"


@pytest.mark.unit
def test_postgres_dsn_format() -> None:
    """postgres_dsn property should produce a well-formed connection string."""
    os.environ.setdefault("POSTGRES_PASSWORD", "test")
    from qbank.infrastructure.config import get_settings

    dsn = get_settings().postgres_dsn
    assert dsn.startswith("postgresql+asyncpg://")
    assert "qbank" in dsn
