"""Small utility helpers shared across the knowledge-graph services.

Extracted from ``kg_service`` so the new automaton-based matcher
(``kg_entity_matcher``) can reuse the same normalization / alias parsing /
blacklist semantics without introducing a circular import between the two
service modules.
"""

from __future__ import annotations

import json

from app.config import settings


def normalize_name(name: str) -> str:
    """Light-weight textual normalization for exact-match fast paths.

    Applies ``casefold()`` so English surface forms (e.g. "Snowflake" vs
    "snowflake") collapse to a single canonical key. Casefold is a no-op for
    CJK characters, so Chinese entities are unaffected.
    """
    return (name or "").strip().casefold()


def parse_aliases(raw: str | None) -> list[str]:
    """Parse the JSON-encoded aliases column into a plain list of strings."""
    if not raw:
        return []
    try:
        data = json.loads(raw)
        return [str(x) for x in data] if isinstance(data, list) else []
    except (json.JSONDecodeError, TypeError):
        return []


def dump_aliases(aliases: list[str]) -> str:
    """Serialize aliases back to the canonical JSON storage format."""
    return json.dumps(list(dict.fromkeys(aliases)), ensure_ascii=False)


def is_blacklisted(name: str) -> bool:
    """True if the (already-normalized) entity name is in the configured blacklist."""
    if not name:
        return True
    blacklist = settings.kg_entity_blacklist_set
    if not blacklist:
        return False
    return name in blacklist
