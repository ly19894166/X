"""Run L1 overlay against the separately deployed, accepted Phase 10 package."""
import argparse
from pathlib import Path
import runpy
import sys

parser=argparse.ArgumentParser(add_help=False)
parser.add_argument('--runtime',type=Path,required=True)
args,unused=parser.parse_known_args()
if sys.version_info[:2]!=(3,12): raise SystemExit('HOLD_LOCAL_PYTHON312_QUALIFICATION')
import xevent
expected=args.runtime.resolve()/'code/accepted-phase10/subsystems/event_engine/src/xevent'
if Path(xevent.__file__).resolve().parent!=expected.resolve():
    raise SystemExit('ACCEPTED_PHASE10_DEPLOYMENT_REQUIRED; remove PYTHONPATH overrides')
overlay=Path(__file__).resolve().parents[2]/'subsystems/event_engine/src/xevent'
xevent.__path__.append(str(overlay))
runpy.run_module('xevent.real_landing.pilot',run_name='__main__')
