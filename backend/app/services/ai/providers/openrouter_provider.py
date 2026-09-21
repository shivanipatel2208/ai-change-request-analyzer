"""OpenRouter implementation of the AIProvider interface.

OpenRouter (openrouter.ai) is a single API that proxies many different
models (Anthropic, OpenAI, Meta, Google, and more) behind one OpenAI-
compatible endpoint and one API key - handy when you already have an
OpenRouter key and don't want to sign up for a model provider directly.

Implemented as a plain REST call via httpx (already a project dependency),
same pattern as gemini_provider.py / ollama_provider.py - no new package to
install. Set AI_PROVIDER=openrouter in backend/.env to use it.
"""
import httpx

from app.core.config import get_settings
from app.services.ai.base import AIProvider

_API_URL = "https://openrouter.ai/api/v1/chat/completions"
# Module 16 (Project Knowledge Base & RAG): OpenRouter's own embeddings
# endpoint - same base API, same API key, an OpenAI-compatible request/
# response shape (see embed() below).
_EMBEDDINGS_API_URL = "https://openrouter.ai/api/v1/embeddings"


class OpenRouterProvider(AIProvider):
    def __init__(self) -> None:
        settings = get_settings()
        self._api_key = settings.openrouter_api_key
        self._model = settings.openrouter_model
        self._embedding_model = settings.openrouter_embedding_model

    def is_configured(self) -> bool:
        return bool(self._api_key)

    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
            # Optional but recommended by OpenRouter for their own request
            # attribution/leaderboards - harmless to include, not required
            # for the API call to work.
            "HTTP-Referer": "http://localhost",
            "X-Title": "AI Change Request Analyzer",
        }

    def embed(self, texts: list[str], *, timeout: float | None = None) -> list[list[float]]:
        if not self.is_configured():
            raise RuntimeError(
                "OpenRouterProvider is not configured - set OPENROUTER_API_KEY in backend/.env"
            )
        if not texts:
            return []

        payload = {"model": self._embedding_model, "input": texts}
        response = httpx.post(_EMBEDDINGS_API_URL, headers=self._headers(), json=payload, timeout=timeout)
        response.raise_for_status()
        data = response.json()

        items = data.get("data") or []
        if len(items) != len(texts):
            error = data.get("error")
            raise RuntimeError(
                f"OpenRouter embeddings returned {len(items)} vectors for {len(texts)} inputs (error={error!r})."
            )
        # The OpenAI-compatible embeddings response includes each item's
        # own "index" - sort by it rather than trusting response list
        # order, so a vector always lines up with the text it belongs to
        # even if a provider ever returns them out of order.
        items_sorted = sorted(items, key=lambda item: item.get("index", 0))
        return [item["embedding"] for item in items_sorted]

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
                "OpenRouterProvider is not configured - set OPENROUTER_API_KEY in backend/.env"
            )

        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        payload = {
            "model": self._model,
            "messages": messages,
            "max_tokens": max_tokens,
        }
        response = httpx.post(_API_URL, headers=self._headers(), json=payload, timeout=timeout)
        response.raise_for_status()  # non-2xx (bad key, model not found, out of credits) -> httpx.HTTPStatusError
        data = response.json()

        choices = data.get("choices") or []
        if not choices:
            error = data.get("error")
            raise RuntimeError(f"OpenRouter returned no response (error={error!r}).")

        return choices[0].get("message", {}).get("content", "") or ""
