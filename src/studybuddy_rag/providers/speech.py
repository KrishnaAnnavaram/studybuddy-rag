"""Speech-to-text adapters.

Audio is recorded **in the browser** (Streamlit's ``st.audio_input``) and uploaded, so voice input
works when the app is deployed; the prototype opened the *server's* microphone instead.
"""
from __future__ import annotations

from .base import ProviderError
from .http import post_multipart

_EXTENSIONS = {"audio/wav": "wav", "audio/x-wav": "wav", "audio/webm": "webm", "audio/mpeg": "mp3",
               "audio/mp4": "m4a", "audio/ogg": "ogg"}


class OpenAITranscriber:
    """Whisper-style ``/audio/transcriptions`` endpoint (OpenAI or a compatible local server)."""

    def __init__(self, api_key: str, model: str = "whisper-1", *, base_url: str = "") -> None:
        self.base_url = (base_url or "https://api.openai.com/v1").rstrip("/")
        if not api_key and "api.openai.com" in self.base_url:
            raise ValueError("OPENAI_API_KEY is required for STUDYBUDDY_SPEECH_PROVIDER=openai")
        self._key = api_key
        self.model = model or "whisper-1"
        self.name = f"openai-stt:{self.model}"

    def transcribe(self, audio: bytes, *, mime_type: str = "audio/wav") -> str:
        if not audio:
            raise ValueError("empty audio")
        ext = _EXTENSIONS.get(mime_type, "wav")
        headers = {"Authorization": f"Bearer {self._key}"} if self._key else {}
        data = post_multipart(
            f"{self.base_url}/audio/transcriptions",
            {"model": self.model},
            "file",
            f"question.{ext}",
            audio,
            mime_type,
            headers,
        )
        if "text" not in data:
            raise ProviderError(f"unexpected transcription response: {str(data)[:200]}")
        return str(data["text"]).strip()
