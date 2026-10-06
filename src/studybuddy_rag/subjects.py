"""The closed label set used by the subject router. Anything outside it is rejected."""
from __future__ import annotations

from enum import Enum


class Subject(str, Enum):
    ARTS = "arts"
    MATHEMATICS = "mathematics"
    SCIENCE = "science"
    GENERAL = "general"

    @classmethod
    def parse(cls, value: object) -> "Subject":
        """Strictly parse a label. Only an exact (case/whitespace-insensitive) label is accepted.

        ``"science"`` and ``" Science "`` parse; ``"This question is about science."`` does not.
        """
        if isinstance(value, Subject):
            return value
        if not isinstance(value, str):
            raise ValueError(f"subject label must be a string, got {type(value).__name__}")
        norm = value.strip().lower()
        for member in cls:
            if member.value == norm:
                return member
        raise ValueError(f"{value!r} is not one of {[m.value for m in cls]}")

    @property
    def has_corpus(self) -> bool:
        """``general`` questions are answered without subject retrieval."""
        return self is not Subject.GENERAL


SUBJECT_LABELS: tuple[str, ...] = tuple(s.value for s in Subject)
CORPUS_SUBJECTS: tuple[Subject, ...] = tuple(s for s in Subject if s.has_corpus)
