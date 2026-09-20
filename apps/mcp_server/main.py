"""MCP Server entrypoint. DEV-030, DEV-037.

Architecture:
    Claude / ChatGPT / Cursor
          │
          ▼
     MCP Server  ← this file (thin)
          │
          ▼
  Application Services  ← src/qbank/application/
          │
          ▼
    Retrieval Service
          │
      ┌───┴────┐
      ▼         ▼
  PostgreSQL   Qdrant

Transport:
  - stdio  → for local development / Claude Desktop (default)
  - http   → for remote deployment (Streamable HTTP, not deprecated SSE)

Do NOT add retrieval or business logic here.
"""

from __future__ import annotations

import logging
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import structlog
import uvicorn
from fastmcp import FastMCP
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Mount, Route

from apps.mcp_server.container import AppContainer, lifespan
from apps.mcp_server.resources import register_resources
from apps.mcp_server.tools import register_tools
from qbank.infrastructure.config import get_settings


def _configure_logging(log_level: str = "INFO") -> None:
    """Configure structured JSON logging. DEV-043."""
    structlog.configure(
        processors=[
            structlog.stdlib.filter_by_level,
            structlog.stdlib.add_logger_name,
            structlog.stdlib.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(),
        ],
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stderr,
        level=getattr(logging, log_level.upper(), logging.INFO),
    )


@asynccontextmanager
async def _mcp_lifespan(server: FastMCP) -> AsyncIterator[AppContainer]:  # type: ignore[type-arg]
    """Wrap our lifespan CM for FastMCP's lifespan parameter."""
    async with lifespan() as container:
        yield container


def create_server() -> FastMCP:
    """Create and configure the FastMCP server instance."""
    settings = get_settings()
    _configure_logging(settings.log_level)

    mcp: FastMCP = FastMCP(
        name="IUT Question Bank",
        instructions=(
            "You have access to the IUT (Islamic University of Technology) question bank. "
            "Use search_questions to find past exam questions semantically. "
            "Use get_past_papers to browse exam papers by course and year. "
            "Use get_course_materials to find lecture notes and other materials. "
            "Use get_course_syllabus to retrieve course syllabi. "
            "All results include provenance: course code, year, semester, page, and source URL. "
            "Always cite the source URL and year when presenting retrieved content."
        ),
        lifespan=_mcp_lifespan,
    )

    register_tools(mcp)
    register_resources(mcp)

    return mcp


def main() -> None:
    """Start the MCP server. DEV-037.

    Transport is controlled by MCP_TRANSPORT env var:
      stdio  — for local development (Claude Desktop, Cursor, etc.)
      http   — for remote / hosted deployment (Streamable HTTP)

    stdio is the default and primary transport.
    """
    settings = get_settings()
    _configure_logging(settings.log_level)

    logger = logging.getLogger(__name__)
    mcp = create_server()

    transport = settings.mcp_transport.lower()

    if transport == "stdio":
        logger.info("Starting MCP server on stdio transport")
        mcp.run(transport="stdio")

    elif transport == "http":
        logger.info(
            "Starting MCP server on HTTP transport at %s:%d",
            settings.mcp_host,
            settings.mcp_port,
        )

        # ── /health endpoint for Render / load-balancer probes ────────────────
        async def health(request: Request) -> JSONResponse:
            return JSONResponse({"status": "ok"})

        # Wrap FastMCP's ASGI app so /health is served alongside /mcp
        mcp_asgi = mcp.http_app(path="/mcp")
        app = Starlette(
            routes=[
                Route("/health", health, methods=["GET"]),
                Mount("/", app=mcp_asgi),
            ]
        )

        uvicorn.run(
            app,
            host=settings.mcp_host,
            port=settings.mcp_port,
            log_level=settings.log_level.lower(),
        )

    else:
        logger.error("Unknown MCP_TRANSPORT=%r. Use 'stdio' or 'http'.", transport)
        sys.exit(1)


if __name__ == "__main__":
    main()
