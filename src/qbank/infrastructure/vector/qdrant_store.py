"""Qdrant vector store integration. DEV-009.

Manages the iut_qbank_chunks_v1 collection with:
  - Configurable vector dimensions and cosine similarity
  - Rich payload for metadata filtering
  - Index versioning support (DEV-024)
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, ClassVar

from qdrant_client import AsyncQdrantClient
from qdrant_client.http.models import (
    Distance,
    FieldCondition,
    Filter,
    MatchValue,
    PayloadSchemaType,
    PointStruct,
    Range,
    ScoredPoint,
    VectorParams,
)

from qbank.infrastructure.config import get_settings

# ── Payload schema ────────────────────────────────────────────────────────────

@dataclass
class ChunkPayload:
    """Metadata stored alongside each vector in Qdrant.

    Matches the payload schema defined in DEV-009.
    All fields are also indexed for metadata filtering (DEV-027).
    """
    chunk_id: str
    document_id: str
    version_id: str
    course_id: str | None
    course_code: str | None
    department: str | None
    year: int | None
    semester: str | None
    document_type: str
    page: int | None
    question_number: str | None
    source_type: str
    language: str
    text: str                       # stored for result formatting
    document_title: str = ""
    document_url: str = ""
    tenant_id: str = "IUT"

    def to_dict(self) -> dict[str, Any]:
        return {k: v for k, v in self.__dict__.items() if v is not None}


@dataclass
class SearchFilter:
    """Structured filter for retrieval queries. DEV-027."""
    course_code: str | None = None
    department: str | None = None
    year_min: int | None = None
    year_max: int | None = None
    semester: str | None = None
    document_type: str | None = None
    question_number: str | None = None
    tenant_id: str = "IUT"

    def to_qdrant_filter(self) -> Filter | None:
        must: list[FieldCondition] = []

        must.append(FieldCondition(key="tenant_id", match=MatchValue(value=self.tenant_id)))

        if self.course_code:
            must.append(
                FieldCondition(key="course_code", match=MatchValue(value=self.course_code))
            )
        if self.department:
            must.append(
                FieldCondition(key="department", match=MatchValue(value=self.department))
            )
        if self.semester:
            must.append(FieldCondition(key="semester", match=MatchValue(value=self.semester)))
        if self.document_type:
            must.append(
                FieldCondition(key="document_type", match=MatchValue(value=self.document_type))
            )
        if self.question_number:
            must.append(
                FieldCondition(
                    key="question_number", match=MatchValue(value=self.question_number)
                )
            )
        if self.year_min is not None or self.year_max is not None:
            must.append(
                FieldCondition(
                    key="year",
                    range=Range(
                        gte=self.year_min,
                        lte=self.year_max,
                    ),
                )
            )

        if not must:
            return None
        return Filter(must=must)  # type: ignore[arg-type]


@dataclass
class SearchResult:
    """Standardized result from a retrieval query. DEV-028."""
    id: str
    text: str
    score: float
    course_code: str | None
    year: int | None
    semester: str | None
    page: int | None
    document_id: str
    document_title: str
    document_url: str
    question_number: str | None = None
    department: str | None = None
    document_type: str = "other"

    @classmethod
    def from_scored_point(cls, point: ScoredPoint) -> SearchResult:
        p = point.payload or {}
        return cls(
            id=str(point.id),
            text=p.get("text", ""),
            score=point.score,
            course_code=p.get("course_code"),
            year=p.get("year"),
            semester=p.get("semester"),
            page=p.get("page"),
            document_id=p.get("document_id", ""),
            document_title=p.get("document_title", ""),
            document_url=p.get("document_url", ""),
            question_number=p.get("question_number"),
            department=p.get("department"),
            document_type=p.get("document_type", "other"),
        )


# ── Qdrant client wrapper ─────────────────────────────────────────────────────

class QdrantStore:
    """Manages Qdrant operations for the qbank collection.

    Handles:
      - Collection creation with configurable vector dimensions
      - Payload indexing for fast metadata filtering
      - Upsert and search
      - Collection versioning (DEV-024)
    """

    # Payload fields to index for filtering
    INDEXED_FIELDS: ClassVar[list[tuple[str, PayloadSchemaType]]] = [
        ("course_code", PayloadSchemaType.KEYWORD),
        ("department", PayloadSchemaType.KEYWORD),
        ("year", PayloadSchemaType.INTEGER),
        ("semester", PayloadSchemaType.KEYWORD),
        ("document_type", PayloadSchemaType.KEYWORD),
        ("tenant_id", PayloadSchemaType.KEYWORD),
        ("question_number", PayloadSchemaType.KEYWORD),
    ]

    def __init__(self, client: AsyncQdrantClient | None = None) -> None:
        settings = get_settings()
        self._collection = settings.qdrant_active_collection
        self._dimension = settings.embedding_dimension
        self._client = client or AsyncQdrantClient(
            host=settings.qdrant_host,
            port=settings.qdrant_port,
            https=False,
            api_key=settings.qdrant_api_key,
        )

    @property
    def collection(self) -> str:
        return self._collection

    async def ensure_collection(self, collection: str | None = None) -> None:
        """Create the collection if it does not exist and add payload indexes."""
        name = collection or self._collection
        existing = await self._client.get_collections()
        names = [c.name for c in existing.collections]

        if name not in names:
            await self._client.create_collection(
                collection_name=name,
                vectors_config=VectorParams(
                    size=self._dimension,
                    distance=Distance.COSINE,
                ),
            )
            # Create payload indexes for fast metadata filtering
            for field_name, schema_type in self.INDEXED_FIELDS:
                await self._client.create_payload_index(
                    collection_name=name,
                    field_name=field_name,
                    field_schema=schema_type,
                )

    async def upsert(
        self,
        vectors: list[list[float]],
        payloads: list[ChunkPayload],
        collection: str | None = None,
    ) -> None:
        """Insert or update vectors with their payloads."""
        name = collection or self._collection
        points = [
            PointStruct(
                id=p.chunk_id,
                vector=v,
                payload=p.to_dict(),
            )
            for v, p in zip(vectors, payloads, strict=True)
        ]
        await self._client.upsert(collection_name=name, points=points)

    async def search(
        self,
        query_vector: list[float],
        search_filter: SearchFilter | None = None,
        limit: int = 10,
        collection: str | None = None,
    ) -> list[SearchResult]:
        """Perform a vector similarity search with optional metadata filtering."""
        name = collection or self._collection
        qdrant_filter = search_filter.to_qdrant_filter() if search_filter else None

        response = await self._client.query_points(
            collection_name=name,
            query=query_vector,
            query_filter=qdrant_filter,
            limit=limit,
            with_payload=True,
        )
        return [SearchResult.from_scored_point(r) for r in response.points]

    async def retrieve_by_id(self, point_id: str, collection: str | None = None) -> SearchResult | None:
        """Retrieve a single point by ID from Qdrant."""
        name = collection or self._collection
        try:
            points = await self._client.retrieve(
                collection_name=name,
                ids=[point_id],
                with_payload=True,
            )
            if not points:
                return None
            point = points[0]
            p = point.payload or {}
            return SearchResult(
                id=str(point.id),
                text=p.get("text", ""),
                score=1.0,
                course_code=p.get("course_code"),
                year=p.get("year"),
                semester=p.get("semester"),
                page=p.get("page"),
                document_id=p.get("document_id", ""),
                document_title=p.get("document_title", ""),
                document_url=p.get("document_url", ""),
                question_number=p.get("question_number"),
                department=p.get("department"),
                document_type=p.get("document_type", "other"),
            )
        except Exception:
            return None

    async def delete_by_document(self, document_id: str, collection: str | None = None) -> None:
        """Remove all vectors belonging to a document."""
        name = collection or self._collection
        await self._client.delete(
            collection_name=name,
            points_selector=Filter(  # type: ignore[arg-type]
                must=[FieldCondition(key="document_id", match=MatchValue(value=document_id))]
            ),
        )

    async def health(self) -> bool:
        """Return True if Qdrant is reachable."""
        try:
            await self._client.get_collections()
            return True
        except Exception:
            return False
