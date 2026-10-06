"""Application service: the one place where auth, tutoring, voice and logging meet.

The UI and CLI only talk to ``StudyBuddy``; every call takes a session token and is scoped to the
user behind it.
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from .analytics import InstructorOverview, StudentDashboard, grade_summary, instructor_overview, student_dashboard
from .auth import AuthService, Principal, Session
from .config import Settings
from .db import Database
from .index import HybridIndex
from .ingest import chunk_corpus, load_corpus
from .providers import build_embedder, build_llm, build_speech
from .providers.base import LLM, SpeechToText
from .router import CentroidRouter, LLMRouter
from .tutor import Tutor, TutorAnswer


class VoiceDisabled(RuntimeError):
    pass


@dataclass
class StudyBuddy:
    db: Database
    auth: AuthService
    tutor: Tutor
    llm: LLM
    speech: SpeechToText | None = None
    k_anonymity: int = 3

    # ---- session ---------------------------------------------------------------------------
    def login(self, username: str, password: str) -> Session:
        return self.auth.login(username, password)

    def logout(self, token: str | None) -> None:
        self.auth.logout(token)

    def whoami(self, token: str | None) -> Principal:
        return self.auth.authenticate(token)

    # ---- tutoring --------------------------------------------------------------------------
    def ask(self, token: str | None, question: str, *, input_mode: str = "text") -> TutorAnswer:
        principal = self.auth.authenticate(token)
        answer = self.tutor.answer(question)
        if answer.kind != "greeting":
            self.db.insert_query(
                principal.user_id, self.auth.clock(), input_mode, answer.question, answer.subject.value,
                answer.route.method if answer.route else "none", answer.text,
                [c.as_dict() for c in answer.cited], answer.grounded,
            )
        return answer

    def ask_voice(self, token: str | None, audio: bytes, *, mime_type: str = "audio/wav") -> tuple[str, TutorAnswer]:
        self.auth.authenticate(token)  # check before spending a transcription call
        if self.speech is None:
            raise VoiceDisabled("voice input is disabled (set STUDYBUDDY_SPEECH_PROVIDER)")
        transcript = self.speech.transcribe(audio, mime_type=mime_type).strip()
        if not transcript:
            raise ValueError("could not understand the recording")
        return transcript, self.ask(token, transcript, input_mode="voice")

    # ---- analytics -------------------------------------------------------------------------
    def dashboard(self, token: str | None) -> StudentDashboard:
        return student_dashboard(self.db, self.auth.authenticate(token), k=self.k_anonymity)

    def summary(self, token: str | None, *, use_llm: bool = False) -> str:
        return grade_summary(self.db, self.auth.authenticate(token), self.llm if use_llm else None)

    def instructor_view(self, token: str | None) -> InstructorOverview:
        return instructor_overview(self.db, self.auth.authenticate(token), k=self.k_anonymity)


def build_index(settings: Settings, embedder=None) -> HybridIndex:
    embedder = embedder or build_embedder(settings)
    return HybridIndex.build(chunk_corpus(load_corpus(settings.corpus_dir)), embedder)


def build_app(settings: Settings, *, db: Database | None = None, llm: LLM | None = None,
              speech: SpeechToText | None = None, index: HybridIndex | None = None) -> StudyBuddy:
    """Wire everything from settings. Loads the persisted index, or builds it from the corpus."""
    db = db or Database(settings.db_path)
    embedder = index.embedder if index is not None else build_embedder(settings)
    if index is None:
        try:
            index = HybridIndex.load(settings.db_path, embedder) if settings.db_path != ":memory:" else None
        except (FileNotFoundError, ValueError, sqlite3.Error):
            index = None  # no (compatible) persisted index yet: build one from the corpus
        if index is None or len(index) == 0:
            index = build_index(settings, embedder)
    llm = llm or build_llm(settings)
    router = LLMRouter(llm, fallback=CentroidRouter.from_index(index))
    tutor = Tutor(llm, index, router, top_k=settings.top_k, min_score=settings.min_score)
    return StudyBuddy(db, AuthService(db, ttl_minutes=settings.session_ttl_minutes), tutor, llm,
                      speech if speech is not None else build_speech(settings), settings.k_anonymity)
