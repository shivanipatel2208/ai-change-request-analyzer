"""Verifies the authentication endpoints against the real running app (same
pattern as test_health.py). Each test uses a fresh, randomly-generated
email so re-running the suite never collides with a previous run's data.

Note: this writes real (if randomly-emailed) user rows into your actual
backend/data/app.db each time you run it - harmless, and consistent with
how test_health.py already works, but it means that file will accumulate
test users over time. Delete it any time to reset; tables are recreated
automatically on next run.

Run with (from backend/):  pytest ../tests
"""
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from app.database.init_db import init_db

init_db()  # make sure the users table exists even if init_db was never run manually

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def _unique_email() -> str:
    return f"test-{uuid.uuid4().hex[:10]}@example.com"


def test_register_login_and_me_flow():
    email = _unique_email()
    password = "supersecret123"

    register_response = client.post(
        "/auth/register",
        json={"name": "Test User", "email": email, "password": password, "confirm_password": password},
    )
    assert register_response.status_code == 201
    register_body = register_response.json()
    assert register_body["user"]["email"] == email
    assert "access_token" in register_body

    login_response = client.post(
        "/auth/login", json={"email": email, "password": password, "remember_me": False}
    )
    assert login_response.status_code == 200
    token = login_response.json()["access_token"]

    me_response = client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me_response.status_code == 200
    assert me_response.json()["email"] == email

    logout_response = client.post("/auth/logout", headers={"Authorization": f"Bearer {token}"})
    assert logout_response.status_code == 200


def test_register_rejects_duplicate_email():
    email = _unique_email()
    password = "supersecret123"
    body = {"name": "Test User", "email": email, "password": password, "confirm_password": password}

    first = client.post("/auth/register", json=body)
    assert first.status_code == 201

    second = client.post("/auth/register", json=body)
    assert second.status_code == 409


def test_register_rejects_mismatched_passwords():
    response = client.post(
        "/auth/register",
        json={
            "name": "Test User",
            "email": _unique_email(),
            "password": "supersecret123",
            "confirm_password": "different123",
        },
    )
    assert response.status_code == 422


def test_login_rejects_wrong_password():
    email = _unique_email()
    password = "supersecret123"
    client.post(
        "/auth/register",
        json={"name": "Test User", "email": email, "password": password, "confirm_password": password},
    )

    response = client.post(
        "/auth/login", json={"email": email, "password": "wrongpassword", "remember_me": False}
    )
    assert response.status_code == 401


def test_me_requires_authentication():
    response = client.get("/auth/me")
    assert response.status_code == 401
