"""Aho-Corasick based fast-path for query-side entity recognition.

The LLM NER in ``kg_service.extract_query_entities`` is the dominant
per-query latency cost (300–800 ms against ``qwen3.5-flash``). But for any
query that mentions an entity we already know about, the NER problem
degenerates to "find substrings of the query that appear in the entity
dictionary" — an O(n + m) operation with Aho-Corasick.

Design notes:

* Singleton automaton in the process; built lazily on first use.
* Rebuilds are triggered by checking ``SELECT MAX(updated_at)`` on
  ``kg_entities`` before every match. SQLAlchemy's ``onupdate=func.now()``
  already bumps the column on merge, so ingesting a new document
  invalidates the cache naturally. The scalar query is a cheap index probe.
* Entries are registered per (name + each alias); on duplicate surface
  forms the entity with the highest ``mention_count`` wins, so the matcher
  biases toward "popular" interpretations when two entities share a name.
* Minimum surface-form length filters out 1-char tokens which are mostly
  noise in Chinese (no word boundaries → catastrophic false positives).
* The matcher resolves overlapping matches with longest-span-first greedy
  selection, e.g. query "张三丰" won't match entity "张三" if "张三丰"
  is also in the dictionary; if only "张三" is known, the 2-char match
  still fires (at which point the short-length filter is the main guard).
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from datetime import datetime

import ahocorasick
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.config import settings
from app.models.knowledge_graph import Entity
from app.services.kg_utils import is_blacklisted, normalize_name, parse_aliases

logger = logging.getLogger(__name__)


@dataclass
class _MatcherState:
    """Snapshot of a built automaton + the DB version it was built against."""

    automaton: ahocorasick.Automaton
    version: datetime | None
    size: int  # number of registered surface forms (for logs / diagnostics)


_state: _MatcherState | None = None
_lock = threading.Lock()


def _current_db_version(db: Session) -> datetime | None:
    """Return ``MAX(kg_entities.updated_at)`` — used as an opaque version token.

    Returns ``None`` when the table is empty so the first insert triggers a
    rebuild instead of serving an empty automaton forever.
    """
    return db.query(func.max(Entity.updated_at)).scalar()


def _build_automaton(db: Session, min_length: int) -> _MatcherState:
    """Load every entity + alias and compile a fresh Aho-Corasick automaton.

    Entities are pulled ordered by ``mention_count DESC`` so that when two
    entities share a surface form, the more-referenced one wins the slot
    (``automaton.add_word`` overwrites silently, but we early-skip after
    seeing the first insertion to keep the intent explicit).
    """
    start = time.perf_counter()
    rows = (
        db.query(Entity.id, Entity.entity_type, Entity.name, Entity.aliases, Entity.mention_count)
        .order_by(Entity.mention_count.desc(), Entity.id.asc())
        .all()
    )

    a = ahocorasick.Automaton()
    seen_keys: set[str] = set()
    registered = 0
    skipped_blacklist = 0
    skipped_short = 0

    for ent_id, etype, name, aliases_raw, _mention in rows:
        surfaces = [name, *parse_aliases(aliases_raw)]
        for raw in surfaces:
            key = normalize_name(raw)
            if not key:
                continue
            if len(key) < min_length:
                skipped_short += 1
                continue
            if is_blacklisted(key):
                skipped_blacklist += 1
                continue
            if key in seen_keys:
                continue
            seen_keys.add(key)
            a.add_word(key, (ent_id, etype, len(key)))
            registered += 1

    if registered > 0:
        a.make_automaton()

    elapsed_ms = (time.perf_counter() - start) * 1000
    logger.info(
        "KG automaton rebuilt: entities=%d registered=%d skipped_short=%d "
        "skipped_blacklist=%d elapsed=%.1fms",
        len(rows), registered, skipped_short, skipped_blacklist, elapsed_ms,
    )
    return _MatcherState(
        automaton=a,
        version=_current_db_version(db),
        size=registered,
    )


def _get_matcher(db: Session) -> _MatcherState | None:
    """Lazy accessor with cache-invalidation via ``MAX(updated_at)``.

    Returns ``None`` when the dictionary is empty — callers should treat
    that as "nothing to match against, fall back to LLM" rather than as
    an error.
    """
    global _state
    current = _current_db_version(db)
    cached = _state
    if cached is not None and cached.version == current and cached.size > 0:
        return cached

    with _lock:
        # Re-read under lock to avoid a thundering-herd rebuild if many
        # requests raced past the fast path simultaneously.
        cached = _state
        if cached is not None and cached.version == current and cached.size > 0:
            return cached

        min_length = max(1, settings.kg_query_automaton_min_length)
        new_state = _build_automaton(db, min_length=min_length)
        _state = new_state
        return new_state if new_state.size > 0 else None


def extract_entity_ids(db: Session, query: str) -> list[int]:
    """Return entity ids literally mentioned in ``query``.

    Resolution rules:
      * Empty / whitespace-only queries -> ``[]``.
      * Overlapping matches are disambiguated longest-span-first; e.g. if
        both "张三" and "张三丰" exist, a query of "张三丰的弟子" resolves
        to just "张三丰".
      * Duplicate entity ids across different surface forms are collapsed,
        preserving first-seen order so the downstream IDF ranker is
        deterministic.
    """
    q = normalize_name(query)
    if not q:
        return []

    matcher = _get_matcher(db)
    if matcher is None:
        return []

    matches: list[tuple[int, int, int]] = []  # (start, end_exclusive, entity_id)
    for end_idx, (ent_id, _etype, key_len) in matcher.automaton.iter(q):
        start = end_idx - key_len + 1
        matches.append((start, end_idx + 1, ent_id))

    if not matches:
        return []

    # Longest span wins; ties broken by earliest start.
    matches.sort(key=lambda m: (-(m[1] - m[0]), m[0]))

    taken: list[tuple[int, int]] = []
    ordered_ids: list[int] = []
    seen_ids: set[int] = set()
    for start, end_excl, ent_id in matches:
        if any(not (end_excl <= ts or start >= te) for ts, te in taken):
            continue
        taken.append((start, end_excl))
        if ent_id not in seen_ids:
            seen_ids.add(ent_id)
            ordered_ids.append(ent_id)

    return ordered_ids


def invalidate() -> None:
    """Drop the in-memory automaton; next call rebuilds.

    Exposed for tests and for explicit admin-side cache busts after bulk
    imports where relying on ``MAX(updated_at)`` drift isn't desirable.
    """
    global _state
    with _lock:
        _state = None
