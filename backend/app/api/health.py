"""Health-check endpoint - confirms the API is up, the DB is reachable,
and reports (without calling out to it) whether an AI provider is configured.
"""
from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.database.session import get_db
from app.schemas.health import HealthResponse

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse)
def health_check(db: Session = Depends(get_db)) -> HealthResponse:
    settings = get_settings()

    try:
        db.execute(text("SELECT 1"))
        db_status = "connected"
    except Exception as exc:  # pragma: no cover - defensive, surfaced in response
        db_status = f"error: {exc}"

    ai_configured = bool(
        settings.anthropic_api_key if settings.ai_provider == "anthropic" else settings.openai_api_key
    )

    return HealthResponse(
        status="ok",
        app_name=settings.app_name,
        app_env=settings.app_env,
        database=db_status,
        ai_provider_configured=ai_configured,
    )
