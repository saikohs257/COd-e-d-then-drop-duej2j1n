"""
Adversary v0 — Main Runner (ENHANCED)
Oracle Project | March 2026

Modes:
  synthetic    Pipeline validation (no API)
  live_fetch   Real Kraken data, signal demo
  full         Complete backtest with CSVs

Usage:
  python run.py --mode synthetic
  python run.py --mode live_fetch
  python run.py --mode full --oracle-csv X --candles-csv Y --events-csv Z
  python run.py --mode full --oracle-csv X --candles-csv Y --events-csv Z --trace
"""

import sys, os, time, argparse
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from signals import OracleTick, Candle5m, AdversaryV0, VolSurpriseSignal, HaircutFunction, ContestationEngine
from backtest import Crash72Event, BacktestEngine, AblationRunner, generate_report
from fetcher import KrakenFetcher, load_candles_from_csv, load_oracle_from_csv, load_events_from_csv


class SyntheticGenerator:
    def __init__(self, seed=42):
        self.rng = np.random.RandomState(seed)

    def generate(self, days=90):
        cpd = 288
        n = days * cpd
        t0 = time.time() - days * 86400
        prices = self._prices(n)
        candles = self._candles(prices, t0)
        events = self._crashes(prices, t0)
        oracle = self._posterior(prices, events, t0)
        return {'oracle_history': oracle, 'candles': candles, 'crash_events': events}

    def _prices(self, n):
        p = [50000.0]
        dt = 5 / (365.25 * 24 * 60)
        crashes = sorted(self.rng.choice(range(n//4, n-500), size=self.rng.randint(5,9), replace=False))
        crash_set = set()
        for cc in crashes:
            for j in range(self.rng.randint(12, 72)):
                crash_set.add(cc + j)
        for i in range(1, n):
            r = self.rng.normal(-0.003, 0.008) if i in crash_set else self.rng.normal(0.3*dt, 0.7*np.sqrt(dt))
            p.append(p[-1] * (1 + r))
        return p

    def _candles(self, prices, t0):
        out = []
        for i, p in enumerate(prices):
            n = self.rng.uniform(0.998, 1.002, 3)
            out.append(Candle5m(timestamp=t0+i*300, open=p*n[0], high=p*max(n),
                                low=p*min(n), close=p,
                                vwap=p*(1+self.rng.uniform(-0.0002,0.0002)),
                                volume=self.rng.uniform(5,500), count=self.rng.randint(10,1000)))
        return out

    def _crashes(self, prices, t0):
        events = []
        i = 0
        while i < len(prices) - 864:
            w = prices[i:i+864]
            t = min(w)
            dd = (t - w[0]) / w[0]
            if dd < -0.05:
                ti = w.index(t)
                events.append(Crash72Event(t0+i*300, t0+(i+ti)*300, dd, f'synth_{len(events)}'))
                i += ti + 100
            else:
                i += 288
        return events

    def _posterior(self, prices, events, t0):
        cph = 12
        nh = len(prices) // cph
        cs = [e.start_time for e in events]
        hist = []
        post = 0.15
        for h in range(nh):
            ts = t0 + h * 3600
            ci = h * cph
            near = any(-2 < (s-ts)/3600 < 12 for s in cs)
            si = max(0, ci-72)
            rr = (prices[ci]-prices[si])/prices[si] if si<len(prices) and ci<len(prices) and prices[si]>0 else 0
            tgt = min(1.0, 0.6+abs(rr)*5) if near else max(0.05, 0.15+abs(rr)*3)
            a = 0.3 if near else 0.1
            post = np.clip(post*(1-a)+tgt*a, 0, 1)
            hist.append(OracleTick(ts, float(post), oracle_cap=float(max(0.1, 1-0.8*post))))
        return hist


def run_synthetic():
    print("="*60)
    print("ADVERSARY v0 — SYNTHETIC VALIDATION (ENHANCED)")
    print("="*60)
    data = SyntheticGenerator(42).generate(90)
    print(f"\n  Oracle: {len(data['oracle_history'])} ticks")
    print(f"  Candles: {len(data['candles'])}")
    print(f"  Crashes: {len(data['crash_events'])}")
    for i, e in enumerate(data['crash_events']):
        print(f"    [{i:2d}] {e.label}  dd={e.drawdown_pct:.1%}")

    engine = BacktestEngine(data['oracle_history'], data['candles'], data['crash_events'])
    baseline = engine.run_baseline()

    configs = {}
    for wv in ['equal', 'stress_dominant']:
        name = f"adversary_A_{wv}"
        print(f"  Running {name}...")
        adv = AdversaryV0(variant='A', weight_version=wv)
        adv.calibrate(data['oracle_history'])
        configs[name] = engine.run_adversary(adv, name)

    print("  Running ablation...")
    abl = AblationRunner(engine).run_full_ablation('A', 'equal')

    print("\n" + generate_report(baseline, configs, abl))


def run_live_fetch():
    print("="*60)
    print("ADVERSARY v0 — LIVE SIGNAL CHECK (ENHANCED)")
    print("="*60)
    fetcher = KrakenFetcher(use_futures=False)
    try:
        candles = fetcher.fetch_candles(28)
    except RuntimeError as e:
        print(f"  FETCH FAILED: {e}")
        candles = SyntheticGenerator(99).generate(3)['candles']

    print(f"  {len(candles)} candles")
    if candles:
        t0 = time.strftime('%Y-%m-%d %H:%M', time.gmtime(candles[0].timestamp))
        t1 = time.strftime('%Y-%m-%d %H:%M', time.gmtime(candles[-1].timestamp))
        print(f"  Range: {t0} → {t1} UTC")
        print(f"  Price: ${candles[-1].close:,.2f}")

    # Both estimators for comparison
    vs_park = VolSurpriseSignal(use_parkinson=True)
    vs_cc = VolSurpriseSignal(use_parkinson=False)
    v_park = vs_park.compute(candles)
    v_cc = vs_cc.compute(candles)

    print(f"\n  Vol Surprise (Parkinson): {v_park:.4f}")
    print(f"  Vol Surprise (close-close): {v_cc:.4f}")
    print(f"  Difference: {abs(v_park - v_cc):.4f}")

    for wv in ['equal', 'stress_dominant']:
        ce = ContestationEngine('A', wv)
        s = ce.score(0.0, v_park)
        hf = HaircutFunction()
        h, state = hf.compute(s)
        print(f"  [{wv:>16}] contest={s:.4f}  haircut={h:.4f}  [{state}]")
        hf.reset()


def run_full(oracle_csv, candles_csv, events_csv, collect_trace=False):
    print("="*60)
    print("ADVERSARY v0 — FULL BACKTEST (ENHANCED)")
    print("="*60)

    oracle_history = load_oracle_from_csv(oracle_csv)
    print(f"  Oracle: {len(oracle_history)} ticks")
    has_l1 = any(t.l1_structural is not None for t in oracle_history)
    has_l2 = any(t.l2_context is not None for t in oracle_history)
    print(f"  L1: {has_l1}  L2: {has_l2}")

    candles = load_candles_from_csv(candles_csv)
    print(f"  Candles: {len(candles)}")

    events = load_events_from_csv(events_csv)
    print(f"  Events: {len(events)}")

    engine = BacktestEngine(oracle_history, candles, events)
    baseline = engine.run_baseline()

    variants = ['A']
    if has_l1 and has_l2:
        variants.append('B')

    configs = {}
    for v in variants:
        for wv in ['equal', 'stress_dominant']:
            name = f"adversary_{v}_{wv}"
            print(f"  Running {name}...")
            adv = AdversaryV0(variant=v, weight_version=wv)
            cal = adv.calibrate(oracle_history)
            print(f"    turbulence_denom={cal['turbulence_norm_denominator']:.4f}")
            configs[name] = engine.run_adversary(adv, name, collect_trace=collect_trace)

            if collect_trace and configs[name].trace:
                trace_path = os.path.join(os.path.dirname(__file__), f'trace_{name}.csv')
                configs[name].trace.to_csv(trace_path)
                print(f"    Trace → {trace_path}")

    print("  Running ablation (A/equal)...")
    abl = AblationRunner(engine).run_full_ablation('A', 'equal')

    report = generate_report(baseline, configs, abl)
    print("\n" + report)

    rpath = os.path.join(os.path.dirname(__file__), 'adversary_v0_report.txt')
    with open(rpath, 'w') as f:
        f.write(report)
    print(f"\nReport: {rpath}")


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('--mode', choices=['synthetic','live_fetch','full'], default='synthetic')
    p.add_argument('--oracle-csv')
    p.add_argument('--candles-csv')
    p.add_argument('--events-csv')
    p.add_argument('--trace', action='store_true', help='Export tick-by-tick trace CSVs')
    args = p.parse_args()

    if args.mode == 'synthetic':
        run_synthetic()
    elif args.mode == 'live_fetch':
        run_live_fetch()
    elif args.mode == 'full':
        missing = [n for n,v in [('--oracle-csv',args.oracle_csv),
                                  ('--candles-csv',args.candles_csv),
                                  ('--events-csv',args.events_csv)] if not v]
        if missing:
            print(f"Required: {', '.join(missing)}")
            sys.exit(1)
        run_full(args.oracle_csv, args.candles_csv, args.events_csv, args.trace)
