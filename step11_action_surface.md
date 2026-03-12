# Step 11 — Action-Surface Falsification Report

**Question:** Is action-surface misregistration the dominant remaining failure?

**Event definition:** −5%, 24h lookback, 48h gap → 76 events
**Oracle grounding:** Pass 2 (Drawdown Damage + Vol Regime) — fixed

## Results

| Metric | Current | Cand A | Cand B | Cand C |
|--------|---------|--------|--------|--------|
| Detection % | 21.1%|35.5%|50.0%|78.9% |
| Exp T0 | 0.377|0.373|0.365|0.351 |
| Pre-24h Exp | 0.367|0.363|0.356|0.344 |
| Persistence | 18.1|27.9|39.8|60.3 |
| Active occ % | 25.2%|30.1%|40.0%|62.7% |
| Half-on % | 78.2%|80.7%|88.3%|95.0% |
| Decisive % | 0.0%|0.0%|0.1%|0.6% |
| Active off-evt % | 22.1%|25.7%|34.0%|52.8% |
| FA episodes | 58|104|157|194 |
| FP h/30d | 159.4|184.9|244.7|380.3 |
| TFA % | 6.6%|6.6%|6.6%|6.6% |
| Structural % | 93.4%|93.4%|93.4%|93.4% |

## Motif Distribution

| Motif | Current | Cand A | Cand B | Cand C |
|-------|---------|--------|--------|--------|
| QLR | 0|0|0|0|
| ODP | 70|70|70|71|
| RI | 1|1|1|0|
| TFA | 5|5|5|5|
| UNK | 0|0|0|0|

## Verdict

**PARTIAL CONFIRMATION — curve is part of the problem but not the whole problem**

- B lowers T0: Yes (0.377 → 0.365)
- B lowers pre24h: Yes (0.367 → 0.356)
- B reduces half-on: No (78.2% → 88.3%)
- B preserves structural motifs: Yes
- B doesn't explode off-event occupancy: Yes
- Motif divergence detected: No
