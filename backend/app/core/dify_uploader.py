"""Dify Knowledge Base uploader — upload documents and set metadata via Dify API.

Workflow per document:
  1. ensure_metadata_fields  — create any missing metadata field definitions
  2. upload_document         — POST file to Dify, get document_id + batch_id
  3. wait_for_indexing       — poll until indexing completes or errors
  4. set_document_metadata   — batch-update metadata values on the document
"""

import asyncio
import json
import logging
from pathlib import Path

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

DIFY_METADATA_FIELDS: list[dict[str, str]] = [
    {"name": "knowledge_db_name", "type": "string"},
    {"name": "department", "type": "string"},
    {"name": "section", "type": "string"},
    {"name": "access_level", "type": "string"},
    {"name": "shared_departments", "type": "string"},
    {"name": "doc_category", "type": "string"},
    {"name": "creator", "type": "string"},
    {"name": "is_redacted", "type": "string"},
]

_POLL_INTERVAL = 2.0
_POLL_MAX_ATTEMPTS = 120


def _headers(api_key: str | None = None) -> dict[str, str]:
    key = api_key or settings.dify_api_key
    return {"Authorization": f"Bearer {key}"}


def _base_url(base: str | None = None) -> str:
    return (base or settings.dify_base_url).rstrip("/")


def to_dify_metadata(index_meta: dict) -> dict[str, str]:
    """Convert index_generator dify_metadata dict to flat string-only dict for Dify."""
    meta: dict[str, str] = {}
    meta["knowlege_db_name"] = str(index_meta.get("filename", ""))
    meta["department"] = str(index_meta.get("department", ""))
    meta["section"] = str(index_meta.get("section", ""))
    meta["access_level"] = str(index_meta.get("access_level", ""))
    meta["doc_category"] = str(index_meta.get("doc_category", "other"))
    meta["creator"] = str(index_meta.get("creator", ""))
    meta["is_redacted"] = str(index_meta.get("is_redacted", False)).lower()

    shared = index_meta.get("shared_departments", [])
    if isinstance(shared, list):
        meta["shared_departments"] = ",".join(shared)
    else:
        meta["shared_departments"] = str(shared)

    return meta


async def list_metadata_fields(dataset_id: str, api_key: str | None = None, base_url: str | None = None) -> list[dict]:
    """GET /datasets/{dataset_id}/metadata — return existing field definitions."""
    url = f"{_base_url(base_url)}/datasets/{dataset_id}/metadata"
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(url, headers=_headers(api_key))
        resp.raise_for_status()
        return resp.json().get("doc_metadata", [])


async def ensure_metadata_fields(dataset_id: str, api_key: str | None = None, base_url: str | None = None) -> dict[str, str]:
    """Ensure all required metadata fields exist in the knowledge base.

    Returns a mapping of field_name → field_id for later use.
    """
    existing = await list_metadata_fields(dataset_id, api_key, base_url)
    name_to_id: dict[str, str] = {f["name"]: f["id"] for f in existing}

    create_url = f"{_base_url(base_url)}/datasets/{dataset_id}/metadata"
    async with httpx.AsyncClient(timeout=30) as client:
        for field_def in DIFY_METADATA_FIELDS:
            if field_def["name"] not in name_to_id:
                resp = await client.post(
                    create_url,
                    headers=_headers(api_key),
                    json={"type": field_def["type"], "name": field_def["name"]},
                )
                resp.raise_for_status()
                data = resp.json()
                name_to_id[data["name"]] = data["id"]
                logger.info("Created Dify metadata field: %s (id=%s)", data["name"], data["id"])

    return name_to_id


async def upload_document(
    dataset_id: str,
    file_path: str,
    *,
    upload_name: str | None = None,
    indexing_technique: str = "high_quality",
    doc_form: str = "text_model",
    doc_language: str = "Chinese",
    api_key: str | None = None,
    base_url: str | None = None,
) -> dict:
    """Upload a file to Dify knowledge base.

    Args:
        dataset_id: Knowledge base ID.
        file_path: Local path to the file.
        upload_name: Override the filename sent to Dify (useful when full/redacted
                     share the same local filename but need distinct names in Dify).

    Returns {"document_id": str, "batch": str, "name": str}.
    """
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"File not found: {file_path}")

    dify_filename = upload_name or path.name
    url = f"{_base_url(base_url)}/datasets/{dataset_id}/document/create-by-file"

    data_payload = json.dumps({
        "indexing_technique": indexing_technique,
        "doc_form": doc_form,
        "doc_language": doc_language,
        "process_rule": {"mode": "automatic"},
    })

    async with httpx.AsyncClient(timeout=60) as client:
        with open(path, "rb") as f:
            resp = await client.post(
                url,
                headers=_headers(api_key),
                files={"file": (dify_filename, f, "text/markdown")},
                data={"data": data_payload},
            )
        resp.raise_for_status()
        result = resp.json()

    doc_info = result.get("document", {})
    batch_id = result.get("batch", "")
    document_id = doc_info.get("id", "")
    name = doc_info.get("name", dify_filename)

    logger.info("Uploaded to Dify: %s (doc_id=%s, batch=%s)", name, document_id, batch_id)
    return {"document_id": document_id, "batch": batch_id, "name": name}


async def wait_for_indexing(
    dataset_id: str,
    batch_id: str,
    *,
    poll_interval: float = _POLL_INTERVAL,
    max_attempts: int = _POLL_MAX_ATTEMPTS,
    api_key: str | None = None,
    base_url: str | None = None,
) -> dict:
    """Poll indexing status until completed or error.

    Returns the final status entry for the first document in the batch.
    Raises RuntimeError on timeout or indexing error.
    """
    url = f"{_base_url(base_url)}/datasets/{dataset_id}/documents/{batch_id}/indexing-status"

    async with httpx.AsyncClient(timeout=30) as client:
        for attempt in range(1, max_attempts + 1):
            resp = await client.get(url, headers=_headers(api_key))
            resp.raise_for_status()
            entries = resp.json().get("data", [])

            if not entries:
                await asyncio.sleep(poll_interval)
                continue

            entry = entries[0]
            status = entry.get("indexing_status", "")

            if status == "completed":
                logger.info("Dify indexing completed (batch=%s, segments=%s)",
                            batch_id, entry.get("total_segments"))
                return entry

            if status == "error":
                error_msg = entry.get("error") or "Unknown indexing error"
                raise RuntimeError(f"Dify indexing failed: {error_msg}")

            logger.debug("Dify indexing status: %s (attempt %d/%d)", status, attempt, max_attempts)
            await asyncio.sleep(poll_interval)

    raise RuntimeError(f"Dify indexing timed out after {max_attempts * poll_interval:.0f}s")


async def set_document_metadata(
    dataset_id: str,
    document_id: str,
    metadata_values: dict[str, str],
    field_name_to_id: dict[str, str],
    api_key: str | None = None,
    base_url: str | None = None,
) -> None:
    """Set metadata values on a single Dify document.

    Args:
        dataset_id: Knowledge base ID.
        document_id: Dify document ID.
        metadata_values: {field_name: value} pairs.
        field_name_to_id: mapping from field name to Dify field ID.
    """
    metadata_list = []
    for name, value in metadata_values.items():
        field_id = field_name_to_id.get(name)
        if field_id is None:
            logger.warning("Metadata field '%s' not found in Dify, skipping", name)
            continue
        metadata_list.append({"id": field_id, "name": name, "value": value})

    if not metadata_list:
        logger.warning("No metadata to set for document %s", document_id)
        return

    url = f"{_base_url()}/datasets/{dataset_id}/documents/metadata"
    payload = {
        "operation_data": [
            {
                "document_id": document_id,
                "metadata_list": metadata_list,
                "partial_update": True,
            }
        ]
    }

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(url, headers=_headers(), json=payload)
        resp.raise_for_status()

    logger.info("Set %d metadata fields on document %s", len(metadata_list), document_id)


async def upload_with_metadata(
    file_path: str,
    index_meta: dict,
    dataset_id: str | None = None,
    *,
    upload_name: str | None = None,
    api_key: str | None = None,
    base_url: str | None = None,
) -> dict:
    """Full pipeline: upload file → wait for indexing → set metadata.

    Args:
        file_path: Path to the MD file.
        index_meta: The dify_metadata dict from index_generator (full or redacted).
        dataset_id: Override the default dataset. Falls back to settings.dify_dataset_id.
        upload_name: Override filename in Dify (e.g. "报告_redacted.md").
        api_key: Override the default Dify API key.
        base_url: Override the default Dify base URL.

    Returns:
        {"document_id": str, "batch": str, "name": str, "metadata": dict}
    """
    ds_id = dataset_id or settings.dify_dataset_id
    if not ds_id:
        raise ValueError("dify_dataset_id is not configured")

    field_map = await ensure_metadata_fields(ds_id, api_key, base_url)
    upload_result = await upload_document(ds_id, file_path, upload_name=upload_name, api_key=api_key, base_url=base_url)
    await wait_for_indexing(ds_id, upload_result["batch"], api_key=api_key, base_url=base_url)

    metadata_values = to_dify_metadata(index_meta)
    if upload_name:
        metadata_values["knowlege_db_name"] = upload_name
    await set_document_metadata(ds_id, upload_result["document_id"], metadata_values, field_map, api_key, base_url)

    return {**upload_result, "metadata": metadata_values}
