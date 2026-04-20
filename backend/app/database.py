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
    # Postgres uses BYTEA for raw bytes; SQLite accepts BLOB (or even the BYTEA keyword
    # as a no-op type name). We branch on dialect to stay portable.
    _blob_type = "BYTEA" if _is_postgres else "BLOB"
    _bool_true = "TRUE" if _is_postgres else "1"
    _MIGRATIONS: list[tuple[str, str, str]] = [
        ("users", "display_name", "VARCHAR(200) NOT NULL DEFAULT ''"),
        ("users", "section", "VARCHAR(200) NOT NULL DEFAULT ''"),
        ("users", "is_active", f"BOOLEAN NOT NULL DEFAULT {_bool_true}"),
        ("documents", "section", "VARCHAR(200) NOT NULL DEFAULT ''"),
        ("documents", "uploaded_by", "VARCHAR(100) NOT NULL DEFAULT ''"),
        ("documents", "knowledge_base_id", "VARCHAR(64) NOT NULL DEFAULT ''"),
        ("documents", "index_embedding", f"{_blob_type}"),
        ("documents", "index_embedding_dim", "INTEGER NOT NULL DEFAULT 0"),
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

    # Seed departments from existing distinct values in users/documents.
    # Kept idempotent: ON CONFLICT / INSERT OR IGNORE skips existing codes.
    if insp.has_table("departments"):
        _seed_departments(insp)

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

    # After all tables exist, promote configured usernames to SYS_ADMIN.
    _bootstrap_sys_admin()


def _seed_departments(insp) -> None:
    """Seed the ``departments`` table from distinct values in users/documents."""
    with engine.begin() as conn:
        codes: set[str] = set()
        for table, column in (("users", "department"), ("documents", "department")):
            if insp.has_table(table):
                rows = conn.execute(text(f"SELECT DISTINCT {column} FROM {table} WHERE {column} <> ''")).fetchall()
                codes.update(str(r[0]) for r in rows if r[0])

        # Always include the configured BE department so BE_CROSS lookup works out of the box.
        from app.config import settings as _settings  # local import to avoid cycles
        if _settings.be_department_code:
            codes.add(_settings.be_department_code)

        for code in codes:
            if _is_postgres:
                conn.execute(
                    text("INSERT INTO departments (code, name, is_active) VALUES (:c, :n, TRUE) "
                         "ON CONFLICT (code) DO NOTHING"),
                    {"c": code, "n": code},
                )
            else:
                conn.execute(
                    text("INSERT OR IGNORE INTO departments (code, name, is_active) VALUES (:c, :n, 1)"),
                    {"c": code, "n": code},
                )


def _bootstrap_sys_admin() -> None:
    """Grant SYS_ADMIN role to users listed in ``settings.admin_usernames`` if they exist."""
    from app.config import settings as _settings  # local import to avoid cycles

    usernames = [u.strip() for u in (_settings.admin_usernames or "").split(",") if u.strip()]
    if not usernames:
        return

    insp = inspect(engine)
    if not (insp.has_table("users") and insp.has_table("user_roles")):
        return

    with engine.begin() as conn:
        for username in usernames:
            row = conn.execute(
                text("SELECT id FROM users WHERE username = :u"), {"u": username}
            ).fetchone()
            if not row:
                continue
            user_id = row[0]
            existing = conn.execute(
                text("SELECT 1 FROM user_roles WHERE user_id = :uid AND role = 'SYS_ADMIN' "
                     "AND department_id IS NULL"),
                {"uid": user_id},
            ).fetchone()
            if existing:
                continue
            conn.execute(
                text("INSERT INTO user_roles (user_id, role, department_id, granted_by) "
                     "VALUES (:uid, 'SYS_ADMIN', NULL, 'system')"),
                {"uid": user_id},
            )
            logger.info("Migration: granted SYS_ADMIN to user %s", username)
