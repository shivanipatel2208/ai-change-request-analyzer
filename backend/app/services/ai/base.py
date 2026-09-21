"""
Provider-agnostic AI interface.

Every concrete provider (Anthropic, OpenAI, ...) implements this interface.
Nothing else in the codebase should import a specific provider's SDK directly -
always go through `get_ai_provider()` in `factory.py`, so swapping providers
later is a one-line config change (AI_PROVIDER env var), not a code change.
"""
from abc import ABC, abstractmethod


class AIProvider(ABC):
    """Minimal contract the rest of the app relies on.

    Analysis modules built in later steps (requirement extraction, risk
    analysis, etc.) will call `.complete()` with a prompt and get text back.
    Keeping the interface to a single method is deliberate: it's the
    smallest surface that still lets us swap providers freely.
    """

    @abstractmethod
    def complete(
        self,
        prompt: str,
        *,
        system: str | None = None,
        max_tokens: int = 1024,
        timeout: float | None = None,
    ) -> str:
        """Send a prompt to the underlying model and return its text response.

        Implementations should let timeouts and provider/network errors
        propagate as ordinary exceptions - callers (the analysis engine,
        Module 6) are responsible for catching them and turning them into
        a user-facing error, not this layer.
        """
        raise NotImplementedError

    @abstractmethod
    def is_configured(self) -> bool:
        """Whether this provider has the credentials it needs to actually run."""
        raise NotImplementedError

    def embed(self, texts: list[str], *, timeout: float | None = None) -> list[list[float]]:
        """Returns one embedding vector (a list of floats) per input text,
        in the same order as `texts`. Used by Module 16 (Project
        Knowledge Base & RAG) to turn a document's chunks - and a search
        query - into vectors for similarity search.

        Deliberately NOT an @abstractmethod: not every provider wired up
        in this app exposes an embeddings endpoint (Anthropic/Gemini/
        Ollama, as configured here, don't), and none of them should have
        to stub out a method they can't meaningfully implement just to
        remain instantiable. The default here raises a clear, catchable
        error instead - only OpenRouterProvider overrides it for real
        (OpenRouter has a native embeddings endpoint using the same API
        key already configured for chat completions)."""
        raise NotImplementedError(
            f"{type(self).__name__} does not support embeddings - "
            "set AI_PROVIDER=openrouter in backend/.env to use the knowledge base's search."
        )
