"""Reference problem 1: the router must be a strict classifier, so retrieval actually runs."""
import json

import pytest

from studybuddy_rag.providers.base import ProviderError
from studybuddy_rag.providers.fakes import FakeLLM, ScriptedLLM
from studybuddy_rag.router import (
    ROUTER_SCHEMA,
    CentroidRouter,
    LLMRouter,
    RouterOutputError,
    parse_route_output,
)
from studybuddy_rag.subjects import SUBJECT_LABELS, Subject


def test_label_set_is_closed():
    assert SUBJECT_LABELS == ("arts", "mathematics", "science", "general")
    assert ROUTER_SCHEMA["properties"]["subject"]["enum"] == list(SUBJECT_LABELS)
    assert Subject.parse(" Science ") is Subject.SCIENCE
    with pytest.raises(ValueError):
        Subject.parse("physics")


@pytest.mark.parametrize(
    "raw",
    [
        "This question is about science, specifically photosynthesis.",   # the prototype's failure mode
        "science",                                                         # bare word, not JSON
        '{"subject": "physics", "confidence": 0.9}',                      # outside the label set
        '{"subject": "science"}',                                          # missing confidence
        '{"subject": "science", "confidence": 1.7}',                      # out of range
        '{"subject": "science", "confidence": true}',
        '{"subject": "science", "confidence": 0.9, "reason": "x"}',       # extra field
        '["science"]',
    ],
)
def test_parse_rejects_anything_but_the_schema(raw):
    with pytest.raises(RouterOutputError):
        parse_route_output(raw)


def test_parse_accepts_valid_json_and_code_fences():
    assert parse_route_output('{"subject": "arts", "confidence": 0.8}') == (Subject.ARTS, 0.8)
    assert parse_route_output('```json\n{"subject": "Mathematics", "confidence": 1}\n```') == (
        Subject.MATHEMATICS, 1.0)


def test_classification_is_a_dedicated_call_with_schema():
    llm = ScriptedLLM([json.dumps({"subject": "science", "confidence": 0.93})])
    decision = LLMRouter(llm).route("How does photosynthesis work?")
    assert decision.subject is Subject.SCIENCE and decision.method == "llm"
    call = llm.calls[0]
    assert call["json_schema"] is ROUTER_SCHEMA
    # not wrapped in an answer-generation prompt (the prototype's bug)
    assert "detailed" not in call["prompt"].lower() and "Context" not in call["prompt"]


def test_retries_then_falls_back_to_embedding_classifier(index):
    llm = ScriptedLLM(["Sure! This is about science.", "Science, definitely."])
    router = LLMRouter(llm, fallback=CentroidRouter.from_index(index), retries=1)
    decision = router.route("Explain photosynthesis and chlorophyll in leaves")
    assert len(llm.calls) == 2
    assert decision.method == "centroid"
    assert decision.subject is Subject.SCIENCE
    assert "rejected" in decision.detail


def test_provider_error_falls_back_to_general_without_fallback():
    class Broken:
        name = "broken"

        def complete(self, *a, **k):
            raise ProviderError("quota exceeded")

    decision = LLMRouter(Broken(), retries=0).route("anything")
    assert decision.subject is Subject.GENERAL and decision.method == "fallback-default"


def test_centroid_router_routes_offtopic_to_general(index):
    router = CentroidRouter.from_index(index)
    assert router.route("What is the hypotenuse of a right triangle?").subject is Subject.MATHEMATICS
    assert router.route("Which colours are complementary on the colour wheel?").subject is Subject.ARTS
    assert router.route("zzz qqq").subject is Subject.GENERAL


def test_fake_llm_router_end_to_end():
    router = LLMRouter(FakeLLM())
    assert router.route("How do I add two fractions?").subject is Subject.MATHEMATICS
    assert router.route("What should I eat today?").subject is Subject.GENERAL
