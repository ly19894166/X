"""透明相对收益和同时间基准；不估beta，不输出因果收益。"""
from statistics import median, pstdev
from datetime import timezone as fixed_timezone, timedelta
from ..registry.engine import key
from .contracts import MarketObservation, MarketSession, AdjustmentBasis, ProviderQualification, Window


def comparable(a,b):
    return (a.instrument_ref==b.instrument_ref and a.unit==b.unit and a.currency==b.currency
        and a.adjustment_ref==b.adjustment_ref and a.adjustment_type==b.adjustment_type
        and a.source_ref==b.source_ref and a.provider_ref==b.provider_ref)


def price_return(points):
    if len(points)!=2: return None
    a,b=points
    if (not comparable(a,b) or any(o.value is None or o.quality_status!='QUALIFIED' for o in points)
        or a.value<=0 or a.window.end>=b.window.end): return None
    return b.value/a.value-1


def observation_key(o):
    from .freshness import semantic_scope
    return semantic_scope(o)


def quality(o,view,at,rules,current=False):
    errors=[]
    provider=view[key(o.provider_ref)]
    if provider.qualification_status!='PROVIDER_QUALIFIED': errors.append('PROVIDER_HOLD')
    if o.quality_status!='QUALIFIED' or o.value is None: errors.append('PRICE_STALE' if o.quality_status=='STALE' else 'OBSERVATION_UNQUALIFIED')
    if current:
        session=view[key(o.session_ref)]
        if not any(w.start<=at<=w.end for w in session.intervals):
            errors.append('MARKET_CLOSED' if session.intervals else 'NO_CURRENT_SESSION')
        if (at-o.observed_at).total_seconds()>rules.max_price_age_seconds: errors.append('STALE_PRICE')
    return errors


def volume_multiple(current,baselines,view,anchor,rules):
    if current is None or current.value is None or current.quality_status!='QUALIFIED': return None,0
    session=view[key(current.session_ref)]
    timezone=fixed_timezone(timedelta(minutes=session.utc_offset_minutes))
    start=current.window.start.astimezone(timezone); end=current.window.end.astimezone(timezone)
    days=set(); valid=[]
    for old in baselines:
        if (not comparable(current,old) or old.observation_type!=current.observation_type or old.value is None
            or old.value<0 or old.quality_status!='QUALIFIED' or old.window.end>=anchor): continue
        old_session=view[key(old.session_ref)]
        if old_session.timezone!=session.timezone: continue
        old_timezone=fixed_timezone(timedelta(minutes=old_session.utc_offset_minutes))
        os=old.window.start.astimezone(old_timezone); oe=old.window.end.astimezone(old_timezone)
        if (os.timetz().replace(tzinfo=None)!=start.timetz().replace(tzinfo=None)
            or oe.timetz().replace(tzinfo=None)!=end.timetz().replace(tzinfo=None)
            or old.window.end-old.window.start!=current.window.end-current.window.start or os.date() in days): continue
        days.add(os.date()); valid.append(old.value)
    if len(valid)<rules.min_volume_samples or median(valid)<=0: return None,len(valid)
    return current.value/median(valid),len(valid)


def diffusion(composition,pairs,benchmark_return,view):
    expected={}
    for r in composition.component_security_refs:
        security=view[key(r)]
        expected.setdefault(security.company_ref.object_id,set()).add(security.object_id)
    values={}
    for a,b in pairs:
        company=view[key(a.instrument_ref)].company_ref.object_id
        if company in expected and a.instrument_ref.object_id in expected[company]:
            value=price_return([a,b])
            if value is not None and benchmark_return is not None:
                values.setdefault(company,[]).append(value-benchmark_return)
    per_company=[median(v) for v in values.values()]
    complete=composition.coverage_status=='COMPLETE_DECLARED_SCOPE' and len(values)==len(expected) and bool(expected)
    positive=[max(v,0.0) for v in per_company]
    return dict(eligible_company_count=len(expected),observed_company_count=len(values),
        reacting_company_count=sum(v>0 for v in per_company) if complete else None,
        breadth_ratio=sum(v>0 for v in per_company)/len(expected) if complete else None,
        median_relative_return=median(per_company) if complete else None,
        dispersion=pstdev(per_company) if complete else None,
        leader_concentration=max(positive)/sum(positive) if complete and sum(positive)>0 else None,
        denominator_source=dict(object_id=composition.object_id,version=composition.version),
        coverage='COMPLETE_DECLARED_SCOPE' if complete else 'INCOMPLETE')


def classify_dimensions(f,*,rules,thesis,novelty,dissemination,buyer,nonreaction,cause,remaining_diffusion,sessions,counter):
    """有名联合条件，不把涨幅转换成定价百分比；阈值未校准。"""
    ar=f.industry_relative_return
    breadth=f.diffusion.breadth_ratio if f.diffusion else None
    ratios=[v for v in (f.volume_ratio,f.amount_ratio) if v is not None]
    flow=max(ratios) if ratios else None
    recognition='UNKNOWN'; reasons={}
    if dissemination=='YES':
        recognition='EARLY_RECOGNITION'
        if breadth is not None and breadth>=rules.broad_diffusion:
            recognition='BROAD_RECOGNITION'
            if breadth>=rules.consensus_diffusion and sessions>=rules.sustained_sessions:
                recognition='CONSENSUS'
        elif ar is not None and ar>=rules.noticeable_relative and flow is not None and flow>=rules.abnormal_volume:
            recognition='PARTIAL_RECOGNITION'
    elif dissemination=='NO' and ar is not None and abs(ar)<rules.low_reaction:
        recognition='UNRECOGNIZED'
    reasons['recognition']=['DISSEMINATION_'+dissemination,'OBSERVED_DIFFUSION_AND_RELATIVE_REACTION']
    crowd='UNKNOWN'
    if ar is not None and flow is not None and breadth is not None:
        crowd='LOW'
        if flow>=rules.abnormal_volume and (ar>=rules.large_relative or breadth>=rules.broad_diffusion): crowd='HIGH'
        elif flow>=rules.abnormal_volume or ar>=rules.large_relative: crowd='MEDIUM'
        if crowd=='HIGH' and flow>=rules.extreme_volume and sessions>=rules.sustained_sessions: crowd='EXTREME'
    reasons['crowding']=['RELATIVE_RETURN_FLOW_DIFFUSION_DURATION_JOINT','NOT_PRICE_LIMIT_CLASSIFICATION']
    price_in='UNKNOWN'
    if ar is not None and novelty!='UNDETERMINED' and recognition!='UNKNOWN' and crowd!='UNKNOWN':
        if recognition in ('BROAD_RECOGNITION','CONSENSUS') and sessions>=rules.sustained_sessions and crowd in ('HIGH','EXTREME'):
            price_in='VERY_HIGH' if recognition=='CONSENSUS' and crowd=='EXTREME' else 'HIGH'
        elif nonreaction and nonreaction.recognition_gap:
            price_in='LOW'
        elif ar>=rules.noticeable_relative and flow is not None and flow>=rules.abnormal_volume and recognition=='PARTIAL_RECOGNITION':
            price_in='MEDIUM'
    reasons['price_in']=['NOVELTY_RECOGNITION_REACTION_DURATION_CROWDING','NO_RETURN_TO_PRICE_IN_PERCENT']
    reversal='UNKNOWN'
    if price_in in ('HIGH','VERY_HIGH') and crowd in ('HIGH','EXTREME'):
        reversal='EXTREME' if crowd=='EXTREME' and not buyer else 'HIGH'
    elif crowd!='UNKNOWN' and ar is not None and cause!='CAUSE_UNKNOWN' and f.pre_event_return is not None:
        reversal='MEDIUM' if f.pre_event_return>rules.large_relative or cause in ('MULTI_CAUSE','ALTERNATIVE_CAUSE_STRONG') else 'LOW'
    if (crowd in ('MEDIUM','HIGH','EXTREME') and
        ((f.volatility is not None and f.volatility>=rules.large_relative)
         or (f.breadth_delta is not None and f.breadth_delta < -rules.low_reaction))):
        reversal='HIGH' if reversal!='EXTREME' else reversal
    reasons['reversal']=['PRICE_IN_CROWDING_PRETREND_ALTERNATIVE_CAUSE_NEXT_BUYER','NOT_STOP_LOSS']
    edge='UNKNOWN'
    if counter or cause=='ALTERNATIVE_CAUSE_STRONG':
        edge='NEGATIVE'
    elif price_in in ('HIGH','VERY_HIGH') and crowd in ('HIGH','EXTREME'):
        edge='THIN' if buyer else 'NONE'
    elif not buyer:
        edge='NONE' if price_in in ('MEDIUM','HIGH','VERY_HIGH') else 'UNKNOWN'
    elif (thesis in ('HIGH','VERY_HIGH') and novelty in ('R3','R4') and nonreaction and nonreaction.recognition_gap
          and remaining_diffusion=='YES' and cause=='CURRENT_EVENT_DOMINANT' and crowd in ('LOW','MEDIUM') and reversal=='LOW'):
        edge='POSITIVE'
    reasons['remaining_edge']=['THESIS_NOVELTY_GAP_BUYER_DIFFUSION_MINUS_RISK_AND_MISSINGNESS','NOT_100_MINUS_PRICE_IN']
    return recognition,price_in,crowd,edge,reversal,reasons
