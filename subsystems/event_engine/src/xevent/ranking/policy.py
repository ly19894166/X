"""Transparent ordered rules. No market-return score, training or account inputs."""
from .contracts import RankDimensions, RankRules, OrdinalDimension, BETA_CORE, GRADE_ORDER


def unknown_dimensions(d, rules):
    return [name for name in rules.dimension_order if str(getattr(d,name)) in ('UNKNOWN','HOLD','CAUSE_UNKNOWN')]


def classify(dimensions, rules, *, hard=(), reject=(), countercase=(), failures=(), soft=()):
    d=RankDimensions.model_validate(dimensions)
    rules=RankRules.model_validate(rules)
    if reject: return 'REJECT','REJECT',tuple(sorted(set(reject)))
    if hard: return 'WATCH','HOLD',tuple(sorted(set(hard)))
    if d.world=='NARRATIVE': return 'WATCH','WATCH',('NARRATIVE_ONLY_FOR_ECONOMIC_ALPHA',)
    if d.research_status!='MOCK_PASS' or d.decision_source in ('HOLD_GATE','UNKNOWN'):
        return 'WATCH','HOLD',('RESEARCH_HOLD',)
    if d.final_choice not in ('TARGET','ALT'): return 'REJECT','REJECT',('RESEARCH_NULL',)
    if d.red_team_status in ('TARGET_INVALIDATED','NULL_PREFERRED'):
        return 'REJECT','REJECT',('RED_TEAM_INVALIDATED',)
    if d.red_team_status=='INCOMPLETE' or not countercase or not failures:
        return 'WATCH','HOLD',('RED_TEAM_OR_FAILURE_CONDITION_INCOMPLETE',)
    if d.pricing_status!='ENGINEERING_ONLY': return 'WATCH','HOLD',('PRICING_HOLD',)
    if d.price_in_band in rules.high_price_bands and d.remaining_edge in rules.no_edge_bands:
        return 'OVERPRICED','OVERPRICED',('HIGH_PRICING_NO_REMAINING_EDGE_NOT_SHORT',)
    # Explicit BETA exception: company-specific Next Buyer is optional; core pricing is not.
    if d.systemic_basis=='BROAD_SECTOR_RELATIVE_NEUTRAL':
        missing=[n for n in BETA_CORE if getattr(d,n) in ('UNKNOWN','HOLD')]
        if missing: return 'WATCH','WATCH',tuple('BLOCKING_UNKNOWN:'+n for n in missing)
    # Beta requires explicit broad sector transmission, not just failed Alpha eligibility.
    if (d.systemic_basis=='BROAD_SECTOR_RELATIVE_NEUTRAL' and d.purity=='LOW'
        and d.thesis_strength in rules.alpha2_thesis and d.remaining_edge not in ('NONE','NEGATIVE','HOLD')
        and d.reversal_risk!='EXTREME'):
        return 'BETA','VALID',('SYSTEMIC_EXPOSURE_NOT_COMPANY_SPECIFIC_ALPHA',)
    unknown=unknown_dimensions(d,rules)
    blocking=[n for n in unknown if rules.unknown_policy[n]=='BLOCKING_UNKNOWN']
    if blocking: return 'WATCH','WATCH',tuple('BLOCKING_UNKNOWN:'+n for n in blocking)
    alpha_common=(d.remaining_edge in rules.alpha2_edges and d.thesis_strength in rules.alpha2_thesis
        and d.next_buyer_status in rules.alpha2_buyers
        and d.price_in_band in rules.alpha2_risks and d.crowding_band in rules.alpha2_risks
        and d.reversal_risk in rules.alpha2_risks and d.alternative_cause_status!='ALTERNATIVE_CAUSE_STRONG')
    if not alpha_common: return 'WATCH','WATCH',('ALPHA_DIMENSIONS_NOT_SUFFICIENT',)
    strict=(d.exposure_type=='VERIFIED_DIRECT' and d.remaining_edge in rules.alpha1_edges and d.thesis_strength in rules.alpha1_thesis
        and d.next_buyer_status in rules.alpha1_buyers and d.purity=='HIGH'
        and all(getattr(d,n) in rules.alpha1_risks for n in ('price_in_band','crowding_band','reversal_risk'))
        and d.alternative_cause_status=='CURRENT_EVENT_DOMINANT'
        and d.red_team_status in ('UNCHANGED','ALT_STRONGER') and not unknown and not soft)
    if strict: return 'ALPHA1','VALID',('STRONG_ECONOMIC_DIMENSIONS_ENGINEERING_ONLY',)
    why=['POSITIVE_OR_CONDITIONALLY_THIN_EDGE']
    if d.remaining_edge=='THIN': why.append('THIN_REQUIRES_VALID_THESIS_SPECIFIC_BUYER_AND_NONEXTREME_RISK')
    why.extend('SOFT_UNKNOWN:'+n for n in unknown)
    why.extend(soft)
    return 'ALPHA2','VALID',tuple(sorted(set(why)))


def ordinal_dimensions(d, rules):
    values=[]
    for name in rules.dimension_order:
        value=str(getattr(d,name)); order=rules.ordinal_orders[name]
        known=value in order
        values.append(OrdinalDimension(dimension=name,raw_value=value,
            ordinal=order.index(value) if known else None,
            knowledge='KNOWN' if known else rules.unknown_policy[name]))
    return tuple(values)


def sort_key(vector, rules):
    state=('VALID','WATCH','OVERPRICED','REJECT','HOLD').index(vector.processing_state)
    # Unknown is its own knowledge bucket, never a substituted numeric measurement.
    dimensions=tuple((0,x.ordinal) if x.ordinal is not None else (1,0) for x in vector.dimensions)
    return state,rules.grade_order.index(vector.candidate_grade),dimensions,tuple(vector.tie_break)


def grade_change(before, after):
    if before is None: return 'NEW'
    if before==after: return 'UNCHANGED'
    if after=='REJECT': return 'REJECTED'
    if after=='OVERPRICED': return 'OVERPRICED'
    return 'UPGRADED' if GRADE_ORDER.index(after)<GRADE_ORDER.index(before) else 'DOWNGRADED'
