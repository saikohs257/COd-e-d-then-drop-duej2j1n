# Real-Data Smoke Test — Assessment
**Data:** Dec 11 2025 → Mar 11 2026 (91 days, Bybit/Binance)
**Oracle status:** PARTIAL — L2 grounded (realized vol, price momentum, funding rate). L1 stubbed (no onchain risk, no macro trend).

---

## Results at a glance

| Metric | Value |
|--------|-------|
| Crash events detected | 17 |
| Adversary detection rate | 52.9% |
| Mean signal persistence | 3.9 bars (~20 min) |
| False positives / event | 0.00 |
| Fragility mean | 0.203 |
| Fragility max | 0.748 (Jan 20) |

---

## A. Did the system collapse into nonsense?

**No.** Architecture survived contact with real data.

- Fragility is not flat. It ranges 0.0–0.748 with meaningful variation.
- Motif assignments cover all four families — not degenerate.
- Hazard memory produces haircuts without pathological lock-in.
- Zero false positives is suspicious (see C below).

---

## B. What looked structurally promising?

**Fragility behaviour is the clearest positive signal.**

Three events show the expected fragility → crash sequence:

- **Dec 15**: fragility climbs from 0.13 (t-48h) to 0.58 (t-24h) before a −5.1% drop. Classified `quiet_loading_release`. Correct pattern.
- **Jan 20**: fragility spikes from 0.09 (t-48h) to 0.74 (t-6h) before −5.0% drop. Highest confidence assignment (0.62). Classified `quiet_loading_release`. The fragility peak cluster (Jan 20, 15:00–21:00) aligns with the event perfectly.
- **Feb 5 (−9.8%)**: fragility rises from 0.00 to 0.60 in the 12h before the largest crash in the window. Classified `recirculating_instability`. Fragility was doing work before the worst event.
- **Feb 24**: fragility 0.02 → 0.64 (t-24h) → 0.60 (t0). Clean pre-loading pattern.

**Motif distribution is coherent:**
- `quiet_loading_release`: 7/17 (41%) — dominant, matches synthetic expectation
- `recirculating_instability`: 5/17 (29%) — elevated vs synthetic, plausible given cascading Feb events
- `transition_false_alarm`: 4/17 (24%) — high, but these events are genuinely borderline
- `occupied_danger_plateau`: 1/17 — Jan 20 post-spike residual, reasonable

---

## C. What failed?

**1. Detection rate is 53% — worse than synthetic (~97%)**
The Adversary fires on 9/17 events. The 8 misses are all Category E ("oracle already sufficient") which means the Oracle cap was already constraining exposure without the Adversary needing to act. This is an Oracle blindness problem: with L1 stubbed, the posterior sits in a narrow band (mean=0.375, std=0.025) and never reaches high enough to trigger the hazard threshold on its own.

**2. Lead time is 0h across the board**
The Adversary fires at or after T0 on every detected event, not before. In synthetic data, fragility gave 2–6h lead. On real data the hazard kernel isn't accumulating enough signal pre-event. Likely cause: OI resolution is 1h vs the 5m candle resolution — fragility updates are coarse. Also: the event detection threshold (−5%) is too tight — many "events" are just the tail of a move the Adversary caught late.

**3. Feb 2–4 cluster: fragility flat-zero before three consecutive drops**
Feb 2, 3, 4 all show frag=0.000 at all horizons. The OI data simply isn't moving during this period — either OI was genuinely flat (possible in a choppy market) or the 1h cadence is missing intraday spikes. This is a data resolution problem, not a model problem.

**4. Zero false positives is too clean**
In 91 days of real volatile BTC data, zero spurious warnings is implausible. The Adversary is probably under-firing due to the posterior being too flat (L1 stubbed → low baseline risk). This compresses the hazard score below the dead zone consistently.

---

## D. Next correction if partial success

This is **partial success** — architecture coherent, fragility informative on ~40% of events, motifs plausible. The system is not broken but is operating below capacity due to Oracle blindness.

**Recommended next step: ground the Oracle posterior with a simple real L1 proxy.**

The minimal viable L1 without onchain data:
- Use a 30-day rolling price drawdown from ATH as a structural risk proxy (0 = near ATH, 1 = deep bear)
- Use the 14-day realized vol percentile rank as a volatility regime signal

These are computable from the candle data we already have, require no external feed, and would widen the posterior range from (0.35–0.40) to something like (0.20–0.75) — enough for the Adversary's hazard threshold to activate pre-event.

That single change would likely push detection rate from 53% to 80%+ and restore lead time.

---

## Caveats

- Oracle L1 is fully stubbed. Results should be understood as "L2-only" performance.
- OI data is 1h cadence — fragility misses intraday OI spikes that would appear at higher resolution.
- 91 days is a short real-data window. The Feb cascade (4 events in 4 days) dominates the statistics.
- Motif confidence is calibrated for synthetic data — real-data confidence scores are slightly lower but rankings are consistent.
