"""Phase 8 A1: mode-qualified current-knowledge identities, never stored latest refs."""
from datetime import timezone
from .contracts import (PricingEnvelope, MarketObservation, ProviderQualification, PricingContext,
    BenchmarkComposition, AdjustmentBasis, MarketSession, PricingPolicy)


def mode_scope(mode):
    # Offline fixtures and Mock forward are compatible; neither qualifies real forward.
    return 'FIXTURE_FORWARD' if mode in ('ENGINEERING_FIXTURE','MOCK_FORWARD') else mode


def semantic_scope(obj):
    if isinstance(obj,MarketObservation):
        value=(obj.instrument_ref.object_id,obj.observation_type,obj.window.start,obj.window.end,obj.source_ref.object_id)
    elif isinstance(obj,ProviderQualification):
        value=(obj.provider,obj.source_ref.object_id,obj.scope)
    elif isinstance(obj,PricingContext):
        value=(obj.event_ref.object_id,obj.security_ref.object_id)
    elif isinstance(obj,BenchmarkComposition):
        value=(obj.benchmark_ref.object_id,obj.industry_ref.object_id if obj.industry_ref else None)
    elif isinstance(obj,AdjustmentBasis):
        value=(obj.instrument_ref.object_id,'PRIMARY_PRICE_BASIS')
    elif isinstance(obj,MarketSession):
        # Existing fixtures declare separate historical periods. Calendar version is
        # revision metadata, not scope. Explicit scope is preferred for new providers.
        coverage=tuple(sorted({w.start.astimezone(timezone.utc).date() for w in obj.intervals}))
        value=(obj.instrument_ref.object_id,obj.session_scope or coverage)
    elif isinstance(obj,PricingPolicy):
        value=(obj.policy_version,)
    else:
        value=(obj.object_id,)
    return (type(obj).__name__,mode_scope(obj.pricing_mode),*value)


def session_scope_conflict(a,b):
    """Legacy overlapping/unspecified session ranges cannot prove independence."""
    if not isinstance(a,MarketSession) or a.instrument_ref.object_id!=b.instrument_ref.object_id: return False
    if a.session_scope is not None and b.session_scope is not None: return a.session_scope==b.session_scope
    if not a.intervals or not b.intervals: return True
    return any(x.start<y.end and y.start<x.end for x in a.intervals for y in b.intervals)

def newer_inputs(view,obj,pricing_mode):
    if not isinstance(obj,PricingEnvelope) or mode_scope(obj.pricing_mode)!=mode_scope(pricing_mode): return []
    return [o for o in view.values() if type(o) is type(obj)
        and mode_scope(o.pricing_mode)==mode_scope(pricing_mode)
        and o.available_at>obj.available_at
        and (semantic_scope(o)==semantic_scope(obj) or o.object_id==obj.object_id or session_scope_conflict(o,obj))]
