"""Resolves the configured AI provider by name.

Adding a new provider later is: write a class implementing AIProvider,
register it in _PROVIDERS below, and set AI_PROVIDER in .env - nothing
else in the app needs to change.
"""
from functools import lru_cache

from app.core.config import get_settings
from app.services.ai.base import AIProvider
from app.services.ai.providers.anthropic_provider import AnthropicProvider
from app.services.ai.providers.gemini_provider import GeminiProvider
from app.services.ai.providers.ollama_provider import OllamaProvider
from app.services.ai.providers.openrouter_provider import OpenRouterProvider

_PROVIDERS: dict[str, type[AIProvider]] = {
    "anthropic": AnthropicProvider,
    "gemini": GeminiProvider,
    "ollama": OllamaProvider,
    "openrouter": OpenRouterProvider,
    # "openai": OpenAIProvider,  # add when that module is built
}


@lru_cache
def get_ai_provider() -> AIProvider:
    settings = get_settings()
    provider_cls = _PROVIDERS.get(settings.ai_provider)
    if provider_cls is None:
        raise ValueError(
            f"Unknown AI_PROVIDER '{settings.ai_provider}'. "
            f"Available: {', '.join(_PROVIDERS)}"
        )
    return provider_cls()
