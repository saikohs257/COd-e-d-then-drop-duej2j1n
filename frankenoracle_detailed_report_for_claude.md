# FrankenOracle — Detailed Findings Report for Claude
**Date:** 2026-03-11

## Purpose

This document is a high-detail handoff report for the next Claude session.

It records:

- the current architecture
- the completed experiments
- the main empirical findings
- the non-obvious connections discovered so far
- the current bottleneck
- the exact next task

This is meant to save time and prevent re-deriving conclusions already earned through testing.

---

# 1. Current Architecture

The project is no longer just a BTC trading model.
It is a survival-first instability detection architecture.

## Core stack

- **Oracle** → slow environment / risk cap
- **Predictor** → bounded opportunity expression
- **Adversary V1** → hazard activation and persistence
- **Structural Fragility** → slow structural weakness
- **Event Forensics** → event reconstruction / case files
- **Motif Engine** → process classification

## Action rule

```text
final_exposure =
    min(oracle_cap, predictor_desired)
    * adversary_haircut
```

## Current conceptual split

- Oracle = what kind of environment is this?
- Fragility = how loaded is the structure?
- Hazard memory = how long should skepticism persist?
- Motif engine = what process family is unfolding?

---

# 2. Components Implemented

## Adversary V1
Built and tested.

Main additions:
- `PosteriorLevelSignal`
- `HazardKernel`
- `AdversaryV1(AdversaryV0)` with compatible evaluate() signature

Headline synthetic results:
- detection rate at T0: **36.8% → 94.7%**
- persistence: **2.8 bars → 11.7 bars**
- false positives / event: **2.53 → 0.37**

Interpretation:
Hazard memory solved the core **time-axis bug** in V0.

---

## Structural Fragility Signal
Built and tested.

Inputs:
- open interest
- funding persistence

Design:
- OI = rolling percentile rank, centered so calm baseline does not bias upward
- funding = rolling mean / z-scored pressure, positive side only
- output = `fragility_score ∈ [0,1]`

Headline synthetic comparison:
- timing score: **84.2% → 94.7%**
- crash exposure reduction: **8.7% → 12.2%**
- mean exposure at T0: **0.445 → 0.428**
- false positives / event: **0.37 → 0.53**

Interpretation:
Fragility helped materially and did not meaningfully damage return behavior in synthetic tests.

Important design property:
**Fragility alone does not trigger haircuts.**
It amplifies acute signals; it does not replace them.

---

## Event Forensics Engine
Built and tested.

Main outputs:
- `events_report.csv`
- `event_summary.json`

Main structures:
- `TickRecord`
- `EventCaseFile`
- `ForensicsAggregate`

Tracks:
- exposure at T0
- lead time
- persistence
- dominant signal
- fragility at T0
- fragility peak pre-event
- failure taxonomy

Interpretation:
This converted the project from a strategy tester into a **scientific instrument**.

---

## Motif Engine
Built and tested.

Motifs:
- `quiet_loading_release`
- `occupied_danger_plateau`
- `recirculating_instability`
- `transition_false_alarm`
- `unknown`

Key hidden feature:
- signal sequence encoding, e.g. `fragility → turbulence → hazard`

Interpretation:
This is the first real **grammar layer** in the project.

---

## Motif Robustness Harness
Built and tested.

Experiments:
1. seed sweep
2. fragility ablation
3. hazard decay sweep
4. prefix motif prediction

This harness is now the main research tool for falsifying the grammar.

---

# 3. Synthetic Research Findings

## 3.1 Motif grammar is real enough to study
Across 20 synthetic worlds:

- `quiet_loading_release`: **60.3%**
- `occupied_danger_plateau`: **18.3%**
- `recirculating_instability`: **16.1%**
- `transition_false_alarm`: **5.3%**

Additional metrics:
- motif stability score for quiet-loading: **0.823**
- motif separation score: **0.419**
- timing score mean: **0.9656**
- detection rate mean: **0.9681**

Interpretation:
The motifs are not random labels. The grammar is structurally stable enough to justify further study.

---

## 3.2 Fragility is load-bearing
Pure-off fragility ablation:

### With fragility
- timing: **0.966**
- quiet_loading_release: **60.3%**
- transition_false_alarm: **5.3%**

### Pure-off
- timing: **0.890**
- quiet_loading_release: **12.5%**
- transition_false_alarm: **75.8%**

### Redistributed-off
- timing: **0.860**
- quiet_loading_release: **12.5%**
- transition_false_alarm: **75.8%**

Interpretation:
Fragility is genuinely load-bearing.
It is not cosmetic.
It is one of the main reasons the system can distinguish:

- **loaded structure**
from
- **temporary transition noise**

The pure-off vs redistributed-off comparison confirms the earlier ablation ambiguity is resolved.

---

## 3.3 Hazard decay is a real control surface
Decay sweep headline:
- best timing: **0.80**
- fewest false positives: **0.93**

Interpretation:
Hazard memory is no longer mysterious.
It is a real tradeoff knob:

- lower decay = sharper timing
- higher decay = calmer behavior

Non-obvious connection:
The motif grammar remained relatively stable across the decay sweep.
This suggests the motifs are more a property of the environment / event structure than of the exact kernel constant.

---

## 3.4 Prefix motif prediction works, but only in motif-specific windows

### Overall accuracy by horizon
- **T−12h:** 16.1%
- **T−8h:** 62.9%
- **T−4h:** 56.1%
- **T−2h:** 43.2%

This is not monotonic, which is important.

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
- ~90–100% at all horizons

Interpretation:
Different instability families become legible at different phases of formation.

This is one of the most important discoveries in the project so far.

### Meaning
There is probably **no single best warning horizon** for collapse.

Instead:
- plateau = early sickness
- quiet-loading = mid-window release
- recirculating = late pre-cascade
- false alarm = visible throughout

This is real grammar behavior.

---

## 3.5 Confidence calibration was fixed
Old confidence:
- pure rule match fraction

New confidence:
- rule match fraction
- plus winner margin over runner-up

Effect:
- mean confidence dropped from ~0.86 to ~0.40
- confidence became more honest / less swaggering

Interpretation:
The engine is now less overconfident and more trustworthy.

---

# 4. Real-Data Smoke Test Findings

## Real-data smoke test panel
Initial real-data contact used:
- BTC candles
- open interest
- funding

Headline real-data results:
- crash events: **17**
- detection rate: **52.9%**
- mean persistence: **3.9 bars**
- false positives / event: **0.00**
- fragility mean: **0.203**
- fragility max: **0.748**

Motif distribution:
- quiet_loading_release: **7**
- recirculating_instability: **5**
- transition_false_alarm: **4**
- occupied_danger_plateau: **1**

## What held up
- the system did **not** collapse into nonsense
- fragility showed meaningful rises before several real drops
- motifs remained interpretable
- recirculating instability was more common in reality than in synthetic

## What failed
- detection rate too low
- lead time effectively near zero in many cases
- Oracle still too compressed / underfed
- 1h OI cadence may be too blunt for 5m event structure

## Best real-data conclusion
Fragility survived reality **better than hazard timing**.

This is encouraging:
the system appears better at seeing that the ground is getting weak than at converting that into timely action.

Main diagnosis:
**Oracle judgment is still under-grounded.**

---

# 5. Full-Stack Real Split Battery

## Honest full-stack structural era
Because OI starts late from the source, the honest full-stack era is:

**2020-07-20 → 2026-03-11**

The earlier period is kept as reduced-feature context only.

## Split styles run
1. forward
2. backward
3. middle ascending
4. middle descending

## Models compared
- V0
- V1
- V1 + fragility

---

## 5.1 Later regime OOS
(roughly 2024-04 → 2026-03, 15 events)

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

### Interpretation
Later regime is the current weak point.
Fragility helps V1, but V0 still wins on raw protection.

This suggests the bottleneck is not motif logic.
It is likely the **Oracle slow-state baseline** in later-cycle conditions.

---

## 5.2 Earlier regime OOS
(roughly 2020-07 → 2022-06, 41 events)

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

### Interpretation
In earlier regimes, V1 + fragility clearly improves on V1.
But V0 still has the best raw T0 exposure.

Again:
**great at interpretation, not yet best-in-class at action.**

---

## 5.3 Regime-dependent motif behavior

### Later regime
All models mostly see:
- transition_false_alarm: **60%**
- recirculating_instability: **33.3%**
- quiet_loading_release: **6.7%**
- plateau: **0%**

Interpretation:
Later regime looks like messy, pulsing, transition-heavy instability.

### Earlier regime (V1 + fragility)
- occupied_danger_plateau: **34.1%**
- recirculating_instability: **26.8%**
- quiet_loading_release: **19.5%**
- transition_false_alarm: **19.5%**

Interpretation:
Earlier regime has richer grammar, and fragility shifts the model away from false alarms toward plateau recognition.

---

## 5.4 Prefix prediction survives split testing
Different motif families still show different visibility windows under the split battery.

This is one of the strongest pieces of evidence that the grammar is not a one-slice artifact.

---

# 6. Non-Obvious Connections Discovered

These are important and should not be lost.

## 6.1 Fragility changes interpretation more than raw detection
Removing fragility did not just worsen timing.
It changed **what kind of world** the system believed it was seeing.

Without fragility:
- quiet-loading collapsed
- transition-false-alarm exploded

This means fragility is acting as a **type discriminator**, not just a performance enhancer.

---

## 6.2 Hazard memory shapes time more than identity
Hazard memory improves persistence and timing behavior,
but the motif families themselves remain relatively stable across decay values.

Interpretation:
- fragility helps define process identity
- hazard memory helps define temporal response

This is an elegant split.

---

## 6.3 Real BTC is more recirculating than synthetic
In the real smoke test, recirculating instability showed up more often than in earlier synthetic mixes.

Interpretation:
The synthetic generator probably under-represents:
- clustered pulsing stress
- repeated disturbance loops
- late feedback behavior

This is important if synthetic worlds are to remain useful.

---

## 6.4 Different motifs become visible at different phases
This is one of the biggest results in the entire project.

Not all failures have the same “warning horizon.”

This strongly suggests the system is seeing genuine process geometry, not just threshold artifacts.

---

## 6.5 Oracle weakness is now localized
The split battery suggests:
- earlier regime structure is more legible
- later regime behavior is more transition-heavy and harder to ground

So the next improvement should be **late-regime Oracle grounding**, not random architecture expansion.

---

# 7. Data Availability / Honest Panel Policy

## Available starts from actual source pulls
- Candles: **2019-09-08**
- Funding: **2019-09-10**
- Open interest: **2020-07-20**

## Locked policy
### Full-stack structural era
**2020-07-20 → 2026-03-11**

Use for:
- fragility
- hazard memory
- motifs
- split battery
- serious evaluation

### Pre-structural era
**2019-09-08 → 2020-07-20**

Use only for:
- crash mapping
- reduced-feature context
- sanity checks

Do NOT backfill missing OI with nonsense.
Do NOT pretend full features existed earlier.

---

# 8. Current Diagnosis

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

This is the clearest next target.

---

# 9. Exact Next Task for Claude

## Title
**Late-Regime Oracle Grounding Ladder**

## Purpose
Improve the Oracle’s slow-state baseline in the later regime without redesigning the system.

## Hypothesis
The later regime is being seen as too much “transition noise” because the Oracle lacks enough slow environmental context.

## Minimal L1 grounding candidates
Implement and test incrementally:

### L1 Proxy 1 — Drawdown Damage
Example:
- rolling distance from 30d / 60d high
- mapped to `[0,1]`

Purpose:
capture already-damaged structure.

### L1 Proxy 2 — Volatility Regime
Example:
- 7d or 14d realized vol percentile versus rolling 90d / 180d history

Purpose:
persistent environment instability.

### L1 Proxy 3 — Slow Funding Pressure
Example:
- 3d / 7d funding average, normalized and capped

Purpose:
slow leverage regime, not acute funding spikes.

### Optional L1 Proxy 4 — Trend Damage
Example:
- slow MA damage / slope deterioration

Purpose:
prevent Oracle complacency in post-peak churn.

---

## Test ladder
Run later-regime OOS with:

1. baseline Oracle
2. + drawdown damage only
3. + drawdown damage + vol regime
4. + drawdown damage + vol regime + slow funding

Keep everything else fixed.

Compare:
- V0
- V1
- V1 + fragility

Metrics:
- detection rate
- exposure at T0
- mean exposure pre-event
- false positives
- persistence
- motif distribution
- prefix prediction by motif

Main question:
Does better L1 grounding convert later-regime transition noise into more useful structural motifs and earlier protection?

---

## Success condition
In the later regime:
- V1 + fragility begins to close the gap vs V0 on T0 exposure and/or detection
- transition_false_alarm share falls
- structural motifs become more coherent
- prefix recognition improves in the 8h–4h zone

## Failure condition
If later-regime performance barely moves, then the next suspects become:
- fragility normalization in later regimes
- hazard kernel shape
- motif rules too synthetic for later BTC conditions

But Oracle grounding should be tested first.

---

# 10. Bottom Line for Claude

The project is now in this state:

> **Great at interpretation, not yet best-in-class at action.**

Do not redesign the architecture.
Do not add new organs.
Do not add machine learning.

The next serious move is:
**targeted late-regime Oracle grounding**.

This is the shortest path to the next truth.
