"""Verifies the database layer: every table creates successfully, and
relationships/cascades behave correctly - using a throwaway in-memory
SQLite database (never touches the real backend/data/app.db file).

Run with (from backend/):  pytest ../tests
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app import models  # noqa: F401 - registers all models on Base.metadata
from app.database.session import Base
from app.models.enums import ChangeRequestStatus, ComplexityLevel, Priority, RequirementType, UserRole


@pytest.fixture()
def db_session():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    session = Session(bind=engine)
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def test_all_tables_created(db_session):
    table_names = set(Base.metadata.tables.keys())
    expected = {
        "users",
        "change_requests",
        "analyses",
        "requirements",
        "affected_components",
        "dependencies",
        "risks",
        "clarification_questions",
        "test_cases",
        "implementation_tasks",
    }
    assert expected.issubset(table_names)


def test_change_request_belongs_to_its_creator(db_session):
    user = models.User(
        name="Ada Lovelace",
        email="ada@example.com",
        password_hash="hashed",
        role=UserRole.ENGINEER,
    )
    db_session.add(user)
    db_session.flush()

    change_request = models.ChangeRequest(
        title="Add dark mode",
        description="Add a dark theme toggle to settings.",
        priority=Priority.MEDIUM,
        status=ChangeRequestStatus.DRAFT,
        created_by=user.id,
    )
    db_session.add(change_request)
    db_session.commit()

    assert change_request.creator.email == "ada@example.com"
    assert user.change_requests == [change_request]


def test_analysis_cascades_delete_to_its_children(db_session):
    user = models.User(name="Ada", email="ada2@example.com", password_hash="x", role=UserRole.ENGINEER)
    db_session.add(user)
    db_session.flush()

    cr = models.ChangeRequest(
        title="Add SSO login",
        description="Support SAML-based SSO.",
        priority=Priority.HIGH,
        status=ChangeRequestStatus.SUBMITTED,
        created_by=user.id,
    )
    db_session.add(cr)
    db_session.flush()

    analysis = models.Analysis(
        change_request_id=cr.id,
        summary="Adds SSO login support via SAML.",
        category="feature",
        complexity=ComplexityLevel.HIGH,
        risk_score=65.0,
        confidence_score=80.0,
    )
    analysis.requirements.append(
        models.Requirement(
            requirement_type=RequirementType.FUNCTIONAL,
            description="Users can log in via SAML SSO.",
            priority=Priority.HIGH,
        )
    )
    db_session.add(analysis)
    db_session.commit()

    assert len(cr.analyses) == 1
    assert cr.analyses[0].requirements[0].description.startswith("Users can log in")

    # Deleting the analysis should cascade-delete its requirement row too.
    db_session.delete(analysis)
    db_session.commit()

    assert db_session.query(models.Requirement).count() == 0
