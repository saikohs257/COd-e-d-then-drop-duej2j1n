"""
Adversary v0 — Backtest Harness & Ablation (ENHANCED)
Oracle Project | March 2026

Audit fixes applied:
  [5]  Crash events outside data range are flagged and excluded
  [6]  Timing score uses relative threshold (haircut value, not absolute gap)
  [13] Full time series output for diagnostic overlay
  [14] Lightweight transaction cost model (turnover-based)
  Prior: ablation disables cooldown to prevent state contamination
"""

import numpy as np
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Tuple
from signals import (
    OracleTick, Candle5m, AdversaryV0, AdversaryOutput,
    ContestationEngine, HaircutFunction, SignalContribution,
)


# ─────────────────────────────────────────────────────────────
# Crash72 Event
# ─────────────────────────────────────────────────────────────

@dataclass
class Crash72Event:
    start_time: float
    end_time: float
    drawdown_pct: float
    label: str = ''


# ─────────────────────────────────────────────────────────────
# Time Series Trace — FIX [13]
# ─────────────────────────────────────────────────────────────

@dataclass
class BacktestTrace:
    """Full tick-by-tick time series for diagnostic overlay."""
    timestamps: List[float] = field(default_factory=list)
    prices: List[float] = field(default_factory=list)
    oracle_caps: List[float] = field(default_factory=list)
    exposures: List[float] = field(default_factory=list)
    haircuts: List[float] = field(default_factory=list)
    contestation_scores: List[float] = field(default_factory=list)
    turbulence: List[float] = field(default_factory=list)
    vol_surprise: List[float] = field(default_factory=list)
    dominant_signal: List[str] = field(default_factory=list)
    capital: List[float] = field(default_factory=list)

    def to_csv(self, filepath: str):
        """Export trace for plotting in external tools."""
        import csv
        with open(filepath, 'w', newline='') as f:
            w = csv.writer(f)
            w.writerow(['timestamp', 'price', 'oracle_cap', 'exposure', 'haircut',
                        'contestation', 'turbulence', 'vol_surprise', 'dominant', 'capital'])
            for i in range(len(self.timestamps)):
                w.writerow([
                    f'{self.timestamps[i]:.0f}',
                    f'{self.prices[i]:.2f}',
                    f'{self.oracle_caps[i]:.4f}',
                    f'{self.exposures[i]:.4f}',
                    f'{self.haircuts[i]:.4f}',
                    f'{self.contestation_scores[i]:.4f}' if i < len(self.contestation_scores) else '',
                    f'{self.turbulence[i]:.4f}' if i < len(self.turbulence) else '',
                    f'{self.vol_surprise[i]:.4f}' if i < len(self.vol_surprise) else '',
                    self.dominant_signal[i] if i < len(self.dominant_signal) else '',
                    f'{self.capital[i]:.6f}',
                ])


# ─────────────────────────────────────────────────────────────
# Backtest Metrics
# ─────────────────────────────────────────────────────────────

@dataclass
class BacktestMetrics:
    config_name: str
    variant: str
    weight_version: str

    # Protection
    mean_crash_exposure: float
    mean_pre24h_exposure: float
    min_pre24h_exposure: float
    worst_event_exposure: float

    # Returns
    return_multiple: float
    return_multiple_net: float          # FIX [14]: after transaction costs
    max_drawdown_proxy: float
    total_turnover: float               # FIX [14]: sum of |exposure changes|

    # Behavior
    haircut_occupancy: float
    mean_haircut_when_active: float
    haircut_timing_score: float

    # Events
    per_event_exposure: List[float] = field(default_factory=list)
    events_in_range: int = 0            # FIX [5]: events within data range
    events_excluded: int = 0            # FIX [5]: events outside data range

    # Diagnostic
    trace: Optional[BacktestTrace] = None

    def protection_vs_cost(self, baseline: 'BacktestMetrics') -> Dict[str, float]:
        if baseline.mean_crash_exposure > 0:
            crash_reduction = 1.0 - (self.mean_crash_exposure / baseline.mean_crash_exposure)
        else:
            crash_reduction = 0.0

        if baseline.return_multiple_net > 0:
            return_cost = 1.0 - (self.return_multiple_net / baseline.return_multiple_net)
        else:
            return_cost = 0.0

        passes = (
            crash_reduction >= 0.15 and
            return_cost <= 0.08 and
            self.worst_event_exposure < baseline.worst_event_exposure and
            self.haircut_occupancy < 0.35 and
            self.haircut_timing_score > 0.5
        )

        return {
            'crash_exposure_reduction': crash_reduction,
            'return_cost': return_cost,
            'return_cost_gross': 1.0 - (self.return_multiple / max(1e-10, baseline.return_multiple)),
            'worst_event_improvement': baseline.worst_event_exposure - self.worst_event_exposure,
            'passes_acceptance': passes,
        }


# ─────────────────────────────────────────────────────────────
# Backtest Engine — ENHANCED
# ─────────────────────────────────────────────────────────────

class BacktestEngine:

    # FIX [14]: default taker fee for Kraken perps
    DEFAULT_FEE_RATE = 0.0003  # 0.03% per side

    def __init__(self, oracle_history: List[OracleTick],
                 candles: List[Candle5m],
                 crash_events: List[Crash72Event],
                 fee_rate: float = DEFAULT_FEE_RATE):
        self.oracle_history = sorted(oracle_history, key=lambda t: t.timestamp)
        self.candles = sorted(candles, key=lambda c: c.timestamp)
        self.fee_rate = fee_rate

        self._candle_timestamps = np.array([c.timestamp for c in self.candles])
        self._tick_prices = self._build_tick_prices()

        # FIX [5]: Validate crash events against data range
        data_start = self.oracle_history[0].timestamp if self.oracle_history else 0
        data_end = self.oracle_history[-1].timestamp if self.oracle_history else 0

        self.crash_events = []
        self._excluded_events = []
        for evt in sorted(crash_events, key=lambda e: e.start_time):
            if data_start <= evt.start_time <= data_end:
                self.crash_events.append(evt)
            else:
                self._excluded_events.append(evt)

        if self._excluded_events:
            import warnings
            warnings.warn(
                f"{len(self._excluded_events)} crash events outside data range "
                f"[{data_start:.0f}, {data_end:.0f}] — excluded from metrics"
            )

    def _build_tick_prices(self) -> List[float]:
        prices = []
        for tick in self.oracle_history:
            idx = int(np.searchsorted(self._candle_timestamps, tick.timestamp, side='right')) - 1
            idx = max(0, min(idx, len(self.candles) - 1))
            prices.append(self.candles[idx].close)
        return prices

    def _get_candle_window(self, end_time: float, num_candles: int) -> List[Candle5m]:
        idx = int(np.searchsorted(self._candle_timestamps, end_time, side='right'))
        start = max(0, idx - num_candles)
        return self.candles[start:idx]

    def run_baseline(self) -> BacktestMetrics:
        exposures = [tick.oracle_cap for tick in self.oracle_history]
        return self._compute_metrics(exposures, 'oracle_only', 'N/A', 'N/A')

    def run_adversary(self, adversary: AdversaryV0,
                      config_name: str = '',
                      collect_trace: bool = False) -> BacktestMetrics:
        exposures = []
        trace = BacktestTrace() if collect_trace else None

        adversary.reset_state()
        min_candles = adversary.vol_surprise_signal.total_candles_needed
        min_ticks = max(5, adversary.turbulence_signal.lookback_hours + 1)

        for i, tick in enumerate(self.oracle_history):
            history_slice = self.oracle_history[:i + 1]
            candle_window = self._get_candle_window(tick.timestamp, min_candles + 50)

            if len(candle_window) < min_candles or i < min_ticks:
                exposures.append(tick.oracle_cap)
                if trace:
                    self._append_trace(trace, tick, tick.oracle_cap, 1.0, 0.0, 0.0, 0.0, 'none')
                continue

            output = adversary.evaluate(history_slice, candle_window, tick.timestamp)
            adj_exposure = tick.oracle_cap * output.haircut
            exposures.append(adj_exposure)

            if trace:
                dominant = output.contribution.dominant_signal if output.contribution else 'none'
                self._append_trace(trace, tick, adj_exposure, output.haircut,
                                   output.contestation_score, output.turbulence,
                                   output.vol_surprise, dominant)

        name = config_name or f"adversary_{adversary.variant}_{adversary.weight_version}"
        metrics = self._compute_metrics(exposures, name, adversary.variant, adversary.weight_version)
        metrics.trace = trace
        return metrics

    def _append_trace(self, trace, tick, exposure, haircut, contestation, turb, vol, dominant):
        trace.timestamps.append(tick.timestamp)
        idx = int(np.searchsorted(self._candle_timestamps, tick.timestamp, side='right')) - 1
        idx = max(0, min(idx, len(self.candles) - 1))
        trace.prices.append(self.candles[idx].close)
        trace.oracle_caps.append(tick.oracle_cap)
        trace.exposures.append(exposure)
        trace.haircuts.append(haircut)
        trace.contestation_scores.append(contestation)
        trace.turbulence.append(turb)
        trace.vol_surprise.append(vol)
        trace.dominant_signal.append(dominant)

    def _compute_metrics(self, exposures: List[float],
                         config_name: str, variant: str,
                         weight_version: str) -> BacktestMetrics:

        timestamps = [t.timestamp for t in self.oracle_history]
        prices = self._tick_prices
        n = len(prices)

        # --- Returns and turnover ---
        capital = 1.0
        peak = 1.0
        max_dd = 0.0
        total_turnover = 0.0
        capital_trace = [1.0]

        for i in range(1, n):
            # FIX [14]: Transaction cost from exposure changes
            exposure_delta = abs(exposures[i] - exposures[i - 1])
            total_turnover += exposure_delta
            fee = exposure_delta * self.fee_rate

            if prices[i - 1] > 0:
                ret = (prices[i] - prices[i - 1]) / prices[i - 1]
                capital *= (1.0 + exposures[i - 1] * ret)
                capital -= fee * capital  # fee proportional to capital
                capital = max(capital, 1e-10)

            capital_trace.append(capital)
            peak = max(peak, capital)
            dd = (capital - peak) / peak
            max_dd = min(max_dd, dd)

        return_multiple_gross = capital  # will recompute without fees
        return_multiple_net = capital

        # Also compute gross (no fees) for comparison
        capital_gross = 1.0
        for i in range(1, n):
            if prices[i - 1] > 0:
                ret = (prices[i] - prices[i - 1]) / prices[i - 1]
                capital_gross *= (1.0 + exposures[i - 1] * ret)
                capital_gross = max(capital_gross, 1e-10)

        # --- Crash event metrics ---
        ts_array = np.array(timestamps)
        exp_array = np.array(exposures)
        cap_array = np.array([t.oracle_cap for t in self.oracle_history])

        event_exposures = []
        pre24h_means = []
        pre24h_mins = []
        timing_hits = 0

        for event in self.crash_events:
            idx = int(np.searchsorted(ts_array, event.start_time, side='right')) - 1
            idx = max(0, min(idx, n - 1))
            event_exposures.append(exposures[idx])

            # Pre-24h
            mask_24h = (ts_array >= event.start_time - 86400) & (ts_array < event.start_time)
            pre_24h = exp_array[mask_24h]
            if len(pre_24h) > 0:
                pre24h_means.append(float(np.mean(pre_24h)))
                pre24h_mins.append(float(np.min(pre_24h)))
            else:
                pre24h_means.append(exposures[idx])
                pre24h_mins.append(exposures[idx])

            # FIX [6]: Timing score — use relative haircut threshold
            # instead of fixed 0.95 * cap. Check if haircut < 0.95 (5% reduction).
            mask_2h = (ts_array >= event.start_time - 7200) & (ts_array < event.start_time)
            exp_2h = exp_array[mask_2h]
            cap_2h = cap_array[mask_2h]
            if len(exp_2h) > 0 and len(cap_2h) > 0:
                # Compute actual haircut ratios in the 2h window
                valid = cap_2h > 0
                if np.any(valid):
                    haircut_ratios = exp_2h[valid] / cap_2h[valid]
                    # Hit if mean haircut ratio < 0.95 (at least 5% average reduction)
                    if float(np.mean(haircut_ratios)) < 0.95:
                        timing_hits += 1

        mean_crash = float(np.mean(event_exposures)) if event_exposures else 0.0
        worst_event = float(max(event_exposures)) if event_exposures else 0.0

        # --- Occupancy ---
        active_mask = exp_array < (cap_array * 0.99)
        occupancy = float(np.sum(active_mask)) / max(1, n)

        valid_active = active_mask & (cap_array > 0)
        active_ratios = exp_array[valid_active] / cap_array[valid_active]
        mean_active = float(np.mean(active_ratios)) if len(active_ratios) > 0 else 1.0

        timing = timing_hits / max(1, len(self.crash_events))

        metrics = BacktestMetrics(
            config_name=config_name,
            variant=variant,
            weight_version=weight_version,
            mean_crash_exposure=mean_crash,
            mean_pre24h_exposure=float(np.mean(pre24h_means)) if pre24h_means else 0.0,
            min_pre24h_exposure=float(np.mean(pre24h_mins)) if pre24h_mins else 0.0,
            worst_event_exposure=worst_event,
            return_multiple=float(capital_gross),
            return_multiple_net=float(return_multiple_net),
            max_drawdown_proxy=float(max_dd),
            total_turnover=float(total_turnover),
            haircut_occupancy=occupancy,
            mean_haircut_when_active=mean_active,
            haircut_timing_score=timing,
            per_event_exposure=event_exposures,
            events_in_range=len(self.crash_events),
            events_excluded=len(self._excluded_events),
        )

        # Attach capital trace to trace if available
        if metrics.trace is not None:
            metrics.trace.capital = capital_trace

        return metrics


# ─────────────────────────────────────────────────────────────
# Ablation Framework
# ─────────────────────────────────────────────────────────────

class AblationRunner:

    def __init__(self, backtest_engine: BacktestEngine):
        self.engine = backtest_engine

    def run_full_ablation(self, variant: str = 'A',
                          weight_version: str = 'equal') -> Dict[str, BacktestMetrics]:
        results = {}

        full_adv = AdversaryV0(variant=variant, weight_version=weight_version,
                               enable_cooldown=False)
        full_adv.calibrate(self.engine.oracle_history)
        results['full'] = self.engine.run_adversary(full_adv, f'full_{variant}_{weight_version}')

        results['drop_turbulence'] = self._run_ablated(
            variant, weight_version, zero_turbulence=True, name='drop_turbulence')
        results['drop_vol'] = self._run_ablated(
            variant, weight_version, zero_vol=True, name='drop_vol')
        results['only_turbulence'] = self._run_ablated(
            variant, weight_version, zero_vol=True, zero_conflict=True, name='only_turbulence')
        results['only_vol'] = self._run_ablated(
            variant, weight_version, zero_turbulence=True, zero_conflict=True, name='only_vol')

        if variant == 'B':
            results['drop_conflict'] = self._run_ablated(
                variant, weight_version, zero_conflict=True, name='drop_conflict')
            results['only_conflict'] = self._run_ablated(
                variant, weight_version, zero_turbulence=True, zero_vol=True, name='only_conflict')

        return results

    def _run_ablated(self, variant, weight_version,
                     zero_turbulence=False, zero_conflict=False, zero_vol=False,
                     name='') -> BacktestMetrics:
        adv = AblatedAdversary(
            variant=variant, weight_version=weight_version,
            enable_cooldown=False,
            zero_turbulence=zero_turbulence,
            zero_conflict=zero_conflict,
            zero_vol=zero_vol,
        )
        adv.calibrate(self.engine.oracle_history)
        return self.engine.run_adversary(adv, name)


class AblatedAdversary(AdversaryV0):

    def __init__(self, zero_turbulence=False, zero_conflict=False, zero_vol=False, **kwargs):
        super().__init__(**kwargs)
        self._zero_turbulence = zero_turbulence
        self._zero_conflict = zero_conflict
        self._zero_vol = zero_vol

    def evaluate(self, oracle_history, candles, current_time=None):
        output = super().evaluate(oracle_history, candles, current_time)
        turb = 0.0 if self._zero_turbulence else output.turbulence
        conf = None if self._zero_conflict else output.conflict
        vol = 0.0 if self._zero_vol else output.vol_surprise
        score = self.contestation.score(turb, vol, conf)
        haircut, hstate = self.haircut_fn.compute(score)
        output.turbulence = turb
        output.conflict = conf
        output.vol_surprise = vol
        output.contestation_score = score
        output.haircut = haircut
        output.hysteresis_state = hstate
        output.contribution = self.contestation.contribution(turb, vol, conf)
        return output


# ─────────────────────────────────────────────────────────────
# Report Generator — ENHANCED
# ─────────────────────────────────────────────────────────────

def generate_report(baseline: BacktestMetrics,
                    configs: Dict[str, BacktestMetrics],
                    ablation_results: Optional[Dict[str, BacktestMetrics]] = None) -> str:
    lines = []
    lines.append("=" * 72)
    lines.append("ADVERSARY v0 — BACKTEST REPORT (ENHANCED)")
    lines.append("=" * 72)

    if baseline.events_excluded > 0:
        lines.append(f"\n  ⚠ {baseline.events_excluded} crash events excluded (outside data range)")
    lines.append(f"  Events evaluated: {baseline.events_in_range}")

    lines.append(f"\n{'─' * 72}")
    lines.append("BASELINE: Oracle Only")
    lines.append(f"{'─' * 72}")
    lines.append(_format_metrics(baseline))

    for name, m in configs.items():
        lines.append(f"\n{'─' * 72}")
        lines.append(f"CONFIG: {name}")
        lines.append(f"{'─' * 72}")
        lines.append(_format_metrics(m))

        comp = m.protection_vs_cost(baseline)
        lines.append("\n  Section 12 Acceptance:")
        cr = comp['crash_exposure_reduction']
        lines.append(f"    Crash reduction:    {cr:+.1%}  {'✓' if cr >= 0.15 else '✗'} (≥15%)")
        rc = comp['return_cost']
        label = "cost" if rc > 0 else "BENEFIT"
        lines.append(f"    Return impact (net): {rc:+.1%} ({label})  {'✓' if rc <= 0.08 else '✗'} (≤8% cost)")
        rcg = comp['return_cost_gross']
        lines.append(f"    Return impact (gross): {rcg:+.1%}")
        wi = comp['worst_event_improvement']
        lines.append(f"    Worst event Δ:      {wi:+.4f}  {'✓' if wi > 0 else '✗'}")
        lines.append(f"    Occupancy:          {m.haircut_occupancy:.1%}  {'✓' if m.haircut_occupancy < 0.35 else '✗'} (<35%)")
        lines.append(f"    Timing:             {m.haircut_timing_score:.1%}  {'✓' if m.haircut_timing_score > 0.5 else '✗'} (>50%)")
        lines.append(f"    Turnover:           {m.total_turnover:.1%}")
        lines.append(f"    *** {'PASSES' if comp['passes_acceptance'] else 'FAILS'} ***")

    if ablation_results:
        lines.append(f"\n{'═' * 72}")
        lines.append("SIGNAL ABLATION — Fake Mustache Diagnostic")
        lines.append(f"{'═' * 72}")

        full = ablation_results.get('full')
        if full:
            lines.append(f"\n  Reference (full, no cooldown):")
            lines.append(f"    Crash exposure: {full.mean_crash_exposure:.4f}  Return: {full.return_multiple:.4f}")

            for name, m in ablation_results.items():
                if name == 'full':
                    continue
                delta = 0.0
                if full.mean_crash_exposure > 0:
                    delta = (m.mean_crash_exposure - full.mean_crash_exposure) / full.mean_crash_exposure
                lines.append(f"\n  {name}:")
                lines.append(f"    Crash Δ vs full: {delta:+.1%}  Return: {m.return_multiple:.4f}  Occ: {m.haircut_occupancy:.1%}")

            lines.append(f"\n{'─' * 72}")
            lines.append("VERDICT:")
            only_vol = ablation_results.get('only_vol')
            if only_vol and full and baseline.mean_crash_exposure > 0:
                vol_prot = 1.0 - (only_vol.mean_crash_exposure / baseline.mean_crash_exposure)
                full_prot = 1.0 - (full.mean_crash_exposure / baseline.mean_crash_exposure)
                share = vol_prot / max(0.001, full_prot) if full_prot > 0 else 0.0
                lines.append(f"  Vol-surprise alone: {share:.0%} of full protection")
                if share > 0.85:
                    lines.append("  ⚠ FAKE MUSTACHE: Adversary ≈ vol filter + decoration")
                elif share > 0.65:
                    lines.append("  ⚡ Vol-dominant, other signals marginal")
                else:
                    lines.append("  ✓ Multi-signal contributions confirmed")

    lines.append(f"\n{'═' * 72}")
    return "\n".join(lines)


def _format_metrics(m: BacktestMetrics) -> str:
    return f"""  Variant:             {m.variant}
  Weights:             {m.weight_version}
  Return (gross):      {m.return_multiple:.4f}
  Return (net):        {m.return_multiple_net:.4f}
  Max drawdown:        {m.max_drawdown_proxy:.1%}
  Total turnover:      {m.total_turnover:.1%}
  Mean crash exp:      {m.mean_crash_exposure:.4f}
  Mean pre-24h exp:    {m.mean_pre24h_exposure:.4f}
  Min pre-24h exp:     {m.min_pre24h_exposure:.4f}
  Worst event exp:     {m.worst_event_exposure:.4f}
  Haircut occupancy:   {m.haircut_occupancy:.1%}
  Mean active haircut: {m.mean_haircut_when_active:.4f}
  Timing score:        {m.haircut_timing_score:.1%}"""
