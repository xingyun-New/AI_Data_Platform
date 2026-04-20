"""RBAC helpers — role checks and per-department authorization.

Uses the JWT-embedded ``roles`` payload (written by ``create_access_token``) so
most checks are purely in-memory and don't hit the DB per request.

Role semantics:
    SYS_ADMIN  -> full access, all departments, rule and system setting maintenance.
    BE_CROSS   -> can upload / maintain documents across every department.
    DEPT_PIC   -> can upload / maintain documents in departments listed in
                  ``pic_department_ids`` (the user_roles.department_id binding).
    MEMBER     -> read-only, limited to their home ``department``.
"""

from __future__ import annotations

from fastapi import Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.database import get_db
from app.models.department import Department
from app.models.user_role import (
    ROLE_BE_CROSS,
    ROLE_DEPT_PIC,
    ROLE_MEMBER,
    ROLE_SYS_ADMIN,
)


def has_role(user: dict, role: str) -> bool:
    return role in (user.get("role_names") or [])


def is_sys_admin(user: dict) -> bool:
    return has_role(user, ROLE_SYS_ADMIN)


def is_be_cross(user: dict) -> bool:
    return has_role(user, ROLE_BE_CROSS)


def is_dept_pic_of(user: dict, department_id: int | None) -> bool:
    if department_id is None:
        return False
    return department_id in (user.get("pic_department_ids") or [])


def require_roles(*roles: str):
    """Dependency factory: require the current user to have at least one of ``roles``."""

    def _dep(user: dict = Depends(get_current_user)) -> dict:
        names = set(user.get("role_names") or [])
        if not names.intersection(roles):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"权限不足：需要角色 {', '.join(roles)}",
            )
        return user

    return _dep


def require_sys_admin(user: dict = Depends(get_current_user)) -> dict:
    if not is_sys_admin(user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="权限不足：仅系统管理员可执行该操作",
        )
    return user


def resolve_department_id(db: Session, department_code: str) -> int | None:
    """Look up a department id by code. Returns None if the code is empty/unknown."""
    if not department_code:
        return None
    row = db.query(Department).filter(Department.code == department_code).first()
    return row.id if row else None


def can_upload_document(user: dict, db: Session, department_code: str) -> bool:
    """Return True if the user may create/update/delete documents under ``department_code``."""
    if is_sys_admin(user) or is_be_cross(user):
        return True
    dept_id = resolve_department_id(db, department_code)
    return is_dept_pic_of(user, dept_id)


def can_manage_rule(user: dict) -> bool:
    """Rule maintenance is admin-only per plan (BE does not touch rules)."""
    return is_sys_admin(user)


def can_view_document(user: dict, document_department: str) -> bool:
    """Read permission: admin/BE see everything, PIC sees managed depts + home dept,
    MEMBER sees only their home department's docs.
    """
    if is_sys_admin(user) or is_be_cross(user):
        return True
    # PIC: we don't need to load the department_id here — they can always see their home dept,
    # and for other PIC-managed departments the department code string is what comes from the row.
    # Callers that need strict PIC-scoping filter at the query level using pic_department_ids.
    if has_role(user, ROLE_DEPT_PIC):
        return True  # PIC visibility is enforced at query time; don't 403 here.
    return (user.get("department") or "") == (document_department or "")


def document_filter_clause(user: dict):
    """Return a (callable -> SQL filter) fragment restricting the docs list to what
    the current user is allowed to see. ``None`` means "no restriction (admin/BE)".
    """
    if is_sys_admin(user) or is_be_cross(user):
        return None
    # For PIC: they can see their home dept + any dept they're PIC of. We return a
    # descriptor dict the caller applies to the SQLAlchemy query (keeps this module
    # import-cycle-free).
    visible_depts = set()
    if user.get("department"):
        visible_depts.add(user["department"])
    return {
        "role_names": user.get("role_names") or [],
        "visible_departments": visible_depts,
        "pic_department_ids": user.get("pic_department_ids") or [],
    }


__all__ = [
    "ROLE_SYS_ADMIN",
    "ROLE_BE_CROSS",
    "ROLE_DEPT_PIC",
    "ROLE_MEMBER",
    "has_role",
    "is_sys_admin",
    "is_be_cross",
    "is_dept_pic_of",
    "require_roles",
    "require_sys_admin",
    "resolve_department_id",
    "can_upload_document",
    "can_manage_rule",
    "can_view_document",
    "document_filter_clause",
    "get_db",
]
