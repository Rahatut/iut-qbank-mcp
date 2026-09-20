"""Unit tests for the retrieval service. DEV-026, DEV-027, DEV-028."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from qbank.application.retrieval_service import (
    PastPapersQuery,
    RetrievalService,
    SearchQuery,
)
from qbank.infrastructure.vector.qdrant_store import SearchResult


def _make_result(**kwargs: object) -> SearchResult:
    defaults: dict = {
        "id": "chunk-1",
        "text": "Sample question text",
        "score": 0.91,
        "course_code": "CSE3101",
        "year": 2024,
        "semester": "Winter",
        "page": 2,
        "document_id": "doc-1",
        "document_title": "CSE3101 Final 2024",
        "document_url": "https://dspace.iut.ac.bd/handle/123",
        "question_number": "3",
        "department": "CSE",
        "document_type": "question_paper",
    }
    defaults.update(kwargs)  # type: ignore[arg-type]
    return SearchResult(**defaults)  # type: ignore[arg-type]


class TestRetrievalService:
    """Unit tests for RetrievalService. Uses mocked infrastructure."""

    def setup_method(self) -> None:
        self.mock_embed = MagicMock()
        self.mock_embed.embed_query.return_value = [0.1] * 384
        self.mock_embed.embed_documents.return_value = [[0.1] * 384]

        self.mock_store = AsyncMock()
        self.mock_store.collection = "iut_qbank_chunks_v1"
        self.mock_store.search.return_value = [_make_result()]
        self.mock_store.health.return_value = True

        self.service = RetrievalService(
            embedding_provider=self.mock_embed,
            qdrant_store=self.mock_store,
        )

    @pytest.mark.asyncio
    async def test_search_calls_embed_then_qdrant(self) -> None:
        query = SearchQuery(query="normalization", course_code="CSE3101")
        results = await self.service.search(query)

        self.mock_embed.embed_query.assert_called_once_with("normalization")
        self.mock_store.search.assert_called_once()
        assert len(results) == 1
        assert results[0].course_code == "CSE3101"

    @pytest.mark.asyncio
    async def test_search_passes_filter_to_store(self) -> None:
        query = SearchQuery(
            query="deadlock",
            course_code="CSE4105",
            year_min=2020,
            year_max=2025,
            semester="Winter",
        )
        await self.service.search(query)

        call_kwargs = self.mock_store.search.call_args.kwargs
        sf = call_kwargs["search_filter"]
        assert sf.course_code == "CSE4105"
        assert sf.year_min == 2020
        assert sf.year_max == 2025
        assert sf.semester == "Winter"

    @pytest.mark.asyncio
    async def test_search_questions_combines_topic(self) -> None:
        await self.service.search_questions(
            query="semaphore",
            topic="mutex",
            course_code="CSE4105",
        )
        call_kwargs = self.mock_embed.embed_query.call_args.args[0]
        assert "semaphore" in call_kwargs
        assert "mutex" in call_kwargs

    @pytest.mark.asyncio
    async def test_search_questions_forces_question_paper_type(self) -> None:
        await self.service.search_questions(query="Fourier transform")
        call_kwargs = self.mock_store.search.call_args.kwargs
        sf = call_kwargs["search_filter"]
        assert sf.document_type == "question_paper"

    @pytest.mark.asyncio
    async def test_get_past_papers_uses_correct_doc_type(self) -> None:
        pq = PastPapersQuery(course_code="EEE2101", year_min=2020)
        await self.service.get_past_papers(pq)
        call_kwargs = self.mock_store.search.call_args.kwargs
        sf = call_kwargs["search_filter"]
        assert sf.document_type == "question_paper"
        assert sf.course_code == "EEE2101"
        assert sf.year_min == 2020

    @pytest.mark.asyncio
    async def test_get_course_syllabus_filters_by_type(self) -> None:
        await self.service.get_course_syllabus("CSE3101")
        call_kwargs = self.mock_store.search.call_args.kwargs
        sf = call_kwargs["search_filter"]
        assert sf.document_type == "syllabus"
        assert sf.course_code == "CSE3101"

    @pytest.mark.asyncio
    async def test_health_delegates_to_store(self) -> None:
        result = await self.service.health()
        self.mock_store.health.assert_called_once()
        assert result is True

    @pytest.mark.asyncio
    async def test_search_result_schema(self) -> None:
        """Verify the returned SearchResult matches DEV-028 schema."""
        query = SearchQuery(query="test")
        results = await self.service.search(query)
        r = results[0]
        # All fields from DEV-028 schema must be present
        assert hasattr(r, "id")
        assert hasattr(r, "text")
        assert hasattr(r, "score")
        assert hasattr(r, "course_code")
        assert hasattr(r, "year")
        assert hasattr(r, "semester")
        assert hasattr(r, "page")
        assert hasattr(r, "document_id")
        assert hasattr(r, "document_title")
        assert hasattr(r, "document_url")

    @pytest.mark.asyncio
    async def test_get_by_id_returns_none_on_empty(self) -> None:
        self.mock_store.retrieve_by_id.return_value = None
        result = await self.service.get_by_id("nonexistent-id")
        assert result is None
