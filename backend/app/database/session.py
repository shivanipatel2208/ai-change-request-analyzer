"""
SQLAlchemy engine/session setup for SQLite.

Kept intentionally simple for the hackathon: a single SQLite file under
backend/data/, created automatically on first run. Later modules (models,
schemas, services) will import `Base` and `get_db` from here.
"""
import os
from pathlib import Path
from typing import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.core.config import get_settings

settings = get_settings()

# Ensure the SQLite file's parent directory exists (e.g. backend/data/)
if settings.database_url.startswith("sqlite:///./"):
    relative_path = settings.database_url.replace("sqlite:///./", "")
    db_path = Path(__file__).resolve().parent.parent.parent / relative_path
    db_path.parent.mkdir(parents=True, exist_ok=True)

connect_args = {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}

engine = create_engine(settings.database_url, connect_args=connect_args)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    """Shared declarative base for all ORM models."""
    pass


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency that yields a DB session and always closes it.

    Module 22: the `except` below rolls back on the way out whenever the
    request raised (an HTTPException, or a genuinely unexpected error) -
    previously only `close()` ran, which still ends the session but
    leaves an already-open failed transaction to SQLAlchemy's own
    implicit handling instead of explicitly closing it out. This never
    changes behavior for the success path (nothing here runs unless an
    exception propagated through the `yield`), and the endpoint's own
    `db.commit()` calls are completely unaffected either way."""
    db = SessionLocal()
    try:
        yield db
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
