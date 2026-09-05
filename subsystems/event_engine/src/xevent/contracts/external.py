"""仅规范化三个外部分类字段；不改变内部状态或证据质量。"""
from typing import get_args

from .models import EvidenceType, EventType, StatementType

EXTERNAL_TYPES = {
    "statement_type": get_args(StatementType),
    "evidence_type": get_args(EvidenceType),
    "event_type": get_args(EventType),
}


def normalize_external(record: dict, field: str) -> dict:
    """返回新字典，调用者仍须交给 Pydantic 和版本引用校验。"""
    allowed = EXTERNAL_TYPES[field]
    result = dict(record)
    value = result.get(field)
    if value is None or value == "":
        result[field] = "UNKNOWN"
        result.setdefault("raw_type", None)
        result["classification_missing_reason"] = "来源未提供分类"
    elif isinstance(value, str) and value not in allowed:
        if result.get("raw_type") not in (None, value):
            raise ValueError("EXTERNAL_RAW_CONFLICT：原始分类冲突，不能覆盖")
        result[field] = "OTHER"
        result["raw_type"] = value
    elif isinstance(value, str) and value not in ("UNKNOWN", "OTHER"):
        if result.get("raw_type") not in (None, value):
            raise ValueError("EXTERNAL_RAW_CONFLICT：原始分类冲突，不能覆盖")
        result["raw_type"] = value
    return result
