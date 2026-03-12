# Claude Task 8 — Event Independence Audit + Late-Regime Oracle Grounding Ladder

## Purpose

This task is the next disciplined step in FrankenOracle.

It has two linked objectives:

1. **Audit event independence in the later regime**
2. **Run a minimal late-regime Oracle grounding ladder**

This task exists because the latest findings suggest two important issues:

- the Oracle posterior is too compressed in later-regime conditions
- the current later-regime event set may be oversliced, causing one cascade to appear as multiple separate events

Do not redesign the architecture.
Do not add new organs.
Do not add ML.

This is a **clean-up and grounding task**.

---

# Context

Current diagnosis:

- the system is **great at interpretation, not yet best-in-class at action**
- fragility remains load-bearing
- motifs are real enough to study
- later-regime OOS is the current weakness
- Oracle posterior is too compressed / under-grounded
- later-regime events may be oversliced by the current event detector

The immediate goal is to improve the honesty of the evaluation and the quality of the Oracle’s slow-state baseline.

---

# Part A — Event Independence Audit

## Why this matters

Current later-regime evaluation uses a crash detector around:

- drawdown threshold ≈ `-5%`
- lookback window ≈ `24h`
- minimum gap constraint

This may be slicing one prolonged cascade into multiple “events,” especially in clustered periods.

If so, detection metrics may look worse than they truly are because the event set is not independent.

---

## Objective

Audit whether later-regime events are genuinely independent episodes or fragments of the same larger stress process.

---

## Required comparisons

At minimum, compare event sets under these conditions:

### Baseline
- current threshold / lookback / gap settings

### Variant 1
- same threshold
- same lookback
- **larger minimum gap**

### Variant 2
- **stricter drawdown threshold** (for example `-7%`)
- same or slightly adjusted gap

If easy, also include:

### Variant 3
- same threshold
- **longer lookback**

---

## Deliverables for Part A

Produce an audit artifact, for example:

- `event_independence_audit.md`
- `event_independence_audit.json`
- optional CSV comparison

For each event-setting variant, report:

- total number of events
- event clusters / inter-event gaps
- average drawdown
- average event duration if available
- how many later-regime events look like cascade fragments

Please include a short written judgment:

- Is the current later-regime event set oversliced?
- If yes, what event definition should be used for the grounding ladder?

---

# Part B — Late-Regime Oracle Grounding Ladder

## Goal

Improve the Oracle’s slow-state baseline in the later regime with the smallest defensible set of L1 proxies.

The later regime currently looks too much like:

- transition_false_alarm
- recirculating_instability

with too little structural coherence.

The hypothesis is:

> the Oracle is missing enough slow context that it cannot distinguish later-cycle churn from truly degraded environment state.

---

## IMPORTANT constraint

### Do NOT add slow funding to Oracle yet.

Reason:
Funding already enters the system through **Structural Fragility**.
Adding slow funding directly into Oracle L1 risks **double-counting** the same underlying information.

So the grounding ladder should use only:

### Proxy 1 — Drawdown Damage
Example:
- rolling distance from 30d / 60d high
- mapped to `[0,1]`

Purpose:
capture already-damaged structure.

### Proxy 2 — Volatility Regime
Example:
- 7d / 14d realized vol percentile vs rolling 90d / 180d history

Purpose:
capture persistent environment instability, not event-level spikes.

---

## Grounding ladder passes

Run later-regime OOS with:

### Pass 0
- baseline Oracle

### Pass 1
- baseline Oracle + Drawdown Damage

### Pass 2
- baseline Oracle + Drawdown Damage + Volatility Regime

Keep everything else fixed.

Compare:
- V0
- V1
- V1 + fragility

---

## Metrics to compare

At minimum:

### Protection
- detection rate
- exposure at T0
- mean exposure pre-event
- persistence
- false positives

### Grammar
- motif distribution
- motif coherence / separation if available
- transition_false_alarm share
- structural motif share (quiet-loading / plateau / recirculating)

### Prefix
- overall prefix accuracy
- prefix accuracy by motif if easy

---

## Main question

Does adding minimal slow-state grounding in the later regime:

- reduce `transition_false_alarm` share?
- make structural motifs more coherent?
- improve V1 + fragility relative to V0 on action metrics?
- improve prefix recognition in the 8h–4h window?

---

# Part C — Funding Double-Counting Guardrail

Do not add slow funding to Oracle in this task.

However, please add a small diagnostic note or artifact that estimates:

- correlation between the proposed slow-funding proxy and current fragility score
- whether they appear strongly overlapping in later-regime periods

This can be simple and approximate.

The purpose is just to prevent accidental double-counting in future tasks.

Suggested output:
- `funding_overlap_note.md`
or a short section in the main report.

---

# Output Artifacts

Please return:

- `event_independence_audit.md`
- `event_independence_audit.json`
- `late_regime_grounding_ladder.md`
- `late_regime_grounding_ladder.json`

Optional:
- CSV summaries for each comparison
- small overlap note for slow funding vs fragility

---

# Required Written Assessment

Please answer clearly:

## 1. Event definition honesty
- Is the later-regime event set oversliced?
- Which event definition should be trusted going forward?

## 2. Oracle grounding impact
- Did Drawdown Damage help?
- Did Drawdown Damage + Vol Regime help more?
- Did later-regime action metrics improve?

## 3. Motif impact
- Did TFA share fall?
- Did structural motifs become more coherent?

## 4. Funding guardrail
- Does slow funding look distinct enough from fragility to consider later?
- Or is it likely duplicate information?

## 5. Next recommendation
- What is the next correction if Pass 2 still fails?

---

# Constraints

Do NOT:

- redesign Oracle architecture
- redesign the Adversary
- add new signal families
- add slow funding to Oracle in this task
- add ML
- hide bad results

This task is about:
- evaluation honesty
- minimal grounding
- disciplined next steps

---

# Success Criteria

This task is successful if we can answer, honestly:

1. Is later-regime evaluation currently overstating weakness due to event slicing?
2. Do simple slow L1 proxies materially improve later-regime behavior?
3. Is the later-regime weakness mainly an Oracle grounding problem?
4. Should slow funding remain excluded from L1 for now?

If those questions are answered cleanly, the task is complete.

---

# Output Format

Return:

1. modified code only if necessary
2. the audit / ladder output files
3. a concise explanation of what changed
4. the main findings
5. caveats
6. next recommendation

Be skeptical, explicit, and concrete.
