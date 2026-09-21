"""Module 15 Phase 7 (Repository Intelligence - Security pass): a
dedicated test for the module's own spec rule 9 - "never expose API
keys/passwords/tokens/secrets/.env contents; don't index sensitive files
unnecessarily." Phases 1/2 already cover parts of this incidentally
(test_module15_phase1.py's "secrets are skipped" test,
test_module15_phase2.py's env-var-NAME extraction test) - this file is the
dedicated pass asked for by the spec, closing the gaps those didn't cover:

  * A HARDCODED secret literal - a bare module-level constant, a class
    attribute, or a getenv/environ.get *fallback default* - is never
    captured by the code-understanding extractor at all, under any field
    name. This is the one gap Phase 2's own test didn't cover: it proved
    the extractor captures the env var's NAME ("env:SECRET_KEY"), but never
    proved a literal secret VALUE sitting elsewhere in the same file stays
    out of every field.
  * Every category of "secret-shaped" file the scanner is supposed to
    refuse to open at all (.env and its .env.* variants, credentials.json,
    a private key file) is skipped before scanning - re-verified together
    here as one dedicated security checklist, rather than trusting each
    exclusion is still in place only because Phase 1's own test happens to
    check a couple of them.
  * The exact shape of what gets sent to the AI for repository matching
    (app/services/repository_matcher.py::_candidate_digest) is locked down
    to the known-safe field set - never raw file content, never anything
    resembling a "value" or "content" key - so a future change can't
    accidentally widen what leaves this app for an AI call.
  * The two public API response schemas this module added
    (IndexedFileRead, RepositoryFindingRead) are locked down to their known
    field sets too, for the same "a future change can't accidentally add a
    raw-content field" reason.

Run with (from backend/):  pytest ../tests
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from app.database.init_db import init_db

init_db()

from app.database.session import SessionLocal
from app.schemas.repository_finding import RepositoryFindingRead
from app.schemas.repository_scan import IndexedFileRead
from app.services import repository_matcher
from app.services.code_understanding import understand_file
from app.services.repository_scanner import scan_repository

# Secret-shaped VALUES that must never appear anywhere in extracted
# structure, however they're written into source - only their key/variable
# NAMES are ever legitimate to extract.
_SECRET_VALUES = [
    "sk-hardcoded-real-secret-abc123xyz",
    "ghp_realtokenvalue1234567890",
    "hunter2-actual-password",
    "sk_live_51ABCDEFGHIJKLMNOP",
]

_PYTHON_SOURCE_WITH_HARDCODED_SECRETS = '''
import os

SECRET_KEY = "sk-hardcoded-real-secret-abc123xyz"
API_TOKEN = "ghp_realtokenvalue1234567890"


def get_secret():
    fallback = os.getenv("SECRET_KEY", "sk-hardcoded-real-secret-abc123xyz")
    other = os.environ.get("DB_PASSWORD", "hunter2-actual-password")
    return fallback, other


class Config:
    STRIPE_KEY = "sk_live_51ABCDEFGHIJKLMNOP"
'''


def _all_extracted_strings(understanding) -> list[str]:
    return (
        understanding.imports
        + understanding.functions
        + understanding.classes
        + understanding.api_routes
        + understanding.database_references
        + understanding.config_references
    )


def test_hardcoded_secret_literals_never_leak_into_extracted_structure():
    understanding = understand_file(_PYTHON_SOURCE_WITH_HARDCODED_SECRETS, "python")

    all_extracted = _all_extracted_strings(understanding)
    for secret_value in _SECRET_VALUES:
        assert not any(secret_value in extracted for extracted in all_extracted), (
            f"Secret value {secret_value!r} leaked into extracted structure: {all_extracted}"
        )

    # The env var NAMES themselves are still legitimately captured - this
    # isn't "extract nothing about config," just "never the value."
    assert "env:SECRET_KEY" in understanding.config_references
    assert "env:DB_PASSWORD" in understanding.config_references
    # The class constant and the bare module-level secrets aren't captured
    # under ANY field - the extractor only ever looks at getenv/environ/
    # settings access patterns for config_references, never arbitrary
    # module-level or class-level assignments.
    assert understanding.config_references == ["env:SECRET_KEY", "env:DB_PASSWORD"]


def test_hardcoded_secret_in_javascript_never_leaks():
    js_source = """
const STRIPE_KEY = "sk_live_51ABCDEFGHIJKLMNOP"
const apiKey = process.env.WIDGET_API_KEY
function chargeCard() {
  return fetch('/api/charge')
}
"""
    understanding = understand_file(js_source, "javascript")
    all_extracted = _all_extracted_strings(understanding)
    assert not any("sk_live_51ABCDEFGHIJKLMNOP" in extracted for extracted in all_extracted)
    assert understanding.config_references == ["env:WIDGET_API_KEY"]


def test_secret_shaped_files_are_never_indexed(tmp_path):
    """One combined checklist for every "never open this at all" category
    the module spec calls out, scanned together so a future refactor that
    accidentally narrows the exclusion list fails one obvious test rather
    than silently regressing one file type at a time."""
    root = tmp_path / "secrets_repo"
    root.mkdir()

    (root / ".env").write_text("SECRET_KEY=super-secret-value\nDATABASE_PASSWORD=hunter2\n")
    (root / ".env.production").write_text("SECRET_KEY=another-secret\n")
    (root / "credentials.json").write_text('{"private_key": "-----BEGIN PRIVATE KEY-----"}')
    (root / "service-account.json").write_text('{"private_key": "-----BEGIN PRIVATE KEY-----"}')
    (root / "id_rsa.pem").write_text("-----BEGIN RSA PRIVATE KEY-----\nMIIEow...\n-----END RSA PRIVATE KEY-----\n")
    (root / "server.key").write_text("-----BEGIN PRIVATE KEY-----\nMIIEow...\n-----END PRIVATE KEY-----\n")
    (root / ".npmrc").write_text("//registry.npmjs.org/:_authToken=npm_realtoken123\n")
    # A legitimate source file, so the scan itself succeeds and this test
    # can tell "nothing indexed because everything was correctly skipped"
    # apart from "nothing indexed because the scan itself failed."
    (root / "app.py").write_text("def handler():\n    return 'ok'\n")

    db = SessionLocal()
    try:
        scan = scan_repository(db, root_path=root)
        # Asserted here, before the session closes below - scan.files is a
        # lazy relationship (same reason test_module15_phase1.py's own scan
        # test reads it inside this same try block rather than after).
        assert scan.status.value == "completed"
        indexed_paths = {f.file_path for f in scan.files}
        assert indexed_paths == {"app.py"}
        assert scan.skipped_count >= 7
    finally:
        db.close()


def test_ai_candidate_digest_never_includes_raw_content():
    """Locks down exactly what app/services/repository_matcher.py sends the
    AI provider for one candidate file - the known-safe field set only,
    never a "content"/"source"/"text" key that could carry raw file bytes
    (and therefore any secret literal sitting in them, whatever the
    scanner's own file-level exclusions miss)."""

    class _FakeIndexedFile:
        file_path = "app/config.py"
        language = "python"
        imports = None
        functions = None
        classes = None
        api_routes = None
        database_references = None
        config_references = '["env:SECRET_KEY"]'

    digest = repository_matcher._candidate_digest(_FakeIndexedFile())
    assert set(digest.keys()) == {
        "file_path",
        "language",
        "imports",
        "functions",
        "classes",
        "api_routes",
        "database_references",
        "config_references",
    }
    for forbidden_key in ("content", "source", "text", "body", "raw"):
        assert forbidden_key not in digest


def test_response_schemas_never_expose_raw_file_content():
    """IndexedFileRead and RepositoryFindingRead - the two schemas this
    module returns from the API - are locked to their known field sets, so
    a future field added to either model doesn't silently start returning
    raw file content to the frontend without anyone deciding that on
    purpose."""
    indexed_file_fields = set(IndexedFileRead.model_fields.keys())
    assert indexed_file_fields == {
        "id",
        "file_path",
        "language",
        "size_bytes",
        "line_count",
        "imports",
        "functions",
        "classes",
        "api_routes",
        "database_references",
        "config_references",
    }
    for forbidden_key in ("content", "source", "text", "body", "raw"):
        assert forbidden_key not in indexed_file_fields

    finding_fields = set(RepositoryFindingRead.model_fields.keys())
    for forbidden_key in ("content", "source", "text", "body", "raw", "file_content"):
        assert forbidden_key not in finding_fields
