"""Object storage abstraction. DEV-010.

Defines the ObjectStorage interface so the ingestion pipeline is not
tied to a specific provider.

Implementations:
    LocalStorage   — filesystem, for development/testing
    S3Storage      — AWS S3 (future)
    MinIOStorage   — MinIO / S3-compatible (future)
"""
from __future__ import annotations

import hashlib
from abc import ABC, abstractmethod
from pathlib import Path


class ObjectStorage(ABC):
    """Abstract interface for storing and retrieving document files."""

    @abstractmethod
    async def put(self, key: str, data: bytes, content_type: str = "application/pdf") -> str:
        """Store data under key. Returns the storage key (may differ from input)."""
        ...

    @abstractmethod
    async def get(self, key: str) -> bytes:
        """Retrieve data by key. Raises KeyError if not found."""
        ...

    @abstractmethod
    async def exists(self, key: str) -> bool:
        """Return True if the key exists in storage."""
        ...

    @abstractmethod
    async def delete(self, key: str) -> None:
        """Delete the object at key. Silently succeeds if key absent."""
        ...

    @abstractmethod
    async def get_url(self, key: str) -> str:
        """Return a URL or file path that can be used to reference this object."""
        ...

    @staticmethod
    def make_key(source_id: str, document_id: str, version_hash: str, suffix: str = ".pdf") -> str:
        """Generate a deterministic storage key."""
        return f"{source_id}/{document_id}/{version_hash}{suffix}"

    @staticmethod
    def compute_hash(data: bytes) -> str:
        """SHA-256 hex digest of raw bytes."""
        return hashlib.sha256(data).hexdigest()


class LocalStorage(ObjectStorage):
    """Filesystem-backed storage. Safe for dev and test; not for production scale."""

    def __init__(self, base_path: str | Path) -> None:
        self._base = Path(base_path)
        self._base.mkdir(parents=True, exist_ok=True)

    def _resolve(self, key: str) -> Path:
        path = (self._base / key).resolve()
        # Guard against path traversal
        if not str(path).startswith(str(self._base.resolve())):
            raise ValueError(f"Invalid storage key: {key!r}")
        return path

    async def put(self, key: str, data: bytes, content_type: str = "application/pdf") -> str:
        path = self._resolve(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return key

    async def get(self, key: str) -> bytes:
        path = self._resolve(key)
        if not path.exists():
            raise KeyError(f"Storage key not found: {key!r}")
        return path.read_bytes()

    async def exists(self, key: str) -> bool:
        return self._resolve(key).exists()

    async def delete(self, key: str) -> None:
        path = self._resolve(key)
        if path.exists():
            path.unlink()

    async def get_url(self, key: str) -> str:
        return str(self._resolve(key))


def make_storage(backend: str, **kwargs: object) -> ObjectStorage:
    """Factory. Returns the correct ObjectStorage implementation for the given backend.

    Supported backends: "local"
    Future backends: "s3", "minio" — add implementations without changing callers.
    """
    if backend == "local":
        local_path = kwargs.get("local_path", "./data/storage")
        return LocalStorage(str(local_path))
    raise NotImplementedError(
        f"Storage backend {backend!r} is not yet implemented. "
        "Supported: 'local'. Planned: 's3', 'minio'."
    )
