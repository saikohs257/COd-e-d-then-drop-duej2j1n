# Claude Prompt — Step 11 Action-Surface Falsification Pass

Read these first if available:

- `frankenoracle_detailed_report_for_claude.md`
- `claude_task8_event_audit_and_grounding_ladder.md`
- `frankenoracle_task9_task10_internal_report.md`
- `frankenoracle_step11_action_surface_falsification.md`

Do NOT redesign the architecture.  
Do NOT add new organs.  
Do NOT add ML.  
Do NOT quietly change event definitions.  
Do NOT oversell results.

You are running **Step 11: Action-Surface Falsification Pass**.

The current project diagnosis is:

- event overslicing was real and has been corrected
- minimal Oracle grounding helped materially
- fragility remains load-bearing
- the dominant remaining weakness is no longer sensing
- the current weakness appears to be the **belief-to-action transform**
- the system seems to live too often on the **shoulder of its sigmoid**:
  it senses enough to worry, but not enough to commit
- the current bottleneck may be **action-surface misregistration relative to the occupied hazard manifold**

Your job is to test that hypothesis cleanly.

---

## Locked data / evaluation policy

Use the **honest later-regime full-stack setup**.

Use the later-regime event definition recommended by the event audit:

- drawdown threshold: `-5%`
- lookback: `24h`
- minimum gap: `48h`

Do NOT revert to the oversliced event set.

Keep the Oracle grounding baseline from Task 8 fixed.
This is an action-surface test, not another grounding experiment.

---

## Models / curves to compare

At minimum compare:

1. **Current curve**
2. **Candidate B — Balanced**
3. **Candidate C — Boundary probe**

Optional:
4. **Candidate A — Conservative** as a sanity anchor

Use these meanings:

### Current
Reference only.

### Candidate B — Balanced
- midpoint = `0.30`
- steepness = `14`
- dead_zone = `0.16`

Interpretation:
This is the main falsification probe.
It tests whether the current action surface is simply too far to the right / too soft for the actual occupied hazard band.

### Candidate C — Boundary probe
Treat C as a diagnostic boundary probe, not a default winner candidate.

Interpretation:
If C helps a lot without breaking occupancy or motifs, the system has been severely underacting.
If C explodes occupancy or distorts motif structure, softness was only part of the problem.

---

## What to measure

Measure all of these for each curve candidate.

### 1. Protection
- detection rate
- exposure at T0
- mean exposure pre24h
- persistence

### 2. Action shape
- time spent in **half-on zone**
- total active occupancy
- hazard distribution during events
- hazard distribution outside events

### 3. Grammar preservation
- motif distribution
- transition_false_alarm share
- structural motif share
- whether stronger action collapses motif diversity

### 4. Time-of-bite
This is critical.

Do NOT assume lower T0 automatically means earlier action.

You must explicitly examine whether lower T0 exposure comes from:
- **earlier action**
or
- merely **stronger action at onset**

### 5. False-positive honesty
Do NOT rely only on the old FP/event metric.

Also report:
- active windows outside event neighborhoods
- occupancy outside event windows
- half-on occupancy outside event windows

Reason:
later-regime BTC may genuinely live in a recirculating weak-danger ecology, so raw occupancy is not automatically bad.
We need to distinguish:
- isolated wrong alarms
- legitimate long danger occupancy
- mushy indecisive half-activation

---

## Very important interpretation guardrails

These are not optional.

### Guardrail 1 — Do not assume the current hazard band is the final true band
A win for Candidate B does **not** automatically prove that B is the permanent global solution.

A B win may mean either:
- the curve was truly misregistered
or
- the sensor / Oracle is still somewhat compressed and B is the least-bad compensation

You must keep that distinction explicit.

### Guardrail 2 — Watch half-on occupancy first
Half-on occupancy is now the central pathology.

Too much half-on means:
- the hazard cloud sits on the shoulder of the curve
- the system senses enough to worry
- but not enough to commit

This is more important than any one top-line metric.

### Guardrail 3 — Preserve structural motifs, not all diversity blindly
If stronger action helps by flattening everything into one regime, that is not success.

But also do not insist on preserving every noisy motif count.
The real question is:
- does the action layer preserve **structural motifs**
- while reducing **spurious transition mush**

### Guardrail 4 — One global sigmoid may be nearing its limit
If Candidate B helps some motifs and hurts others in a stable way, do NOT hand-wave that away.

That may be the first serious evidence that:
- one global action surface is becoming the wrong abstraction
- motif-aware action policy may eventually be needed

---

## How to read the results

Use this exact rubric.

### Strong confirmation of current hypothesis
Candidate B:
- lowers T0 exposure
- lowers pre24h exposure
- reduces half-on occupancy
- preserves structural motifs
- does not explode off-event occupancy

Meaning:
the dominant remaining problem was **action-surface misregistration**.

### Partial confirmation
Candidate B:
- improves some exposure or detection metrics
- but bite is still late
- or half-on occupancy remains high

Meaning:
the curve is part of the problem, but not the whole problem.

### Rejection of the current hypothesis
Candidate B and C:
- barely improve protection
- or improve it only by collapsing motif structure
- or create massive chronic occupancy

Meaning:
the dominant problem is not mainly curve softness.
Look upstream again.

### Motif-specific divergence
If B helps one motif family but hurts another in a stable way:

Meaning:
one global sigmoid may be aging out.
That is not a side note.
That is the next architectural frontier.

---

## Hidden questions you must check

Please explicitly address these:

1. Is the occupied hazard band stable across subperiods?
   - early full-stack vs later full-stack
   - quieter loaded periods vs pulsing stress periods

2. Is action weakness uniform across motifs?
   - maybe quiet-loading is undercut because the curve is too soft
   - maybe transition noise is overcut because the dead zone is too permissive

3. Does B improve structure or merely sharpen expression?
   - does it align action to real structure
   - or just make the same indecision look more decisive?

---

## Deliverables

Return:

1. modified code only if needed
2. the comparison outputs for Current / B / C
3. a concise written assessment
4. a clear statement of which branch occurred:

- B win
- B partial win
- B/C fail
- motif divergence

5. caveats
6. next recommendation

---

## Bottom line

This is not a tuning spree.

This is a falsification pass for one sharp claim:

> Now that sensing has improved, is the dominant remaining failure simply that the action surface is positioned in the wrong part of the hazard space?

Answer that question directly and honestly.
