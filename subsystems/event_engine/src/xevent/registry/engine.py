"""复用Phase2耐久化事务；Phase5只新增自己的记录类型。"""
from datetime import datetime, timedelta, timezone
from pydantic import TypeAdapter
from ..contracts import Source, EvidenceVersion
from ..contracts.common import PITQuery, UTCDateTime
from ..ledger.store import digest, ref
from .contracts import (Company, CompanySpec, SecurityVersion, SecuritySpec, CompanySecurityRelation,
    RelationSpec, ResearchUniverseSnapshot, POLICY, UNIVERSE)


def key(r):
    return r.object_id, r.version


def refs(values):
    return [dict(object_id=k[0], version=k[1]) for k in sorted({key(r) for r in values})]


def latest(view, cls):
    result = {}
    for r in view.values():
        if isinstance(r, cls) and (r.object_id not in result or result[r.object_id].version < r.version):
            result[r.object_id] = r
    return result


def effective(obj, at):
    return (obj.status in ("READY", "DEGRADED") and
        (obj.effective_from is None or obj.effective_from <= at) and
        (obj.effective_to is None or at < obj.effective_to))


def identity_at(view, cls, at):
    # 已知的未来生效版本不提前遮蔽现行身份；到期版本不回退成旧身份。
    all_latest = latest(view, cls)
    started = latest({k:r for k,r in view.items() if r.effective_from is None or r.effective_from <= at}, cls)
    return {identity:started.get(identity,obj) for identity,obj in all_latest.items()}


class Registry:
    def __init__(self, ledger):
        self.ledger = ledger

    def input(self, view, r, cls):
        obj = view.get(key(r))
        if not isinstance(obj, cls) or obj.status not in ("READY", "DEGRADED") or obj.mode != "LIVE_FORWARD":
            raise ValueError("REGISTRY_REFERENCE：固定版本缺失/类型错误/隔离输入")
        return obj

    def proof(self, view, spec):
        sources = [self.input(view, r, Source) for r in spec.source_refs]
        for r in spec.evidence_refs:
            evidence = self.input(view, r, EvidenceVersion)
            if key(evidence.source_ref) not in {key(s) for s in sources}:
                raise ValueError("PROVENANCE_SOURCE：证据来源与声明来源不一致")
        if getattr(spec, "identity_status", None) == "VERIFIED":
            if not spec.reviewed_by or any(s.identity_status != "VERIFIED" for s in sources):
                raise ValueError("IDENTITY_PROOF：需要明确核验记录及已核实来源")
            if any(self.input(view, r, EvidenceVersion).quality_status != "VALIDATED" or
                self.input(view,r,EvidenceVersion).claim_kind != "FACT" for r in spec.evidence_refs):
                raise ValueError("IDENTITY_PROOF：身份材料尚未校验")

    def _publish(self, identity, version, spec, cls, validate, references):
        def build(conn, view, batch):
            previous = [r for r in view.values() if r.object_id == identity]
            if any(not isinstance(r, cls) for r in previous):
                raise ValueError("REGISTRY_ID_TYPE：稳定ID不得跨类型重用")
            old = max(previous, key=lambda r:r.version, default=None)
            if version != (old.version + 1 if old else 1):
                raise ValueError("REGISTRY_VERSION：只允许追加下一知识版本")
            validate(view, old)
            inputs = references(view) + ([old] if old else [])
            self.ledger._put(conn, batch, cls.__name__, identity, version,
                {**spec.model_dump(mode="json"), "policy_version": POLICY, "supersedes_version":old.version if old else None},
                refs(inputs))
        self.ledger._write("P5:" + identity + ":" + str(version), digest(spec.model_dump(mode="json")), build)
        return self.ledger.get(identity, version)

    def company(self, version, spec: CompanySpec):
        spec = CompanySpec.model_validate(spec)
        def validate(view, old):
            self.proof(view, spec)
            if spec.company_identifier and spec.identity_status == "VERIFIED" and any(
                c.company_id != spec.company_id and c.company_identifier == spec.company_identifier and c.identity_status == "VERIFIED"
                for c in latest(view,Company).values()):
                raise ValueError("COMPANY_DUPLICATE：同一已核实法律标识不能复制经济实体")
            if old and old.company_identifier and old.company_identifier != spec.company_identifier and spec.identity_status == "VERIFIED":
                raise ValueError("COMPANY_CONTINUITY_HOLD：法律标识改变不得自动确认同一实体")
        return self._publish(spec.company_id, version, spec, Company, validate, lambda v:[*spec.evidence_refs, *spec.source_refs])

    def security(self, version, spec: SecuritySpec):
        spec = SecuritySpec.model_validate(spec)
        def validate(view, old):
            self.proof(view, spec)
            company = self.input(view, spec.company_ref, Company)
            if spec.identity_status == "VERIFIED" and company.identity_status != "VERIFIED":
                raise ValueError("SECURITY_COMPANY_HOLD：公司身份未确认，证券须隔离")
            if old and old.company_ref.object_id != company.object_id and spec.identity_status == "VERIFIED":
                raise ValueError("SECURITY_CONTINUITY_HOLD：换壳/法律实体改变需要显式REVIEW_REQUIRED")
        return self._publish(spec.security_id, version, spec, SecurityVersion, validate,
            lambda v:[spec.company_ref, *spec.evidence_refs, *spec.source_refs])

    def relation(self, version, spec: RelationSpec):
        spec = RelationSpec.model_validate(spec)
        def validate(view, old):
            self.proof(view, spec)
            company = self.input(view, spec.company_ref, Company)
            security = self.input(view, spec.security_ref, SecurityVersion)
            if security.company_ref.object_id != company.object_id:
                raise ValueError("RELATION_COMPANY：证券归属与关系声明不一致")
            if spec.identity_status == "VERIFIED" and (company.identity_status != "VERIFIED" or security.identity_status != "VERIFIED"):
                raise ValueError("RELATION_IDENTITY：两端身份需要核实")
            if old and (old.company_ref.object_id, old.security_ref.object_id) != (company.object_id, security.object_id):
                raise ValueError("RELATION_ID：同一关系不能更换端点")
        return self._publish(spec.relation_id, version, spec, CompanySecurityRelation, validate,
            lambda v:[spec.company_ref, spec.security_ref, *spec.evidence_refs, *spec.source_refs])

    def snapshot(self, snapshot_id, *, as_of):
        cutoff = TypeAdapter(UTCDateTime).validate_python(as_of)
        if cutoff > self.ledger.now():
            raise ValueError("PIT_UNIVERSE：禁止未来知识时点")
        def build(conn, full, batch):
            view = {k:r for k,r in full.items() if r.available_at <= cutoff}
            companies = identity_at(view, Company, cutoff)
            securities = identity_at(view, SecurityVersion, cutoff)
            relations = identity_at(view, CompanySecurityRelation, cutoff)
            decisions, inputs, sources = [], [], []
            # 1992年起中国证券日期使用UTC+8；更早夏令时历史不在本Phase验证范围。
            day = cutoff.astimezone(timezone(timedelta(hours=8))).date()
            for s in sorted(securities.values(), key=lambda r:r.object_id):
                company = companies.get(s.company_ref.object_id)
                matches = [r for r in relations.values() if r.security_ref.object_id == s.object_id and
                    r.company_ref.object_id == s.company_ref.object_id and effective(r, cutoff) and r.identity_status == "VERIFIED"]
                relation = matches[0] if len(matches) == 1 else None
                decision, reasons = "INCLUDED", ["A_SHARE_RESEARCH_NO_EXECUTION_FILTER"]
                if s.security_type != "A_SHARE":
                    decision, reasons = ("HOLD", ["SECURITY_TYPE_UNKNOWN"]) if s.security_type == "UNKNOWN" else ("EXCLUDED", ["NOT_A_SHARE"])
                elif cutoff < datetime(1992,1,1,tzinfo=timezone.utc):
                    decision, reasons = "HOLD", ["HOLD_PRE_1992_CALENDAR"]
                elif s.identity_status != "VERIFIED" or not company or company.identity_status != "VERIFIED" or not relation:
                    decision, reasons = "HOLD", ["IDENTITY_OR_RELATION_UNRESOLVED"]
                elif sum((other.exchange,other.security_code)==(s.exchange,s.security_code) and effective(other,cutoff)
                    and other.listing_status=="LISTED" for other in securities.values()) > 1:
                    decision, reasons = "HOLD", ["SECURITY_IDENTITY_COLLISION"]
                elif not effective(s, cutoff) or not effective(company, cutoff):
                    decision, reasons = "EXCLUDED", ["OUTSIDE_EFFECTIVE_PERIOD"]
                elif s.listing_date is None or s.listing_status == "UNKNOWN":
                    decision, reasons = "HOLD", ["LISTING_HISTORY_UNKNOWN"]
                elif day < s.listing_date or s.listing_status == "NOT_LISTED":
                    decision, reasons = "EXCLUDED", ["NOT_YET_LISTED"]
                elif s.listing_status == "DELISTED" or (s.delisting_date and day >= s.delisting_date):
                    decision, reasons = "EXCLUDED", ["DELISTED_AT_AS_OF"]
                decisions.append(dict(security_ref=ref(s), company_ref=ref(company) if company else None,
                    relation_ref=ref(relation) if relation else None, decision=decision, reason_codes=reasons))
                used = [s, *([company] if company else []), *([relation] if relation else [])]
                inputs.extend(used)
                sources.extend(r for u in used for r in u.source_refs)
            groups = {name:[d["security_ref"] for d in decisions if d["decision"] == status]
                for name,status in (("included_security_refs","INCLUDED"),("excluded_security_refs","EXCLUDED"),("security_hold_refs","HOLD"))}
            self.ledger._put(conn,batch,"ResearchUniverseSnapshot",snapshot_id,1,
                dict(snapshot_id=snapshot_id, as_of=cutoff.isoformat(), decisions=decisions, source_refs=refs(sources),
                    policy_version=POLICY, **groups), refs([*inputs,*sources]))
        self.ledger._write("P5_SNAPSHOT:"+snapshot_id, digest([cutoff.isoformat(),UNIVERSE,POLICY]), build)
        return self.ledger.get(snapshot_id,1)
