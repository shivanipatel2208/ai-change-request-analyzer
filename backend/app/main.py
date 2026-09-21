"""
FastAPI application entrypoint.

Run with:  uvicorn app.main:app --reload   (from inside backend/)
"""
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api import (
    admin,
    analytics,
    auth,
    change_requests,
    dashboard,
    health,
    knowledge,
    my_work,
    notifications,
    reports,
    repository,
    users,
)
from app.core.config import get_settings
from app.database.init_db import init_db

settings = get_settings()
logger = logging.getLogger("app")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Hackathon-simple: create any missing tables on startup instead of a
    # separate migration step. init_db() is idempotent - safe to call every
    # time the app starts.
    init_db()
    yield


app = FastAPI(
    title=settings.app_name,
    description="AI-powered engineering assistant that analyzes software change requests.",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router)
app.include_router(auth.router)
app.include_router(dashboard.router)
app.include_router(change_requests.router)
app.include_router(users.router)
app.include_router(notifications.router)
app.include_router(repository.router)
app.include_router(knowledge.router)
app.include_router(my_work.router)
app.include_router(analytics.router)
app.include_router(admin.router)
app.include_router(reports.router)


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Module 22 (Final Integration, Security & Quality) spec section 6:
    "show useful user-facing errors, do not expose stack traces in
    production UI." Every expected failure in this app already raises its
    own HTTPException with a clean message (bad AI response, missing CR,
    permission denied, and so on) - those are handled by FastAPI's own
    built-in HTTPException handler and never reach this one (Starlette
    picks the most specific registered handler for an exception's type,
    and HTTPException already has one). This one only catches whatever's
    left: a genuinely unexpected bug. Before this handler existed,
    Starlette's own default already returned a generic 500 with no
    traceback in the response body - so nothing was ever actually leaking
    to a client - but it never logged anything server-side either, making
    an unexpected failure invisible except as a mysterious 500 in the
    browser. This just adds that logging, with the real traceback, so a
    real bug is diagnosable instead of an opaque dead end."""
    logger.exception("Unhandled exception on %s %s", request.method, request.url.path, exc_info=exc)
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"detail": "Something went wrong on our end. Please try again."},
    )


@app.get("/")
def root() -> dict:
    return {
        "message": f"{settings.app_name} API is running.",
        "docs": "/docs",
        "health": "/health",
    }
