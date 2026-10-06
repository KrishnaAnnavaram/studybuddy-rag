from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from studybuddy_rag.config import Settings
from studybuddy_rag.db import Database
from studybuddy_rag.index import HybridIndex
from studybuddy_rag.ingest import chunk_corpus, load_corpus
from studybuddy_rag.providers.embeddings import HashingEmbedder
from studybuddy_rag.providers.fakes import FakeLLM, FakeSpeechToText
from studybuddy_rag.service import build_app

PASSWORD = "correct-horse-42"


class FakeClock:
    def __init__(self) -> None:
        self.now = datetime(2026, 1, 15, 9, 0, tzinfo=timezone.utc)

    def __call__(self) -> datetime:
        return self.now

    def advance(self, **kw) -> None:
        self.now += timedelta(**kw)


@pytest.fixture(scope="session")
def embedder():
    return HashingEmbedder()


@pytest.fixture(scope="session")
def chunks():
    return chunk_corpus(load_corpus(Settings().corpus_dir))


@pytest.fixture(scope="session")
def index(chunks, embedder):
    return HybridIndex.build(chunks, embedder)


@pytest.fixture
def clock():
    return FakeClock()


@pytest.fixture
def app(index, clock):
    settings = Settings(db_path=":memory:")
    db = Database(":memory:")
    app = build_app(settings, db=db, llm=FakeLLM(), speech=FakeSpeechToText(), index=index)
    app.auth.clock = clock
    return app


@pytest.fixture
def users(app):
    """Three students and one instructor with a shared course; returns {name: Principal}."""
    out = {}
    for name in ("student_a", "student_b", "student_c"):
        out[name] = app.auth.register(name, PASSWORD, display_name=name.replace("_", " ").title())
    out["teacher"] = app.auth.register("teacher", PASSWORD, role="instructor", display_name="Teacher")
    return out


def login(app, username: str) -> str:
    return app.login(username, PASSWORD).token
