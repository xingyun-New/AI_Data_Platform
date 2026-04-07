"""AI-driven document desensitization using department rules."""

import logging

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.core.ai_service import call_ai_json
from app.core.file_manager import read_file, write_redacted
from app.models.rule import DesensitizeRule

logger = logging.getLogger(__name__)

PROMPT_FILE = "desensitize.txt"


def _build_rules_context(db: Session, department: str, section: str = "") -> str:
    """Load active rules matching this department/section and format as system prompt.

    Matching strategy (any match counts):
      - rule.department equals department or section (exact)
      - rule.department contains department or section (e.g. "CH70/CH73" contains "CH70")
    """
    _NO_DEPT_RULES = (
        "## 当前部门脱敏规则\n\n"
        "（该部门没有配置专属脱敏规则）\n\n"
        '请按照上方"脱敏默认规则"对文档进行脱敏处理。'
    )

    codes = [c for c in (department, section) if c]
    if not codes:
        return _NO_DEPT_RULES

    conditions = []
    for code in codes:
        conditions.append(DesensitizeRule.department == code)
        conditions.append(DesensitizeRule.department.contains(code))

    rules: list[DesensitizeRule] = (
        db.query(DesensitizeRule)
        .filter(
            DesensitizeRule.is_active.is_(True),
            or_(*conditions),
        )
        .order_by(DesensitizeRule.priority.desc())
        .all()
    )
    if not rules:
        return _NO_DEPT_RULES

    lines = [
        "## 当前部门脱敏规则",
        "",
        "请严格按照以下规则进行脱敏，规则未覆盖的内容一律不得修改：",
        "",
    ]
    for r in rules:
        lines.append(f"- 【{r.rule_type}】{r.rule_name}：{r.rule_description}")
    lines.append("")
    lines.append("以上就是全部规则。规则列表之外的任何信息（包括但不限于金额、姓名、公司名、百分比等）都必须保留原样。")
    return "\n".join(lines)


async def desensitize_file(
    raw_path: str,
    department: str,
    db: Session,
    section: str = "",
) -> dict:
    """Run AI desensitization on a single Markdown file.

    Returns:
        {
            "redacted_path": str,
            "report": { "total_changes": int, "changes": [...] },
        }
    """
    from pathlib import Path

    content = read_file(Path(raw_path))
    rules_context = _build_rules_context(db, department, section)

    result = await call_ai_json(
        PROMPT_FILE,
        content,
        extra_system=rules_context,
    )

    redacted_content = result.get("redacted_content", content)
    report = result.get("report", {"total_changes": 0, "changes": []})

    filename = Path(raw_path).name
    out_path = write_redacted(filename, redacted_content)

    logger.info("Desensitized %s -> %s  changes=%d", raw_path, out_path, report.get("total_changes", 0))
    return {
        "redacted_path": str(out_path),
        "report": report,
    }
