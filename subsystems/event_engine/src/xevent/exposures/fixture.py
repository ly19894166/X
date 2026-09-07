"""完全虚构数据；与真实全A股覆盖验收分开。"""
import json
from datetime import timedelta
from pathlib import Path
from ..contracts import Source
from ..contracts.common import TypeAdapter, UTCDateTime, VersionRef
from ..ledger.contracts import RawObservation, EventSeed
from ..ledger.store import Ledger, ref
from ..ontology.engine import OntologyEngine
from ..ontology.contracts import OntologyDraft
from ..registry.contracts import CompanySpec, SecuritySpec, RelationSpec
from ..registry.engine import Registry
from .contracts import DisclosureSpec, ExposureSpec, MetricSpec
from .engine import ExposureMaster


class FixtureClock:
    def __init__(self, at):
        self.value = TypeAdapter(UTCDateTime).validate_python(at)
    def __call__(self):
        self.value += timedelta(milliseconds=1)
        return self.value
    def advance(self, **kwargs):
        self.value += timedelta(**kwargs)


def vr(obj):
    return VersionRef(**ref(obj))


def seed_fixture(db, config_dir):
    base = json.loads((config_dir/"offline_fixture.zh-CN.json").read_text(encoding="utf-8-sig"))
    clock = FixtureClock("2025-01-01T00:00:00Z")
    ledger = Ledger(db,clock=clock)
    source = ledger.register_source(Source.model_validate({**base["sources"][0],
        "recorded_at":clock().isoformat(),"available_at":clock().isoformat(),"identity_status":"VERIFIED"}))
    seed = EventSeed(event_id="P5_RAW_ARCHIVE_ONLY",title_zh="虚构身份披露存档",
        dna={**base["event_versions"][0]["dna"],"actor_refs":[]})
    evidence = ledger.ingest(RawObservation(source_ref=ref(source),locator="fixture:identity",
        raw="虚构甲公司法律身份及A/H证券注册清单".encode(),first_seen_at=clock(),collected_at=clock(),
        content_version="1",is_first_hand=True,claim_kind="FACT"),seed)
    ontology_data = json.loads((config_dir/"phase4_ontology.zh-CN.json").read_text(encoding="utf-8-sig"))["ontology"]
    ontology_data["crosswalks"] = []
    for segment in ontology_data["segments"]:
        segment["effective_from"]="2020-01-01T00:00:00Z"
    ontology = OntologyEngine(ledger).publish(OntologyDraft.model_validate(ontology_data))
    registry,master = Registry(ledger),ExposureMaster(ledger)
    proof = dict(evidence_refs=[ref(evidence)],source_refs=[ref(source)],provenance_zh="虚构原始注册材料人工核验",
        reviewed_by="fixture核验者",effective_from="2020-01-01T00:00:00Z")
    company = registry.company(1,CompanySpec(**proof,company_id="CO_FIXTURE_A",canonical_name_zh="虚构甲公司",
        legal_name="虚构甲有限公司",company_identifier="FIXTURE-LEGAL-A",domicile="CN",operating_geographies=["CN"],
        company_status="ACTIVE",identity_status="VERIFIED",identity_reason_zh="虚构法律主体证明",continuity_status="CONFIRMED"))
    return dict(ledger=ledger,clock=clock,source=source,seed=seed,evidence=evidence,ontology=ontology,
        registry=registry,master=master,proof=proof,company=company)


def security(w, identity="SEC_A", **changes):
    fields=dict(**w["proof"],security_id=identity,company_ref=ref(w["company"]),exchange="SZSE",security_code="000001",
        ticker="000001.SZ",security_name="虚构证券旧名",security_type="A_SHARE",board="SZ_MAIN",currency="CNY",
        listing_status="LISTED",st_status="NORMAL",suspension_status="TRADING",listing_date="2020-01-01",
        identity_status="VERIFIED",identity_reason_zh="虚构证券身份证明")
    return SecuritySpec.model_validate({**fields,**changes})


def add_security(w,identity="SEC_A",**changes):
    s=w["registry"].security(1,security(w,identity,**changes))
    w["registry"].relation(1,RelationSpec(**w["proof"],relation_id="REL_"+identity,company_ref=s.company_ref,
        security_ref=ref(s),identity_status=s.identity_status,identity_reason_zh="虚构公司证券归属"))
    return s


def disclose(w,version=1,*,raw_text=None,**changes):
    clock=w["clock"]
    raw="虚构甲公司年报：拥有铜矿，收入30，总收入100，铜产量20；人工核实归属及计量口径"
    if version > 1:
        raw="虚构甲公司更正年报：拥有铜矿，收入20，总收入100，铜产量20；人工核实归属及计量口径"
    if raw_text is not None:
        raw=raw_text
    evidence=w["ledger"].ingest(RawObservation(source_ref=ref(w["source"]),locator="fixture:annual",
        raw=raw.encode(),first_seen_at=clock(),collected_at=clock(),published_at=clock.value,
        content_version=str(version),change_type="INITIAL" if version==1 else "EDIT",
        is_first_hand=True,claim_kind="FACT"),w["seed"])
    spec=DisclosureSpec.model_validate(dict(disclosure_id="DISC_A_2025",company_ref=ref(w["company"]),
        reporting_period=dict(start="2025-01-01",end="2025-12-31"),disclosure_type="ANNUAL_REPORT",
        published_at=evidence.published_at,first_seen_at=evidence.first_seen_at,evidence_refs=[ref(evidence)],
        source_refs=[ref(w["source"])],provenance_zh="虚构年报人工校核",reviewed_by="fixture核验者",
        review_status="MANUALLY_VERIFIED",quoted_span=raw,issuer_identity_verified=True,revision_reason_zh="初始或更正披露",
        input_method="FIXTURE",**changes))
    return w["master"].disclosure(version,spec)


def exposure(w,disclosure,**changes):
    fields=dict(exposure_id="EXP_A_COPPER_2025",company_ref=ref(w["company"]),
        industry_ref=dict(object_id="XIND_COPPER_MINING",version=1),business_role="PRODUCER",exposure_type="VERIFIED_DIRECT",
        geography=["CN"],reporting_period=disclosure.reporting_period,evidence_refs=disclosure.evidence_refs,
        source_refs=disclosure.source_refs,provenance_zh="人工核实年报中本公司铜矿及产量",reviewed_by="fixture核验者",
        evidence_type=disclosure.disclosure_type,source_disclosure_ref=ref(disclosure),validation_status="VERIFIED",
        mechanism_zh="本公司拥有铜矿并产出铜",description_zh="报告期内直接生产暴露；不推导股票收益",
        effective_from="2025-01-01T00:00:00Z",effective_to="2026-01-01T00:00:00Z",
        mapping_method="MANUAL_VERIFIED",mapping_review_zh="核实披露中的法律主体、业务角色与固定产业节点")
    return ExposureSpec.model_validate({**fields,**changes})


def metric(exposure,**changes):
    fields=dict(metric_id="METRIC_A_REVENUE_SHARE",exposure_ref=ref(exposure),metric_type="REVENUE_SHARE",
        numerator=30.0,denominator=100.0,unit="RATIO",currency="CNY",period=exposure.reporting_period,scope="合并报表",
        evidence_ref=exposure.evidence_refs[0],calculation_method="SAME_BASIS_RATIO",validation_status="VERIFIED",
        numerator_basis="同期间铜矿业务收入",denominator_basis="同期间同币种合并营业收入",basis_verified_by="fixture核验者")
    fields.update(changes)
    for name,basis in (("numerator","收入"),("denominator","总收入")):
        value=fields[name]
        number=format(value,"g") if value is not None else None
        fields.setdefault(name+"_source_span",dict(quote=basis+number,basis_text=basis,
            value_text=number,value_offset=len(basis)) if number is not None else None)
    return MetricSpec.model_validate(fields)


def run_fixture(path,db):
    if db.exists():
        raise ValueError("FIXTURE_DB：只允许新隔离数据库")
    data=json.loads(path.read_text(encoding="utf-8-sig"))
    w=seed_fixture(db,path.parent)
    try:
        a=add_security(w)
        add_security(w,"SEC_H",exchange="HKEX",security_code="00001",ticker="00001.HK",
            security_type="H_SHARE",board="HK",currency="HKD")
        w["clock"].value=TypeAdapter(UTCDateTime).validate_python("2026-03-28T00:00:00Z")
        d=disclose(w)
        x=w["master"].exposure(1,exposure(w,d))
        m=w["master"].metric(1,metric(x))
        old=w["master"].exposure_view(as_of="2026-01-15T00:00:00Z")
        snapshot=w["registry"].snapshot("SNAP_FIXTURE",as_of=w["clock"]())
        report=w["master"].coverage("COVER_FIXTURE",vr(snapshot))
        return {"声明":data["description_zh"],"能力":snapshot.capability,"历史覆盖":snapshot.coverage_status,
            "真实业务覆盖":report.exposure_coverage_status,"年报晚披露":{"一月可见暴露":len(old),"三月可见暴露":len(w["master"].exposure_view(as_of=w["clock"]()))},
            "公司ID":w["company"].company_id,"A股代码":a.security_code,"收入占比":m.value,
            "覆盖报告":report.model_dump(mode="json"),"结论":"工程能力完成 ≠ 全 A 股真实数据覆盖完成。"}
    finally:
        w["ledger"].close()
