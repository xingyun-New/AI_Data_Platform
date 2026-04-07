"""Authentication service — Innomate API integration + JWT issuance."""

import logging
from datetime import datetime, timedelta, timezone

import httpx
from jose import jwt

from app.config import settings

logger = logging.getLogger(__name__)


async def get_user_info_from_innomate(username: str) -> dict:
    """Call the Innomate findData API to look up the user's department.

    Returns {"department": ..., "section": ..., "display_name": ..., "raw": ...}
    Falls back to mock when INNOMATE_API_URL is not configured.
    """
    if not settings.innomate_api_url:
        dept = _mock_department(username)
        return {
            "department": dept,
            "section": "",
            "display_name": username,
            "raw": None,
        }

    payload = {
        "firm": "36",
        "userInfo": {
            "i4Id": "",
            "firm": "",
        },
        "inputData": {
            "applicationName": "AI_DATA_HANDLING",
            "dataKey": "getUserInfor",
            "customizedParams": {
                "i4id": username,
            },
        },
    }

    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(
            settings.innomate_api_url,
            json=payload,
            headers={
                "Content-Type": "application/json",
                "Accept": "*/*",
            },
        )
        resp.raise_for_status()
        data = resp.json()

    logger.info("Innomate API response for %s: %s", username, data)

    user_record = _extract_user_record(data)
    department = _extract_field(user_record, ("DEPARTMENT", "department", "dept", "deptName"))
    section = _extract_field(user_record, ("SECTION", "section", "sectionName"))
    display_name = _extract_field(user_record, ("USERNAME", "displayName", "name", "userName", "fullName")) or username

    return {
        "department": department,
        "section": section,
        "display_name": display_name,
        "raw": data,
    }


def _extract_user_record(data: dict) -> dict:
    """Extract the first user record from the Innomate API response.

    Expected structure: outputData.dataValue[0] → {USERNAME, DEPARTMENT, SECTION, ...}
    """
    if not data:
        return {}

    output = data.get("outputData")
    if isinstance(output, dict):
        data_value = output.get("dataValue")
        if isinstance(data_value, list) and len(data_value) > 0:
            item = data_value[0]
            if isinstance(item, dict):
                return item

    for wrapper in ("data", "result", "resultData"):
        inner = data.get(wrapper)
        if isinstance(inner, dict):
            return inner
        if isinstance(inner, list) and len(inner) > 0 and isinstance(inner[0], dict):
            return inner[0]

    return data


def _extract_field(record: dict, candidates: tuple[str, ...]) -> str:
    """Return the first non-empty value matching any candidate key (case-insensitive)."""
    if not record:
        return ""
    lower_map = {k.lower(): v for k, v in record.items()}
    for key in candidates:
        val = record.get(key) or lower_map.get(key.lower())
        if val:
            return str(val)
    return ""


def _mock_department(username: str) -> str:
    """Return a mock department for local development."""
    mock_map = {
        "admin": "Admin",
        "sales_user": "Sales",
        "pe_user": "PE",
        "rd_user": "R&D",
    }
    return mock_map.get(username, "General")


def verify_password(password: str) -> bool:
    return password == settings.unified_password


def create_access_token(username: str, department: str, section: str = "", display_name: str = "") -> str:
    expire = datetime.now(timezone.utc) + timedelta(minutes=settings.jwt_expire_minutes)
    payload = {
        "sub": username,
        "dept": department,
        "section": section,
        "display_name": display_name,
        "exp": expire,
    }
    return jwt.encode(payload, settings.secret_key, algorithm=settings.jwt_algorithm)
