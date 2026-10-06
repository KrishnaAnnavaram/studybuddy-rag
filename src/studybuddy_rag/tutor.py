"""The question-answering pipeline: greeting check -> route -> retrieve top-k -> answer with citations.

Routing *narrows* retrieval, it never disables it: if the routed subject has no relevant chunk the
whole corpus is searched, and ``general`` questions still get a (stricter) corpus search. Answers
cite numbered sources; citations are validated and an answer without a valid citation is flagged
as ungrounded instead of being presented as course material.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from .index import HybridIndex, ScoredChunk
from .providers.base import LLM
from .router import RouteDecision, Router
from .subjects import Subject

ANSWER_SYSTEM = (
    "You are a patient tutor for school students. Answer the question using ONLY the numbered "
    "sources. Put the source number in square brackets after each claim, e.g. [2]. If the sources "
    "do not contain the answer, say that the study material does not cover it. Keep it short and clear."
)
GENERAL_SYSTEM = (
    "You are a friendly study assistant. No study material matched this question, so answer briefly "
    "from general knowledge and say that the answer is not from the course material."
)

_GREETING_RE = re.compile(
    r"^\s*(hi|hii+|hello|hey|hey there|hello there|good (morning|afternoon|evening)|bye|goodbye|thanks|"
    r"thank you)\s*[!.,]*\s*$",
    re.IGNORECASE,
)
_CITATION_RE = re.compile(r"\[(\d{1,2})\]")


@dataclass(frozen=True)
class Citation:
    number: int
    chunk_id: str
    title: str
    section: str
    page: int | None
    subject: str
    score: float
    snippet: str

    def label(self) -> str:
        page = f", p. {self.page}" if self.page is not None else ""
        return f"[{self.number}] {self.title} - {self.section}{page}"

    def as_dict(self) -> dict:
        return {"n": self.number, "chunk_id": self.chunk_id, "title": self.title, "section": self.section,
                "page": self.page, "subject": self.subject, "score": self.score}


@dataclass(frozen=True)
class TutorAnswer:
    question: str
    text: str
    kind: str                       # greeting | grounded | ungrounded
    route: RouteDecision | None
    sources: tuple[Citation, ...] = ()
    cited: tuple[Citation, ...] = ()
    notes: tuple[str, ...] = field(default=())

    @property
    def grounded(self) -> bool:
        return self.kind == "grounded"

    @property
    def subject(self) -> Subject:
        return self.route.subject if self.route else Subject.GENERAL


def is_greeting(text: str) -> bool:
    return bool(_GREETING_RE.match(text))


def build_answer_prompt(question: str, hits: list[ScoredChunk]) -> str:
    lines = ["Sources:"]
    for n, hit in enumerate(hits, start=1):
        lines.append(f"[{n}] ({hit.chunk.citation_label()}) {hit.chunk.text}")
    lines += ["", f"Question: {question}"]
    return "\n".join(lines)


def extract_citations(text: str, n_sources: int) -> tuple[list[int], list[int]]:
    """Return (valid, invalid) citation numbers in first-seen order."""
    valid: list[int] = []
    invalid: list[int] = []
    for m in _CITATION_RE.finditer(text):
        n = int(m.group(1))
        bucket = valid if 1 <= n <= n_sources else invalid
        if n not in bucket:
            bucket.append(n)
    return valid, invalid


class Tutor:
    def __init__(self, llm: LLM, index: HybridIndex, router: Router, *, top_k: int = 4,
                 min_score: float = 0.05, general_min_score: float = 0.25) -> None:
        self.llm = llm
        self.index = index
        self.router = router
        self.top_k = top_k
        self.min_score = min_score
        self.general_min_score = general_min_score

    def retrieve(self, question: str, route: RouteDecision) -> tuple[list[ScoredChunk], list[str]]:
        notes: list[str] = []
        if route.subject.has_corpus:
            hits = self.index.search(question, k=self.top_k, subject=route.subject, min_score=self.min_score)
            if hits:
                return hits, notes
            notes.append(f"no {route.subject.value} passage matched; searched all subjects")
            return self.index.search(question, k=self.top_k, min_score=self.min_score), notes
        return self.index.search(question, k=self.top_k, min_score=self.general_min_score), notes

    def answer(self, question: str) -> TutorAnswer:
        question = " ".join(question.split())
        if not question:
            raise ValueError("question is empty")
        if is_greeting(question):
            return TutorAnswer(question, "Hello! Ask me anything about arts, mathematics or science.",
                               "greeting", None)

        route = self.router.route(question)
        hits, notes = self.retrieve(question, route)
        sources = tuple(
            Citation(n, h.chunk.chunk_id, h.chunk.title, h.chunk.section, h.chunk.page, h.chunk.subject.value,
                     h.score, h.chunk.text[:240])
            for n, h in enumerate(hits, start=1)
        )
        if not hits:
            text = self.llm.complete(f"Question: {question}", system=GENERAL_SYSTEM)
            return TutorAnswer(question, text.strip(), "ungrounded", route, (), (),
                               tuple(notes + ["no study material matched"]))

        text = self.llm.complete(build_answer_prompt(question, hits), system=ANSWER_SYSTEM).strip()
        valid, invalid = extract_citations(text, len(sources))
        if invalid:
            notes.append(f"removed citations to non-existent sources: {invalid}")
            text = _CITATION_RE.sub(lambda m: m.group(0) if int(m.group(1)) in valid else "", text).strip()
        cited = tuple(sources[n - 1] for n in valid)
        if not cited:
            notes.append("the answer did not cite the retrieved material")
        kind = "grounded" if cited else "ungrounded"
        return TutorAnswer(question, text, kind, route, sources, cited, tuple(notes))
