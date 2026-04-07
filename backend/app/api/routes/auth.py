"""Login endpoint — username + unified password + Innomate department lookup."""

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.database import get_db
from app.models.user import User
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


class LoginResponse(BaseModel):
    token: str
    username: str
    display_name: str
    department: str
    section: str


class UserInfo(BaseModel):
    username: str
    display_name: str
    department: str
    section: str


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
    else:
        user.display_name = display_name
        user.department = department
        user.section = section
    user.last_login_at = datetime.now(timezone.utc)
    db.commit()

    token = create_access_token(body.username, department, section, display_name)
    return LoginResponse(
        token=token,
        username=body.username,
        display_name=display_name,
        department=department,
        section=section,
    )


@router.get("/me", response_model=UserInfo)
def me(current_user: dict = Depends(get_current_user)):
    return UserInfo(**current_user)
