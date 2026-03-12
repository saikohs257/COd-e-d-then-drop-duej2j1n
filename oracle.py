"""
Oracle v0 — BTC Survival-First Risk Oracle
Oracle Project | March 2026

Produces OracleTick sequences consumed by the Adversary.

Architecture:
  The Oracle answers one question: "How much of our capital should be at risk?"
  It outputs two values per tick:
    posterior   — risk index ∈ [0, 1]  (1.0 = maximum danger)
    oracle_cap  — exposure ceiling ∈ [0.1, 1.0] derived via PosteriorGov mapping

  Variant A: single posterior from structural + context blend (no L1/L2 separation)
  Variant B: exposes l1_structural and l2_context separately (enables Adversary Variant B)

Layer architecture:
  L1 — Structural state: slow-moving, regime-level features (on-chain, macro trend)
  L2 — Context layer:    fast-moving, market microstructure signals (vol, momentum)

  Final posterior = blend(L1, L2) via PosteriorGov mapping

Integration with Adversary:
  oracle = OracleV0()
  ticks = oracle.evaluate(features)  → List[OracleTick]
  # Feed ticks to BacktestEngine or live Adversary

SWAP-POINTS (clearly marked with # SWAP-POINT):
  1. _compute_l1()      — replace stub with your real L1 model
  2. _compute_l2()      — replace stub with your real L2 model
  3. _posterior_gov()   — replace linear formula with PosteriorGov_piecewise
  4. load_from_csv()    — swap the cap formula when adding oracle_cap column to CSV

Design invariants:
  - posterior is always ∈ [0, 1]  (hard-clipped, never NaN)
  - oracle_cap is always ∈ [0.1, 1.0]  (floor prevents Oracle from vetoing entirely)
  - No signal can INCREASE cap above 1.0
  - All inputs normalized before blending — L1 and L2 live in [0, 1]
"""

import time
import warnings
import numpy as np
from dataclasses import dataclass, field
from typing import List, Optional, Tuple, Dict

from signals import OracleTick, Candle5m


# ─────────────────────────────────────────────────────────────
# Feature Bundle
# ─────────────────────────────────────────────────────────────

@dataclass
class OracleFeatures:
    """
    All inputs to a single Oracle evaluation tick.

    Callers populate what they have. Oracle degrades gracefully
    when optional fields are absent (stubs return 0.5 uncertainty).

    timestamp:      Unix epoch seconds
    price:          BTC spot/perp price
    candles:        Recent 5-min OHLCV candles (for vol/momentum)

    --- L1 Structural (slow, regime-level) ---
    onchain_risk:   On-chain composite ∈ [0,1] (e.g. SOPR, MVRV, exchange inflows)
    macro_trend:    Macro regime score ∈ [0,1] (e.g. trend-following index)

    --- L2 Context (fast, microstructure) ---
    realized_vol:   Recent realized volatility (annualized, raw — Oracle normalizes)
    price_momentum: Price return over lookback ∈ [-1, 1] (negative = falling)
    funding_rate:   Perpetual funding rate (raw — normalized internally)
    liquidation_vol: Liquidation volume proxy ∈ [0, 1] (already normalized)
    """
    timestamp: float
    price: float = 0.0
    candles: List[Candle5m] = field(default_factory=list)

    # L1 structural (optional — stub returns 0.5 if absent)
    onchain_risk: Optional[float] = None
    macro_trend: Optional[float] = None

    # L2 context (optional — stub returns 0.5 if absent)
    realized_vol: Optional[float] = None
    price_momentum: Optional[float] = None
    funding_rate: Optional[float] = None
    liquidation_vol: Optional[float] = None


# ─────────────────────────────────────────────────────────────
# PosteriorGov Mapping
# ─────────────────────────────────────────────────────────────

class PosteriorGov:
    """
    Maps posterior ∈ [0, 1] → oracle_cap ∈ [0.1, 1.0].

    Currently: piecewise linear with three regimes:
      Safe    (posterior < low_threshold):   cap stays near 1.0
      Caution (low_threshold to high_threshold): linear decay
      Danger  (posterior > high_threshold):  steep decay to floor

    SWAP-POINT: Replace _piecewise() with your calibrated mapping once
    you have empirical data on how posterior levels historically correspond
    to loss events. The PosteriorGov_piecewise from the spec should go here.

    Design constraint: cap floor = 0.1 (Oracle never fully exits — that's
    a separate kill-switch mechanism outside this module).
    """

    def __init__(self,
                 low_threshold: float = 0.30,
                 high_threshold: float = 0.70,
                 cap_at_low: float = 0.90,
                 cap_at_high: float = 0.40,
                 floor: float = 0.10):
        """
        Args:
            low_threshold:  posterior below this → near-full exposure
            high_threshold: posterior above this → steep reduction
            cap_at_low:     oracle_cap when posterior = low_threshold
            cap_at_high:    oracle_cap when posterior = high_threshold
            floor:          minimum oracle_cap (hard floor)
        """
        assert 0 < low_threshold < high_threshold < 1.0
        assert cap_at_high < cap_at_low <= 1.0
        assert 0 < floor < cap_at_high

        self.low_threshold = low_threshold
        self.high_threshold = high_threshold
        self.cap_at_low = cap_at_low
        self.cap_at_high = cap_at_high
        self.floor = floor

    def compute(self, posterior: float) -> float:
        """
        Map posterior to oracle_cap.

        SWAP-POINT: Replace this function body with PosteriorGov_piecewise
        once calibrated from crash72 backtest results.
        """
        return self._piecewise(posterior)

    def _piecewise(self, posterior: float) -> float:
        """
        Three-zone piecewise linear mapping.

        Zone 1 (posterior < low): full exposure, slight decay begins
        Zone 2 (low ≤ posterior < high): linear decay from cap_at_low to cap_at_high
        Zone 3 (posterior ≥ high): steep decay from cap_at_high to floor
        """
        if posterior < self.low_threshold:
            # Slight decay from 1.0 to cap_at_low as posterior rises to low_threshold
            progress = posterior / self.low_threshold
            return 1.0 - (1.0 - self.cap_at_low) * progress

        elif posterior < self.high_threshold:
            # Linear decay from cap_at_low to cap_at_high
            progress = (posterior - self.low_threshold) / (self.high_threshold - self.low_threshold)
            return self.cap_at_low - (self.cap_at_low - self.cap_at_high) * progress

        else:
            # Steep decay from cap_at_high to floor
            progress = min(1.0, (posterior - self.high_threshold) / (1.0 - self.high_threshold))
            return self.cap_at_high - (self.cap_at_high - self.floor) * progress


# ─────────────────────────────────────────────────────────────
# L1: Structural Layer
# ─────────────────────────────────────────────────────────────

class L1StructuralModel:
    """
    Structural risk layer — slow-moving regime signals.

    Combines on-chain risk and macro trend into a single L1 score ∈ [0, 1].

    Current implementation: weighted blend of available inputs.
    Missing inputs fall back to a neutral 0.5.

    SWAP-POINT: Replace _compute_from_onchain() and _compute_from_macro()
    with your real model outputs (e.g. SOPR-based on-chain risk, macro HMM state).
    The stub currently returns the inputs directly (assuming they're already
    normalized to [0, 1]).
    """

    def __init__(self,
                 onchain_weight: float = 0.60,
                 macro_weight: float = 0.40,
                 smoothing_alpha: float = 0.15):
        """
        Args:
            onchain_weight: weight on on-chain risk signal
            macro_weight:   weight on macro trend signal
            smoothing_alpha: EMA smoothing factor (lower = slower response)
        """
        assert abs(onchain_weight + macro_weight - 1.0) < 1e-9, \
            "L1 weights must sum to 1.0"
        self.onchain_weight = onchain_weight
        self.macro_weight = macro_weight
        self.smoothing_alpha = smoothing_alpha
        self._state: float = 0.3  # Internal EMA state

    def compute(self, onchain_risk: Optional[float],
                macro_trend: Optional[float]) -> float:
        """
        Returns L1 structural score ∈ [0, 1].

        Args:
            onchain_risk: on-chain risk composite ∈ [0, 1] (or None)
            macro_trend:  macro regime ∈ [0, 1] (or None)
        """
        # Handle missing inputs with neutral fallback
        oc = self._validate(onchain_risk, default=0.5, name="onchain_risk")
        mt = self._validate(macro_trend, default=0.5, name="macro_trend")

        # SWAP-POINT: Replace direct passthrough with real model transforms
        raw_l1 = self.onchain_weight * oc + self.macro_weight * mt

        # Exponential smoothing for temporal stability
        self._state = self._state * (1 - self.smoothing_alpha) + raw_l1 * self.smoothing_alpha

        return float(np.clip(self._state, 0.0, 1.0))

    def reset(self, initial_state: float = 0.3):
        """Reset internal state (call before backtest)."""
        self._state = initial_state

    @staticmethod
    def _validate(value: Optional[float], default: float, name: str) -> float:
        if value is None:
            return default
        if np.isnan(value) or np.isinf(value):
            warnings.warn(f"L1: {name} is NaN/Inf, using default {default}")
            return default
        return float(np.clip(value, 0.0, 1.0))


# ─────────────────────────────────────────────────────────────
# L2: Context Layer
# ─────────────────────────────────────────────────────────────

class L2ContextModel:
    """
    Context layer — fast-moving microstructure signals.

    Combines vol, momentum, funding rate, and liquidation volume
    into a single L2 score ∈ [0, 1].

    L2 is allowed to react faster than L1 because it captures acute
    stress. The Adversary's vol_surprise signal overlaps with L2 intentionally —
    they operate at different time scales (Adversary is 2h window;
    L2 is a 4-24h composite).

    SWAP-POINT: Replace _normalize_vol(), _normalize_momentum(), etc.
    with your real normalization tables once calibrated from historical data.
    Current normalization is based on typical BTC parameter ranges.
    """

    # Typical BTC normalization bounds (annualized vol)
    # Calibrated from 2020-2025 BTC realized vol distribution
    VOL_LOW = 0.30    # ~30% annualized = calm
    VOL_HIGH = 1.80   # ~180% annualized = extreme stress (March 2020 peak)

    FUNDING_NEUTRAL = 0.0001   # ~0.01% per 8h = neutral
    FUNDING_EXTREME = 0.003    # ~0.3% per 8h = extreme long crowding

    def __init__(self,
                 vol_weight: float = 0.40,
                 momentum_weight: float = 0.25,
                 funding_weight: float = 0.20,
                 liquidation_weight: float = 0.15,
                 smoothing_alpha: float = 0.35):
        """
        Args:
            *_weight:       signal weights (must sum to 1.0)
            smoothing_alpha: EMA smoothing (higher = faster response than L1)
        """
        total = vol_weight + momentum_weight + funding_weight + liquidation_weight
        assert abs(total - 1.0) < 1e-9, f"L2 weights must sum to 1.0, got {total}"
        self.vol_weight = vol_weight
        self.momentum_weight = momentum_weight
        self.funding_weight = funding_weight
        self.liquidation_weight = liquidation_weight
        self.smoothing_alpha = smoothing_alpha
        self._state: float = 0.3

    def compute(self,
                realized_vol: Optional[float] = None,
                price_momentum: Optional[float] = None,
                funding_rate: Optional[float] = None,
                liquidation_vol: Optional[float] = None,
                candles: Optional[List[Candle5m]] = None) -> float:
        """
        Returns L2 context score ∈ [0, 1].

        If candles are provided and realized_vol/price_momentum are absent,
        computes them from candles directly.
        """
        # Derive from candles if not provided directly
        if candles and len(candles) >= 24:
            if realized_vol is None:
                realized_vol = self._vol_from_candles(candles)
            if price_momentum is None:
                price_momentum = self._momentum_from_candles(candles)

        # Normalize each signal to [0, 1] where 1 = maximum risk
        vol_score = self._normalize_vol(realized_vol)
        mom_score = self._normalize_momentum(price_momentum)
        fund_score = self._normalize_funding(funding_rate)
        liq_score = self._validate_normalized(liquidation_vol, default=0.3)

        raw_l2 = (self.vol_weight * vol_score +
                  self.momentum_weight * mom_score +
                  self.funding_weight * fund_score +
                  self.liquidation_weight * liq_score)

        # Exponential smoothing — faster than L1
        self._state = self._state * (1 - self.smoothing_alpha) + raw_l2 * self.smoothing_alpha

        return float(np.clip(self._state, 0.0, 1.0))

    def reset(self, initial_state: float = 0.3):
        self._state = initial_state

    # ── Normalization helpers ──────────────────────────────────

    def _normalize_vol(self, vol: Optional[float]) -> float:
        """
        Map annualized realized vol to [0, 1] risk score.
        SWAP-POINT: Recalibrate VOL_LOW and VOL_HIGH from your dataset.
        """
        if vol is None or np.isnan(vol):
            return 0.4  # Slightly elevated uncertainty when missing
        v = float(np.clip(vol, 0, None))
        if v <= self.VOL_LOW:
            return 0.0
        elif v >= self.VOL_HIGH:
            return 1.0
        else:
            return (v - self.VOL_LOW) / (self.VOL_HIGH - self.VOL_LOW)

    def _normalize_momentum(self, momentum: Optional[float]) -> float:
        """
        Map price momentum ∈ [-1, 1] to risk score ∈ [0, 1].
        Negative momentum (price falling) increases risk score.
        Positive momentum reduces risk score.

        Convention: risk ↑ when price falling, risk ↓ when rising.
        """
        if momentum is None or np.isnan(momentum):
            return 0.4
        # Invert: falling price = high risk
        m = float(np.clip(momentum, -1.0, 1.0))
        return float(np.clip(0.5 - m * 0.5, 0.0, 1.0))

    def _normalize_funding(self, funding_rate: Optional[float]) -> float:
        """
        Map funding rate to risk score.
        High positive funding = over-leveraged longs = crash risk.
        High negative funding = over-leveraged shorts = squeeze risk (moderate).

        SWAP-POINT: Calibrate FUNDING_NEUTRAL and FUNDING_EXTREME from
        your instrument's historical funding distribution.
        """
        if funding_rate is None or np.isnan(funding_rate):
            return 0.3
        f = float(funding_rate)
        if abs(f) <= self.FUNDING_NEUTRAL:
            return 0.0
        elif f > 0:
            # Long crowding: risk increases with positive funding
            return float(np.clip((f - self.FUNDING_NEUTRAL) / (self.FUNDING_EXTREME - self.FUNDING_NEUTRAL), 0.0, 1.0))
        else:
            # Short crowding: moderate risk (squeeze less severe than liquidation cascade)
            return float(np.clip(abs(f) / (self.FUNDING_EXTREME * 2), 0.0, 0.6))

    @staticmethod
    def _validate_normalized(value: Optional[float], default: float) -> float:
        if value is None or np.isnan(value):
            return default
        return float(np.clip(value, 0.0, 1.0))

    # ── Derivation from candles ────────────────────────────────

    @staticmethod
    def _vol_from_candles(candles: List[Candle5m],
                          window_hours: int = 4) -> float:
        """
        Compute annualized realized vol from recent candles.
        Uses Parkinson high-low estimator (more efficient than close-to-close).
        """
        n_candles = window_hours * 12  # 5-min candles per hour
        recent = candles[-min(n_candles, len(candles)):]

        if len(recent) < 4:
            return 0.7  # Conservative default

        log_hl_sq = []
        for c in recent:
            if c.high > 0 and c.low > 0 and c.low < c.high:
                log_hl_sq.append((np.log(c.high / c.low)) ** 2)

        if not log_hl_sq:
            return 0.7

        # Parkinson estimator: annualize from 5-min to annual
        candle_vol = np.sqrt(np.mean(log_hl_sq) / (4 * np.log(2)))
        annual_vol = candle_vol * np.sqrt(365.25 * 24 * 12)
        return float(annual_vol)

    @staticmethod
    def _momentum_from_candles(candles: List[Candle5m],
                                lookback_hours: int = 6) -> float:
        """
        Compute price momentum as fractional return over lookback.
        Returns value in [-1, 1] (clipped).
        """
        n_candles = lookback_hours * 12
        if len(candles) < 2:
            return 0.0

        recent = candles[-min(n_candles, len(candles)):]
        start_price = recent[0].close
        end_price = recent[-1].close

        if start_price <= 0:
            return 0.0

        raw_return = (end_price - start_price) / start_price
        return float(np.clip(raw_return, -1.0, 1.0))


# ─────────────────────────────────────────────────────────────
# Oracle V0 — Main Evaluator
# ─────────────────────────────────────────────────────────────

class OracleV0:
    """
    Full Oracle evaluation pipeline.

    Usage (live):
        oracle = OracleV0(variant='B')
        tick = oracle.evaluate(features)
        # tick.oracle_cap → exposure ceiling for this tick
        # tick.posterior  → risk index [0, 1]

    Usage (batch / backtest):
        oracle = OracleV0()
        oracle.reset()
        ticks = [oracle.evaluate(f) for f in feature_sequence]
        # Pass ticks to BacktestEngine

    Variant A: posterior only (l1_structural, l2_context not stored in output)
    Variant B: posterior + l1_structural + l2_context (enables Adversary Variant B)
    """

    # Blend weights: how L1 and L2 combine into the final posterior
    # L1 is slow/structural, L2 is fast/contextual
    # Higher L1 weight = more stable, slower-reacting Oracle
    # Higher L2 weight = more reactive, more false positives possible
    L1_WEIGHT_DEFAULT = 0.55
    L2_WEIGHT_DEFAULT = 0.45

    def __init__(self,
                 variant: str = 'A',
                 l1_weight: float = L1_WEIGHT_DEFAULT,
                 l2_weight: float = L2_WEIGHT_DEFAULT,
                 posterior_gov: Optional[PosteriorGov] = None):
        """
        Args:
            variant:        'A' (posterior only) or 'B' (expose L1/L2 separately)
            l1_weight:      blend weight for L1 structural layer
            l2_weight:      blend weight for L2 context layer
            posterior_gov:  custom PosteriorGov mapping (default: PosteriorGov())
        """
        assert variant in ('A', 'B'), f"Unknown variant: {variant}"
        assert abs(l1_weight + l2_weight - 1.0) < 1e-9, \
            f"L1+L2 weights must sum to 1.0, got {l1_weight + l2_weight}"

        self.variant = variant
        self.l1_weight = l1_weight
        self.l2_weight = l2_weight
        self.posterior_gov = posterior_gov or PosteriorGov()

        self.l1_model = L1StructuralModel()
        self.l2_model = L2ContextModel()

    def evaluate(self, features: OracleFeatures) -> OracleTick:
        """
        Run full Oracle evaluation on a single feature bundle.

        Args:
            features: OracleFeatures populated with all available signals

        Returns:
            OracleTick with posterior, oracle_cap, and optionally l1/l2
        """
        # Compute layer scores
        l1 = self.l1_model.compute(
            onchain_risk=features.onchain_risk,
            macro_trend=features.macro_trend,
        )

        l2 = self.l2_model.compute(
            realized_vol=features.realized_vol,
            price_momentum=features.price_momentum,
            funding_rate=features.funding_rate,
            liquidation_vol=features.liquidation_vol,
            candles=features.candles if features.candles else None,
        )

        # Blend into posterior
        posterior = float(np.clip(
            self.l1_weight * l1 + self.l2_weight * l2,
            0.0, 1.0
        ))

        # Map posterior → oracle_cap via PosteriorGov
        oracle_cap = self.posterior_gov.compute(posterior)

        return OracleTick(
            timestamp=features.timestamp,
            posterior=posterior,
            oracle_cap=oracle_cap,
            l1_structural=l1 if self.variant == 'B' else None,
            l2_context=l2 if self.variant == 'B' else None,
        )

    def evaluate_sequence(self,
                          feature_sequence: List[OracleFeatures]) -> List[OracleTick]:
        """
        Evaluate a time-ordered sequence of features.
        Internal EMA state carries forward — call reset() before reuse.
        """
        return [self.evaluate(f) for f in feature_sequence]

    def reset(self):
        """Reset all internal EMA state. Call before each backtest run."""
        self.l1_model.reset()
        self.l2_model.reset()


# ─────────────────────────────────────────────────────────────
# CSV Loader — with oracle_cap support
# ─────────────────────────────────────────────────────────────

def load_oracle_from_csv(filepath: str,
                         posterior_gov: Optional[PosteriorGov] = None) -> List[OracleTick]:
    """
    Load Oracle history from CSV into OracleTick list.

    Expected CSV columns:
        timestamp   (required)
        posterior   (required)

    Optional columns (auto-detected):
        oracle_cap         — if present, used directly
        l1 or l1_structural
        l2 or l2_context

    If oracle_cap is absent, it is derived from posterior via PosteriorGov.

    SWAP-POINT: Once your CSV includes an oracle_cap column computed by
    your calibrated PosteriorGov_piecewise, the placeholder formula below
    is bypassed automatically. No code change needed — just add the column.
    """
    import csv

    gov = posterior_gov or PosteriorGov()
    ticks = []

    with open(filepath, 'r') as f:
        reader = csv.DictReader(f)
        headers = reader.fieldnames or []

        has_cap = 'oracle_cap' in headers
        has_l1 = 'l1_structural' in headers or 'l1' in headers
        has_l2 = 'l2_context' in headers or 'l2' in headers

        if not has_cap:
            warnings.warn(
                "oracle_cap column not found in CSV. "
                "Using PosteriorGov placeholder formula. "
                "Add oracle_cap column for production use. [SWAP-POINT]"
            )

        for row in reader:
            ts = float(row['timestamp'])
            posterior = float(np.clip(float(row['posterior']), 0.0, 1.0))

            # oracle_cap: use CSV column if available, else derive
            if has_cap:
                oracle_cap = float(np.clip(float(row['oracle_cap']), 0.1, 1.0))
            else:
                # SWAP-POINT: Replace gov.compute() with PosteriorGov_piecewise
                # once calibrated. Or better: add oracle_cap to your CSV.
                oracle_cap = gov.compute(posterior)

            # Optional L1/L2 for Variant B
            l1 = None
            if has_l1:
                l1_val = row.get('l1_structural') or row.get('l1')
                if l1_val:
                    l1 = float(np.clip(float(l1_val), 0.0, 1.0))

            l2 = None
            if has_l2:
                l2_val = row.get('l2_context') or row.get('l2')
                if l2_val:
                    l2 = float(np.clip(float(l2_val), 0.0, 1.0))

            ticks.append(OracleTick(
                timestamp=ts,
                posterior=posterior,
                oracle_cap=oracle_cap,
                l1_structural=l1,
                l2_context=l2,
            ))

    ticks.sort(key=lambda t: t.timestamp)
    return ticks


def write_oracle_to_csv(ticks: List[OracleTick], filepath: str,
                        include_l1l2: bool = False):
    """
    Write OracleTick sequence to CSV in the format expected by the Adversary.

    Args:
        ticks:        List[OracleTick] sorted ascending
        filepath:     Output file path
        include_l1l2: If True, write l1_structural and l2_context columns
    """
    import csv

    fieldnames = ['timestamp', 'posterior', 'oracle_cap']
    if include_l1l2:
        fieldnames += ['l1_structural', 'l2_context']

    with open(filepath, 'w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for tick in ticks:
            row = {
                'timestamp': f"{tick.timestamp:.3f}",
                'posterior': f"{tick.posterior:.6f}",
                'oracle_cap': f"{tick.oracle_cap:.6f}",
            }
            if include_l1l2:
                row['l1_structural'] = f"{tick.l1_structural:.6f}" if tick.l1_structural is not None else ''
                row['l2_context'] = f"{tick.l2_context:.6f}" if tick.l2_context is not None else ''
            writer.writerow(row)


# ─────────────────────────────────────────────────────────────
# Calibration Utilities
# ─────────────────────────────────────────────────────────────

class OracleCalibrator:
    """
    Utilities for calibrating Oracle parameters from historical data.

    Calibration sequence:
      1. Run Oracle on historical feature data with default params
      2. Compare posterior distribution against crash72 events
      3. Tune PosteriorGov thresholds to minimize exposure at crash starts
         while keeping occupancy < 35% (same acceptance criteria as Adversary)
      4. Re-run with calibrated params, verify metrics
    """

    @staticmethod
    def calibrate_posterior_gov(ticks: List[OracleTick],
                                crash_start_times: List[float],
                                target_crash_pctile: float = 70.0) -> PosteriorGov:
        """
        Suggest PosteriorGov thresholds based on posterior distribution at crash events.

        Strategy: The 'low_threshold' should be set so that the posterior at crash
        event starts is mostly above it. The 'high_threshold' marks where the steeper
        reduction kicks in.

        Args:
            ticks:              Oracle history
            crash_start_times:  Unix timestamps of crash event starts
            target_crash_pctile: Percentile of crash-time posteriors to use as low_threshold

        Returns:
            Suggested PosteriorGov with calibrated thresholds
        """
        if not ticks or not crash_start_times:
            warnings.warn("Insufficient data for calibration — returning defaults")
            return PosteriorGov()

        ts_arr = np.array([t.timestamp for t in ticks])
        post_arr = np.array([t.posterior for t in ticks])

        # Collect posterior values at each crash start (nearest tick)
        crash_posteriors = []
        for cs in crash_start_times:
            idx = int(np.searchsorted(ts_arr, cs, side='right')) - 1
            idx = max(0, min(idx, len(ticks) - 1))
            crash_posteriors.append(post_arr[idx])

        if not crash_posteriors:
            return PosteriorGov()

        crash_arr = np.array(crash_posteriors)
        low_thresh = float(np.percentile(crash_arr, 100 - target_crash_pctile))
        high_thresh = float(np.percentile(crash_arr, target_crash_pctile))

        # Ensure reasonable separation
        low_thresh = max(0.20, min(low_thresh, 0.45))
        high_thresh = max(low_thresh + 0.15, min(high_thresh, 0.80))

        print(f"[OracleCalibrator] crash posterior stats:")
        print(f"  n={len(crash_posteriors)}, mean={crash_arr.mean():.3f}, "
              f"p25={np.percentile(crash_arr,25):.3f}, p75={np.percentile(crash_arr,75):.3f}")
        print(f"  Suggested low_threshold={low_thresh:.3f}, high_threshold={high_thresh:.3f}")

        return PosteriorGov(low_threshold=low_thresh, high_threshold=high_thresh)

    @staticmethod
    def compute_posterior_stats(ticks: List[OracleTick]) -> Dict[str, float]:
        """Summary statistics of Oracle posterior over a history."""
        if not ticks:
            return {}
        post = np.array([t.posterior for t in ticks])
        cap = np.array([t.oracle_cap for t in ticks])
        return {
            'posterior_mean': float(post.mean()),
            'posterior_std': float(post.std()),
            'posterior_p10': float(np.percentile(post, 10)),
            'posterior_p50': float(np.percentile(post, 50)),
            'posterior_p90': float(np.percentile(post, 90)),
            'cap_mean': float(cap.mean()),
            'cap_min': float(cap.min()),
            'frac_cap_below_half': float((cap < 0.5).mean()),
        }


# ─────────────────────────────────────────────────────────────
# Smoke Test
# ─────────────────────────────────────────────────────────────

def _smoke_test():
    """
    Quick sanity check — runs without any external data.
    Verifies Oracle output is within contract bounds.
    """
    import time as _time

    print("Oracle v0 smoke test...")

    oracle = OracleV0(variant='B')

    # Generate a few test ticks
    base_ts = _time.time() - 3600

    test_cases = [
        # (label, onchain_risk, macro_trend, vol, momentum, funding)
        ("calm",        0.1, 0.1, 0.35, 0.05,  0.0001),
        ("rising_risk", 0.5, 0.4, 0.80, -0.10, 0.0008),
        ("high_stress", 0.8, 0.7, 1.50, -0.30, 0.0020),
        ("max_danger",  1.0, 1.0, 2.00, -0.50, 0.0030),
        ("missing",     None, None, None, None, None),
    ]

    all_pass = True
    for i, (label, oc, mt, vol, mom, fund) in enumerate(test_cases):
        features = OracleFeatures(
            timestamp=base_ts + i * 3600,
            onchain_risk=oc, macro_trend=mt,
            realized_vol=vol, price_momentum=mom, funding_rate=fund,
        )
        tick = oracle.evaluate(features)

        # Contract invariants
        assert 0.0 <= tick.posterior <= 1.0, f"posterior out of bounds: {tick.posterior}"
        assert 0.1 <= tick.oracle_cap <= 1.0, f"oracle_cap out of bounds: {tick.oracle_cap}"
        assert tick.l1_structural is not None, "Variant B must populate l1_structural"
        assert tick.l2_context is not None, "Variant B must populate l2_context"

        print(f"  [{label:12s}]  posterior={tick.posterior:.4f}  "
              f"cap={tick.oracle_cap:.4f}  "
              f"L1={tick.l1_structural:.4f}  L2={tick.l2_context:.4f}")

    # Verify monotonicity: higher danger features should NOT produce lower posteriors
    # (due to EMA smoothing, we just check the extreme cases)
    oracle.reset()
    calm_feats = OracleFeatures(timestamp=base_ts, onchain_risk=0.0, macro_trend=0.0,
                                realized_vol=0.3, price_momentum=0.1, funding_rate=0.0)
    danger_feats = OracleFeatures(timestamp=base_ts + 3600, onchain_risk=1.0, macro_trend=1.0,
                                  realized_vol=2.0, price_momentum=-0.5, funding_rate=0.003)
    calm_tick = oracle.evaluate(calm_feats)
    danger_tick = oracle.evaluate(danger_feats)
    assert danger_tick.posterior > calm_tick.posterior, \
        f"Monotonicity failed: danger ({danger_tick.posterior:.4f}) ≤ calm ({calm_tick.posterior:.4f})"
    assert danger_tick.oracle_cap < calm_tick.oracle_cap, \
        f"Cap monotonicity failed: danger cap ({danger_tick.oracle_cap:.4f}) ≥ calm cap ({calm_tick.oracle_cap:.4f})"

    print(f"\n  Monotonicity check PASSED")
    print(f"    calm: posterior={calm_tick.posterior:.4f} cap={calm_tick.oracle_cap:.4f}")
    print(f"    danger: posterior={danger_tick.posterior:.4f} cap={danger_tick.oracle_cap:.4f}")
    print(f"\nAll smoke tests PASSED ✓")
    return True


if __name__ == '__main__':
    _smoke_test()
