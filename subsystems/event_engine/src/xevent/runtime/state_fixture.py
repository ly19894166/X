"""仅执行虚构时间线；无网络、真实行情或研究模型。"""
import json
from datetime import timedelta

from ..contracts import Source
from ..contracts.common import TypeAdapter, UTCDateTime, VersionRef
from ..ledger.contracts import EventSeed, RawObservation
from ..ledger.store import Ledger, ref
from ..states.engine import StateEngine


def run_fixture(path, db):
    if db.exists():
        raise ValueError("FIXTURE_DB：演示仅使用新的独立数据库，避免把虚构时钟混入已有研究")
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    base = json.loads((path.parent / data["base_fixture"]).read_text(encoding="utf-8-sig"))
    class FixtureClock:
        value = TypeAdapter(UTCDateTime).validate_python(data["steps"][0]["at"]) - timedelta(minutes=1)
        def __call__(self):
            self.value += timedelta(milliseconds=1)
            return self.value
    clock = FixtureClock()
    ledger = Ledger(db, clock=clock)
    try:
        source = ledger.register_source(Source.model_validate({**base["sources"][0], "identity_status":"VERIFIED"}))
        seed = EventSeed(event_id="PHASE3_FIXTURE", title_zh="虚构事件：传闻、确认、否认",
                         dna={**base["event_versions"][0]["dna"], "actor_refs":[]})
        engine = StateEngine(ledger)
        policy = engine.policy()
        result = []
        for n, step in enumerate(data["steps"]):
            clock.value = TypeAdapter(UTCDateTime).validate_python(step["at"])
            evidence = ledger.ingest(RawObservation(source_ref=ref(source), locator=f"fixture:phase3:{n}",
                raw=step["text"].encode(), first_seen_at=clock(), collected_at=clock(), content_version="1",
                claim_kind=step["claim_kind"], is_first_hand=bool(step.get("assessment"))), seed)
            event = ledger.history(as_of=clock(), kind="EventVersion")[-1]
            assessments = []
            if step.get("assessment"):
                a = engine.assess(VersionRef(**ref(event)), VersionRef(**ref(evidence)), assessment_key=f"fixture:{n}",
                    kind=step["assessment"], quoted_span=step["text"], reviewed_by="虚构fixture",
                    interpretation_zh="样例标注对应主张，不声称自动验证语义", authority_scope_zh="虚构负责机构")
                assessments.append(VersionRef(**ref(a)))
            state = engine.evaluate(VersionRef(**ref(event)), VersionRef(**ref(policy)), request_key=f"fixture:{n}",
                                    as_of=clock(), assessment_refs=assessments)
            if state.fact_state != step["expected_fact"]:
                raise ValueError("FIXTURE_STATE：状态不符合场景验收")
            result.append({"时间":step["at"],"事实":state.fact_state,"叙事":state.narrative_state,"价格":state.pricing_state})
        past = ledger.replay(data["replay_as_of"])
        if past != ledger.replay(data["replay_as_of"]):
            raise ValueError("REPLAY_MISMATCH：两次回放不一致")
        transitions = ledger.history(as_of=data["replay_as_of"],kind="StateTransition")
        if any(t.new_state != "UNVERIFIED" for t in transitions if t.dimension == "FACT"):
            raise ValueError("PIT_FIXTURE：10:15不能看到后来确认或否认")
        return {"声明":data["description_zh"],"时间线":result,"旧时点回放":"10:15仅传闻；两次回放一致","历史版本数":len(past)}
    finally:
        ledger.close()
