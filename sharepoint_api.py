"""SharePoint 数据获取 API — 基于 FastAPI + NTLM 认证"""

import logging
import os
import traceback
from typing import Optional

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from sharepoint_client import SharePointClient

load_dotenv()

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="SharePoint Data API",
    description="通过 REST API 获取 On-Premises SharePoint 站点数据",
    version="1.0.0",
)


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    tb = traceback.format_exc()
    logger.error(f"Unhandled error on {request.method} {request.url}:\n{tb}")
    return JSONResponse(
        status_code=500,
        content={"detail": str(exc), "type": type(exc).__name__, "traceback": tb},
    )

SITE_URL = os.getenv("SHAREPOINT_SITE_URL", "")
USERNAME = os.getenv("SHAREPOINT_USERNAME", "")
PASSWORD = os.getenv("SHAREPOINT_PASSWORD", "")


def _client() -> SharePointClient:
    if not all([SITE_URL, USERNAME, PASSWORD]):
        raise HTTPException(
            status_code=500,
            detail="SharePoint 连接参数未配置，请检查 .env 文件",
        )
    return SharePointClient(SITE_URL, USERNAME, PASSWORD)


# ── 健康检查 ──────────────────────────────────────────────────


@app.get("/health", tags=["系统"])
def health_check():
    return {"status": "ok"}


@app.get("/debug/test-connection", tags=["系统"])
def debug_test_connection():
    """直接测试 SharePoint 连接，返回完整调试信息"""
    import requests as req
    from requests_ntlm import HttpNtlmAuth

    info = {"site_url": SITE_URL, "username": USERNAME, "password_set": bool(PASSWORD)}
    try:
        api_url = f"{SITE_URL}/_api/web"
        resp = req.get(
            api_url,
            auth=HttpNtlmAuth(USERNAME, PASSWORD),
            headers={"Accept": "application/json;odata=nometadata"},
            timeout=15,
        )
        info["status_code"] = resp.status_code
        info["response_headers"] = dict(resp.headers)
        info["response_body"] = resp.text[:2000]
    except Exception as e:
        info["error"] = str(e)
        info["error_type"] = type(e).__name__
        info["traceback"] = traceback.format_exc()
    return info


# ── 站点 ──────────────────────────────────────────────────────


@app.get("/api/site", tags=["站点信息"])
def get_site_info():
    """获取站点基本信息 (标题、描述、URL、创建时间等)"""
    return _client().get_site_info()


@app.get("/api/site/users", tags=["站点信息"])
def get_site_users():
    """获取站点所有用户"""
    return _client().get_site_users()


@app.get("/api/site/currentuser", tags=["站点信息"])
def get_current_user():
    """获取当前认证用户信息"""
    return _client().get_current_user()


@app.get("/api/site/subsites", tags=["站点信息"])
def get_subsites():
    """获取所有子站点"""
    return _client().get_subsites()


# ── 列表 ──────────────────────────────────────────────────────


@app.get("/api/lists", tags=["列表"])
def get_all_lists():
    """获取站点下所有列表 (含文档库)"""
    try:
        return _client().get_all_lists()
    except Exception as e:
        logger.error(f"get_all_lists failed: {traceback.format_exc()}")
        raise HTTPException(status_code=500, detail={
            "error": str(e),
            "type": type(e).__name__,
            "trace": traceback.format_exc(),
        })


class ListSummary(BaseModel):
    Title: str
    EntityTypeName: Optional[str] = None
    ItemCount: int = 0
    BaseTemplate: int = 0
    Hidden: bool = False


@app.get("/api/lists/summary", tags=["列表"], response_model=list[ListSummary])
def get_lists_summary():
    """获取所有列表的精简摘要 (标题、类型、条目数)"""
    raw = _client().get_all_lists()
    return [
        ListSummary(
            Title=item["Title"],
            EntityTypeName=item.get("EntityTypeName"),
            ItemCount=item.get("ItemCount", 0),
            BaseTemplate=item.get("BaseTemplate", 0),
            Hidden=item.get("Hidden", False),
        )
        for item in raw
    ]


@app.get("/api/lists/{title}", tags=["列表"])
def get_list_by_title(title: str):
    """根据列表标题获取列表元数据"""
    try:
        return _client().get_list_by_title(title)
    except Exception as e:
        raise HTTPException(status_code=404, detail=str(e))


@app.get("/api/lists/{title}/fields", tags=["列表"])
def get_list_fields(title: str):
    """获取列表的所有字段 (列) 定义"""
    return _client().get_list_fields(title)


@app.get("/api/lists/{title}/items", tags=["列表"])
def get_list_items(
    title: str,
    top: int = Query(100, ge=1, le=5000, description="每页条数"),
    skip: int = Query(0, ge=0, description="跳过条数"),
    select: Optional[str] = Query(None, description="字段选择，逗号分隔，如 Title,Created"),
    filter: Optional[str] = Query(None, alias="$filter", description="OData 筛选表达式"),
    orderby: Optional[str] = Query(None, alias="$orderby", description="排序字段，如 Created desc"),
):
    """获取列表数据行 (支持分页 / 筛选 / 排序 / 字段选择)"""
    return _client().get_list_items(
        title, top=top, skip=skip, select=select,
        filter_query=filter, orderby=orderby,
    )


@app.get("/api/lists/{title}/count", tags=["列表"])
def get_list_item_count(title: str):
    """获取列表项总数"""
    return {"title": title, "count": _client().get_list_item_count(title)}


@app.get("/api/lists/{title}/contenttypes", tags=["列表"])
def get_list_content_types(title: str):
    """获取列表的内容类型"""
    return _client().get_list_content_types(title)


@app.get("/api/lists/{title}/views", tags=["列表"])
def get_list_views(title: str):
    """获取列表的所有视图"""
    return _client().get_list_views(title)


# ── 文件 / 文件夹 ────────────────────────────────────────────


@app.get("/api/folders", tags=["文件"])
def get_folder_contents(
    path: str = Query(..., description="服务器相对路径，如 /orgs/BFAB003M0/Shared Documents"),
):
    """获取指定文件夹下的子文件夹与文件列表"""
    return _client().get_folder_contents(path)


@app.get("/api/files/metadata", tags=["文件"])
def get_file_metadata(
    path: str = Query(..., description="文件的服务器相对路径"),
):
    """获取单个文件的元数据 (大小、修改时间、作者等)"""
    return _client().get_file_metadata(path)


# ── 搜索 ──────────────────────────────────────────────────────


@app.get("/api/search", tags=["搜索"])
def search(
    q: str = Query(..., description="搜索关键词"),
    limit: int = Query(50, ge=1, le=500, description="返回行数"),
):
    """SharePoint 全文搜索 (需要 Search Service 已启用)"""
    return _client().search(q, row_limit=limit)


# ── 启动入口 ──────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn

    uvicorn.run("sharepoint_api:app", host="0.0.0.0", port=8000, reload=True)
