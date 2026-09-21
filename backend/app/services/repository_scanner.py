"""Module 15 Phase 1 (Repository Intelligence): safely walks a local
repository/folder and records what it found as a RepositoryScan +
IndexedFile rows.

Deliberately lightweight, per the module's own spec ("do not introduce
unnecessary infrastructure"): no upload/archive handling, no external
indexing service, no third-party gitignore-parsing dependency - just
os.walk with an allow-list of source-like extensions, a deny-list of
directories/files that should never be touched, and a small best-effort
.gitignore reader for the common cases (comments, blank lines, a plain
"name" or "name/" or "*.ext" pattern; a leading "/" anchors it to the
scanned root; negation ("!pattern") is not supported - "respect .gitignore
where practical" per the spec, not a full gitignore-spec implementation).

This module NEVER reads the contents of anything on the hard-excluded
list below - secrets/env files are skipped before they are ever opened,
not read-then-redacted.

Module 15 Phase 2 (Code Understanding): every file kept here also gets
passed to app.services.code_understanding.understand_file(), and its
imports/functions/classes/api_routes/database_references/
config_references are stored alongside the basic path/language/size/line
stats recorded in Phase 1.
"""
from __future__ import annotations

import fnmatch
import json
import os
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.indexed_file import IndexedFile
from app.models.repository_scan import RepositoryScan
from app.models.enums import RepositoryScanStatus
from app.services.code_understanding import understand_file

# --- Directories never descended into, regardless of .gitignore --------
# Dependency/build/VCS/cache noise, plus this app's own SQLite data folder
# (binary database files, not source).
_IGNORED_DIR_NAMES = {
    "node_modules", ".git", ".hg", ".svn", "__pycache__", ".venv", "venv",
    "env", ".env.d", "build", "dist", ".next", ".nuxt", "out", "target",
    "bin", "obj", ".cache", "coverage", ".nyc_output", ".pytest_cache",
    ".mypy_cache", ".ruff_cache", ".tox", ".idea", ".vscode", ".parcel-cache",
    "site-packages", "data",
}

# --- Exact filenames that are always skipped - secrets first, then large
# generated/lockfiles that carry no hand-written meaning of their own. ---
_ALWAYS_IGNORED_FILENAMES = {
    ".env", ".npmrc", ".pypirc", ".netrc",
    "package-lock.json", "yarn.lock", "pnpm-lock.yaml", "poetry.lock", "Pipfile.lock",
    "credentials.json", "service-account.json",
}
_ALWAYS_IGNORED_FILENAME_PREFIXES = (".env.",)

# --- Extensions that are always skipped - secrets/keys, then binaries and
# other formats that aren't meaningfully "source". ---
_ALWAYS_IGNORED_EXTENSIONS = {
    ".pem", ".key", ".crt", ".cer", ".p12", ".pfx", ".keystore", ".jks",
    ".pyc", ".pyo", ".so", ".dll", ".dylib", ".exe", ".class", ".jar", ".war",
    ".db", ".sqlite", ".sqlite3",
    ".zip", ".tar", ".gz", ".tgz", ".7z", ".rar",
    ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".ico", ".webp", ".svg",
    ".mp4", ".mov", ".avi", ".mp3", ".wav", ".pdf",
    ".woff", ".woff2", ".ttf", ".eot", ".otf",
    ".whl", ".egg", ".map", ".lock",
}

# --- The only extensions actually indexed - an allow-list is safer than
# trying to enumerate every possible binary format. ---
_INDEXABLE_EXTENSIONS = {
    ".py", ".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs",
    ".json", ".yaml", ".yml", ".toml", ".ini", ".cfg",
    ".html", ".css", ".scss", ".less",
    ".md", ".sql", ".sh", ".bat", ".ps1",
}

_EXTENSION_LANGUAGE_MAP = {
    ".py": "python",
    ".js": "javascript", ".jsx": "javascript", ".mjs": "javascript", ".cjs": "javascript",
    ".ts": "typescript", ".tsx": "typescript",
    ".json": "json", ".yaml": "yaml", ".yml": "yaml", ".toml": "toml",
    ".ini": "ini", ".cfg": "ini",
    ".html": "html", ".css": "css", ".scss": "scss", ".less": "less",
    ".md": "markdown", ".sql": "sql",
    ".sh": "shell", ".bat": "batch", ".ps1": "powershell",
}

# Files larger than this are skipped as "large irrelevant files" per the
# module spec, regardless of extension - a 5MB generated JSON fixture isn't
# useful context for matching a change request to source code.
MAX_INDEXABLE_FILE_BYTES = 512 * 1024


class RepositoryScanError(Exception):
    """Raised for a scan that can't even start (bad/missing configured
    path) - distinct from a per-file problem during the walk, which is
    just skipped and counted, never enough to fail the whole scan."""


@dataclass
class _WalkResult:
    indexed: list[dict] = field(default_factory=list)
    skipped_count: int = 0


def _load_gitignore_patterns(root: Path) -> list[str]:
    gitignore_path = root / ".gitignore"
    if not gitignore_path.is_file():
        return []
    patterns: list[str] = []
    try:
        text = gitignore_path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or stripped.startswith("!"):
            continue  # blank/comment/negation - negation isn't supported, see module docstring
        patterns.append(stripped)
    return patterns


def _matches_gitignore(rel_posix: str, basename: str, patterns: list[str]) -> bool:
    for pattern in patterns:
        pattern = pattern.rstrip("/")  # a trailing slash just marks "directory-only"
        if not pattern:
            continue
        if pattern.startswith("/"):
            anchored = pattern.lstrip("/")
            if fnmatch.fnmatch(rel_posix, anchored) or fnmatch.fnmatch(rel_posix, f"{anchored}/*"):
                return True
        else:
            if (
                fnmatch.fnmatch(basename, pattern)
                or fnmatch.fnmatch(rel_posix, pattern)
                or fnmatch.fnmatch(rel_posix, f"*/{pattern}")
                or fnmatch.fnmatch(rel_posix, f"{pattern}/*")
                or fnmatch.fnmatch(rel_posix, f"*/{pattern}/*")
            ):
                return True
    return False


def _should_skip_file(rel_posix: str, basename: str, ext: str, size_bytes: int, gitignore_patterns: list[str]) -> bool:
    if basename in _ALWAYS_IGNORED_FILENAMES:
        return True
    if any(basename.startswith(prefix) for prefix in _ALWAYS_IGNORED_FILENAME_PREFIXES):
        return True
    if ext in _ALWAYS_IGNORED_EXTENSIONS:
        return True
    if ext not in _INDEXABLE_EXTENSIONS:
        return True
    if size_bytes > MAX_INDEXABLE_FILE_BYTES:
        return True
    if _matches_gitignore(rel_posix, basename, gitignore_patterns):
        return True
    return False


def _walk(root: Path) -> _WalkResult:
    result = _WalkResult()
    gitignore_patterns = _load_gitignore_patterns(root)

    for dirpath, dirnames, filenames in os.walk(root):
        # Prune ignored directories in place so os.walk never descends into
        # them at all - not "descend then discard".
        kept_dirnames = []
        for d in dirnames:
            if d in _IGNORED_DIR_NAMES:
                continue
            rel_dir_posix = str(PurePosixPath(*Path(dirpath, d).relative_to(root).parts))
            if _matches_gitignore(rel_dir_posix, d, gitignore_patterns):
                continue
            kept_dirnames.append(d)
        dirnames[:] = kept_dirnames

        for filename in filenames:
            full_path = Path(dirpath) / filename
            rel_parts = full_path.relative_to(root).parts
            rel_posix = str(PurePosixPath(*rel_parts))
            ext = full_path.suffix.lower()

            try:
                size_bytes = full_path.stat().st_size
            except OSError:
                result.skipped_count += 1
                continue

            if _should_skip_file(rel_posix, filename, ext, size_bytes, gitignore_patterns):
                result.skipped_count += 1
                continue

            try:
                content = full_path.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                result.skipped_count += 1
                continue

            language = _EXTENSION_LANGUAGE_MAP.get(ext)
            # Module 15 Phase 2: reuses the content already read above for
            # line-counting - never a second file read. A file this can't
            # make sense of (bad syntax, etc.) just comes back with empty
            # lists, never a reason to skip indexing the file itself.
            understanding = understand_file(content, language)

            result.indexed.append(
                {
                    "file_path": rel_posix,
                    "language": language,
                    "size_bytes": size_bytes,
                    "line_count": content.count("\n") + (1 if content and not content.endswith("\n") else 0),
                    "imports": json.dumps(understanding.imports) if understanding.imports else None,
                    "functions": json.dumps(understanding.functions) if understanding.functions else None,
                    "classes": json.dumps(understanding.classes) if understanding.classes else None,
                    "api_routes": json.dumps(understanding.api_routes) if understanding.api_routes else None,
                    "database_references": (
                        json.dumps(understanding.database_references) if understanding.database_references else None
                    ),
                    "config_references": (
                        json.dumps(understanding.config_references) if understanding.config_references else None
                    ),
                }
            )

    return result


def scan_repository(
    db: Session,
    *,
    root_path: Optional[Path] = None,
    triggered_by: Optional[int] = None,
) -> RepositoryScan:
    """Walks `root_path` (or the app's configured repository root if not
    given) and records the result as a new RepositoryScan + IndexedFile
    rows. Never mutates or deletes a prior scan - each call is a new, fully
    independent row, so an old scan's findings are always still exactly
    what they were (same non-destructive rule Module 13 Phase 3 applies to
    AI re-analysis)."""
    if root_path is None:
        from app.core.config import get_settings

        root_path = get_settings().repository_root_path

    root_path = Path(root_path).expanduser().resolve()
    if not root_path.exists() or not root_path.is_dir():
        raise RepositoryScanError(
            f"Configured repository path does not exist or is not a folder: {root_path}"
        )

    scan_number = (
        db.query(func.max(RepositoryScan.scan_number))
        .filter(RepositoryScan.root_path == str(root_path))
        .scalar()
        or 0
    ) + 1

    scan = RepositoryScan(
        root_path=str(root_path),
        scan_number=scan_number,
        status=RepositoryScanStatus.COMPLETED,
        triggered_by=triggered_by,
        started_at=datetime.utcnow(),
    )
    db.add(scan)
    db.flush()

    try:
        walk_result = _walk(root_path)
    except Exception as exc:  # noqa: BLE001 - a genuinely unexpected walk failure
        scan.status = RepositoryScanStatus.FAILED
        scan.error_message = str(exc)
        scan.completed_at = datetime.utcnow()
        db.commit()
        db.refresh(scan)
        return scan

    for entry in walk_result.indexed:
        db.add(IndexedFile(scan_id=scan.id, **entry))

    scan.file_count = len(walk_result.indexed)
    scan.skipped_count = walk_result.skipped_count
    scan.completed_at = datetime.utcnow()
    db.commit()
    db.refresh(scan)
    return scan
