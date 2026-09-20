Below is a developer-facing task list for the IUT Question Bank MCP Server. It is organized so the team can build the retrieval prototype first while keeping the architecture compatible with future uploads, moderation, multi-university support, and higher scale.

## IUT Question Bank MCP Server — Developer Task Plan

### Phase 0 — Repository and architecture foundation

**DEV-001 — Repository scaffold**
Create the project structure around a modular monolith.

Deliverables:

* `apps/mcp_server`
* `apps/api`
* `apps/worker`
* `src/qbank/domain`
* `src/qbank/application`
* `src/qbank/infrastructure`
* `src/qbank/connectors`
* `src/qbank/processing`
* `tests/unit`
* `tests/integration`
* `tests/e2e`
* `scripts`
* Docker configuration
* `pyproject.toml`
* README

Acceptance:

* Project installs cleanly.
* Test suite runs.
* Application modules can be imported independently.
* No retrieval logic is placed directly inside MCP handlers.

---

**DEV-002 — Configuration system**

Implement centralized configuration using environment variables/settings management.

Configuration should cover:

* PostgreSQL
* Qdrant
* object storage
* embedding provider
* embedding model
* MCP transport
* logging
* ingestion settings
* environment (`dev`, `test`, `prod`)

Acceptance:

* No secrets/configuration hardcoded in source.
* `.env.example` provided.
* Development configuration works through Docker Compose.

---

**DEV-003 — Dependency and code-quality baseline**

Set up:

* Python 3.12+
* formatting/linting
* type checking
* pytest
* pre-commit or equivalent
* GitHub Actions

Acceptance:

* CI runs tests and static checks on every PR.
* Team follows a consistent project structure.

---

# Phase 1 — Canonical knowledge model

### DEV-004 — Domain models

Define the core domain objects:

```text
Source
Document
DocumentVersion
Chunk
Question
Course
Department
```

The important hierarchy is:

```text
Source
  ↓
Document
  ↓
DocumentVersion
  ↓
Chunk
  ↓
Question
```

Keep domain models independent from PostgreSQL, Qdrant, and MCP.

---

### DEV-005 — Course normalization

Implement course normalization.

Examples:

```text
CSE3101
CSE 3101
CSE-3101
```

should resolve to the same canonical course.

Store:

```text
course_id
course_code
title
department
aliases
```

Acceptance:

* Search filters work consistently regardless of common course-code formatting.

---

### DEV-006 — Provenance model

Every piece of retrieved content must be traceable to its source.

Minimum provenance:

```text
source
  → document
  → document version
  → page
  → chunk
```

Store:

* repository URL
* document URL
* source ID
* document ID
* page number
* version/hash
* original filename where applicable.

This is a core requirement, not optional metadata.

---

# Phase 2 — Storage layer

### DEV-007 — PostgreSQL schema

Create the initial relational schema.

V1 tables:

```text
departments
courses
sources
documents
document_versions
document_chunks
questions
sync_runs
processing_jobs
```

Do not implement community/user/moderation tables yet.

Use Alembic migrations.

Acceptance:

* Fresh database can be created entirely through migrations.
* Migration rollback works for development migrations.

---

### DEV-008 — Repository interfaces

Create repository abstractions such as:

```python
DocumentRepository
CourseRepository
ChunkRepository
SourceRepository
```

Application services should depend on these interfaces rather than directly querying PostgreSQL.

---

### DEV-009 — Qdrant integration

Implement:

```text
iut_qbank_chunks_v1
```

with configurable vector dimensions and cosine similarity.

Payload should include:

```text
document_id
version_id
course_id
course_code
department
year
semester
document_type
page
question_number
source_type
language
```

Acceptance:

* Vectors can be inserted.
* Metadata filters work.
* Search returns provenance metadata.

---

### DEV-010 — Object storage abstraction

Create a storage interface even if local storage is initially used.

Example:

```python
ObjectStorage
 ├── LocalStorage
 └── S3Storage / MinIOStorage
```

Store original PDFs independently from the database.

This prevents the ingestion layer from becoming dependent on one storage provider.

---

# Phase 3 — IUT DSpace ingestion

### DEV-011 — DSpace connector

Implement:

```python
ContentSource
    └── DSpaceConnector
```

The connector should support:

```text
discover()
fetch()
get_version()
```

It should discover:

* communities
* collections
* items
* bitstreams/files
* repository metadata
* URLs/handles
* identifiers.

Prefer the DSpace API over HTML scraping.

---

### DEV-012 — DSpace incremental synchronization

Implement synchronization state.

The sync system should determine:

```text
new document
changed document
unchanged document
deleted/unavailable document
```

Use:

* repository IDs
* checksums
* timestamps
* remote identifiers
* previous sync state.

Do not download unchanged PDFs repeatedly.

---

### DEV-013 — Sync run tracking

Create:

```text
SyncRun
```

tracking:

```text
started_at
finished_at
source
documents_discovered
documents_downloaded
documents_skipped
documents_failed
status
error_summary
```

This will later support monitoring and scheduled synchronization.

---

# Phase 4 — Document processing pipeline

### DEV-014 — PDF extraction

Implement extraction using PyMuPDF as the primary engine.

Fallbacks:

```text
PyMuPDF
   ↓
alternative PDF parser
   ↓
OCR
```

Do not OCR every document automatically.

---

### DEV-015 — Extraction quality detection

Determine whether extracted text is usable.

For example:

```text
PDF
 ↓
extract text
 ↓
quality check
 ├── sufficient → continue
 └── poor → OCR
```

Track:

```text
extraction_status
extraction_method
text_quality
```

---

### DEV-016 — OCR fallback

Integrate Tesseract for scanned question papers.

Requirements:

* page-level OCR
* preserve page numbers
* record OCR status
* allow failed OCR jobs to be retried.

---

### DEV-017 — Metadata normalization

Normalize metadata using layered extraction:

```text
Repository metadata
        ↓
Directory/path
        ↓
Filename
        ↓
PDF metadata
        ↓
Extracted text
        ↓
Classifier
```

Extract where possible:

```text
course
course code
department
year
semester
exam type
document type
language
```

Do not require perfect metadata before indexing; retain confidence values.

---

### DEV-018 — Document classification

Classify documents into types such as:

```text
question_paper
syllabus
lecture_material
tutorial
assignment
other
```

Keep classification replaceable so a later ML/LLM classifier can be introduced without rewriting ingestion.

---

# Phase 5 — Semantic chunking

### DEV-019 — Chunking engine

Implement a chunking module independent of the PDF parser.

For question papers, preserve:

```text
page
question number
sub-question
question boundaries
```

Example:

```text
Page 2
Question 3
  3(a)
  3(b)
```

should preferably remain structurally identifiable.

---

### DEV-020 — Chunk metadata

Each chunk should contain:

```text
chunk_id
document_id
version_id
page
chunk_index
text
token_count
question_number
```

Avoid excessively large chunks.

---

### DEV-021 — Question extraction

Create a question extraction layer that can identify individual questions when possible.

This is separate from generic document chunking.

The architecture should support:

```text
Document
 ├── generic chunks
 └── structured questions
```

This will become important for future question-pattern analysis.

---

# Phase 6 — Embedding and indexing

### DEV-022 — Embedding provider abstraction

Create:

```python
EmbeddingProvider
```

with:

```python
embed_documents()
embed_query()
```

Initial implementation can use:

```text
sentence-transformers / BGE
```

but the application should not depend directly on a specific model.

---

### DEV-023 — Embedding pipeline

Implement:

```text
chunks
 ↓
embedding provider
 ↓
vectors
 ↓
Qdrant
```

Track:

* embedding model
* embedding version
* vector dimension.

---

### DEV-024 — Index versioning

Support:

```text
iut_qbank_chunks_v1
iut_qbank_chunks_v2
...
```

and an active-index configuration.

This allows the team to change embedding models later without destroying the currently working index.

---

### DEV-025 — Index rebuild utility

Create:

```bash
python scripts/rebuild_index.py
```

It should be able to:

```text
create new collection
→ embed documents
→ validate
→ switch active index
```

No destructive replacement until the new index passes validation.

---

# Phase 7 — Retrieval engine

### DEV-026 — Retrieval service

Implement the central:

```python
RetrievalService
```

Pipeline V1:

```text
query
 ↓
embedding
 ↓
Qdrant metadata filtering
 ↓
vector search
 ↓
top-k results
 ↓
provenance formatting
```

The MCP layer must call this service rather than implementing search itself.

---

### DEV-027 — Metadata filtering

Support:

```text
course_code
department
year
semester
document_type
question_number
```

Example:

```text
"normalization"
course = CSE3101
year = 2020–2025
document_type = question_paper
```

---

### DEV-028 — Search result schema

Standardize the result:

```json
{
  "id": "...",
  "text": "...",
  "score": 0.91,
  "course_code": "CSE3101",
  "year": 2024,
  "semester": "Winter",
  "page": 2,
  "source": {
    "document_id": "...",
    "title": "...",
    "url": "..."
  }
}
```

This schema should be shared by the REST API and MCP layers later.

---

### DEV-029 — Retrieval evaluation

Create a small manually verified retrieval dataset.

Measure:

```text
Recall@5
Recall@10
MRR
NDCG@10
course-filter accuracy
year-filter accuracy
provenance correctness
```

This gives the team an objective way to evaluate retrieval changes.

---

# Phase 8 — MCP server

### DEV-030 — FastMCP server foundation

Implement the MCP server separately from the application layer.

Architecture:

```text
MCP Tool
   ↓
Application Service
   ↓
Retrieval Service
   ↓
Infrastructure
```

The MCP server should be thin.

---

### DEV-031 — `search_questions`

Implement:

```text
search_questions(
    query,
    course_code?,
    topic?,
    year_range?,
    semester?,
    document_type?,
    limit?
)
```

Return compact evidence with provenance.

---

### DEV-032 — `get_past_papers`

Implement:

```text
get_past_papers(
    course_code,
    year_range?,
    semester?
)
```

Return matching papers and their metadata/URLs.

---

### DEV-033 — `get_course_materials`

Implement:

```text
get_course_materials(
    course_code
)
```

Return available learning materials.

---

### DEV-034 — `get_course_syllabus`

Implement:

```text
get_course_syllabus(
    course_code
)
```

Return the canonical syllabus document/material.

---

### DEV-035 — `get_question`

Implement retrieval of a specific question/chunk:

```text
get_question(question_id)
```

Return the question and complete provenance.

---

### DEV-036 — MCP resources

Implement read-only resources such as:

```text
course://{course_code}
course://{course_code}/syllabus
course://{course_code}/materials
course://{course_code}/past-papers
question://{course_code}/{year}/{semester}/{question_id}
document://{document_id}
```

Only expose resources that map to real canonical entities.

---

### DEV-037 — MCP transport

Support:

```text
stdio
```

for local development.

Prepare:

```text
Streamable HTTP
```

for remote deployment.

Do not build the deprecated HTTP+SSE transport as the primary architecture.

---

# Phase 9 — End-to-end integration

### DEV-038 — Full ingestion-to-search test

Build an integration test covering:

```text
DSpace
 ↓
download
 ↓
extract
 ↓
metadata
 ↓
chunk
 ↓
embed
 ↓
Qdrant
 ↓
RetrievalService
 ↓
MCP
```

The test should use a small fixture dataset rather than the entire repository.

---

### DEV-039 — Real IUT dataset indexing

Run the pipeline against a controlled subset of the IUT repository.

Start with:

```text
one department
→ several courses
→ several years
→ question papers
```

Do not ingest the entire repository until the pipeline is validated.

---

### DEV-040 — AI-host integration test

Verify that a supported MCP client can perform queries such as:

```text
Find CSE4105 final exam questions from 2022–2025
about operating systems.
```

The response should contain actual IUT material and provenance rather than fabricated answers.

---

# Phase 10 — Docker/deployment

### DEV-041 — Docker Compose environment

Create:

```text
mcp-server
postgres
qdrant
minio
```

Redis can remain optional until caching/work queues are introduced.

---

### DEV-042 — Health checks

Implement:

```text
/health
/ready
```

or equivalent service health mechanisms.

Check:

```text
PostgreSQL
Qdrant
object storage
MCP application
```

---

### DEV-043 — Structured logging

Use structured JSON logs containing:

```text
timestamp
service
request_id
operation
duration
status
error
document_id
query_id
```

Avoid logging sensitive request contents unnecessarily.

---

### DEV-044 — Observability foundation

Prepare interfaces for:

```text
metrics
tracing
```

Later stack:

```text
Prometheus
OpenTelemetry
Grafana
```

Do not build a large observability platform before the prototype needs it.

---

# Phase 11 — Testing and quality

### DEV-045 — Unit tests

Cover:

* course normalization
* metadata extraction
* document classification
* chunking
* provenance
* filtering
* retrieval formatting
* MCP input validation.

---

### DEV-046 — Integration tests

Test:

```text
PostgreSQL ↔ repository layer
Qdrant ↔ retrieval
storage ↔ documents
DSpace ↔ ingestion
```

---

### DEV-047 — End-to-end tests

At least one complete scenario:

```text
question paper
→ indexed
→ searched
→ returned through MCP
```

---

### DEV-048 — Failure-path tests

Test:

```text
DSpace unavailable
PDF download failure
corrupt PDF
OCR failure
embedding failure
Qdrant unavailable
PostgreSQL unavailable
duplicate document
```

The system should fail explicitly and preserve enough state to retry processing.

---

# Phase 12 — Future-extension interfaces

These should be designed now but not fully implemented in the retrieval prototype.

### DEV-049 — Source connector interface

Ensure future connectors can be added as:

```text
DSpaceConnector
GitHubConnector
UploadConnector
GoogleDriveConnector
AdminImportConnector
```

without changing retrieval logic.

---

### DEV-050 — Processing pipeline interface

Keep processing stages independently replaceable:

```text
Extractor
OCRProcessor
MetadataExtractor
Classifier
Chunker
EmbeddingProvider
Indexer
```

---

### DEV-051 — Future community-upload boundary

Define where future uploads enter:

```text
Upload API
 ↓
Object Storage
 ↓
Processing Queue
 ↓
Processing Pipeline
 ↓
Moderation
 ↓
Canonical Knowledge Base
```

Do not implement the actual community system yet.

---

### DEV-052 — Multi-university readiness

Include `tenant_id`/institution context in the canonical architecture.

For now:

```text
tenant_id = IUT
```

Future:

```text
IUT
BUET
KUET
DU
...
```

This prevents a later database/vector-schema redesign.

---

# Future backlog — explicitly out of prototype scope

These should remain tracked but should **not** block the retrieval MVP:

```text
FB-001 Authentication
FB-002 Student accounts
FB-003 Community uploads
FB-004 Upload moderation
FB-005 Duplicate detection
FB-006 Content voting
FB-007 Flags/reports
FB-008 Contributor points
FB-009 Badges
FB-010 Leaderboards
FB-011 Analytics
FB-012 Question-pattern analysis
FB-013 Knowledge graph
FB-014 Advanced reranking
FB-015 Hybrid BM25 + vector search
FB-016 Redis caching
FB-017 Background job queue
FB-018 REST API
FB-019 Web portal
FB-020 Multi-university tenancy
FB-021 Horizontal MCP scaling
FB-022 HA PostgreSQL
FB-023 Qdrant cluster
```

## Recommended implementation order

The team should **not** work on all tasks simultaneously.

The dependency chain is:

```text
1. Project scaffold
        ↓
2. Domain + database model
        ↓
3. DSpace connector
        ↓
4. PDF extraction
        ↓
5. Metadata normalization
        ↓
6. Chunking
        ↓
7. Embeddings
        ↓
8. Qdrant indexing
        ↓
9. RetrievalService
        ↓
10. MCP tools
        ↓
11. MCP resources
        ↓
12. End-to-end testing
        ↓
13. Real IUT dataset
        ↓
14. AI-client integration
        ↓
15. Deployment
```

The key architectural rule for the team is:

> **Do not let MCP become the application.**

The actual dependency should remain:

```text
Claude / ChatGPT / Cursor
          │
          ▼
     MCP Server
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

And ingestion remains independent:

```text
IUT DSpace
    │
    ▼
Connector
    │
    ▼
Processing Pipeline
    │
    ├── Extract
    ├── OCR
    ├── Metadata
    ├── Chunk
    └── Embed
          │
          ▼
   Knowledge Layer
```

That separation is what makes the system easy to extend later without rewriting the MCP interface.
