#!/usr/bin/env python
"""Index rebuild utility. DEV-024, DEV-025.

Creates a new Qdrant collection, re-embeds all chunks from the database,
validates the new collection, then switches the active index.

Usage:
    python scripts/rebuild_index.py
    python scripts/rebuild_index.py --collection iut_qbank_chunks_v2 --validate

Safety: The new collection is NOT destructively used until it passes validation.
If any step fails, the existing collection remains active.

Pipeline:
    create new collection
     ↓
    embed all chunks from PostgreSQL
     ↓
    validate (count check)
     ↓
    switch QDRANT_ACTIVE_COLLECTION in .env (or print new value)
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path

# Ensure project root is on the path when run directly
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from qbank.infrastructure.config import get_settings
from qbank.infrastructure.db.models import DocumentChunkRow
from qbank.infrastructure.vector.qdrant_store import ChunkPayload, QdrantStore
from qbank.processing.embedding import SentenceTransformerProvider

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    stream=sys.stderr,
)
logger = logging.getLogger("rebuild_index")


async def load_chunks_from_db(
    session: AsyncSession,
) -> list[tuple[str, str, dict]]:
    """Load all chunks from PostgreSQL.

    Returns list of (chunk_id, text, metadata_dict).
    """
    from sqlalchemy import select
    from sqlalchemy.orm import joinedload

    logger.info("Loading chunks from PostgreSQL …")
    result = await session.execute(
        select(DocumentChunkRow)
        .options(joinedload(DocumentChunkRow.document))  # type: ignore[attr-defined]
    )
    rows = result.unique().scalars().all()
    logger.info("Found %d chunks in database", len(rows))

    chunks = []
    for row in rows:
        doc = row.document
        chunks.append((
            row.chunk_id,
            row.text,
            {
                "document_id": row.document_id,
                "version_id": row.version_id,
                "course_id": doc.course_id if doc else None,
                "course_code": doc.course_code if doc else None,
                "department": doc.department if doc else None,
                "year": doc.year if doc else None,
                "semester": doc.semester if doc else None,
                "document_type": doc.document_type if doc else "other",
                "page": row.page,
                "question_number": row.question_number,
                "source_type": "dspace",
                "language": doc.language if doc else "en",
                "text": row.text,
                "document_title": doc.title if doc else "",
                "document_url": doc.document_url if doc else "",
                "tenant_id": doc.tenant_id if doc else "IUT",
            },
        ))
    return chunks


async def rebuild(
    target_collection: str,
    batch_size: int = 32,
    validate: bool = True,
) -> None:
    """Run the full index rebuild pipeline. DEV-025."""
    settings = get_settings()

    # ── Embedding provider ────────────────────────────────────────────────────
    logger.info("Loading embedding model: %s", settings.embedding_model)
    embedder = SentenceTransformerProvider(
        model_name=settings.embedding_model,
        batch_size=settings.embedding_batch_size,
    )

    # ── Target QdrantStore ────────────────────────────────────────────────────
    store = QdrantStore()
    logger.info("Creating collection: %s", target_collection)
    await store.ensure_collection(collection=target_collection)

    # ── Load chunks from PostgreSQL ───────────────────────────────────────────
    engine = create_async_engine(settings.postgres_dsn, echo=False)
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)  # type: ignore[call-overload]

    async with async_session() as session:
        chunk_data = await load_chunks_from_db(session)

    if not chunk_data:
        logger.warning("No chunks found in database. Nothing to index.")
        await engine.dispose()
        return

    # ── Embed and upsert in batches ───────────────────────────────────────────
    total = len(chunk_data)
    logger.info("Embedding and indexing %d chunks in batches of %d …", total, batch_size)
    indexed = 0

    for i in range(0, total, batch_size):
        batch = chunk_data[i : i + batch_size]
        texts = [t for _, t, _ in batch]

        vectors = embedder.embed_documents(texts)

        payloads = [
            ChunkPayload(
                chunk_id=cid,
                document_id=meta["document_id"],
                version_id=meta["version_id"],
                course_id=meta.get("course_id"),
                course_code=meta.get("course_code"),
                department=meta.get("department"),
                year=meta.get("year"),
                semester=meta.get("semester"),
                document_type=meta.get("document_type", "other"),
                page=meta.get("page"),
                question_number=meta.get("question_number"),
                source_type=meta.get("source_type", "dspace"),
                language=meta.get("language", "en"),
                text=meta.get("text", ""),
                document_title=meta.get("document_title", ""),
                document_url=meta.get("document_url", ""),
                tenant_id=meta.get("tenant_id", "IUT"),
            )
            for cid, _, meta in batch
        ]

        await store.upsert(
            vectors=vectors,
            payloads=payloads,
            collection=target_collection,
        )
        indexed += len(batch)
        logger.info("Indexed %d / %d chunks", indexed, total)

    await engine.dispose()

    # ── Validation ────────────────────────────────────────────────────────────
    if validate:
        logger.info("Validating new collection …")
        info = await store._client.get_collection(target_collection)  # type: ignore[attr-defined]
        indexed_count = info.points_count or 0
        if indexed_count < total * 0.95:
            logger.error(
                "Validation FAILED: expected ~%d points, found %d in %s",
                total,
                indexed_count,
                target_collection,
            )
            sys.exit(1)
        logger.info(
            "Validation PASSED: %d points in %s",
            indexed_count,
            target_collection,
        )

    logger.info("=" * 60)
    logger.info("Index rebuild complete.")
    logger.info(
        "To activate: set QDRANT_ACTIVE_COLLECTION=%s in your .env", target_collection
    )
    logger.info("=" * 60)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Rebuild the IUT QBank Qdrant index. DEV-025."
    )
    settings = get_settings()
    parser.add_argument(
        "--collection",
        default=f"{settings.qdrant_active_collection}_rebuild",
        help="Target collection name (default: <active>_rebuild)",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=32,
        help="Embedding batch size (default: 32)",
    )
    parser.add_argument(
        "--no-validate",
        action="store_true",
        help="Skip post-rebuild validation",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    asyncio.run(
        rebuild(
            target_collection=args.collection,
            batch_size=args.batch_size,
            validate=not args.no_validate,
        )
    )
