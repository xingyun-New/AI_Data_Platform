"""Batch execution endpoints — trigger / status / history / logs."""

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.deps_rbac import require_roles
from app.database import get_db
from app.models.batch_log import BatchFileLog, BatchLog
from app.models.user_role import ROLE_BE_CROSS, ROLE_SYS_ADMIN
from app.services import batch_service

router = APIRouter()

# Batch execution & monitoring are restricted to system administrators and
# the BE cross-department uploader role. Dept PICs and regular members have no
# access (they shouldn't be able to kick off pipelines for other departments
# nor see the full audit log).
_batch_guard = require_roles(ROLE_SYS_ADMIN, ROLE_BE_CROSS)


class BatchSummary(BaseModel):
    id: int
    batch_id: str
    status: str
    total_files: int
    success_count: int
    fail_count: int
    started_at: str
    finished_at: str

    class Config:
        from_attributes = True


@router.post("/run")
async def run_batch(
    department: str = Query(""),
    knowledge_base_id: str = Query(""),
    db: Session = Depends(get_db),
    _user: dict = Depends(_batch_guard),
):
    result = await batch_service.run_batch(
        db,
        department=department or None,
        knowledge_base_id=knowledge_base_id or None,
    )
    return result


@router.get("/status")
def batch_status(_user: dict = Depends(_batch_guard)):
    return {
        "is_running": batch_service.is_running(),
        "current_batch_id": batch_service.get_current_batch_id(),
    }


@router.get("/history")
def batch_history(
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    _user: dict = Depends(_batch_guard),
):
    total = db.query(BatchLog).count()
    rows = (
        db.query(BatchLog)
        .order_by(BatchLog.started_at.desc())
        .offset((page - 1) * size)
        .limit(size)
        .all()
    )
    return {
        "total": total,
        "page": page,
        "size": size,
        "items": [
            BatchSummary(
                id=r.id,
                batch_id=r.batch_id,
                status=r.status,
                total_files=r.total_files,
                success_count=r.success_count,
                fail_count=r.fail_count,
                started_at=str(r.started_at or ""),
                finished_at=str(r.finished_at or ""),
            )
            for r in rows
        ]
    }


@router.get("/logs/{batch_id}")
def batch_logs(batch_id: str, db: Session = Depends(get_db), _user: dict = Depends(_batch_guard)):
    rows = (
        db.query(BatchFileLog)
        .filter(BatchFileLog.batch_id == batch_id)
        .order_by(BatchFileLog.created_at)
        .all()
    )
    return [
        {
            "id": r.id,
            "document_id": r.document_id,
            "step": r.step,
            "status": r.status,
            "error_message": r.error_message,
            "duration_ms": r.duration_ms,
            "created_at": str(r.created_at or ""),
        }
        for r in rows
    ]
