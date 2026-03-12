# Claude Prompt — Step 12 Hazard Manifold Widening Pass

Read these first if available:

- `frankenoracle_detailed_report_for_claude.md`
- `claude_task8_event_audit_and_grounding_ladder.md`
- `frankenoracle_task9_task10_internal_report.md`
- `frankenoracle_step11_action_surface_falsification.md`
- `step11_action_surface.md`
- `step11_action_surface.json`

Do NOT redesign the architecture.  
Do NOT add new organs.  
Do NOT add ML.  
Do NOT silently change event definitions.  
Do NOT turn this into another action-curve tuning pass.

You are running **Step 12: Hazard Manifold Widening Pass**.

The current project diagnosis is:

- Task 8 fixed event honesty and improved Oracle grounding
- Task 11 showed the current action curve was genuinely misregistered
- Candidate B improved detection and exposure
- but half-on occupancy got worse, not better
- decisive action barely increased
- event vs non-event hazard separation is too small:
  - event mean ≈ `0.295`
  - non-event mean ≈ `0.274`
  - gap ≈ `0.021`

Therefore the next sharp hypothesis is:

> The dominant remaining bottleneck is not action-shape softness alone.
> It is that the **hazard manifold is too flat** for any single sigmoid to discriminate sharply.

Your job is to test that hypothesis cleanly.

---

## Locked data / evaluation policy

Use the **honest later-regime full-stack setup**.

Use the later-regime event definition already recommended by the event audit:

- drawdown threshold: `-5%`
- lookback: `24h`
- minimum gap: `48h`

Do NOT revert to the oversliced event set.

Keep the latest Oracle grounding baseline from Task 8 fixed.
This is a hazard-space test, not another Oracle-grounding rewrite.

---

## Core idea of Step 12

Task 11 showed that a sharper / better-centered action curve can improve metrics a bit,
but the real issue is that event days and non-event days still live too close together in hazard space.

So Step 12 asks:

> Can we widen the event/non-event hazard manifold **before** the haircut curve is applied?

That means routing one or two slow-state signals **directly into hazard** rather than letting them exist only in Oracle cap.

---

## Important constraint

### Do NOT add slow funding yet
Do not route slow funding into hazard in this task.

Reason:
- funding already enters through Structural Fragility
- slow funding recently looked weakly correlated with fragility in one pass, but it is still too easy to accidentally duplicate information
- drawdown damage and vol regime are the cleaner first widening tests

---

## Passes to run

At minimum compare these three hazard stacks:

### Pass 0 — Current hazard stack
Use the current grounded-later-regime baseline from Task 11.

### Pass 1 — Hazard + Drawdown Damage
Route **drawdown damage** directly into hazard, not just Oracle cap.

Suggested role:
- slow structural stress enhancer
- should help distinguish quiet loaded days from truly damaged / event-adjacent days

### Pass 2 — Hazard + Drawdown Damage + Vol Regime
Add **volatility regime** directly into hazard as well.

Suggested role:
- persistent instability context
- should help separate sustained bad environment from ordinary churn

Keep the rest of the stack fixed:
- same event set
- same Oracle grounding baseline
- same fragility
- same motif logic
- same action curve baseline unless a clearly stated comparison requires otherwise

---

## Implementation discipline

Do NOT let this become a feature soup experiment.

The point is not to add five new hazard inputs.
The point is to test whether **one or two slow context signals** materially widen hazard separation.

Use small, explicit weights.
Document them.
Keep the change surgical.

If you use normalization, explain it clearly.

---

## What to measure

### 1. Hazard manifold separation
This is the main scoreboard now.

For each pass, report:

- event hazard mean
- event hazard median
- event hazard upper tail
- non-event hazard mean
- non-event hazard median
- non-event hazard upper tail
- simple separation metrics if easy:
  - mean gap
  - median gap
  - overlap estimate
  - percentile separation

The first question is:
**Did event and non-event hazard move farther apart?**

### 2. Action consequences
Using the same downstream action surface, report:

- detection rate
- exposure at T0
- mean exposure pre24h
- persistence
- half-on occupancy
- decisive occupancy
- off-event occupancy

We want to know whether wider hazard separation actually improves action behavior.

### 3. Grammar preservation
Report:

- motif distribution
- transition_false_alarm share
- structural motif share
- whether widening hazard destroys motif diversity or preserves structural motifs

### 4. Time-of-bite
Again, do not confuse stronger action with earlier action.

Please inspect whether:
- lower T0 exposure comes from earlier activation
or
- just stronger cutting at onset

---

## Interpretation guardrails

These are mandatory.

### Guardrail 1 — Widening hazard is the goal, not just improving top-line metrics
A pass is not a success merely because detection rises.
It is a success if the event/non-event hazard manifold actually widens.

### Guardrail 2 — Do not mistake chronic occupancy for discrimination
If a pass raises hazard everywhere, that is not useful widening.
That is just inflation.

We want:
- event hazard up more than non-event hazard
or
- non-event hazard down relative to event hazard
or both

### Guardrail 3 — Preserve structural motifs
If widening hazard makes every event look the same, that is not a true win.
The system should keep distinguishing structural process families.

### Guardrail 4 — Keep the action-surface question separate
If hazard widening helps, that does not automatically mean the current action curve is now perfect.
It just means Step 11 was being limited by a flat manifold.

---

## What counts as success

### Strong Step 12 success
A pass:
- materially widens event/non-event hazard separation
- reduces half-on occupancy
- increases decisive occupancy somewhat
- improves T0 and pre24h exposure
- preserves structural motifs

Meaning:
the next bottleneck really was **hazard manifold flatness**.

### Partial success
A pass:
- widens hazard separation somewhat
- improves some action metrics
- but half-on remains high or bite remains late

Meaning:
hazard flatness was part of the problem, but not the whole problem.

### Failure
A pass:
- barely changes hazard separation
- or raises both event and non-event hazard equally
- or improves metrics only by flattening motif structure
- or creates massive chronic occupancy

Meaning:
the issue is not mainly hazard-space flatness.
Look again at upstream signal design or motif-aware action.

---

## Hidden questions you must check

Please address these explicitly:

1. Does drawdown damage into hazard help more than drawdown damage into Oracle alone?
2. Does vol regime add genuinely new separation, or only small inflation?
3. Is hazard widening uniform across motifs, or does it help some process families more than others?
4. Does the later-regime “Occupied Danger Plateau” dominance persist after widening, or does the manifold recover more balanced structure?

---

## Deliverables

Return:

1. modified code only if needed
2. comparison outputs for Pass 0 / Pass 1 / Pass 2
3. a concise written assessment
4. a clear statement of which branch occurred:

- strong widening success
- partial widening success
- failure / inflation
- motif-specific widening

5. caveats
6. next recommendation

---

## Bottom line

This is not another generic tuning pass.

It is a falsification test of one sharp claim:

> The current action system cannot cut sharply because the event and non-event days remain too close together in hazard space.

Answer that question directly and honestly.
