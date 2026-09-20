"""End-to-end integration test: DEV-038.

Tests the complete flow against real services (PostgreSQL + Qdrant):
1. Ingest simulated DSpace RemoteDocument fixture
2. Extract text & calculate quality
3. Extract and normalize metadata
4. Chunk text into question chunks
5. Embed chunks using SentenceTransformerProvider
6. Index in QdrantStore & persist in PostgreSQL
7. Query via RetrievalService
8. Verify result schema, metadata, and provenance
"""
from __future__ import annotations

import uuid

import pytest

from qbank.application.retrieval_service import RetrievalService
from qbank.connectors.base import RemoteDocument
from qbank.domain.models import (
    Chunk,
    Document,
    DocumentType,
    DocumentVersion,
    ExtractionMethod,
    ExtractionStatus,
    Language,
    Source,
    SourceType,
)
from qbank.infrastructure.db.engine import make_engine, make_session_factory
from qbank.infrastructure.repositories import (
    SqlChunkRepository,
    SqlDocumentRepository,
    SqlDocumentVersionRepository,
    SqlSourceRepository,
)
from qbank.infrastructure.vector.qdrant_store import ChunkPayload, QdrantStore
from qbank.processing.chunker import QuestionPaperChunker
from qbank.processing.embedding import SentenceTransformerProvider
from qbank.processing.interfaces import ExtractedDocument, PageText
from qbank.processing.metadata import RuleBasedMetadataExtractor


@pytest.mark.integration
@pytest.mark.asyncio
async def test_end_to_end_ingestion_and_retrieval() -> None:
    # 1. Setup mock remote document from DSpace
    remote_doc = RemoteDocument(
        remote_id=f"dspace-item-{uuid.uuid4().hex[:8]}",
        title="CSE 4105 Operating Systems Final Examination Winter 2023",
        document_url="https://repository.iutoic-dhaka.edu/bitstream/sample-cse4105.pdf",
        handle_url="https://repository.iutoic-dhaka.edu/handle/123456789/100",
        metadata={
            "dc.title": ["CSE 4105 Operating Systems Final Examination Winter 2023"],
            "dc.subject": ["Operating Systems", "Deadlock", "Virtual Memory"],
        },
    )

    # 2. Simulated extraction (PyMuPDF output)
    simulated_pages = [
        PageText(
            page_number=1,
            text=(
                "ISLAMIC UNIVERSITY OF TECHNOLOGY (IUT)\n"
                "DEPARTMENT OF COMPUTER SCIENCE AND ENGINEERING\n"
                "WINTER SEMESTER, 2023\n"
                "COURSE NO: CSE 4105       COURSE TITLE: Operating Systems\n\n"
                "1. (a) Define deadlock. What are the four necessary conditions for deadlock to occur?\n"
                "(b) Explain the Banker's algorithm for deadlock avoidance with a suitable state matrix.\n\n"
                "2. (a) Distinguish between paging and segmentation.\n"
                "(b) Describe how Translation Lookaside Buffers (TLBs) speed up address translation.\n"
            ),
            extraction_method="native",
            quality_score=0.98,
        )
    ]
    extracted_doc = ExtractedDocument(
        pages=simulated_pages,
        extraction_method="native",
        overall_quality=0.98,
        page_count=1,
    )

    # 3. Metadata extraction & normalization
    meta_extractor = RuleBasedMetadataExtractor()
    normalized_meta = meta_extractor.extract(
        filename="CSE_4105_Winter_2023.pdf",
        repository_metadata=remote_doc.metadata,
        text_sample=extracted_doc.full_text,
    )
    assert normalized_meta.course_code == "CSE4105"
    assert normalized_meta.year == 2023
    assert normalized_meta.semester == "Winter"

    # 4. Chunking
    chunker = QuestionPaperChunker()
    chunks_data, structured_questions = chunker.chunk_with_questions(extracted_doc)
    assert len(chunks_data) >= 2
    assert len(structured_questions) >= 2

    # 5. Persist to PostgreSQL
    engine = make_engine()
    session_factory = make_session_factory(engine)

    doc_id = str(uuid.uuid4())
    version_id = str(uuid.uuid4())
    source_id = str(uuid.uuid4())

    async with session_factory() as session:
        async with session.begin():
            src_repo = SqlSourceRepository(session)
            doc_repo = SqlDocumentRepository(session)
            ver_repo = SqlDocumentVersionRepository(session)
            chunk_repo = SqlChunkRepository(session)

            await src_repo.save(
                Source(
                    source_id=source_id,
                    source_type=SourceType.DSPACE,
                    name="IUT DSpace",
                    base_url="https://repository.iutoic-dhaka.edu",
                )
            )

            await doc_repo.save(
                Document(
                    document_id=doc_id,
                    source_id=source_id,
                    remote_id=remote_doc.remote_id,
                    title=remote_doc.title,
                    document_url=remote_doc.document_url,
                    original_filename="CSE_4105_Winter_2023.pdf",
                    document_type=DocumentType.QUESTION_PAPER,
                    course_code=normalized_meta.course_code,
                    department=normalized_meta.department or "CSE",
                    year=normalized_meta.year,
                    language=Language.ENGLISH,
                )
            )

            await ver_repo.save(
                DocumentVersion(
                    version_id=version_id,
                    document_id=doc_id,
                    version_hash="dummy_hash_" + doc_id[:8],
                    file_size_bytes=1024,
                    storage_key="test/cse4105.pdf",
                    extraction_status=ExtractionStatus.SUCCEEDED,
                    extraction_method=ExtractionMethod.NATIVE,
                    text_quality_score=extracted_doc.overall_quality,
                    page_count=extracted_doc.page_count,
                )
            )

            domain_chunks = [
                Chunk(
                    chunk_id=str(uuid.uuid4()),
                    document_id=doc_id,
                    version_id=version_id,
                    page=c.page,
                    chunk_index=c.chunk_index,
                    text=c.text,
                    token_count=c.token_count,
                    question_number=c.question_number,
                )
                for c in chunks_data
            ]
            await chunk_repo.bulk_insert(domain_chunks)

    # 6. Embed & index into Qdrant
    embed_provider = SentenceTransformerProvider()
    qdrant_store = QdrantStore()
    await qdrant_store.ensure_collection()

    texts_to_embed = [c.text for c in domain_chunks]
    vectors = embed_provider.embed_documents(texts_to_embed)

    payloads = [
        ChunkPayload(
            chunk_id=c.chunk_id,
            document_id=doc_id,
            version_id=version_id,
            course_id=None,
            course_code=normalized_meta.course_code,
            department=normalized_meta.department or "CSE",
            year=normalized_meta.year,
            semester=normalized_meta.semester,
            document_type="question_paper",
            page=c.page,
            question_number=c.question_number,
            source_type="dspace",
            language="en",
            text=c.text,
            document_title=remote_doc.title,
            document_url=remote_doc.document_url,
            tenant_id="IUT",
        )
        for c in domain_chunks
    ]

    await qdrant_store.upsert(vectors=vectors, payloads=payloads)

    # 7. Search via RetrievalService
    retrieval_service = RetrievalService(
        embedding_provider=embed_provider,
        qdrant_store=qdrant_store,
    )

    results = await retrieval_service.search_questions(
        query="Explain Banker's algorithm for deadlock avoidance",
        course_code="CSE4105",
        year_range=(2020, 2025),
        limit=3,
    )

    # 8. Assertions
    assert len(results) > 0
    top_hit = results[0]
    assert top_hit.course_code == "CSE4105"
    assert top_hit.year == 2023
    assert top_hit.document_title == remote_doc.title
    assert "Banker" in top_hit.text or "deadlock" in top_hit.text.lower()
    assert top_hit.score > 0.4

    # Test DEV-035 get_by_id on retrieved point
    by_id_result = await retrieval_service.get_by_id(top_hit.id)
    assert by_id_result is not None
    assert by_id_result.id == top_hit.id
    assert by_id_result.course_code == "CSE4105"

    # Cleanup test data in Qdrant & DB
    await qdrant_store.delete_by_document(doc_id)
    await engine.dispose()
