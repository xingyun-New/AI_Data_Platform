"""DashScope embedding wrapper — batched text embedding via the OpenAI-compatible API.

Reuses the same AsyncOpenAI client pattern as `ai_service` so no new dependency is needed.
Vectors are kept as Python lists (list[float]); encoding/decoding to bytes is handled by
`pack_vector` / `unpack_vector` for BLOB storage.
"""

from __future__ import annotations

import asyncio
import logging
import struct

from openai import AsyncOpenAI

from app.config import settings

logger = logging.getLogger(__name__)

_client: AsyncOpenAI | None = None


def _get_client() -> AsyncOpenAI:
    """Lazy-init a singleton AsyncOpenAI client pointing to DashScope."""
    global _client
    if _client is None:
        _client = AsyncOpenAI(
            api_key=settings.dashscope_api_key,
            base_url=settings.dashscope_base_url,
        )
    return _client


async def embed_texts(
    texts: list[str],
    *,
    model: str | None = None,
    dimensions: int | None = None,
    retries: int = 3,
) -> list[list[float]]:
    """Embed a list of texts in batches, preserving input order.

    DashScope's text-embedding-v3 accepts up to ~25 items per call; we chunk by
    `settings.kg_embedding_batch_size` (default 10) for safety.

    Returns a list of vectors (list[float]) aligned with the input order.
    Raises on persistent failures after retries.
    """
    if not texts:
        return []

    model_name = model or settings.kg_embedding_model
    dim = dimensions or settings.kg_embedding_dim
    batch_size = max(1, settings.kg_embedding_batch_size)

    client = _get_client()
    results: list[list[float]] = []

    for start in range(0, len(texts), batch_size):
        batch = texts[start:start + batch_size]
        last_err: Exception | None = None
        for attempt in range(retries):
            try:
                resp = await client.embeddings.create(
                    model=model_name,
                    input=batch,
                    dimensions=dim,
                )
                for item in resp.data:
                    results.append(list(item.embedding))
                break
            except Exception as exc:
                last_err = exc
                if attempt < retries - 1:
                    wait = 2 ** attempt
                    logger.warning(
                        "Embedding batch failed (attempt %d/%d): %s. Retrying in %ds",
                        attempt + 1, retries, exc, wait,
                    )
                    await asyncio.sleep(wait)
                else:
                    logger.error("Embedding batch failed after %d attempts: %s", retries, exc)
                    raise last_err from exc

    if len(results) != len(texts):
        raise RuntimeError(
            f"Embedding mismatch: requested {len(texts)} got {len(results)}"
        )
    return results


async def embed_text(text: str) -> list[float]:
    """Convenience wrapper: embed a single text, return a single vector."""
    vectors = await embed_texts([text])
    return vectors[0]


def pack_vector(vec: list[float]) -> bytes:
    """Pack a float32 vector into compact bytes for BLOB storage."""
    return struct.pack(f"{len(vec)}f", *vec)


def unpack_vector(blob: bytes, dim: int) -> list[float]:
    """Reverse of pack_vector. Returns a list[float] of length *dim*."""
    if not blob:
        return []
    return list(struct.unpack(f"{dim}f", blob[: dim * 4]))


def cosine_similarity(a: list[float], b: list[float]) -> float:
    """Plain cosine similarity without numpy, good enough for <=1024-dim vectors."""
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = 0.0
    na = 0.0
    nb = 0.0
    for x, y in zip(a, b):
        dot += x * y
        na += x * x
        nb += y * y
    if na == 0.0 or nb == 0.0:
        return 0.0
    return dot / ((na ** 0.5) * (nb ** 0.5))


def weighted_mean(
    old_vec: list[float],
    old_weight: int,
    new_vec: list[float],
) -> list[float]:
    """Update the centroid when merging a new observation into an existing entity.

    new = (old * n + new_vec) / (n + 1)
    """
    if not old_vec:
        return list(new_vec)
    if not new_vec:
        return list(old_vec)
    n = max(1, old_weight)
    return [(a * n + b) / (n + 1) for a, b in zip(old_vec, new_vec)]
