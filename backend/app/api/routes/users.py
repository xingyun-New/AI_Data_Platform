"""User / role / department administration — SYS_ADMIN only."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.api.deps_rbac import require_sys_admin
from app.database import get_db
from app.models.department import Department
from app.models.user import User
from app.models.user_role import ALL_ROLES, ROLE_DEPT_PIC, UserRole

router = APIRouter()


# ---------- Schemas ---------------------------------------------------------


class RoleBindingOut(BaseModel):
    id: int
    role: str
    department_id: int | None = None
    department_code: str | None = None
    granted_by: str = ""
    granted_at: str = ""


class UserOut(BaseModel):
    id: int
    username: str
    display_name: str
    department: str
    section: str
    is_active: bool
    last_login_at: str | None = None
    created_at: str | None = None
    roles: list[RoleBindingOut] = []


class UserUpdate(BaseModel):
    display_name: str | None = None
    is_active: bool | None = None


class RoleGrantBody(BaseModel):
    role: str
    department_id: int | None = None


class DepartmentOut(BaseModel):
    id: int
    code: str
    name: str
    is_active: bool


class DepartmentCreate(BaseModel):
    code: str
    name: str = ""
    is_active: bool = True


class DepartmentUpdate(BaseModel):
    name: str | None = None
    is_active: bool | None = None


# ---------- Helpers ---------------------------------------------------------


def _load_user_roles(db: Session, user_id: int) -> list[RoleBindingOut]:
    rows = (
        db.query(UserRole, Department)
        .outerjoin(Department, Department.id == UserRole.department_id)
        .filter(UserRole.user_id == user_id)
        .all()
    )
    return [
        RoleBindingOut(
            id=r.id,
            role=r.role,
            department_id=r.department_id,
            department_code=d.code if d else None,
            granted_by=r.granted_by or "",
            granted_at=str(r.granted_at or ""),
        )
        for r, d in rows
    ]


def _user_to_out(db: Session, u: User) -> UserOut:
    return UserOut(
        id=u.id,
        username=u.username,
        display_name=u.display_name or "",
        department=u.department or "",
        section=u.section or "",
        is_active=bool(u.is_active) if u.is_active is not None else True,
        last_login_at=str(u.last_login_at) if u.last_login_at else None,
        created_at=str(u.created_at) if u.created_at else None,
        roles=_load_user_roles(db, u.id),
    )


# ---------- User endpoints --------------------------------------------------


@router.get("/users", response_model=list[UserOut])
def list_users(
    keyword: str | None = Query(None),
    department: str | None = Query(None),
    role: str | None = Query(None),
    db: Session = Depends(get_db),
    _admin: dict = Depends(require_sys_admin),
):
    q = db.query(User)
    if keyword:
        like = f"%{keyword}%"
        q = q.filter((User.username.ilike(like)) | (User.display_name.ilike(like)))
    if department:
        q = q.filter(User.department == department)
    users = q.order_by(User.id.asc()).all()

    if role:
        user_ids_with_role = {
            row[0]
            for row in db.query(UserRole.user_id).filter(UserRole.role == role).all()
        }
        users = [u for u in users if u.id in user_ids_with_role]

    return [_user_to_out(db, u) for u in users]


@router.get("/users/{user_id}", response_model=UserOut)
def get_user(
    user_id: int,
    db: Session = Depends(get_db),
    _admin: dict = Depends(require_sys_admin),
):
    u = db.get(User, user_id)
    if not u:
        raise HTTPException(status_code=404, detail="用户不存在")
    return _user_to_out(db, u)


@router.patch("/users/{user_id}", response_model=UserOut)
def update_user(
    user_id: int,
    body: UserUpdate,
    db: Session = Depends(get_db),
    _admin: dict = Depends(require_sys_admin),
):
    u = db.get(User, user_id)
    if not u:
        raise HTTPException(status_code=404, detail="用户不存在")
    data = body.model_dump(exclude_unset=True)
    for field, value in data.items():
        setattr(u, field, value)
    db.commit()
    db.refresh(u)
    return _user_to_out(db, u)


# ---------- Role endpoints --------------------------------------------------


@router.get("/users/{user_id}/roles", response_model=list[RoleBindingOut])
def list_user_roles(
    user_id: int,
    db: Session = Depends(get_db),
    _admin: dict = Depends(require_sys_admin),
):
    if not db.get(User, user_id):
        raise HTTPException(status_code=404, detail="用户不存在")
    return _load_user_roles(db, user_id)


@router.post("/users/{user_id}/roles", response_model=RoleBindingOut)
def grant_user_role(
    user_id: int,
    body: RoleGrantBody,
    db: Session = Depends(get_db),
    admin: dict = Depends(require_sys_admin),
):
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")
    if body.role not in ALL_ROLES:
        raise HTTPException(status_code=400, detail=f"未知角色：{body.role}")

    department_id = body.department_id
    if body.role == ROLE_DEPT_PIC:
        if department_id is None:
            raise HTTPException(status_code=400, detail="DEPT_PIC 必须指定部门")
        if not db.get(Department, department_id):
            raise HTTPException(status_code=400, detail="部门不存在")
    else:
        department_id = None

    existing = (
        db.query(UserRole)
        .filter(
            UserRole.user_id == user_id,
            UserRole.role == body.role,
            UserRole.department_id.is_(department_id) if department_id is None else UserRole.department_id == department_id,
        )
        .first()
    )
    if existing:
        binding = existing
    else:
        binding = UserRole(
            user_id=user_id,
            role=body.role,
            department_id=department_id,
            granted_by=admin.get("username") or "admin",
        )
        db.add(binding)
        db.commit()
        db.refresh(binding)

    dept = db.get(Department, binding.department_id) if binding.department_id else None
    return RoleBindingOut(
        id=binding.id,
        role=binding.role,
        department_id=binding.department_id,
        department_code=dept.code if dept else None,
        granted_by=binding.granted_by or "",
        granted_at=str(binding.granted_at or ""),
    )


@router.delete("/users/{user_id}/roles/{binding_id}")
def revoke_user_role(
    user_id: int,
    binding_id: int,
    db: Session = Depends(get_db),
    _admin: dict = Depends(require_sys_admin),
):
    binding = db.get(UserRole, binding_id)
    if not binding or binding.user_id != user_id:
        raise HTTPException(status_code=404, detail="角色绑定不存在")
    db.delete(binding)
    db.commit()
    return {"status": "deleted", "id": binding_id}


# ---------- Department endpoints -------------------------------------------


@router.get("/departments", response_model=list[DepartmentOut])
def list_departments(
    db: Session = Depends(get_db),
    _user: dict = Depends(get_current_user),
):
    """List departments — available to all authenticated users.

    The document upload dropdown needs this so SYS_ADMIN / BE_CROSS / multi-dept
    PICs can pick the **target** department for uploads. Write endpoints below
    remain SYS_ADMIN-only.
    """
    rows = db.query(Department).order_by(Department.code.asc()).all()
    return [
        DepartmentOut(id=r.id, code=r.code, name=r.name or "", is_active=bool(r.is_active))
        for r in rows
    ]


@router.post("/departments", response_model=DepartmentOut)
def create_department(
    body: DepartmentCreate,
    db: Session = Depends(get_db),
    _admin: dict = Depends(require_sys_admin),
):
    if db.query(Department).filter(Department.code == body.code).first():
        raise HTTPException(status_code=409, detail="部门代码已存在")
    dept = Department(code=body.code, name=body.name or body.code, is_active=body.is_active)
    db.add(dept)
    db.commit()
    db.refresh(dept)
    return DepartmentOut(id=dept.id, code=dept.code, name=dept.name, is_active=bool(dept.is_active))


@router.patch("/departments/{dept_id}", response_model=DepartmentOut)
def update_department(
    dept_id: int,
    body: DepartmentUpdate,
    db: Session = Depends(get_db),
    _admin: dict = Depends(require_sys_admin),
):
    dept = db.get(Department, dept_id)
    if not dept:
        raise HTTPException(status_code=404, detail="部门不存在")
    data = body.model_dump(exclude_unset=True)
    for field, value in data.items():
        setattr(dept, field, value)
    db.commit()
    db.refresh(dept)
    return DepartmentOut(id=dept.id, code=dept.code, name=dept.name, is_active=bool(dept.is_active))
