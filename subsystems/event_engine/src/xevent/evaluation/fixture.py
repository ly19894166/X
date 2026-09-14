"""Fictional shadow timeline. No live data, account returns, or Alpha claim."""
import argparse
import json
from datetime import timedelta
from pathlib import Path
from ..contracts.bundle import content_digest
from ..ledger.store import ref
from ..ranking.fixture import prepare_package
from ..pricing.contracts import MarketSession, MarketObservation
from .contracts import SettlementCalendar, OutcomeQuote
from .store import LabelLedger
from .engine import EvaluationEngine, vr, raw
from .calendar import windows, next_session
from .report import report


def revised(model,**changes):
    obj=type(model).model_validate({**model.model_dump(),**changes})
    return type(model).model_validate({**obj.model_dump(),'content_hash':content_digest(obj)})


def prepare(feature_db,label_db,configs):
    w,ranking,package,empty,_=prepare_package(feature_db,configs)
    return prepare_labels(w,label_db,package,empty)


def prepare_labels(w,label_db,package,empty):
    feature_db=w['ledger'].path
    label=LabelLedger(label_db,feature_path=feature_db,clock=w['clock'])
    engine=EvaluationEngine(label)
    offset=timedelta(hours=8)
    start=(package.available_at+offset).replace(hour=0,minute=0,second=0,microsecond=0)-offset
    days=[]; closed=[]
    for i in range(14):
        d=start+timedelta(days=i); local=d+offset
        # Weekend plus an explicitly fictional weekday holiday.
        if local.weekday()>=5 or i==5: closed.append(str(local.date())); continue
        days.append(dict(trading_date=str(local.date()),intervals=[((d+timedelta(hours=9,minutes=30)).isoformat(),(d+timedelta(hours=11,minutes=30)).isoformat()),
            ((d+timedelta(hours=13)).isoformat(),(d+timedelta(hours=15)).isoformat())]))
    session=revised(w['sessions'][w['security'].object_id],object_id='P10_FICTIONAL_SESSION',calendar_version='P10_FICTIONAL_SPLIT_SESSION_V1',
        session_scope='P10_FIXTURE',intervals=[dict(start=a,end=b) for day in days for a,b in day['intervals']])
    cal=engine.publish(SettlementCalendar,'P10_CALENDAR',dict(evaluation_mode='ENGINEERING_FIXTURE',session=raw(session),
        coverage_start=start.isoformat(),coverage_end=(start+timedelta(days=14)).isoformat(),days=days,closed_dates=closed,
        qualification_status='ENGINEERING_QUALIFIED'))
    registration_start=w['clock']()+timedelta(seconds=1)
    plan=engine.plan('P10_PLAN',calendar_ref=vr(cal),rank_policy_ref=package.request.policy_ref,epoch='ENGINEERING_EPOCH_1',
        registration_start=registration_start.isoformat(),registration_end=(registration_start+timedelta(days=1)).isoformat(),expected_runs=2)
    w['clock'].value=registration_start+timedelta(seconds=1)
    run=engine.register('P10_RUN',features=w['ledger'],package_ref=vr(package),plan_ref=vr(plan))
    empty_run=engine.register('P10_EMPTY_RUN',features=w['ledger'],package_ref=vr(empty),plan_ref=vr(plan))
    w.update(labels=label,evaluation=engine,calendar=cal,evaluation_plan=plan,run=run,empty_run=empty_run,package=package)
    return w


def quote(w,identity,at,value,*,entry='EXECUTABLE',exit='EXECUTABLE',limit='NONE',quality='QUALIFIED',version=1,revision_reason=None):
    w['clock'].value=max(w['clock'].value,at+timedelta(seconds=1))
    sec=w['security']; session=w['calendar'].session; provider=w['provider']; adjustment=w['adjustments'][sec.object_id]
    obs=MarketObservation.model_validate(dict(object_id=identity+':OBS',version=version,recorded_at=at.isoformat(),available_at=at.isoformat(),
        computed_at=at.isoformat(),as_of=at.isoformat(),observed_at=at.isoformat(),content_hash='0'*64,run_id='ENGINEERING_OBSERVATION',policy_version='X_PRICING_V0.1',
        provenance_zh='完全虚构未来结果报价；只存放label库',pricing_mode='ENGINEERING_FIXTURE',instrument_ref=ref(sec),observation_type='PRICE',
        window=dict(start=at.isoformat(),end=at.isoformat()),value=value,unit='CURRENCY_PER_UNIT',currency='CNY',adjustment_ref=ref(adjustment),
        adjustment_type='UNADJUSTED',source_ref=ref(w['source']),provider_ref=ref(provider),provider=provider.provider,provider_timestamp=at.isoformat(),
        received_at=at.isoformat(),first_seen_at=at.isoformat(),session_ref=ref(session),staleness_seconds=0.0,quality_status=quality))
    obs=revised(obs)
    return w['evaluation'].publish(OutcomeQuote,identity,dict(evaluation_mode='ENGINEERING_FIXTURE',observation=raw(obs),provider_qualification=raw(provider),
        adjustment=raw(adjustment),session=raw(session),entry_executability=entry,exit_executability=exit,limit_state=limit,
        execution_evidence='虚构逐笔成交及可执行性证明；非真实盘口' if 'EXECUTABLE' in (entry,exit) else None,
        traded_volume=1000.0 if 'EXECUTABLE' in (entry,exit) else 0.0,revision_reason=revision_reason),version=version)


def finish(w):
    cal=w['calendar']; plan=w['evaluation_plan']; run=w['run']
    entry_time=next_session(cal,run.package_available_at+timedelta(seconds=plan.rules.delay_seconds))
    schedule=windows(cal,run.package_available_at)
    # Losses are deliberate demonstrations, not evidence of actual model quality.
    stamps={entry_time:100.0,**{s.end:99.0-i for i,s in enumerate(schedule)}}
    for i,(stamp,value) in enumerate(sorted(stamps.items())):
        quote(w,'P10_QUOTE_'+str(i),stamp,value)
    w['clock'].value=max(s.end for s in schedule)+timedelta(minutes=2)
    for r in (run,w['empty_run']): w['evaluation'].settle(vr(r),as_of=w['clock']())
    return report(w['evaluation'],'P10_REPORT',(vr(run),vr(w['empty_run'])),as_of=w['clock']())


def main():
    parser=argparse.ArgumentParser(description='Phase10离线Shadow工程演示；不证明Alpha')
    parser.add_argument('--db',type=Path,required=True,help='新的label数据库')
    parser.add_argument('--features-db',type=Path,required=True,help='新的虚构feature数据库')
    parser.add_argument('--configs',type=Path,default=Path('configs'))
    args=parser.parse_args()
    if args.db.exists() or args.features_db.exists(): raise ValueError('FIXTURE_NEW_DATABASES_ONLY')
    w=prepare(args.features_db,args.db,args.configs)
    try: print(json.dumps(raw(finish(w)),ensure_ascii=False,indent=2))
    finally: w['labels'].close(); w['ledger'].close()


if __name__=='__main__': main()
