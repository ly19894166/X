"""手工核验的结构化披露入口；不联网、不用模型猜测。"""
from ..contracts import EvidenceVersion, Source
from ..contracts.common import TypeAdapter, UTCDateTime
from ..ledger.store import digest, ref
from ..ontology.contracts import IndustrySegment, NarrativeTheme
from ..registry.contracts import Company, SecurityVersion, ResearchUniverseSnapshot, POLICY
from ..registry.engine import Registry, key, refs, latest
from .contracts import (DisclosureSpec, DisclosureImport, ExposureSpec, CompanyExposure, MetricSpec,
    ExposureMetric, CoverageReport, DIRECT_TYPES, metric_result)


class ExposureMaster(Registry):
    def disclosure(self, version, spec: DisclosureSpec):
        spec = DisclosureSpec.model_validate(spec)
        def validate(view, old):
            self.proof(view, spec)
            self.input(view, spec.company_ref, Company)
            evidence = [self.input(view,r,EvidenceVersion) for r in spec.evidence_refs]
            if spec.first_seen_at != min(e.first_seen_at for e in evidence):
                raise ValueError("DISCLOSURE_FIRST_SEEN：必须保留证据真实首次接收时间")
            if spec.published_at != min((e.published_at for e in evidence if e.published_at), default=None):
                raise ValueError("DISCLOSURE_PUBLICATION：公开时间必须来自证据，未知保留null")
            if not any(spec.quoted_span in self.ledger.raw(e.raw_object_ref).decode("utf-8",errors="replace") for e in evidence):
                raise ValueError("DISCLOSURE_QUOTE：核验摘录必须存在于不可变原文")
            if old and (old.company_ref.object_id != spec.company_ref.object_id or old.reporting_period != spec.reporting_period):
                raise ValueError("DISCLOSURE_ID：同一披露ID的重述不得更换公司/报告期")
        return self._publish(spec.disclosure_id, version, spec, DisclosureImport, validate,
            lambda v:[spec.company_ref,*spec.evidence_refs,*spec.source_refs])

    def exposure(self, version, spec: ExposureSpec):
        spec = ExposureSpec.model_validate(spec)
        def validate(view, old):
            self.proof(view,spec)
            company = self.input(view,spec.company_ref,Company)
            disclosure = self.input(view,spec.source_disclosure_ref,DisclosureImport)
            if disclosure.company_ref.object_id != company.object_id or disclosure.reporting_period != spec.reporting_period:
                raise ValueError("EXPOSURE_DISCLOSURE：披露必须属于该公司/报告期")
            if spec.evidence_type != disclosure.disclosure_type or not set(map(key,spec.evidence_refs)) <= set(map(key,disclosure.evidence_refs)):
                raise ValueError("EXPOSURE_PROVENANCE：证据类型/引用必须来自指定披露版本")
            if spec.industry_ref:
                industry = self.input(view,spec.industry_ref,IndustrySegment)
                # 知识可用性由固定输入版本和Ledger提交门槛保证；现实适用性只看两段现实区间。
                # 左闭右开，未知端点开放；产业退役不能阻止后来披露的合法历史业务。
                if ((industry.effective_to is not None and spec.effective_from >= industry.effective_to) or
                    (industry.effective_from is not None and spec.effective_to is not None and
                     industry.effective_from >= spec.effective_to)):
                    raise ValueError("EXPOSURE_INDUSTRY_INTERVAL：产业与业务现实区间无重叠")
            if spec.narrative_theme_ref:
                self.input(view,spec.narrative_theme_ref,NarrativeTheme)
            if disclosure.disclosure_type == "NARRATIVE" and spec.exposure_type not in ("NARRATIVE_ASSOCIATION","UNKNOWN","HOLD"):
                raise ValueError("NARRATIVE_GATE：叙事材料不得创建经济暴露")
            if spec.exposure_type == "VERIFIED_DIRECT":
                evidence = [self.input(view,r,EvidenceVersion) for r in spec.evidence_refs]
                if (company.identity_status != "VERIFIED" or disclosure.review_status != "MANUALLY_VERIFIED" or
                    not disclosure.issuer_identity_verified or disclosure.disclosure_type not in DIRECT_TYPES or
                    any(self.input(view,r,Source).identity_status != "VERIFIED" for r in spec.source_refs) or
                    not any(e.is_first_hand is True and e.quality_status == "VALIDATED" and e.claim_kind == "FACT"
                        and e.evidence_type in ("COMPANY_DISCLOSURE","OFFICIAL_DOCUMENT","UNKNOWN")
                        and disclosure.quoted_span in self.ledger.raw(e.raw_object_ref).decode("utf-8",errors="replace")
                        for e in evidence)):
                    raise ValueError("DIRECT_PROOF：需要已核验主体的原始正式事实披露；新闻不能默认直接核实")
            if old and (old.company_ref.object_id != company.object_id or old.reporting_period != spec.reporting_period):
                raise ValueError("EXPOSURE_ID：重述同公司同报告期；其他期间使用新ID")
        return self._publish(spec.exposure_id,version,spec,CompanyExposure,validate,
            lambda v:[spec.company_ref,spec.source_disclosure_ref,*spec.evidence_refs,*spec.source_refs,
                *([spec.industry_ref] if spec.industry_ref else []),*([spec.narrative_theme_ref] if spec.narrative_theme_ref else [])])

    def metric(self, version, spec: MetricSpec):
        spec = MetricSpec.model_validate(spec)
        result = metric_result(spec)
        # 持久化输入与派生结果；绝不把未定义比率补成零。
        class Payload(MetricSpec):
            value: float | None
            result_status: str
            metric_reason_codes: tuple[str,...]
        payload = Payload(**spec.model_dump(),value=result[0],result_status=result[1],metric_reason_codes=tuple(result[2]))
        def validate(view,old):
            exposure = self.input(view,spec.exposure_ref,CompanyExposure)
            evidence = self.input(view,spec.evidence_ref,EvidenceVersion)
            if spec.evidence_ref not in exposure.evidence_refs or spec.period != exposure.reporting_period:
                raise ValueError("METRIC_EVIDENCE：指标必须来自该暴露披露及报告期")
            if spec.validation_status == "VERIFIED" and exposure.exposure_type not in ("VERIFIED_DIRECT","SUPPORTED_DIRECT"):
                raise ValueError("METRIC_VERIFICATION：叙事/推断/未知暴露不得携带已核实经济指标")
            if spec.validation_status == "VERIFIED":
                disclosure = self.input(view,exposure.source_disclosure_ref,DisclosureImport)
                if (evidence.claim_kind != "FACT" or evidence.quality_status != "VALIDATED" or
                    evidence.is_first_hand is not True or
                    evidence.evidence_type not in ("COMPANY_DISCLOSURE","OFFICIAL_DOCUMENT","UNKNOWN") or
                    disclosure.disclosure_type not in DIRECT_TYPES or
                    disclosure.review_status != "MANUALLY_VERIFIED" or not disclosure.issuer_identity_verified):
                    raise ValueError("METRIC_FACT_PROOF：VERIFIED需已核验正式披露及一手FACT/VALIDATED证据；新闻保留SUPPORTED/HOLD")
                raw = self.ledger.raw(evidence.raw_object_ref).decode("utf-8",errors="strict")
                for span in (spec.numerator_source_span,spec.denominator_source_span):
                    if span is not None and not span.matches_raw(raw):
                        raise ValueError("METRIC_RAW_PROVENANCE：不可变raw中找不到完整数值及对应原文片段")
            if old and (old.metric_type != spec.metric_type or old.exposure_ref.object_id != spec.exposure_ref.object_id or
                old.period != spec.period or old.scope != spec.scope or old.unit != spec.unit or old.currency != spec.currency):
                raise ValueError("METRIC_ID：同指标ID不能改变类型/公司暴露/期间/范围/单位/币种")
        return self._publish(spec.metric_id,version,payload,ExposureMetric,validate,
            lambda v:[spec.exposure_ref,spec.evidence_ref])

    def exposure_view(self, *, as_of):
        cutoff = TypeAdapter(UTCDateTime).validate_python(as_of)
        view = {key(r):r for r in self.ledger.history(as_of=cutoff)}
        # 报告期已经结束的披露仍可研究；不把effective_to当知识失效日期。
        return sorted(latest(view,CompanyExposure).values(),key=lambda r:r.object_id)

    def metric_view(self, *, as_of):
        cutoff = TypeAdapter(UTCDateTime).validate_python(as_of)
        view = {key(r):r for r in self.ledger.history(as_of=cutoff)}
        exposures = latest(view,CompanyExposure)
        # 新披露版本未重新核验旧指标时保留缺失，而非沿用已被重述的比例。
        return sorted((m for m in latest(view,ExposureMetric).values() if
            m.exposure_ref == type(m.exposure_ref)(**ref(exposures[m.exposure_ref.object_id]))),key=lambda r:r.object_id)

    def coverage(self, report_id, snapshot_ref):
        def build(conn,view,batch):
            snapshot = self.input(view,snapshot_ref,ResearchUniverseSnapshot)
            known = {k:r for k,r in view.items() if r.available_at <= snapshot.as_of}
            exposures = latest(known,CompanyExposure)
            rows, company_types, economic, with_any, inputs = [], {}, set(), set(), [snapshot]
            included = [d for d in snapshot.decisions if d.decision == "INCLUDED"]
            for d in included:
                s = self.input(known,d.security_ref,SecurityVersion)
                company = self.input(known,d.company_ref,Company)
                xs = sorted((x for x in exposures.values() if x.company_ref.object_id == company.object_id),key=lambda x:x.object_id)
                # 已结束报告期仍显示为历史披露事实；范围和期间保留，不伪称当前业务。
                real = [x for x in xs if x.exposure_type in ("VERIFIED_DIRECT","SUPPORTED_DIRECT","INFERRED")]
                types = {x.exposure_type for x in xs}
                company_types.setdefault(company.object_id,set()).update(types or {"UNKNOWN"})
                if xs: with_any.add(company.object_id)
                if real: economic.add(company.object_id)
                missing = []
                if not xs: missing.append("EXPOSURE_MISSING")
                if not real: missing.append("ECONOMIC_EXPOSURE_UNKNOWN")
                if "HOLD" in types: missing.append("EXPOSURE_HOLD")
                if "UNKNOWN" in types: missing.append("EXPOSURE_UNKNOWN")
                rows.append(dict(security_ref=ref(s),company_ref=ref(company),relation_ref=d.relation_ref.model_dump(),
                    board=s.board, exposure_refs=refs(xs),economic_exposure_refs=refs(real),exposure_types=sorted(types),
                    missing_reason_codes=missing))
                inputs.extend([s,company,d.relation_ref,*xs])
            def count(t): return sum(t in ts for ts in company_types.values())
            self.ledger._put(conn,batch,"CoverageReport",report_id,1,
                dict(report_id=report_id,snapshot_ref=ref(snapshot),as_of=snapshot.as_of.isoformat(),
                    research_security_n=len(included),identified_company_n=len(company_types),
                    company_security_mapping_n=len(included),company_with_exposure_n=len(with_any),
                    company_with_economic_exposure_n=len(economic),verified_direct_company_n=count("VERIFIED_DIRECT"),
                    inferred_company_n=count("INFERRED"),unknown_company_n=sum(c not in economic for c in company_types),
                    hold_company_n=count("HOLD"),security_identity_hold_n=len(snapshot.security_hold_refs),
                    rows=rows,policy_version=POLICY),refs(inputs))
        self.ledger._write("P5_COVERAGE:"+report_id,digest([ref(snapshot_ref),POLICY]),build)
        return self.ledger.get(report_id,1)
