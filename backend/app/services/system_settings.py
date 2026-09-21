"""Module 21 spec section 5 (System Settings) - deliberately scoped down
from the spec's full list. Two different things live here:

1. A genuinely admin-editable setting (cr_categories) - stored as a
   SystemSetting row, read/written through get_cr_categories/
   set_cr_categories below.
2. Read-only info panels for AI provider / repository / knowledge base
   configuration - these stay .env-driven (see app/core/config.py) and are
   only ever DISPLAYED here, never written through this module. Changing
   them still goes through the guided .env edit this project has always
   used, not a form that saves directly - see get_ai_provider_info /
   get_repository_info / get_knowledge_base_info, none of which ever
   return an actual API key or secret.

Priority values and the workflow status transition graph are NOT exposed
here at all, editable or otherwise - both are load-bearing across risk
scoring, sorting, and the status machine throughout this app (see
app/services/workflow_rules.py), and making them admin-editable at
runtime would be a real risk of quietly breaking other modules rather
than a simple settings toggle. That's a deliberate, disclosed scope limit
(see PROJECT_REPORT.md's Module 21 section), not an oversight.

cr_categories itself is ALSO scoped down from what it might look like it
does: it's a plain editable reference list (add/rename/remove a category
name), stored and returned as-is - it is NOT yet wired into the Dashboard
(app/api/dashboard.py) or Analytics (app/services/analytics.py) category
groupings, which each keep their own separate, already-tested
CANONICAL_CATEGORIES/_CATEGORY_ALIASES copies (a pre-existing, deliberate
duplication - see either file's own comments). Properly synchronizing an
editable alias-keyword mapping into both of those without risking a
regression in already-shipped reporting is a larger change than this
module takes on; this list is a maintained reference for now.
"""
from __future__ import annotations

import json
from typing import List, Optional

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.knowledge_document import KnowledgeDocument
from app.models.repository_scan import RepositoryScan
from app.models.system_setting import SystemSetting

CR_CATEGORIES_KEY = "cr_categories"

# Same default vocabulary app/api/change_requests.py, app/api/dashboard.py,
# and app/services/analytics.py each already hardcode their own copy of.
DEFAULT_CR_CATEGORIES: List[str] = [
    "Feature",
    "Bug Fix",
    "Security",
    "Database",
    "API",
    "Infrastructure",
    "Integration",
]


def get_cr_categories(db: Session) -> List[str]:
    row = db.get(SystemSetting, CR_CATEGORIES_KEY)
    if row is None:
        return list(DEFAULT_CR_CATEGORIES)
    try:
        value = json.loads(row.value_json)
    except (TypeError, ValueError):
        return list(DEFAULT_CR_CATEGORIES)
    return value if isinstance(value, list) else list(DEFAULT_CR_CATEGORIES)


def set_cr_categories(db: Session, categories: List[str], *, updated_by: Optional[int]) -> None:
    row = db.get(SystemSetting, CR_CATEGORIES_KEY)
    value_json = json.dumps(categories)
    if row is None:
        db.add(SystemSetting(key=CR_CATEGORIES_KEY, value_json=value_json, updated_by=updated_by))
    else:
        row.value_json = value_json
        row.updated_by = updated_by
    db.flush()


def get_ai_provider_info() -> dict:
    """Never returns an API key - only which provider is active, which
    model it's configured to use, and whether a key is present at all
    (True/False, never the value)."""
    settings = get_settings()
    provider = settings.ai_provider
    model_by_provider = {
        "anthropic": settings.anthropic_model,
        "openai": settings.openai_model,
        "gemini": settings.gemini_model,
        "ollama": settings.ollama_model,
        "openrouter": settings.openrouter_model,
    }
    key_configured_by_provider = {
        "anthropic": bool(settings.anthropic_api_key),
        "openai": bool(settings.openai_api_key),
        "gemini": bool(settings.gemini_api_key),
        "ollama": True,  # no key needed - runs locally
        "openrouter": bool(settings.openrouter_api_key),
    }
    return {
        "provider": provider,
        "model": model_by_provider.get(provider, "unknown"),
        "api_key_configured": key_configured_by_provider.get(provider, False),
        "embeddings_supported": provider == "openrouter",
    }


def get_repository_info(db: Session) -> dict:
    settings = get_settings()
    latest_scan = db.query(RepositoryScan).order_by(RepositoryScan.started_at.desc()).first()
    return {
        "repository_root": str(settings.repository_root_path),
        "last_scan_status": latest_scan.status.value if latest_scan else None,
        "last_scan_file_count": latest_scan.file_count if latest_scan else None,
        "last_scan_at": latest_scan.completed_at or latest_scan.started_at if latest_scan else None,
    }


def get_knowledge_base_info(db: Session) -> dict:
    settings = get_settings()
    document_count = db.query(KnowledgeDocument).count()
    return {
        "embedding_model": settings.openrouter_embedding_model,
        "embeddings_supported": settings.ai_provider == "openrouter",
        "document_count": document_count,
    }
