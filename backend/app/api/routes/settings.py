"""Settings API routes — manage system configuration stored in the database."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.services.settings_service import (
    batch_update_settings,
    get_all_settings,
    get_knowledge_bases,
    save_knowledge_bases,
    update_setting,
)

router = APIRouter()


class SettingsUpdateRequest(BaseModel):
    dify: dict[str, str] = {}
    path: dict[str, str] = {}


class SettingSingleUpdateRequest(BaseModel):
    value: str
    path_mode: str | None = None


class KnowledgeBaseItem(BaseModel):
    id: str
    name: str
    api_key: str
    base_url: str
    dataset_id: str


class KnowledgeBasesUpdateRequest(BaseModel):
    knowledge_bases: list[KnowledgeBaseItem]
    default_id: str


@router.get("/settings", tags=["系统设置"])
def get_settings(db: Session = Depends(get_db)) -> dict[str, Any]:
    """获取全部系统配置，按分类返回。"""
    return get_all_settings(db)


@router.put("/settings", tags=["系统设置"])
def update_settings(data: SettingsUpdateRequest, db: Session = Depends(get_db)) -> dict[str, Any]:
    """批量更新系统配置。"""
    updates = {
        "dify": data.dify,
        "path": data.path,
    }
    return batch_update_settings(db, updates)


@router.put("/settings/{key}", tags=["系统设置"])
def update_single_setting(key: str, data: SettingSingleUpdateRequest, db: Session = Depends(get_db)) -> dict[str, Any]:
    """更新单条配置。"""
    setting = update_setting(db, key, data.value, data.path_mode)
    return {
        "key": setting.key,
        "value": setting.value,
        "category": setting.category,
        "path_mode": setting.path_mode,
    }


@router.get("/settings/resolve-path", tags=["系统设置"])
def resolve_relative_path(relative_path: str, db: Session = Depends(get_db)) -> dict[str, str]:
    """将相对路径解析为绝对路径。"""
    from app.config import settings as app_settings
    resolved = app_settings.resolve_path(relative_path)
    return {"absolute_path": str(resolved)}


@router.get("/knowledge-bases", tags=["系统设置"])
def get_knowledge_bases_endpoint(db: Session = Depends(get_db)) -> dict[str, Any]:
    """获取所有知识库列表和默认知识库ID。"""
    return get_knowledge_bases(db)


@router.put("/knowledge-bases", tags=["系统设置"])
def save_knowledge_bases_endpoint(
    data: KnowledgeBasesUpdateRequest,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """保存知识库列表和默认知识库ID。"""
    kb_list = [kb.model_dump() for kb in data.knowledge_bases]
    return save_knowledge_bases(db, kb_list, data.default_id)
