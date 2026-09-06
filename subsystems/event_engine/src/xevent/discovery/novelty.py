"""规则只使用可追溯的结构字段差异；不能确定时保存证据并 HOLD。"""
from ..ledger.contracts import RawObservation

POLICY_VERSION = "NOVELTY_RULES_V0.1"


def classify(current: RawObservation, previous: RawObservation | None, *, duplicate=False, diffusion=False):
    if duplicate:
        return "R0", ["EXACT_DUPLICATE"]
    if previous is not None and current.structured_basis == previous.structured_basis == "SOURCE_STRUCTURED":
        changed = {k for k, v in current.structured_fields.items() if previous.structured_fields.get(k) != v}
        if "retracted" in changed and current.structured_fields["retracted"] == "true" and current.is_first_hand:
            return "R5", ["SOURCE_STRUCTURED_RETRACTION"]
        if "legal_status" in changed:
            return "R4", ["SOURCE_STRUCTURED_LEGAL_STATUS_CHANGE"]
        if changed & {"amount", "effective_date"}:
            return "R3", ["SOURCE_STRUCTURED_MATERIAL_TERM_CHANGE"]
        if changed == {"detail"} and current.structured_fields.keys() == previous.structured_fields.keys():
            return "R2", ["SOURCE_STRUCTURED_DETAIL_ONLY"]
    if diffusion and previous is None:
        return "R1", ["PROVEN_ORIGIN_DIFFUSION"]
    return "UNDETERMINED", ["MATERIALITY_UNDETERMINED"]
