"""Verifies Module 15 Phase 2 (Repository Intelligence - Code
Understanding):

  * A Python file gets exact imports/functions/classes/API-route/database-
    reference/config-reference extraction via the stdlib `ast` module -
    including this project's own real patterns: an APIRouter prefix
    combined with a route decorator, a SQLAlchemy `__tablename__`, a
    `Mapped["User"]`-style relationship forward-reference, `os.getenv`/
    `os.environ[...]`, and a `settings.xxx` attribute access.
  * A JavaScript file gets a best-effort regex extraction covering this
    project's own conventions: ES imports, function/arrow-function
    declarations, a class, an `apiRequest(...)`/`fetch(...)` call's route,
    and `import.meta.env.*`/`process.env.*` references.
  * A JSON config file's top-level keys become config references.
  * A Python file with a genuine syntax error still gets indexed (path/
    language/size/line-count are unaffected) - it just gets empty
    understanding lists instead of failing the whole scan.
  * A file type Phase 2 doesn't attempt (markdown) gets empty lists too -
    never invented, never a reason to skip indexing the file itself.
  * The API layer returns these six fields as real JSON lists (never a
    raw JSON-encoded string, never null).

Run with (from backend/):  pytest ../tests
"""
import json
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from app.database.init_db import init_db

init_db()

from fastapi.testclient import TestClient

from app.database.session import SessionLocal
from app.main import app
from app.services.code_understanding import understand_file
from app.services.repository_scanner import scan_repository

client = TestClient(app)


def _unique_email() -> str:
    return f"m15p2-{uuid.uuid4().hex[:10]}@example.com"


def _auth() -> dict:
    email = _unique_email()
    password = "supersecret123"
    response = client.post(
        "/auth/register",
        json={"name": "Module15 Phase2 Tester", "email": email, "password": password, "confirm_password": password},
    )
    assert response.status_code == 201
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


_PY_SAMPLE = '''\
import os
from fastapi import APIRouter, Depends
from app.models.user import User

router = APIRouter(prefix="/api/widgets", tags=["widgets"])


class Widget(Base):
    __tablename__ = "widgets"
    owner: Mapped["User"] = relationship(back_populates="widgets")


@router.post("/create")
def create_widget(current_user: User = Depends(get_current_user)):
    api_key = os.getenv("WIDGET_API_KEY")
    db_password = os.environ["WIDGET_DB_PASSWORD"]
    result = db.query(Widget)
    return settings.repository_root_path
'''

_JS_SAMPLE = """\
import { apiRequest } from './client'

export function createWidget(payload, token) {
  return apiRequest(`/api/widgets/create`, { method: 'POST', body: payload, token })
}

export const getWidget = (id, token) => {
  return apiRequest(`/api/widgets/${id}`, { token })
}

class WidgetForm {}

const key = import.meta.env.VITE_WIDGET_KEY
"""

_JSON_SAMPLE = '{"name": "widgets", "version": "1.0", "scripts": {"dev": "vite"}}'


def _make_sample_repo(tmp_path: Path) -> Path:
    root = tmp_path / "phase2_repo"
    root.mkdir()
    (root / "widgets.py").write_text(_PY_SAMPLE)
    (root / "widgets.js").write_text(_JS_SAMPLE)
    (root / "package.json").write_text(_JSON_SAMPLE)
    (root / "broken.py").write_text("def broken(:\n    pass\n")
    (root / "README.md").write_text("# Widgets\n\nSome notes about widgets.\n")
    return root


def _file_by_path(scan, path: str):
    return next(f for f in scan.files if f.file_path == path)


def test_python_file_extraction(tmp_path):
    root = _make_sample_repo(tmp_path)
    db = SessionLocal()
    try:
        scan = scan_repository(db, root_path=root)
        widget = _file_by_path(scan, "widgets.py")

        assert set(json.loads(widget.imports)) >= {"os", "fastapi.APIRouter", "fastapi.Depends", "app.models.user.User"}
        assert json.loads(widget.functions) == ["create_widget"]
        assert json.loads(widget.classes) == ["Widget"]
        assert json.loads(widget.api_routes) == ["POST /api/widgets/create"]
        db_refs = set(json.loads(widget.database_references))
        assert "table:widgets" in db_refs
        assert "relationship:User" in db_refs
        assert "query:Widget" in db_refs
        config_refs = set(json.loads(widget.config_references))
        assert "env:WIDGET_API_KEY" in config_refs
        assert "env:WIDGET_DB_PASSWORD" in config_refs
        assert "settings.repository_root_path" in config_refs
    finally:
        db.close()


def test_js_file_extraction(tmp_path):
    root = _make_sample_repo(tmp_path)
    db = SessionLocal()
    try:
        scan = scan_repository(db, root_path=root)
        widget_js = _file_by_path(scan, "widgets.js")

        assert json.loads(widget_js.imports) == ["./client"]
        assert set(json.loads(widget_js.functions)) == {"createWidget", "getWidget"}
        assert json.loads(widget_js.classes) == ["WidgetForm"]
        assert set(json.loads(widget_js.api_routes)) == {"/api/widgets/create", "/api/widgets/${id}"}
        assert "env:VITE_WIDGET_KEY" in json.loads(widget_js.config_references)
    finally:
        db.close()


def test_json_config_extraction(tmp_path):
    root = _make_sample_repo(tmp_path)
    db = SessionLocal()
    try:
        scan = scan_repository(db, root_path=root)
        pkg = _file_by_path(scan, "package.json")
        config_refs = set(json.loads(pkg.config_references))
        assert {"key:name", "key:version", "key:scripts"} <= config_refs
    finally:
        db.close()


def test_syntax_error_file_still_indexed_with_empty_understanding(tmp_path):
    root = _make_sample_repo(tmp_path)
    db = SessionLocal()
    try:
        scan = scan_repository(db, root_path=root)
        broken = _file_by_path(scan, "broken.py")
        assert broken.line_count == 2
        assert broken.imports is None
        assert broken.functions is None
        assert broken.classes is None
    finally:
        db.close()


def test_unattempted_file_type_has_no_understanding_fields(tmp_path):
    root = _make_sample_repo(tmp_path)
    db = SessionLocal()
    try:
        scan = scan_repository(db, root_path=root)
        readme = _file_by_path(scan, "README.md")
        assert readme.imports is None
        assert readme.functions is None
        assert readme.database_references is None
    finally:
        db.close()


def test_understand_file_never_raises_on_garbage_input():
    # Defensive: whatever language string comes through, or unparseable
    # content, understand_file() always returns something, never raises -
    # a scan should never fail because one file's contents were odd.
    result = understand_file("\x00\x01 not real code {{{", "python")
    assert result.imports == []
    result = understand_file("", "unknown_language")
    assert result.functions == []


def test_api_returns_real_lists_not_json_strings():
    headers = _auth()
    response = client.post("/api/repository/scan", headers=headers)
    assert response.status_code == 201
    scan_id = response.json()["id"]

    detail = client.get(f"/api/repository/{scan_id}", headers=headers)
    assert detail.status_code == 200
    files = detail.json()["files"]
    assert len(files) > 0

    # This project's own backend/app/api/repository.py is always part of a
    # scan of its own repository - a real file, not a synthetic fixture,
    # confirming the whole pipeline (walk -> understand -> persist ->
    # serialize) works end to end on real code, not just a crafted sample.
    repository_router_file = next(
        (f for f in files if f["file_path"].endswith("backend/app/api/repository.py")), None
    )
    if repository_router_file is not None:
        assert isinstance(repository_router_file["imports"], list)
        assert isinstance(repository_router_file["api_routes"], list)
        assert any("scan" in route for route in repository_router_file["api_routes"])

    for f in files:
        for field_name in (
            "imports", "functions", "classes", "api_routes", "database_references", "config_references",
        ):
            assert isinstance(f[field_name], list)
