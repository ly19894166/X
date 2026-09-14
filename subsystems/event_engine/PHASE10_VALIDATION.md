# Phase 10 validation

Accepted base: `6ea68d12692cd817b909b49652b76a72d95ee4c7` (`build/x-event-engine-phase9`).

Local validation: PASS. Delivery status: HOLD pending exact-head four-environment CI; CI evidence will be recorded on the Draft PR and Issue #15.

## Scope evidence

All 28 original test files match their baseline Git content hashes. Original 777 tests remain unchanged.
Final collection: `832 tests collected in 0.96s` (55 new Phase 10 tests).
Only evaluation implementation, Phase 10 documentation/tests, minimal shadow CLI dispatch and the incremental Event Engine CI fixture step change.
No dependency/lockfile, Market Engine, src/xalpha, or Phase 1–9 domain implementation changes.

## Final verification

- Focused: `55 passed in 1197.21s (0:19:57)` (`python -m pytest -q tests/test_phase10_evaluation.py`).
- Full: `832 passed in 3088.00s (0:51:27)` (`python -m pytest -q`).
- PIT: `275 passed, 557 deselected in 1481.44s (0:24:41)` (`python -m pytest -q -m pit`).
- Exact-head Ubuntu Python 3.11 / 3.12: pending.
- Exact-head Windows Python 3.11 / 3.12: pending.

The earlier 830-test full pass predates the final event-cluster fixes and is not final acceptance evidence.
The targeted clustering regression check passed: `3 passed, 52 deselected in 0.82s`.
Origin relations expand to a fixed point, including intermediate origins without candidates, independently of traversal order.
Unresolved Event identities stay in the candidate denominator but do not count as known independent event clusters or bootstrap samples.

## Qualification boundary

ENGINEERING_DEMO / NO_ALPHA_CLAIM / NO_INVESTMENT_ADVICE / SIMULATED_ONLY.
No live market, model, broker or account connection. API_BUDGET=0.
REAL_FORWARD remains HOLD and formal_live_alpha=false.
No Phase 11, merge, force push or main modification.

## Final focused fixture report

Read back from the new focused test LabelLedger, not inferred from expected assertions:

- 2 registered / 2 expected / 2 settled runs; both explicitly late.
- 28 frozen candidates, 168 outcomes (all six windows), empty-list rate 0.5.
- Every ALL_FROZEN window retains all 28 samples, 9 known event clusters and 1 unresolved-event sample.
- Reference quote coverage 1.0; simulated settlement coverage 4/6; PIT violations 0.
- H30 / T_CLOSE: 28 PARTIAL observational samples each, simulated return null because of T+1.
- T1_0935 / T1_1000 / T1_CLOSE / T3_CLOSE: 28 simulated settlements each.
- Deliberate reference losses in window order: -1%, -2%, -3%, -4%, -5%, -6%. Fees/slippage further reduce simulated returns.
- ALL_FROZEN conclusions remain INSUFFICIENT_SAMPLE. No fixture Alpha claim.
- Missing diagnostic minute grid keeps MFE/MAE null; separate complete-grid test verifies diagnostic MFE cannot replace registered-window return.

Report HOLDs: FORWARD_HOLD_INSUFFICIENT_SAMPLE; HOLD_ABLATION_NO_NEXT_BUYER; HOLD_ABLATION_NO_RED_TEAM;
HOLD_EVALUATION_POLICY_CALIBRATION; HOLD_EVENT_CLUSTER_IDENTIFICATION; HOLD_HISTORICAL_UNIVERSE_COVERAGE;
HOLD_LICENSE_TEXT_FOR_REDISTRIBUTION; HOLD_MARKET_DATA_PROVIDER_LIVE; HOLD_MODEL_PROVIDER_LIVE;
HOLD_MODEL_USAGE_COST_UNVERIFIED; HOLD_PRE_1992_CALENDAR; HOLD_PRICING_POLICY_CALIBRATION;
HOLD_RANK_POLICY_CALIBRATION; HOLD_REAL_COMPANY_EXPOSURE_COVERAGE; HOLD_REAL_COST_QUALIFICATION;
HOLD_REAL_FORWARD_QUALIFICATION; HOLD_STATISTICAL_INTERVAL.
Input-specific calendar/PIT/market/execution failure reasons remain covered by the tests and are not silently dropped.
