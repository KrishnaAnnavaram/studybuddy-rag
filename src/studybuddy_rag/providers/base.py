"""Interfaces every provider implements."""
from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class LLM(Protocol):
    name: str

    def complete(self, prompt: str, *, system: str = "", json_schema: dict | None = None) -> str:
        """Return the model's text. With ``json_schema`` the model is asked for JSON matching it.

        Callers must still validate the output: providers are not trusted to honour the schema.
        """
        ...


@runtime_checkable
class Embedder(Protocol):
    name: str
    dim: int

    def embed(self, texts: list[str]) -> list[list[float]]:
        """Return one L2-normalised vector per text, in order."""
        ...


@runtime_checkable
class SpeechToText(Protocol):
    name: str

    def transcribe(self, audio: bytes, *, mime_type: str = "audio/wav") -> str:
        """Transcribe audio recorded in the *browser* and uploaded to the server."""
        ...


class ProviderError(RuntimeError):
    """A provider call failed (network, auth, quota or a malformed response)."""
