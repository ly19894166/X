# Phase 8 — Market Recognition / Price-in / Remaining Edge

## Scope and accepted base

Stacked on `build/x-event-engine-phase7` at `18e57a4f6448480c743adf6ad82f2e48bbd8f970`; Refs #13, parent specification #4.
Only `xevent/pricing/` implements new research behavior. Existing Ledger and CLI only register new schemas. No SQL table or migration is needed: objects use the existing append-only SQLite records, fixed version inputs and publication fence. Prior Phase 1–7 tests and implementation remain unchanged except schema registration.

`API_BUDGET = 0`. The module uses structured inputs and deterministic Python calculations. `adapter.py` is a Protocol only; there is no live market, model, broker, ChatGPT, manual model bridge, rank, target price, return forecast, account filter or execution implementation. No new dependency or license change.

## Formal V0.1 compatibility amendment

For Phase 8 machine storage, `pricing/contracts.py` with `policy_version=X_PRICING_V0.1` is the unique contract. This amendment records the explicit Phase 8 user instruction taking precedence over the older Phase 0 technical specification section 9. It does not rewrite the frozen document or historical commits.

- Recognition: `UNRECOGNIZED / EARLY_RECOGNITION / PARTIAL_RECOGNITION / BROAD_RECOGNITION / CONSENSUS / UNKNOWN`.
- Price-in: `LOW / MEDIUM / HIGH / VERY_HIGH / UNKNOWN / HOLD`.
- Crowding and reversal risk: separate `LOW / MEDIUM / HIGH / EXTREME / UNKNOWN` fields.
- Remaining edge: `STRONG / POSITIVE / THIN / NONE / NEGATIVE / UNKNOWN / HOLD`. STRONG is reserved and is never emitted by the uncalibrated V0.1 rules.
- No numerical Price-in percentage or `100 - Price-in` field exists. No old enum synonym is stored alongside the new canonical enum. Unknown older classifications require explicit reviewed migration, not an automatic guessed conversion.
- The event reaction anchor is `SYSTEM_VERSION_AVAILABLE`, not retrospective public time. The frozen EventVersion and its evidence refs prove `max(available_at, first_seen_at, first_public_at when present)`.
- Old public-time analysis cannot silently become a system-known forward observation. It must be imported as a separate historical version, with its mode and knowledge qualification intact. This release imports no legacy pricing records.

Economic research is never overwritten: Phase 7 final choice and decision source remain authoritative. A hot narrative or Phase 7 NULL cannot create TARGET. Price response cannot rescue a Phase 7 HOLD.

## Versioned schemas and provenance

All stored pricing objects extend `PricingEnvelope`: object_id, version, as_of, observed_at, computed_at, recorded_at, available_at, policy_version, input_version_refs, pricing_mode, provenance_zh and the inherited Ledger audit/hash fields. Every nested VersionRef is declared in the fixed input list. Dynamic latest is used only to detect staleness, never stored as an official reference.

| Object | Purpose |
| --- | --- |
| MarketInstrument | Fixed index/commodity/FX/overseas/rate identity; securities reuse Registry SecurityVersion |
| MarketSession | Fixed source, instrument, ordered session windows and calendar version |
| AdjustmentBasis | Fixed instrument, factor, UNADJUSTED/PIT_ADJUSTED; never fetch today's factor |
| ProviderQualification | Timestamp/unit/currency qualifications independently checked; fixture-only scope |
| MarketObservation | Window, field, value/null, unit/currency, adjustment, provider/source, source time, first-seen/received and quality |
| BenchmarkComposition | Fixed constituent SecurityVersion refs, expected count, industry and declared coverage |
| BenchmarkSnapshot | Fixed endpoint observations and composition; transparent endpoint return |
| PricingContext | Typed reviewed findings with FACT + VALIDATED EvidenceVersion and quote verified in immutable raw |
| PricingPolicy | Explicit uncalibrated rule parameters, published as a fixed version |
| MarketReactionFeatures | Original returns, relative returns, pretrend, volume/amount samples, diffusion and cross-asset context |
| NextBuyerHypothesis | Specific potential buyer mechanism and failure condition; always a hypothesis |
| NonReactionInvestigation | Twelve explicit alternative nonreaction explanations and investigation completeness |
| AlternativeCauseSearch | Eleven explicit other-cause checks; fixed scope, not causal proof |
| MissingDimensions | Each missing reason, severity, source status and formal requirement |
| PricingAssessment | Separate recognition/Price-in/crowding/edge/reversal plus refs to every investigation and raw input |

Observation enums include PRICE, RETURN, VOLUME, TURNOVER, AMOUNT, VWAP, VOLATILITY, BREADTH, INDUSTRY_RETURN, BENCHMARK_RETURN and CROSS_ASSET. PRICE is a point; RETURN requires two genuine PRICE refs and a verified matching window/value. Naive timestamps, non-finite numbers, impossible windows and systemic unit/currency binding errors fail closed. Missing values remain null with a reason.

## PIT, sessions and publication

An input must be available by request.as_of. Reaction start cannot precede the fixed EventVersion knowledge anchor, and reaction end cannot exceed as_of. A 14:00 public event first seen at 14:02 cannot claim a 14:00 system-known reaction. A material updated EventVersion may yield a later version anchor, intentionally preventing old reactions from being silently assigned to new evidence.

Pre-event baseline ends no later than the earlier public/first-seen anchor, separately from post-event endpoints. Reporting/market time is never knowledge time. Provider timestamp, first_seen_at, received_at, observed_at and available_at remain distinct.

The existing Ledger transaction and publication fence atomically publish features, investigations, next buyers, missing dimensions and assessment. recorded_at/available_at retain the accepted durable publication semantics, not INSERT execution time. A computation finishing two minutes later is not visible one minute after it started. Rollback publishes no partial assessment. Idempotent identity/version/request hash returns the same result. Replay preserves every older version.

Session timezone labels and `utc_offset_minutes` are explicitly provider-declared fixed data (`PROVIDER_DECLARED_SESSION_OFFSET`). This release does not install tzdata or claim validated worldwide historical DST/calendar coverage. Different historical offsets require separately qualified session versions. The demo uses `FICTIONAL_CONTINUOUS_SESSION_V1`, not the real A-share exchange calendar. Missing current session, closed market and stale current prices block current pricing; closed cross-assets are asynchronous context and degrade only that dimension.

## Calculations and denominator discipline

- Raw return is end/start minus one with two comparable positive prices. Market and industry relative returns subtract the corresponding same-window fixed benchmark return. They are MARKET_REACTION_FEATURES, never CAUSAL_RETURN or Event Alpha.
- Beta remains null / NOT_ESTIMATED. There is no training or factor model, hence no future beta window.
- Comparability requires identical instrument, source/provider, currency/unit and adjustment version. Incompatible endpoint data does not produce a usable return.
- Volume and amount use the median of at least three distinct pre-event dates with identical local-clock window and duration. No full-day comparison or future daily total. A zero/insufficient baseline yields null; sample counts are retained.
- Diffusion deduplicates securities by Company and reports eligible/observed/reacting companies, breadth, median relative return, dispersion and leader concentration. It uses the fixed composition and checks coverage against known matching graph exposures. Missing companies or an incomplete declared denominator yield UNKNOWN, not 100% breadth. This is not real full-market exposure coverage.
- Sustained trading is counted from supplied qualified, explicit post-anchor price-pair dates. It is not inferred from an editable days-traded string. Optional turnover, volatility and fixed previous features preserve context and breadth decay.
- A cross-asset must match the existing Impact mechanism. FX requires exact base/quote, FX_RATE units and a fixed PIT-available rate no later than the cross-asset observation. Converted commodity context is labeled with unit/currency and never mixed into equity return. Missing FX degrades; wrong pair/unit fails closed.

## Deterministic research policy

Rules retain dimensions rather than summing a score. Engineering defaults: low reaction 0.5%, noticeable relative reaction 1%, large relative reaction 5%, abnormal flow multiple 2, extreme flow 4, broad diffusion 60%, consensus diffusion 85%, sustained sessions 3, maximum current price age 300 seconds. These are named transparent engineering thresholds, **not calibrated market facts or return forecasts**. Each is versioned in PricingPolicy.

Recognition requires reviewed dissemination plus reaction/flow/diffusion dimensions. Broad recognition and several sessions can become CONSENSUS. No dissemination knowledge remains UNKNOWN. Lack of a price move alone cannot establish unrecognized information.

Crowding requires joint relative-return, flow and breadth observations. HIGH/EXTREME requires multiple dimensions and duration. No price-limit shortcut exists. Price-in HIGH/VERY_HIGH additionally requires known novelty, broad recognition and sustained crowded trading; a +5% stock with +5% industry suggests sector cause rather than high event Price-in.

Nonreaction checks old news, wrong exposure, materiality, macro pressure, company counterfactors, liquidity, delay, wrong timing, pretrading, counterevidence, indirect benefit and long horizon. Recognition gap requires high thesis strength, confirmed dissemination, complete reviewed checks, valid pretrend/data and unexplained low reaction. Unknown checks remain DATA_INSUFFICIENT. A no-reaction event alone is never STRONG edge.

Alternative cause checks other events, earnings, orders, merger, policy, sector rally, commodity, index beta, other theme, technical rebound and prior event. Explicit pretrend or sector-relative neutrality after an absolute rise adds an explanation. CURRENT_EVENT_DOMINANT only means no reviewed alternative in the fixed input scope; it does not prove causation.

Next buyer needs fixed economic path/observations, a specific not-already-present explanation, trigger and failure condition with fixed raw proof. It remains `HYPOTHESIS_NOT_OBSERVED_BUYER`, including when SUPPORTED. Generic 'later money may notice' is WEAK; unestablished A-share short covering is REJECTED. Volume cannot identify buyers.

Positive **engineering simulation** requires high thesis, R3/R4 novelty, investigated recognition gap, specific buyer, remaining diffusion, complete denominator, no alternative cause and low risk. High pricing/crowding can leave THIN even with a buyer, or NONE without one. Counterevidence/strong alternative cause can yield NEGATIVE. Missing required data gates produce HOLD/UNKNOWN. Reversal risk separately considers pricing, crowding, pretrend, cause, buyer, volatility and diffusion decay. It is not a stop-loss rule.

## Phase 7 and freshness gates

Reuse AnalysisRun decision-source validation and fixed primary/red/adjudication results, ResearchPacket, MappingHistory/Assessment and selected economic TransmissionPath. Existing ResearchStore.gates checks Phase 6/7 freshness including exposure selection. Phase 7 HOLD, HOLD_GATE, NULL, narrative or mismatched selected path blocks positive output. A newer AnalysisRun for the same event/security/mode invalidates old current pricing even if its packet ID changed.

Market inputs check both fixed-version and same semantic window newer observations. Composition, adjustment, provider, session, context and policy revisions require recomputation. `current()` returns immutable as-recorded assessment alongside current HOLD/recompute reasons. Old as_of remains unchanged. Price aging is rechecked even without a new observation.

## Engineering qualification and HOLD

`ENGINEERING_FIXTURE`, `MOCK_FORWARD`, `HISTORICAL_REPLAY`, `REAL_FORWARD` are explicit. Historical results cannot pass forward visibility. This release cannot qualify REAL_FORWARD: all providers are `ENGINEERING_FIXTURE_ONLY`, all successful assessments are ENGINEERING_ONLY, and formal_positive_remaining_edge is always false. Provider qualification is independent of research calibration/validity.

Permanent release limits:

- HOLD_MODEL_PROVIDER_LIVE
- HOLD_MODEL_USAGE_COST_UNVERIFIED
- HOLD_MARKET_DATA_PROVIDER_LIVE
- HOLD_PRICING_POLICY_CALIBRATION
- HOLD_HISTORICAL_UNIVERSE_COVERAGE
- HOLD_REAL_COMPANY_EXPOSURE_COVERAGE
- HOLD_PRE_1992_CALENDAR
- HOLD_LICENSE_TEXT_FOR_REDISTRIBUTION

Conditional missing/stale/freshness/provider/units/research gates remain attached to each result. Live market data, real model effectiveness, actual global historical sessions and alpha are unverified. Engineering completion is not provider or investment acceptance.

## Offline demonstration

From `subsystems/event_engine`, after installing the existing locked package:

```text
python -m xevent.pricing.fixture --db phase8-demo.sqlite
```

Use a new isolated database. All companies, indices, commodity/FX data and observations are fictional: ENGINEERING_DEMO / NO_ALPHA_CLAIM / NO_INVESTMENT_ADVICE. The example explicitly shows stock +5% and industry +5% without claiming high event Price-in. No live smoke is performed.
