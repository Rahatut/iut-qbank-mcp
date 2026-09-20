"""Placeholder — replace with real tests as modules are implemented."""
import pytest


@pytest.mark.unit
def test_package_importable() -> None:
    """The qbank package should be importable."""
    import qbank  # noqa: F401


@pytest.mark.unit
def test_settings_loads() -> None:
    """Settings should load from environment without crashing."""
    import os

    os.environ.setdefault("POSTGRES_PASSWORD", "test")
    from qbank.infrastructure.config import get_settings

    settings = get_settings()
    assert settings.tenant_id == "IUT"
    assert settings.qdrant_active_collection == "iut_qbank_chunks_v1"
