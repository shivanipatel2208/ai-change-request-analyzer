"""Module 12 Phase 5: parses @mentions out of a comment's raw text.

Deliberately simple - not a tokenizer/parser, just "does '@<user's full
name>' appear in this text", checked against every registered user (a small
team, no pagination concerns), longest name first so a short name (e.g.
"Al") can't shadow-match ahead of a longer one that starts the same way
(e.g. "Alice Tester"). Good enough for a small team; the frontend's mention
picker (see frontend/src/components/ChangeRequestDetail.jsx) inserts the
exact "@Full Name" text so what's typed always matches exactly what's
stored - nothing here tries to guess partial or misspelled names.
"""
from __future__ import annotations

from typing import Iterable, List, Optional

from app.models.user import User


def extract_mentioned_users(
    body: str, candidates: Iterable[User], *, exclude_user_id: Optional[int] = None
) -> List[User]:
    """Every candidate user whose "@Full Name" appears in `body`, longest
    name first, deduplicated, excluding `exclude_user_id` (the comment's
    own author - mentioning yourself doesn't notify yourself)."""
    lowered = body.lower()
    matched: List[User] = []
    seen_ids: set[int] = set()
    for candidate in sorted(candidates, key=lambda u: len(u.name), reverse=True):
        if candidate.id == exclude_user_id or candidate.id in seen_ids:
            continue
        needle = f"@{candidate.name}".lower()
        if needle in lowered:
            matched.append(candidate)
            seen_ids.add(candidate.id)
    return matched
