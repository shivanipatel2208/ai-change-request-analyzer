"""Google Gemini implementation of the AIProvider interface.

Added as a free-tier alternative to Anthropic: a Gemini API key (created at
https://aistudio.google.com/apikey) doesn't require billing/a credit card
to get started, unlike an Anthropic key. Implemented as a plain REST call
via httpx (already a project dependency) rather than pulling in Google's
SDK, so switching AI_PROVIDER=gemini in backend/.env is the only change
needed - no new packages to install.
"""
import httpx

from app.core.config import get_settings
from app.services.ai.base import AIProvider

_API_BASE = "https://generativelanguage.googleapis.com/v1beta"


class GeminiProvider(AIProvider):
    def __init__(self) -> None:
        settings = get_settings()
        self._api_key = settings.gemini_api_key
        self._model = settings.gemini_model

    def is_configured(self) -> bool:
        return bool(self._api_key)

    def complete(
        self,
        prompt: str,
        *,
        system: str | None = None,
        max_tokens: int = 1024,
        timeout: float | None = None,
    ) -> str:
        if not self.is_configured():
            raise RuntimeError(
                "GeminiProvider is not configured - set GEMINI_API_KEY in backend/.env"
            )

        url = f"{_API_BASE}/models/{self._model}:generateContent"
        payload: dict = {
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {"maxOutputTokens": max_tokens},
        }
        if system:
            payload["systemInstruction"] = {"parts": [{"text": system}]}

        response = httpx.post(url, params={"key": self._api_key}, json=payload, timeout=timeout)
        response.raise_for_status()  # non-2xx (e.g. bad key, quota) becomes httpx.HTTPStatusError
        data = response.json()

        candidates = data.get("candidates") or []
        if not candidates:
            block_reason = (data.get("promptFeedback") or {}).get("blockReason")
            raise RuntimeError(f"Gemini returned no response (blockReason={block_reason!r}).")

        parts = candidates[0].get("content", {}).get("parts", [])
        return "".join(part.get("text", "") for part in parts)
