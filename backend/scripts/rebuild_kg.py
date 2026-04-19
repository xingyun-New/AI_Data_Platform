"""One-click knowledge-graph rebuild.

This script clears kg_entities / kg_document_entities / kg_document_relations
and then re-runs ``kg_service.save_graph`` for every indexed/uploaded document,
so the three 3-star improvements (IDF weighting, entity blacklist, union merge)
take effect on ALL historical data.

Execution is fully offline — no running backend or auth token is required.
It reuses the ``knowledge_graph`` block already cached inside each document's
index JSON on disk (so LLM calls are skipped for most documents, only embedding
calls for entity normalization remain).

Usage (run from the backend/ directory):

    # Preview
    python scripts/rebuild_kg.py --dry-run

    # Full wipe + rebuild (asks for confirmation)
    python scripts/rebuild_kg.py

    # Skip confirmation (for CI / scripting)
    python scripts/rebuild_kg.py --yes

    # Limit to a subset
    python scripts/rebuild_kg.py --limit 10
    python scripts/rebuild_kg.py --doc-ids 1,2,3

    # Keep existing rows (test the union-merge path, no wipe)
    python scripts/rebuild_kg.py --no-wipe
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
import time
from pathlib import Path
from typing import Any

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")
    except (AttributeError, OSError):
        pass

HERE = Path(__file__).resolve().parent
BACKEND_ROOT = HERE.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

site_packages = BACKEND_ROOT / "Lib" / "site-packages"
if site_packages.exists() and str(site_packages) not in sys.path:
    sys.path.insert(0, str(site_packages))

from sqlalchemy import text

from app.config import settings
from app.core.ai_service import call_ai_json
from app.core.file_manager import read_file, read_index, write_index
from app.core.index_generator import GRAPH_PROMPT_FILE
from app.database import SessionLocal
from app.models.document import Document
from app.models.knowledge_graph import DocumentEntity, DocumentRelation, Entity
from app.services import kg_service

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s | %(message)s",
)
logger = logging.getLogger("rebuild_kg")


def _print_stats(db, prefix: str) -> None:
    entity_count = db.query(Entity).count()
    doc_entity_count = db.query(DocumentEntity).count()
    doc_relation_count = db.query(DocumentRelation).count()
    type_rows = db.query(Entity.entity_type).all()
    by_type: dict[str, int] = {}
    for (etype,) in type_rows:
        by_type[etype] = by_type.get(etype, 0) + 1
    print(f"\n=== {prefix} ===")
    print(f"  kg_entities            : {entity_count}")
    print(f"  kg_document_entities   : {doc_entity_count}")
    print(f"  kg_document_relations  : {doc_relation_count}")
    if by_type:
        dist = ", ".join(f"{k}={v}" for k, v in sorted(by_type.items()))
        print(f"  entities_by_type       : {dist}")
    blacklist = settings.kg_entity_blacklist_set
    if blacklist:
        print(f"  blacklist (active)     : {sorted(blacklist)}")
    else:
        print("  blacklist (active)     : (empty — nothing will be filtered)")


def _wipe_graph_tables(db) -> None:
    """DELETE (not DROP) from all three KG tables. Keeps schema intact."""
    logger.info("Wiping kg_document_relations / kg_document_entities / kg_entities ...")
    db.execute(text("DELETE FROM kg_document_relations"))
    db.execute(text("DELETE FROM kg_document_entities"))
    db.execute(text("DELETE FROM kg_entities"))
    db.commit()


async def _load_or_extract_graph(
    doc: Document,
    *,
    allow_llm: bool,
) -> dict[str, Any] | None:
    """Return graph_data for *doc*, preferring the cached block in index JSON."""
    stem = Path(doc.filename).stem
    index_raw = read_index(stem)
    cached_graph: dict[str, Any] | None = None
    idx_obj: dict[str, Any] | None = None
    if index_raw:
        try:
            idx_obj = json.loads(index_raw)
            if isinstance(idx_obj, dict) and idx_obj.get("knowledge_graph"):
                cached_graph = idx_obj["knowledge_graph"]
        except json.JSONDecodeError:
            pass

    if cached_graph is not None:
        return cached_graph

    if not allow_llm:
        logger.warning(
            "No cached knowledge_graph in index JSON for doc_id=%s (%s). "
            "Re-run is disabled without --allow-llm.",
            doc.id, doc.filename,
        )
        return None

    if not doc.raw_path or not Path(doc.raw_path).exists():
        logger.error(
            "Raw file missing for doc_id=%s (%s), skipping.",
            doc.id, doc.raw_path,
        )
        return None

    try:
        content = read_file(Path(doc.raw_path))
        fresh = await call_ai_json(
            GRAPH_PROMPT_FILE, content,
            temperature=0.1, max_tokens=4096,
            chunk_strategy="graph_merge",
        )
    except Exception as exc:
        logger.error("LLM graph-extract failed for doc_id=%s: %s", doc.id, exc)
        return None

    # Persist back into index JSON for future rebuilds
    if idx_obj is not None:
        try:
            idx_obj["knowledge_graph"] = {
                "entities": fresh.get("entities") or [],
                "document_relations": fresh.get("document_relations") or [],
            }
            write_index(stem, json.dumps(idx_obj, ensure_ascii=False, indent=2))
        except Exception as exc:
            logger.warning("Failed to persist graph back to index json: %s", exc)

    return fresh


async def _rebuild_one(db, doc: Document, *, allow_llm: bool) -> tuple[bool, str]:
    graph_data = await _load_or_extract_graph(doc, allow_llm=allow_llm)
    if graph_data is None:
        return False, "no graph data"
    result = await kg_service.save_graph(db, doc.id, graph_data)
    return True, (
        f"entities={result.get('entity_count', 0)} "
        f"edges={result.get('relation_count', 0)}"
    )


async def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true",
                        help="Only show what would happen; do not modify the DB.")
    parser.add_argument("--yes", action="store_true",
                        help="Skip the confirmation prompt.")
    parser.add_argument("--no-wipe", action="store_true",
                        help="Skip wiping the KG tables (exercise the new union-merge path only).")
    parser.add_argument("--limit", type=int, default=None,
                        help="Process at most N documents.")
    parser.add_argument("--doc-ids", type=str, default=None,
                        help="Comma-separated document ids to process (default: all indexed/uploaded).")
    parser.add_argument("--allow-llm", action="store_true",
                        help="Allow fresh LLM calls for documents that lack a cached knowledge_graph in their index JSON.")
    args = parser.parse_args(argv)

    doc_id_filter: set[int] | None = None
    if args.doc_ids:
        doc_id_filter = {int(x) for x in args.doc_ids.split(",") if x.strip()}

    db = SessionLocal()
    try:
        _print_stats(db, "BEFORE")

        query = db.query(Document).filter(Document.status.in_(["indexed", "uploaded"]))
        if doc_id_filter:
            query = query.filter(Document.id.in_(doc_id_filter))
        all_docs = query.order_by(Document.id.asc()).all()
        if args.limit and args.limit > 0:
            all_docs = all_docs[: args.limit]

        print(f"\nTarget documents : {len(all_docs)}")
        if args.dry_run:
            print("Mode             : DRY-RUN (no changes will be written)")
        else:
            action = "UNION-MERGE only (no wipe)" if args.no_wipe else "WIPE + rebuild"
            print(f"Mode             : {action}")
        print(f"LLM fallback     : {'enabled' if args.allow_llm else 'disabled (cached JSON only)'}")

        if args.dry_run:
            for d in all_docs[:20]:
                stem = Path(d.filename).stem
                idx = read_index(stem)
                has_cached = bool(
                    idx and '"knowledge_graph"' in idx
                )
                print(f"  - doc_id={d.id:<4} {d.filename}  cached_graph={has_cached}")
            if len(all_docs) > 20:
                print(f"  ... and {len(all_docs) - 20} more")
            return 0

        if not args.yes:
            prompt = "\n continue? [yes/N] "
            try:
                ans = input(prompt).strip().lower()
            except EOFError:
                ans = ""
            if ans != "yes" and ans != "y":
                print("Aborted.")
                return 1

        if not args.no_wipe:
            _wipe_graph_tables(db)
            _print_stats(db, "AFTER WIPE")

        ok = 0
        failed = 0
        errors: list[dict[str, Any]] = []
        t0 = time.time()

        for i, doc in enumerate(all_docs, 1):
            try:
                success, detail = await _rebuild_one(db, doc, allow_llm=args.allow_llm)
                if success:
                    ok += 1
                    print(f"  [{i:>3}/{len(all_docs)}] OK   doc_id={doc.id:<4} {doc.filename}  {detail}")
                else:
                    failed += 1
                    errors.append({"doc_id": doc.id, "filename": doc.filename, "error": detail})
                    print(f"  [{i:>3}/{len(all_docs)}] SKIP doc_id={doc.id:<4} {doc.filename}  {detail}")
            except Exception as exc:
                failed += 1
                errors.append({"doc_id": doc.id, "filename": doc.filename, "error": str(exc)})
                logger.exception("Rebuild failed for doc_id=%s", doc.id)
                print(f"  [{i:>3}/{len(all_docs)}] FAIL doc_id={doc.id:<4} {doc.filename}  {exc}")

        elapsed = time.time() - t0
        print(f"\nFinished: ok={ok} failed={failed} elapsed={elapsed:.1f}s")
        if errors:
            print("Failures:")
            for e in errors:
                print(f"  - doc_id={e['doc_id']} {e['filename']}: {e['error']}")

        _print_stats(db, "AFTER REBUILD")
        return 0 if failed == 0 else 2
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
