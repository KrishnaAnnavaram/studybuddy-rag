"""Settings, read from environment variables (and an optional local .env file).

Nothing secret has a default. Every provider defaults to the offline ``fake`` implementation,
so the app, the CLI and the tests run without network access or API keys.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

PACKAGE_DIR = Path(__file__).resolve().parent
DEFAULT_CORPUS_DIR = PACKAGE_DIR / "data" / "corpus"
DEFAULT_EVAL_SET = PACKAGE_DIR / "data" / "eval_set.jsonl"


def load_dotenv(path: str | os.PathLike[str] = ".env", *, override: bool = False) -> int:
    """Load ``KEY=VALUE`` lines from ``path`` into ``os.environ``. Returns the number of keys set.

    A deliberately tiny parser (no interpolation) so the core package has no dependencies.
    Empty values are skipped, which keeps ``.env.example``-style files harmless.
    """
    p = Path(path)
    if not p.is_file():
        return 0
    count = 0
    for raw in p.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip().strip('"').strip("'")
        if not key or not value:
            continue
        if override or key not in os.environ:
            os.environ[key] = value
            count += 1
    return count


def _env(name: str, default: str = "") -> str:
    value = os.environ.get(name, "").strip()
    return value or default


def _env_int(name: str, default: int) -> int:
    raw = _env(name)
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer, got {raw!r}") from exc


def _env_float(name: str, default: float) -> float:
    raw = _env(name)
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be a number, got {raw!r}") from exc


@dataclass(frozen=True)
class Settings:
    db_path: str = "data/studybuddy.db"
    corpus_dir: str = str(DEFAULT_CORPUS_DIR)
    llm_provider: str = "fake"            # fake | gemini | openai
    llm_model: str = ""
    llm_base_url: str = ""
    embedding_provider: str = "hashing"   # hashing | sentence-transformers
    embedding_model: str = "all-MiniLM-L6-v2"
    speech_provider: str = "none"         # none | fake | openai
    speech_model: str = "whisper-1"
    top_k: int = 4
    min_score: float = 0.05
    session_ttl_minutes: int = 60
    log_retention_days: int = 180
    k_anonymity: int = 3
    gemini_api_key: str = field(default="", repr=False)
    openai_api_key: str = field(default="", repr=False)

    def __post_init__(self) -> None:
        if self.top_k < 1:
            raise ValueError("top_k must be >= 1")
        if self.session_ttl_minutes < 1:
            raise ValueError("session_ttl_minutes must be >= 1")
        if self.k_anonymity < 1:
            raise ValueError("k_anonymity must be >= 1")
        if self.llm_provider not in {"fake", "gemini", "openai"}:
            raise ValueError(f"unknown STUDYBUDDY_LLM_PROVIDER {self.llm_provider!r}")
        if self.embedding_provider not in {"hashing", "sentence-transformers"}:
            raise ValueError(f"unknown STUDYBUDDY_EMBEDDING_PROVIDER {self.embedding_provider!r}")
        if self.speech_provider not in {"none", "fake", "openai"}:
            raise ValueError(f"unknown STUDYBUDDY_SPEECH_PROVIDER {self.speech_provider!r}")

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            db_path=_env("STUDYBUDDY_DB_PATH", cls.db_path),
            corpus_dir=_env("STUDYBUDDY_CORPUS_DIR", str(DEFAULT_CORPUS_DIR)),
            llm_provider=_env("STUDYBUDDY_LLM_PROVIDER", cls.llm_provider).lower(),
            llm_model=_env("STUDYBUDDY_LLM_MODEL"),
            llm_base_url=_env("STUDYBUDDY_LLM_BASE_URL"),
            embedding_provider=_env("STUDYBUDDY_EMBEDDING_PROVIDER", cls.embedding_provider).lower(),
            embedding_model=_env("STUDYBUDDY_EMBEDDING_MODEL", cls.embedding_model),
            speech_provider=_env("STUDYBUDDY_SPEECH_PROVIDER", cls.speech_provider).lower(),
            speech_model=_env("STUDYBUDDY_SPEECH_MODEL", cls.speech_model),
            top_k=_env_int("STUDYBUDDY_TOP_K", cls.top_k),
            min_score=_env_float("STUDYBUDDY_MIN_SCORE", cls.min_score),
            session_ttl_minutes=_env_int("STUDYBUDDY_SESSION_TTL_MINUTES", cls.session_ttl_minutes),
            log_retention_days=_env_int("STUDYBUDDY_LOG_RETENTION_DAYS", cls.log_retention_days),
            k_anonymity=_env_int("STUDYBUDDY_K_ANONYMITY", cls.k_anonymity),
            gemini_api_key=_env("GEMINI_API_KEY"),
            openai_api_key=_env("OPENAI_API_KEY"),
        )
