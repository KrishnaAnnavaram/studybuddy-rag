"""Privacy-scoped learning analytics.

* A **student** view contains only that student's own grades and questions. There are no
  classmates' grades, no other users' queries and no all-user word cloud (the prototype had all
  three). Course averages are shown only when at least ``k`` students contribute to them.
* An **instructor** view contains aggregates only, with any group smaller than ``k`` suppressed.
* "You" is always the authenticated principal passed in; nothing is derived from a loop variable
  (the prototype's highlight bug).
"""
from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass, field
from datetime import timedelta

from .auth import Principal, require_role
from .db import Database, utcnow
from .providers.base import LLM
from .text import tokenize

GRADE_POINTS = {"A": 4, "B": 3, "C": 2, "D": 1, "F": 0}


@dataclass(frozen=True)
class GradeRow:
    course: str
    subject: str
    grade: str

    @property
    def points(self) -> int:
        return GRADE_POINTS[self.grade]


@dataclass(frozen=True)
class HistoryItem:
    asked_at: str
    input_mode: str
    question: str
    subject: str
    answer: str
    citations: list[dict]
    grounded: bool


@dataclass(frozen=True)
class StudentDashboard:
    student: str
    grades: tuple[GradeRow, ...]
    gpa: float | None
    strongest: tuple[str, ...]
    weakest: tuple[str, ...]
    course_averages: dict[str, float]            # only courses with >= k graded students
    questions_by_subject: dict[str, int]
    grounded_rate: float | None
    top_terms: tuple[tuple[str, int], ...]
    recent: tuple[HistoryItem, ...] = field(default=())


@dataclass(frozen=True)
class InstructorOverview:
    grade_distribution: dict[str, dict[str, int]]   # course -> grade -> count (suppressed if < k)
    suppressed_courses: tuple[str, ...]
    questions_by_subject: dict[str, int]            # subjects asked by >= k distinct students


def my_grades(db: Database, principal: Principal) -> list[GradeRow]:
    return [GradeRow(r["course"], r["subject"], r["grade"]) for r in db._grades_for_user(principal.user_id)]


def my_history(db: Database, principal: Principal, *, limit: int = 50) -> list[HistoryItem]:
    return [
        HistoryItem(r["asked_at"], r["input_mode"], r["question"], r["subject"], r["answer"],
                    json.loads(r["citations"]), bool(r["grounded"]))
        for r in db._queries_for_user(principal.user_id, limit)
    ]


def _k_anonymous_course_averages(db: Database, k: int) -> dict[str, float]:
    totals: dict[str, list[int]] = {}
    for row in db._grade_counts_by_course():
        totals.setdefault(row["course"], []).extend([GRADE_POINTS[row["grade"]]] * row["n"])
    return {c: round(sum(v) / len(v), 2) for c, v in totals.items() if len(v) >= k}


def student_dashboard(db: Database, principal: Principal, *, k: int = 3, history_limit: int = 200) -> StudentDashboard:
    grades = tuple(my_grades(db, principal))
    gpa = round(sum(g.points for g in grades) / len(grades), 2) if grades else None
    strongest: tuple[str, ...] = ()
    weakest: tuple[str, ...] = ()
    if grades:
        hi = max(g.points for g in grades)
        lo = min(g.points for g in grades)
        strongest = tuple(g.course for g in grades if g.points == hi)
        weakest = tuple(g.course for g in grades if g.points == lo) if lo < hi else ()
    my_courses = {g.course for g in grades}
    averages = {c: a for c, a in _k_anonymous_course_averages(db, k).items() if c in my_courses}

    history = my_history(db, principal, limit=history_limit)
    by_subject = Counter(h.subject for h in history)
    terms = Counter(t for h in history for t in tokenize(h.question, drop_stopwords=True) if len(t) > 2)
    grounded_rate = round(sum(h.grounded for h in history) / len(history), 3) if history else None
    return StudentDashboard(
        student=principal.display_name,
        grades=grades,
        gpa=gpa,
        strongest=strongest,
        weakest=weakest,
        course_averages=averages,
        questions_by_subject=dict(sorted(by_subject.items())),
        grounded_rate=grounded_rate,
        top_terms=tuple(terms.most_common(15)),
        recent=tuple(history[:10]),
    )


def instructor_overview(db: Database, principal: Principal, *, k: int = 3) -> InstructorOverview:
    require_role(principal, "instructor")
    dist: dict[str, dict[str, int]] = {}
    for row in db._grade_counts_by_course():
        dist.setdefault(row["course"], {})[row["grade"]] = int(row["n"])
    suppressed = tuple(sorted(c for c, g in dist.items() if sum(g.values()) < k))
    visible = {c: g for c, g in dist.items() if c not in suppressed}
    questions = {r["subject"]: int(r["n"]) for r in db._query_counts_by_subject() if r["users"] >= k}
    return InstructorOverview(visible, suppressed, dict(sorted(questions.items())))


def grade_summary(db: Database, principal: Principal, llm: LLM | None = None) -> str:
    """One summary function. The optional LLM only ever sees the caller's own grades."""
    grades = my_grades(db, principal)
    if not grades:
        return "No grades recorded yet."
    lines = [f"{g.course} ({g.subject}): {g.grade}" for g in grades]
    dash_gpa = sum(g.points for g in grades) / len(grades)
    base = f"Grade point average {dash_gpa:.2f} across {len(grades)} courses. " + "; ".join(lines) + "."
    if llm is None:
        return base
    schema = {"type": "object", "properties": {"summary": {"type": "string"}}, "required": ["summary"],
              "additionalProperties": False}
    prompt = ("Write two encouraging sentences on strengths and one concrete study tip, based only on:\n"
              + "\n".join(lines))
    try:
        data = json.loads(llm.complete(prompt, json_schema=schema))
        summary = str(data["summary"]).strip()
    except Exception:  # noqa: BLE001 - an optional nicety must never break the dashboard
        return base
    return summary or base


def purge_old_queries(db: Database, retention_days: int) -> int:
    """Apply the query-log retention policy. Returns the number of deleted rows."""
    if retention_days < 1:
        raise ValueError("retention_days must be >= 1")
    return db.purge_queries_before(utcnow() - timedelta(days=retention_days))
