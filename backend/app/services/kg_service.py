"""Knowledge-graph service — normalize entities with vector similarity, persist
document→entity edges, and incrementally build document↔document relations using
a single aggregate SQL over the entity inverted-index.

Flow per document:
    1. graph_data = {entities: [...], document_relations: [...]}  from LLM
    2. batch-embed "{type}: {name}" for every entity
    3. for each candidate: vector-normalize against same-type existing entities
         -> merge (update aliases + centroid) OR create new row
    4. write kg_document_entities rows (one per entity-doc edge)
    5. run aggregate SQL: shared_entities with *other* docs >= min_shared
    6. batch-insert kg_document_relations for new edges (undirected, src_id < dst_id)
"""

from __future__ import annotations

import json
import logging
import math
from collections import Counter
from typing import Any

from sqlalchemy import func, text
from sqlalchemy.orm import Session

from app.config import settings
from app.core.ai_service import call_ai_json
from app.core.embedding_service import (
    cosine_similarity,
    embed_texts,
    pack_vector,
    unpack_vector,
    weighted_mean,
)
from app.models.knowledge_graph import DocumentEntity, DocumentRelation, Entity

logger = logging.getLogger(__name__)

_VALID_ENTITY_TYPES = {
    "person", "customer", "project", "product", "org", "contract", "other",
}
_VALID_REL_TYPES = {"mentions", "authored_by", "about", "belongs_to"}


def _is_blacklisted(name: str) -> bool:
    """True if the (already-normalized) entity name is in the configured blacklist."""
    if not name:
        return True
    blacklist = settings.kg_entity_blacklist_set
    if not blacklist:
        return False
    return name in blacklist


# ---- Helpers ----------------------------------------------------------------

def _embed_text(entity_type: str, name: str) -> str:
    """Canonical text used to compute an entity's embedding (type-prefixed)."""
    return f"{entity_type}: {name}"


def _normalize_name(name: str) -> str:
    """Light-weight textual normalization for exact-match fast path.

    Applies casefold() so English surface forms (e.g. "Snowflake" vs "snowflake")
    collapse to a single canonical key. Casefold is a no-op for CJK characters,
    so Chinese entities are unaffected.
    """
    return (name or "").strip().casefold()


def _parse_aliases(raw: str | None) -> list[str]:
    if not raw:
        return []
    try:
        data = json.loads(raw)
        return [str(x) for x in data] if isinstance(data, list) else []
    except (json.JSONDecodeError, TypeError):
        return []


def _dump_aliases(aliases: list[str]) -> str:
    return json.dumps(list(dict.fromkeys(aliases)), ensure_ascii=False)


# ---- Entity normalization ---------------------------------------------------

def _find_similar_entity(
    db: Session,
    entity_type: str,
    candidate_vec: list[float],
    threshold: float,
) -> tuple[Entity | None, float]:
    """Find the existing same-type entity with highest cosine similarity.

    SQLite-friendly implementation: load all same-type entity rows into memory and
    compute cosine. For typical deployments (< 50k entities per type) this is well
    under 100 ms. Callers should profile if scales grow larger — at that point a
    pgvector-backed query should replace this function.
    """
    rows = (
        db.query(Entity)
        .filter(Entity.entity_type == entity_type)
        .filter(Entity.embedding.isnot(None))
        .all()
    )
    best: Entity | None = None
    best_score = -1.0
    for row in rows:
        if not row.embedding or not row.embedding_dim:
            continue
        vec = unpack_vector(row.embedding, row.embedding_dim)
        score = cosine_similarity(candidate_vec, vec)
        if score > best_score:
            best_score = score
            best = row
    if best is not None and best_score >= threshold:
        return best, best_score
    return None, best_score


def _exact_match_entity(db: Session, entity_type: str, name: str) -> Entity | None:
    """Fast path: exact name or alias hit within the same entity_type.

    Case-insensitive on both sides: the query text is casefold()-ed via
    ``_normalize_name`` and the stored ``Entity.name`` is wrapped in ``LOWER()``
    at the SQL layer, so legacy rows stored with original casing still match.
    """
    name_n = _normalize_name(name)
    if not name_n:
        return None

    row = (
        db.query(Entity)
        .filter(
            Entity.entity_type == entity_type,
            func.lower(Entity.name) == name_n,
        )
        .first()
    )
    if row is not None:
        return row

    candidates = (
        db.query(Entity)
        .filter(Entity.entity_type == entity_type)
        .filter(func.lower(Entity.aliases).contains(name_n))
        .all()
    )
    for c in candidates:
        folded = [_normalize_name(a) for a in _parse_aliases(c.aliases)]
        if name_n in folded:
            return c
    return None


def _merge_entity(
    db: Session,
    existing: Entity,
    candidate_name: str,
    candidate_aliases: list[str],
    candidate_vec: list[float],
) -> None:
    """Update an entity in place when merging a new observation."""
    aliases = _parse_aliases(existing.aliases)
    new_forms = [_normalize_name(candidate_name), *candidate_aliases]
    for n in new_forms:
        if n and n != existing.name and n not in aliases:
            aliases.append(n)
    existing.aliases = _dump_aliases(aliases)

    if candidate_vec and existing.embedding_dim:
        old_vec = unpack_vector(existing.embedding or b"", existing.embedding_dim)
        merged = weighted_mean(old_vec, existing.mention_count, candidate_vec)
        existing.embedding = pack_vector(merged)
        existing.embedding_dim = len(merged)

    existing.mention_count = (existing.mention_count or 0) + 1


def _create_entity(
    db: Session,
    name: str,
    entity_type: str,
    aliases: list[str],
    vec: list[float],
) -> Entity:
    ent = Entity(
        name=_normalize_name(name),
        entity_type=entity_type,
        aliases=_dump_aliases(aliases),
        embedding=pack_vector(vec) if vec else None,
        embedding_dim=len(vec) if vec else 0,
        mention_count=1,
    )
    db.add(ent)
    db.flush()
    return ent


async def normalize_entities(
    db: Session,
    candidates: list[dict[str, Any]],
) -> list[tuple[int, dict[str, Any]]]:
    """Normalize a batch of candidate entities, returning [(entity_id, candidate), ...].

    Each candidate dict must have: name (str), type (str), aliases (list[str]).
    - Invalid/empty entries are filtered out silently.
    - Exact-name/alias match within same type takes the fast path (no embedding).
    - Otherwise falls back to cosine similarity against same-type embeddings.

    Embeddings for candidates are computed **in a single batched request** to
    minimize DashScope calls. If embedding fails the pipeline continues with the
    exact-match results (degrades gracefully).
    """
    cleaned: list[dict[str, Any]] = []
    for c in candidates:
        name = _normalize_name(c.get("name", ""))
        etype = (c.get("type") or "other").strip().lower()
        if not name:
            continue
        if _is_blacklisted(name):
            logger.debug("Skipping blacklisted entity: %s", name)
            continue
        if etype not in _VALID_ENTITY_TYPES:
            etype = "other"
        aliases = [
            _normalize_name(a) for a in (c.get("aliases") or [])
            if _normalize_name(a) and not _is_blacklisted(_normalize_name(a))
        ]
        cleaned.append({"name": name, "type": etype, "aliases": aliases})

    if not cleaned:
        return []

    exact_hits: dict[int, Entity] = {}
    pending_idx: list[int] = []
    for i, c in enumerate(cleaned):
        hit = _exact_match_entity(db, c["type"], c["name"])
        if hit is not None:
            exact_hits[i] = hit
        else:
            pending_idx.append(i)

    pending_vectors: dict[int, list[float]] = {}
    if pending_idx:
        texts = [_embed_text(cleaned[i]["type"], cleaned[i]["name"]) for i in pending_idx]
        try:
            vecs = await embed_texts(texts)
            for idx, vec in zip(pending_idx, vecs):
                pending_vectors[idx] = vec
        except Exception as exc:
            logger.warning(
                "Embedding failed for %d entities, falling back to name-only matching: %s",
                len(pending_idx), exc,
            )

    results: list[tuple[int, dict[str, Any]]] = []
    threshold = settings.kg_entity_merge_threshold

    for i, c in enumerate(cleaned):
        if i in exact_hits:
            ent = exact_hits[i]
            _merge_entity(db, ent, c["name"], c["aliases"], pending_vectors.get(i, []))
            results.append((ent.id, c))
            continue

        vec = pending_vectors.get(i, [])
        matched: Entity | None = None
        if vec:
            matched, _score = _find_similar_entity(db, c["type"], vec, threshold)

        if matched is not None:
            _merge_entity(db, matched, c["name"], c["aliases"], vec)
            results.append((matched.id, c))
        else:
            new_ent = _create_entity(db, c["name"], c["type"], c["aliases"], vec)
            results.append((new_ent.id, c))

    db.flush()
    return results


# ---- Per-document graph persistence ----------------------------------------

def _write_document_entities(
    db: Session,
    doc_id: int,
    entity_map: list[tuple[int, dict[str, Any]]],
    document_relations: list[dict[str, Any]],
) -> list[int]:
    """Upsert kg_document_entities rows using a UNION strategy (no deletion).

    Behaviour:
      * Existing ``(doc_id, entity_id, relation_type)`` rows are kept as-is,
        protecting the graph against transient LLM under-extraction.
      * New triples produced by this extraction run are inserted if not already
        present (relies on the ``uq_doc_entity_rel`` unique constraint).
      * The returned list is the UNION of all entity ids linked to this document
        (old + new), so edge rebuilding is based on the complete picture.
    """
    name_to_id: dict[str, int] = {}
    for ent_id, c in entity_map:
        name_to_id[c["name"]] = ent_id
        for alias in c.get("aliases") or []:
            name_to_id[alias] = ent_id

    incoming_rels: dict[int, str] = {}
    for r in document_relations or []:
        ent_name = _normalize_name(r.get("entity_name", ""))
        rel_type = (r.get("relation") or "mentions").strip().lower()
        if rel_type not in _VALID_REL_TYPES:
            rel_type = "mentions"
        ent_id = name_to_id.get(ent_name)
        if ent_id is not None:
            incoming_rels[ent_id] = rel_type

    for ent_id, _c in entity_map:
        incoming_rels.setdefault(ent_id, "mentions")

    existing_rows = (
        db.query(DocumentEntity.entity_id, DocumentEntity.relation_type)
        .filter(DocumentEntity.document_id == doc_id)
        .all()
    )
    existing_triples: set[tuple[int, str]] = {(eid, rel) for eid, rel in existing_rows}
    existing_entity_ids: set[int] = {eid for eid, _ in existing_rows}

    inserted = 0
    for ent_id, rel_type in incoming_rels.items():
        if (ent_id, rel_type) in existing_triples:
            continue
        db.add(DocumentEntity(
            document_id=doc_id,
            entity_id=ent_id,
            relation_type=rel_type,
            confidence=1.0,
        ))
        existing_triples.add((ent_id, rel_type))
        existing_entity_ids.add(ent_id)
        inserted += 1

    db.flush()
    if inserted:
        logger.debug(
            "KG upsert doc_id=%s inserted=%d kept=%d total_entities=%d",
            doc_id, inserted, len(existing_rows), len(existing_entity_ids),
        )
    return list(existing_entity_ids)


def _dominant_relation_type(db: Session, shared_entity_ids: list[int]) -> str:
    """Pick a relation label based on the majority entity_type in the shared set."""
    if not shared_entity_ids:
        return "related"
    types = [
        t for (t,) in db.query(Entity.entity_type)
        .filter(Entity.id.in_(shared_entity_ids)).all()
    ]
    if not types:
        return "related"
    top, count = Counter(types).most_common(1)[0]
    if count == 0:
        return "related"
    mapping = {
        "project": "same_project",
        "customer": "same_customer",
        "person": "same_person",
        "product": "same_product",
        "org": "same_org",
        "contract": "same_contract",
    }
    return mapping.get(top, "related")


def _build_relations_for_document(
    db: Session,
    doc_id: int,
    entity_ids: list[int],
) -> int:
    """Build/refresh doc-doc edges using the entity inverted-index.

    Executes one aggregate SQL to find all other docs sharing >= min_shared entities,
    then batch-inserts the edges (deleting any stale edges touching *doc_id* first).
    Returns the number of edges written.
    """
    if not entity_ids:
        return 0

    min_shared = max(1, settings.kg_min_shared_entities)
    max_edges = max(1, settings.kg_max_edges_per_doc)

    db.query(DocumentRelation).filter(
        (DocumentRelation.src_doc_id == doc_id)
        | (DocumentRelation.dst_doc_id == doc_id)
    ).delete(synchronize_session=False)
    db.flush()

    placeholders = ",".join([f":e{i}" for i in range(len(entity_ids))])
    params: dict[str, Any] = {f"e{i}": eid for i, eid in enumerate(entity_ids)}
    params["doc_id"] = doc_id
    params["min_shared"] = min_shared
    params["max_edges"] = max_edges

    sql = text(
        f"""
        SELECT document_id, COUNT(*) AS shared_count
        FROM kg_document_entities
        WHERE entity_id IN ({placeholders})
          AND document_id != :doc_id
        GROUP BY document_id
        HAVING COUNT(*) >= :min_shared
        ORDER BY shared_count DESC
        LIMIT :max_edges
        """
    )
    rows = db.execute(sql, params).all()

    written = 0
    for other_doc_id, shared_count in rows:
        other_entity_ids = [
            eid for (eid,) in db.query(DocumentEntity.entity_id)
            .filter(DocumentEntity.document_id == other_doc_id)
            .filter(DocumentEntity.entity_id.in_(entity_ids))
            .all()
        ]
        if not other_entity_ids:
            continue

        rel_type = _dominant_relation_type(db, other_entity_ids)
        src = min(doc_id, other_doc_id)
        dst = max(doc_id, other_doc_id)

        db.add(DocumentRelation(
            src_doc_id=src,
            dst_doc_id=dst,
            relation_type=rel_type,
            weight=float(shared_count),
            shared_entities=json.dumps(other_entity_ids, ensure_ascii=False),
        ))
        written += 1

    db.flush()
    return written


async def save_graph(
    db: Session,
    doc_id: int,
    graph_data: dict[str, Any],
) -> dict[str, Any]:
    """Entry point: persist the extracted graph for a single document.

    `graph_data` must match the structure produced by graph_extract.txt:
        {"entities": [...], "document_relations": [...]}
    """
    if not doc_id or not isinstance(graph_data, dict):
        return {"entity_count": 0, "relation_count": 0}

    entities = graph_data.get("entities") or []
    doc_rels = graph_data.get("document_relations") or []

    entity_map = await normalize_entities(db, entities)
    linked_entity_ids = _write_document_entities(db, doc_id, entity_map, doc_rels)
    edges_written = _build_relations_for_document(db, doc_id, linked_entity_ids)

    db.commit()
    logger.info(
        "KG saved for doc_id=%s entities=%d edges=%d",
        doc_id, len(linked_entity_ids), edges_written,
    )
    return {
        "entity_count": len(linked_entity_ids),
        "relation_count": edges_written,
    }


# ---- Query-side helpers -----------------------------------------------------

async def extract_query_entities(query: str) -> list[dict[str, Any]]:
    """Run the lightweight LLM prompt to pull entities from a user question.

    Uses ``settings.kg_query_model`` (defaults to ``qwen3.5-flash``) rather
    than the heavyweight ``dashscope_model``: query-time NER is simple,
    latency-sensitive, and runs on every user question.
    """
    if not (query or "").strip():
        return []
    try:
        data = await call_ai_json(
            "graph_query_extract.txt",
            query,
            temperature=0.0,
            max_tokens=512,
            model=settings.kg_query_model,
        )
    except Exception as exc:
        logger.warning("Query entity extraction failed: %s", exc)
        return []
    entities = data.get("entities") if isinstance(data, dict) else None
    return entities if isinstance(entities, list) else []


async def match_query_entities(
    db: Session,
    query_entities: list[dict[str, Any]],
) -> list[Entity]:
    """Map user-question entities to existing DB entities via exact+vector match.

    Returns DB rows; candidates with no match are dropped silently.
    """
    matched: list[Entity] = []
    pending: list[tuple[int, dict[str, Any]]] = []

    for idx, c in enumerate(query_entities):
        name = _normalize_name(c.get("name", ""))
        etype = (c.get("type") or "other").strip().lower()
        if not name:
            continue
        if _is_blacklisted(name):
            continue
        if etype not in _VALID_ENTITY_TYPES:
            etype = "other"

        hit = _exact_match_entity(db, etype, name)
        if hit is not None:
            matched.append(hit)
        else:
            pending.append((idx, {"name": name, "type": etype}))

    if pending:
        try:
            vecs = await embed_texts([_embed_text(c["type"], c["name"]) for _, c in pending])
        except Exception as exc:
            logger.warning("Query embedding failed: %s", exc)
            vecs = []

        threshold = settings.kg_entity_merge_threshold
        for (_, c), vec in zip(pending, vecs):
            if not vec:
                continue
            row, _ = _find_similar_entity(db, c["type"], vec, threshold)
            if row is not None:
                matched.append(row)

    seen: set[int] = set()
    deduped: list[Entity] = []
    for e in matched:
        if e.id not in seen:
            seen.add(e.id)
            deduped.append(e)
    return deduped


def _compute_entity_idf(
    db: Session,
    entity_ids: list[int],
) -> dict[int, float]:
    """Return {entity_id: idf_weight} where idf = 1 / log(1 + df).

    ``df`` is the number of distinct documents mentioning the entity in
    ``kg_document_entities``. Rare entities (low df) get high weight; "star"
    noise entities (high df) get their influence naturally damped.

    Entities absent from the inverted index default to df=0 -> weight=1/log(1)=inf,
    so we floor df at 1 (effective weight ~1.44).
    """
    if not entity_ids:
        return {}

    placeholders = ",".join([f":e{i}" for i in range(len(entity_ids))])
    params = {f"e{i}": eid for i, eid in enumerate(entity_ids)}

    sql = text(
        f"""
        SELECT entity_id, COUNT(DISTINCT document_id) AS df
        FROM kg_document_entities
        WHERE entity_id IN ({placeholders})
        GROUP BY entity_id
        """
    )
    rows = db.execute(sql, params).all()

    df_map: dict[int, int] = {eid: 1 for eid in entity_ids}
    for entity_id, df in rows:
        df_map[entity_id] = max(1, int(df))

    return {eid: 1.0 / math.log(1 + df) for eid, df in df_map.items()}


def retrieve_by_entities(
    db: Session,
    entity_ids: list[int],
    *,
    top_k: int = 10,
    expand_one_hop: bool = True,
) -> list[dict[str, Any]]:
    """Score documents by how well they match the given entity set.

    Scoring:
        direct_score(doc) = sum of IDF weights for each matched entity in doc
                            where weight(entity) = 1 / log(1 + df(entity))
        expansion_score   = sum over (related_doc edge weights) for 1-hop neighbours,
                            weighted by 0.5 to rank them below direct hits

    IDF weighting ensures rare/specific entities (e.g. a contract number) dominate
    the score over noisy high-frequency entities (e.g. "本公司"). The edge weight
    in kg_document_relations is kept as-is (it is a count of shared entities).

    Returns a list of dicts sorted by score descending, capped at top_k.
    """
    if not entity_ids:
        return []

    from app.models.document import Document  # local import to avoid cycle

    idf_weights = _compute_entity_idf(db, entity_ids)

    placeholders = ",".join([f":e{i}" for i in range(len(entity_ids))])
    params = {f"e{i}": eid for i, eid in enumerate(entity_ids)}
    detail_sql = text(
        f"""
        SELECT document_id, entity_id
        FROM kg_document_entities
        WHERE entity_id IN ({placeholders})
        """
    )
    detail_rows = db.execute(detail_sql, params).all()

    scores: dict[int, float] = {}
    matched_entities_per_doc: dict[int, set[int]] = {}
    for doc_id, ent_id in detail_rows:
        weight = idf_weights.get(ent_id, 1.0)
        scores[doc_id] = scores.get(doc_id, 0.0) + weight
        matched_entities_per_doc.setdefault(doc_id, set()).add(ent_id)

    if expand_one_hop and scores:
        direct_doc_ids = list(scores.keys())
        rel_rows = db.query(
            DocumentRelation.src_doc_id,
            DocumentRelation.dst_doc_id,
            DocumentRelation.weight,
        ).filter(
            (DocumentRelation.src_doc_id.in_(direct_doc_ids))
            | (DocumentRelation.dst_doc_id.in_(direct_doc_ids))
        ).all()
        for src, dst, weight in rel_rows:
            other = dst if src in scores else src
            if other in scores:
                continue
            scores[other] = scores.get(other, 0.0) + 0.5 * float(weight)

    if not scores:
        return []

    doc_ids_sorted = sorted(scores.keys(), key=lambda d: scores[d], reverse=True)[:top_k]
    docs = {
        d.id: d for d in db.query(Document).filter(Document.id.in_(doc_ids_sorted)).all()
    }

    results: list[dict[str, Any]] = []
    for doc_id in doc_ids_sorted:
        doc = docs.get(doc_id)
        if doc is None:
            continue
        results.append({
            "doc_id": doc_id,
            "filename": doc.filename,
            "knowledge_db_name": doc.filename,  # matches dify_uploader's knowlege_db_name
            "department": doc.department,
            "status": doc.status,
            "score": round(scores[doc_id], 4),
            "matched_entities": sorted(list(matched_entities_per_doc.get(doc_id, set()))),
        })
    return results


async def retrieve_by_query(
    db: Session,
    query: str,
    *,
    top_k: int = 10,
    department: str | None = None,
) -> dict[str, Any]:
    """Full graph-retrieval pipeline used by the Dify integration endpoint."""
    q_entities = await extract_query_entities(query)
    matched = await match_query_entities(db, q_entities)
    entity_ids = [e.id for e in matched]

    documents = retrieve_by_entities(db, entity_ids, top_k=top_k)

    if department:
        documents = [d for d in documents if (d.get("department") or "") == department]

    return {
        "query": query,
        "matched_entities": [
            {"id": e.id, "name": e.name, "type": e.entity_type}
            for e in matched
        ],
        "documents": documents,
    }


# ---- Doc subgraph (for visualization) --------------------------------------

def get_document_graph(db: Session, doc_id: int) -> dict[str, Any]:
    """Return a small subgraph centered on *doc_id* for UI visualization."""
    from app.models.document import Document  # local import

    root = db.get(Document, doc_id)
    if root is None:
        return {"nodes": [], "edges": []}

    entity_rows = (
        db.query(DocumentEntity, Entity)
        .join(Entity, DocumentEntity.entity_id == Entity.id)
        .filter(DocumentEntity.document_id == doc_id)
        .all()
    )

    related_rows = (
        db.query(DocumentRelation)
        .filter(
            (DocumentRelation.src_doc_id == doc_id)
            | (DocumentRelation.dst_doc_id == doc_id)
        )
        .all()
    )
    related_doc_ids = {
        (r.dst_doc_id if r.src_doc_id == doc_id else r.src_doc_id)
        for r in related_rows
    }
    related_docs = {
        d.id: d for d in db.query(Document).filter(Document.id.in_(related_doc_ids)).all()
    } if related_doc_ids else {}

    nodes: list[dict[str, Any]] = [{
        "id": f"doc:{root.id}",
        "label": root.filename,
        "type": "document",
        "department": root.department,
        "is_root": True,
    }]

    for de, ent in entity_rows:
        nodes.append({
            "id": f"ent:{ent.id}",
            "label": ent.name,
            "type": "entity",
            "entity_type": ent.entity_type,
            "mention_count": ent.mention_count,
        })

    for rel_doc_id, rel_doc in related_docs.items():
        nodes.append({
            "id": f"doc:{rel_doc.id}",
            "label": rel_doc.filename,
            "type": "document",
            "department": rel_doc.department,
            "is_root": False,
        })

    edges: list[dict[str, Any]] = []
    for de, ent in entity_rows:
        edges.append({
            "source": f"doc:{doc_id}",
            "target": f"ent:{ent.id}",
            "type": de.relation_type,
        })

    for r in related_rows:
        other = r.dst_doc_id if r.src_doc_id == doc_id else r.src_doc_id
        edges.append({
            "source": f"doc:{doc_id}",
            "target": f"doc:{other}",
            "type": r.relation_type,
            "weight": r.weight,
        })

    return {"nodes": nodes, "edges": edges}
