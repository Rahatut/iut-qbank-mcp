"""MCP resource definitions. DEV-036.

Resources are read-only, URI-addressable entities that AI clients can
read directly (like files). They complement tools which perform actions.

Resource URIs:
    course://{course_code}                           — course metadata
    course://{course_code}/syllabus                  — syllabus content
    course://{course_code}/materials                 — available materials
    course://{course_code}/past-papers               — exam paper listing
    question://{course_code}/{year}/{semester}/{id}  — specific question
    document://{document_id}                         — document metadata

Only URIs backed by real canonical entities are exposed (DEV-036).
"""

from __future__ import annotations

import logging
from typing import Any

from fastmcp import FastMCP

from apps.mcp_server.container import get_container
from qbank.application.retrieval_service import PastPapersQuery, SearchQuery

logger = logging.getLogger(__name__)


def register_resources(mcp: FastMCP) -> None:
    """Register all MCP resources on the FastMCP instance."""

    # ── course://{course_code} ─────────────────────────────────────────────

    @mcp.resource("course://{course_code}")
    async def course_overview(course_code: str) -> dict[str, Any]:
        """Overview of a course: available materials, papers, and metadata.

        URI: course://CSE3101
        """
        container = get_container()

        # Fetch syllabus, materials, and recent papers concurrently
        import asyncio

        syllabus_task = container.retrieval_service.get_course_syllabus(course_code)
        materials_task = container.retrieval_service.get_course_materials(course_code, limit=5)
        papers_task = container.retrieval_service.get_past_papers(
            PastPapersQuery(course_code=course_code, limit=5)
        )
        syllabus, materials, papers = await asyncio.gather(
            syllabus_task, materials_task, papers_task
        )

        return {
            "course_code": course_code,
            "has_syllabus": len(syllabus) > 0,
            "materials_count": len(materials),
            "recent_papers": [
                {
                    "title": r.document_title,
                    "year": r.year,
                    "semester": r.semester,
                    "url": r.document_url,
                }
                for r in papers
            ],
            "syllabus_snippet": syllabus[0].text[:500] if syllabus else None,
        }

    # ── course://{course_code}/syllabus ────────────────────────────────────

    @mcp.resource("course://{course_code}/syllabus")
    async def course_syllabus(course_code: str) -> dict[str, Any]:
        """Full syllabus content for a course.

        URI: course://CSE3101/syllabus
        """
        container = get_container()
        results = await container.retrieval_service.get_course_syllabus(course_code)
        if not results:
            return {"course_code": course_code, "found": False, "content": None}
        top = results[0]
        return {
            "course_code": course_code,
            "found": True,
            "content": top.text,
            "source": {
                "document_id": top.document_id,
                "title": top.document_title,
                "url": top.document_url,
            },
        }

    # ── course://{course_code}/materials ────────────────────────────────────

    @mcp.resource("course://{course_code}/materials")
    async def course_materials(course_code: str) -> dict[str, Any]:
        """List of available learning materials for a course.

        URI: course://CSE3101/materials
        """
        container = get_container()
        results = await container.retrieval_service.get_course_materials(course_code, limit=30)
        # Deduplicate by document_id
        seen: set[str] = set()
        docs: list[dict[str, Any]] = []
        for r in results:
            if r.document_id not in seen:
                seen.add(r.document_id)
                docs.append(
                    {
                        "document_id": r.document_id,
                        "title": r.document_title,
                        "document_type": r.document_type,
                        "url": r.document_url,
                    }
                )
        return {
            "course_code": course_code,
            "materials": docs,
            "count": len(docs),
        }

    # ── course://{course_code}/past-papers ─────────────────────────────────

    @mcp.resource("course://{course_code}/past-papers")
    async def course_past_papers(course_code: str) -> dict[str, Any]:
        """List of all past examination papers for a course.

        URI: course://CSE4105/past-papers
        """
        container = get_container()
        results = await container.retrieval_service.get_past_papers(
            PastPapersQuery(course_code=course_code, limit=50)
        )
        # Deduplicate by document_id; keep best score per document
        seen: dict[str, dict[str, Any]] = {}
        for r in results:
            if r.document_id not in seen:
                seen[r.document_id] = {
                    "document_id": r.document_id,
                    "title": r.document_title,
                    "year": r.year,
                    "semester": r.semester,
                    "url": r.document_url,
                }
        papers = sorted(
            seen.values(),
            key=lambda x: (x.get("year") or 0, x.get("semester") or ""),
            reverse=True,
        )
        return {
            "course_code": course_code,
            "papers": papers,
            "count": len(papers),
        }

    # ── question://{course_code}/{year}/{semester}/{question_id} ───────────

    @mcp.resource("question://{course_code}/{year}/{semester}/{question_id}")
    async def question_by_id(
        course_code: str, year: str, semester: str, question_id: str
    ) -> dict[str, Any] | None:
        """Retrieve a specific question with its full provenance.

        URI: question://CSE4105/2023/Winter/abc123
        """
        container = get_container()
        result = await container.retrieval_service.get_by_id(question_id)
        if result is None:
            return None
        return {
            "id": result.id,
            "text": result.text,
            "course_code": result.course_code,
            "year": result.year,
            "semester": result.semester,
            "page": result.page,
            "question_number": result.question_number,
            "source": {
                "document_id": result.document_id,
                "title": result.document_title,
                "url": result.document_url,
            },
        }

    # ── document://{document_id} ────────────────────────────────────────────

    @mcp.resource("document://{document_id}")
    async def document_by_id(document_id: str) -> dict[str, Any]:
        """Retrieve metadata for a specific document.

        URI: document://abc-123-def
        Returns document metadata. To search within a document use search_questions.
        """
        container = get_container()
        # Search for content from this specific document
        results = await container.retrieval_service.search(
            SearchQuery(
                query=document_id,
                limit=1,
            )
        )
        # Find matching document from any result
        for r in results:
            if r.document_id == document_id:
                return {
                    "document_id": r.document_id,
                    "title": r.document_title,
                    "url": r.document_url,
                    "course_code": r.course_code,
                    "year": r.year,
                    "semester": r.semester,
                    "document_type": r.document_type,
                    "department": r.department,
                }
        return {
            "document_id": document_id,
            "found": False,
        }
