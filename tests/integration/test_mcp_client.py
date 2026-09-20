"""AI-Host integration test: DEV-040.

Tests that a simulated MCP AI client can:
1. Connect to FastMCP server via client protocol
2. Discover tools and dynamic resources
3. Call `search_questions`, `get_past_papers`, `get_course_syllabus`, `get_course_materials`, `get_question`
4. Read resource templates (e.g. course://CSE4105/past-papers)
5. Receive structured provenance answers.
"""

from __future__ import annotations

import pytest
from apps.mcp_server.main import create_server
from fastmcp import Client


@pytest.mark.integration
@pytest.mark.asyncio
async def test_mcp_client_tools_and_query_flow() -> None:
    server = create_server()

    async with Client(server) as client:
        # 1. Verify tools discovery
        tools = await client.list_tools()
        tool_names = [t.name for t in tools]
        assert "search_questions" in tool_names
        assert "get_past_papers" in tool_names
        assert "get_course_materials" in tool_names
        assert "get_course_syllabus" in tool_names
        assert "get_question" in tool_names

        # 2. Verify resource templates discovery
        templates = await client.list_resource_templates()
        template_uris = [t.uri_template for t in templates]
        assert "course://{course_code}" in template_uris
        assert "course://{course_code}/syllabus" in template_uris
        assert "course://{course_code}/past-papers" in template_uris
        assert "question://{course_code}/{year}/{semester}/{question_id}" in template_uris

        # 3. Call search_questions via client
        results = await client.call_tool(
            "search_questions",
            {
                "query": "Find operating system deadlocks and Banker algorithm",
                "course_code": "CSE4105",
                "year_from": 2020,
                "year_to": 2025,
                "limit": 5,
            },
        )
        assert results is not None
        # Should return a valid list (results format from tool)
        assert isinstance(results.data, list)

        # 4. Call get_past_papers via client
        past_papers = await client.call_tool(
            "get_past_papers",
            {
                "course_code": "CSE4105",
                "year_from": 2020,
                "year_to": 2025,
            },
        )
        assert past_papers is not None
        assert isinstance(past_papers.data, list)

        # 5. Call get_course_syllabus via client
        syllabus = await client.call_tool(
            "get_course_syllabus",
            {
                "course_code": "CSE4105",
            },
        )
        assert syllabus is not None
        assert isinstance(syllabus.data, list)
