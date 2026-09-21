"""Smoke test for the health-check endpoint.

Run with (from backend/):  pytest ../tests
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health_check_returns_ok():
    response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert "database" in body
    assert "ai_provider_configured" in body


def test_root_returns_metadata():
    response = client.get("/")
    assert response.status_code == 200
    assert "message" in response.json()
