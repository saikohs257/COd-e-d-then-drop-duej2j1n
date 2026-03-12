# FrankenOracle — Full Handoff for a New Chat
**Date:** 2026-03-11

This is the comprehensive handoff for continuing the FrankenOracle project in a fresh ChatGPT chat.

## 0. One-paragraph resume summary

FrankenOracle is no longer just a BTC trading model. It has evolved into a survival-first instability detection architecture with these layers: **Oracle** for slow environment / risk cap, **Adversary V1** for hazard activation and persistence, **Structural Fragility** for slow structural weakness, **Event Forensics** for event reconstruction, and **Motif Engine** for process classification. The strongest proven findings so far are: **hazard memory solved the time-axis failure of V0**, **fragility is load-bearing**, **motifs are real enough to study**, and **different instability families become visible at different phases of formation**. The biggest current bottleneck is **Oracle grounding in later-regime real data**, not motif logic.

---

# 1. Project identity

## What this project is
A **survival-first, fragility-aware instability observatory** with an action layer attached.

## What it is not
- not primarily a next-candle predictor
- not just a BTC signal stack
- not a machine-learning black box
- not a dashboard-first product

## Core philosophy
The system should answer four stacked questions:

1. **Oracle** — what kind of environment is this?
2. **Fragility** — how loaded / weak is the structure?
3. **Adversary** — has instability activated, and should skepticism persist?
4. **Motif Engine** — what process family is unfolding?

## Action rule
```text
final_exposure =
    min(oracle_cap, predictor_desired)
    * adversary_haircut
```

---

# 2. Conceptual evolution

The project started as a BTC exposure / crash-survival system.

It evolved through these steps:

1. **Oracle / Predictor / Adversary split**
2. **Hazard memory** to fix early activation / early decay
3. **Structural fragility** from open interest + funding persistence
4. **Event Forensics** to convert traces into case files
5. **Motif Engine** to classify recurring process families

The project is now better understood as:
> a system for studying how instability forms, persists, and cascades.

Recurring internal ideas that shaped the architecture:
- octopus / semi-independent arms
- flow / whirlpool / vortex intuition
- signals as words
- motifs as grammar
- energy landscape / basin language
- later realization: **great at interpretation, not yet best-in-class at action**

---

# 3. Current architecture

## Oracle
Role:
- slow environment sensing
- risk cap / climate layer
- should behave like **climate, not weather**

Known weakness:
- Oracle posterior is still too compressed in later-regime real data
- this is the main current bottleneck

## Predictor
Role:
- bounded opportunity expression

Status:
- not the main active research focus right now

## Adversary V0
Original adversary used:
- turbulence
- conflict
- vol_surprise

Known issue:
- activated early, then deactivated too soon when posterior velocity stabilized

## Adversary V1
Adds:
- `PosteriorLevelSignal`
- `HazardKernel`
- persistence logic

Role:
- turn acute signals into persistent skepticism

Result:
- solved the time-axis bug in synthetic tests

## Structural Fragility
Inputs:
- open interest
- funding persistence

Role:
- detect load-bearing structural weakness
- amplifies acute signals, does not trigger haircuts by itself

## Event Forensics
Turns runs into:
- event case files
- lead time analysis
- persistence analysis
- failure taxonomy
- Oracle vs Adversary attribution

## Motif Engine
Classifies events into:
- `quiet_loading_release`
- `occupied_danger_plateau`
- `recirculating_instability`
- `transition_false_alarm`
- `unknown`

Key hidden feature:
- sequence encoding like `fragility → turbulence → hazard`

## Motif Harness
Runs robustness experiments:
- seed sweep
- fragility ablation
- hazard decay sweep
- prefix motif prediction

---

# 4. Implemented files and what they do

## Core code
- `oracle.py` — Oracle shell and posterior / cap logic
- `signals.py` — original signal logic and shared signal structures
- `hazard_memory.py` — Adversary V1, hazard kernel, posterior level signal
- `fragility.py` — structural fragility signal from OI + funding
- `event_forensics.py` — event reconstruction and case-file generation
- `motif_engine.py` — motif classifier / process grammar layer
- `motif_harness.py` — robustness testing harness
- `backtest.py` — backtest engine and metrics
- `run.py` — execution / synthetic / backtest entry points
- `fetcher.py` — data loading / acquisition hooks

## Important analysis / memo files
- `frankenoracle_evolution_notes.md`
- `oracle_autonomous_execution_plan.md`
- `oracle_grounding_memo.md`
- `oracle_direction_reset_transformations_flow_grammar.md`
- `oracle_instability_energy_landscape_memo.md`
- `adversary_v1_evaluation_charter.md`
- `frankenoracle_detailed_report_for_claude.md`

## Current Claude handoff task
- `claude_task8_event_audit_and_grounding_ladder.md`

---

# 5. Data availability and honest panel policy

## Actual feature availability from the user's pulls
- **Candles:** start at `2019-09-08`
- **Funding:** start at `2019-09-10`
- **Open Interest:** start at `2020-07-20`

## Locked policy
### Full-stack structural era
**2020-07-20 → 2026-03-11**

Use this era for:
- fragility
- hazard memory
- motifs
- full-stack split battery
- serious evaluation

### Pre-structural era
**2019-09-08 → 2020-07-20**

Use only for:
- crash mapping
- reduced-feature context
- sanity checks

Do **not** backfill missing OI with fake continuity.

---

# 6. Key empirical findings

## 6.1 Hazard memory solved the V0 timing pathology
Synthetic headline:
- detection at T0: **36.8% → 94.7%**
- persistence: **2.8 bars → 11.7**
- false positives / event: **2.53 → 0.37**

Meaning:
- V1 fixed the “activates early then dies too soon” failure mode

## 6.2 Fragility is load-bearing
Pure-off ablation:

### With fragility
- timing: **0.966**
- quiet_loading_release: **60.3%**
- transition_false_alarm: **5.3%**

### Pure-off
- timing: **0.890**
- quiet_loading_release: **12.5%**
- transition_false_alarm: **75.8%**

Conclusion:
- fragility is not cosmetic
- it is one of the main reasons the system can distinguish **loaded structure** from **temporary transition noise**

## 6.3 Motif grammar is stable enough to study
Across 20 synthetic worlds:
- quiet_loading_release: **60.3%**
- occupied_danger_plateau: **18.3%**
- recirculating_instability: **16.1%**
- transition_false_alarm: **5.3%**

Additional:
- motif stability score (quiet-loading): **0.823**
- motif separation score: **0.419**
- timing score mean: **0.9656**
- detection rate mean: **0.9681**

Conclusion:
- the motifs are not random labels
- the grammar is structurally stable enough to keep working on

## 6.4 Hazard decay is a real control surface
Headline:
- best timing: **0.80**
- fewest false positives: **0.93**

Meaning:
- lower decay = sharper timing
- higher decay = calmer behavior

Non-obvious finding:
- motif grammar stayed relatively stable across decay values
- suggests motifs are more about environment / event shape than exact kernel constant

## 6.5 Prefix motif prediction works, but in motif-specific windows

### Overall
- T−12h: **16.1%**
- T−8h: **62.9%**
- T−4h: **56.1%**
- T−2h: **43.2%**

### By motif

#### quiet_loading_release
- 12h: **1.7%**
- 8h: **94.9%**
- 4h: **71.1%**
- 2h: **37.9%**

#### occupied_danger_plateau
- 12h: **61.1%**
- 8h: **1.4%**
- 4h: **5.6%**
- 2h: **9.7%**

#### recirculating_instability
- 12h: **3.2%**
- 8h: **6.5%**
- 4h: **51.6%**
- 2h: **93.6%**

#### transition_false_alarm
- ~90–100% across horizons

Conclusion:
- there is **no single best warning horizon**
- different instability families become visible at different phases:
  - plateau = early sickness
  - quiet-loading = mid-window release
  - recirculating = late pre-cascade
  - false alarm = visible throughout

## 6.6 Confidence calibration was fixed
Old confidence:
- pure rule-match rate

New confidence:
- rule match fraction
- plus winner margin over runner-up

Effect:
- mean confidence dropped from ~0.86 to ~0.40
- confidence is more honest and less swaggering

---

# 7. Real-data smoke test

## Initial real-data contact
Used:
- BTC candles
- open interest
- funding

Headline:
- crash events: **17**
- detection rate: **52.9%**
- mean persistence: **3.9 bars**
- false positives / event: **0.00**
- fragility mean: **0.203**
- fragility max: **0.748**

Motif counts:
- quiet_loading_release: **7**
- recirculating_instability: **5**
- transition_false_alarm: **4**
- occupied_danger_plateau: **1**

## What held up
- system did **not** collapse into nonsense
- fragility rose meaningfully before several real drops
- motifs remained interpretable
- recirculating instability was more common in reality than in synthetic

## What failed
- detection rate too low
- lead time near zero in many cases
- Oracle still too compressed / underfed
- 1h OI cadence may be too blunt for 5m event structure

## Best conclusion
Fragility survived reality **better than hazard timing**.

Meaning:
- sensing layer is working better than response layer

Main diagnosis:
- **Oracle judgment is still under-grounded**

---

# 8. Full-stack real split battery (all-directions)

Honest full-stack evaluation era:
**2020-07-20 → 2026-03-11**

Split styles tested:
1. forward
2. backward
3. middle ascending
4. middle descending

Models compared:
- V0
- V1
- V1 + fragility

## Later-regime OOS
(~2024-04 → 2026-03, 15 events)

### Forward calibration
- V0:
  - detection: **46.7%**
  - exposure at T0: **0.757**
- V1:
  - detection: **33.3%**
  - exposure at T0: **0.847**
- V1 + fragility:
  - detection: **40.0%**
  - exposure at T0: **0.846**

### Middle calibration → later OOS
- V0:
  - detection: **46.7%**
  - exposure at T0: **0.757**
- V1:
  - detection: **33.3%**
  - exposure at T0: **0.847**
- V1 + fragility:
  - detection: **46.7%**
  - exposure at T0: **0.844**

Conclusion:
- later regime is the current weak point
- fragility helps V1, but V0 still wins on raw protection

## Earlier-regime OOS
(~2020-07 → 2022-06, 41 events)

### Backward calibration
- V0:
  - detection: **43.9%**
  - exposure at T0: **0.698**
- V1:
  - detection: **39.0%**
  - exposure at T0: **0.737**
- V1 + fragility:
  - detection: **51.2%**
  - exposure at T0: **0.734**

### Middle calibration → earlier OOS
- V0:
  - detection: **43.9%**
  - exposure at T0: **0.698**
- V1:
  - detection: **41.5%**
  - exposure at T0: **0.736**
- V1 + fragility:
  - detection: **51.2%**
  - exposure at T0: **0.734**

Conclusion:
- in earlier regimes, V1 + fragility clearly improves on V1
- but V0 still has the best raw T0 exposure

## Regime-dependent motif behavior

### Later regime
Mostly:
- transition_false_alarm: **60%**
- recirculating_instability: **33.3%**
- quiet_loading_release: **6.7%**
- plateau: **0%**

Interpretation:
- later regime looks messy, pulsing, transition-heavy

### Earlier regime (V1 + fragility)
- occupied_danger_plateau: **34.1%**
- recirculating_instability: **26.8%**
- quiet_loading_release: **19.5%**
- transition_false_alarm: **19.5%**

Interpretation:
- earlier regime has richer grammar
- fragility shifts the model away from false alarms toward plateau recognition

## Big picture conclusion
The architecture survives.

But:
> **great at interpretation, not yet best-in-class at action**

---

# 9. Non-obvious connections discovered

## 9.1 Fragility changes interpretation more than raw detection
Removing fragility changed **what kind of world** the system thinks it is seeing.

Without fragility:
- quiet-loading collapses
- transition-false-alarm explodes

This means fragility is acting as a **type discriminator**, not just a performance enhancer.

## 9.2 Hazard memory shapes time more than identity
Hazard memory improves persistence and timing,
but motifs stay relatively stable across decay values.

Interpretation:
- fragility helps define process identity
- hazard memory helps define temporal response

## 9.3 Real BTC is more recirculating than synthetic
Reality shows more:
- clustered pulsing stress
- repeated disturbance loops
- late feedback behavior

Synthetic generator probably under-represents this.

## 9.4 Different motifs become visible at different phases
This is one of the biggest results in the project.

It strongly suggests the system is seeing genuine process geometry, not just threshold artifacts.

## 9.5 Oracle weakness is now localized
The split battery suggests:
- earlier regime structure is more legible
- later regime is transition-heavy and harder to ground

So the next improvement should be:
- **late-regime Oracle grounding**
not architecture expansion.

---

# 10. Current diagnosis

## Proven
- fragility matters
- motifs are real enough to study
- prefix visibility is motif-specific
- regime direction matters
- the architecture survives reality

## Not yet proven
- that V1 + fragility beats V0 consistently on raw real multi-regime protection

## Main bottleneck
**Oracle grounding for later-regime environments**

That is the clearest current target.

---

# 11. Current next task (latest handoff)

## Task title
**Event Independence Audit + Late-Regime Oracle Grounding Ladder**

Stored here:
- `claude_task8_event_audit_and_grounding_ladder.md`

## Why this is next
Two issues remain:
1. later-regime events may be oversliced
2. Oracle posterior is too compressed in later-regime conditions

## Part A — Event independence audit
Need to test whether later-regime event detection is slicing one prolonged cascade into multiple artificial events.

Audit variants:
- current threshold / lookback / gap
- larger minimum gap
- stricter drawdown threshold (e.g. -7%)
- optionally longer lookback

Need to answer:
- is later-regime weakness partly overstated by overslicing?

## Part B — Late-regime Oracle grounding ladder
Use only minimal L1 proxies at first:

### Proxy 1 — Drawdown Damage
- rolling distance from 30d / 60d high
- mapped to [0,1]

### Proxy 2 — Volatility Regime
- 7d / 14d realized vol percentile vs rolling history

**Do not add slow funding to Oracle yet.**

Reason:
- funding already enters through fragility
- adding it into Oracle L1 risks double-counting

## Success condition
In later-regime OOS:
- transition_false_alarm share falls
- structural motifs become more coherent
- V1 + fragility closes the gap vs V0 on detection and/or T0 exposure
- prefix recognition improves in the 8h–4h zone

---

# 12. Funding double-counting guardrail

The project explicitly decided:

- **Do not add slow funding to Oracle L1 yet**

Before ever adding it, measure:
- correlation between slow-funding proxy and fragility score
- whether it adds genuinely new information

This should be an explicit choice, not an accident.

---

# 13. Recommended “first prompt” for a new chat

Paste something like this into a new ChatGPT chat:

> Read `frankenoracle_detailed_report_for_claude.md` and `claude_task8_event_audit_and_grounding_ladder.md` first. This project is an instability observatory, not just a BTC trading model. The current diagnosis is: fragility is load-bearing, motifs are real enough to study, hazard memory fixed the time-axis bug, but later-regime Oracle grounding is the main bottleneck and event slicing may be overstating later-regime weakness. Continue from there without redesigning the architecture.

---

# 14. Key files to prioritize in a fresh chat

## Read first
- `oracle.py`
- `signals.py`
- `hazard_memory.py`
- `fragility.py`
- `event_forensics.py`
- `motif_engine.py`
- `motif_harness.py`
- `backtest.py`
- `run.py`
- `fetcher.py`
- `real_smoke_test_summary.md`
- `real_event_summary.json`
- `fragility_ablation_pure_off.json`
- `seed_sweep.json`
- `prefix_prediction.json`
- `prefix_prediction_by_motif.json`
- `frankenoracle_detailed_report_for_claude.md`
- `claude_task8_event_audit_and_grounding_ladder.md`

## Other files currently present in workspace
- `0aaa577d9bd249d6a884e90ff788036b.csv`
- `3078d8fbf274423a950846ff354169a4.csv`
- `3b8d79edb97d426bbdb645ff1cc8a0f8.csv`
- `3yearcompress.zip`
- `66ca1b8d74b74bf8a5c6dfc8414983d1.csv`
- `RUNBOOK.md`
- `adaptive_convergence_tail_retest_pack.zip`
- `adef20ba630342d9be0c2843ac9287a1.csv`
- `adversary_upgrade_plan_v2.md`
- `adversary_v0_report.jsx.txt`
- `adversary_v1_evaluation_charter.md`
- `adversary_v1_fragility_aware_spec.md`
- `backtest.py`
- `bitcoin_oracle_structural_signals.md`
- `btc_candles_5m (1).csv`
- `btc_funding_rate (1).csv`
- `btc_open_interest_1h (1).csv`
- `bybit_btc_github_links_bundle.zip`
- `cascade_flow_direction_research_note.md`
- `claude_adversary_v0_assignment.md`
- `claude_oracle_engineering_tasks.md`
- `claude_task3_structural_fragility.md`
- `claude_task4_motif_engine.md`
- `claude_task5_motif_robustness_harness.md`
- `claude_task7_real_data_smoke_test.md`
- `claude_task8_event_audit_and_grounding_ladder.md`
- `event_forensics.py`
- `event_summary.json`
- `events_report.csv`
- `fetcher.py`
- `fragility.py`
- `fragility_ablation.json`
- `fragility_ablation_pure_off.csv`
- `fragility_ablation_pure_off.json`
- `frankenoracle_detailed_report_for_claude.md`
- `frankenoracle_evolution_notes.md`
- `hazard_memory.py`
- `label_family_regime_recompute_pack.zip`
- `layer1_episode_taxonomy_pack.zip`
- `layer1_structured_hazard_arm_report.md`
- `layer1_structured_hazard_arm_schema.md`
- `layer2_data_acquisition_pack.zip`
- `motif_engine-3.py`
- `motif_engine.py`
- `motif_harness-1.py`
- `motif_harness.py`
- `motif_report.csv`
- `motif_summary.json`
- `oracle.py`
- `oracle_autonomous_execution_plan.md`
- `oracle_change_memo_pack.zip`
- `oracle_direction_reset_transformations_flow_grammar.md`
- `oracle_grounding_memo.md`
- `oracle_instability_energy_landscape_memo.md`
- `oracle_project_docs_pack.zip`
- `oracle_project_state_march_2026.md`
- `oracle_whole_system_interpretation_memo.md`
- `poopooooooo.zip`
- `posterior_governor_pack.zip`
- `posterior_layer1_lookup_pack.zip`
- `posterior_protocol_and_salvage_pack.zip`
- `prefix_prediction.json`
- `prefix_prediction_by_motif.csv`
- `prefix_prediction_by_motif.json`
- `project_resource_manifest.csv`
- `project_resource_map.md`
- `project_source_of_truth_bundle.zip`
- `real_event_summary.json`
- `real_events_report.csv`
- `real_fragility_summary.csv`
- `real_motif_report.csv`
- `real_smoke_test_summary.md`
- `run.py`
- `seed_sweep.json`
- `signals.py`
- `streamB_fast_onset_pack.zip`
- `three_path_v2_walkforward_pack.zip`
- `three_path_v2c_decision_pack.zip`
- `three_path_v2c_implementation_pack.zip`

---

# 15. Bottom line

FrankenOracle is now in this state:

> **Great at interpretation, not yet best-in-class at action.**

It has earned the right to be tested harder.
The next honest move is not expansion.
It is:

1. event-definition honesty
2. late-regime Oracle grounding
3. then re-evaluate whether later-regime weakness was structural or just underspecified

That is the shortest path to the next truth.
