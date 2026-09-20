"""MCP tool definitions for the IUT QBank server. DEV-031 through DEV-035.

All tools follow the architecture rule:
    MCP Tool → Application Service → Retrieval Service → Infrastructure

No database or vector-search logic lives in this file.
"""

from __future__ import annotations

import logging
from typing import Annotated, Any

from fastmcp import FastMCP
from pydantic import Field

from apps.mcp_server.container import get_container
from qbank.infrastructure.vector.qdrant_store import SearchResult

logger = logging.getLogger(__name__)


def _result_to_dict(r: SearchResult) -> dict[str, Any]:
    """Serialise a SearchResult to a JSON-compatible dict. DEV-028."""
    return {
        "id": r.id,
        "text": r.text,
        "score": round(r.score, 4),
        "course_code": r.course_code,
        "year": r.year,
        "semester": r.semester,
        "page": r.page,
        "question_number": r.question_number,
        "department": r.department,
        "document_type": r.document_type,
        "source": {
            "document_id": r.document_id,
            "title": r.document_title,
            "url": r.document_url,
        },
    }


def register_tools(mcp: FastMCP) -> None:
    """Register all MCP tools on the FastMCP instance."""

    # ── DEV-031: search_questions ─────────────────────────────────────────────

    @mcp.tool()
    async def search_questions(
        query: Annotated[
            str,
            Field(
                description="Natural language search query, e.g. 'normalization in database systems'"
            ),
        ],
        course_code: Annotated[
            str | None, Field(description="Filter by course code, e.g. 'CSE3101'")
        ] = None,
        topic: Annotated[
            str | None, Field(description="Additional topic keyword to refine search")
        ] = None,
        year_from: Annotated[
            int | None, Field(description="Earliest year to include, e.g. 2020")
        ] = None,
        year_to: Annotated[
            int | None, Field(description="Latest year to include, e.g. 2025")
        ] = None,
        semester: Annotated[
            str | None, Field(description="Semester: Spring | Summer | Fall | Winter")
        ] = None,
        document_type: Annotated[
            str | None,
            Field(
                description="Document type: question_paper | syllabus | lecture_material | tutorial | assignment"
            ),
        ] = None,
        limit: Annotated[
            int, Field(description="Maximum number of results to return", ge=1, le=50)
        ] = 10,
    ) -> list[dict[str, Any]]:
        """Search for questions and content across IUT exam papers and course materials.

        Performs semantic vector search with optional metadata filters.
        Returns results with full provenance (course, year, semester, page, source URL).

        Example queries:
        - "process synchronization deadlock"
        - "Fourier transform frequency domain" with course_code="EEE2101"
        - "normalization 3NF BCNF" with year_from=2020, year_to=2024
        """
        container = get_container()
        year_range = None
        if year_from is not None or year_to is not None:
            year_range = (year_from or 2000, year_to or 2100)

        results = await container.retrieval_service.search_questions(
            query=query,
            course_code=course_code,
            topic=topic,
            year_range=year_range,
            semester=semester,
            document_type=document_type,
            limit=limit,
        )
        return [_result_to_dict(r) for r in results]

    # ── DEV-032: get_past_papers ──────────────────────────────────────────────

    @mcp.tool()
    async def get_past_papers(
        course_code: Annotated[str, Field(description="Course code, e.g. 'CSE4105'")],
        year_from: Annotated[int | None, Field(description="Earliest year, e.g. 2020")] = None,
        year_to: Annotated[int | None, Field(description="Latest year, e.g. 2025")] = None,
        semester: Annotated[
            str | None, Field(description="Semester: Spring | Summer | Fall | Winter")
        ] = None,
        limit: Annotated[int, Field(description="Maximum papers to return", ge=1, le=50)] = 20,
    ) -> list[dict[str, Any]]:
        """Retrieve past examination papers for a course.

        Returns paper metadata and direct source URLs. Use this to find what
        exam papers exist for a given course before diving into specific questions.

        Example:
        - course_code="CSE4105", year_from=2022, year_to=2025
        - course_code="EEE3101", semester="Winter"
        """
        from qbank.application.retrieval_service import PastPapersQuery

        container = get_container()
        paper_query = PastPapersQuery(
            course_code=course_code,
            year_min=year_from,
            year_max=year_to,
            semester=semester,
            limit=limit,
        )
        results = await container.retrieval_service.get_past_papers(paper_query)
        return [_result_to_dict(r) for r in results]

    # ── DEV-033: get_course_materials ─────────────────────────────────────────

    @mcp.tool()
    async def get_course_materials(
        course_code: Annotated[str, Field(description="Course code, e.g. 'CSE3101'")],
        material_type: Annotated[
            str | None,
            Field(description="Type: lecture_material | tutorial | assignment | syllabus"),
        ] = None,
        limit: Annotated[int, Field(description="Maximum results to return", ge=1, le=50)] = 20,
    ) -> list[dict[str, Any]]:
        """Retrieve available learning materials for a course.

        Returns lecture notes, tutorials, assignments, and other academic materials.
        Does not include exam papers (use get_past_papers for those).

        Example:
        - course_code="CSE3101" — all materials for the course
        - course_code="CSE3101", material_type="lecture_material"
        """
        container = get_container()
        results = await container.retrieval_service.get_course_materials(
            course_code=course_code,
            document_type=material_type,
            limit=limit,
        )
        return [_result_to_dict(r) for r in results]

    # ── DEV-034: get_course_syllabus ──────────────────────────────────────────

    @mcp.tool()
    async def get_course_syllabus(
        course_code: Annotated[str, Field(description="Course code, e.g. 'CSE3101'")],
    ) -> list[dict[str, Any]]:
        """Retrieve the syllabus for a specific course.

        Returns the canonical syllabus document including topics, credit hours,
        prerequisites, and learning outcomes where available.

        Example:
        - course_code="CSE4105" — Operating Systems syllabus
        """
        container = get_container()
        results = await container.retrieval_service.get_course_syllabus(course_code)
        return [_result_to_dict(r) for r in results]

    # ── DEV-035: get_question ─────────────────────────────────────────────────

    @mcp.tool()
    async def get_question(
        question_id: Annotated[
            str,
            Field(
                description="The unique ID of the question/chunk (from a previous search result)"
            ),
        ],
    ) -> dict[str, Any] | None:
        """Retrieve a specific question or content chunk by its ID.

        Use the 'id' field from search_questions results to fetch the full
        content and complete provenance for a specific item.

        Returns null if the question ID is not found.
        """
        container = get_container()
        result = await container.retrieval_service.get_by_id(question_id)
        if result is None:
            return None
        return _result_to_dict(result)

    # ── DEV-042: check_health ─────────────────────────────────────────────────

    @mcp.tool()
    async def check_health() -> dict[str, Any]:
        """Check system and dependency health (PostgreSQL, Qdrant, Object Storage).

        Returns overall status and individual status for each service dependency.
        """
        container = get_container()
        return await container.check_health()
