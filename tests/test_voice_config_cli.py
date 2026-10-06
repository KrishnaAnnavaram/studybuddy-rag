"""Reference problems 7-8: browser-uploaded voice behind an interface, configurable providers, eval harness."""
import pytest

from studybuddy_rag.cli import main
from studybuddy_rag.config import DEFAULT_EVAL_SET, Settings, load_dotenv
from studybuddy_rag.evaluate import evaluate, load_eval_set
from studybuddy_rag.providers import build_llm, build_speech
from studybuddy_rag.providers.base import LLM, SpeechToText
from studybuddy_rag.providers.fakes import FakeLLM
from studybuddy_rag.providers.llm import GeminiLLM, OpenAICompatibleLLM
from studybuddy_rag.router import CentroidRouter, LLMRouter
from studybuddy_rag.service import VoiceDisabled
from studybuddy_rag.tutor import Tutor
from tests.conftest import login


def test_voice_question_goes_through_speech_interface_and_is_logged(app, users):
    token = login(app, "student_a")
    transcript, answer = app.ask_voice(token, b"TEXT:How does photosynthesis work in plants?", mime_type="audio/webm")
    assert transcript == "How does photosynthesis work in plants?"
    assert answer.grounded
    row = app.db.conn.execute("SELECT input_mode, question FROM query_log").fetchone()
    assert tuple(row) == ("voice", transcript)


def test_voice_disabled_when_no_provider(app, users):
    app.speech = None
    with pytest.raises(VoiceDisabled):
        app.ask_voice(login(app, "student_a"), b"RIFF....")


def test_settings_from_env_and_validation(monkeypatch):
    monkeypatch.setenv("STUDYBUDDY_LLM_PROVIDER", "gemini")
    monkeypatch.setenv("STUDYBUDDY_LLM_MODEL", "gemini-2.5-flash")
    monkeypatch.setenv("STUDYBUDDY_TOP_K", "6")
    s = Settings.from_env()
    assert (s.llm_provider, s.llm_model, s.top_k) == ("gemini", "gemini-2.5-flash", 6)
    monkeypatch.setenv("STUDYBUDDY_TOP_K", "zero")
    with pytest.raises(ValueError):
        Settings.from_env()
    with pytest.raises(ValueError):
        Settings(llm_provider="mystery")


def test_api_keys_are_hidden_from_repr():
    assert "abc123" not in repr(Settings(gemini_api_key="abc123"))


def test_provider_factory(monkeypatch):
    assert isinstance(build_llm(Settings()), FakeLLM)
    assert build_speech(Settings()) is None
    assert isinstance(build_speech(Settings(speech_provider="fake")), SpeechToText)
    with pytest.raises(ValueError, match="GEMINI_API_KEY"):
        build_llm(Settings(llm_provider="gemini"))
    llm = build_llm(Settings(llm_provider="openai", llm_base_url="http://localhost:11434/v1", llm_model="llama3.2"))
    assert isinstance(llm, OpenAICompatibleLLM) and isinstance(llm, LLM)
    assert GeminiLLM("k").model == "gemini-2.5-flash"     # a current, configurable model id


def test_dotenv_loader_skips_empty_values(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    env.write_text("# comment\nSTUDYBUDDY_TOP_K=7\nGEMINI_API_KEY=\n", encoding="utf-8")
    monkeypatch.delenv("STUDYBUDDY_TOP_K", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    assert load_dotenv(env) == 1
    assert Settings.from_env().top_k == 7


def test_eval_harness_meets_baseline(index):
    items = load_eval_set(DEFAULT_EVAL_SET)
    llm = FakeLLM()
    router = LLMRouter(llm, fallback=CentroidRouter.from_index(index))
    report = evaluate(items, router, index, k=4, tutor=Tutor(llm, index, router))
    assert report.n == len(items) >= 20
    assert report.router_accuracy >= 0.85
    assert report.recall_at_k >= 0.9
    assert report.citation_rate is not None and report.citation_rate >= 0.8


def test_cli_init_and_ask(tmp_path, monkeypatch, capsys):
    db = tmp_path / "demo.db"
    monkeypatch.setenv("STUDYBUDDY_DB_PATH", str(db))
    monkeypatch.setenv("STUDYBUDDY_PASSWORD", "demo-pass-123")
    assert main(["--env-file", str(tmp_path / "none.env"), "init", "--password", "demo-pass-123"]) == 0
    out = capsys.readouterr().out
    assert "student_a" in out and "indexed" in out
    assert main(["--env-file", str(tmp_path / "none.env"), "ask", "-u", "student_a",
                 "How do I find the hypotenuse of a right triangle?"]) == 0
    out = capsys.readouterr().out
    assert "subject: mathematics" in out and "Sequences and Shapes" in out


def test_cli_bad_password_returns_error(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("STUDYBUDDY_DB_PATH", str(tmp_path / "demo.db"))
    main(["--env-file", "none.env", "init", "--password", "demo-pass-123"])
    monkeypatch.setenv("STUDYBUDDY_PASSWORD", "wrong-password")
    assert main(["--env-file", "none.env", "ask", "-u", "student_a", "hello?"]) == 1
    assert "invalid username or password" in capsys.readouterr().err


def test_cli_ui_passes_streamlit_options_after_the_separator(monkeypatch):
    calls = []
    monkeypatch.setattr("studybuddy_rag.cli.subprocess.call", lambda cmd: calls.append(cmd) or 0)
    assert main(["--env-file", "none.env", "ui", "--", "--server.port", "8502"]) == 0
    assert main(["--env-file", "none.env", "ui"]) == 0
    first, second = calls
    assert first[2:4] == ["streamlit", "run"] and first[-2:] == ["--server.port", "8502"]
    assert "--" not in first
    assert second[-1].endswith("streamlit_app.py")
