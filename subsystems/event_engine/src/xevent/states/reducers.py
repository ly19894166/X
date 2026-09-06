"""离散规则：每一维只接收本维证据，热度/价格不得进入事实判断。"""
from typing import get_args

from ..contracts.models import FactState
from .contracts import NarrativeState, PricingState

FACT_ALLOWED = {
    "UNVERIFIED": set(get_args(FactState)),
    "PLAUSIBLE": {"PLAUSIBLE", "PARTIALLY_CONFIRMED", "INDEPENDENTLY_CONFIRMED", "OFFICIALLY_CONFIRMED", "IMPLEMENTED", "CONTRADICTED", "INVALIDATED"},
    "PARTIALLY_CONFIRMED": {"PARTIALLY_CONFIRMED", "INDEPENDENTLY_CONFIRMED", "OFFICIALLY_CONFIRMED", "IMPLEMENTED", "CONTRADICTED", "INVALIDATED"},
    "INDEPENDENTLY_CONFIRMED": {"INDEPENDENTLY_CONFIRMED", "OFFICIALLY_CONFIRMED", "IMPLEMENTED", "CONTRADICTED", "INVALIDATED"},
    "OFFICIALLY_CONFIRMED": {"OFFICIALLY_CONFIRMED", "IMPLEMENTED", "CONTRADICTED", "INVALIDATED"},
    "IMPLEMENTED": {"IMPLEMENTED", "CONTRADICTED", "INVALIDATED"},
    "CONTRADICTED": set(get_args(FactState)),
    "INVALIDATED": set(get_args(FactState)),
}
FACT_FORBIDDEN = {state: set(get_args(FactState)) - targets for state, targets in FACT_ALLOWED.items()}
ALLOWED = {"FACT": FACT_ALLOWED,
           "NARRATIVE": {state: set(get_args(NarrativeState)) for state in get_args(NarrativeState)},
           "PRICING": {state: set(get_args(PricingState)) for state in get_args(PricingState)}}
FORBIDDEN = {dimension: {state: set(table) - targets for state, targets in table.items()}
             for dimension, table in ALLOWED.items()}

# 状态对通过后仍须满足本维证据门槛；反证解除不是无条件允许。
GUARDS_ZH = {
    "FACT": "事实升级需对应主张证据；实施需新执行材料；反证解除需新材料显式复核；时间/传播/价格不可代替证据",
    "NARRATIVE": "跳转/衰减须有截至时点的来源去重、窗口、画像及传播速度；粉丝数单独无效",
    "PRICING": "已知状态须有范围明确的价格fixture；缺数据只能UNKNOWN；混合观察HOLD",
}


def check_transition(dimension, previous, new):
    if dimension not in ALLOWED or previous not in ALLOWED[dimension] or new not in ALLOWED[dimension][previous]:
        raise ValueError("TRANSITION_FORBIDDEN：非法状态转换，拒绝本事件写入")


def fact_reduce(previous, assessments, independent_sources, *, new_r5=False):
    resolved = {(ref.object_id, ref.version) for a in assessments if a.kind == "RESOLUTION" for ref in a.resolves_refs}
    negative = [a for a in assessments if a.kind in ("COUNTEREVIDENCE", "OFFICIAL_DENIAL", "INVALIDATION")
                and (a.object_id, a.version) not in resolved]
    if negative or new_r5:
        invalid = previous == "INVALIDATED" or any(a.kind == "INVALIDATION" for a in negative)
        return ("INVALIDATED" if invalid else "CONTRADICTED", "反证_核心证伪" if invalid else "反证_矛盾尚未解除", "APPLIED")
    if previous in ("CONTRADICTED", "INVALIDATED") and not resolved:
        return previous, "反证_等待新证据复核", "HOLD"
    # 解除反证也不能复用反证出现前的利好；必须有后来支持证据。
    resolved_times = [a.available_at for a in assessments if (a.object_id, a.version) in resolved]
    kinds = {a.kind for a in assessments if not resolved_times or a.available_at > max(resolved_times)}
    if previous == "INDEPENDENTLY_CONFIRMED" and (independent_sources is None or independent_sources < 2) and not kinds & {"OFFICIAL_CONFIRMATION", "IMPLEMENTATION"}:
        return "CONTRADICTED", "反证_独立来源确认条件失效", "HOLD"
    if "IMPLEMENTATION" in kinds:
        candidate = "IMPLEMENTED"
    elif "OFFICIAL_CONFIRMATION" in kinds:
        candidate = "OFFICIALLY_CONFIRMED"
    elif independent_sources is not None and independent_sources >= 2 and "SUPPORT" in kinds:
        candidate = "INDEPENDENTLY_CONFIRMED"
    elif "PARTIAL" in kinds:
        candidate = "PARTIALLY_CONFIRMED"
    elif kinds & {"PLAUSIBLE", "SUPPORT"}:
        candidate = "PLAUSIBLE"
    else:
        return previous, "事实_缺合格支持证据", "UNCHANGED"
    order = list(get_args(FactState))[:6]
    if previous in order and order.index(candidate) < order.index(previous):
        return previous, "事实_无反证不因时间降级", "UNCHANGED"
    return candidate, "事实_对应主张证据通过", "APPLIED"


def narrative_reduce(previous, summary, rules):
    count = len(summary["source_ids"])
    old = summary["previous_source_count"]
    if count == 0:
        state = "DECAY" if previous not in ("UNKNOWN", "QUIET") else "QUIET"
    elif summary["delete_count"] >= count and summary["delete_count"] > 0:
        state = "DECAY"
    elif count >= rules.crowded_min_sources:
        state = "CROWDED"
    elif count >= rules.mainstream_min_sources and "S1" in summary["source_tiers"]:
        state = "MAINSTREAM"
    elif count >= rules.rapid_min_sources and count >= max(1, old) * rules.acceleration_factor:
        state = "RAPID_DIFFUSION"
    elif old > 0 and count * rules.acceleration_factor < old:
        state = "DECAY"
    elif count >= 2:
        state = "EARLY_DIFFUSION"
    elif summary["professional_sources"]:
        state = "PROFESSIONAL_DISCOVERY"
    else:
        state = "QUIET"
    return state, "叙事_窗口去重传播规则", "APPLIED" if state != previous else "UNCHANGED"


def pricing_reduce(previous, observations):
    values = {p.observation for p in observations}
    if not values or "UNKNOWN" in values:
        return "UNKNOWN", "价格_缺观察不等于无反应", "HOLD"
    if len(values) > 1:
        return "UNKNOWN", "价格_不同证券观察分歧保留明细", "HOLD"
    value = next(iter(values))
    return value, "价格_仅给定fixture范围摘要", "APPLIED" if value != previous else "UNCHANGED"
