"""Ollama implementation of the AIProvider interface - runs a model
entirely on this machine via a local Ollama install (ollama.com). No API
key, no signup, no internet needed once a model is pulled - the only
"local" option among the three providers.

Implemented as a plain REST call via httpx (already a project dependency)
against Ollama's /api/chat endpoint, same pattern as the other providers.
Uses Ollama's `format: "json"` mode so the model is constrained to return
syntactically valid JSON - the analysis engine's Pydantic validation still
checks it actually matches the required shape.
"""
import httpx

from app.core.config import get_settings
from app.services.ai.base import AIProvider


class OllamaProvider(AIProvider):
    def __init__(self) -> None:
        settings = get_settings()
        self._base_url = settings.ollama_base_url.rstrip("/")
        self._model = settings.ollama_model

    def is_configured(self) -> bool:
        # No API key to check - Ollama either has a model pulled and
        # running or it doesn't. A model name being set is enough to try.
        return bool(self._model)

    def complete(
        self,
        prompt: str,
        *,
        system: str | None = None,
        max_tokens: int = 1024,
        timeout: float | None = None,
    ) -> str:
        if not self.is_configured():
            raise RuntimeError("OllamaProvider has no model configured - set OLLAMA_MODEL in backend/.env")

        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        payload = {
            "model": self._model,
            "messages": messages,
            "stream": False,
            "format": "json",
            "options": {"num_predict": max_tokens},
        }

        try:
            response = httpx.post(f"{self._base_url}/api/chat", json=payload, timeout=timeout)
        except httpx.ConnectError as exc:
            raise RuntimeError(
                f"Couldn't reach Ollama at {self._base_url} - make sure the Ollama app is running "
                f"and you've run `ollama pull {self._model}`."
            ) from exc

        response.raise_for_status()
        data = response.json()
        return data.get("message", {}).get("content", "")
