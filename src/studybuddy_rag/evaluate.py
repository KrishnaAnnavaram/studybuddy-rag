"""Evaluation harness: router accuracy, retrieval recall@k / MRR, and answer citation rate."""
from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from .index import HybridIndex
from .router import Router
from .subjects import Subject
from .tutor import Tutor


@dataclass(frozen=True)
class EvalItem:
    question: str
    subject: Subject
    source_id: str
    section: str


@dataclass(frozen=True)
class EvalReport:
    n: int
    router_accuracy: float
    confusion: dict[str, dict[str, int]]
    recall_at_k: float
    mrr: float
    k: int
    citation_rate: float | None = None

    def as_dict(self) -> dict:
        return self.__dict__.copy()


def load_eval_set(path: str | Path) -> list[EvalItem]:
    items = []
    for line_no, line in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        row = json.loads(line)
        try:
            items.append(EvalItem(row["question"], Subject.parse(row["subject"]), row.get("source_id", ""),
                                  row.get("section", "")))
        except (KeyError, ValueError) as exc:
            raise ValueError(f"{path}:{line_no}: {exc}") from exc
    return items


def evaluate(items: list[EvalItem], router: Router, index: HybridIndex, *, k: int = 4,
             tutor: Tutor | None = None) -> EvalReport:
    if not items:
        raise ValueError("empty eval set")
    correct = 0
    confusion: dict[str, Counter[str]] = {}
    hits = 0
    rr_total = 0.0
    retrieval_n = 0
    cited = 0
    answered = 0
    for item in items:
        decision = router.route(item.question)
        correct += decision.subject == item.subject
        confusion.setdefault(item.subject.value, Counter())[decision.subject.value] += 1
        if item.source_id:
            retrieval_n += 1
            results = index.search(item.question, k=k, subject=item.subject)
            for rank, r in enumerate(results, start=1):
                if r.chunk.source_id == item.source_id and (not item.section or r.chunk.section == item.section):
                    hits += 1
                    rr_total += 1.0 / rank
                    break
            if tutor is not None:
                answered += 1
                cited += tutor.answer(item.question).grounded
    return EvalReport(
        n=len(items),
        router_accuracy=round(correct / len(items), 3),
        confusion={g: dict(c) for g, c in sorted(confusion.items())},
        recall_at_k=round(hits / retrieval_n, 3) if retrieval_n else 0.0,
        mrr=round(rr_total / retrieval_n, 3) if retrieval_n else 0.0,
        k=k,
        citation_rate=round(cited / answered, 3) if answered else None,
    )
