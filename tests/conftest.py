"""Pytest bootstrap - runs before any test module in this directory is
imported, and is why this file has no tests of its own.

Every test file in this suite talks to the app the same simple way: import
app.database.init_db / app.main directly and drive them with FastAPI's
TestClient (hackathon-simple, no separate test-database wiring). Without
this file, that means every `pytest ../tests` run reads and writes the
exact same backend/data/app.db the developer is using in the browser at
the same time - so every user a test registers (a fresh one per test, via
each file's _register()/_auth() helper, uuid'd email but a fixed name)
permanently piles up in the real database. That's mostly just clutter in
the real app's "assign a team member" / "@mention" pickers, but as of
Module 12 Phase 5 it can cause a genuine test failure: run the suite
twice, and there are now two different users both named e.g. "Priya
Shah" - and @mention matching (app/services/mentions.py), which can only
go on the plain text of the comment, correctly matches both of them,
breaking a test written assuming there's exactly one.

Redirecting DATABASE_URL to its own throwaway sqlite file - before
app.core.config.get_settings() is ever called anywhere - keeps every
pytest run isolated from the real app's data and from every previous
pytest run. Deleting that file first means a clean slate every run, so no
test result ever depends on what a previous run left behind. This only
changes the environment of this pytest process - the already-running
`uvicorn app.main:app --reload` in your other terminal is a separate
program and is completely unaffected.
"""
import os
from pathlib import Path

_TEST_DB_PATH = Path(__file__).resolve().parent.parent / "backend" / "data" / "test_app.db"
_TEST_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
if _TEST_DB_PATH.exists():
    _TEST_DB_PATH.unlink()

os.environ["DATABASE_URL"] = f"sqlite:///{_TEST_DB_PATH.as_posix()}"
