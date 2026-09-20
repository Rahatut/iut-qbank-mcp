"""Central retrieval service. DEV-026, DEV-027, DEV-028.

The RetrievalService is the single point of contact for all search operations.
MCP tools MUST call this service — they must NOT query Qdrant or PostgreSQL directly.

Pipeline V1:
    query
     ↓
    embed (EmbeddingProvider)
     ↓
    Qdrant metadata filtering (SearchFilter)
     ↓
    vector search
     ↓
    top-k results
     ↓
    provenance formatting (SearchResult)

Future extensions (BM25 hybrid, reranking) slot in here without touching MCP.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

from qbank.infrastructure.vector.qdrant_store import (
    QdrantStore,
    SearchFilter,
    SearchResult,
)
from qbank.processing.interfaces import EmbeddingProvider

logger = logging.getLogger(__name__)


# ── Query DTOs ────────────────────────────────────────────────────────────────

@dataclass
class SearchQuery:
    """All parameters for a retrieval request. DEV-026, DEV-027.

    The MCP layer constructs this from tool arguments and passes it
    to RetrievalService. Nothing search-specific leaks into the MCP layer.
    """
    query: str
    course_code: str | None = None
    department: str | None = None
    year_min: int | None = None
    year_max: int | None = None
    semester: str | None = None
    document_type: str | None = None
    question_number: str | None = None
    limit: int = 10
    tenant_id: str = "IUT"

    # Normalise year_range shorthand
    @classmethod
    def from_year_range(
        cls,
        query: str,
        year_range: tuple[int, int] | None = None,
        **kwargs: object,
    ) -> SearchQuery:
        yr_min = yr_max = None
        if year_range:
            yr_min, yr_max = year_range
        return cls(query=query, year_min=yr_min, year_max=yr_max, **kwargs)  # type: ignore[arg-type]


@dataclass
class PastPapersQuery:
    """Query for listing past papers (non-semantic). DEV-032."""
    course_code: str
    year_min: int | None = None
    year_max: int | None = None
    semester: str | None = None
    limit: int = 20
    tenant_id: str = "IUT"


# ── Service ───────────────────────────────────────────────────────────────────

class RetrievalService:
    """Central retrieval service. Thin orchestration layer.

    Dependencies are injected — the service is independent of HTTP/MCP transport.

    Args:
        embedding_provider: Any EmbeddingProvider implementation (DEV-022).
        qdrant_store: QdrantStore wrapping the active collection (DEV-009).
    """

    def __init__(
        self,
        embedding_provider: EmbeddingProvider,
        qdrant_store: QdrantStore,
    ) -> None:
        self._embed = embedding_provider
        self._store = qdrant_store

    # ── Semantic search ───────────────────────────────────────────────────────

    async def search(self, query: SearchQuery) -> list[SearchResult]:
        """Execute semantic search with metadata filtering.

        DEV-026 pipeline:
          query → embed → filter → vector search → SearchResult list
        """
        logger.info(
            "search: query=%r course=%s year=[%s,%s] limit=%d",
            query.query[:80],
            query.course_code,
            query.year_min,
            query.year_max,
            query.limit,
        )

        # 1. Embed the query
        query_vector = self._embed.embed_query(query.query)

        # 2. Build metadata filter (DEV-027)
        search_filter = SearchFilter(
            course_code=query.course_code,
            department=query.department,
            year_min=query.year_min,
            year_max=query.year_max,
            semester=query.semester,
            document_type=query.document_type,
            question_number=query.question_number,
            tenant_id=query.tenant_id,
        )

        # 3. Vector search in Qdrant
        results = await self._store.search(
            query_vector=query_vector,
            search_filter=search_filter,
            limit=query.limit,
        )

        logger.info("search: returned %d results", len(results))
        return results

    async def search_questions(
        self,
        query: str,
        course_code: str | None = None,
        topic: str | None = None,
        year_range: tuple[int, int] | None = None,
        semester: str | None = None,
        document_type: str | None = None,
        limit: int = 10,
    ) -> list[SearchResult]:
        """Convenience wrapper for MCP tool DEV-031.

        Combines topic with query for richer semantic search.
        """
        combined_query = f"{query} {topic}" if topic else query
        yr_min = yr_max = None
        if year_range:
            yr_min, yr_max = year_range

        return await self.search(
            SearchQuery(
                query=combined_query,
                course_code=course_code,
                year_min=yr_min,
                year_max=yr_max,
                semester=semester,
                document_type=document_type or "question_paper",
                limit=limit,
            )
        )

    async def get_past_papers(self, query: PastPapersQuery) -> list[SearchResult]:
        """Retrieve past papers matching course/year/semester. DEV-032.

        Uses a generic query with hard metadata filters so results are
        document-level matches rather than chunk-level semantic matches.
        """
        return await self.search(
            SearchQuery(
                query=f"{query.course_code} question paper exam",
                course_code=query.course_code,
                year_min=query.year_min,
                year_max=query.year_max,
                semester=query.semester,
                document_type="question_paper",
                limit=query.limit,
                tenant_id=query.tenant_id,
            )
        )

    async def get_course_materials(
        self,
        course_code: str,
        document_type: str | None = None,
        limit: int = 20,
    ) -> list[SearchResult]:
        """Retrieve learning materials for a course. DEV-033."""
        return await self.search(
            SearchQuery(
                query=f"{course_code} course material lecture notes",
                course_code=course_code,
                document_type=document_type,
                limit=limit,
            )
        )

    async def get_course_syllabus(
        self, course_code: str
    ) -> list[SearchResult]:
        """Retrieve syllabus documents for a course. DEV-034."""
        return await self.search(
            SearchQuery(
                query=f"{course_code} syllabus course outline",
                course_code=course_code,
                document_type="syllabus",
                limit=5,
            )
        )

    async def get_by_id(self, chunk_id: str) -> SearchResult | None:
        """Retrieve a specific chunk/question by ID. DEV-035.

        Fetches directly from Qdrant payload without embedding.
        """
        return await self._store.retrieve_by_id(chunk_id)

    # ── Health ────────────────────────────────────────────────────────────────

    async def health(self) -> bool:
        """Return True if Qdrant is reachable."""
        return await self._store.health()
