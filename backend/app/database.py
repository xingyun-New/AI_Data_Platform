"""SQLAlchemy engine, session, and base model."""

import logging

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.config import settings

logger = logging.getLogger(__name__)

_is_postgres = "postgresql" in settings.database_url

engine = create_engine(
    settings.database_url,
    connect_args={"check_same_thread": False} if "sqlite" in settings.database_url else {},
    pool_pre_ping=True,
    echo=False,
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _index_exists(insp, table: str, index_name: str) -> bool:
    """Check if an index exists (works for both SQLite and PostgreSQL)."""
    if _is_postgres:
        with engine.connect() as conn:
            result = conn.execute(text(
                "SELECT 1 FROM pg_indexes WHERE tablename = :table AND indexname = :index"
            ), {"table": table, "index": index_name})
            return result.fetchone() is not None
    else:
        indexes = insp.get_indexes(table)
        return any(idx["name"] == index_name for idx in indexes)


def run_migrations() -> None:
    """Add missing columns and indexes to existing tables (lightweight schema migration)."""
    _MIGRATIONS: list[tuple[str, str, str]] = [
        ("users", "display_name", "VARCHAR(200) NOT NULL DEFAULT ''"),
        ("users", "section", "VARCHAR(200) NOT NULL DEFAULT ''"),
        ("documents", "section", "VARCHAR(200) NOT NULL DEFAULT ''"),
        ("documents", "uploaded_by", "VARCHAR(100) NOT NULL DEFAULT ''"),
        ("documents", "knowledge_base_id", "VARCHAR(64) NOT NULL DEFAULT ''"),
        ("kg_entities", "embedding_dim", "INTEGER NOT NULL DEFAULT 0"),
    ]
    insp = inspect(engine)
    with engine.begin() as conn:
        for table, column, col_type in _MIGRATIONS:
            if not insp.has_table(table):
                continue
            existing = {c["name"] for c in insp.get_columns(table)}
            if column not in existing:
                conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {col_type}"))
                logger.info("Migration: added column %s.%s", table, column)

        if insp.has_table("documents"):
            indexes = [
                ("idx_document_status", "documents (status)"),
                ("idx_document_department", "documents (department)"),
                ("idx_document_status_department", "documents (status, department)"),
            ]
            for index_name, columns in indexes:
                if not _index_exists(insp, "documents", index_name):
                    conn.execute(text(f"CREATE INDEX {index_name} ON documents {columns}"))
                    logger.info("Migration: added index %s", index_name)

    # Create system_settings table if it doesn't exist
    if not insp.has_table("system_settings"):
        with engine.begin() as conn:
            if _is_postgres:
                conn.execute(text("""
                    CREATE TABLE system_settings (
                        id SERIAL PRIMARY KEY,
                        key VARCHAR(64) NOT NULL UNIQUE,
                        value TEXT NOT NULL DEFAULT '',
                        category VARCHAR(32) NOT NULL DEFAULT 'general',
                        path_mode VARCHAR(16),
                        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                """))
            else:
                conn.execute(text("""
                    CREATE TABLE system_settings (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        key VARCHAR(64) NOT NULL UNIQUE,
                        value TEXT NOT NULL DEFAULT '',
                        category VARCHAR(32) NOT NULL DEFAULT 'general',
                        path_mode VARCHAR(16),
                        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                """))
            logger.info("Migration: created system_settings table")
