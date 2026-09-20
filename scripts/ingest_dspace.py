#!/usr/bin/env python
"""DSpace → PostgreSQL → Qdrant ingestion runner.

Orchestrates the full ingestion pipeline using the existing, decoupled
processing components and repository implementations.

State machine per document:
    DISCOVERED → FETCHED → EXTRACTED → CLASSIFIED/METADATA
    → PERSISTED → INDEXED → PROCESSED

Idempotency:
    Documents are skipped when their content hash (version_hash) already
    exists in DocumentVersion and extraction_status = SUCCEEDED.

Usage:
    python scripts/ingest_dspace.py
    python scripts/ingest_dspace.py --limit 10
    python scripts/ingest_dspace.py --dry-run
    python scripts/ingest_dspace.py --limit 5 --dry-run

Exit codes:
    0  All discovered documents processed or cleanly skipped.
    1  At least one document failed (partial run still counted).
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import logging
import sys
import traceback
from dataclasses import dataclass, field
from datetime import UTC, datetime

# ── Ensure the project src/ is importable when run directly ──────────────────
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(_ROOT / "src"))

# ── Project imports ───────────────────────────────────────────────────────────
from qbank.connectors.dspace import DSpaceConnector
from qbank.domain.models import (
    Chunk,
    Document,
    DocumentType,
    DocumentVersion,
    ExtractionMethod,
    ExtractionStatus,
    Language,
    Question,
    Semester,
    Source,
    SourceType,
    SyncRun,
)
from qbank.infrastructure.config import get_settings
from qbank.infrastructure.db.engine import make_engine, make_session_factory
from qbank.infrastructure.repositories.sqlalchemy_repos import (
    SqlChunkRepository,
    SqlDocumentRepository,
    SqlDocumentVersionRepository,
    SqlQuestionRepository,
    SqlSourceRepository,
    SqlSyncRunRepository,
)
from qbank.infrastructure.storage.object_storage import ObjectStorage, make_storage
from qbank.infrastructure.vector.qdrant_store import ChunkPayload, QdrantStore
from qbank.processing.chunker import QuestionData, QuestionPaperChunker
from qbank.processing.classifier import RuleBasedClassifier
from qbank.processing.embedding import SentenceTransformerProvider
from qbank.processing.extractor import PyMuPDFExtractor
from qbank.processing.interfaces import ChunkData, NormalizedMetadata
from qbank.processing.metadata import RuleBasedMetadataExtractor

# ── Logging ───────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("ingest_dspace")

# Silence noisy library loggers
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
logging.getLogger("sentence_transformers").setLevel(logging.WARNING)
logging.getLogger("qdrant_client").setLevel(logging.WARNING)


# ── Run statistics ────────────────────────────────────────────────────────────


@dataclass
class RunStats:
    discovered: int = 0
    new: int = 0
    changed: int = 0
    skipped: int = 0
    processed: int = 0
    failed: int = 0
    chunks: int = 0
    questions: int = 0
    vectors: int = 0
    failed_titles: list[str] = field(default_factory=list)

    def print_summary(self) -> None:
        width = 14
        print("\n" + "─" * 48)
        print("  Ingestion summary")
        print("─" * 48)
        print(f"  {'Discovered':<{width}} {self.discovered}")
        print(f"  {'New':<{width}} {self.new}")
        print(f"  {'Changed':<{width}} {self.changed}")
        print(f"  {'Skipped':<{width}} {self.skipped}")
        print(f"  {'Processed':<{width}} {self.processed}")
        print(f"  {'Failed':<{width}} {self.failed}")
        print(f"  {'Chunks':<{width}} {self.chunks}")
        print(f"  {'Questions':<{width}} {self.questions}")
        print(f"  {'Vectors':<{width}} {self.vectors}")
        print("─" * 48)
        if self.failed_titles:
            print(f"\n  Failed documents ({len(self.failed_titles)}):")
            for title in self.failed_titles:
                print(f"    • {title}")
        print()


# ── Helpers ───────────────────────────────────────────────────────────────────


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _doc_type_from_classifier(label: str) -> DocumentType:
    mapping = {
        "question_paper": DocumentType.QUESTION_PAPER,
        "syllabus": DocumentType.SYLLABUS,
        "lecture_material": DocumentType.LECTURE_MATERIAL,
        "tutorial": DocumentType.TUTORIAL,
        "assignment": DocumentType.ASSIGNMENT,
    }
    return mapping.get(label, DocumentType.OTHER)


def _semester_from_str(s: str | None) -> Semester | None:
    if not s:
        return None
    try:
        return Semester(s)
    except ValueError:
        return None


def _extraction_method_from_str(method: str) -> ExtractionMethod | None:
    mapping = {
        "native": ExtractionMethod.NATIVE,
        "native_low_quality": ExtractionMethod.NATIVE,
        "ocr_required": ExtractionMethod.OCR,
        "hybrid_required": ExtractionMethod.HYBRID,
    }
    return mapping.get(method)


# ── Core ingestion logic ──────────────────────────────────────────────────────


async def _ensure_source(
    source_repo: SqlSourceRepository,
    settings,
) -> Source:
    """Get-or-create the DSpace Source record."""
    # Use a deterministic source_id derived from the base URL so re-runs
    # always resolve to the same database row.
    source_id = _sha256(settings.dspace_base_url.encode())[:32]
    existing = await source_repo.get_by_id(source_id)
    if existing:
        logger.info("Using existing Source record: %s", existing.name)
        return existing

    source = Source(
        source_id=source_id,
        source_type=SourceType.DSPACE,
        name="IUT DSpace",
        base_url=settings.dspace_base_url,
        repository_url=settings.dspace_base_url,
        tenant_id="IUT",
        is_active=True,
    )
    await source_repo.save(source)
    logger.info("Created new Source record: %s", source.name)
    return source


async def _process_document(  # noqa: PLR0913 — orchestrator; many deps expected
    *,
    remote_doc,
    source: Source,
    connector: DSpaceConnector,
    storage: ObjectStorage,
    extractor: PyMuPDFExtractor,
    metadata_extractor: RuleBasedMetadataExtractor,
    classifier: RuleBasedClassifier,
    chunker: QuestionPaperChunker,
    embedding_provider: SentenceTransformerProvider,
    qdrant_store: QdrantStore,
    doc_repo: SqlDocumentRepository,
    version_repo: SqlDocumentVersionRepository,
    chunk_repo: SqlChunkRepository,
    question_repo: SqlQuestionRepository,
    stats: RunStats,
    dry_run: bool,
) -> bool:
    """Full pipeline for a single RemoteDocument. Returns True on success."""

    title = remote_doc.title or remote_doc.remote_id
    logger.info("Processing: %s", title)

    # ── 1. Determine version hash (before downloading) ────────────────────────
    version_hash = await connector.get_version(remote_doc)
    logger.debug("  version_hash=%s", version_hash[:16])

    # ── 2. Idempotency check ──────────────────────────────────────────────────
    # Track new-vs-changed locally; only write to aggregates once we know the
    # document will actually be processed (avoids retroactive counter mutation).
    existing_doc = await doc_repo.get_by_remote_id(source.source_id, remote_doc.remote_id)
    is_new_doc = existing_doc is None

    if existing_doc:
        existing_version = await version_repo.get_by_hash(
            existing_doc.document_id, version_hash
        )
        if existing_version and existing_version.extraction_status == ExtractionStatus.SUCCEEDED:
            logger.info("  ↳ SKIPPED (unchanged, already processed)")
            stats.skipped += 1
            return True
        logger.info("  ↳ CHANGED (new version detected)")
    else:
        logger.info("  ↳ NEW document")

    if dry_run:
        logger.info("  ↳ [dry-run] Would process — skipping actual work")
        if is_new_doc:
            stats.new += 1
        else:
            stats.changed += 1
        stats.processed += 1
        return True

    # ── 3. Fetch PDF bytes ────────────────────────────────────────────────────
    logger.info("  ↳ Fetching PDF...")
    pdf_bytes = await connector.fetch(remote_doc)
    if not pdf_bytes:
        raise ValueError("Empty PDF response from connector")

    actual_hash = _sha256(pdf_bytes)
    # Use the actual content hash (authoritative) — connector may return a
    # weaker checksum (e.g. MD5). Re-check idempotency with the real hash.
    if existing_doc and actual_hash != version_hash:
        # connector.get_version returned a non-SHA256 value; re-check with
        # the real content hash so we don't duplicate work.
        existing_version = await version_repo.get_by_hash(
            existing_doc.document_id, actual_hash
        )
        if existing_version and existing_version.extraction_status == ExtractionStatus.SUCCEEDED:
            logger.info("  ↳ SKIPPED (content hash match — version already processed)")
            stats.skipped += 1
            return True

    # Content hash is now authoritative. Increment the correct aggregate counter
    # exactly once — here, after all early-exit paths are cleared.
    version_hash = actual_hash
    if is_new_doc:
        stats.new += 1
    else:
        stats.changed += 1

    # ── 4. Extract text ───────────────────────────────────────────────────────
    logger.info("  ↳ Extracting text (PyMuPDF)...")
    extracted = extractor.extract(pdf_bytes)
    logger.info(
        "  ↳ Extracted %d pages, quality=%.2f, method=%s",
        extracted.page_count,
        extracted.overall_quality,
        extracted.extraction_method,
    )

    if extracted.extraction_method == "failed":
        raise ValueError("PDF text extraction failed (no pages returned)")

    text_sample = extracted.full_text[:2000]

    # ── 5. Classify document ──────────────────────────────────────────────────
    original_filename = remote_doc.metadata.get("filename") or (
        remote_doc.document_url.split("/")[-1] if remote_doc.document_url else None
    )
    doc_type_label, classification_conf = classifier.classify(
        filename=original_filename,
        text_sample=text_sample,
        repository_metadata=remote_doc.metadata,
    )
    logger.info(
        "  ↳ Classified as '%s' (conf=%.2f)", doc_type_label, classification_conf
    )

    # ── 6. Extract / normalise metadata ──────────────────────────────────────
    normalized: NormalizedMetadata = metadata_extractor.extract(
        repository_metadata=remote_doc.metadata,
        filename=original_filename,
        text_sample=text_sample,
    )
    logger.info(
        "  ↳ Metadata: course=%s, year=%s, semester=%s, dept=%s (conf=%.2f)",
        normalized.course_code,
        normalized.year,
        normalized.semester,
        normalized.department,
        normalized.confidence,
    )

    # ── 7. Upsert Document row ────────────────────────────────────────────────
    doc_type = _doc_type_from_classifier(doc_type_label)
    semester_enum = _semester_from_str(normalized.semester)

    document = Document(
        source_id=source.source_id,
        remote_id=remote_doc.remote_id,
        title=title,
        document_url=remote_doc.document_url,
        original_filename=original_filename,
        document_type=doc_type,
        course_code=normalized.course_code,
        department=normalized.department,
        year=normalized.year,
        semester=semester_enum,
        language=Language.ENGLISH,
        tenant_id=source.tenant_id,
        metadata={
            "handle_url": remote_doc.handle_url,
            "collection_path": remote_doc.collection_path,
            "remote_metadata": remote_doc.metadata,
        },
    )
    if existing_doc:
        document.document_id = existing_doc.document_id

    persisted_doc = await doc_repo.upsert(document)
    document_id = persisted_doc.document_id

    # ── 8. Store PDF in object storage ────────────────────────────────────────
    storage_key = ObjectStorage.make_key(source.source_id, document_id, version_hash)
    if not await storage.exists(storage_key):
        await storage.put(storage_key, pdf_bytes)
        logger.info("  ↳ Stored PDF at: %s", storage_key)
    else:
        logger.debug("  ↳ PDF already in storage: %s", storage_key)

    # ── 9. Create DocumentVersion (PENDING) ───────────────────────────────────
    extraction_method_enum = _extraction_method_from_str(extracted.extraction_method)

    version = DocumentVersion(
        document_id=document_id,
        version_hash=version_hash,
        file_size_bytes=len(pdf_bytes),
        storage_key=storage_key,
        extraction_status=ExtractionStatus.PENDING,
        extraction_method=extraction_method_enum,
        text_quality_score=extracted.overall_quality,
        page_count=extracted.page_count,
    )
    await version_repo.save(version)
    version_id = version.version_id
    logger.info("  ↳ Persisted DocumentVersion (PENDING): %s", version_id[:8])

    # ── 10. Chunk the document ────────────────────────────────────────────────
    logger.info("  ↳ Chunking...")
    chunk_data_list: list[ChunkData]
    question_data_list: list[QuestionData]

    if doc_type == DocumentType.QUESTION_PAPER:
        chunk_data_list, question_data_list = chunker.chunk_with_questions(extracted)
    else:
        chunk_data_list = chunker.chunk(extracted)
        question_data_list = []

    logger.info(
        "  ↳ %d chunks, %d questions", len(chunk_data_list), len(question_data_list)
    )

    # ── 11. Build domain Chunk objects ────────────────────────────────────────
    chunks: list[Chunk] = [
        Chunk(
            document_id=document_id,
            version_id=version_id,
            page=cd.page,
            chunk_index=cd.chunk_index,
            text=cd.text,
            token_count=cd.token_count,
            question_number=cd.question_number,
        )
        for cd in chunk_data_list
    ]

    # ── 12. Build domain Question objects ─────────────────────────────────────
    questions: list[Question] = [
        Question(
            document_id=document_id,
            version_id=version_id,
            question_number=qd.question_number,
            text=qd.text,
            page=qd.page,
            course_code=normalized.course_code,
            year=normalized.year,
            semester=semester_enum,
        )
        for qd in question_data_list
    ]

    # ── 13. Persist chunks and questions ──────────────────────────────────────
    await chunk_repo.bulk_insert(chunks)
    if questions:
        await question_repo.bulk_insert(questions)
    logger.info("  ↳ Persisted %d chunks, %d questions to PostgreSQL", len(chunks), len(questions))

    # ── 14. Generate embeddings ───────────────────────────────────────────────
    texts = [c.text for c in chunks]
    if not texts:
        # No embeddable text — mark processed without a Qdrant entry. The
        # version status is still SUCCEEDED: extraction and persistence both
        # completed; there is simply nothing to index.
        logger.warning("  ↳ No chunks to embed — marking SUCCEEDED without Qdrant entry")
        await version_repo.mark_processed(
            version_id=version_id,
            extraction_method=extracted.extraction_method,
            text_quality_score=extracted.overall_quality,
        )
        logger.info("  ↳ DocumentVersion marked SUCCEEDED (no vectors)")
        stats.processed += 1
        stats.chunks += len(chunks)
        stats.questions += len(questions)
        return True

    logger.info("  ↳ Embedding %d chunks...", len(texts))
    vectors = embedding_provider.embed_documents(texts)

    # ── 15. Build Qdrant payloads ─────────────────────────────────────────────
    payloads: list[ChunkPayload] = [
        ChunkPayload(
            chunk_id=chunk.chunk_id,
            document_id=document_id,
            version_id=version_id,
            course_id=None,  # course_id linkage is a future step (DEV-022)
            course_code=normalized.course_code,
            department=normalized.department,
            year=normalized.year,
            semester=normalized.semester,
            document_type=doc_type.value,
            page=chunk.page,
            question_number=chunk.question_number,
            source_type=source.source_type.value,
            language=Language.ENGLISH.value,
            text=chunk.text,
            document_title=title,
            document_url=remote_doc.document_url,
            tenant_id=source.tenant_id,
        )
        for chunk in chunks
    ]

    # ── 16. Upsert vectors to Qdrant ─────────────────────────────────────────
    # Qdrant is outside the PostgreSQL transaction boundary. The ordering
    # invariant is:
    #   Qdrant upsert succeeds → mark_processed(SUCCEEDED) → pg commit
    #
    # Failure modes:
    #   • Qdrant fails → exception propagates → session.rollback() cancels
    #     PENDING version + chunks → next run retries cleanly.
    #   • mark_processed or pg commit fails after Qdrant succeeds → version
    #     stays PENDING in Postgres (rolled back) → next run re-upserts the
    #     same chunk_ids into Qdrant (QdrantStore.upsert is idempotent).
    #
    # Invariant: SUCCEEDED in Postgres ↔ vectors present in Qdrant.
    logger.info("  ↳ Upserting %d vectors to Qdrant...", len(vectors))
    await qdrant_store.upsert(vectors=vectors, payloads=payloads)

    # ── 17. Mark version SUCCEEDED — only after Qdrant confirms ──────────────
    await version_repo.mark_processed(
        version_id=version_id,
        extraction_method=extracted.extraction_method,
        text_quality_score=extracted.overall_quality,
    )
    logger.info("  ↳ DocumentVersion marked SUCCEEDED")

    stats.processed += 1
    stats.chunks += len(chunks)
    stats.questions += len(questions)
    stats.vectors += len(vectors)

    logger.info("  ↳ Done ✓")
    return True


# ── Entry point ───────────────────────────────────────────────────────────────


async def run(limit: int | None, dry_run: bool) -> int:
    """Main ingestion loop. Returns exit code (0 = success, 1 = partial failure)."""

    settings = get_settings()
    stats = RunStats()

    logger.info(
        "Starting DSpace ingestion (limit=%s, dry_run=%s)",
        limit if limit else "unlimited",
        dry_run,
    )

    # ── Infrastructure setup ──────────────────────────────────────────────────
    engine = make_engine()
    session_factory = make_session_factory(engine)

    storage = make_storage(
        settings.storage_backend,
        local_path=settings.storage_local_path,
    )

    embedding_provider = SentenceTransformerProvider(
        model_name=settings.embedding_model,
        batch_size=settings.embedding_batch_size,
    )

    qdrant_store = QdrantStore()
    await qdrant_store.ensure_collection()
    logger.info("Qdrant collection ready: %s", qdrant_store.collection)

    # ── Processing components (stateless; instantiated once) ──────────────────
    extractor = PyMuPDFExtractor()
    metadata_extractor = RuleBasedMetadataExtractor()
    classifier = RuleBasedClassifier()
    chunker = QuestionPaperChunker()

    # ── Connector ─────────────────────────────────────────────────────────────
    connector = DSpaceConnector()

    # ── SyncRun record ────────────────────────────────────────────────────────
    sync_run = SyncRun(started_at=datetime.now(UTC))

    try:
        async with session_factory() as session:
            source_repo = SqlSourceRepository(session)
            doc_repo = SqlDocumentRepository(session)
            version_repo = SqlDocumentVersionRepository(session)
            chunk_repo = SqlChunkRepository(session)
            question_repo = SqlQuestionRepository(session)
            sync_run_repo = SqlSyncRunRepository(session)

            # ── Ensure Source row exists ───────────────────────────────────────
            source = await _ensure_source(source_repo, settings)
            sync_run.source_id = source.source_id

            # Save the SyncRun in RUNNING state
            if not dry_run:
                await sync_run_repo.save(sync_run)
                await session.commit()

            # ── Discovery loop ─────────────────────────────────────────────────
            logger.info("Discovering documents from DSpace...")
            count = 0

            async for remote_doc in connector.discover():
                stats.discovered += 1
                count += 1

                try:
                    await _process_document(
                        remote_doc=remote_doc,
                        source=source,
                        connector=connector,
                        storage=storage,
                        extractor=extractor,
                        metadata_extractor=metadata_extractor,
                        classifier=classifier,
                        chunker=chunker,
                        embedding_provider=embedding_provider,
                        qdrant_store=qdrant_store,
                        doc_repo=doc_repo,
                        version_repo=version_repo,
                        chunk_repo=chunk_repo,
                        question_repo=question_repo,
                        stats=stats,
                        dry_run=dry_run,
                    )
                    # Commit after each successfully processed document
                    if not dry_run:
                        await session.commit()

                except Exception:  # noqa: BLE001
                    stats.failed += 1
                    stats.failed_titles.append(remote_doc.title or remote_doc.remote_id)
                    logger.error(
                        "FAILED: %s\n%s",
                        remote_doc.title or remote_doc.remote_id,
                        traceback.format_exc(),
                    )
                    # Roll back partial work for this document only
                    await session.rollback()

                if limit and count >= limit:
                    logger.info("Reached --limit %d, stopping discovery.", limit)
                    break

            # ── Finalise SyncRun ───────────────────────────────────────────────
            sync_run.finished_at = datetime.now(UTC)
            sync_run.status = "failed" if stats.failed and not stats.processed else "completed"
            sync_run.documents_discovered = stats.discovered
            sync_run.documents_downloaded = stats.new + stats.changed
            sync_run.documents_skipped = stats.skipped
            sync_run.documents_failed = stats.failed
            if stats.failed_titles:
                sync_run.error_summary = "; ".join(stats.failed_titles[:5])

            if not dry_run:
                await sync_run_repo.update(sync_run)
                await source_repo.update_last_synced(source.source_id)
                await session.commit()

    finally:
        await connector.close()
        await engine.dispose()
        logger.info("Resources closed.")

    stats.print_summary()

    return 1 if stats.failed else 0


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Ingest IUT DSpace documents into PostgreSQL + Qdrant."
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        metavar="N",
        help="Stop after discovering N documents (useful for testing).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=False,
        help="Discover and classify documents without writing to the database or Qdrant.",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        default=False,
        help="Enable DEBUG-level logging.",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)

    exit_code = asyncio.run(run(limit=args.limit, dry_run=args.dry_run))
    sys.exit(exit_code)
