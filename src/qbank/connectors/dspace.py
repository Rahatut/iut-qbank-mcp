"""IUT DSpace connector. DEV-011.

Implements the ContentSource interface for the IUT DSpace 7 REST API.
Discovers communities → collections → items → bitstreams.

DSpace 7 REST API reference:
    https://repository.iutoic-dhaka.edu/server/api
"""

from __future__ import annotations

import hashlib
import logging
import re
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from qbank.connectors.base import ConnectorCapabilities, ContentSource, RemoteDocument
from qbank.infrastructure.config import get_settings

logger = logging.getLogger(__name__)


@dataclass
class DSpaceItem:
    """Raw DSpace item metadata before conversion to RemoteDocument."""

    uuid: str
    name: str
    handle: str
    last_modified: str | None
    metadata: dict[str, Any] = field(default_factory=dict)
    bitstreams: list[dict[str, Any]] = field(default_factory=list)


class DSpaceConnector(ContentSource):
    """Connector for IUT DSpace 7 REST API.

    Discovers all accessible items and their primary PDF bitstreams.
    Uses the DSpace REST API (not HTML scraping) as required by DEV-011.

    Supports incremental sync via last_modified timestamps.
    """

    def __init__(
        self,
        base_url: str | None = None,
        api_version: str | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        settings = get_settings()
        self._base_url = (base_url or settings.dspace_base_url).rstrip("/")
        self._api_version = api_version or settings.dspace_api_version
        self._api_root = f"{self._base_url}/server/api"
        self._timeout = settings.ingestion_download_timeout_secs
        self._client = client

    @property
    def capabilities(self) -> ConnectorCapabilities:
        return ConnectorCapabilities(
            supports_incremental_sync=True,
            supports_checksum=True,
            supports_collections=True,
            supports_metadata=True,
        )

    @property
    def source_type(self) -> str:
        return "dspace"

    # ── HTTP helpers ──────────────────────────────────────────────────────────

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=self._timeout,
                follow_redirects=True,
                headers={"Accept": "application/json"},
            )
        return self._client

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
    async def _get_json(self, url: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        client = await self._get_client()
        response = await client.get(url, params=params)
        response.raise_for_status()
        return response.json()  # type: ignore[no-any-return]

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
    async def _get_bytes(self, url: str) -> bytes:
        client = await self._get_client()
        response = await client.get(url)
        response.raise_for_status()
        return response.content

    # ── Discovery ─────────────────────────────────────────────────────────────

    # Artifact patterns to exclude from academic ingestion
    _EXCLUDED_BITSTREAM_PATTERNS = re.compile(
        r"(\bturnitin\b|similarity\s*report|originality\s*report|^\d+%\s*thesis|\blicense\b)",
        re.IGNORECASE,
    )

    async def discover(self) -> AsyncIterator[RemoteDocument]:
        """Yield RemoteDocument for every valid academic PDF bitstream in DSpace.

        Walks: communities → collections → items → bitstreams
        Filters out non-academic artifacts (Turnitin reports, license files, etc.).
        """
        async for item in self._iter_all_items():
            pdf_bitstreams = [
                b
                for b in item.bitstreams
                if b.get("bundleName", "") == "ORIGINAL"
                and b.get("name", "").lower().endswith(".pdf")
            ]
            for bitstream in pdf_bitstreams:
                name = bitstream.get("name", "")
                if self._EXCLUDED_BITSTREAM_PATTERNS.search(name):
                    logger.info("Skipping non-academic artifact bitstream: %s", name)
                    continue

                doc = self._to_remote_document(item, bitstream)
                yield doc

    async def _iter_all_items(self) -> AsyncIterator[DSpaceItem]:
        """Page through all DSpace items via REST API."""
        page = 0
        page_size = 50
        while True:
            try:
                data = await self._get_json(
                    f"{self._api_root}/discover/search/objects",
                    params={
                        "dsoType": "item",
                        "page": page,
                        "size": page_size,
                        "embed": "bundles/bitstreams",
                    },
                )
            except Exception as exc:
                logger.error("DSpace item discovery failed at page %d: %s", page, exc)
                break

            search_result = data.get("_embedded", {}).get("searchResult", {})
            embedded = search_result.get("_embedded", {}).get("objects", [])

            if not embedded:
                break

            for obj in embedded:
                dso = obj.get("_embedded", {}).get("indexableObject", {})
                item = self._parse_item(dso)
                if item:
                    yield item

            page_info = search_result.get("page", {})
            total_pages = page_info.get("totalPages", 1)
            if page + 1 >= total_pages:
                break
            page += 1

    def _parse_item(self, dso: dict[str, Any]) -> DSpaceItem | None:
        """Parse a raw DSpace DSO dict into a DSpaceItem."""
        uuid = dso.get("uuid", "")
        name = dso.get("name", "")
        handle = dso.get("handle", "")
        if not uuid:
            return None

        # Extract metadata values
        metadata: dict[str, Any] = {}
        for key, values in (dso.get("metadata") or {}).items():
            metadata[key] = [v.get("value", "") for v in values]

        # Extract bitstreams from embedded bundles
        bitstreams: list[dict[str, Any]] = []
        bundles = (
            dso.get("_embedded", {}).get("bundles", {}).get("_embedded", {}).get("bundles", [])
        )
        for bundle in bundles:
            bundle_name = bundle.get("name", "")
            bs_list = (
                bundle.get("_embedded", {})
                .get("bitstreams", {})
                .get("_embedded", {})
                .get("bitstreams", [])
            )
            for bs in bs_list:
                bs["bundleName"] = bundle_name
                bitstreams.append(bs)

        last_modified = dso.get("lastModified")
        return DSpaceItem(
            uuid=uuid,
            name=name,
            handle=handle,
            last_modified=last_modified,
            metadata=metadata,
            bitstreams=bitstreams,
        )

    def _to_remote_document(self, item: DSpaceItem, bitstream: dict[str, Any]) -> RemoteDocument:
        """Convert a DSpaceItem + bitstream into a RemoteDocument.

        Scopes remote_id per bitstream to prevent collision when an item
        contains multiple PDF bitstreams.
        """
        bs_uuid = bitstream.get("uuid", "")
        download_url = f"{self._base_url}/server/api/core/bitstreams/{bs_uuid}/content"
        handle_url = f"{self._base_url}/handle/{item.handle}" if item.handle else ""
        checksum_info = bitstream.get("checkSum", {})
        checksum = checksum_info.get("value") if checksum_info else None

        last_modified: datetime | None = None
        if item.last_modified:
            try:
                last_modified = datetime.fromisoformat(item.last_modified.replace("Z", "+00:00"))
            except ValueError:
                pass

        bs_name = bitstream.get("name", "")
        # Provenance includes item-level metadata alongside specific bitstream attributes
        extended_meta: dict[str, Any] = {
            **item.metadata,
            "item_uuid": item.uuid,
            "item_name": item.name,
            "bitstream_uuid": bs_uuid,
            "filename": bs_name,
            "bundle_name": bitstream.get("bundleName", "ORIGINAL"),
        }

        return RemoteDocument(
            remote_id=f"{item.uuid}/{bs_uuid}" if bs_uuid else item.uuid,
            title=item.name or bs_name,
            document_url=download_url,
            handle_url=handle_url,
            checksum=checksum,
            last_modified=last_modified,
            file_size_bytes=bitstream.get("sizeBytes"),
            metadata=extended_meta,
            collection_path=[],  # TODO: populate from community/collection hierarchy
        )

    # ── Fetch & version ───────────────────────────────────────────────────────

    async def fetch(self, document: RemoteDocument) -> bytes:
        """Download raw PDF bytes for the given document."""
        logger.info("Downloading: %s (%s)", document.title, document.document_url)
        return await self._get_bytes(document.document_url)

    async def get_version(self, document: RemoteDocument) -> str:
        """Return a stable version string for change detection (DEV-012).

        Uses the remote checksum if available; otherwise falls back to
        a hash of the remote_id + last_modified.
        """
        if document.checksum:
            return document.checksum
        fingerprint = f"{document.remote_id}:{document.last_modified}"
        return hashlib.sha256(fingerprint.encode()).hexdigest()

    async def close(self) -> None:
        """Close the underlying HTTP client."""
        if self._client is not None:
            await self._client.aclose()
            self._client = None
