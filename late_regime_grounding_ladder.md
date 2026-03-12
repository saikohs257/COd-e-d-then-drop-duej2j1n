# Late-Regime Oracle Grounding Ladder

**Event definition:** Var1(-5%,24h,48h)
**Events:** 76

**Adversary note:** sigmoid mid recalibrated from 0.50 to 0.446 to match oracle compressed output range.

## Results

| Pass | Model | Detection% | Exp T0 | Pre-24h Exp | Persistence | FP/evt |
|------|-------|-----------|--------|-------------|-------------|--------|
| 0 | V0 | 25.0% | 0.336 | 0.336 | 18.8 | 141.2 |
| 0 | V1 | 25.0% | 0.336 | 0.336 | 18.8 | 141.1 |
| 0 | V1+Frag | 43.4% | 0.331 | 0.33 | 33.5 | 988.4 |
| 1 | V0 | 43.4% | 0.375 | 0.356 | 36.8 | 458.2 |
| 1 | V1 | 43.4% | 0.375 | 0.356 | 37.0 | 458.1 |
| 1 | V1+Frag | 60.5% | 0.371 | 0.352 | 49.5 | 1215.9 |
| 2 | V0 | 42.1% | 0.369 | 0.359 | 31.5 | 389.9 |
| 2 | V1 | 43.4% | 0.369 | 0.359 | 31.5 | 389.7 |
| 2 | V1+Frag | 61.8% | 0.364 | 0.354 | 45.4 | 1194.3 |

## Verdict

- Drawdown helped: **Yes**
- Vol regime helped: **Yes**
- Gap closed vs V0: **Yes**

## Funding Double-Count Guardrail

Correlation: **0.032** [LOW]

Funding and fragility are sufficiently distinct (r=0.03). Safe to consider slow funding for future L1 proxy.
