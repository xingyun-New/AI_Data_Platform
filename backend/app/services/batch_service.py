"""Batch pipeline — scan -> desensitize -> index -> upload-to-Dify for all raw MD files.

Supports concurrent processing of multiple files via asyncio.gather
with a configurable semaphore (settings.batch_concurrency).
Files already indexed (but not yet uploaded) will skip AI steps and go
straight to Dify upload.
"""

import asyncio
import json
import logging
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy.orm import Session

from app.config import settings
from app.core import file_manager
from app.core.desensitizer import desensitize_file
from app.core.dify_uploader import upload_with_metadata
from app.core.index_generator import generate_index
from app.models.batch_log import BatchFileLog, BatchLog
from app.models.document import Document

logger = logging.getLogger(__name__)

_running_batch_id: str | None = None


def is_running() -> bool:
    return _running_batch_id is not None


def get_current_batch_id() -> str | None:
    """Return the current running batch ID (public accessor)."""
    return _running_batch_id


@dataclass
class _FileResult:
    """Collects per-file processing outcome for deferred DB writes."""
    raw_path: Path
    doc_id: int
    upload_only: bool = False
    ok: bool = False
    failed_step: str = ""
    error: str = ""
    redacted_path: str = ""
    index_path: str = ""
    desensitize_ms: float = 0
    index_ms: float = 0
    upload_ms: float = 0
    dify_uploaded: bool = False


# ---- Dify upload helper (shared by full and upload-only pipelines) --------

async def _do_dify_upload(
    result: _FileResult,
    raw_path: Path,
    index_doc: dict,
    kb_id: str | None = None,
    db: Session | None = None,
) -> None:
    """Upload full + redacted versions to Dify in parallel.

    Mutates *result* in place (upload_ms, dify_uploaded, failed_step, error).
    Resolves dataset_id and API credentials from the specified knowledge base
    or falls back to the default KB / settings.
    """
    from app.services.settings_service import get_dify_config

    kb_config = get_dify_config(db, kb_id) if db else None
    dataset_id = kb_config["dataset_id"] if kb_config else (settings.dify_dataset_id or "")
    api_key = kb_config.get("api_key") if kb_config else None
    base_url = kb_config.get("base_url") if kb_config else None

    if not dataset_id:
        return

    t = time.perf_counter()
    try:
        dify_meta = index_doc.get("dify_metadata", {})
        upload_coros: list = []

        if "full" in dify_meta:
            upload_coros.append(
                upload_with_metadata(
                    file_path=str(raw_path),
                    index_meta=dify_meta["full"],
                    dataset_id=dataset_id,
                    upload_name=raw_path.name,
                    api_key=api_key,
                    base_url=base_url,
                )
            )

        has_redacted = (
            result.redacted_path
            and Path(result.redacted_path).exists()
            and "redacted" in dify_meta
        )
        if has_redacted:
            redacted_name = f"{raw_path.stem}_redacted{raw_path.suffix}"
            upload_coros.append(
                upload_with_metadata(
                    file_path=result.redacted_path,
                    index_meta=dify_meta["redacted"],
                    dataset_id=dataset_id,
                    upload_name=redacted_name,
                    api_key=api_key,
                    base_url=base_url,
                )
            )

        if upload_coros:
            await asyncio.gather(*upload_coros)

        result.upload_ms = (time.perf_counter() - t) * 1000
        result.dify_uploaded = True
    except Exception as exc:
        logger.exception("Dify upload failed: %s", raw_path.name)
        result.failed_step = "upload"
        result.error = str(exc)
        result.upload_ms = (time.perf_counter() - t) * 1000


# ---- Per-file pipelines ---------------------------------------------------

async def _process_one_file(
    sem: asyncio.Semaphore,
    raw_path: Path,
    department: str,
    section: str,
    doc_id: int,
    db: Session,
) -> _FileResult:
    """Full pipeline: desensitize -> index -> upload (AI-heavy, IO-bound)."""
    result = _FileResult(raw_path=raw_path, doc_id=doc_id)

    async with sem:
        # Step 1: desensitize
        t0 = time.perf_counter()
        try:
            de_out = await desensitize_file(
                str(raw_path), department, db, section=section,
            )
            result.redacted_path = de_out["redacted_path"]
            result.desensitize_ms = (time.perf_counter() - t0) * 1000
        except Exception as exc:
            logger.exception("Desensitize failed: %s", raw_path.name)
            result.failed_step = "desensitize"
            result.error = str(exc)
            result.desensitize_ms = (time.perf_counter() - t0) * 1000
            return result

        # Step 2: generate index (with db + section for rule support)
        t1 = time.perf_counter()
        try:
            index_doc = await generate_index(
                str(raw_path), department, db, section=section,
            )
            result.index_path = str(
                file_manager._index_dir() / f"{raw_path.stem}.json"
            )
            result.index_ms = (time.perf_counter() - t1) * 1000
        except Exception as exc:
            logger.exception("Index generation failed: %s", raw_path.name)
            result.failed_step = "index"
            result.error = str(exc)
            result.index_ms = (time.perf_counter() - t1) * 1000
            return result

        # Step 2b: persist knowledge-graph entities/relations (best-effort, non-fatal)
        graph_block = index_doc.get("knowledge_graph")
        if graph_block and doc_id:
            try:
                from app.services.kg_service import save_graph
                await save_graph(db, doc_id, graph_block)
            except Exception as exc:
                logger.warning(
                    "KG persistence failed for %s (continuing): %s", raw_path.name, exc,
                )

        # Step 3: upload to Dify
        kb_id = None
        if db and result.doc_id:
            from app.models.document import Document
            doc = db.get(Document, result.doc_id)
            kb_id = doc.knowledge_base_id if doc else None
        await _do_dify_upload(result, raw_path, index_doc, kb_id=kb_id, db=db)
        if result.failed_step:
            return result

    result.ok = True
    return result


async def _upload_one_file(
    sem: asyncio.Semaphore,
    raw_path: Path,
    doc_id: int,
    redacted_path: str,
    index_path: str,
) -> _FileResult:
    """Upload-only pipeline for files already indexed but not yet uploaded."""
    result = _FileResult(
        raw_path=raw_path, doc_id=doc_id, upload_only=True,
        redacted_path=redacted_path, index_path=index_path,
    )

    async with sem:
        index_raw = file_manager.read_index(raw_path.stem)
        if not index_raw:
            result.failed_step = "upload"
            result.error = "Index file not found on disk"
            return result

        index_doc = json.loads(index_raw)
        # Get KB ID from the document associated with this result
        from app.database import SessionLocal
        from app.models.document import Document
        temp_db = SessionLocal()
        try:
            doc = temp_db.get(Document, result.doc_id)
            kb_id = doc.knowledge_base_id if doc else None
        finally:
            temp_db.close()
        await _do_dify_upload(result, raw_path, index_doc, kb_id=kb_id, db=None)
        if result.failed_step:
            return result

    result.ok = True
    return result


# ---- Batch orchestrator ---------------------------------------------------

async def run_batch(
    db: Session,
    *,
    department: str | None = None,
    knowledge_base_id: str | None = None,
) -> dict:
    """Execute a full batch: scan raw/ -> desensitize -> index -> upload.

    Files are processed concurrently (up to settings.batch_concurrency).
    Already-indexed files skip AI steps and go straight to Dify upload.
    DB writes are performed sequentially after all parallel work completes.

    When *department* or *knowledge_base_id* are supplied they are applied
    to every document that does not yet have these fields set.
    """
    global _running_batch_id

    if _running_batch_id is not None:
        return {"status": "already_running", "batch_id": _running_batch_id}

    batch_id = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_") + uuid.uuid4().hex[:6]
    _running_batch_id = batch_id

    blog = BatchLog(batch_id=batch_id, status="running")
    db.add(blog)
    db.commit()

    raw_files = file_manager.list_raw_files()
    blog.total_files = len(raw_files)
    db.commit()

    success = 0
    fail = 0

    # --- Phase 1: sequential pre-check (categorize files) ---
    full_tasks: list[tuple[Path, Document]] = []
    upload_only_tasks: list[tuple[Path, Document]] = []

    for raw_path in raw_files:
        _ensure_doc_row(db, raw_path, department=department, knowledge_base_id=knowledge_base_id)
        doc = db.query(Document).filter(Document.filename == raw_path.name).first()
        if doc is None:
            continue

        current_hash = file_manager.file_hash(raw_path)

        if doc.status == "uploaded" and doc.file_hash == current_hash:
            success += 1
            continue

        # Check if any KB is configured for upload-only path
        from app.services.settings_service import get_knowledge_bases
        kb_data = get_knowledge_bases(db)
        has_any_kb = bool(kb_data.get("knowledge_bases"))

        if (
            doc.status == "indexed"
            and doc.file_hash == current_hash
            and has_any_kb
        ):
            upload_only_tasks.append((raw_path, doc))
            continue

        doc.file_hash = current_hash
        db.commit()
        full_tasks.append((raw_path, doc))

    # --- Phase 2: parallel processing ---
    all_coros: list = []
    sem = asyncio.Semaphore(settings.batch_concurrency)

    for raw_path, doc in full_tasks:
        all_coros.append(
            _process_one_file(
                sem, raw_path,
                doc.department or "General",
                getattr(doc, "section", "") or "",
                doc.id, db,
            )
        )
    for raw_path, doc in upload_only_tasks:
        all_coros.append(
            _upload_one_file(
                sem, raw_path, doc.id,
                doc.redacted_path or "",
                doc.index_path or "",
            )
        )

    if all_coros:
        results = await asyncio.gather(*all_coros, return_exceptions=True)

        # --- Phase 3: sequential DB writes with batch commits ---
        batch_size = 10
        pending_changes = 0
        
        for raw_result in results:
            if isinstance(raw_result, BaseException):
                logger.exception("Unexpected error in batch task: %s", raw_result)
                fail += 1
                continue

            r: _FileResult = raw_result
            doc = db.get(Document, r.doc_id)
            if doc is None:
                fail += 1
                continue

            if r.ok:
                if not r.upload_only:
                    doc.redacted_path = r.redacted_path
                    doc.index_path = r.index_path
                doc.status = "uploaded" if r.dify_uploaded else "indexed"
                doc.error_message = ""

                if not r.upload_only:
                    db.add(BatchFileLog(
                        batch_id=batch_id, document_id=r.doc_id,
                        step="desensitize", status="success",
                        duration_ms=r.desensitize_ms,
                    ))
                    db.add(BatchFileLog(
                        batch_id=batch_id, document_id=r.doc_id,
                        step="index", status="success",
                        duration_ms=r.index_ms,
                    ))
                if r.dify_uploaded:
                    db.add(BatchFileLog(
                        batch_id=batch_id, document_id=r.doc_id,
                        step="upload", status="success",
                        duration_ms=r.upload_ms,
                    ))
                pending_changes += 1
                if pending_changes >= batch_size:
                    db.commit()
                    pending_changes = 0
                success += 1

            else:
                _write_failure_logs(
                    db, batch_id, r, doc,
                )
                pending_changes += 1
                if pending_changes >= batch_size:
                    db.commit()
                    pending_changes = 0
                fail += 1
        
        if pending_changes > 0:
            db.commit()

    blog.success_count = success
    blog.fail_count = fail
    blog.status = "completed" if fail == 0 else "failed"
    blog.finished_at = datetime.now(timezone.utc)
    db.commit()

    _running_batch_id = None
    return {
        "status": blog.status,
        "batch_id": batch_id,
        "total": blog.total_files,
        "success": success,
        "fail": fail,
    }


def _write_failure_logs(
    db: Session,
    batch_id: str,
    r: _FileResult,
    doc: Document,
) -> None:
    """Write DB status + BatchFileLogs for a failed file result."""
    if r.failed_step == "desensitize":
        doc.status = "error"
        doc.error_message = r.error
        db.add(BatchFileLog(
            batch_id=batch_id, document_id=r.doc_id,
            step="desensitize", status="failed",
            error_message=r.error, duration_ms=r.desensitize_ms,
        ))

    elif r.failed_step == "index":
        doc.redacted_path = r.redacted_path
        doc.status = "desensitized"
        doc.error_message = r.error
        db.add(BatchFileLog(
            batch_id=batch_id, document_id=r.doc_id,
            step="desensitize", status="success",
            duration_ms=r.desensitize_ms,
        ))
        db.add(BatchFileLog(
            batch_id=batch_id, document_id=r.doc_id,
            step="index", status="failed",
            error_message=r.error, duration_ms=r.index_ms,
        ))

    elif r.failed_step == "upload":
        if not r.upload_only:
            doc.redacted_path = r.redacted_path
            doc.index_path = r.index_path
        doc.status = "indexed"
        doc.error_message = r.error
        if not r.upload_only:
            db.add(BatchFileLog(
                batch_id=batch_id, document_id=r.doc_id,
                step="desensitize", status="success",
                duration_ms=r.desensitize_ms,
            ))
            db.add(BatchFileLog(
                batch_id=batch_id, document_id=r.doc_id,
                step="index", status="success",
                duration_ms=r.index_ms,
            ))
        db.add(BatchFileLog(
            batch_id=batch_id, document_id=r.doc_id,
            step="upload", status="failed",
            error_message=r.error, duration_ms=r.upload_ms,
        ))


def _ensure_doc_row(
    db: Session,
    raw_path: Path,
    *,
    department: str | None = None,
    knowledge_base_id: str | None = None,
) -> None:
    existing = db.query(Document).filter(Document.filename == raw_path.name).first()
    if existing is None:
        doc = Document(
            filename=raw_path.name,
            directory=str(raw_path.parent),
            file_hash=file_manager.file_hash(raw_path),
            raw_path=str(raw_path),
            status="raw",
            department=department or "",
            knowledge_base_id=knowledge_base_id or "",
        )
        db.add(doc)
        db.commit()
    else:
        changed = False
        if department and not existing.department:
            existing.department = department
            changed = True
        if knowledge_base_id and not existing.knowledge_base_id:
            existing.knowledge_base_id = knowledge_base_id
            changed = True
        if changed:
            db.commit()
