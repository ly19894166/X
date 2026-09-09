"""Phase8新增PIT/模式/时间资格测试。"""
from datetime import timedelta
from types import SimpleNamespace
import pytest
from pydantic import ValidationError, TypeAdapter
from test_phase8_pricing import seed,w,pub,get,revise,assess,replace_ref,new_analysis
from xevent.pricing.fixture import observation
from xevent.pricing.contracts import *
from xevent.pricing.engine import event_anchor,validate_reaction_window
from xevent.pricing.calculations import volume_multiple
from xevent.contracts.common import PITQuery,UTCDateTime
from xevent.ledger.store import ref
from xevent.research.packet import vr

pytestmark=pytest.mark.pit


def test_public_fourteen_firstseen_two_minutes_late():
    stamp=lambda t:TypeAdapter(UTCDateTime).validate_python('2026-09-01T'+t+'+08:00')
    event=SimpleNamespace(object_id='EV',version=1,first_public_at=stamp('14:00:00'),
        first_seen_at=stamp('14:02:00'),available_at=stamp('14:02:05'),evidence_refs=(VersionRef(object_id='EV_RAW',version=1),))
    anchor=event_anchor(event)
    assert anchor.known_at==stamp('14:02:05') and anchor.proof_refs==event.evidence_refs
    with pytest.raises(ValueError,match='ANCHOR'):
        validate_reaction_window(anchor,Window(start=stamp('14:00:00'),end=stamp('14:30:00')),stamp('14:31:00'))
    validate_reaction_window(anchor,Window(start=stamp('14:02:05'),end=stamp('14:30:00')),stamp('14:31:00'))


def test_actual_event_version_available_after_firstseen(w):
    with pytest.raises(ValueError,match='ANCHOR'):
        assess(w,reaction_window=Window(start=w['event'].first_seen_at,end=w['end']))


def test_pre_event_window_cannot_cross_anchor(w):
    post=w['request'].price_refs
    with pytest.raises(ValueError,match='PRE_EVENT'):
        assess(w,pre_price_refs=post)


def test_future_end_cannot_enter_asof(w):
    with pytest.raises(ValueError,match='ANCHOR'):
        assess(w,reaction_window=Window(start=w['start'],end=w['clock']()+timedelta(hours=1)))


def test_future_daily_volume_not_known_intraday(w):
    cutoff=w['clock']()
    w['clock'].advance(hours=6)
    late=observation(w,'FULL_DAY',w['security'],'VOLUME',10000.0,w['start'],w['end']+timedelta(hours=6))
    with pytest.raises(ValueError,match='REGISTRY_REFERENCE'):
        assess(w,as_of=cutoff,volume_ref=vr(late))


def test_full_day_baseline_not_same_clock(w):
    refs=[]
    for index,r in enumerate(w['request'].volume_baseline_refs):
        old=get(w,r)
        day=observation(w,'DAY_BASE'+str(index),w['security'],'VOLUME',10000.0,
            old.window.start.replace(hour=0,minute=0,second=0),old.window.end.replace(hour=23,minute=59,second=0))
        refs.append(vr(day))
    a=assess(w,volume_baseline_refs=refs)
    assert get(w,a.features_ref).volume_ratio is None
    assert get(w,a.features_ref).volume_sample_n==0


def test_industry_membership_revision_no_backfill(w):
    old=assess(w)
    cutoff=w['clock'](); replay=w['ledger'].replay(cutoff)
    revise(w,w['INDUSTRY_composition'],expected_component_count=20,coverage_status='INCOMPLETE')
    assert w['ledger'].replay(cutoff)==replay
    oldread=w['pricing'].current(vr(old),as_of=cutoff,pricing_mode='ENGINEERING_FIXTURE')
    current=w['pricing'].current(vr(old),as_of=w['clock'](),pricing_mode='ENGINEERING_FIXTURE')
    assert oldread['freshness']=='AS_RECORDED'
    assert 'BENCHMARKCOMPOSITION_RECOMPUTE_REQUIRED' in current['recompute_reasons']
    assert assess(w,'AFTER').remaining_edge=='HOLD'


def test_adjustment_revision_no_backfill(w):
    old=assess(w); cutoff=w['clock'](); replay=w['ledger'].replay(cutoff)
    adjust=w['adjustments'][w['security'].object_id]
    revise(w,adjust,adjustment_type='PIT_ADJUSTED',factor=0.5)
    assert w['ledger'].replay(cutoff)==replay
    a=assess(w,'AFTER')
    assert 'ADJUSTMENTBASIS_RECOMPUTE_REQUIRED' in a.hold_reasons
    assert a.price_in_band=='UNKNOWN'


def test_beta_is_not_estimated_or_trained_with_future_data(w):
    a=assess(w); f=get(w,a.features_ref)
    assert f.beta is None and f.beta_method=='NOT_ESTIMATED'
    data=f.model_dump(); data['beta']=1.0
    with pytest.raises(ValidationError): MarketReactionFeatures.model_validate(data)
    data=w['request'].model_dump(); data['beta_training_end']=w['end']+timedelta(days=1)
    with pytest.raises(ValidationError): PricingRequest.model_validate(data)


def asset(w,identity,currency='USD',kind='COMMODITY',closed=False):
    pair=dict(base='USD',quote='CNY') if kind=='FX' else None
    obj=pub(w,MarketInstrument,identity,canonical_name_zh='虚构跨资产',asset_type=kind,currency=currency,
        timezone='UTC',target_object='CURRENCY' if kind=='FX' else 'COPPER',fx_pair=pair)
    w['adjustments'][identity]=pub(w,AdjustmentBasis,'ADJ_'+identity,instrument_ref=ref(obj),adjustment_type='UNADJUSTED',
        factor=1.0,source_ref=ref(w['source']))
    start=w['start']-timedelta(days=1) if closed else w['start']
    end=w['end']-timedelta(days=1) if closed else w['end']+timedelta(hours=1)
    w['sessions'][identity]=pub(w,MarketSession,'SESSION_'+identity,instrument_ref=ref(obj),source_ref=ref(w['source']),
        timezone='UTC',utc_offset_minutes=0,intervals=[dict(start=start.isoformat(),end=end.isoformat())],
        calendar_version='FICTIONAL_CROSS_ASSET')
    return obj


def test_closed_overseas_price_is_asynchronous_context(w):
    obj=asset(w,'CLOSED_COPPER',closed=True)
    old=observation(w,'CLOSED_PRICE',obj,'CROSS_ASSET',10.0,w['end']-timedelta(days=1))
    a=assess(w,cross_asset_ref=vr(old))
    f=get(w,a.features_ref)
    assert f.cross_asset_state=='ASYNCHRONOUS' and f.converted_cross_asset_value is None
    assert any(m.dimension=='CROSS_ASSET_DELAYED' and m.severity=='DEGRADED' for m in get(w,a.missing_dimensions_ref).items)


def test_fx_published_after_cutoff_cannot_convert(w):
    copper=asset(w,'COPPER'); fxasset=asset(w,'FX',currency='CNY',kind='FX')
    price=observation(w,'COPPER_PRICE',copper,'CROSS_ASSET',10.0,w['end'])
    cutoff=w['clock']()
    rate=observation(w,'FX_RATE',fxasset,'CROSS_ASSET',7.0,w['end'])
    with pytest.raises(ValueError,match='REGISTRY_REFERENCE'):
        assess(w,as_of=cutoff,cross_asset_ref=vr(price),fx_ref=vr(rate))


def test_valid_fx_is_context_not_equity_return(w):
    copper=asset(w,'COPPER'); fxasset=asset(w,'FX',currency='CNY',kind='FX')
    price=observation(w,'COPPER_PRICE',copper,'CROSS_ASSET',10.0,w['end'])
    rate=observation(w,'FX_RATE',fxasset,'CROSS_ASSET',7.0,w['end'])
    a=assess(w,cross_asset_ref=vr(price),fx_ref=vr(rate)); f=get(w,a.features_ref)
    assert f.converted_cross_asset_value==70.0 and f.converted_currency=='CNY'
    assert f.converted_unit=='CURRENCY_PER_UNIT' and 'CONTEXT_ONLY' in f.conversion_basis
    assert f.raw_return==0.0


def test_missing_fx_soft_degradation(w):
    copper=asset(w,'COPPER')
    price=observation(w,'COPPER_PRICE',copper,'CROSS_ASSET',10.0,w['end'])
    a=assess(w,cross_asset_ref=vr(price))
    assert get(w,a.features_ref).converted_cross_asset_value is None
    assert any(m.dimension=='FX_MISSING' and m.severity=='DEGRADED' for m in get(w,a.missing_dimensions_ref).items)


def test_published_two_minutes_later_not_visible_midway(w):
    started=w['clock']()
    def fault(stage):
        if stage=='after_pricing_assessment': w['clock'].advance(minutes=2)
    w['ledger'].fault=fault
    a=assess(w); w['ledger'].fault=lambda _:None
    mid=started+timedelta(minutes=1)
    assert a.available_at>mid and a.computed_at>mid
    assert not any(o.object_id==a.object_id for o in w['ledger'].history(as_of=mid))
    assert not a.is_visible(PITQuery(as_of=mid,mode='OBSERVED_REPLAY'))


def test_historical_analysis_cannot_be_real_forward(w):
    analysis=new_analysis(w,choice='TARGET',mode='HISTORICAL_REPLAY')
    a=assess(w,analysis_ref=vr(analysis),pricing_mode='REAL_FORWARD')
    assert a.remaining_edge=='HOLD' and 'RESEARCH_MODE_MISMATCH' in a.hold_reasons
    hist=assess(w,'HIST',analysis_ref=vr(analysis),pricing_mode='HISTORICAL_REPLAY')
    assert not hist.is_visible(PITQuery(as_of=w['clock'](),mode='LIVE_FORWARD'))
    with pytest.raises(ValueError,match='MODE_ISOLATION'):
        w['pricing'].current(vr(hist),as_of=w['clock'](),pricing_mode='REAL_FORWARD')


def test_new_observation_requires_current_recompute_but_old_replay_stable(w):
    a=assess(w); cutoff=w['clock'](); replay=w['ledger'].replay(cutoff)
    old=get(w,w['request'].price_refs[-1])
    revise(w,old,value=110.0)
    assert w['ledger'].replay(cutoff)==replay
    assert w['pricing'].current(vr(a),as_of=cutoff,pricing_mode='ENGINEERING_FIXTURE')['freshness']=='AS_RECORDED'
    current=w['pricing'].current(vr(a),as_of=w['clock'](),pricing_mode='ENGINEERING_FIXTURE')
    assert current['current_remaining_edge']=='HOLD'
    assert 'MARKET_OBSERVATION_RECOMPUTE_REQUIRED' in current['recompute_reasons']
    assert assess(w,'STALE').remaining_edge=='HOLD'


def test_new_observation_different_id_same_window_not_bypass_stale_gate(w):
    a=get(w,w['request'].price_refs[-1])
    observation(w,'OTHER_PRICE_ID',w['security'],'PRICE',101.0,a.window.end)
    assert 'MARKET_OBSERVATION_RECOMPUTE_REQUIRED' in assess(w).hold_reasons


def test_later_new_analysis_packet_invalidates_current_pricing(w):
    a=assess(w); cutoff=w['clock']()
    new_analysis(w,choice='NULL')
    now=w['pricing'].current(vr(a),as_of=w['clock'](),pricing_mode='ENGINEERING_FIXTURE')
    assert 'ANALYSIS_RECOMPUTE_REQUIRED' in now['recompute_reasons']
    assert w['pricing'].current(vr(a),as_of=cutoff,pricing_mode='ENGINEERING_FIXTURE')['freshness']=='AS_RECORDED'


def test_price_becomes_stale_as_clock_advances(w):
    a=assess(w)
    w['clock'].advance(minutes=10)
    current=w['pricing'].current(vr(a),as_of=w['clock'](),pricing_mode='ENGINEERING_FIXTURE')
    assert current['current_remaining_edge']=='HOLD' and 'STALE_PRICE' in current['recompute_reasons']


def test_provider_requalification_does_not_rewrite_history(w):
    a=assess(w); cutoff=w['clock']()
    revise(w,w['provider'],qualification_status='PROVIDER_HOLD',timestamp_verified=False)
    assert w['pricing'].current(vr(a),as_of=cutoff,pricing_mode='ENGINEERING_FIXTURE')['freshness']=='AS_RECORDED'
    assert 'PROVIDERQUALIFICATION_RECOMPUTE_REQUIRED' in assess(w,'NEW').hold_reasons


def test_replay_twice_identical(w):
    assess(w); at=w['clock']()
    assert w['ledger'].replay(at)==w['ledger'].replay(at)

def test_wrong_fx_pair_fails_closed(w):
    copper=asset(w,'COPPER'); fxasset=asset(w,'FX',currency='CNY',kind='FX')
    wrong=revise(w,fxasset,fx_pair=dict(base='EUR',quote='CNY'))
    w['adjustments']['FX']=revise(w,w['adjustments']['FX'],instrument_ref=ref(wrong))
    w['sessions']['FX']=revise(w,w['sessions']['FX'],instrument_ref=ref(wrong))
    rate=observation(w,'WRONG_RATE',wrong,'CROSS_ASSET',7.0,w['end'])
    price=observation(w,'COPPER_PRICE',copper,'CROSS_ASSET',10.0,w['end']-timedelta(seconds=1))
    with pytest.raises(ValueError,match='FX_UNIT_PAIR_HOLD'):
        assess(w,cross_asset_ref=vr(price),fx_ref=vr(rate))


@pytest.mark.parametrize('empty',[False,True])
def test_closed_or_missing_current_session_holds(w,empty):
    session=w['sessions'][w['security'].object_id]
    revised=revise(w,session,intervals=[] if empty else [dict(start=w['start'].isoformat(),end=w['end'].isoformat())])
    old=get(w,w['request'].price_refs[-1])
    new=revise(w,old,session_ref=ref(revised),quality_status='STALE' if empty else 'QUALIFIED')
    w['request']=replace_ref(w['request'],old,new)
    a=assess(w)
    assert a.remaining_edge=='HOLD'
    missing=get(w,a.missing_dimensions_ref)
    assert any(m.dimension==('NO_CURRENT_SESSION' if empty else 'MARKET_CLOSED') for m in missing.items)


def test_same_clock_uses_each_historical_session_offset(w):
    refs=[]
    for index,r in enumerate(w['request'].volume_baseline_refs):
        old=get(w,r)
        session=get(w,old.session_ref)
        # A separately declared historical offset; UTC window differs by one hour,
        # but the historical local clock equals the current local clock.
        historic=pub(w,MarketSession,'HIST_OFFSET_'+str(index),instrument_ref=ref(w['security']),
            source_ref=ref(w['source']),timezone=session.timezone,utc_offset_minutes=session.utc_offset_minutes-60,
            intervals=[dict(start=(old.window.start-timedelta(hours=2)).isoformat(),
                            end=(old.window.end+timedelta(hours=2)).isoformat())],calendar_version='FIXTURE_HIST_OFFSET')
        shifted=observation(w,'HIST_VOLUME_'+str(index),w['security'],'VOLUME',old.value,
            old.window.start+timedelta(hours=1),old.window.end+timedelta(hours=1),session_ref=ref(historic))
        refs.append(vr(shifted))
    a=assess(w,volume_baseline_refs=refs)
    features=get(w,a.features_ref)
    assert features.volume_sample_n==3 and features.volume_ratio==1.0
