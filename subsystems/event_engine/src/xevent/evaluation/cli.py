"""Manual one-shot shadow commands, no daemon or live connector."""
import argparse
import json
from pathlib import Path
from ..contracts.common import VersionRef
from ..ledger.store import Ledger
from .store import LabelLedger
from .engine import EvaluationEngine
from .report import report


def parse_ref(text):
    identity,version=text.rsplit('@',1)
    return VersionRef(object_id=identity,version=int(version))


def main(argv=None):
    parser=argparse.ArgumentParser(description='Shadow单次冻结/结算/报告；所有引用ID@version')
    parser.add_argument('action',choices=('register','settle','report'))
    parser.add_argument('--db',type=Path,required=True)
    parser.add_argument('--features-db',type=Path,required=True)
    parser.add_argument('--run-id',required=True)
    parser.add_argument('--package-ref',type=parse_ref)
    parser.add_argument('--plan-ref',type=parse_ref)
    parser.add_argument('--run-ref',type=parse_ref,action='append')
    parser.add_argument('--as-of')
    parser.add_argument('--version',type=int,default=1)
    parser.add_argument('--revision-reason')
    args=parser.parse_args(argv)
    ledger=LabelLedger(args.db,feature_path=args.features_db)
    engine=EvaluationEngine(ledger)
    try:
        if args.action=='register':
            if not args.package_ref or not args.plan_ref: parser.error('register需要package-ref与plan-ref')
            features=Ledger(args.features_db,recover_on_open=False)
            try: output=engine.register(args.run_id,features=features,package_ref=args.package_ref,plan_ref=args.plan_ref)
            finally: features.close()
        elif args.action=='settle':
            output=engine.settle(VersionRef(object_id=args.run_id,version=1),as_of=args.as_of or ledger.now(),
                version=args.version,revision_reason=args.revision_reason)
        else:
            if not args.run_ref and not args.plan_ref: parser.error('report需要全部run-ref，零run时需要plan-ref')
            output=report(engine,args.run_id,args.run_ref or (),as_of=args.as_of or ledger.now(),version=args.version,
                revision_reason=args.revision_reason,plan_ref=args.plan_ref)
        result=[o.model_dump(mode='json') for o in output] if isinstance(output,list) else output.model_dump(mode='json')
        print(json.dumps(result,ensure_ascii=False,indent=2)); return 0
    finally: ledger.close()


if __name__=='__main__': raise SystemExit(main())
