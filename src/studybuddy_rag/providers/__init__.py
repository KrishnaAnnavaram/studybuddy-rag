"""Pluggable providers (LLM, embeddings, speech-to-text) behind small interfaces.

Real adapters are selected with environment variables (see ``config.Settings``); the offline
fakes in ``providers.fakes`` are deterministic and are what the tests and demo mode use.
"""
from .base import LLM, Embedder, SpeechToText
from .factory import build_embedder, build_llm, build_speech

__all__ = ["LLM", "Embedder", "SpeechToText", "build_embedder", "build_llm", "build_speech"]
