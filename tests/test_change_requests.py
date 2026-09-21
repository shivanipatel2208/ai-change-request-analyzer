"""Verifies the change-request creation workflow (Module 4): auth is
required, valid submissions are persisted with status "pending_analysis",
validation rejects bad input, and the list/get-one endpoints return what was
just created.

Run with (from backend/):  pytest ../tests
"""
import sys
import uuid
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from app.database.init_db import init_db

init_db()  # make sure every table/column exists even if init_db was never run manually

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def _unique_email() -> str:
    return f"cr-{uuid.uuid4().hex[:10]}@example.com"


def _auth_headers() -> dict:
    email = _unique_email()
    password = "supersecret123"
    response = client.post(
        "/auth/register",
        json={"name": "CR Tester", "email": email, "password": password, "confirm_password": password},
    )
    assert response.status_code == 201
    token = response.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def _valid_payload(**overrides) -> dict:
    payload = {
        "title": "Allow OTP login for customers",
        "description": "Allow customers to log in using OTP sent to their registered mobile number.",
        "business_objective": "Reduce password-reset support tickets.",
        "priority": "high",
        "requested_by": "Jamie Rivera",
        "target_system": "Mobile App",
        "desired_deadline": (date.today() + timedelta(days=14)).isoformat(),
    }
    payload.update(overrides)
    return payload


def test_create_requires_authentication():
    response = client.post("/api/change-requests", json=_valid_payload())
    assert response.status_code == 401


def test_create_change_request_succeeds_with_valid_data():
    headers = _auth_headers()
    response = client.post("/api/change-requests", json=_valid_payload(), headers=headers)
    assert response.status_code == 201
    body = response.json()
    assert body["title"] == "Allow OTP login for customers"
    assert body["status"] == "pending_analysis"
    assert body["requested_by"] == "Jamie Rivera"
    assert body["target_system"] == "Mobile App"
    assert "id" in body


def test_create_rejects_short_title():
    headers = _auth_headers()
    response = client.post("/api/change-requests", json=_valid_payload(title="Fix"), headers=headers)
    assert response.status_code == 422


def test_create_rejects_short_description():
    headers = _auth_headers()
    response = client.post(
        "/api/change-requests", json=_valid_payload(description="Too short."), headers=headers
    )
    assert response.status_code == 422


def test_create_rejects_missing_requested_by():
    headers = _auth_headers()
    response = client.post("/api/change-requests", json=_valid_payload(requested_by=" "), headers=headers)
    assert response.status_code == 422


def test_create_rejects_past_deadline():
    headers = _auth_headers()
    past_date = (date.today() - timedelta(days=1)).isoformat()
    response = client.post(
        "/api/change-requests", json=_valid_payload(desired_deadline=past_date), headers=headers
    )
    assert response.status_code == 422


def test_created_request_appears_in_list_and_get_one():
    headers = _auth_headers()
    create_response = client.post(
        "/api/change-requests", json=_valid_payload(title="Add barcode rescan option"), headers=headers
    )
    assert create_response.status_code == 201
    created_id = create_response.json()["id"]

    list_response = client.get("/api/change-requests", headers=headers)
    assert list_response.status_code == 200
    ids_in_list = {item["id"] for item in list_response.json()["items"]}
    assert created_id in ids_in_list

    get_response = client.get(f"/api/change-requests/{created_id}", headers=headers)
    assert get_response.status_code == 200
    assert get_response.json()["title"] == "Add barcode rescan option"


def test_get_one_returns_404_for_unknown_id():
    headers = _auth_headers()
    response = client.get("/api/change-requests/999999999", headers=headers)
    assert response.status_code == 404
