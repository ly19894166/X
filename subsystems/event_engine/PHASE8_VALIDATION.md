# Phase 8 validation

Accepted base: `build/x-event-engine-phase7` at `18e57a4f6448480c743adf6ad82f2e48bbd8f970`.
Head branch: `build/x-event-engine-phase8`; stacked Draft PR, Refs #13. No merge or Phase 9.

## Final local commands

Run from `subsystems/event_engine` with the existing locked Python 3.11 environment and `PYTHONPATH=src`:

```text
python -m pytest -q tests/test_phase8_pricing.py tests/test_phase8_pit.py
python -m pytest -q
python -m pytest -q -m pit
python -m xevent.pricing.fixture --db <new isolated SQLite file>
```

Final raw results are appended after completion. An earlier full run was deliberately stopped after adding the historical per-session UTC-offset test; that incomplete run is not acceptance evidence. The final sequence re-runs focused, full and PIT on the completed source.

## Added tests and requirement mapping

`test_phase8_pricing.py` covers:

- A/B: stock+industry both +5%, and +2% versus -3% relative reaction without causal/Price-in equivalence.
- C/D/G: pre-event +8% separate from post-event +1%; checked and unchecked nonreaction; dissemination without forced strong edge.
- E: missing price/benchmark, null vs zero, insufficient/zero volume baselines.
- F/J: both pure rule and persisted four-session crowded scenarios; buyer can leave THIN, absence NONE.
- H/I: other-event MULTI_CAUSE, unsupported next buyer and unsupported A-share short covering.
- K/L/M: a genuine normalized narrative path and Phase 7 NULL/HOLD cannot be rescued by hot prices.
- Company-level denominator incompleteness, same-clock samples, no actual buyer identity inferred from volume.
- Independent timestamp/unit/currency provider gate, return price-endpoint validation, invalid enums/units/non-finite values/naive times, immutable-raw finding quote validation.
- All schemas JSON round-trip and fixed nested refs; idempotence, no upstream mutation and atomic rollback.
- Account holdings, costs, preference, account permissions and future outcome fields rejected; socket and MockModelProvider calls prohibited during pricing.
- REAL_FORWARD cannot launder fixture qualification; Chinese fixture report retains all dimensions and disclaimers.

`test_phase8_pit.py` covers:

- 14:00 public / 14:02 first-seen / 14:02:05 available anchor, actual EventVersion publication, event/pre-event window boundaries.
- No future daily total, wrong-clock baseline, or future beta; each historical session's fixed offset defines its local-clock baseline.
- Fixed industry constituents and adjustment revisions cannot rewrite old replay.
- Closed cross-asset is asynchronous; late FX excluded, missing FX soft-degraded, wrong pair fails closed, valid conversion remains context only.
- A result finishing two minutes later is invisible at the intermediate minute.
- Historical results cannot become real forward; newer same-window observations, including new IDs, and newer AnalysisRun/Packet require recomputation.
- Price aging, current market closed/no session, provider requalification and repeated replay.

All prior 582 tests are preserved without deletion or modification. All tests inherit the unchanged `no_real_network` fixture. No live market/model smoke is performed.

## CI

The original Ubuntu/Windows × Python 3.11/3.12 matrix continues to run full tests, separate PIT and every Phase 1–7 fixture, followed by the Phase 8 Chinese fixture. Pinned actions, hashed dependencies and installation commands are unchanged.

Remote run URL, exact head SHA, four job conclusions and raw test summaries are recorded on the Draft PR and Issue #13 after successful execution. Local success cannot substitute for those jobs.

## Boundaries

No new dependencies, lock hashes, license change, SQL schema or migration. The sgmllib3k redistribution text HOLD remains. No Market Engine, src/xalpha, old tests, main, Phase 1–7 business logic, real providers or Phase 9 implementation.

Provider scope remains ENGINEERING_FIXTURE_ONLY; all successful assessments remain ENGINEERING_ONLY, with formal_positive_remaining_edge=false. Uncalibrated policy thresholds, fictional sessions and all real coverage/model/provider HOLDs are listed in PHASE8.md. Engineering completeness is not validated real market pricing, alpha or data coverage.

## Final local raw results

Phase 8 focused:

```text
74 passed in 160.40s (0:02:40)
```

Phase 1–8 full:

```text
656 passed in 694.78s (0:11:34)
```

Added: 74 tests, of which 25 are PIT. Existing 582 tests are unchanged.

PIT separately:

```text
197 passed, 459 deselected in 288.49s (0:04:48)
```

The isolated Phase 8 CLI fixture exited 0. Stock +5% and industry +5% produced:

```text
模式: ENGINEERING_FIXTURE
市场认知: EARLY_RECOGNITION
已定价: UNKNOWN
拥挤: LOW
剩余空间: UNKNOWN
反转风险: MEDIUM
研究状态: ENGINEERING_ONLY
正式正向空间: false
重算原因: []
缺失维度: []
```

All eight permanent HOLDs remain in the report. This is a fictional demonstration, not Live smoke or formal market acceptance.
