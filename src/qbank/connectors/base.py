"""Source connector interface. DEV-011, DEV-049.

Defines the ContentSource protocol that all source connectors implement.
This ensures that adding DSpaceConnector, GitHubConnector, UploadConnector,
etc. never requires changes to the ingestion or retrieval logic.

Connector hierarchy:
    ContentSource (ABC)
     ├── DSpaceConnector      (DEV-011)
     ├── GitHubConnector      (future DEV-049)
     ├── UploadConnector      (future DEV-049)
     └── GoogleDriveConnector (future DEV-049)
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class RemoteDocument:
    """A document discovered by a connector, before downloading.

    Contains enough information to determine whether a download is needed
    (incremental sync, DEV-012).
    """

    remote_id: str  # connector-specific identifier (e.g. DSpace UUID)
    title: str
    document_url: str  # direct file download URL
    handle_url: str = ""  # canonical landing page URL
    checksum: str | None = None  # remote checksum if available
    last_modified: datetime | None = None
    file_size_bytes: int | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    collection_path: list[str] = field(default_factory=list)


@dataclass
class ConnectorCapabilities:
    """Declares what a connector supports."""

    supports_incremental_sync: bool = True
    supports_checksum: bool = False
    supports_collections: bool = True
    supports_metadata: bool = True


class ContentSource(ABC):
    """Abstract base class for all content source connectors. DEV-049.

    Implementations must be stateless between calls. Any sync state
    (e.g. last_sync_at) is managed by the SyncRun infrastructure.
    """

    @abstractmethod
    def discover(self) -> AsyncIterator[RemoteDocument]:
        """Yield all discoverable documents from this source.

        Should yield RemoteDocument objects without downloading file content.
        The caller decides which documents to fetch based on sync state.
        """
        ...

    @abstractmethod
    async def fetch(self, document: RemoteDocument) -> bytes:
        """Download and return the raw file bytes for a RemoteDocument."""
        ...

    @abstractmethod
    async def get_version(self, document: RemoteDocument) -> str:
        """Return a version string (checksum or timestamp) for change detection.

        Used by incremental sync (DEV-012) to skip unchanged documents.
        """
        ...

    @property
    @abstractmethod
    def capabilities(self) -> ConnectorCapabilities:
        """Return this connector's capabilities."""
        ...

    @property
    @abstractmethod
    def source_type(self) -> str:
        """Return the SourceType string for this connector."""
        ...
