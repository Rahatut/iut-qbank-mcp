"""Sentence-Transformers embedding provider. DEV-022, DEV-023.

EmbeddingProvider implementation using sentence-transformers (BGE family).

The application never depends directly on sentence-transformers — it depends
only on the EmbeddingProvider interface (DEV-050). Swap to OpenAI, Cohere,
or any other provider without changing callers.

Embedding pipeline (DEV-023):
    chunks → EmbeddingProvider → vectors → QdrantStore
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from qbank.infrastructure.config import get_settings
from qbank.processing.interfaces import EmbeddingProvider

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


class SentenceTransformerProvider(EmbeddingProvider):
    """Embedding provider backed by sentence-transformers. DEV-022.

    Lazy-loads the model on first use so import is fast.
    Batches documents according to EMBEDDING_BATCH_SIZE config.
    """

    def __init__(
        self,
        model_name: str | None = None,
        batch_size: int | None = None,
    ) -> None:
        settings = get_settings()
        self._model_name = model_name or settings.embedding_model
        self._batch_size = batch_size or settings.embedding_batch_size
        self._dimension = settings.embedding_dimension
        self._model = None  # lazy-loaded

    # ── Lazy model loading ────────────────────────────────────────────────────

    def _get_model(self):  # type: ignore[return]
        if self._model is None:
            try:
                from sentence_transformers import SentenceTransformer

                logger.info("Loading embedding model: %s", self._model_name)
                self._model = SentenceTransformer(self._model_name)
                dim_getter = getattr(
                    self._model,
                    "get_embedding_dimension",
                    getattr(self._model, "get_sentence_embedding_dimension", None),
                )
                if dim_getter:
                    self._dimension = dim_getter() or self._dimension
                logger.info("Embedding model loaded. Dimension: %d", self._dimension)
            except ImportError as exc:
                raise RuntimeError(
                    "sentence-transformers is not installed. Run: pip install sentence-transformers"
                ) from exc
        return self._model

    # ── EmbeddingProvider interface ───────────────────────────────────────────

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        """Embed a batch of document texts. DEV-022.

        Respects EMBEDDING_BATCH_SIZE from config to avoid OOM on large inputs.
        """
        if not texts:
            return []

        model = self._get_model()
        all_embeddings: list[list[float]] = []

        for i in range(0, len(texts), self._batch_size):
            batch = texts[i : i + self._batch_size]
            embeddings = model.encode(
                batch,
                batch_size=self._batch_size,
                show_progress_bar=False,
                convert_to_numpy=True,
                normalize_embeddings=True,  # cosine similarity friendly
            )
            all_embeddings.extend(emb.tolist() for emb in embeddings)
            logger.debug(
                "Embedded batch %d/%d (%d texts)",
                i // self._batch_size + 1,
                (len(texts) - 1) // self._batch_size + 1,
                len(batch),
            )

        return all_embeddings

    def embed_query(self, text: str) -> list[float]:
        """Embed a single query string. DEV-022."""
        model = self._get_model()
        embedding = model.encode(
            text,
            show_progress_bar=False,
            convert_to_numpy=True,
            normalize_embeddings=True,
        )
        return embedding.tolist()  # type: ignore[union-attr]

    @property
    def model_name(self) -> str:
        return self._model_name

    @property
    def dimension(self) -> int:
        return self._dimension
