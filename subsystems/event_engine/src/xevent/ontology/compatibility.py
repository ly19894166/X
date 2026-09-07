"""V0.1 A1显式投影；只转换命名/缺失UNKNOWN，不改时间、事实或历史数据库。"""
from .contracts import ImpactSpec

LEGACY_POLICY = "X_ONTOLOGY_RULES_V0.1"
POLICY = "X_ONTOLOGY_RULES_V0.1_A1"


def normalize_impact_input(data):
    """旧输入边界：歧义双字段拒绝；输出只含唯一正式命名。"""
    result = dict(data)
    if "inference_type" in result:
        if "observation_kind" in result:
            raise ValueError("COMPAT_DUPLICATE：不得同时提交inference_type和observation_kind")
        result["observation_kind"] = result.pop("inference_type")
    if result.get("variable_type") == "OUTPUT_PRICE":
        result["variable_type"] = "PRICE"
    return ImpactSpec.model_validate(result)


def project_legacy_record(kind, payload, object_id):
    """仅已知82728ab策略记录的读取投影；原payload/hash/回执不变。"""
    if payload.get("policy_version") != LEGACY_POLICY:
        return payload
    result = dict(payload)
    if kind == "ImpactVariable":
        result.setdefault("impact_id", object_id)
        for field in ("scope", "magnitude_band", "start_horizon", "persistence_band"):
            result.setdefault(field, "UNKNOWN")
    if kind in ("IndustryImpactRule", "IndustryImpactCandidate") and result.get("impact_direction") == "UNCERTAIN":
        result["impact_direction"] = "UNKNOWN"
    return result


def combine_impact_directions(values):
    """同一目标的实质正负并存为MIXED；未知绝不当中性。保留各原路径。"""
    directions = set(values)
    if not directions <= {"POSITIVE", "NEGATIVE", "MIXED", "NEUTRAL", "UNKNOWN"}:
        raise ValueError("IMPACT_DIRECTION：未知内部方向，UNCERTAIN不是合法成员")
    if "MIXED" in directions or {"POSITIVE", "NEGATIVE"} <= directions:
        return "MIXED"
    if not directions or "UNKNOWN" in directions:
        return "UNKNOWN"
    if "POSITIVE" in directions:
        return "POSITIVE"
    if "NEGATIVE" in directions:
        return "NEGATIVE"
    return "NEUTRAL"
