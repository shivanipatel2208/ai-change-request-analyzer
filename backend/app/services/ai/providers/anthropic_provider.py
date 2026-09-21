"""Anthropic (Claude) implementation of the AIProvider interface."""
from app.core.config import get_settings
from app.services.ai.base import AIProvider


class AnthropicProvider(AIProvider):
    def __init__(self) -> None:
        settings = get_settings()
        self._api_key = settings.anthropic_api_key
        self._model = settings.anthropic_model
        self._client = None  # created lazily, only once we know a key is present

    def is_configured(self) -> bool:
        return bool(self._api_key)

    def _get_client(self):
        if self._client is None:
            import anthropic  # imported lazily so the package is only required when actually used

            self._client = anthropic.Anthropic(api_key=self._api_key)
        return self._client

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
                "AnthropicProvider is not configured - set ANTHROPIC_API_KEY in backend/.env"
            )

        client = self._get_client()
        response = client.messages.create(
            model=self._model,
            max_tokens=max_tokens,
            system=system or "",
            messages=[{"role": "user", "content": prompt}],
            timeout=timeout,
        )
        return "".join(block.text for block in response.content if block.type == "text")
