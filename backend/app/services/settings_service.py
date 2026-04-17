"""Service for managing system settings stored in the database."""

from __future__ import annotations

import json
import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.setting import SystemSetting

logger = logging.getLogger(__name__)


# Default settings that mirror .env values
DEFAULT_SETTINGS: dict[str, dict[str, Any]] = {
    "dify_api_key": {"value": "", "category": "dify"},
    "dify_base_url": {"value": "https://api.dify.ai/v1", "category": "dify"},
    "dify_dataset_id": {"value": "", "category": "dify"},
    "md_raw_dir": {"value": "../data/raw", "category": "path"},
    "md_redacted_dir": {"value": "../data/redacted", "category": "path"},
    "md_raw_dir_abs": {"value": "", "category": "path"},
    "md_redacted_dir_abs": {"value": "", "category": "path"},
    "index_dir": {"value": "../data/index", "category": "path"},
    "index_dir_abs": {"value": "", "category": "path"},
    "path_mode": {"value": "relative", "category": "path"},
}


def _ensure_defaults(db: Session) -> None:
    """Insert default rows for any missing settings keys."""
    existing_keys = {
        row[0]
        for row in db.execute(select(SystemSetting.key)).all()
    }
    for key, meta in DEFAULT_SETTINGS.items():
        if key not in existing_keys:
            db.add(SystemSetting(key=key, value=meta["value"], category=meta["category"]))
    db.commit()


def get_all_settings(db: Session) -> dict[str, Any]:
    """Return all settings grouped by category."""
    _ensure_defaults(db)
    rows = db.execute(select(SystemSetting)).scalars().all()

    result: dict[str, Any] = {
        "dify": {},
        "path": {},
        "general": {},
    }
    for row in rows:
        if row.category in result:
            result[row.category][row.key] = row.value

    # Include path_mode at the path level
    path_mode_row = db.execute(
        select(SystemSetting).where(SystemSetting.key == "path_mode")
    ).scalar_one_or_none()
    if path_mode_row:
        result["path"]["path_mode"] = path_mode_row.value

    return result


def update_setting(db: Session, key: str, value: str, path_mode: str | None = None) -> SystemSetting:
    """Update or create a single setting."""
    setting = db.execute(
        select(SystemSetting).where(SystemSetting.key == key)
    ).scalar_one_or_none()

    if setting:
        setting.value = value
        if path_mode is not None:
            setting.path_mode = path_mode
    else:
        category = DEFAULT_SETTINGS.get(key, {}).get("category", "general")
        setting = SystemSetting(key=key, value=value, category=category, path_mode=path_mode)
        db.add(setting)

    db.commit()
    db.refresh(setting)
    return setting


def batch_update_settings(db: Session, updates: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Batch update multiple settings by category.

    Expected format:
    {
        "dify": {"dify_api_key": "...", "dify_base_url": "...", ...},
        "path": {"md_raw_dir": "...", "path_mode": "relative", ...}
    }
    """
    results: dict[str, Any] = {}

    # Update dify settings
    for key, value in updates.get("dify", {}).items():
        setting = update_setting(db, key, value)
        results[key] = setting.value

    # Update path settings
    path_data = updates.get("path", {})
    path_mode = path_data.pop("path_mode", "relative")
    # Update path_mode first
    update_setting(db, "path_mode", path_mode)
    results["path_mode"] = path_mode

    for key, value in path_data.items():
        if key == "path_mode":
            continue
        setting = update_setting(db, key, value)
        results[key] = setting.value

    return results


def get_value(db: Session, key: str, default: str = "") -> str:
    """Get a single setting value by key, with fallback to default."""
    row = db.execute(
        select(SystemSetting).where(SystemSetting.key == key)
    ).scalar_one_or_none()
    return row.value if row else default


def get_path_value(db: Session, key: str, default: str = "") -> str:
    """Get a path value respecting the current path_mode."""
    mode = get_value(db, "path_mode", "relative")
    if mode == "absolute":
        abs_key = f"{key}_abs"
        val = get_value(db, abs_key, "")
        return val if val else get_value(db, key, default)
    return get_value(db, key, default)


# ---- Knowledge Base management ----

def get_knowledge_bases(db: Session) -> dict[str, Any]:
    """Return all knowledge bases and the default ID.

    Returns:
        {"knowledge_bases": [...], "default_id": "kb_xxx"}
    """
    kb_json = get_value(db, "knowledge_bases", "[]")
    try:
        knowledge_bases = json.loads(kb_json)
    except json.JSONDecodeError:
        knowledge_bases = []

    default_id = get_value(db, "default_knowledge_base_id", "")

    # If no default is set but there are KBs, pick the first one
    if not default_id and knowledge_bases:
        default_id = knowledge_bases[0].get("id", "")

    return {
        "knowledge_bases": knowledge_bases,
        "default_id": default_id,
    }


def save_knowledge_bases(db: Session, knowledge_bases: list[dict[str, Any]], default_id: str) -> dict[str, Any]:
    """Save knowledge bases list and default ID.

    Args:
        knowledge_bases: List of KB dicts with keys: id, name, api_key, base_url, dataset_id
        default_id: The ID of the default knowledge base
    """
    kb_json = json.dumps(knowledge_bases, ensure_ascii=False)
    update_setting(db, "knowledge_bases", kb_json)
    update_setting(db, "default_knowledge_base_id", default_id)

    return {
        "knowledge_bases": knowledge_bases,
        "default_id": default_id,
    }


def get_kb_by_id(db: Session, kb_id: str) -> dict[str, Any] | None:
    """Get a single knowledge base by its ID."""
    result = get_knowledge_bases(db)
    for kb in result.get("knowledge_bases", []):
        if kb.get("id") == kb_id:
            return kb
    return None


def get_default_kb(db: Session) -> dict[str, Any] | None:
    """Get the default knowledge base."""
    result = get_knowledge_bases(db)
    default_id = result.get("default_id", "")
    for kb in result.get("knowledge_bases", []):
        if kb.get("id") == default_id:
            return kb
    # Fallback to first KB
    if result.get("knowledge_bases"):
        return result["knowledge_bases"][0]
    return None


def get_dify_config(db: Session, kb_id: str | None = None) -> dict[str, str] | None:
    """Get Dify API config for a specific KB or the default KB.

    Returns dict with keys: api_key, base_url, dataset_id
    Returns None if no KB is configured.
    """
    if kb_id:
        kb = get_kb_by_id(db, kb_id)
    else:
        kb = get_default_kb(db)

    if kb:
        return {
            "api_key": kb.get("api_key", ""),
            "base_url": kb.get("base_url", ""),
            "dataset_id": kb.get("dataset_id", ""),
        }
    return None
