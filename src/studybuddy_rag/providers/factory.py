"""Build providers from ``Settings``."""
from __future__ import annotations

from ..config import Settings
from .base import LLM, Embedder, SpeechToText
from .embeddings import HashingEmbedder, SentenceTransformerEmbedder
from .fakes import FakeLLM, FakeSpeechToText
from .llm import GeminiLLM, OpenAICompatibleLLM
from .speech import OpenAITranscriber


def build_llm(settings: Settings) -> LLM:
    if settings.llm_provider == "gemini":
        return GeminiLLM(settings.gemini_api_key, settings.llm_model, base_url=settings.llm_base_url)
    if settings.llm_provider == "openai":
        return OpenAICompatibleLLM(settings.openai_api_key, settings.llm_model, base_url=settings.llm_base_url)
    return FakeLLM()


def build_embedder(settings: Settings) -> Embedder:
    if settings.embedding_provider == "sentence-transformers":
        return SentenceTransformerEmbedder(settings.embedding_model)  # pragma: no cover
    return HashingEmbedder()


def build_speech(settings: Settings) -> SpeechToText | None:
    """``None`` means voice input is disabled and the UI hides the microphone."""
    if settings.speech_provider == "openai":
        return OpenAITranscriber(settings.openai_api_key, settings.speech_model)
    if settings.speech_provider == "fake":
        return FakeSpeechToText()
    return None
