"""Runs the bulk synthetic-data generator at a small scale as part of the
normal test suite, so a broken generator gets caught by `pytest ../tests`
before anyone runs it for real at full (thousands-of-rows) scale.

Run with (from backend/):  pytest ../tests
"""
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from app.database.init_db import init_db

init_db()

from fastapi.testclient import TestClient

from app.database.seed_bulk import seed_bulk_data
from app.main import app

client = TestClient(app)


def _register_user() -> str:
    email = f"seedcheck-{uuid.uuid4().hex[:10]}@example.com"
    password = "supersecret123"
    response = client.post(
        "/auth/register",
        json={"name": "Seed Check", "email": email, "password": password, "confirm_password": password},
    )
    assert response.status_code == 201
    return response.json()["access_token"]


def test_seed_bulk_runs_and_dashboard_still_works():
    # Small scale on purpose - this proves the generator's logic (FKs, enum
    # values, chunked commits) is correct without slowing down the normal
    # test run. seed_bulk.py defaults to 3000+ when run directly for real
    # stress-testing, and skips itself if it already ran once before.
    seed_bulk_data(count=15)

    token = _register_user()
    response = client.get("/dashboard/summary", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200
    body = response.json()
    # >=15 rather than ==15 because other tests/seeding may add rows too.
    assert body["metrics"]["total_change_requests"] >= 15
