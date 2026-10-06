"""Hybrid retrieval: dense cosine similarity + BM25, filtered by subject, returning the top-k chunks.

The index is built once (offline, ``studybuddy ingest``) and persisted to SQLite together with the
name of the embedder that produced it, so queries never re-embed the corpus.
"""
from __future__ import annotations

import json
import math
import sqlite3
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from .ingest import Chunk
from .providers.base import Embedder
from .subjects import Subject
from .text import terms


@dataclass(frozen=True)
class ScoredChunk:
    chunk: Chunk
    score: float
    dense: float
    sparse: float


class _BM25:
    def __init__(self, docs: list[list[str]], k1: float = 1.5, b: float = 0.75) -> None:
        self.k1, self.b = k1, b
        self.tfs = [Counter(d) for d in docs]
        self.lens = [len(d) for d in docs]
        self.avgdl = (sum(self.lens) / len(self.lens)) if docs else 0.0
        df: Counter[str] = Counter()
        for d in docs:
            df.update(set(d))
        n = len(docs)
        self.idf = {t: math.log(1 + (n - f + 0.5) / (f + 0.5)) for t, f in df.items()}

    def score(self, query: list[str], i: int) -> float:
        tf, dl = self.tfs[i], self.lens[i]
        s = 0.0
        for term in query:
            f = tf.get(term, 0)
            if f:
                denom = f + self.k1 * (1 - self.b + self.b * dl / (self.avgdl or 1.0))
                s += self.idf.get(term, 0.0) * f * (self.k1 + 1) / denom
        return s


class HybridIndex:
    def __init__(self, chunks: list[Chunk], vectors: list[list[float]], embedder: Embedder,
                 *, dense_weight: float = 0.6) -> None:
        if len(chunks) != len(vectors):
            raise ValueError("chunks and vectors must have the same length")
        if not 0.0 <= dense_weight <= 1.0:
            raise ValueError("dense_weight must be in [0, 1]")
        self.chunks = list(chunks)
        self.vectors = vectors
        self.embedder = embedder
        self.dense_weight = dense_weight
        self._bm25 = _BM25([terms(f"{c.section} {c.text}") for c in self.chunks])

    @classmethod
    def build(cls, chunks: list[Chunk], embedder: Embedder, **kwargs) -> "HybridIndex":
        vectors = embedder.embed([f"{c.section}. {c.text}" for c in chunks]) if chunks else []
        return cls(chunks, vectors, embedder, **kwargs)

    def __len__(self) -> int:
        return len(self.chunks)

    def subjects(self) -> set[Subject]:
        return {c.subject for c in self.chunks}

    def search(self, query: str, *, k: int = 4, subject: Subject | None = None,
               min_score: float = 0.0) -> list[ScoredChunk]:
        if k < 1:
            raise ValueError("k must be >= 1")
        candidates = [i for i, c in enumerate(self.chunks) if subject is None or c.subject == subject]
        if not candidates or not query.strip():
            return []
        qvec = self.embedder.embed([query])[0]
        qtok = terms(query)
        dense = {i: sum(a * b for a, b in zip(qvec, self.vectors[i])) for i in candidates}
        sparse = {i: self._bm25.score(qtok, i) for i in candidates}
        max_sparse = max(sparse.values()) or 1.0
        results = []
        for i in candidates:
            s = self.dense_weight * max(dense[i], 0.0) + (1 - self.dense_weight) * sparse[i] / max_sparse
            if s >= min_score and s > 0:
                results.append(ScoredChunk(self.chunks[i], round(s, 6), dense[i], sparse[i]))
        results.sort(key=lambda r: (-r.score, r.chunk.chunk_id))
        return results[:k]

    # ---- persistence -------------------------------------------------------------------------
    def save(self, path: str | Path) -> None:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(path) as conn:
            conn.execute("DROP TABLE IF EXISTS chunks")
            conn.execute("DROP TABLE IF EXISTS index_meta")
            conn.execute(
                "CREATE TABLE chunks (chunk_id TEXT PRIMARY KEY, source_id TEXT, title TEXT, subject TEXT,"
                " section TEXT, page INTEGER, position INTEGER, text TEXT, vector TEXT)"
            )
            conn.execute("CREATE TABLE index_meta (key TEXT PRIMARY KEY, value TEXT)")
            conn.executemany(
                "INSERT INTO chunks VALUES (?,?,?,?,?,?,?,?,?)",
                [
                    (c.chunk_id, c.source_id, c.title, c.subject.value, c.section, c.page, c.position,
                     c.text, json.dumps([round(x, 6) for x in v]))
                    for c, v in zip(self.chunks, self.vectors)
                ],
            )
            conn.execute("INSERT INTO index_meta VALUES ('embedder', ?)", (self.embedder.name,))

    @classmethod
    def load(cls, path: str | Path, embedder: Embedder, **kwargs) -> "HybridIndex":
        if not Path(path).is_file():
            raise FileNotFoundError(f"index not found: {path} (run `studybuddy ingest`)")
        with sqlite3.connect(path) as conn:
            row = conn.execute("SELECT value FROM index_meta WHERE key='embedder'").fetchone()
            if row is None or row[0] != embedder.name:
                raise ValueError(
                    f"index was built with {row[0] if row else '?'} but the configured embedder is "
                    f"{embedder.name}; rebuild it with `studybuddy ingest`"
                )
            rows = conn.execute(
                "SELECT chunk_id, source_id, title, subject, section, page, position, text, vector"
                " FROM chunks ORDER BY source_id, position"
            ).fetchall()
        chunks = [Chunk(r[0], r[1], r[2], Subject.parse(r[3]), r[4], r[7], r[5], r[6]) for r in rows]
        return cls(chunks, [json.loads(r[8]) for r in rows], embedder, **kwargs)
