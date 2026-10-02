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
from qbank.application.response_budget import (
    empty_notice,
    results_payload,
    single_result_to_dict,
)

logger = logging.getLogger(__name__)

# Guidance returned instead of a bare [] so the model can distinguish an
# index gap from an over-restrictive filter and adjust its next call.
_NO_RESULTS_HINT = (
    "No results matched. The index may not contain this course or topic yet, "
    "or the filters are too narrow. Try: drop document_type, widen the year "
    "range, search by department code (e.g. 'CSE') instead of a course code, "
    "or call check_health to verify the index is reachable."
)


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
            str | None,
            Field(
                description=(
                    "Filter by course code, e.g. 'CSE3101'. Normalised automatically, "
                    "so 'CSE 3101' and 'cse-3101' also match."
                )
            ),
        ] = None,
        department: Annotated[
            str | None,
            Field(
                description=(
                    "Filter by department code, e.g. 'CSE', 'EEE', 'MAT'. "
                    "Many question papers are indexed per department, not per course."
                )
            ),
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
            int,
            Field(
                description=(
                    "Maximum number of results to return. "
                    "Each result's text is truncated to stay within the context budget; "
                    "use get_question with the returned id for the full text."
                ),
                ge=1,
                le=25,
            ),
        ] = 8,
    ) -> list[dict[str, Any]]:
        """Search for questions and content across IUT exam papers and course materials.

        Performs semantic vector search with optional metadata filters.
        Returns results with provenance (course, year, semester, page, source URL).

        Filtering is optional — omitting document_type searches all indexed
        material. Course codes are auto-normalised ("CSE 3101" matches "CSE3101").

        Results carry `truncated` and `original_chars`. When `truncated` is true,
        call get_question with that result's `id` to read the full text.

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
            department=department,
            year_range=year_range,
            semester=semester,
            document_type=document_type,
            limit=limit,
        )
        if not results:
            return empty_notice(_NO_RESULTS_HINT)
        return results_payload(results)

    # ── DEV-032: get_past_papers ──────────────────────────────────────────────

    @mcp.tool()
    async def get_past_papers(
        course_code: Annotated[
            str | None, Field(description="Course code, e.g. 'CSE4105'. Optional.")
        ] = None,
        department: Annotated[
            str | None,
            Field(
                description=(
                    "Department code, e.g. 'CSE'. Use this when the papers are "
                    "indexed per department rather than per course."
                )
            ),
        ] = None,
        year_from: Annotated[int | None, Field(description="Earliest year, e.g. 2020")] = None,
        year_to: Annotated[int | None, Field(description="Latest year, e.g. 2025")] = None,
        semester: Annotated[
            str | None, Field(description="Semester: Spring | Summer | Fall | Winter")
        ] = None,
        limit: Annotated[int, Field(description="Maximum papers to return", ge=1, le=25)] = 15,
    ) -> list[dict[str, Any]]:
        """Retrieve past examination papers for a course or department.

        Returns one entry per paper (not per page), with metadata and a direct
        source URL. Use this to find which exam papers exist before diving into
        specific questions, then use search_questions to search inside them.

        Example:
        - course_code="CSE4105", year_from=2022, year_to=2025
        - department="CSE", semester="Winter"
        """
        from qbank.application.retrieval_service import PastPapersQuery

        if not course_code and not department:
            return empty_notice(
                "get_past_papers requires course_code or department. "
                "Example: department='CSE' to list all CSE exam papers."
            )

        container = get_container()
        paper_query = PastPapersQuery(
            course_code=course_code,
            department=department,
            year_min=year_from,
            year_max=year_to,
            semester=semester,
            limit=limit,
        )
        results = await container.retrieval_service.get_past_papers(paper_query)
        if not results:
            return empty_notice(
                "No past papers matched. Widen the year range, drop the semester "
                "filter, or search by department instead of a specific course code."
            )
        return results_payload(results, total=6000)

    # ── DEV-033: get_course_materials ─────────────────────────────────────────

    @mcp.tool()
    async def get_course_materials(
        course_code: Annotated[
            str | None, Field(description="Course code, e.g. 'CSE3101'. Optional.")
        ] = None,
        department: Annotated[
            str | None, Field(description="Department code, e.g. 'CSE'. Optional.")
        ] = None,
        material_type: Annotated[
            str | None,
            Field(description="Type: lecture_material | tutorial | assignment | syllabus"),
        ] = None,
        limit: Annotated[int, Field(description="Maximum results to return", ge=1, le=25)] = 15,
    ) -> list[dict[str, Any]]:
        """Retrieve available learning materials for a course or department.

        Returns lecture notes, tutorials, assignments, and other academic
        materials, one entry per document. Does not include exam papers
        (use get_past_papers for those).

        Example:
        - course_code="CSE3101" — all materials for the course
        - department="CSE", material_type="lecture_material"
        """
        if not course_code and not department:
            return empty_notice(
                "get_course_materials requires course_code or department. "
                "Example: department='CSE' to list CSE learning materials."
            )

        container = get_container()
        results = await container.retrieval_service.get_course_materials(
            course_code=course_code,
            document_type=material_type,
            department=department,
            limit=limit,
        )
        if not results:
            return empty_notice(
                "No course materials matched. Try dropping material_type, or search "
                "by department instead of a specific course code."
            )
        return results_payload(results, total=6000)

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
        if not results:
            return empty_notice(
                f"No syllabus indexed for {course_code}. The IUT repository "
                "contains very few syllabi; try search_questions instead."
            )
        return results_payload(results, total=6000)

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

        Use the 'id' field from a search_questions result to fetch the full
        content and complete provenance for a specific item. This is the
        follow-up call for any result marked `truncated`.

        Returns null if the question ID is not found.
        """
        container = get_container()
        result = await container.retrieval_service.get_by_id(question_id)
        if result is None:
            return None
        return single_result_to_dict(result)

    # ── DEV-042: check_health ─────────────────────────────────────────────────

    @mcp.tool()
    async def check_health() -> dict[str, Any]:
        """Check system and dependency health (PostgreSQL, Qdrant, Object Storage).

        Returns overall status and individual status for each service dependency.
        """
        container = get_container()
        return await container.check_health()
