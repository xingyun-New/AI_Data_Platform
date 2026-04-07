"""Document metadata model — tracks files through the desensitize / index pipeline."""

from datetime import datetime

from sqlalchemy import DateTime, Index, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class Document(Base):
    __tablename__ = "documents"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    filename: Mapped[str] = mapped_column(String(500), nullable=False, index=True)
    directory: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    department: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    section: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    uploaded_by: Mapped[str] = mapped_column(String(100), nullable=False, default="")
    status: Mapped[str] = mapped_column(
        String(50), nullable=False, default="raw",
        comment="raw | desensitized | indexed | error",
    )
    file_hash: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    raw_path: Mapped[str] = mapped_column(Text, nullable=False, default="")
    redacted_path: Mapped[str] = mapped_column(Text, nullable=False, default="")
    index_path: Mapped[str] = mapped_column(Text, nullable=False, default="")
    error_message: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(),
    )

    __table_args__ = (
        Index("idx_document_status", "status"),
        Index("idx_document_department", "department"),
        Index("idx_document_status_department", "status", "department"),
    )
