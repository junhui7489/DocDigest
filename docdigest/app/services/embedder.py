"""Text embedding service for vector search.

Supports Voyage AI embeddings (recommended for use with Claude)
with a fallback to a simple local hashing approach for development.
"""

from __future__ import annotations

import logging
from typing import Optional

import numpy as np

from app.config import settings

logger = logging.getLogger(__name__)

# Embedding dimension for voyage-3
EMBEDDING_DIM = 1024

_voyage_client: Optional[object] = None


def _get_voyage_client():
    """Lazy-initialise the Voyage AI client."""
    global _voyage_client
    if _voyage_client is None:
        try:
            import voyageai
            # Set API key from environment/config if available
            api_key = getattr(settings, "voyage_api_key", None)
            if not api_key:
                import os
                api_key = os.getenv("VOYAGE_API_KEY")
            if api_key:
                _voyage_client = voyageai.Client(api_key=api_key)
                logger.info("Voyage AI client initialised with API key.")
            else:
                _voyage_client = voyageai.Client()
                logger.info("Voyage AI client initialised (no explicit API key set, relying on environment variable).")
        except ImportError:
            logger.warning(
                "voyageai package not installed. "
                "Using fallback hash-based embeddings (not for production)."
            )
            _voyage_client = "fallback"
    return _voyage_client


async def embed_texts(texts: list[str]) -> list[list[float]]:
    """Embed a batch of texts into vectors.

    Args:
        texts: List of text strings to embed.

    Returns:
        List of embedding vectors (each a list of floats).
    """
    client = _get_voyage_client()

    if client == "fallback":
        return [_fallback_embed(t) for t in texts]

    # Voyage AI supports batching up to 128 texts
    all_embeddings: list[list[float]] = []
    batch_size = 128

    for i in range(0, len(texts), batch_size):
        batch = texts[i : i + batch_size]
        try:
            result = client.embed(
                batch,
                model=settings.embedding_model,
                input_type="document",
            )
            all_embeddings.extend(result.embeddings)
        except Exception as e:
            logger.error("Embedding batch failed: %s", e)
            # Fall back for this batch
            all_embeddings.extend([_fallback_embed(t) for t in batch])

    return all_embeddings


async def embed_query(text: str) -> list[float]:
    """Embed a single query text (uses 'query' input type for asymmetric search)."""
    client = _get_voyage_client()

    if client == "fallback":
        return _fallback_embed(text)

    try:
        result = client.embed(
            [text],
            model=settings.embedding_model,
            input_type="query",
        )
        return result.embeddings[0]
    except Exception as e:
        logger.error("Query embedding failed: %s", e)
        return _fallback_embed(text)


def _fallback_embed(text: str) -> list[float]:
    """Deterministic hash-based embedding for development/testing.

    WARNING: Not suitable for production — no semantic understanding.
    """
    import hashlib
    h = hashlib.sha256(text.encode()).digest()
    rng = np.random.RandomState(int.from_bytes(h[:4], "big"))
    vec = rng.randn(EMBEDDING_DIM).tolist()
    # Normalise to unit length
    norm = sum(x * x for x in vec) ** 0.5
    return [x / norm for x in vec]
