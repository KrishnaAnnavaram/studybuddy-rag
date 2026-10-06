"""Hosted LLM adapters. Model ids are configuration, not code."""
from __future__ import annotations

from .base import ProviderError
from .http import post_json


class GeminiLLM:
    """Google Gemini via the REST ``generateContent`` endpoint, temperature 0."""

    def __init__(self, api_key: str, model: str = "gemini-2.5-flash", *, base_url: str = "") -> None:
        if not api_key:
            raise ValueError("GEMINI_API_KEY is required for STUDYBUDDY_LLM_PROVIDER=gemini")
        self._key = api_key
        self.model = model or "gemini-2.5-flash"
        self.base_url = (base_url or "https://generativelanguage.googleapis.com/v1beta").rstrip("/")
        self.name = f"gemini:{self.model}"

    def complete(self, prompt: str, *, system: str = "", json_schema: dict | None = None) -> str:
        payload: dict = {
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": 0},
        }
        if system:
            payload["systemInstruction"] = {"parts": [{"text": system}]}
        if json_schema is not None:
            payload["generationConfig"]["responseMimeType"] = "application/json"
            payload["generationConfig"]["responseSchema"] = json_schema
        data = post_json(
            f"{self.base_url}/models/{self.model}:generateContent", payload, {"x-goog-api-key": self._key}
        )
        try:
            return "".join(p.get("text", "") for p in data["candidates"][0]["content"]["parts"])
        except (KeyError, IndexError, TypeError) as exc:
            raise ProviderError(f"unexpected Gemini response shape: {str(data)[:200]}") from exc


class OpenAICompatibleLLM:
    """Any ``/chat/completions`` server: OpenAI, or a local Ollama / vLLM / LM Studio endpoint."""

    def __init__(self, api_key: str, model: str = "gpt-4o-mini", *, base_url: str = "") -> None:
        self.base_url = (base_url or "https://api.openai.com/v1").rstrip("/")
        if not api_key and "api.openai.com" in self.base_url:
            raise ValueError("OPENAI_API_KEY is required for the hosted OpenAI endpoint")
        self._key = api_key
        self.model = model or "gpt-4o-mini"
        self.name = f"openai:{self.model}"

    def complete(self, prompt: str, *, system: str = "", json_schema: dict | None = None) -> str:
        messages = ([{"role": "system", "content": system}] if system else []) + [
            {"role": "user", "content": prompt}
        ]
        payload: dict = {"model": self.model, "messages": messages, "temperature": 0}
        if json_schema is not None:
            payload["response_format"] = {
                "type": "json_schema",
                "json_schema": {"name": "output", "schema": json_schema, "strict": True},
            }
        headers = {"Authorization": f"Bearer {self._key}"} if self._key else {}
        data = post_json(f"{self.base_url}/chat/completions", payload, headers)
        try:
            return data["choices"][0]["message"]["content"] or ""
        except (KeyError, IndexError, TypeError) as exc:
            raise ProviderError(f"unexpected chat-completions response: {str(data)[:200]}") from exc
