# IUT Question Bank MCP Server

A retrieval-augmented MCP server providing semantic search over the IUT academic question bank, sourced from [IUT DSpace](https://repository.iutoic-dhaka.edu).

## Architecture

```
Claude / ChatGPT / Cursor
          │
          ▼
     MCP Server          ← thin, no retrieval logic
          │
          ▼
 Application Services
          │
          ▼
   Retrieval Service
          │
     ┌────┴─────┐
     ▼          ▼
 PostgreSQL   Qdrant
     │
     ▼
 Object Storage
```

Ingestion is independent:

```
IUT DSpace
    │
    ▼
Connector
    │
    ▼
Processing Pipeline
    │
    ├── Extract (PyMuPDF)
    ├── OCR (Tesseract)
    ├── Metadata normalization
    ├── Chunking
    └── Embedding (BGE)
          │
          ▼
   Knowledge Layer
```

## Quick Start

```bash
# 1. Copy environment config
cp .env.example .env
# Edit .env with your settings

# 2. Install dependencies
make install-dev

# 3. Start backing services
make up

# 4. Run migrations
make migrate

# 5. Run unit tests
make test-unit
```

## Project Structure

```
apps/                   App entrypoints (thin)
  mcp_server/           MCP server (DEV-030)
  api/                  REST API — future (FB-018)
  worker/               Background worker
src/qbank/              Core library
  domain/               Domain models — DB/ORM agnostic (DEV-004)
  application/          Use cases and services (DEV-026)
  infrastructure/       DB, vector store, storage, config (DEV-007–010)
  connectors/           DSpace and other source connectors (DEV-011)
  processing/           PDF, OCR, metadata, chunking, embedding (DEV-014–023)
tests/
  unit/                 Fast, no external services
  integration/          Requires running Postgres + Qdrant
  e2e/                  Full pipeline scenarios
scripts/                CLI utilities (index rebuild, etc.)
docker/                 Per-service Dockerfiles
```

## Make Targets

| Target | Description |
|---|---|
| `make install-dev` | Install all deps + pre-commit hooks |
| `make test-unit` | Run fast unit tests |
| `make test-integration` | Run integration tests (needs `make up`) |
| `make lint` | ruff check |
| `make fmt` | ruff format |
| `make typecheck` | mypy |
| `make up` | Start Postgres, Qdrant, MinIO |
| `make migrate` | Run Alembic migrations |

## Status

Actively under development. See [`plan.md`](plan.md) for the full 52-task plan.
