"""Embedding providers.

``HashingEmbedder`` is a deterministic, dependency-free bag-of-words embedder (feature hashing of
unigrams and bigrams) used offline and in tests. ``SentenceTransformerEmbedder`` wraps a real model
and loads it **once per process** (the prototype reloaded it on every query).
"""
from __future__ import annotations

import hashlib
import math
from collections import Counter
from functools import lru_cache

from ..text import terms


def _normalise(vec: list[float]) -> list[float]:
    norm = math.sqrt(sum(v * v for v in vec))
    return [v / norm for v in vec] if norm > 0 else vec


class HashingEmbedder:
    def __init__(self, dim: int = 1024) -> None:
        if dim < 16:
            raise ValueError("dim must be >= 16")
        self.dim = dim
        self.name = f"hashing-{dim}"

    def _features(self, text: str) -> Counter[str]:
        toks = terms(text)
        feats: Counter[str] = Counter(toks)
        feats.update(f"{a}_{b}" for a, b in zip(toks, toks[1:]))
        return feats

    def embed(self, texts: list[str]) -> list[list[float]]:
        out = []
        for text in texts:
            vec = [0.0] * self.dim
            for feat, count in self._features(text).items():
                h = int.from_bytes(hashlib.blake2b(feat.encode(), digest_size=8).digest(), "big")
                sign = 1.0 if (h >> 63) & 1 else -1.0
                vec[h % self.dim] += sign * (1.0 + math.log(count))
            out.append(_normalise(vec))
        return out


@lru_cache(maxsize=4)
def _load_sentence_transformer(model_name: str):  # pragma: no cover - needs the optional extra
    try:
        from sentence_transformers import SentenceTransformer  # type: ignore[import-not-found]
    except ImportError as exc:
        raise RuntimeError(
            "STUDYBUDDY_EMBEDDING_PROVIDER=sentence-transformers needs: pip install 'studybuddy-rag[embeddings]'"
        ) from exc
    return SentenceTransformer(model_name)


class SentenceTransformerEmbedder:  # pragma: no cover - needs the optional extra
    def __init__(self, model_name: str = "all-MiniLM-L6-v2") -> None:
        self._model = _load_sentence_transformer(model_name)
        self.dim = int(self._model.get_sentence_embedding_dimension())
        self.name = f"st:{model_name}"

    def embed(self, texts: list[str]) -> list[list[float]]:
        vectors = self._model.encode(texts, normalize_embeddings=True, convert_to_numpy=True)
        return [list(map(float, v)) for v in vectors]
