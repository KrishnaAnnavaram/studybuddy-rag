"""Subject routing as a strict classifier over a validated label set.

The prototype sent its classification prompt through the *answer* prompt, got a paragraph back and
compared it with ``in ["arts", ...]`` - so retrieval almost never ran. Here:

* ``LLMRouter`` makes a dedicated classification call with a JSON schema whose ``subject`` is an
  enum, then **validates** the reply (``parse_route_output``). Prose, unknown labels, missing
  fields or out-of-range confidences are rejected, never fuzzily accepted.
* A rejected reply falls back to an embedding classifier (``CentroidRouter``), so a flaky model
  degrades routing quality instead of silently disabling retrieval.
"""
from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass
from typing import Protocol

from .providers.base import LLM, Embedder, ProviderError
from .subjects import SUBJECT_LABELS, Subject

ROUTER_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "subject": {"type": "string", "enum": list(SUBJECT_LABELS)},
        "confidence": {"type": "number"},
    },
    "required": ["subject", "confidence"],
    "additionalProperties": False,
}

ROUTER_SYSTEM = (
    "You are a classifier. Label the student's question with exactly one subject. "
    "Use 'general' for greetings, study skills or anything outside arts, mathematics and science. "
    'Reply with JSON only, e.g. {"subject": "science", "confidence": 0.9}.'
)

_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE)


class RouterOutputError(ValueError):
    """The classifier's reply did not match the schema."""


@dataclass(frozen=True)
class RouteDecision:
    subject: Subject
    confidence: float
    method: str          # "llm", "centroid", "fallback-default"
    detail: str = ""


class Router(Protocol):
    def route(self, question: str) -> RouteDecision: ...


def parse_route_output(raw: str) -> tuple[Subject, float]:
    """Validate a classifier reply against ``ROUTER_SCHEMA``. Raises ``RouterOutputError``."""
    text = _FENCE_RE.sub("", raw.strip())
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise RouterOutputError(f"not JSON: {raw[:80]!r}") from exc
    if not isinstance(data, dict):
        raise RouterOutputError("expected a JSON object")
    extra = set(data) - {"subject", "confidence"}
    if extra:
        raise RouterOutputError(f"unexpected fields: {sorted(extra)}")
    if "subject" not in data or "confidence" not in data:
        raise RouterOutputError("missing 'subject' or 'confidence'")
    try:
        subject = Subject.parse(data["subject"])
    except ValueError as exc:
        raise RouterOutputError(str(exc)) from exc
    conf = data["confidence"]
    if isinstance(conf, bool) or not isinstance(conf, (int, float)) or not math.isfinite(conf):
        raise RouterOutputError("confidence must be a number")
    if not 0.0 <= float(conf) <= 1.0:
        raise RouterOutputError("confidence must be within [0, 1]")
    return subject, float(conf)


class CentroidRouter:
    """Nearest-centroid embedding classifier.

    Each corpus subject is represented by the mean embedding of its labelled examples (or its
    corpus chunks). If the best cosine similarity is below ``min_similarity`` the question is
    routed to ``general``.
    """

    def __init__(self, embedder: Embedder, centroids: dict[Subject, list[float]],
                 *, min_similarity: float = 0.08) -> None:
        if not centroids:
            raise ValueError("at least one centroid is required")
        self.embedder = embedder
        self.centroids = centroids
        self.min_similarity = min_similarity

    @classmethod
    def from_examples(cls, embedder: Embedder, examples: dict[Subject, list[str]], **kw) -> "CentroidRouter":
        centroids = {}
        for subject, texts in examples.items():
            if subject.has_corpus and texts:
                centroids[subject] = _mean(embedder.embed(texts))
        return cls(embedder, centroids, **kw)

    @classmethod
    def from_index(cls, index, **kw) -> "CentroidRouter":
        groups: dict[Subject, list[list[float]]] = {}
        for chunk, vec in zip(index.chunks, index.vectors):
            groups.setdefault(chunk.subject, []).append(vec)
        return cls(index.embedder, {s: _mean(v) for s, v in groups.items()}, **kw)

    def route(self, question: str) -> RouteDecision:
        q = self.embedder.embed([question])[0]
        sims = {s: sum(a * b for a, b in zip(q, c)) for s, c in self.centroids.items()}
        best = max(sims, key=lambda s: sims[s])
        if sims[best] < self.min_similarity:
            return RouteDecision(Subject.GENERAL, 1.0 - max(sims[best], 0.0), "centroid", "below threshold")
        ordered = sorted(sims.values(), reverse=True)
        margin = ordered[0] - (ordered[1] if len(ordered) > 1 else 0.0)
        return RouteDecision(best, round(min(1.0, 0.5 + margin), 3), "centroid")


class LLMRouter:
    def __init__(self, llm: LLM, fallback: Router | None = None, *, retries: int = 1) -> None:
        self.llm = llm
        self.fallback = fallback
        self.retries = max(0, retries)

    def route(self, question: str) -> RouteDecision:
        prompt = f"Subjects: {', '.join(SUBJECT_LABELS)}\nQuestion: {question.strip()}"
        errors: list[str] = []
        for _ in range(self.retries + 1):
            try:
                raw = self.llm.complete(prompt, system=ROUTER_SYSTEM, json_schema=ROUTER_SCHEMA)
                subject, conf = parse_route_output(raw)
                return RouteDecision(subject, conf, "llm")
            except (RouterOutputError, ProviderError) as exc:
                errors.append(str(exc))
        if self.fallback is not None:
            decision = self.fallback.route(question)
            return RouteDecision(decision.subject, decision.confidence, decision.method,
                                 "llm output rejected: " + "; ".join(errors))
        return RouteDecision(Subject.GENERAL, 0.0, "fallback-default", "; ".join(errors))


def _mean(vectors: list[list[float]]) -> list[float]:
    dim = len(vectors[0])
    m = [sum(v[i] for v in vectors) / len(vectors) for i in range(dim)]
    norm = math.sqrt(sum(x * x for x in m)) or 1.0
    return [x / norm for x in m]
