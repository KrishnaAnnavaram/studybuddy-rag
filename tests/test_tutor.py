"""The end-to-end pipeline: retrieval runs for subject questions and answers carry valid citations."""
from studybuddy_rag.providers.fakes import FakeLLM, ScriptedLLM
from studybuddy_rag.router import CentroidRouter, LLMRouter, RouteDecision
from studybuddy_rag.subjects import Subject
from studybuddy_rag.tutor import ANSWER_SYSTEM, Tutor, extract_citations, is_greeting


class FixedRouter:
    def __init__(self, subject):
        self.subject = subject

    def route(self, question):
        return RouteDecision(self.subject, 1.0, "fixed")


def test_subject_question_is_grounded_with_citations(index):
    llm = FakeLLM()
    tutor = Tutor(llm, index, LLMRouter(llm), top_k=4)
    ans = tutor.answer("What is the formula for the n-th term of an arithmetic progression?")
    assert ans.subject is Subject.MATHEMATICS
    assert ans.grounded and ans.kind == "grounded"
    assert len(ans.sources) > 1                       # several chunks, not one sentence
    assert ans.cited[0].section == "Arithmetic progressions"
    assert "[1]" in ans.text or "[2]" in ans.text
    answer_call = llm.calls[-1]
    assert answer_call["system"] == ANSWER_SYSTEM and "Sources:" in answer_call["prompt"]


def test_invalid_citations_are_stripped_and_flagged(index):
    llm = ScriptedLLM(["Three angles sum to 180 degrees [1] [9]."])
    tutor = Tutor(llm, index, FixedRouter(Subject.MATHEMATICS), top_k=2)
    ans = tutor.answer("What do the angles of a triangle add up to?")
    assert "[9]" not in ans.text and "[1]" in ans.text
    assert [c.number for c in ans.cited] == [1]
    assert any("non-existent" in n for n in ans.notes)


def test_answer_without_citation_is_marked_ungrounded(index):
    tutor = Tutor(ScriptedLLM(["It is 180 degrees."]), index, FixedRouter(Subject.MATHEMATICS))
    ans = tutor.answer("What do the angles of a triangle add up to?")
    assert ans.kind == "ungrounded" and ans.sources and not ans.cited


def test_misrouted_question_still_retrieves_from_whole_corpus(index):
    tutor = Tutor(FakeLLM(), index, FixedRouter(Subject.ARTS), min_score=0.3)
    ans = tutor.answer("Explain Newton's second law with force mass and acceleration")
    assert ans.grounded
    assert ans.cited[0].subject == "science"
    assert any("searched all subjects" in n for n in ans.notes)


def test_offtopic_question_is_ungrounded_and_says_so(index):
    llm = ScriptedLLM(["Try oats and fruit. (Not from the course material.)"])
    tutor = Tutor(llm, index, FixedRouter(Subject.GENERAL))
    ans = tutor.answer("What should I eat for breakfast tomorrow?")
    assert ans.kind == "ungrounded" and not ans.sources


def test_greetings_short_circuit_without_llm(index):
    llm = ScriptedLLM([])
    tutor = Tutor(llm, index, CentroidRouter.from_index(index))
    assert tutor.answer("Hello there!").kind == "greeting"
    assert llm.calls == []
    assert is_greeting("good morning") and not is_greeting("hello, what is a fraction?")


def test_extract_citations():
    assert extract_citations("a [2] b [1] c [2] d [7]", 3) == ([2, 1], [7])
