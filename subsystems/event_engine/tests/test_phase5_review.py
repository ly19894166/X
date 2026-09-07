"""PR #21 Review：仅产业现实时间、数值原文与未实现映射方法三个阻塞项。"""
import json
import pytest
from pydantic import ValidationError
from test_phase5_registry_exposure import w, disclosed, at, CONFIG
from xevent.exposures.contracts import DisclosureSpec, ExposureMetric, MetricSourceSpan
from xevent.exposures.fixture import disclose, exposure, metric, vr
from xevent.ledger.contracts import RawObservation
from xevent.ledger.store import ref, digest
from xevent.ontology.contracts import OntologyDraft
from xevent.ontology.engine import OntologyEngine


def ontology_revision(w, version=2, *, start="2020-01-01T00:00:00Z", end=None, target="XIND_COPPER_MINING"):
    data=json.loads((CONFIG/"phase4_ontology.zh-CN.json").read_text(encoding="utf-8"))["ontology"]
    data["version"]=version
    data["crosswalks"]=[]
    for s in data["segments"]:
        s["effective_from"]="2020-01-01T00:00:00Z"
        if s["industry_id"]=="XIND_COPPER_MINING":
            s["effective_from"],s["effective_to"]=start,end
    data["aliases"]=[dict(alias_id="copper-alias",phrase="虚构铜产业别名",industry_id=target)]
    data["rules"][0]["industry_id"]=target
    return OntologyEngine(w["ledger"]).publish(OntologyDraft.model_validate(data))


@pytest.mark.pit
def test_retired_industry_allows_late_historical_disclosure(w):
    ontology_revision(w,end="2026-01-01T00:00:00Z")
    at(w,"2026-03-28T00:00:00Z")
    d=disclose(w)
    spec=exposure(w,d,industry_ref=dict(object_id="XIND_COPPER_MINING",version=2))
    x=w["master"].exposure(1,spec)
    assert w["master"].exposure_view(as_of="2026-01-15T00:00:00Z")==[]
    assert w["master"].exposure_view(as_of="2026-03-29T00:00:00Z")==[x]
    assert x.industry_ref.version==2
    industry=w["ledger"].get(x.industry_ref.object_id,2)
    assert industry.effective_to < x.available_at
    assert industry.available_at <= x.available_at
    at(w,"2030-01-01T00:00:00Z")
    # 墙钟移动不会把同一历史业务从合法变成非法。
    again=w["master"].exposure(2,spec)
    assert again.industry_ref==x.industry_ref


@pytest.mark.pit
@pytest.mark.parametrize("start,end",[
    ("2026-01-01T00:00:00Z",None),("2020-01-01T00:00:00Z","2025-01-01T00:00:00Z"),
    ("2027-01-01T00:00:00Z",None)])
def test_industry_no_real_interval_overlap_rejected(w,start,end):
    ontology_revision(w,start=start,end=end)
    at(w,"2026-03-28T00:00:00Z")
    d=disclose(w)
    with pytest.raises(ValueError,match="EXPOSURE_INDUSTRY_INTERVAL"):
        w["master"].exposure(1,exposure(w,d,industry_ref=dict(object_id="XIND_COPPER_MINING",version=2)))
    assert w["master"].exposure_view(as_of=w["clock"]())==[]


@pytest.mark.pit
def test_partial_real_overlap_and_exact_known_reference(w):
    ontology_revision(w,start="2025-07-01T00:00:00Z",end="2026-01-01T00:00:00Z")
    at(w,"2026-03-28T00:00:00Z")
    d=disclose(w)
    with pytest.raises(ValueError,match="REGISTRY_REFERENCE"):
        w["master"].exposure(1,exposure(w,d,industry_ref=dict(object_id="XIND_COPPER_MINING",version=3)))
    x=w["master"].exposure(1,exposure(w,d,industry_ref=dict(object_id="XIND_COPPER_MINING",version=2)))
    assert x.industry_ref.version==2


@pytest.mark.parametrize("method",["EXACT_ALIAS_REVIEWED","VERIFIED_RULE"])
def test_unimplemented_mapping_strings_fail_closed(disclosed,method):
    w,d,x=disclosed
    with pytest.raises(ValidationError):
        exposure(w,d,mapping_method=method)
    # 也不能用SUPPORTED/UNKNOWN等状态绕过未实现方法的契约。
    with pytest.raises(ValidationError):
        exposure(w,d,mapping_method=method,exposure_type="UNKNOWN",validation_status="UNKNOWN")


@pytest.mark.pit
def test_later_alias_rule_revision_does_not_rewrite_manual_exposure(disclosed):
    w,d,x=disclosed
    cutoff=w["clock"]()
    before=w["ledger"].replay(cutoff)
    ontology_revision(w)
    w["clock"].advance(days=1)
    newer=ontology_revision(w,3,target="XIND_COPPER_USERS")
    assert newer.alias_refs and newer.rule_refs
    assert w["master"].exposure_view(as_of=cutoff)==[x]
    assert w["ledger"].replay(cutoff)==before
    assert x.mapping_method=="MANUAL_VERIFIED" and x.industry_ref.version==1


@pytest.mark.parametrize("raw",["虚构甲公司拥有铜矿，没有披露收入数字",
    "虚构甲公司拥有铜矿；收入130，总收入100",
    "虚构甲公司拥有铜矿；收入30%，总收入100",
    "虚构甲公司拥有铜矿；收入30e2，总收入100"])
def test_reviewer_cannot_invent_verified_30_100(w,raw):
    at(w,"2026-03-28T00:00:00Z")
    d=disclose(w,raw_text=raw)
    x=w["master"].exposure(1,exposure(w,d))
    with pytest.raises(ValueError,match="METRIC_RAW_PROVENANCE"):
        w["master"].metric(1,metric(x))
    assert w["master"].metric_view(as_of=w["clock"]())==[]


@pytest.mark.parametrize("field",["numerator_source_span","denominator_source_span"])
def test_verified_metric_requires_each_number_span(disclosed,field):
    w,d,x=disclosed
    with pytest.raises(ValidationError,match="METRIC_NUMERIC_PROVENANCE"):
        metric(x,**{field:None})


def test_actual_raw_30_100_passes_and_roundtrips(disclosed):
    w,d,x=disclosed
    m=w["master"].metric(1,metric(x))
    assert m.value==0.3
    assert m.numerator_source_span.quote=="收入30"
    assert m.denominator_source_span.quote=="总收入100"
    assert ExposureMetric.model_validate_json(m.model_dump_json())==m
    assert "MetricSourceSpan" in ExposureMetric.model_json_schema()["$defs"]


@pytest.mark.parametrize("quote,token,offset",[
    ("收入130","30",3),("收入-30","30",3),("收入30%","30",2),
    ("收入30.5","30",2),("收入1,000","000",4)])
def test_provenance_cannot_slice_or_rescale_numeric_token(quote,token,offset):
    with pytest.raises(ValidationError):
        MetricSourceSpan(quote=quote,basis_text="收入",value_text=token,value_offset=offset)


def test_span_number_must_equal_supplied_number(disclosed):
    w,d,x=disclosed
    with pytest.raises(ValidationError,match="METRIC_NUMERIC_PROVENANCE"):
        metric(x,numerator=31.0,numerator_source_span=dict(quote="收入30",basis_text="收入",value_text="30",value_offset=2))


@pytest.mark.pit
def test_corrected_20_100_uses_new_raw_only_at_new_asof(disclosed):
    w,d,x=disclosed
    first=w["master"].metric(1,metric(x))
    cutoff=w["clock"]()
    at(w,"2026-04-10T00:00:00Z")
    revised=disclose(w,2)
    x2=w["master"].exposure(2,exposure(w,revised))
    with pytest.raises(ValueError,match="METRIC_RAW_PROVENANCE"):
        w["master"].metric(2,metric(x2))  # 更正原文不再含收入30。
    second=w["master"].metric(2,metric(x2,numerator=20.0))
    assert second.numerator_source_span.quote=="收入20"
    assert w["master"].metric_view(as_of=cutoff)==[first]
    assert w["master"].metric_view(as_of=w["clock"]())==[second]
    assert first.value==0.3 and second.value==0.2
    assert first.evidence_ref!=second.evidence_ref


def supported_disclosure(w, *, claim="FACT", first_hand=True, disclosure_type="ANNUAL_REPORT", quality="VALIDATED"):
    at(w,"2026-03-28T00:00:00Z")
    raw="虚构甲公司铜矿业务；收入30，总收入100"
    e=w["ledger"].ingest(RawObservation(source_ref=ref(w["source"]),locator="fixture:metric-review",
        raw=raw.encode(),first_seen_at=w["clock"](),collected_at=w["clock"](),content_version="1",
        claim_kind=claim,is_first_hand=first_hand),w["seed"])
    if quality!="VALIDATED":
        # 显式离线PARTIAL证据fixture：复用原始archive，追加新Evidence知识版本。
        payload=e.model_dump(mode="json")
        for field in ("object_id","version","recorded_at","available_at","content_hash","run_id","input_version_refs"):
            payload.pop(field,None)
        payload.update(quality_status=quality,supersedes_version=1)
        w["ledger"]._write("PARTIAL_METRIC_FIXTURE",digest(payload),
            lambda conn,view,batch:w["ledger"]._put(conn,batch,"EvidenceVersion",e.object_id,2,payload,[ref(w["source"])]))
        e=w["ledger"].get(e.object_id,2)
    d=w["master"].disclosure(1,DisclosureSpec(disclosure_id="DISC_SUPPORTED",company_ref=vr(w["company"]),
        reporting_period=dict(start="2025-01-01",end="2025-12-31"),disclosure_type=disclosure_type,
        published_at=None,first_seen_at=e.first_seen_at,evidence_refs=[ref(e)],source_refs=[ref(w["source"])],
        provenance_zh="虚构人工结构化样例",reviewed_by="fixture核验者",review_status="MANUALLY_VERIFIED",
        quoted_span=raw,issuer_identity_verified=True,revision_reason_zh="测试数值Evidence Gate"))
    return w["master"].exposure(1,exposure(w,d,exposure_type="SUPPORTED_DIRECT",validation_status="SUPPORTED"))


@pytest.mark.parametrize("changes",[
    dict(claim="NARRATIVE"),dict(claim="RUMOR"),dict(disclosure_type="NEWS"),
    dict(first_hand=False),dict(quality="PARTIAL")])
def test_news_narrative_partial_secondary_cannot_be_verified_by_reviewer(w,changes):
    x=supported_disclosure(w,**changes)
    with pytest.raises(ValueError,match="METRIC_FACT_PROOF"):
        w["master"].metric(1,metric(x))
    # 未核实材料仍可保留为SUPPORTED/HOLD，不伪造可用数值。
    m=w["master"].metric(1,metric(x,validation_status="SUPPORTED"))
    assert m.value is None and m.result_status=="HOLD"
