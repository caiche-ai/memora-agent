from __future__ import annotations

import math
from typing import Any

from ..config import EmbeddingConfig, config
from .provider import ProviderError, request_json


def embedding_enabled(settings: EmbeddingConfig | None = None) -> bool:
    return bool((settings or config.embedding).api_key)


async def embed_texts(texts: list[str], settings: EmbeddingConfig | None = None) -> list[list[float]]:
    current = settings or config.embedding
    normalized = [text.strip()[:8000] for text in texts if text.strip()]
    if not current.api_key or not normalized:
        return []
    try:
        vectors: list[list[float]] = []
        for start in range(0, len(normalized), 10):
            batch = normalized[start : start + 10]
            payload: dict[str, Any] = {"model": current.model, "input": batch}
            if current.dimensions:
                payload["dimensions"] = current.dimensions
            data = await request_json(
                provider="qwen_embedding",
                operation_name="embed_texts",
                method="POST",
                url=f"{current.base_url}/embeddings",
                timeout=45,
                headers={"Authorization": f"Bearer {current.api_key}"},
                json_body=payload,
            )
            items = sorted(data.get("data", []), key=lambda item: item.get("index", 0))
            batch_vectors = [item.get("embedding") for item in items]
            if len(batch_vectors) != len(batch) or not all(isinstance(item, list) for item in batch_vectors):
                return []
            vectors.extend([[float(value) for value in vector] for vector in batch_vectors])
        return vectors
    except (ProviderError, ValueError, TypeError, KeyError):
        return []


async def embed_query(text: str) -> list[float] | None:
    vectors = await embed_texts([text])
    return vectors[0] if vectors else None


def cosine_similarity(left: list[float] | None, right: list[float] | None) -> float:
    if not left or not right or len(left) != len(right):
        return 0.0
    dot = sum(a * b for a, b in zip(left, right, strict=True))
    left_norm = math.sqrt(sum(value * value for value in left))
    right_norm = math.sqrt(sum(value * value for value in right))
    if not left_norm or not right_norm:
        return 0.0
    return dot / (left_norm * right_norm)
