"""Global pytest fixtures and configuration."""

from pathlib import Path

import pytest
from dotenv import load_dotenv

# Load .env file before running any tests
env_path = Path(__file__).parent.parent / ".env"
if env_path.exists():
    load_dotenv(dotenv_path=env_path, override=True)


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    """Derive a marker from the test directory.

    `make test-unit` selects with `-m unit`, but no test file declares
    markers, so the selection came back empty. Directory layout is the source
    of truth here, so derive the marker instead of trusting per-file pragmas.
    """
    for item in items:
        path = Path(str(item.fspath))
        # Match on any path segment: tests may run from a subdirectory.
        parts = path.parts

        if "e2e" in parts:
            marker = "e2e"
        elif "integration" in parts:
            marker = "integration"
        elif "unit" in parts:
            marker = "unit"
        else:
            continue

        if not any(m.name == marker for m in item.iter_markers()):
            item.add_marker(getattr(pytest.mark, marker))
