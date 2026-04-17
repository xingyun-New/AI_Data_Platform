"""AI-driven document index generation with department-level sharing rules.

The generated index serves as the source of truth for Dify knowledge-base
metadata (shared_departments, access_level, doc_category, etc.).
"""

import asyncio
import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.core.ai_service import call_ai_json
from app.core.file_manager import read_file, read_redacted, write_index
from app.models.index_rule import IndexRule

logger = logging.getLogger(__name__)

PROMPT_FILE = "index_generate.txt"
GRAPH_PROMPT_FILE = "graph_extract.txt"


def _build_index_rules_context(db: Session, department: str, section: str = "") -> str:
    """Load active index rules for *department*/*section* and format as extra system prompt.

    Matching strategy mirrors desensitizer._build_rules_context:
      - rule.department == department or section (exact)
      - rule.department contains department or section (fuzzy)
    """
    _NO_RULES = (
        "## 当前部门索引规则\n\n"
        "（该部门没有配置专属索引规则）\n\n"
        "请根据文档内容自行判断 shared_departments 和 suggested_access_level。"
    )

    codes = [c for c in (department, section) if c]
    if not codes:
        return _NO_RULES

    conditions = []
    for code in codes:
        conditions.append(IndexRule.department == code)
        conditions.append(IndexRule.department.contains(code))

    rules: list[IndexRule] = (
        db.query(IndexRule)
        .filter(
            IndexRule.is_active.is_(True),
            or_(*conditions),
        )
        .order_by(IndexRule.priority.desc())
        .all()
    )
    if not rules:
        return _NO_RULES

    lines = [
        "## 当前部门索引规则",
        "",
        f"文档所属部门：{department}" + (f"（课室：{section}）" if section else ""),
        "",
        "请严格参考以下规则来决定 shared_departments 和 suggested_access_level：",
        "",
    ]

    for r in rules:
        target = ""
        if r.target_departments:
            try:
                depts = json.loads(r.target_departments)
                if depts:
                    target = f" → 目标部门: {', '.join(depts)}"
            except (json.JSONDecodeError, TypeError):
                pass
        lines.append(f"- 【{r.rule_type}】{r.rule_name}：{r.rule_description}{target}")

    lines.append("")
    lines.append(
        "以上规则优先级从高到低排列。"
        "当文档符合多条 share 规则时，合并所有目标部门。"
        "当规则与 AI 判断冲突时，以规则为准。"
    )
    return "\n".join(lines)


def _merge_shared_departments(ai_suggestion: list[str], rules: list[str]) -> list[str]:
    """Merge AI-suggested departments with rule-mandated departments, deduplicated."""
    seen: set[str] = set()
    merged: list[str] = []
    for dept in rules + ai_suggestion:
        if dept and dept not in seen:
            seen.add(dept)
            merged.append(dept)
    return merged


def _extract_rule_target_departments(db: Session, department: str, section: str = "") -> list[str]:
    """Extract all target departments from active share rules for the department."""
    codes = [c for c in (department, section) if c]
    if not codes:
        return []

    conditions = []
    for code in codes:
        conditions.append(IndexRule.department == code)
        conditions.append(IndexRule.department.contains(code))

    rules: list[IndexRule] = (
        db.query(IndexRule)
        .filter(
            IndexRule.is_active.is_(True),
            IndexRule.rule_type == "share",
            or_(*conditions),
        )
        .all()
    )

    all_depts: list[str] = []
    for r in rules:
        if r.target_departments:
            try:
                depts = json.loads(r.target_departments)
                all_depts.extend(depts)
            except (json.JSONDecodeError, TypeError):
                pass
    return list(dict.fromkeys(all_depts))


async def generate_index(
    raw_path: str,
    department: str,
    db: Session | None = None,
    *,
    section: str = "",
    creator: str = "",
) -> dict:
    """Generate index JSON for both full and redacted versions.

    The output is designed as the single source of truth for Dify knowledge-base
    metadata: shared_departments, access_level, doc_category, etc.

    Returns the full index dict that is also written to disk.
    """
    filename = Path(raw_path).name
    stem = Path(raw_path).stem

    rules_context = ""
    rule_target_depts: list[str] = []
    if db is not None:
        rules_context = _build_index_rules_context(db, department, section)
        rule_target_depts = _extract_rule_target_departments(db, department, section)

    full_content = read_file(Path(raw_path))
    redacted_content = read_redacted(filename)

    async def _safe_graph_extract(content: str) -> dict:
        """Extract KG entities; degrade gracefully on failure so indexing still succeeds."""
        try:
            return await call_ai_json(
                GRAPH_PROMPT_FILE, content, temperature=0.1, max_tokens=4096,
            )
        except Exception as exc:
            logger.warning("Graph extraction failed for %s: %s", filename, exc)
            return {"entities": [], "document_relations": []}

    if redacted_content:
        full_index, redacted_index, graph_data = await asyncio.gather(
            call_ai_json(PROMPT_FILE, full_content, extra_system=rules_context),
            call_ai_json(PROMPT_FILE, redacted_content, extra_system=rules_context),
            _safe_graph_extract(full_content),
        )
    else:
        full_index, graph_data = await asyncio.gather(
            call_ai_json(PROMPT_FILE, full_content, extra_system=rules_context),
            _safe_graph_extract(full_content),
        )
        redacted_index = full_index.copy()

    ai_shared = full_index.get("shared_departments", [])
    merged_shared = _merge_shared_departments(ai_shared, rule_target_depts)

    # full version: shared_departments = own department + rule/AI departments (department-level only)
    full_shared = _merge_shared_departments(merged_shared, [department])

    full_access = full_index.get("suggested_access_level", "internal")
    redacted_access = "public" if redacted_content else full_access

    index_doc = {
        "source_file": filename,
        "department": department,
        "section": section,
        "creator": creator,
        "shared_departments": merged_shared,
        "shared_departments_source": {
            "from_rules": rule_target_depts,
            "from_ai": ai_shared,
        },
        "versions": {
            "full": {
                **full_index,
                "access_level": full_access if full_access != "public" else "confidential",
                "shared_departments": merged_shared,
            },
            "redacted": {
                **redacted_index,
                "access_level": redacted_access,
                "shared_departments": ["ALL"],
            },
        },
        "dify_metadata": {
            "full": {
                "type": "knowledge_document",
                "filename": filename,
                "domain": department.lower(),
                "access_level": full_access if full_access != "public" else "confidential",
                "department": department,
                "section": section,
                "shared_departments": merged_shared,
                "creator": creator,
                "doc_category": full_index.get("doc_category", "other"),
                "is_redacted": False,
                "original_doc_id": None,
            },
            "redacted": {
                "type": "knowledge_document",
                "filename": filename,
                "domain": department.lower(),
                "access_level": redacted_access,
                "department": department,
                "section": section,
                "shared_departments": ["ALL"],
                "creator": creator,
                "doc_category": redacted_index.get("doc_category", "other"),
                "is_redacted": True,
                "original_doc_id": stem,
            },
        },
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }

    if isinstance(graph_data, dict) and (graph_data.get("entities") or graph_data.get("document_relations")):
        index_doc["knowledge_graph"] = {
            "entities": graph_data.get("entities") or [],
            "document_relations": graph_data.get("document_relations") or [],
        }

    write_index(stem, json.dumps(index_doc, ensure_ascii=False, indent=2))
    logger.info(
        "Generated index for %s (dept=%s, shared=%s, entities=%d)",
        filename, department, merged_shared,
        len(index_doc.get("knowledge_graph", {}).get("entities", [])),
    )
    return index_doc
