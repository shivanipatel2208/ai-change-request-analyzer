"""Verifies Module 15 Phase 1 (Repository Intelligence - Foundation):

  * scan_repository() walks a given folder and records exactly the files
    it should - source-like extensions only - while silently skipping
    node_modules/.git/build/__pycache__/binaries/oversized files/.env and
    other secret-shaped files/anything matched by the repo's own
    .gitignore. A hard-excluded file's contents are never read at all -
    it's filtered out by name/extension before any read is attempted.
  * scan_number increments per repeated scan of the same root path.
  * Scanning a nonexistent path raises RepositoryScanError *before* any
    RepositoryScan row is created (no junk "attempted" rows left behind).
  * Settings.repository_root_path defaults to this project's own root
    folder when REPOSITORY_ROOT isn't set.
  * The API layer (POST/GET /api/repository/...) requires auth, and its
    list/latest/detail/404 responses behave as expected.

Run with (from backend/):  pytest ../tests
"""
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from app.database.init_db import init_db

init_db()

from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.database.session import SessionLocal
from app.main import app
from app.models.enums import RepositoryScanStatus
from app.models.repository_scan import RepositoryScan
from app.services.repository_scanner import RepositoryScanError, scan_repository

client = TestClient(app)


def _unique_email() -> str:
    return f"m15p1-{uuid.uuid4().hex[:10]}@example.com"


def _auth() -> dict:
    email = _unique_email()
    password = "supersecret123"
    response = client.post(
        "/auth/register",
        json={"name": "Module15 Phase1 Tester", "email": email, "password": password, "confirm_password": password},
    )
    assert response.status_code == 201
    body = response.json()
    return {"Authorization": f"Bearer {body['access_token']}"}


def _make_sample_repo(tmp_path: Path) -> Path:
    root = tmp_path / "sample_repo"
    (root / "src").mkdir(parents=True)
    (root / "node_modules" / "pkg").mkdir(parents=True)
    (root / ".git").mkdir(parents=True)
    (root / "build").mkdir(parents=True)
    (root / "ignored_dir").mkdir(parents=True)

    (root / "src" / "otp_service.py").write_text(
        "import hashlib\n\ndef generate_otp():\n    return 123456\n"
    )
    (root / "src" / "app.jsx").write_text("export function App() { return null }\n")
    (root / "src" / "widget.generated.js").write_text("// generated, gitignored\n")
    (root / "node_modules" / "pkg" / "index.js").write_text("module.exports = {}\n")
    (root / ".git" / "HEAD").write_text("ref: refs/heads/main\n")
    (root / "build" / "bundle.js").write_text("/* generated */\n")
    (root / "ignored_dir" / "should_skip.py").write_text("print('should not be indexed')\n")
    (root / ".env").write_text("SECRET_KEY=super-secret-value\nDATABASE_PASSWORD=hunter2\n")
    (root / "logo.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 20)
    (root / "big.json").write_text("x" * (600 * 1024))  # over the 512KB size cap
    (root / ".gitignore").write_text("ignored_dir/\n*.generated.js\n")

    return root


def test_scan_indexes_source_and_skips_everything_it_should(tmp_path):
    root = _make_sample_repo(tmp_path)
    db = SessionLocal()
    try:
        scan = scan_repository(db, root_path=root, triggered_by=None)
        assert scan.status == RepositoryScanStatus.COMPLETED
        indexed_paths = {f.file_path for f in scan.files}

        assert "src/otp_service.py" in indexed_paths
        assert "src/app.jsx" in indexed_paths

        # node_modules/.git/build are never descended into at all.
        assert not any(p.startswith("node_modules/") for p in indexed_paths)
        assert not any(p.startswith(".git/") for p in indexed_paths)
        assert not any(p.startswith("build/") for p in indexed_paths)
        # secrets, oversized files, and .gitignore-matched files/dirs are skipped.
        assert ".env" not in indexed_paths
        assert "logo.png" not in indexed_paths
        assert "big.json" not in indexed_paths
        assert "ignored_dir/should_skip.py" not in indexed_paths
        assert "src/widget.generated.js" not in indexed_paths

        otp_file = next(f for f in scan.files if f.file_path == "src/otp_service.py")
        assert otp_file.language == "python"
        assert otp_file.line_count == 4
        assert scan.file_count == len(indexed_paths)
        assert scan.skipped_count > 0
    finally:
        db.close()


def test_scan_number_increments_per_root_path(tmp_path):
    root = _make_sample_repo(tmp_path)
    db = SessionLocal()
    try:
        first = scan_repository(db, root_path=root)
        second = scan_repository(db, root_path=root)
        assert second.scan_number == first.scan_number + 1
    finally:
        db.close()


def test_scan_nonexistent_path_raises_before_creating_a_row(tmp_path):
    missing = tmp_path / "does_not_exist"
    db = SessionLocal()
    try:
        count_before = db.query(RepositoryScan).count()
        raised = False
        try:
            scan_repository(db, root_path=missing)
        except RepositoryScanError:
            raised = True
        assert raised
        assert db.query(RepositoryScan).count() == count_before
    finally:
        db.close()


def test_default_repository_root_is_this_projects_own_folder():
    settings = get_settings()
    if settings.repository_root.strip():
        return  # explicitly overridden in this environment - nothing to assert
    root = settings.repository_root_path
    assert (root / "backend").is_dir()
    assert (root / "frontend").is_dir()


def test_api_requires_auth():
    assert client.post("/api/repository/scan").status_code == 401
    assert client.get("/api/repository").status_code == 401
    assert client.get("/api/repository/latest").status_code == 401


def test_api_scan_list_and_detail_round_trip():
    headers = _auth()
    response = client.post("/api/repository/scan", headers=headers)
    assert response.status_code == 201
    created = response.json()
    assert created["status"] == "completed"
    assert created["file_count"] >= 0

    listing = client.get("/api/repository", headers=headers)
    assert listing.status_code == 200
    assert any(s["id"] == created["id"] for s in listing.json())

    latest = client.get("/api/repository/latest", headers=headers)
    assert latest.status_code == 200
    assert latest.json()["id"] == created["id"]
    assert "files" in latest.json()

    detail = client.get(f"/api/repository/{created['id']}", headers=headers)
    assert detail.status_code == 200
    assert detail.json()["id"] == created["id"]


def test_api_unknown_scan_id_404s():
    headers = _auth()
    response = client.get("/api/repository/999999999", headers=headers)
    assert response.status_code == 404
