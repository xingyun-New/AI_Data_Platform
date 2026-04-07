"""SharePoint REST API 客户端封装 (NTLM 认证, 适用于 On-Premises SharePoint)"""

from typing import Optional
import requests
from requests_ntlm import HttpNtlmAuth

HEADERS_JSON = {"Accept": "application/json;odata=nometadata"}


class SharePointClient:
    def __init__(self, site_url: str, username: str, password: str):
        self.site_url = site_url.rstrip("/")
        self.auth = HttpNtlmAuth(username, password)
        self.session = requests.Session()
        self.session.auth = self.auth
        self.session.headers.update(HEADERS_JSON)

    def _get(self, endpoint: str, params: Optional[dict] = None) -> dict:
        url = f"{self.site_url}/_api/{endpoint}"
        resp = self.session.get(url, params=params)
        resp.raise_for_status()
        return resp.json()

    # ── 站点信息 ──────────────────────────────────────────────

    def get_site_info(self) -> dict:
        """获取当前站点基本信息 (标题、描述、URL、创建时间等)"""
        return self._get("web")

    def get_site_users(self) -> list:
        """获取站点所有用户"""
        return self._get("web/siteusers")["value"]

    def get_current_user(self) -> dict:
        """获取当前登录用户信息"""
        return self._get("web/currentuser")

    # ── 列表 (Lists) ─────────────────────────────────────────

    def get_all_lists(self) -> list:
        """获取站点下所有列表 (包含文档库)"""
        return self._get("web/lists")["value"]

    def get_list_by_title(self, title: str) -> dict:
        """根据标题获取单个列表的元数据"""
        return self._get(f"web/lists/getbytitle('{title}')")

    def get_list_fields(self, title: str) -> list:
        """获取列表的所有字段 (列) 定义"""
        return self._get(f"web/lists/getbytitle('{title}')/fields")["value"]

    def get_list_items(
        self,
        title: str,
        top: int = 100,
        skip: int = 0,
        select: Optional[str] = None,
        filter_query: Optional[str] = None,
        orderby: Optional[str] = None,
    ) -> list:
        """获取列表中的数据行 (支持分页、筛选、排序、字段选择)"""
        params: dict = {"$top": top, "$skip": skip}
        if select:
            params["$select"] = select
        if filter_query:
            params["$filter"] = filter_query
        if orderby:
            params["$orderby"] = orderby
        return self._get(
            f"web/lists/getbytitle('{title}')/items", params=params
        )["value"]

    def get_list_item_count(self, title: str) -> int:
        """获取列表项总数"""
        data = self._get(f"web/lists/getbytitle('{title}')")
        return data.get("ItemCount", 0)

    def get_list_content_types(self, title: str) -> list:
        """获取列表的内容类型"""
        return self._get(
            f"web/lists/getbytitle('{title}')/contenttypes"
        )["value"]

    def get_list_views(self, title: str) -> list:
        """获取列表的所有视图"""
        return self._get(f"web/lists/getbytitle('{title}')/views")["value"]

    # ── 文档库 / 文件 ────────────────────────────────────────

    def get_folder_contents(self, folder_path: str) -> dict:
        """获取指定文件夹下的子文件夹和文件"""
        folder_path = folder_path.strip("/")
        folders = self._get(
            f"web/GetFolderByServerRelativeUrl('{folder_path}')/Folders"
        )["value"]
        files = self._get(
            f"web/GetFolderByServerRelativeUrl('{folder_path}')/Files"
        )["value"]
        return {"folders": folders, "files": files}

    def get_file_metadata(self, file_path: str) -> dict:
        """获取单个文件的元数据 (大小、修改时间、作者等)"""
        file_path = file_path.strip("/")
        return self._get(
            f"web/GetFileByServerRelativeUrl('{file_path}')"
        )

    def download_file(self, file_path: str) -> bytes:
        """下载文件内容 (返回二进制数据)"""
        file_path = file_path.strip("/")
        url = (
            f"{self.site_url}/_api/"
            f"web/GetFileByServerRelativeUrl('{file_path}')/$value"
        )
        resp = self.session.get(url)
        resp.raise_for_status()
        return resp.content

    # ── 子站点 ────────────────────────────────────────────────

    def get_subsites(self) -> list:
        """获取所有子站点"""
        return self._get("web/webs")["value"]

    # ── 搜索 ──────────────────────────────────────────────────

    def search(self, query_text: str, row_limit: int = 50) -> list:
        """SharePoint 搜索 (需要 Search Service 已启用)"""
        params = {"querytext": f"'{query_text}'", "rowlimit": row_limit}
        data = self._get("search/query", params=params)
        rows = (
            data.get("PrimaryQueryResult", {})
            .get("RelevantResults", {})
            .get("Table", {})
            .get("Rows", [])
        )
        return rows
