"""有限路径构建；输入固定版本，输出一个原子、不可变的计算批次。"""
from datetime import timedelta, timezone
from ..contracts import EventVersion, EvidenceVersion
from ..contracts.common import VersionRef, TypeAdapter, UTCDateTime
from ..ledger.store import ref, digest
from ..ledger.contracts import OriginClusterVersion
from ..ontology.contracts import (ImpactVariable, IndustrySegment, IndustryImpactCandidate,
    IndustryResolution, NarrativeTheme)
from ..ontology.engine import combine_impact_directions
from ..exposures.contracts import CompanyExposure, DisclosureImport
from ..registry.contracts import Company, SecurityVersion, CompanySecurityRelation, ResearchUniverseSnapshot
from ..registry.engine import Registry, key, refs, latest, identity_at, effective
from ..states.contracts import EventStateSnapshot
from .contracts import BuildRequest, POLICY


class TransmissionGraph:
    def __init__(self, ledger):
        self.ledger = ledger
        self.registry = Registry(ledger)

    def build(self, history_id, version, request):
        request = BuildRequest.model_validate(request)
        if request.as_of > self.ledger.now():
            raise ValueError("GRAPH_PIT：不能构建未来知识")

        def build(conn, full, batch):
            cutoff = request.as_of
            view = {k:r for k,r in full.items() if r.available_at <= cutoff}
            def get(r, cls):
                return self.registry.input(view, r, cls)
            event = get(request.event_ref, EventVersion)
            if latest(view, EventVersion)[event.object_id] != event:
                raise ValueError("GRAPH_EVENT_STALE：当前计算必须显式引用截至时点的事件版本")
            snapshot = get(request.snapshot_ref, ResearchUniverseSnapshot)
            previous = [r for r in full.values() if r.object_id == history_id]
            old = max(previous, key=lambda r:r.version, default=None)
            if (old and type(old).__name__ != "MappingHistory") or version != (old.version+1 if old else 1):
                raise ValueError("GRAPH_VERSION：必须追加下一历史版本")
            if old and old.request.event_ref.object_id != event.object_id:
                raise ValueError("GRAPH_HISTORY_ID：历史身份不得更换事件")
            if old and (old.available_at > cutoff or old.as_of > cutoff):
                raise ValueError("GRAPH_HISTORY_PIT：历史修订不得倒退知识时间")

            # 递归验证固定输入闭包；不使用当前产业有效期判断历史披露是否合法。
            def closure(objects):
                found, pending = {}, list(objects)
                while pending:
                    obj = pending.pop()
                    if key(obj) in found:
                        continue
                    found[key(obj)] = obj
                    for r in obj.input_version_refs:
                        child = view.get(key(r))
                        if child is None:
                            raise ValueError("GRAPH_PIT_REFERENCE：节点前提在截止点不可知")
                        pending.append(child)
                return list(found.values())

            def impact_evidence(value):
                # 本边的证据只沿经济前提，不把Event全量材料当成此边的支持。
                found, pending = {}, [value]
                while pending:
                    node=pending.pop()
                    for r in node.evidence_refs:
                        ev=get(r,EvidenceVersion); found[key(ev)]=ev
                    for r in node.premise_refs:
                        obj=view[key(r)]
                        if isinstance(obj,ImpactVariable): pending.append(obj)
                        elif isinstance(obj,EvidenceVersion): found[key(obj)]=obj
                return list(found.values())

            exposures = [get(r, CompanyExposure) for r in request.exposure_refs]
            for ex in exposures:
                if latest(view, CompanyExposure)[ex.object_id] != ex:
                    raise ValueError("GRAPH_EXPOSURE_STALE：不得绕过已知重述")
            states = [s for s in view.values() if isinstance(s,EventStateSnapshot) and s.event_ref.object_id == event.object_id]
            state = max(states, key=lambda r:(r.available_at,r.object_id), default=None)
            fact = state.fact_state if state else event.fact_state
            holds = ["HOLD_HISTORICAL_UNIVERSE_COVERAGE", "HOLD_REAL_COMPANY_EXPOSURE_COVERAGE"]
            if fact == "INVALIDATED":
                holds.append("CORE_EVENT_INVALIDATED")
            if state and state.lifecycle_status == "ARCHIVED":
                holds.append("EVENT_ARCHIVED")

            # 快照必须已发布；期间身份变更需生成新快照，不能沿用旧证券归属。
            companies = identity_at(view,Company,cutoff)
            securities = identity_at(view,SecurityVersion,cutoff)
            relations = identity_at(view,CompanySecurityRelation,cutoff)
            eligible = []
            day = cutoff.astimezone(timezone(timedelta(hours=8))).date()
            for d in snapshot.decisions:
                if d.decision != "INCLUDED":
                    continue
                s,c,r = get(d.security_ref,SecurityVersion),get(d.company_ref,Company),get(d.relation_ref,CompanySecurityRelation)
                if (securities.get(s.object_id) != s or companies.get(c.object_id) != c or relations.get(r.object_id) != r
                    or not all(effective(obj,cutoff) for obj in (s,c,r)) or s.listing_status != "LISTED"
                    or s.security_type != "A_SHARE" or s.listing_date is None or s.listing_date > day
                    or (s.delisting_date and s.delisting_date <= day)):
                    holds.append("SNAPSHOT_REFRESH_REQUIRED:"+s.object_id)
                    continue
                if sum((other.exchange,other.security_code)==(s.exchange,s.security_code) and effective(other,cutoff)
                       and other.listing_status=="LISTED" for other in securities.values()) != 1:
                    holds.append("SECURITY_IDENTITY_COLLISION:"+s.object_id)
                    continue
                eligible.append((c,s,r))

            clusters = [r for r in view.values() if isinstance(r,OriginClusterVersion)]
            def origins(evidence):
                groups = []
                for cluster in sorted(clusters,key=lambda r:(r.available_at,r.object_id,r.version)):
                    members = set(cluster.member_origin_ids)
                    if cluster.basis == "CONFIRMED_SAME_ORIGIN":
                        joined = [g for g in groups if g & members]
                        groups = [g for g in groups if not g & members] + [members.union(*joined)]
                    else:
                        for member in members:
                            if not any(member in g for g in groups):
                                groups.append({member})
                ids = {e.origin_cluster_id for e in evidence}
                touched = [g for g in groups if g & ids]
                used = [c for c in clusters if set(c.member_origin_ids) & set().union(ids,*touched)]
                return sorted({min(g) for g in touched} | {i for i in ids if not any(i in g for g in touched)}), used

            outputs, path_payloads, all_inputs = [], [], [event,snapshot,*exposures]
            if state:
                all_inputs.append(state)
            def emit(nodes, edge_specs, ex, c, s, relation, candidate=None):
                world = "ECONOMIC" if candidate else "NARRATIVE"
                direction = candidate.impact_direction if candidate else "UNKNOWN"
                depth = len([n for n in nodes if isinstance(n,ImpactVariable)])+1 if candidate else 0
                base_objects = closure([*nodes,relation,*([candidate] if candidate else []),*([state] if state else [])])
                evidence = [x for x in base_objects if isinstance(x,EvidenceVersion)]
                # Origin 仅对应事件/影响证据；年报与证券身份材料不增加事件支持。
                event_evidence = [e for e in evidence if any(key(e)==key(r) for r in event.evidence_refs)]
                group_ids, cluster_inputs = origins(event_evidence)
                base_objects += cluster_inputs
                pid = history_id+":PATH:"+digest([world,[ref(n) for n in nodes],ref(candidate) if candidate else None])[:24]
                edge_refs = []
                for i,(left,right) in enumerate(zip(nodes,nodes[1:])):
                    edge_id = pid+":EDGE:"+str(i)
                    edge_type,inference,mechanism = edge_specs[i]
                    basis = candidate if isinstance(right,IndustrySegment) and candidate else relation if isinstance(right,SecurityVersion) else ex if isinstance(right,Company) else right
                    edge_evidence = impact_evidence(basis) if isinstance(basis,ImpactVariable) else [get(r,EvidenceVersion) for r in basis.evidence_refs]
                    self.ledger._put(conn,batch,"EdgeVersion",edge_id,version,
                        dict(edge_id=edge_id,from_ref=ref(left),to_ref=ref(right),edge_type=edge_type,world=world,
                            impact_direction=direction,mechanism_zh=mechanism,inference_type=inference,
                            origin_cluster_ids=group_ids,as_of=cutoff.isoformat(),provenance_zh="固定节点及其证据闭包；无关键词业务推断",
                            evidence_refs=refs(edge_evidence),policy_version=POLICY),refs(base_objects))
                    edge_refs.append(dict(object_id=edge_id,version=version))
                reasons = []
                if depth > 3:
                    reasons.append("ECONOMIC_DEPTH_REVIEW_REQUIRED")
                if candidate and not effective(ex,cutoff):
                    reasons.append("HISTORICAL_EXPOSURE_CONTINUITY_UNVERIFIED")
                if candidate and ex.exposure_type in ("UNKNOWN","HOLD"):
                    reasons.append("EXPOSURE_UNVERIFIED")
                if candidate and candidate.mapping_status == "HOLD":
                    reasons.append("INDUSTRY_MAPPING_HOLD")
                if fact in ("CONTRADICTED","INVALIDATED"):
                    reasons.append("EVENT_"+fact)
                research = "HOLD" if any(x != "ECONOMIC_DEPTH_REVIEW_REQUIRED" for x in reasons) else "DEGRADED" if reasons else "CANDIDATE"
                payload = dict(path_id=pid,event_ref=ref(event),company_ref=ref(c),security_ref=ref(s),exposure_ref=ref(ex),
                    exposure_type=ex.exposure_type,world=world,node_refs=[ref(n) for n in nodes],edge_refs=edge_refs,
                    graph_hop_count=len(edge_refs),economic_depth=depth,impact_direction=direction,
                    benefit_level=("L1_DIRECT" if depth==1 else "L2_FIRST_ORDER" if depth==2 else "L3_SECOND_ORDER") if candidate else "N1_NARRATIVE",
                    mapping_state=("CONTRADICTED" if fact=="CONTRADICTED" else "PLAUSIBLE") if candidate else "NARRATIVE_ONLY",
                    research_status=research,mechanism_zh=candidate.mechanism_zh if candidate else ex.mechanism_zh,
                    uncertainty_zh="经济结果仅为条件候选，历史暴露不证明当前持续；叙事不证明经济收益",
                    candidate_ref=ref(candidate) if candidate else None,origin_cluster_refs=refs(cluster_inputs),origin_group_ids=group_ids,
                    as_of=cutoff.isoformat(),provenance_zh="复用Phase4候选与Phase5固定暴露、披露及证券身份",
                    evidence_refs=refs(evidence),reason_codes=reasons,policy_version=POLICY)
                self.ledger._put(conn,batch,"TransmissionPath",pid,version,payload,[*refs(base_objects),*edge_refs])
                outputs.append(dict(object_id=pid,version=version)); path_payloads.append(payload)
                all_inputs.extend(base_objects)

            for rr in sorted(request.resolution_refs,key=key):
                resolution = get(rr,IndustryResolution)
                impact = get(resolution.impact_ref,ImpactVariable)
                all_inputs.append(resolution)
                if impact.event_ref != request.event_ref:
                    raise ValueError("GRAPH_EVENT：产业候选不属于指定固定事件")
                # 仅展开既有显式前提。每条分支有限，超深不删；禁止推导新影响或新产业。
                def chains(value, visiting=()):
                    if len(visiting) >= 128:
                        raise ValueError("HOLD_GRAPH_RESOURCE_BOUND：显式前提超过128层，保留输入待审")
                    if value.object_id in visiting:
                        raise ValueError("GRAPH_CYCLE：经济前提循环")
                    parents = [get(r,ImpactVariable) for r in value.premise_refs if isinstance(view.get(key(r)),ImpactVariable)]
                    if not parents:
                        return [[value]]
                    result=[]
                    for parent in sorted(parents,key=key):
                        if parent.event_ref != request.event_ref:
                            raise ValueError("GRAPH_PREMISE：跨事件前提必须先正式核验")
                        for chain in chains(parent,(*visiting,value.object_id)):
                            result.append([*chain,value])
                            if len(result) > 1024:
                                raise ValueError("HOLD_GRAPH_RESOURCE_BOUND：显式路径超过1024条，保留输入待审")
                    return result
                impact_chains=chains(impact)
                for cr in resolution.candidate_refs:
                    candidate=get(cr,IndustryImpactCandidate)
                    if candidate.impact_ref != resolution.impact_ref or candidate.ontology_ref != resolution.ontology_ref:
                        raise ValueError("GRAPH_RESOLUTION：候选与解析版本不一致")
                    if candidate.industry_ref is None:
                        holds.append("INDUSTRY_UNRESOLVED"); continue
                    industry=get(candidate.industry_ref,IndustrySegment)
                    if fact=="INVALIDATED" or (state and state.lifecycle_status=="ARCHIVED"):
                        continue
                    matched=False
                    for ex in sorted(exposures,key=key):
                        if ex.industry_ref != candidate.industry_ref or ex.exposure_type=="NARRATIVE_ASSOCIATION":
                            continue
                        if ex.business_role != candidate.path_role:
                            holds.append("EXPOSURE_ROLE_MISMATCH:"+ex.object_id); continue
                        for c,s,relation in eligible:
                            if ex.company_ref.object_id != c.object_id:
                                continue
                            matched=True
                            for chain in impact_chains:
                                nodes=[event,*chain,industry,ex,c,s]
                                specs=[("CAUSES",x.observation_kind,x.mechanism_zh) for x in chain]
                                specs += [("HARMS" if candidate.impact_direction=="NEGATIVE" else "BENEFITS" if candidate.impact_direction=="POSITIVE" else "CAUSES","HYPOTHESIS",candidate.mechanism_zh),
                                    ("HAS_EXPOSURE","STRUCTURAL",ex.mechanism_zh),("EXPOSURE_OF","STRUCTURAL",ex.description_zh),
                                    ("HAS_SECURITY","STRUCTURAL","固定公司证券归属；证券不复制业务事实")]
                                emit(nodes,specs,ex,c,s,relation,candidate)
                    if not matched:
                        holds.append("NO_ELIGIBLE_EXPOSURE:"+industry.object_id)
            for ex in sorted(exposures,key=key):
                if ex.exposure_type != "NARRATIVE_ASSOCIATION" or ex.narrative_theme_ref is None:
                    continue
                theme=get(ex.narrative_theme_ref,NarrativeTheme)
                if theme.event_ref != request.event_ref:
                    raise ValueError("GRAPH_THEME：主题不属于指定事件版本")
                for c,s,relation in eligible:
                    if ex.company_ref.object_id == c.object_id:
                        disclosure=get(ex.source_disclosure_ref,DisclosureImport)
                        if (not ex.reviewed_by or theme.canonical_name_zh not in disclosure.quoted_span or
                            not any(name in disclosure.quoted_span for name in (c.canonical_name_zh,c.legal_name))):
                            holds.append("NARRATIVE_ASSOCIATION_PROOF_REQUIRED:"+ex.object_id)
                            continue
                        emit([event,theme,ex,c,s],[("EVOKES_THEME","NARRATIVE",theme.description_zh),
                            ("HAS_ASSOCIATION","NARRATIVE",ex.mechanism_zh),("MARKET_ASSOCIATED_WITH","NARRATIVE",ex.description_zh),
                            ("HAS_SECURITY","STRUCTURAL","固定证券归属，仅供研究反查")],ex,c,s,relation)

            assessment_refs=[]
            for company_key in sorted({(p["company_ref"]["object_id"],p["company_ref"]["version"]) for p in path_payloads}):
                ps=[p for p in path_payloads if (p["company_ref"]["object_id"],p["company_ref"]["version"])==company_key]
                def pr(p): return dict(object_id=p["path_id"],version=version)
                economic=[p for p in ps if p["world"]=="ECONOMIC"]
                positive=[p for p in economic if p["impact_direction"] in ("POSITIVE","MIXED")]
                negative=[p for p in economic if p["impact_direction"] in ("NEGATIVE","MIXED")]
                net=combine_impact_directions([p["impact_direction"] for p in economic]) if economic else "UNKNOWN"
                if any(p["research_status"]=="HOLD" for p in economic): net="HOLD"
                aid=history_id+":ASSESS:"+company_key[0]
                counter=sorted(negative,key=lambda p:(p["economic_depth"],p["path_id"]))
                self.ledger._put(conn,batch,"MappingAssessment",aid,version,dict(company_ref=ps[0]["company_ref"],
                    path_refs=[pr(p) for p in ps],positive_path_refs=[pr(p) for p in positive],negative_path_refs=[pr(p) for p in negative],
                    narrative_path_refs=[pr(p) for p in ps if p["world"]=="NARRATIVE"],counter_path_refs=[pr(p) for p in counter],
                    strongest_counter_path_ref=pr(counter[0]) if counter else None,net_effect_state=net,
                    as_of=cutoff.isoformat(),provenance_zh="保留所有正负机制；按深度及固定ID选择展示反路径，不计算Alpha分数",policy_version=POLICY),
                    [ps[0]["company_ref"],*[pr(p) for p in ps]])
                assessment_refs.append(dict(object_id=aid,version=version))
            self.ledger._put(conn,batch,"MappingHistory",history_id,version,dict(request=request.model_dump(mode="json"),
                path_refs=outputs,assessment_refs=assessment_refs,previous_history_ref=ref(old) if old else None,
                hold_reasons=sorted(set(holds)),as_of=cutoff.isoformat(),provenance_zh="固定输入完整记录；修订追加，旧回放不变",policy_version=POLICY),
                [*refs(all_inputs),*outputs,*assessment_refs,*([ref(old)] if old else [])])
            self.ledger.fault("after_transmission_graph")
        self.ledger._write(f"P6:{history_id}:{version}",digest(request.model_dump(mode="json")),build)
        return self.ledger.get(history_id,version)

    def reverse(self, identity, *, as_of, active_only=True):
        """只读既有最新计算；同源分组返回原路径，不设置次数权重。"""
        cutoff=TypeAdapter(UTCDateTime).validate_python(as_of)
        view={key(r):r for r in self.ledger.history(as_of=cutoff)}
        from .contracts import MappingHistory
        histories=latest(view,MappingHistory)
        states=[r for r in view.values() if isinstance(r,EventStateSnapshot)]
        result=[]
        for h in sorted(histories.values(),key=key):
            state=max((s for s in states if s.event_ref.object_id==h.request.event_ref.object_id),key=lambda s:(s.available_at,s.object_id),default=None)
            if active_only and state and (state.lifecycle_status=="ARCHIVED" or state.fact_state=="INVALIDATED"):
                continue
            for r in h.path_refs:
                p=view[key(r)]
                if identity in (p.company_ref.object_id,p.security_ref.object_id):
                    result.append(p)
        groups={}
        for p in result:
            group=(tuple(p.origin_group_ids) or (p.event_ref.object_id,),p.company_ref.object_id,p.security_ref.object_id,p.world,p.impact_direction)
            groups.setdefault(group,[]).append(p)
        def stale(ps):
            reasons=set()
            current_ex=latest(view,CompanyExposure)
            current_events=latest(view,EventVersion)
            current_securities=identity_at(view,SecurityVersion,cutoff)
            for p in ps:
                if key(current_ex[p.exposure_ref.object_id]) != key(p.exposure_ref): reasons.add("EXPOSURE_RECOMPUTE_REQUIRED")
                if key(current_events[p.event_ref.object_id]) != key(p.event_ref): reasons.add("EVENT_RECOMPUTE_REQUIRED")
                if key(current_securities[p.security_ref.object_id]) != key(p.security_ref): reasons.add("SECURITY_RECOMPUTE_REQUIRED")
                if any(isinstance(c,OriginClusterVersion) and c.basis=="CONFIRMED_SAME_ORIGIN" and c.available_at>p.as_of
                       and set(c.member_origin_ids)&set(p.origin_group_ids) for c in view.values()): reasons.add("ORIGIN_RECOMPUTE_REQUIRED")
            return sorted(reasons)
        return [dict(origin_group_ids=list(g[0]),paths=ps,recompute_reasons=stale(ps)) for g,ps in sorted(groups.items())]

    def alternatives(self, company_id, *, industry_ref, as_of):
        """仅检索已保存、同一固定产业的其他公司路径，不生成替代标的理由。"""
        cutoff=TypeAdapter(UTCDateTime).validate_python(as_of)
        from .contracts import MappingHistory
        view={key(r):r for r in self.ledger.history(as_of=cutoff)}
        paths=[view[key(r)] for h in latest(view,MappingHistory).values() for r in h.path_refs]
        return sorted((p for p in paths if p.world=="ECONOMIC" and p.company_ref.object_id != company_id
            and industry_ref in p.node_refs),key=key)
