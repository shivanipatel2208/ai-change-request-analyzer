"""
Centralized application configuration.

All configuration is loaded from environment variables (via a local .env
file during development). Nothing sensitive is ever hardcoded here -
copy backend/.env.example to backend/.env and fill in real values locally.
"""
from functools import lru_cache
from pathlib import Path
from typing import List

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Module 22 (Final Integration, Security & Quality): the one value below
# that must never be a real, working secret. Every other "unsafe" default
# in this file (blank AI provider keys, the local sqlite path) just leaves
# a feature turned off until configured - a weak SECRET_KEY instead
# silently accepts forged login tokens, so it gets its own named sentinel
# and its own startup guard (see Settings.forbid_placeholder_secret_key
# below) rather than just a comment asking a developer to remember to
# change it.
_PLACEHOLDER_SECRET_KEY = "hackathon-dev-secret-change-me"


class Settings(BaseSettings):
    # --- App ---
    app_name: str = "AI Change Request Analyzer"
    # Deliberately no `debug` flag here (an earlier version of this file
    # had one that was never actually wired to FastAPI's own debug mode,
    # which would echo Python tracebacks straight into API responses on an
    # unhandled error - spec section 6's "do not expose stack traces in
    # production UI"). Removing the dead field is safer than fixing its
    # wiring, since this app never needs traceback-in-response behavior -
    # app/main.py's own exception handler is what should show on an
    # unhandled error, in every environment, always.
    app_env: str = "development"

    # --- Database ---
    database_url: str = "sqlite:///./data/app.db"

    # --- CORS ---
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"

    # --- AI provider ---
    ai_provider: str = "anthropic"
    anthropic_api_key: str = ""
    anthropic_model: str = "claude-sonnet-4-5"
    openai_api_key: str = ""
    openai_model: str = "gpt-4o"
    # Google Gemini - a free-tier alternative to Anthropic/OpenAI. A Gemini
    # API key (aistudio.google.com/apikey) doesn't require billing to get
    # started, unlike the other two providers. Set AI_PROVIDER=gemini to use it.
    gemini_api_key: str = ""
    gemini_model: str = "gemini-3.8-flash"
    # Ollama - runs a model entirely on this machine, no API key/signup/
    # internet at all once the model is pulled. Set AI_PROVIDER=ollama to
    # use it (requires Ollama installed and running locally - see
    # ollama.com). Slower than a hosted API on a laptop CPU, so consider
    # raising ai_request_timeout_seconds when using this.
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "llama3.2"
    # OpenRouter - one API key/endpoint that proxies many different models
    # (Anthropic, OpenAI, Meta, Google, etc). Get a key at
    # openrouter.ai/keys, then set AI_PROVIDER=openrouter to use it. Model
    # names are OpenRouter's own slugs (e.g. "openai/gpt-4o-mini",
    # "anthropic/claude-3.5-sonnet") - see openrouter.ai/models.
    openrouter_api_key: str = ""
    openrouter_model: str = "openai/gpt-4o-mini"
    # Module 16 (Project Knowledge Base & RAG): the model OpenRouter's
    # /api/v1/embeddings endpoint uses to turn document chunks and search
    # queries into vectors - a small, cheap, well-established embedding
    # model by default. Only used if AI_PROVIDER=openrouter; other
    # providers wired up here don't support embeddings (see
    # AIProvider.embed's own docstring). Override in backend/.env only if
    # you want a different OpenRouter-hosted embedding model.
    openrouter_embedding_model: str = "openai/text-embedding-3-small"
    # How long (seconds) the AI Analysis Engine (Module 6) waits for one
    # provider call before giving up and reporting a timeout error.
    ai_request_timeout_seconds: int = 60

    # --- Auth ---
    # Signs/verifies login tokens (JWT). The placeholder below only lets
    # the app boot before backend/.env exists at all (same "blank until
    # configured" convention as the AI provider keys above) - it is never
    # a usable production value, and forbid_placeholder_secret_key below
    # refuses to start on it outside local development. Set your own
    # SECRET_KEY in backend/.env (see .env.example for how to generate
    # one) - never one shared with, or committed alongside, this code.
    secret_key: str = _PLACEHOLDER_SECRET_KEY
    access_token_expire_minutes: int = 60 * 24  # 1 day - normal login
    remember_me_token_expire_minutes: int = 60 * 24 * 30  # 30 days - "remember me" checked

    # --- Repository Intelligence (Module 15) ---
    # Local filesystem path to the repository the AI should be aware of
    # when matching change requests to source files. Left blank by default,
    # which means "index this project's own repository" (see
    # repository_root_path below) - the simplest practical option per the
    # module's own spec ("do not introduce unnecessary infrastructure"): no
    # upload/archive handling, no separate storage - just a path on disk
    # this backend process can already read. Set REPOSITORY_ROOT in .env to
    # point at a different local folder instead.
    repository_root: str = ""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    @model_validator(mode="after")
    def forbid_placeholder_secret_key(self) -> "Settings":
        """Module 22: the placeholder SECRET_KEY is fine for local
        development (app_env stays "development" unless APP_ENV is
        explicitly set otherwise in .env) - anyone running this app
        elsewhere with APP_ENV set to anything else is refused a boot
        instead of silently signing every login token with a value that
        ships in this project's own source. This never affects local
        hackathon use: app_env's own default is "development", so nothing
        changes unless APP_ENV is deliberately set."""
        if self.app_env.strip().lower() != "development" and self.secret_key == _PLACEHOLDER_SECRET_KEY:
            raise ValueError(
                "SECRET_KEY is still the placeholder value from config.py, but APP_ENV is "
                f"{self.app_env!r} (not 'development'). Set a real SECRET_KEY in backend/.env "
                "before running outside local development - see .env.example."
            )
        return self

    @property
    def cors_origins_list(self) -> List[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    @property
    def repository_root_path(self) -> Path:
        """Resolves `repository_root` to an absolute path. An explicit
        REPOSITORY_ROOT env var always wins; otherwise this defaults to the
        project's own root folder - computed from this file's own location
        (backend/app/core/config.py -> core -> app -> backend -> project
        root) rather than hardcoded, so it resolves correctly on any
        machine this app is checked out on."""
        if self.repository_root.strip():
            return Path(self.repository_root).expanduser().resolve()
        return Path(__file__).resolve().parents[3]


@lru_cache
def get_settings() -> Settings:
    """Settings are read once and cached - re-reading env vars every request is wasteful."""
    return Settings()
