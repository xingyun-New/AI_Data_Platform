"""Index rule model — department-level rules for index generation and cross-department sharing.

Rules govern how documents are indexed and which departments they should be shared with.
Three rule types:
  - share:    "产品需求类文档默认共享给 PE 和 R&D"
  - access:   "技术规范类文档默认 access_level 为 internal"
  - classify: "含客户信息的文档归类为 客户管理"
"""

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class IndexRule(Base):
    __tablename__ = "index_rules"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    department: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    rule_name: Mapped[str] = mapped_column(String(300), nullable=False)
    rule_description: Mapped[str] = mapped_column(
        Text, nullable=False,
        comment="Natural language description, e.g. '产品需求类文档默认共享给 PE 和 R&D 部门'",
    )
    rule_type: Mapped[str] = mapped_column(
        String(50), nullable=False, default="share",
        comment="share | access | classify",
    )
    target_departments: Mapped[str] = mapped_column(
        Text, nullable=False, default="",
        comment="JSON array of department codes, e.g. '[\"PE\",\"R&D\"]'. Used by share rules.",
    )
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_by: Mapped[str] = mapped_column(String(100), nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(),
    )
