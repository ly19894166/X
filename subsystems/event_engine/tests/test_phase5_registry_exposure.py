from datetime import timedelta
from pathlib import Path
import json
import pytest
from pydantic import ValidationError
from xevent.contracts.common import TypeAdapter, UTCDateTime, VersionRef
from xevent.ledger.store import Ledger, ref
from xevent.registry.contracts import CompanySpec, SecuritySpec, RelationSpec, SCHEMAS as REGISTRY_SCHEMAS
from xevent.registry.engine import Registry
from xevent.exposures.contracts import DisclosureSpec, ExposureSpec, MetricSpec, SCHEMAS as EXPOSURE_SCHEMAS
from xevent.exposures.engine import ExposureMaster
from xevent.exposures.fixture import seed_fixture, add_security, security, disclose, exposure, metric, vr, run_fixture

CONFIG = Path(__file__).parents[1]/"configs"


@pytest.fixture
def w(tmp_path):
    world=seed_fixture(tmp_path/"p5.sqlite",CONFIG)
    yield world
    world["ledger"].close()


def at(w,stamp):
    w["clock"].value=TypeAdapter(UTCDateTime).validate_python(stamp)


def snapshot(w,name="snapshot",stamp=None):
    return w["registry"].snapshot(name,as_of=stamp or w["clock"]())


@pytest.fixture
def disclosed(w):
    add_security(w)
    at(w,"2026-03-28T00:00:00Z")
    d=disclose(w)
    x=w["master"].exposure(1,exposure(w,d))
    return w,d,x


def test_company_security_ah_separation(disclosed):
    w,d,x=disclosed
    h=add_security(w,"SEC_H",exchange="HKEX",security_code="00001",ticker="00001.HK",security_type="H_SHARE",board="HK",currency="HKD")
    assert h.company_ref==vr(w["company"])
    s=snapshot(w)
    assert [r.object_id for r in s.included_security_refs]==["SEC_A"]
    assert [r.object_id for r in s.excluded_security_refs]==["SEC_H"]
    assert len(w["master"].exposure_view(as_of=w["clock"]()))==1
    assert x.company_ref==h.company_ref
    assert "security_ref" not in type(x).model_fields


@pytest.mark.parametrize("board,exchange,code",[
    ("SH_MAIN","SSE","600001"),("SZ_MAIN","SZSE","000001"),("CHINEXT","SZSE","300001"),
    ("STAR","SSE","688001"),("BEIJING","BSE","920001")])
def test_all_boards_in_research(w,board,exchange,code):
    add_security(w,board=board,exchange=exchange,security_code=code,ticker=code+"."+exchange)
    assert len(snapshot(w).included_security_refs)==1


@pytest.mark.parametrize("st,suspension",[("ST","TRADING"),("*ST","TRADING"),("NORMAL","SUSPENDED"),("UNKNOWN","UNKNOWN")])
def test_st_suspension_are_not_execution_filters(w,st,suspension):
    add_security(w,st_status=st,suspension_status=suspension)
    assert len(snapshot(w).included_security_refs)==1


def test_execution_permissions_not_a_research_input(w):
    s=add_security(w,board="STAR",exchange="SSE",security_code="688001")
    before=snapshot(w,"before",w["clock"]())
    with pytest.raises(TypeError):
        w["registry"].snapshot("bad",as_of=w["clock"](),account_permissions=[])
    assert before.included_security_refs==(vr(s),)
    with pytest.raises(ValidationError):
        security(w,account_can_trade=False)


@pytest.mark.parametrize("code",[1,"1","00001","１２３４５６",None])
def test_bad_a_code_rejected(w,code):
    with pytest.raises(ValidationError):
        security(w,security_code=code)


def test_leading_zero_roundtrip(w):
    s=add_security(w)
    assert s.security_code=="000001"
    assert type(s).model_validate_json(s.model_dump_json()).security_code=="000001"


@pytest.mark.pit
def test_rename_code_st_keep_company_and_old_asof(w):
    old=add_security(w)
    cutoff=w["clock"]()
    before=snapshot(w,"old",cutoff)
    w["clock"].advance(days=2)
    new=w["registry"].security(2,security(w,security_name="虚构证券新名",security_code="000002",
        ticker="000002.SZ",st_status="*ST",effective_from=w["clock"]()))
    after=snapshot(w,"new")
    assert old.company_ref==new.company_ref==vr(w["company"])
    assert before.included_security_refs==(vr(old),)
    assert after.included_security_refs==(vr(new),)
    assert snapshot(w,"replayed",cutoff).included_security_refs==before.included_security_refs
    assert w["ledger"].get(old.object_id,old.version).security_name=="虚构证券旧名"


@pytest.mark.pit
def test_later_delisting_preserves_old_universe(w):
    old=add_security(w)
    cutoff=w["clock"]()
    at(w,"2026-02-02T00:00:00Z")
    new=w["registry"].security(2,security(w,listing_status="DELISTED",delisting_date="2026-02-01",
        effective_from="2026-02-01T00:00:00Z"))
    assert snapshot(w,"old",cutoff).included_security_refs==(vr(old),)
    now=snapshot(w,"new")
    assert now.excluded_security_refs==(vr(new),)
    assert now.decisions[0].reason_codes==("DELISTED_AT_AS_OF",)


@pytest.mark.pit
def test_later_listing_cannot_enter_before_listing(w):
    add_security(w,listing_date="2026-03-01")
    assert not snapshot(w,"pre").included_security_refs
    at(w,"2026-03-02T00:00:00Z")
    assert len(snapshot(w,"post").included_security_refs)==1


@pytest.mark.pit
def test_today_list_not_backfilled(w):
    cutoff=w["clock"]()
    w["clock"].advance(days=400)
    add_security(w)
    old=snapshot(w,"past",cutoff)
    assert not old.included_security_refs and not old.decisions
    assert old.coverage_status=="HOLD_HISTORICAL_UNIVERSE_COVERAGE"
    assert len(snapshot(w,"today").included_security_refs)==1


@pytest.mark.parametrize("identity",["UNKNOWN","HOLD","REVIEW_REQUIRED"])
def test_security_identity_isolates_one_candidate(w,identity):
    good=add_security(w)
    bad=add_security(w,"SEC_BAD",security_code="000003",identity_status=identity)
    s=snapshot(w)
    assert s.included_security_refs==(vr(good),)
    assert s.security_hold_refs==(vr(bad),)


@pytest.mark.pit
def test_company_identity_change_hold_does_not_backfill(w):
    good=add_security(w)
    cutoff=w["clock"]()
    spec=CompanySpec.model_validate({k:v for k,v in w["company"].model_dump().items() if k in CompanySpec.model_fields})
    changed={**spec.model_dump(),"company_identifier":"DIFFERENT_LEGAL_ENTITY"}
    with pytest.raises(ValueError,match="CONTINUITY_HOLD"):
        w["registry"].company(2,CompanySpec.model_validate(changed))
    w["registry"].company(2,CompanySpec.model_validate({**changed,"identity_status":"REVIEW_REQUIRED","continuity_status":"REVIEW_REQUIRED"}))
    assert snapshot(w,"new").security_hold_refs==(vr(good),)
    assert snapshot(w,"old",cutoff).included_security_refs==(vr(good),)


@pytest.mark.parametrize("role",["PRODUCER","INPUT_USER","MIXED","UNKNOWN"])
def test_business_roles_remain_distinct(disclosed,role):
    w,d,x=disclosed
    value=exposure(w,d,business_role=role)
    assert value.business_role==role


@pytest.mark.parametrize("kind",["REVENUE_SHARE","PROFIT_SHARE","CAPACITY_SHARE","GROSS_PROFIT_SHARE","CUSTOMER_SHARE"])
def test_share_types_preserved_not_converted(disclosed,kind):
    w,d,x=disclosed
    m=w["master"].metric(1,metric(x,metric_id=kind,metric_type=kind))
    assert m.metric_type==kind and m.value==0.3
    assert type(m).model_validate_json(m.model_dump_json())==m


@pytest.mark.parametrize("changes,reason",[
    ({"denominator":0.0},"DENOMINATOR_ZERO"),({"denominator":-100.0,"metric_type":"PROFIT_SHARE"},"DENOMINATOR_NEGATIVE"),
    ({"numerator":None},"NUMERATOR_MISSING"),({"denominator":None},"DENOMINATOR_MISSING"),
    ({"numerator":-30.0,"metric_type":"PROFIT_SHARE"},"NEGATIVE_COMPONENT_NOT_A_SHARE"),
    ({"numerator":130.0},"SHARE_OUT_OF_RANGE"),({"basis_verified_by":None},"RATIO_BASIS_UNVERIFIED")])
def test_invalid_ratio_not_zero(disclosed,changes,reason):
    w,d,x=disclosed
    m=w["master"].metric(1,metric(x,**changes))
    assert m.value is None and m.result_status in ("UNDEFINED","HOLD")
    assert reason in m.metric_reason_codes


def test_negative_profit_amount_is_not_invalid_ratio(disclosed):
    w,d,x=disclosed
    m=w["master"].metric(1,metric(x,metric_type="OPERATING_PROFIT",numerator=-30.0,denominator=None,
        calculation_method="REPORTED_AMOUNT",unit="CNY",denominator_basis=None))
    assert m.value==-30.0 and m.result_status=="DEFINED"


def test_metric_identity_cannot_change_revenue_into_profit(disclosed):
    w,d,x=disclosed
    w["master"].metric(1,metric(x))
    with pytest.raises(ValueError,match="METRIC_ID"):
        w["master"].metric(2,metric(x,metric_type="PROFIT_SHARE"))


@pytest.mark.parametrize("change",[
    {"evidence_type":"NEWS"},{"mapping_method":"KEYWORD_CANDIDATE"},
    {"industry_ref":None},{"reviewed_by":None},{"validation_status":"UNKNOWN"}])
def test_direct_requires_formal_mapping(disclosed,change):
    w,d,x=disclosed
    with pytest.raises(ValidationError):
        exposure(w,d,**change)


def test_news_supported_not_verified(w):
    at(w,"2026-03-28T00:00:00Z")
    d=disclose(w)
    data={k:v for k,v in d.model_dump().items() if k in DisclosureSpec.model_fields}
    data.update(disclosure_id="DISC_NEWS",disclosure_type="NEWS",issuer_identity_verified=False)
    news=w["master"].disclosure(1,DisclosureSpec.model_validate(data))
    supported=w["master"].exposure(1,exposure(w,news,exposure_type="SUPPORTED_DIRECT",validation_status="SUPPORTED"))
    assert supported.exposure_type=="SUPPORTED_DIRECT"
    with pytest.raises(ValidationError):
        exposure(w,news)


@pytest.mark.parametrize("change",[{"review_status":"UNREVIEWED"},{"issuer_identity_verified":False}])
def test_unreviewed_disclosure_not_direct(w,change):
    at(w,"2026-03-28T00:00:00Z")
    d=disclose(w)
    data={k:v for k,v in d.model_dump().items() if k in DisclosureSpec.model_fields}
    unreviewed=w["master"].disclosure(1,DisclosureSpec.model_validate({**data,**change,"disclosure_id":"UNREVIEWED"}))
    with pytest.raises(ValueError,match="DIRECT_PROOF"):
        w["master"].exposure(1,exposure(w,unreviewed))


def test_narrative_theme_cannot_be_industry(disclosed):
    w,d,x=disclosed
    # 固定引用存在却类型不符也拒绝；不能只靠字符串形状。
    with pytest.raises(ValueError,match="REGISTRY_REFERENCE"):
        w["master"].exposure(1,exposure(w,d,exposure_id="BAD_TYPE",industry_ref=vr(w["company"])))
    with pytest.raises(ValidationError,match="NARRATIVE_GATE"):
        exposure(w,d,narrative_theme_ref=dict(object_id="THEME_ROBOT",version=1))


def test_narrative_only_is_not_economic_coverage(w):
    add_security(w)
    at(w,"2026-03-28T00:00:00Z")
    d=disclose(w)
    spec=exposure(w,d,exposure_type="NARRATIVE_ASSOCIATION",industry_ref=None,validation_status="UNREVIEWED")
    w["master"].exposure(1,spec)
    report=w["master"].coverage("coverage",vr(snapshot(w)))
    assert report.company_with_exposure_n==1 and report.company_with_economic_exposure_n==0
    assert report.unknown_company_n==1 and report.verified_direct_company_n==0


def test_keyword_only_candidate(disclosed):
    w,d,x=disclosed
    candidate=exposure(w,d,exposure_id="KEYWORD",industry_ref=None,exposure_type="UNKNOWN",
        mapping_method="KEYWORD_CANDIDATE",validation_status="CANDIDATE_FOR_REVIEW")
    saved=w["master"].exposure(1,candidate)
    assert saved.exposure_type=="UNKNOWN"


@pytest.mark.pit
def test_annual_report_late_disclosure_A(disclosed):
    w,d,x=disclosed
    old="2026-01-15T00:00:00Z"
    assert x.reporting_period.end.isoformat()=="2025-12-31"
    assert w["master"].exposure_view(as_of=old)==[]
    assert w["master"].exposure_view(as_of="2026-03-29T00:00:00Z")==[x]
    assert d.first_seen_at.year==2026 and x.available_at>=d.available_at


@pytest.mark.pit
def test_restatement_same_period_and_metric_D(disclosed):
    w,d,x=disclosed
    old=w["master"].metric(1,metric(x))
    cutoff=w["clock"]()
    before=w["ledger"].replay(cutoff)
    at(w,"2026-04-10T00:00:00Z")
    corrected=disclose(w,2)
    new=w["master"].exposure(2,exposure(w,corrected))
    assert w["master"].metric_view(as_of=w["clock"]())==[]
    revised=w["master"].metric(2,metric(new,numerator=20.0))
    assert new.reporting_period==x.reporting_period
    assert w["master"].metric_view(as_of=cutoff)==[old]
    assert w["master"].metric_view(as_of=w["clock"]())==[revised]
    assert revised.value==0.2
    assert w["master"].exposure_view(as_of=cutoff)==[x]
    assert w["ledger"].replay(cutoff)==before


@pytest.mark.pit
def test_disclosure_times_cannot_be_backdated(disclosed):
    w,d,x=disclosed
    fields={k:v for k,v in d.model_dump().items() if k in DisclosureSpec.model_fields}
    with pytest.raises(ValueError,match="FIRST_SEEN"):
        w["master"].disclosure(1,DisclosureSpec.model_validate({**fields,"disclosure_id":"BAD","first_seen_at":"2025-12-31T00:00:00Z"}))


def test_coverage_counts_missing_without_filling(w):
    add_security(w)
    fields={k:v for k,v in w["company"].model_dump().items() if k in CompanySpec.model_fields}
    other=w["registry"].company(1,CompanySpec.model_validate({**fields,"company_id":"CO_B","company_identifier":"LEGAL_B"}))
    add_security(w,"SEC_B",company_ref=vr(other),security_code="000002")
    at(w,"2026-03-28T00:00:00Z")
    d=disclose(w)
    w["master"].exposure(1,exposure(w,d))
    report=w["master"].coverage("coverage",vr(snapshot(w)))
    assert report.research_security_n==2 and report.identified_company_n==2
    assert report.company_security_mapping_n==2
    assert report.verified_direct_company_n==1 and report.unknown_company_n==1
    assert report.company_with_exposure_n==1
    assert report.rows[1].missing_reason_codes==("EXPOSURE_MISSING","ECONOMIC_EXPOSURE_UNKNOWN")
    assert len(w["master"].exposure_view(as_of=w["clock"]()))==1


@pytest.mark.pit
def test_coverage_old_asof_does_not_gain_later_exposure(w):
    add_security(w)
    old=snapshot(w)
    at(w,"2026-03-28T00:00:00Z")
    d=disclose(w)
    w["master"].exposure(1,exposure(w,d))
    report=w["master"].coverage("old_coverage",vr(old))
    assert report.research_security_n==1 and report.company_with_exposure_n==0
    assert report.unknown_company_n==1 and report.rows[0].missing_reason_codes==("EXPOSURE_MISSING","ECONOMIC_EXPOSURE_UNKNOWN")


@pytest.mark.pit
def test_replay_restart_deterministic(disclosed):
    w,d,x=disclosed
    s=snapshot(w)
    report=w["master"].coverage("coverage",vr(s))
    cutoff=w["clock"]()
    before=w["ledger"].replay(cutoff)
    w["ledger"].close()
    other=Ledger(w["ledger"].path,clock=w["clock"])
    try:
        assert other.replay(cutoff)==before==other.replay(cutoff)
        assert Registry(other).snapshot(s.snapshot_id,as_of=s.as_of)==s
        assert ExposureMaster(other).coverage(report.report_id,vr(s))==report
    finally:
        other.close()


def test_phase5_does_not_modify_event_states(disclosed):
    w,d,x=disclosed
    before=w["ledger"].history(as_of=w["clock"](),kind="EventVersion")
    s=snapshot(w)
    w["master"].coverage("coverage",vr(s))
    w["master"].metric(1,metric(x))
    assert w["ledger"].history(as_of=w["clock"](),kind="EventVersion")==before


@pytest.mark.parametrize("field,value",[("effective_from","2026-03-28T00:00:00"),("business_role","GUESS"),("exposure_type","TRUST_ME"),("mechanism_zh","")])
def test_schema_rejects_unsafe_input(disclosed,field,value):
    w,d,x=disclosed
    with pytest.raises(ValidationError):
        exposure(w,d,**{field:value})


def test_all_phase5_json_schema_roundtrip(disclosed):
    w,d,x=disclosed
    w["master"].metric(1,metric(x))
    w["master"].coverage("coverage",vr(snapshot(w)))
    models={**REGISTRY_SCHEMAS,**EXPOSURE_SCHEMAS}
    seen=set()
    for record in w["ledger"].history(as_of=w["clock"]()):
        cls=type(record)
        if cls.__name__ in models:
            seen.add(cls.__name__)
            assert cls.model_validate_json(record.model_dump_json())==record
            assert cls.model_json_schema()["additionalProperties"] is False
    assert seen==set(models)


def test_chinese_fixture(tmp_path):
    result=run_fixture(CONFIG/"phase5_exposures.zh-CN.json",tmp_path/"demo.sqlite")
    assert result["年报晚披露"]=={"一月可见暴露":0,"三月可见暴露":1}
    assert result["收入占比"]==0.3
    assert "工程能力完成 ≠ 全 A 股真实数据覆盖完成" in result["结论"]


@pytest.mark.pit
def test_future_effective_rename_does_not_hide_current_identity(w):
    old=add_security(w)
    cutoff=w["clock"]()
    w["registry"].security(2,security(w,security_name="未来名称",effective_from="2026-01-01T00:00:00Z"))
    now=snapshot(w,"known_but_not_effective")
    assert now.included_security_refs==(vr(old),)
    at(w,"2026-01-02T00:00:00Z")
    assert snapshot(w,"effective").included_security_refs[0].version==2
    assert snapshot(w,"past",cutoff).included_security_refs==(vr(old),)


def test_duplicate_legal_identity_rejected(w):
    fields={k:v for k,v in w["company"].model_dump().items() if k in CompanySpec.model_fields}
    with pytest.raises(ValueError,match="COMPANY_DUPLICATE"):
        w["registry"].company(1,CompanySpec.model_validate({**fields,"company_id":"DUPLICATE"}))


def test_security_code_collision_isolated(w):
    add_security(w)
    add_security(w,"DUPLICATE_SECURITY")
    snap=snapshot(w)
    assert not snap.included_security_refs and len(snap.security_hold_refs)==2
    assert all("COLLISION" in d.reason_codes[0] for d in snap.decisions)


def test_unrelated_company_security_relation_rejected(w):
    s=add_security(w)
    fields={k:v for k,v in w["company"].model_dump().items() if k in CompanySpec.model_fields}
    other=w["registry"].company(1,CompanySpec.model_validate({**fields,"company_id":"CO_B","company_identifier":"LEGAL_B"}))
    with pytest.raises(ValueError,match="RELATION_COMPANY"):
        w["registry"].relation(1,RelationSpec(**w["proof"],relation_id="BAD_REL",company_ref=vr(other),
            security_ref=vr(s),identity_status="VERIFIED",identity_reason_zh="错误关系"))


def test_secondary_source_cannot_be_verified_direct(w):
    from xevent.ledger.contracts import RawObservation
    at(w,"2026-03-28T00:00:00Z")
    e=w["ledger"].ingest(RawObservation(source_ref=ref(w["source"]),locator="fixture:secondary",
        raw="转载甲公司有铜矿".encode(),first_seen_at=w["clock"](),collected_at=w["clock"](),
        content_version="1",claim_kind="FACT",is_first_hand=False),w["seed"])
    d=w["master"].disclosure(1,DisclosureSpec(disclosure_id="SECONDARY",company_ref=vr(w["company"]),
        reporting_period=dict(start="2025-01-01",end="2025-12-31"),disclosure_type="ANNUAL_REPORT",
        published_at=None,first_seen_at=e.first_seen_at,evidence_refs=[ref(e)],source_refs=[ref(w["source"])],
        provenance_zh="错误声称转载为原披露",reviewed_by="fixture核验者",review_status="MANUALLY_VERIFIED",
        quoted_span="转载甲公司有铜矿",issuer_identity_verified=True,revision_reason_zh="测试"))
    with pytest.raises(ValueError,match="DIRECT_PROOF"):
        w["master"].exposure(1,exposure(w,d))


@pytest.mark.parametrize("kind",["UNKNOWN","HOLD","INFERRED"])
def test_uncovered_types_reported_explicitly(w,kind):
    add_security(w)
    at(w,"2026-03-28T00:00:00Z")
    d=disclose(w)
    x=w["master"].exposure(1,exposure(w,d,exposure_type=kind,validation_status="HOLD" if kind=="HOLD" else "UNKNOWN",
        industry_ref=None if kind in ("UNKNOWN","HOLD") else dict(object_id="XIND_COPPER_MINING",version=1)))
    report=w["master"].coverage("coverage",vr(snapshot(w)))
    assert report.rows[0].exposure_types==(kind,)
    assert report.verified_direct_company_n==0
    assert report.inferred_company_n==int(kind=="INFERRED")
    assert report.hold_company_n==int(kind=="HOLD")
    assert x.exposure_type==kind


@pytest.mark.pit
def test_exposure_available_at_commit_gate(disclosed):
    w,d,x=disclosed
    assert x.available_at >= max(x.recorded_at,x.computed_at,*(r.available_at for r in x.input_version_refs))
    assert not w["master"].exposure_view(as_of=x.recorded_at-timedelta(microseconds=1))
    assert w["master"].exposure_view(as_of=x.available_at)==[x]


@pytest.mark.pit
def test_snapshot_rejects_future_asof(w):
    with pytest.raises(ValueError,match="PIT_UNIVERSE"):
        snapshot(w,stamp="2099-01-01T00:00:00Z")


@pytest.mark.parametrize("stage",["before_commit","after_commit","after_receipt_commit"])
@pytest.mark.pit
def test_phase5_append_crash_recovery(w,stage):
    spec=security(w)
    def crash(value):
        if value==stage: raise RuntimeError("故障注入")
    w["ledger"].fault=crash
    with pytest.raises(RuntimeError):
        w["registry"].security(1,spec)
    cutoff=w["clock"]()
    assert not w["ledger"].history(as_of=cutoff,kind="SecurityVersion")
    w["ledger"].fault=lambda s:None
    w["clock"].advance(seconds=1)
    w["ledger"].recover()
    saved=w["registry"].security(1,spec)
    assert saved.available_at > cutoff
    assert len(w["ledger"].history(as_of=w["clock"](),kind="SecurityVersion"))==1


def test_amount_currency_and_ratio_units_required(disclosed):
    w,d,x=disclosed
    with pytest.raises(ValidationError,match="METRIC_UNIT"):
        metric(x,unit="PERCENT")
    with pytest.raises(ValidationError,match="METRIC_CURRENCY"):
        metric(x,metric_type="REVENUE",denominator=None,calculation_method="REPORTED_AMOUNT",currency=None)


def test_phase4_narrative_relation_not_economic_evidence(disclosed):
    from xevent.ontology.engine import OntologyEngine
    w,d,x=disclosed
    event=w["ledger"].history(as_of=w["clock"](),kind="EventVersion")[-1]
    engine=OntologyEngine(w["ledger"])
    theme=engine.theme("THEME_FIXTURE",1,event_ref=vr(event),canonical_name_zh="机器人概念",
        description_zh="只表述市场叙事",evidence_refs=list(d.evidence_refs))
    with pytest.raises(ValueError,match="REGISTRY_REFERENCE"):
        w["master"].exposure(1,exposure(w,d,exposure_id="THEME_AS_INDUSTRY",industry_ref=vr(theme)))
    narrative=w["master"].exposure(1,exposure(w,d,exposure_id="NARRATIVE_ONLY",industry_ref=None,
        narrative_theme_ref=vr(theme),exposure_type="NARRATIVE_ASSOCIATION",validation_status="UNREVIEWED"))
    assert narrative.industry_ref is None


@pytest.mark.pit
def test_snapshot_sha_and_results_repeat(w):
    add_security(w)
    cutoff=w["clock"]()
    snap=snapshot(w,"fixed",cutoff)
    assert snapshot(w,"fixed",cutoff)==snap
    later=snapshot(w,"other",cutoff)
    assert later.decisions==snap.decisions and later.source_refs==snap.source_refs


@pytest.mark.parametrize("bad_date",[0,20250101,"20250101","2025-01-01T00:00:00Z"])
def test_calendar_dates_are_not_timestamps(w,bad_date):
    with pytest.raises(ValidationError,match="CALENDAR_DATE"):
        security(w,listing_date=bad_date)


def test_direct_gate_cannot_borrow_unrelated_first_hand_evidence(w):
    from xevent.ledger.contracts import RawObservation
    at(w,"2026-03-28T00:00:00Z")
    d=disclose(w)
    e=w["ledger"].ingest(RawObservation(source_ref=ref(w["source"]),locator="fixture:unrelated-news",
        raw="新闻猜测机器人业务".encode(),first_seen_at=w["clock"](),collected_at=w["clock"](),
        content_version="1",claim_kind="FACT",is_first_hand=False),w["seed"])
    fields={k:v for k,v in d.model_dump().items() if k in DisclosureSpec.model_fields}
    mixed=w["master"].disclosure(1,DisclosureSpec.model_validate({**fields,"disclosure_id":"MIXED_PROOF",
        "evidence_refs":[*d.evidence_refs,vr(e)],"quoted_span":"新闻猜测机器人业务"}))
    with pytest.raises(ValueError,match="DIRECT_PROOF"):
        w["master"].exposure(1,exposure(w,mixed))
