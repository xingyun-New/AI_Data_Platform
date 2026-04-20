"""User-role binding — supports multiple roles per user, scoped by department for PIC."""

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


ROLE_SYS_ADMIN = "SYS_ADMIN"
ROLE_BE_CROSS = "BE_CROSS"
ROLE_DEPT_PIC = "DEPT_PIC"
ROLE_MEMBER = "MEMBER"

ALL_ROLES = [ROLE_SYS_ADMIN, ROLE_BE_CROSS, ROLE_DEPT_PIC, ROLE_MEMBER]


class UserRole(Base):
    __tablename__ = "user_roles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True,
    )
    role: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    # Only used for DEPT_PIC — restricts the PIC role to a specific department.
    department_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("departments.id", ondelete="CASCADE"), nullable=True, index=True,
    )
    granted_by: Mapped[str] = mapped_column(String(100), nullable=False, default="")
    granted_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    __table_args__ = (
        UniqueConstraint("user_id", "role", "department_id", name="uq_user_role_dept"),
    )
