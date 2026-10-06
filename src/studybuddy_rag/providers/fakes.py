"""Deterministic offline providers for tests and the no-API-key demo mode."""
from __future__ import annotations

import json
import re

from ..text import split_sentences, tokenize

_LEXICON: dict[str, set[str]] = {
    "mathematics": {"fraction", "fractions", "decimal", "decimals", "equation", "equations", "algebra",
                    "triangle", "angle", "angles", "area", "perimeter", "percent", "percentage", "solve",
                    "multiply", "divide", "sum", "number", "numbers", "prime", "arithmetic", "progression",
                    "sequence", "geometry", "denominator", "numerator", "slope", "linear", "hypotenuse"},
    "science": {"photosynthesis", "cell", "cells", "plant", "plants", "energy", "force", "gravity",
                "atom", "atoms", "molecule", "chemical", "reaction", "water", "evaporation", "cycle",
                "electricity", "circuit", "light", "chlorophyll", "newton", "motion", "mass", "oxygen",
                "condensation", "organism", "respiration", "acceleration"},
    "arts": {"painting", "paint", "colour", "color", "colors", "colours", "music", "rhythm", "melody",
             "sculpture", "art", "artist", "drawing", "perspective", "tempo", "dance", "poetry",
             "poem", "texture", "hue", "palette", "harmony", "composition", "complementary"},
}

_CITE_LINE_RE = re.compile(r"^\[(\d+)\]\s*(?:\([^)]*\)\s*)?(.*)$")


def _keyword_subject(text: str) -> tuple[str, float]:
    toks = set(tokenize(text))
    scores = {label: len(toks & words) for label, words in _LEXICON.items()}
    best = max(scores, key=lambda k: scores[k])
    if scores[best] == 0:
        return "general", 0.6
    total = sum(scores.values())
    return best, round(scores[best] / total, 3)


class FakeLLM:
    """Behaves like a well-behaved, deterministic model.

    * With a subject-classification schema it returns ``{"subject": ..., "confidence": ...}``.
    * For an answer prompt it extracts the source sentence that best overlaps the question and
      cites it as ``[n]``; with no sources it gives a short, clearly ungrounded reply.
    """

    name = "fake-llm"

    def __init__(self) -> None:
        self.calls: list[dict] = []

    def complete(self, prompt: str, *, system: str = "", json_schema: dict | None = None) -> str:
        self.calls.append({"prompt": prompt, "system": system, "json_schema": json_schema})
        props = (json_schema or {}).get("properties", {})
        if "subject" in props:
            question = prompt.rsplit("Question:", 1)[-1]
            subject, conf = _keyword_subject(question)
            return json.dumps({"subject": subject, "confidence": conf})
        if "summary" in props:
            return json.dumps({"summary": "Deterministic summary: " + prompt.splitlines()[-1][:160]})
        return self._answer(prompt)

    @staticmethod
    def _answer(prompt: str) -> str:
        question = prompt.rsplit("Question:", 1)[-1].strip()
        q_tokens = set(tokenize(question, drop_stopwords=True))
        best: tuple[int, int, str] | None = None
        for line in prompt.splitlines():
            m = _CITE_LINE_RE.match(line.strip())
            if not m:
                continue
            n, body = int(m.group(1)), m.group(2)
            for sentence in split_sentences(body):
                overlap = len(q_tokens & set(tokenize(sentence, drop_stopwords=True)))
                if best is None or overlap > best[0]:
                    best = (overlap, n, sentence)
        if best is None or best[0] == 0:
            return "I could not find this in the study material, so treat this as a general answer."
        return f"{best[2]} [{best[1]}]"


class ScriptedLLM:
    """Returns pre-set responses in order and records every prompt (for unit tests)."""

    def __init__(self, responses: list[str], name: str = "scripted-llm") -> None:
        self._responses = list(responses)
        self.name = name
        self.calls: list[dict] = []

    def complete(self, prompt: str, *, system: str = "", json_schema: dict | None = None) -> str:
        self.calls.append({"prompt": prompt, "system": system, "json_schema": json_schema})
        if not self._responses:
            raise AssertionError("ScriptedLLM ran out of responses")
        return self._responses.pop(0)


class FakeSpeechToText:
    """Returns a fixed transcript (or the UTF-8 text of the 'audio' when it starts with ``TEXT:``)."""

    name = "fake-stt"

    def __init__(self, transcript: str = "What is photosynthesis?") -> None:
        self.transcript = transcript
        self.calls = 0

    def transcribe(self, audio: bytes, *, mime_type: str = "audio/wav") -> str:
        self.calls += 1
        if not audio:
            raise ValueError("empty audio")
        if audio.startswith(b"TEXT:"):
            return audio[5:].decode("utf-8").strip()
        return self.transcript
