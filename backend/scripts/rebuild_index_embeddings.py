"""Backfill topic-level index embeddings onto existing documents.

After adding the ``documents.index_embedding`` column, this script walks every
indexed/uploaded document, reads the on-disk index JSON, reconstructs the
rerank text with ``index_generator.build_index_rerank_text`` and embeds it via
DashScope. Embeddings are persisted onto the Document row so the KG retrieval
pipeline can do topic-level rerank without re-embedding.

Usage (run from the backend/ directory):

    # Preview — no LLM / DB writes
    python scripts/rebuild_index_embeddings.py --dry-run

    # Only backfill docs that are still missing an embedding (default; safe)
    python scripts/rebuild_index_embeddings.py --yes

    # Re-compute every doc, even those already embedded
    python scripts/rebuild_index_embeddings.py --yes --all

    # Limit / filter
    python scripts/rebuild_index_embeddings.py --yes --limit 10
    python scripts/rebuild_index_embeddings.py --yes --doc-ids 1,2,3
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

from app.core.embedding_service import embed_texts, pack_vector
from app.core.file_manager import read_index
from app.core.index_generator import build_index_rerank_text
from app.database import SessionLocal
from app.models.document import Document

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s | %(message)s",
)
logger = logging.getLogger("rebuild_index_embeddings")


def _load_rerank_text(doc: Document) -> tuple[str, dict[str, Any] | None]:
    """Return (rerank_text, full_index_dict) for a document.

    Prefers the ``versions.full`` block (authoritative source of purpose /
    summary / keywords / scenarios) and falls back to the top-level fields
    for legacy index files that pre-date the versioned format.
    """
    stem = Path(doc.filename).stem
    raw = read_index(stem)
    if not raw:
        return "", None
    try:
        idx = json.loads(raw)
    except json.JSONDecodeError:
        return "", None
    if not isinstance(idx, dict):
        return "", None

    versions = idx.get("versions") or {}
    full_block = versions.get("full") if isinstance(versions, dict) else None
    source = full_block if isinstance(full_block, dict) else idx
    return build_index_rerank_text(source), idx


def _print_stats(db, prefix: str) -> None:
    total = db.query(Document).filter(Document.status.in_(["indexed", "uploaded"])).count()
    with_embed = (
        db.query(Document)
        .filter(Document.status.in_(["indexed", "uploaded"]))
        .filter(Document.index_embedding_dim > 0)
        .count()
    )
    print(f"\n=== {prefix} ===")
    print(f"  indexed/uploaded docs         : {total}")
    print(f"  with index_embedding          : {with_embed}")
    print(f"  missing index_embedding       : {total - with_embed}")


async def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true",
                        help="Only show which documents would be processed; no DB writes, no LLM calls.")
    parser.add_argument("--yes", action="store_true",
                        help="Skip the confirmation prompt.")
    parser.add_argument("--all", dest="rebuild_all", action="store_true",
                        help="Re-embed every document (default: only docs without an embedding yet).")
    parser.add_argument("--limit", type=int, default=None,
                        help="Process at most N documents.")
    parser.add_argument("--doc-ids", type=str, default=None,
                        help="Comma-separated document ids to process (default: all indexed/uploaded).")
    parser.add_argument("--batch-size", type=int, default=10,
                        help="Max texts per embedding API call.")
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
        if not args.rebuild_all:
            query = query.filter(
                (Document.index_embedding_dim == 0)
                | (Document.index_embedding.is_(None))
            )
        all_docs = query.order_by(Document.id.asc()).all()
        if args.limit and args.limit > 0:
            all_docs = all_docs[: args.limit]

        print(f"\nTarget documents : {len(all_docs)}")
        print(f"Mode             : {'ALL (re-embed)' if args.rebuild_all else 'only-missing'}")
        if args.dry_run:
            print("Dry-run          : yes (nothing will be written)")

        if not all_docs:
            print("Nothing to do.")
            return 0

        if args.dry_run:
            for d in all_docs[:20]:
                text_, _ = _load_rerank_text(d)
                preview = (text_[:80] + "…") if len(text_) > 80 else text_
                print(
                    f"  - doc_id={d.id:<4} {d.filename}  "
                    f"text_len={len(text_):>4}  preview={preview!r}"
                )
            if len(all_docs) > 20:
                print(f"  ... and {len(all_docs) - 20} more")
            return 0

        if not args.yes:
            try:
                ans = input("\n continue? [yes/N] ").strip().lower()
            except EOFError:
                ans = ""
            if ans not in {"y", "yes"}:
                print("Aborted.")
                return 1

        ok = 0
        skipped = 0
        failed = 0
        errors: list[dict[str, Any]] = []
        t0 = time.time()

        # Batch the embedding calls to minimize DashScope round-trips; we still
        # do a DB commit per document so a failure partway through keeps all
        # prior progress persisted.
        batch_size = max(1, args.batch_size)
        for start in range(0, len(all_docs), batch_size):
            chunk = all_docs[start:start + batch_size]

            pending_docs: list[Document] = []
            pending_texts: list[str] = []
            for doc in chunk:
                text_, _ = _load_rerank_text(doc)
                if not text_:
                    skipped += 1
                    errors.append({
                        "doc_id": doc.id, "filename": doc.filename,
                        "error": "no purpose/summary/keywords in index JSON",
                    })
                    print(f"  SKIP doc_id={doc.id:<4} {doc.filename}  (empty rerank text)")
                    continue
                pending_docs.append(doc)
                pending_texts.append(text_)

            if not pending_docs:
                continue

            try:
                vecs = await embed_texts(pending_texts)
            except Exception as exc:
                failed += len(pending_docs)
                for doc in pending_docs:
                    errors.append({
                        "doc_id": doc.id, "filename": doc.filename, "error": f"embed batch failed: {exc}",
                    })
                    print(f"  FAIL doc_id={doc.id:<4} {doc.filename}  embed batch failed")
                continue

            for doc, vec in zip(pending_docs, vecs):
                try:
                    doc.index_embedding = pack_vector(vec)
                    doc.index_embedding_dim = len(vec)
                    db.commit()
                    ok += 1
                    print(f"  OK   doc_id={doc.id:<4} {doc.filename}  dim={len(vec)}")
                except Exception as exc:
                    db.rollback()
                    failed += 1
                    errors.append({"doc_id": doc.id, "filename": doc.filename, "error": str(exc)})
                    print(f"  FAIL doc_id={doc.id:<4} {doc.filename}  {exc}")

        elapsed = time.time() - t0
        print(f"\nFinished: ok={ok} skipped={skipped} failed={failed} elapsed={elapsed:.1f}s")
        if errors:
            print("Details:")
            for e in errors[:30]:
                print(f"  - doc_id={e['doc_id']} {e['filename']}: {e['error']}")
            if len(errors) > 30:
                print(f"  ... and {len(errors) - 30} more")

        _print_stats(db, "AFTER")
        return 0 if failed == 0 else 2
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
