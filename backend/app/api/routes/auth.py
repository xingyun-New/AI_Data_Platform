"""Login endpoint — username + unified password + Innomate department lookup."""

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.config import settings
from app.database import get_db
from app.models.department import Department
from app.models.user import User
from app.models.user_role import (
    ROLE_BE_CROSS,
    ROLE_MEMBER,
    ROLE_SYS_ADMIN,
    UserRole,
)
from app.services.auth_service import (
    create_access_token,
    get_user_info_from_innomate,
    verify_password,
)

logger = logging.getLogger(__name__)

router = APIRouter()


class LoginRequest(BaseModel):
    username: str
    password: str


class RoleBinding(BaseModel):
    role: str
    department_id: int | None = None
    department_code: str | None = None


class LoginResponse(BaseModel):
    token: str
    username: str
    display_name: str
    department: str
    section: str
    roles: list[RoleBinding]


class UserInfo(BaseModel):
    username: str
    display_name: str
    department: str
    section: str
    roles: list[RoleBinding] = []


def _ensure_department(db: Session, code: str) -> Department | None:
    """Fetch-or-create a department row for ``code``. Returns None for empty code."""
    if not code:
        return None
    dept = db.query(Department).filter(Department.code == code).first()
    if dept is None:
        dept = Department(code=code, name=code, is_active=True)
        db.add(dept)
        db.flush()
    return dept


def _sync_auto_roles(db: Session, user: User, department_code: str) -> None:
    """Apply role bindings that are derived from user attributes / config on every login:

    - Users listed in ``settings.admin_usernames`` get SYS_ADMIN.
    - Users whose department matches ``settings.be_department_code`` get BE_CROSS.
    - Any user without an explicit role gets MEMBER as a safe default.

    Existing manual bindings (e.g. DEPT_PIC granted by an admin) are left untouched.
    """
    admin_names = {u.strip() for u in (settings.admin_usernames or "").split(",") if u.strip()}
    be_code = (settings.be_department_code or "").strip()

    def _grant(role: str, department_id: int | None = None) -> None:
        existing = (
            db.query(UserRole)
            .filter(
                UserRole.user_id == user.id,
                UserRole.role == role,
                UserRole.department_id.is_(department_id) if department_id is None else UserRole.department_id == department_id,
            )
            .first()
        )
        if existing is None:
            db.add(UserRole(
                user_id=user.id,
                role=role,
                department_id=department_id,
                granted_by="system",
            ))

    if user.username in admin_names:
        _grant(ROLE_SYS_ADMIN)

    if be_code and department_code == be_code:
        _grant(ROLE_BE_CROSS)

    db.flush()

    existing_roles = db.query(UserRole).filter(UserRole.user_id == user.id).count()
    if existing_roles == 0:
        _grant(ROLE_MEMBER)
        db.flush()


def _load_role_bindings(db: Session, user_id: int) -> list[RoleBinding]:
    rows = (
        db.query(UserRole, Department)
        .outerjoin(Department, Department.id == UserRole.department_id)
        .filter(UserRole.user_id == user_id)
        .all()
    )
    return [
        RoleBinding(
            role=r.role,
            department_id=r.department_id,
            department_code=(d.code if d else None),
        )
        for r, d in rows
    ]


@router.post("/login", response_model=LoginResponse)
async def login(body: LoginRequest, db: Session = Depends(get_db)):
    if not verify_password(body.password):
        raise HTTPException(status_code=401, detail="密码错误")

    try:
        user_info = await get_user_info_from_innomate(body.username)
        department = user_info["department"]
        section = user_info["section"]
        display_name = user_info["display_name"]
    except Exception as e:
        logger.error("Innomate API call failed for %s: %s", body.username, e)
        raise HTTPException(status_code=502, detail=f"获取用户部门信息失败: {e}")

    user = db.query(User).filter(User.username == body.username).first()
    if user is None:
        user = User(
            username=body.username,
            display_name=display_name,
            department=department,
            section=section,
        )
        db.add(user)
        db.flush()
    else:
        user.display_name = display_name
        user.department = department
        user.section = section
        if not user.is_active:
            raise HTTPException(status_code=403, detail="账户已被禁用，请联系系统管理员")
    user.last_login_at = datetime.now(timezone.utc)

    _ensure_department(db, department)
    _sync_auto_roles(db, user, department)

    bindings = _load_role_bindings(db, user.id)
    db.commit()

    roles_payload = [
        {"role": b.role, "department_id": b.department_id}
        for b in bindings
    ]
    token = create_access_token(body.username, department, section, display_name, roles=roles_payload)
    return LoginResponse(
        token=token,
        username=body.username,
        display_name=display_name,
        department=department,
        section=section,
        roles=bindings,
    )


@router.get("/me", response_model=UserInfo)
def me(
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    user = db.query(User).filter(User.username == current_user["username"]).first()
    bindings = _load_role_bindings(db, user.id) if user else []
    return UserInfo(
        username=current_user["username"],
        display_name=current_user.get("display_name") or current_user["username"],
        department=current_user.get("department") or "",
        section=current_user.get("section") or "",
        roles=bindings,
    )
