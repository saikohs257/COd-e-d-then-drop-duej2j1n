"""
Structural Fragility Signal — Oracle Project
March 2026

Detects slow-building leverage crowding that makes the market easy to break
even before visible collapse begins.

This is a STRUCTURAL signal, not an acute one:
  - It builds over days, not hours
  - It provides background context to the hazard kernel
  - It should NOT trigger haircuts alone (by design)
  - It AMPLIFIES the effect of acute signals (turbulence, vol_surprise)
    when the market is already fragile

Design:
  Two inputs, both measuring leverage crowding:
    Open Interest (OI) — total outstanding derivative contracts
    Funding Rate        — cost of holding long positions in perpetuals

  Fragility = w_oi * normalized_oi + w_funding * normalized_funding_pressure

  Both are normalized relative to their own recent history, making the
  signal self-calibrating without requiring absolute reference values.

Normalization choices:
  OI:      Rolling percentile rank over oi_window, centered so that
           'at or below median' contributes zero. Only the top half
           of the OI distribution signals fragility.
           Formula: clip((percentile_rank - 0.5) * 2.0, 0, 1)

  Funding: Rolling mean over funding_window, then z-scored against
           a longer baseline. Only positive (long-crowding) z-scores
           contribute. Negative funding (short crowding) is a separate
           risk class and is excluded from this signal.
           Formula: clip(z_score / z_cap, 0, 1)

Integration:
  Feeds into AdversaryV1's hazard kernel through the fragility slot
  (replaces the flow_direction placeholder).

  At default weight w_fragility=0.10:
    - Fragility alone cannot breach the hazard dead zone (0.15)
    - Fragility + moderate turbulence crosses the dead zone
    - Fragility + acute vol spike produces meaningfully stronger haircuts

Data format:
  load_fragility_from_csv() accepts a CSV with columns:
    timestamp, open_interest                (OI only)
    timestamp, funding_rate                 (funding only)
    timestamp, open_interest, funding_rate  (merged, preferred)

  OI units: any consistent unit (USD notional, contract count, BTC).
            The percentile normalization handles scale automatically.
  Funding units: fractional rate per period (e.g. 0.0001 = 0.01% per 8h).
"""

import csv
import warnings
import numpy as np
from dataclasses import dataclass
from typing import List, Optional, Tuple


# ─────────────────────────────────────────────────────────────
# Data Structures
# ─────────────────────────────────────────────────────────────

@dataclass
class FragilityPoint:
    """Single observation of fragility inputs."""
    timestamp: float
    open_interest: Optional[float] = None   # Any consistent unit
    funding_rate: Optional[float] = None    # Fractional rate per period


# ─────────────────────────────────────────────────────────────
# Structural Fragility Signal
# ─────────────────────────────────────────────────────────────

class StructuralFragilitySignal:
    """
    Combines Open Interest and Funding Rate into a single fragility score ∈ [0, 1].

    Designed to be:
      - Slow: changes over hours to days, not minutes
      - Persistent: does not spike and immediately vanish
      - Interpretable: each component is independently inspectable
      - Self-normalizing: no absolute calibration required

    Usage (batch / backtest):
        signal = StructuralFragilitySignal()
        for i, point in enumerate(fragility_series):
            score = signal.compute(fragility_series[:i+1])
            # score ∈ [0, 1], 0 = no structural stress, 1 = maximum crowding

    Usage (single evaluation):
        score = signal.compute(fragility_series)
        # evaluates at the last point in the series
    """

    def __init__(
        self,
        oi_window: int = 72,
        funding_window: int = 72,
        funding_baseline_window: int = 168,
        funding_z_cap: float = 3.0,
        w_oi: float = 0.60,
        w_funding: float = 0.40,
    ):
        """
        Args:
            oi_window:               Lookback for OI percentile rank (hours/ticks).
                                     72 = 3 days at hourly cadence.
            funding_window:          Lookback for rolling mean funding (hours/ticks).
                                     72 = 3 days of 8h funding periods ≈ 9 settlement cycles.
            funding_baseline_window: Longer baseline for z-score reference (hours/ticks).
                                     168 = 7 days. Must be > funding_window.
            funding_z_cap:           Z-score above which funding_score = 1.0.
                                     3.0 means 3 standard deviations above baseline = max fragility.
            w_oi:                    Weight on OI component. Must sum with w_funding to 1.0.
            w_funding:               Weight on funding component.
        """
        assert funding_baseline_window > funding_window, (
            f"funding_baseline_window ({funding_baseline_window}) must exceed "
            f"funding_window ({funding_window})"
        )
        assert abs(w_oi + w_funding - 1.0) < 1e-9, (
            f"w_oi + w_funding must equal 1.0, got {w_oi + w_funding}"
        )
        assert funding_z_cap > 0

        self.oi_window = oi_window
        self.funding_window = funding_window
        self.funding_baseline_window = funding_baseline_window
        self.funding_z_cap = funding_z_cap
        self.w_oi = w_oi
        self.w_funding = w_funding

    def compute(self, series: List[FragilityPoint]) -> float:
        """
        Compute fragility score at the latest point in the series.

        Args:
            series: List[FragilityPoint] sorted ascending by timestamp.
                    Needs at least oi_window points for a meaningful score.
                    Returns 0.0 with insufficient data (not 1.0 — absence
                    of data is not evidence of fragility).

        Returns:
            fragility_score ∈ [0, 1]
        """
        if not series:
            return 0.0

        oi_score = self._compute_oi_score(series)
        funding_score = self._compute_funding_score(series)

        fragility = self.w_oi * oi_score + self.w_funding * funding_score
        return float(np.clip(fragility, 0.0, 1.0))

    def compute_components(self, series: List[FragilityPoint]) -> Tuple[float, float, float]:
        """
        Returns (oi_score, funding_score, fragility_score) for diagnostics.
        Useful for forensics reporting.
        """
        oi_score = self._compute_oi_score(series)
        funding_score = self._compute_funding_score(series)
        fragility = float(np.clip(self.w_oi * oi_score + self.w_funding * funding_score, 0.0, 1.0))
        return oi_score, funding_score, fragility

    # ── OI normalization ──────────────────────────────────────

    def _compute_oi_score(self, series: List[FragilityPoint]) -> float:
        """
        Rolling percentile rank of current OI within oi_window, centered.

        Percentile rank tells us: relative to the last oi_window observations,
        how high is OI right now?

        Centering: only the top half of the distribution signals fragility.
        A market at its median OI is neutral. Only above-median OI builds score.

        Formula: clip((percentile_rank - 0.5) * 2.0, 0.0, 1.0)
          percentile = 0.5 (median)  → oi_score = 0.0
          percentile = 0.75          → oi_score = 0.5
          percentile = 1.0 (maximum) → oi_score = 1.0
        """
        oi_values = [p.open_interest for p in series if p.open_interest is not None]

        if len(oi_values) < max(3, self.oi_window // 4):
            return 0.0  # Not enough data — conservative, not alarmist

        window = oi_values[-self.oi_window:]
        current = window[-1]

        percentile_rank = float(np.sum(np.array(window) <= current)) / len(window)
        oi_score = float(np.clip((percentile_rank - 0.5) * 2.0, 0.0, 1.0))
        return oi_score

    # ── Funding normalization ─────────────────────────────────

    def _compute_funding_score(self, series: List[FragilityPoint]) -> float:
        """
        Rolling mean funding z-scored against a longer baseline.

        Why rolling mean, not raw funding?
        A single elevated funding period could be noise.
        Persistently elevated funding over many periods signals real crowding.

        Why z-score against baseline?
        Absolute funding levels vary by market regime and exchange.
        Z-scoring makes the signal self-calibrating.

        Why only positive z-scores?
        Positive funding = longs pay shorts = longs are crowded = long unwind risk.
        Negative funding = shorts crowded = different risk profile, not captured here.
        """
        fund_values = [p.funding_rate for p in series if p.funding_rate is not None]

        if len(fund_values) < max(3, self.funding_window // 4):
            return 0.0

        # Rolling mean over funding_window
        fund_window = fund_values[-self.funding_window:]
        fund_mean = float(np.mean(fund_window))

        # Baseline: the period before the funding_window
        # If not enough history for a separate baseline, use the window itself
        if len(fund_values) >= self.funding_baseline_window:
            baseline = fund_values[-self.funding_baseline_window:-self.funding_window]
        else:
            baseline = fund_window  # fallback: z-score against self (conservative)

        if len(baseline) < 3:
            baseline = fund_window

        base_mean = float(np.mean(baseline))
        base_std = float(np.std(baseline))

        if base_std < 1e-10:
            # Baseline has zero variance — funding has been perfectly stable.
            # Any deviation from that stable level is significant.
            # Use a small absolute threshold instead.
            base_std = max(abs(base_mean) * 0.1, 1e-7)

        z = (fund_mean - base_mean) / base_std

        # Only positive z matters; cap at funding_z_cap (default 3σ = max score)
        funding_score = float(np.clip(z / self.funding_z_cap, 0.0, 1.0))
        return funding_score


# ─────────────────────────────────────────────────────────────
# Synthetic Fragility Generator (for backtest testing)
# ─────────────────────────────────────────────────────────────

def generate_synthetic_fragility(
    candle_timestamps: List[float],
    crash_events: list,
    pre_crash_buildup_hours: int = 48,
    seed: int = 42,
) -> List[FragilityPoint]:
    """
    Generate synthetic OI and funding series that build up before crashes.

    Used when real OI/funding data is not available, to test whether
    the structural fragility signal adds value in a controlled setting.

    Design:
      - Baseline OI: slow random walk around 1.0
      - Pre-crash: OI increases 30-60% above baseline in the buildup window
      - Baseline funding: noise around 0.0001 (0.01%/period)
      - Pre-crash: funding rises to 0.0006-0.0010 in the buildup window

    Args:
        candle_timestamps: From candles, used to generate hourly OI/funding series
        crash_events:      List of Crash72Event (or objects with .start_time)
        pre_crash_buildup_hours: How many hours before crash to inject fragility
        seed:              Random seed for reproducibility

    Returns:
        List[FragilityPoint] at hourly cadence
    """
    rng = np.random.RandomState(seed)

    if not candle_timestamps:
        return []

    start_ts = candle_timestamps[0]
    end_ts = candle_timestamps[-1]

    # Generate hourly timestamps
    n_hours = int((end_ts - start_ts) / 3600) + 1
    hourly_ts = [start_ts + h * 3600 for h in range(n_hours)]

    # Identify pre-crash hours
    crash_start_times = [e.start_time for e in crash_events]
    pre_crash_set = set()
    for cs in crash_start_times:
        for h in range(pre_crash_buildup_hours):
            target = cs - h * 3600
            nearest_hour = round((target - start_ts) / 3600)
            pre_crash_set.add(nearest_hour)

    # Generate OI series: slow random walk, spikes before crashes
    oi_base = 1.0
    oi_values = []
    for h in range(n_hours):
        noise = rng.randn() * 0.005
        if h in pre_crash_set:
            # Gradual buildup: how close to the crash?
            intensity = 0.3 + rng.uniform(0, 0.3)
            oi_base = oi_base + intensity * 0.015  # gradual rise
        else:
            oi_base = max(0.5, oi_base * 0.995 + 0.005)  # mean reversion
        oi_values.append(max(0.1, oi_base + noise))

    # Generate funding series: noise baseline, elevated before crashes
    funding_baseline = 0.0001
    funding_values = []
    for h in range(n_hours):
        noise = rng.randn() * 0.00005
        if h in pre_crash_set:
            # Elevated funding during buildup
            elevated = funding_baseline + rng.uniform(0.0003, 0.0008)
            funding_values.append(elevated + noise)
        else:
            # Normal: small positive or occasionally negative
            funding_values.append(funding_baseline + noise)

    points = []
    for h in range(n_hours):
        points.append(FragilityPoint(
            timestamp=hourly_ts[h],
            open_interest=oi_values[h],
            funding_rate=funding_values[h],
        ))

    return points


# ─────────────────────────────────────────────────────────────
# CSV Loaders
# ─────────────────────────────────────────────────────────────

def load_fragility_from_csv(filepath: str) -> List[FragilityPoint]:
    """
    Load OI and/or funding rate data from CSV.

    Accepted column layouts:
      timestamp, open_interest
      timestamp, funding_rate
      timestamp, open_interest, funding_rate   ← preferred

    Timestamps: Unix epoch seconds.
    OI units:   any consistent unit (percentile normalization is scale-free).
    Funding:    fractional rate per period (0.0001 = 0.01% per 8h).

    Returns List[FragilityPoint] sorted ascending by timestamp.
    Missing columns produce None values (signal degrades gracefully).
    """
    points = []

    with open(filepath, 'r') as f:
        reader = csv.DictReader(f)
        headers = set(reader.fieldnames or [])

        has_oi = 'open_interest' in headers or 'oi' in headers
        has_funding = 'funding_rate' in headers or 'funding' in headers

        if not has_oi and not has_funding:
            warnings.warn(
                f"[load_fragility_from_csv] No recognized columns in {filepath}. "
                f"Expected 'open_interest' and/or 'funding_rate'. "
                f"Found: {sorted(headers)}"
            )
            return []

        if not has_oi:
            warnings.warn("[load_fragility_from_csv] 'open_interest' column missing — OI score will be 0.0")
        if not has_funding:
            warnings.warn("[load_fragility_from_csv] 'funding_rate' column missing — funding score will be 0.0")

        for row in reader:
            ts = float(row.get('timestamp', row.get('time', 0)))

            oi = None
            if has_oi:
                raw = row.get('open_interest') or row.get('oi', '')
                if raw and raw.strip():
                    try:
                        oi = float(raw)
                    except ValueError:
                        pass

            funding = None
            if has_funding:
                raw = row.get('funding_rate') or row.get('funding', '')
                if raw and raw.strip():
                    try:
                        funding = float(raw)
                    except ValueError:
                        pass

            points.append(FragilityPoint(timestamp=ts, open_interest=oi, funding_rate=funding))

    points.sort(key=lambda p: p.timestamp)
    return points


def load_fragility_from_separate_csvs(
    oi_filepath: str,
    funding_filepath: str,
    max_merge_gap_seconds: float = 7200.0,
) -> List[FragilityPoint]:
    """
    Merge OI and funding from separate CSV files.

    Each file needs: timestamp, value
    OI file:      timestamp, open_interest
    Funding file: timestamp, funding_rate

    Merges by nearest timestamp within max_merge_gap_seconds.
    Missing matches produce None for that field.

    Returns List[FragilityPoint] sorted ascending.
    """
    oi_points = load_fragility_from_csv(oi_filepath)
    fund_points = load_fragility_from_csv(funding_filepath)

    if not oi_points and not fund_points:
        return []

    if not oi_points:
        return fund_points
    if not fund_points:
        return oi_points

    # Build lookup: fund timestamp → funding_rate
    fund_ts = np.array([p.timestamp for p in fund_points])
    fund_vals = [p.funding_rate for p in fund_points]

    merged = []
    for oi_pt in oi_points:
        idx = int(np.searchsorted(fund_ts, oi_pt.timestamp, side='nearest'))
        idx = max(0, min(idx, len(fund_points) - 1))

        if abs(fund_ts[idx] - oi_pt.timestamp) <= max_merge_gap_seconds:
            funding = fund_vals[idx]
        else:
            funding = None

        merged.append(FragilityPoint(
            timestamp=oi_pt.timestamp,
            open_interest=oi_pt.open_interest,
            funding_rate=funding,
        ))

    return sorted(merged, key=lambda p: p.timestamp)


def align_fragility_to_oracle(
    fragility_series: List[FragilityPoint],
    oracle_timestamps: List[float],
    max_gap_seconds: float = 7200.0,
) -> List[float]:
    """
    Align fragility scores to Oracle tick timestamps.

    For each Oracle tick, finds the most recent fragility point at or before
    that tick (forward-fill). Returns 0.0 if no point is within max_gap_seconds.

    Args:
        fragility_series: Pre-computed fragility scores — should be computed
                          incrementally first (see StructuralFragilitySignal.compute).
                          Pass the raw series; this function aligns timestamps only.
        oracle_timestamps: List of Oracle tick timestamps (Unix seconds).
        max_gap_seconds:  Max allowed staleness for a fragility reading.

    Returns:
        List[float] of fragility scores aligned to oracle_timestamps, same length.

    Note: This function aligns already-computed scores. To compute scores
    incrementally (as required for correct backtest behavior), use
    compute_fragility_series() below.
    """
    if not fragility_series or not oracle_timestamps:
        return [0.0] * len(oracle_timestamps)

    frag_ts = np.array([p.timestamp for p in fragility_series])
    aligned = []

    for ots in oracle_timestamps:
        # Find most recent fragility point at or before this Oracle tick
        idx = int(np.searchsorted(frag_ts, ots, side='right')) - 1
        if idx < 0:
            aligned.append(0.0)
            continue
        if abs(frag_ts[idx] - ots) > max_gap_seconds:
            aligned.append(0.0)
            continue
        # fragility_series[idx] holds the raw point; caller must pre-compute scores
        # For alignment use only — actual scores come from compute_fragility_series
        aligned.append(float(getattr(fragility_series[idx], '_score', 0.0)))

    return aligned


def compute_fragility_series(
    fragility_points: List[FragilityPoint],
    signal: Optional['StructuralFragilitySignal'] = None,
) -> List[Tuple[float, float]]:
    """
    Compute fragility scores incrementally over a series of points.

    This is the correct way to compute fragility for a backtest:
    each score is computed using only the history available at that tick.

    Args:
        fragility_points: Full series, sorted ascending.
        signal:           StructuralFragilitySignal instance (default params if None).

    Returns:
        List of (timestamp, fragility_score) tuples.
    """
    if signal is None:
        signal = StructuralFragilitySignal()

    results = []
    for i in range(len(fragility_points)):
        score = signal.compute(fragility_points[:i + 1])
        results.append((fragility_points[i].timestamp, score))

    return results
