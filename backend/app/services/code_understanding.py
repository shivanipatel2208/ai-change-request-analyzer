"""Module 15 Phase 2 (Repository Intelligence - Code Understanding).

For each indexed file, extracts a lightweight structural summary: imports,
function names, class names, API routes, and database/config references.
Deliberately not a full static analyzer ("keep implementation lightweight"
per the module's own spec):

  * Python gets real, exact answers via the stdlib `ast` module - no extra
    dependency, and no risk of the regex-style false positives/negatives
    every other language here is subject to.
  * JavaScript/TypeScript/JSX/TSX get a best-effort regex pass - good
    enough to find the common patterns this project's own frontend
    actually uses (import/require, `apiRequest(...)`/`fetch(...)` calls,
    `import.meta.env.*`), but not a real parser.
  * JSON/YAML/TOML/INI config files get their top-level keys read as
    config references (JSON via the stdlib parser; the rest via a simple
    line pattern, not a real parser).
  * SQL files get table names read off FROM/INTO/UPDATE/TABLE keywords.
  * Anything else (markdown, CSS, HTML, shell scripts, ...) yields empty
    lists - not every file has to have findings, and inventing some would
    be worse than none.

A file that can't be understood this way (a syntax error, a JSON parse
failure, ...) never fails the scan over it - understand_file() always
returns a result, falling back to empty lists, the same way an unreadable
file is just skipped rather than aborting the whole walk
(repository_scanner.py).
"""
from __future__ import annotations

import ast
import json
import re
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class CodeUnderstanding:
    imports: list[str] = field(default_factory=list)
    functions: list[str] = field(default_factory=list)
    classes: list[str] = field(default_factory=list)
    api_routes: list[str] = field(default_factory=list)
    database_references: list[str] = field(default_factory=list)
    config_references: list[str] = field(default_factory=list)


def _dedupe(values: list[str]) -> list[str]:
    seen: dict[str, None] = {}
    for value in values:
        seen.setdefault(value, None)
    return list(seen.keys())


def understand_file(content: str, language: Optional[str]) -> CodeUnderstanding:
    try:
        if language == "python":
            return _understand_python(content)
        if language in ("javascript", "typescript"):
            return _understand_js(content)
        if language == "json":
            return _understand_json_config(content)
        if language in ("yaml", "toml", "ini"):
            return _understand_line_based_config(content)
        if language == "sql":
            return _understand_sql(content)
    except Exception:  # noqa: BLE001 - a file this app can't parse is just empty, never a scan failure
        pass
    return CodeUnderstanding()


# --- Python (stdlib ast - exact, no dependency) -------------------------

_HTTP_DECORATOR_METHODS = {"get", "post", "put", "patch", "delete", "websocket"}
_FORWARD_REF_RE = re.compile(r"^[A-Z][A-Za-z0-9_]*$")


def _literal_str(node) -> Optional[str]:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def _kwarg_str(call: ast.Call, name: str) -> Optional[str]:
    for kw in call.keywords:
        if kw.arg == name:
            return _literal_str(kw.value)
    return None


def _dotted_name(node) -> Optional[str]:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = _dotted_name(node.value)
        return f"{base}.{node.attr}" if base else node.attr
    return None


def _route_from_decorator(decorator: ast.expr, router_prefixes: dict[str, str]) -> Optional[str]:
    if not isinstance(decorator, ast.Call):
        return None
    func = decorator.func
    if not isinstance(func, ast.Attribute) or func.attr not in _HTTP_DECORATOR_METHODS:
        return None
    if not isinstance(func.value, ast.Name):
        return None
    path = _literal_str(decorator.args[0]) if decorator.args else None
    if path is None:
        return None
    prefix = router_prefixes.get(func.value.id, "")
    return f"{func.attr.upper()} {prefix}{path}"


def _forward_ref_strings(annotation: ast.expr) -> list[str]:
    """Pulls string forward-references out of a `Mapped[...]` style type
    annotation, e.g. `Mapped["User"]` or `Mapped[List["Analysis"]]` - this
    project's own SQLAlchemy models declare every relationship's target
    exactly this way (see app/models/change_request.py), so this is a real,
    precise way to find ORM relationships, not a guess."""
    found = []
    for node in ast.walk(annotation):
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and _FORWARD_REF_RE.match(node.value):
            found.append(node.value)
    return found


def _understand_python(source: str) -> CodeUnderstanding:
    imports: list[str] = []
    functions: list[str] = []
    classes: list[str] = []
    api_routes: list[str] = []
    database_references: list[str] = []
    config_references: list[str] = []
    router_prefixes: dict[str, str] = {}

    try:
        tree = ast.parse(source)
    except SyntaxError:
        return CodeUnderstanding()

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            imports.extend(f"{module}.{alias.name}" if module else alias.name for alias in node.names)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            functions.append(node.name)
            for decorator in node.decorator_list:
                route = _route_from_decorator(decorator, router_prefixes)
                if route:
                    api_routes.append(route)
        elif isinstance(node, ast.ClassDef):
            classes.append(node.name)
        elif isinstance(node, ast.AnnAssign) and node.annotation is not None:
            if isinstance(node.target, ast.Name) and node.target.id == "__tablename__":
                value = _literal_str(node.value) if node.value is not None else None
                if value:
                    database_references.append(f"table:{value}")
            for ref in _forward_ref_strings(node.annotation):
                database_references.append(f"relationship:{ref}")
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "__tablename__":
                    value = _literal_str(node.value)
                    if value:
                        database_references.append(f"table:{value}")
            if (
                len(node.targets) == 1
                and isinstance(node.targets[0], ast.Name)
                and isinstance(node.value, ast.Call)
                and _dotted_name(node.value.func) == "APIRouter"
            ):
                prefix = _kwarg_str(node.value, "prefix") or ""
                router_prefixes[node.targets[0].id] = prefix
        elif isinstance(node, ast.Call):
            call_name = _dotted_name(node.func)
            if call_name == "ForeignKey" and node.args:
                target = _literal_str(node.args[0])
                if target:
                    database_references.append(f"foreign_key:{target}")
            elif call_name in ("os.getenv", "os.environ.get") and node.args:
                value = _literal_str(node.args[0])
                if value:
                    config_references.append(f"env:{value}")
            elif call_name and call_name.split(".")[-1] == "query" and node.args:
                if isinstance(node.args[0], ast.Name):
                    database_references.append(f"query:{node.args[0].id}")
        elif isinstance(node, ast.Subscript):
            if _dotted_name(node.value) == "os.environ":
                key_node = node.slice
                value = _literal_str(key_node)
                if value:
                    config_references.append(f"env:{value}")
        elif isinstance(node, ast.Attribute):
            if isinstance(node.value, ast.Name) and node.value.id == "settings":
                config_references.append(f"settings.{node.attr}")

    return CodeUnderstanding(
        imports=_dedupe(imports),
        functions=_dedupe(functions),
        classes=_dedupe(classes),
        api_routes=_dedupe(api_routes),
        database_references=_dedupe(database_references),
        config_references=_dedupe(config_references),
    )


# --- JavaScript / TypeScript (regex best-effort) -------------------------

_JS_IMPORT_FROM_RE = re.compile(r"""(?:import|export)\s[^;]*?\sfrom\s+['"]([^'"]+)['"]""")
_JS_BARE_IMPORT_RE = re.compile(r"""^\s*import\s+['"]([^'"]+)['"]""", re.MULTILINE)
_JS_REQUIRE_RE = re.compile(r"""require\(\s*['"]([^'"]+)['"]\s*\)""")
_JS_DYNAMIC_IMPORT_RE = re.compile(r"""import\(\s*['"]([^'"]+)['"]\s*\)""")
_JS_FUNCTION_DECL_RE = re.compile(r"""\bfunction\s+([A-Za-z_$][\w$]*)\s*\(""")
_JS_CONST_ARROW_RE = re.compile(r"""\b(?:const|let)\s+([A-Za-z_$][\w$]*)\s*=\s*(?:async\s*)?\([^)]*\)\s*=>""")
_JS_CONST_FUNC_RE = re.compile(r"""\b(?:const|let)\s+([A-Za-z_$][\w$]*)\s*=\s*(?:async\s*)?function""")
_JS_CLASS_RE = re.compile(r"""\bclass\s+([A-Za-z_$][\w$]*)""")
_JS_ROUTE_CALL_RE = re.compile(
    r"""\b(?:apiRequest|fetch|axios\.(?:get|post|put|patch|delete))\(\s*[`'"]([^`'"]+)[`'"]"""
)
_JS_ENV_RE = re.compile(r"""(?:import\.meta\.env|process\.env)\.([A-Za-z_][A-Za-z0-9_]*)""")


def _understand_js(source: str) -> CodeUnderstanding:
    imports = (
        _JS_IMPORT_FROM_RE.findall(source)
        + _JS_BARE_IMPORT_RE.findall(source)
        + _JS_REQUIRE_RE.findall(source)
        + _JS_DYNAMIC_IMPORT_RE.findall(source)
    )
    functions = (
        _JS_FUNCTION_DECL_RE.findall(source)
        + _JS_CONST_ARROW_RE.findall(source)
        + _JS_CONST_FUNC_RE.findall(source)
    )
    classes = _JS_CLASS_RE.findall(source)
    api_routes = _JS_ROUTE_CALL_RE.findall(source)
    config_references = [f"env:{name}" for name in _JS_ENV_RE.findall(source)]

    return CodeUnderstanding(
        imports=_dedupe(imports),
        functions=_dedupe(functions),
        classes=_dedupe(classes),
        api_routes=_dedupe(api_routes),
        database_references=[],
        config_references=_dedupe(config_references),
    )


# --- Config files (JSON exact, YAML/TOML/INI best-effort) ----------------


def _understand_json_config(source: str) -> CodeUnderstanding:
    try:
        data = json.loads(source)
    except ValueError:
        return CodeUnderstanding()
    if isinstance(data, dict):
        keys = [f"key:{key}" for key in data.keys()]
        return CodeUnderstanding(config_references=_dedupe(keys))
    return CodeUnderstanding()


_CONFIG_LINE_KEY_RE = re.compile(r"""^\s*([A-Za-z_][A-Za-z0-9_.\-]*)\s*[:=]""")


def _understand_line_based_config(source: str) -> CodeUnderstanding:
    keys = []
    for line in source.splitlines():
        if line.strip().startswith(("#", ";", "[")):
            continue
        match = _CONFIG_LINE_KEY_RE.match(line)
        if match:
            keys.append(f"key:{match.group(1)}")
    return CodeUnderstanding(config_references=_dedupe(keys))


# --- SQL (keyword-based table references) --------------------------------

_SQL_TABLE_RE = re.compile(r"""\b(?:FROM|INTO|UPDATE|TABLE)\s+["'`]?([A-Za-z_][\w]*)""", re.IGNORECASE)


def _understand_sql(source: str) -> CodeUnderstanding:
    tables = [f"table:{name}" for name in _SQL_TABLE_RE.findall(source)]
    return CodeUnderstanding(database_references=_dedupe(tables))
