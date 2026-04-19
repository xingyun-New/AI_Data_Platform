"""Knowledge-graph API — retrieval endpoint for Dify workflows, plus inspection
endpoints for the frontend and a backfill endpoint for bootstrapping existing
documents into the graph.

Note on auth: `POST /retrieve` is intentionally left unauthenticated so that it
can be called directly from a Dify HTTP node without embedding JWTs in the
workflow. Other endpoints require a logged-in user.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core import file_manager
from app.database import get_db
from app.models.document import Document
from app.models.knowledge_graph import DocumentEntity, DocumentRelation, Entity
from app.services import kg_service

logger = logging.getLogger(__name__)

router = APIRouter()


# ---- Request / response schemas --------------------------------------------

class RetrieveRequest(BaseModel):
    query: str
    top_k: int = 10
    department: str | None = None


class RetrieveDocItem(BaseModel):
    doc_id: int
    filename: str
    knowledge_db_name: str
    department: str
    status: str
    score: float
    matched_entities: list[int]
    # Populated only when kg_enable_index_rerank is True. ``kg_score`` is the
    # raw entity-match IDF score (pre-fusion); ``index_cosine`` is the cosine
    # between the user query and the doc's stored index embedding. Both are
    # exposed so Dify / the admin UI can surface "why was this doc picked".
    kg_score: float | None = None
    index_cosine: float | None = None


class RetrieveDocRelation(BaseModel):
    src_doc_id: int
    dst_doc_id: int
    weight: float


class RetrieveResponse(BaseModel):
    query: str
    matched_entities: list[dict[str, Any]]
    documents: list[RetrieveDocItem]
    doc_relations: list[RetrieveDocRelation] = []
    knowledge_db_names: list[str]


class RebuildResponse(BaseModel):
    total: int
    success: int
    failed: int
    errors: list[dict[str, Any]] = []


# ---- Public: retrieval (consumed by Dify HTTP node) ------------------------

@router.post("/retrieve", response_model=RetrieveResponse)
async def retrieve(
    body: RetrieveRequest,
    db: Session = Depends(get_db),
):
    """Primary endpoint consumed by Dify workflow.

    Flow:
      1. Extract entities from the user query (lightweight LLM)
      2. Match to canonical entity rows (vector similarity)
      3. Score documents by entity mentions + 1-hop expansion via
         kg_document_relations
      4. Return ranked doc list with `knowledge_db_name` for Dify metadata filter
    """
    if not body.query or not body.query.strip():
        raise HTTPException(status_code=400, detail="query 不能为空")

    result = await kg_service.retrieve_by_query(
        db, body.query.strip(),
        top_k=max(1, min(body.top_k, 50)),
        department=body.department or None,
    )

    documents = result["documents"]
    return RetrieveResponse(
        query=result["query"],
        matched_entities=result["matched_entities"],
        documents=documents,
        doc_relations=result.get("doc_relations", []),
        knowledge_db_names=[d["knowledge_db_name"] for d in documents],
    )


# ---- Authenticated inspection endpoints ------------------------------------

@router.get("/document/{doc_id}")
def document_subgraph(
    doc_id: int,
    db: Session = Depends(get_db),
    _user: dict = Depends(get_current_user),
):
    """Return entities and related documents for one document (for UI)."""
    doc = db.get(Document, doc_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="文档不存在")
    return kg_service.get_document_graph(db, doc_id)


@router.get("/entities")
def list_entities(
    q: str | None = Query(None, description="名称模糊匹配"),
    entity_type: str | None = Query(None),
    page: int = Query(1, ge=1),
    size: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    _user: dict = Depends(get_current_user),
):
    query = db.query(Entity)
    if entity_type:
        query = query.filter(Entity.entity_type == entity_type)
    if q:
        pattern = f"%{q}%"
        query = query.filter(
            (Entity.name.like(pattern)) | (Entity.aliases.like(pattern))
        )
    total = query.count()
    rows = (
        query.order_by(Entity.mention_count.desc(), Entity.id.desc())
        .offset((page - 1) * size)
        .limit(size)
        .all()
    )
    items = []
    for r in rows:
        try:
            aliases = json.loads(r.aliases) if r.aliases else []
        except json.JSONDecodeError:
            aliases = []
        items.append({
            "id": r.id,
            "name": r.name,
            "entity_type": r.entity_type,
            "aliases": aliases,
            "mention_count": r.mention_count,
            "created_at": str(r.created_at or ""),
        })
    return {"total": total, "page": page, "size": size, "items": items}


@router.get("/entities/{entity_id}/documents")
def entity_documents(
    entity_id: int,
    db: Session = Depends(get_db),
    _user: dict = Depends(get_current_user),
):
    """List documents that mention a given entity."""
    ent = db.get(Entity, entity_id)
    if ent is None:
        raise HTTPException(status_code=404, detail="实体不存在")

    rows = (
        db.query(DocumentEntity, Document)
        .join(Document, DocumentEntity.document_id == Document.id)
        .filter(DocumentEntity.entity_id == entity_id)
        .all()
    )
    return {
        "entity": {
            "id": ent.id, "name": ent.name, "entity_type": ent.entity_type,
        },
        "documents": [
            {
                "doc_id": d.id,
                "filename": d.filename,
                "department": d.department,
                "relation_type": de.relation_type,
                "status": d.status,
            }
            for de, d in rows
        ],
    }


@router.get("/stats")
def stats(
    db: Session = Depends(get_db),
    _user: dict = Depends(get_current_user),
):
    """Top-level counts for the admin dashboard."""
    entity_count = db.query(Entity).count()
    doc_entity_count = db.query(DocumentEntity).count()
    doc_relation_count = db.query(DocumentRelation).count()

    type_rows = (
        db.query(Entity.entity_type, Entity.id).all()
    )
    by_type: dict[str, int] = {}
    for etype, _eid in type_rows:
        by_type[etype] = by_type.get(etype, 0) + 1

    return {
        "entity_count": entity_count,
        "document_entity_count": doc_entity_count,
        "document_relation_count": doc_relation_count,
        "entities_by_type": by_type,
    }


# ---- Backfill / rebuild endpoint ------------------------------------------

class RebuildRequest(BaseModel):
    document_ids: list[int] | None = None
    only_missing: bool = True
    limit: int | None = None


@router.post("/rebuild", response_model=RebuildResponse)
async def rebuild(
    body: RebuildRequest = RebuildRequest(),
    db: Session = Depends(get_db),
    _user: dict = Depends(get_current_user),
):
    """Re-extract KG data for existing indexed/uploaded documents.

    Strategy:
      - Look up documents whose index JSON already sits on disk (cheap).
      - If the persisted index contains `knowledge_graph`, reuse it (no LLM cost).
      - Otherwise run the graph-extract prompt against the raw content.
      - Persist via `kg_service.save_graph`.

    `only_missing` skips documents that already have at least one DocumentEntity row.
    """
    from app.core.ai_service import call_ai_json
    from app.core.index_generator import GRAPH_PROMPT_FILE
    from app.core.file_manager import read_file, read_index

    query = db.query(Document).filter(Document.status.in_(["indexed", "uploaded"]))
    if body.document_ids:
        query = query.filter(Document.id.in_(body.document_ids))
    all_docs = query.order_by(Document.id.asc()).all()

    if body.only_missing:
        existing_doc_ids = {
            row[0] for row in db.query(DocumentEntity.document_id).distinct().all()
        }
        all_docs = [d for d in all_docs if d.id not in existing_doc_ids]

    if body.limit and body.limit > 0:
        all_docs = all_docs[: body.limit]

    total = len(all_docs)
    success = 0
    failed = 0
    errors: list[dict[str, Any]] = []

    for doc in all_docs:
        try:
            stem = Path(doc.filename).stem
            graph_block: dict[str, Any] | None = None

            index_raw = read_index(stem)
            if index_raw:
                try:
                    idx = json.loads(index_raw)
                    if isinstance(idx, dict) and idx.get("knowledge_graph"):
                        graph_block = idx["knowledge_graph"]
                except json.JSONDecodeError:
                    pass

            if graph_block is None:
                if not doc.raw_path or not Path(doc.raw_path).exists():
                    raise FileNotFoundError(f"raw 文件缺失: {doc.raw_path}")
                content = read_file(Path(doc.raw_path))
                try:
                    graph_block = await call_ai_json(
                        GRAPH_PROMPT_FILE, content,
                        temperature=0.1, max_tokens=4096,
                    )
                except Exception as exc:
                    raise RuntimeError(f"graph-extract LLM 失败: {exc}") from exc

                if index_raw:
                    try:
                        idx = json.loads(index_raw)
                        idx["knowledge_graph"] = {
                            "entities": graph_block.get("entities") or [],
                            "document_relations": graph_block.get("document_relations") or [],
                        }
                        file_manager.write_index(
                            stem, json.dumps(idx, ensure_ascii=False, indent=2),
                        )
                    except Exception as exc:
                        logger.warning("回写 index json 失败 (%s): %s", doc.filename, exc)

            await kg_service.save_graph(db, doc.id, graph_block)
            success += 1
        except Exception as exc:
            failed += 1
            errors.append({"doc_id": doc.id, "filename": doc.filename, "error": str(exc)})
            logger.exception("Rebuild KG failed for doc_id=%s", doc.id)

    return RebuildResponse(
        total=total, success=success, failed=failed, errors=errors,
    )


@router.delete("/document/{doc_id}")
def delete_document_graph(
    doc_id: int,
    db: Session = Depends(get_db),
    _user: dict = Depends(get_current_user),
):
    """Remove all KG edges for a document (entity nodes themselves are preserved).

    Useful after re-indexing when old entities may no longer apply.
    """
    doc = db.get(Document, doc_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="文档不存在")

    edge_count = (
        db.query(DocumentEntity)
        .filter(DocumentEntity.document_id == doc_id)
        .delete(synchronize_session=False)
    )
    rel_count = (
        db.query(DocumentRelation)
        .filter(
            (DocumentRelation.src_doc_id == doc_id)
            | (DocumentRelation.dst_doc_id == doc_id)
        )
        .delete(synchronize_session=False)
    )
    db.commit()
    return {
        "status": "ok",
        "deleted_entity_edges": edge_count,
        "deleted_document_relations": rel_count,
    }
