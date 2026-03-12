"""
Adversary v0 — Signal Computation Engine (ENHANCED)
Oracle Project | March 2026

Audit fixes applied:
  [1]  Vol surprise: absolute vol floor prevents false alarms in quiet markets
  [9]  Cooldown: grace-tick hysteresis prevents single-tick flicker reset
  [11] Vol surprise: Parkinson estimator for 5x statistical efficiency
  [12] Per-signal contribution tracking in AdversaryOutput
  [15] Haircut hysteresis: separated activate/deactivate thresholds

Design invariants (unchanged):
  - All signals normalized to [0, 1]
  - Adversary can only REDUCE exposure (haircut in [floor, 1.0])
  - No signal can increase risk beyond Oracle cap
  - Adversary never vetoes (floor = 0.3)
"""

import numpy as np
from dataclasses import dataclass, field
from typing import List, Tuple, Optional, Dict
from enum import Enum
import warnings


# ─────────────────────────────────────────────────────────────
# Data Structures
# ─────────────────────────────────────────────────────────────

@dataclass
class OracleTick:
    """Single Oracle evaluation tick."""
    timestamp: float
    posterior: float
    l1_structural: Optional[float] = None
    l2_context: Optional[float] = None
    oracle_cap: float = 1.0


@dataclass
class Candle5m:
    """Single 5-minute OHLCV candle."""
    timestamp: float
    open: float
    high: float
    low: float
    close: float
    vwap: float        # 0 if unavailable
    volume: float
    count: int = 0


@dataclass
class SignalContribution:
    """Per-signal breakdown of what drove contestation at a tick."""
    turbulence_raw: float
    turbulence_weighted: float
    turbulence_pct: float           # fraction of total score
    conflict_raw: Optional[float]
    conflict_weighted: float
    conflict_pct: float
    vol_surprise_raw: float
    vol_surprise_weighted: float
    vol_surprise_pct: float
    dominant_signal: str            # 'turbulence' | 'conflict' | 'vol_surprise'


@dataclass
class AdversaryOutput:
    """Complete Adversary evaluation at a single tick."""
    timestamp: float
    turbulence: float
    conflict: Optional[float]
    vol_surprise: float
    contestation_score: float
    haircut: float
    variant: str
    weight_version: str
    contribution: Optional[SignalContribution] = None
    cooldown_active: bool = False
    hysteresis_state: str = 'inactive'


class WeightVersion(Enum):
    EQUAL = 'equal'
    STRESS_DOMINANT = 'stress_dominant'


# ─────────────────────────────────────────────────────────────
# Signal 1: Model Turbulence
# ─────────────────────────────────────────────────────────────

class TurbulenceSignal:

    def __init__(self, lookback_hours: int = 4, norm_denominator: float = 0.4):
        self.lookback_hours = lookback_hours
        self.norm_denominator = norm_denominator

    def compute(self, posterior_history: List[Tuple[float, float]],
                current_time: float) -> float:
        if len(posterior_history) < 2:
            return 0.0
        target_time = current_time - self.lookback_hours * 3600
        current_posterior = posterior_history[-1][1]
        past_posterior = self._find_nearest(posterior_history, target_time)
        if past_posterior is None:
            return 0.0
        velocity = abs(current_posterior - past_posterior)
        return min(1.0, velocity / self.norm_denominator)

    def calibrate_denominator(self, posterior_history: List[Tuple[float, float]],
                               percentile: float = 95.0) -> float:
        if len(posterior_history) < self.lookback_hours + 1:
            warnings.warn("Insufficient history for turbulence calibration")
            return self.norm_denominator
        lookback_seconds = self.lookback_hours * 3600
        deltas = []
        for i in range(len(posterior_history)):
            target_ts = posterior_history[i][0] - lookback_seconds
            past_val = self._find_nearest(posterior_history[:i], target_ts)
            if past_val is not None:
                deltas.append(abs(posterior_history[i][1] - past_val))
        if not deltas:
            return self.norm_denominator
        calibrated = float(np.percentile(deltas, percentile))
        self.norm_denominator = max(0.05, calibrated)
        return self.norm_denominator

    @staticmethod
    def _find_nearest(history: List[Tuple[float, float]],
                      target_time: float) -> Optional[float]:
        if not history:
            return None
        lo, hi = 0, len(history) - 1
        while lo < hi:
            mid = (lo + hi) // 2
            if history[mid][0] < target_time:
                lo = mid + 1
            else:
                hi = mid
        best_idx, best_dist = lo, abs(history[lo][0] - target_time)
        if lo > 0:
            alt_dist = abs(history[lo - 1][0] - target_time)
            if alt_dist < best_dist:
                best_idx, best_dist = lo - 1, alt_dist
        if best_dist > 5400:  # 1.5h tolerance
            return None
        return history[best_idx][1]


# ─────────────────────────────────────────────────────────────
# Signal 2: Layer Conflict (Variant B only)
# ─────────────────────────────────────────────────────────────

class ConflictSignal:

    def __init__(self, rank_window_hours: int = 168):
        self.rank_window_hours = rank_window_hours

    def compute(self, l1_history: List[Tuple[float, float]],
                l2_history: List[Tuple[float, float]],
                current_time: float) -> Optional[float]:
        if not l1_history or not l2_history:
            return None
        cutoff = current_time - self.rank_window_hours * 3600
        l1_w = [v for ts, v in l1_history if ts >= cutoff]
        l2_w = [v for ts, v in l2_history if ts >= cutoff]
        if len(l1_w) < 10 or len(l2_w) < 10:
            return None
        l1_rank = self._percentile_rank(l1_w[-1], l1_w)
        l2_rank = self._percentile_rank(l2_w[-1], l2_w)
        return abs(l1_rank - l2_rank)

    @staticmethod
    def _percentile_rank(value: float, population: List[float]) -> float:
        return sum(1 for v in population if v <= value) / len(population)


# ─────────────────────────────────────────────────────────────
# Signal 3: Microstructure Stress — ENHANCED
# ─────────────────────────────────────────────────────────────
#
# FIX [1]:  Absolute vol floor prevents denominator collapse in quiet markets.
# FIX [11]: Parkinson high-low range estimator: 5x more efficient than
#           close-to-close. 24 Parkinson candles ≈ 125 close-to-close returns.

class VolSurpriseSignal:

    # Floor: minimum baseline vol. Typical BTC 5-min std ≈ 0.001-0.003.
    # Below this floor, market is too quiet for surprise ratio to be meaningful.
    # Calibrated from live BTC Kraken 5-min Parkinson vol:
    # 10th percentile ≈ 0.00073. Using 0.0008 (slightly above) so that
    # only genuinely unusual quiet markets trigger the floor.
    VOL_FLOOR = 0.0008

    def __init__(self,
                 realized_window_minutes: int = 120,
                 baseline_window_hours: int = 24,
                 gap_hours: int = 2,
                 candle_interval_minutes: int = 5,
                 use_parkinson: bool = True):
        self.realized_window_minutes = realized_window_minutes
        self.baseline_window_hours = baseline_window_hours
        self.gap_hours = gap_hours
        self.candle_interval_minutes = candle_interval_minutes
        self.use_parkinson = use_parkinson

        self.realized_candles = realized_window_minutes // candle_interval_minutes
        self.gap_candles = (gap_hours * 60) // candle_interval_minutes
        self.baseline_candles = (baseline_window_hours * 60) // candle_interval_minutes
        self.total_candles_needed = (self.realized_candles + self.gap_candles
                                     + self.baseline_candles)

    def compute(self, candles: List[Candle5m]) -> float:
        if len(candles) < self.total_candles_needed:
            return 1.0

        realized_slice = candles[-self.realized_candles:]
        baseline_end = len(candles) - self.realized_candles - self.gap_candles
        baseline_start = baseline_end - self.baseline_candles
        baseline_slice = candles[baseline_start:baseline_end]

        if self.use_parkinson:
            realized_vol = self._parkinson_vol(realized_slice)
            baseline_vol = self._parkinson_vol(baseline_slice)
        else:
            realized_vol = self._log_return_std(
                [self._price(c) for c in realized_slice])
            baseline_vol = self._log_return_std(
                [self._price(c) for c in baseline_slice])

        # FIX [1]: vol floor prevents quiet→normal false alarms
        effective_baseline = max(baseline_vol, self.VOL_FLOOR)

        if effective_baseline <= 0 or np.isnan(effective_baseline):
            return 1.0

        raw_surprise = max(0.0, (realized_vol - effective_baseline) / effective_baseline)
        return min(1.0, raw_surprise)

    @staticmethod
    def _price(c: Candle5m) -> float:
        return c.vwap if c.vwap > 0 else c.close

    @staticmethod
    def _log_return_std(prices: List[float]) -> float:
        if len(prices) < 2:
            return 0.0
        log_rets = [np.log(prices[i] / prices[i - 1])
                    for i in range(1, len(prices))
                    if prices[i - 1] > 0 and prices[i] > 0]
        if len(log_rets) < 2:
            return 0.0
        return float(np.std(log_rets, ddof=1))

    @staticmethod
    def _parkinson_vol(candles: List[Candle5m]) -> float:
        """
        Parkinson high-low range estimator.
        sigma^2 = (1 / 4n*ln2) * sum(ln(H/L)^2)
        ~5.2x more efficient than close-to-close for same sample size.
        """
        if len(candles) < 1:
            return 0.0
        sum_sq = 0.0
        valid = 0
        for c in candles:
            if c.high > 0 and c.low > 0 and c.high >= c.low:
                log_hl = np.log(c.high / c.low)
                sum_sq += log_hl ** 2
                valid += 1
        if valid < 2:
            return 0.0
        variance = sum_sq / (4.0 * valid * np.log(2.0))
        return float(np.sqrt(max(0.0, variance)))


# ─────────────────────────────────────────────────────────────
# Contestation Score — ENHANCED with contribution tracking
# ─────────────────────────────────────────────────────────────

class ContestationEngine:

    WEIGHTS = {
        ('A', 'equal'):           (0.50,  0.0,  0.50),
        ('A', 'stress_dominant'): (0.30,  0.0,  0.70),
        ('B', 'equal'):           (0.333, 0.333, 0.334),
        ('B', 'stress_dominant'): (0.20,  0.20,  0.60),
    }

    def __init__(self, variant: str = 'A', weight_version: str = 'equal'):
        if variant not in ('A', 'B'):
            raise ValueError(f"Unknown variant: {variant}")
        if weight_version not in ('equal', 'stress_dominant'):
            raise ValueError(f"Unknown weight version: {weight_version}")
        self.variant = variant
        self.weight_version = weight_version
        self.w_turb, self.w_conf, self.w_vol = self.WEIGHTS[(variant, weight_version)]

    def _effective_weights(self, conflict: Optional[float]):
        """Return (w_t, w_c, w_v) accounting for variant fallback."""
        if self.variant == 'B' and conflict is not None:
            return self.w_turb, self.w_conf, self.w_vol
        w_t, _, w_v = self.WEIGHTS[('A', self.weight_version)]
        return w_t, 0.0, w_v

    def score(self, turbulence: float, vol_surprise: float,
              conflict: Optional[float] = None) -> float:
        wt, wc, wv = self._effective_weights(conflict)
        conf_val = conflict if conflict is not None else 0.0
        raw = wt * turbulence + wc * conf_val + wv * vol_surprise
        return float(np.clip(raw, 0.0, 1.0))

    def contribution(self, turbulence: float, vol_surprise: float,
                     conflict: Optional[float] = None) -> SignalContribution:
        """FIX [12]: Per-signal contribution for diagnosis."""
        wt, wc, wv = self._effective_weights(conflict)
        conf_val = conflict if conflict is not None else 0.0

        t_w = wt * turbulence
        c_w = wc * conf_val
        v_w = wv * vol_surprise
        total = t_w + c_w + v_w

        if total > 0:
            t_pct, c_pct, v_pct = t_w / total, c_w / total, v_w / total
        else:
            t_pct = c_pct = v_pct = 0.0

        contribs = {'turbulence': t_w, 'conflict': c_w, 'vol_surprise': v_w}
        dominant = max(contribs, key=contribs.get)

        return SignalContribution(
            turbulence_raw=turbulence, turbulence_weighted=t_w, turbulence_pct=t_pct,
            conflict_raw=conflict, conflict_weighted=c_w, conflict_pct=c_pct,
            vol_surprise_raw=vol_surprise, vol_surprise_weighted=v_w, vol_surprise_pct=v_pct,
            dominant_signal=dominant,
        )


# ─────────────────────────────────────────────────────────────
# Haircut Function — ENHANCED with hysteresis
# ─────────────────────────────────────────────────────────────
#
# FIX [15]: Separate activate/deactivate thresholds.
# Once active, stays active until contestation drops below deactivate_threshold.
# Band: [0.12, 0.17] — 5 points of hysteresis prevents flicker.

class HaircutFunction:

    def __init__(self,
                 activate_threshold: float = 0.17,
                 deactivate_threshold: float = 0.12,
                 threshold_mid: float = 0.50,
                 mid_haircut: float = 0.70,
                 floor: float = 0.30):
        self.activate_threshold = activate_threshold
        self.deactivate_threshold = deactivate_threshold
        self.threshold_mid = threshold_mid
        self.mid_haircut = mid_haircut
        self.floor = floor
        self._active = False

    def compute(self, contestation: float) -> Tuple[float, str]:
        """Returns (haircut, state). state is 'active' or 'inactive'."""
        if self._active:
            if contestation < self.deactivate_threshold:
                self._active = False
        else:
            if contestation >= self.activate_threshold:
                self._active = True

        if not self._active:
            return 1.0, 'inactive'

        # Ramp from deactivate_threshold to mid, then mid to floor
        if contestation < self.threshold_mid:
            span = self.threshold_mid - self.deactivate_threshold
            if span > 0:
                progress = (contestation - self.deactivate_threshold) / span
            else:
                progress = 0.0
            progress = max(0.0, min(1.0, progress))
            haircut = 1.0 - (1.0 - self.mid_haircut) * progress
        else:
            span = 1.0 - self.threshold_mid
            if span > 0:
                progress = (contestation - self.threshold_mid) / span
            else:
                progress = 0.0
            progress = min(1.0, progress)
            haircut = self.mid_haircut - (self.mid_haircut - self.floor) * progress

        return haircut, 'active'

    def reset(self):
        self._active = False


# ─────────────────────────────────────────────────────────────
# Cooldown — ENHANCED with grace-tick hysteresis
# ─────────────────────────────────────────────────────────────
#
# FIX [9]: Requires grace_ticks consecutive ticks below threshold
# before resetting. Prevents oscillating markets from permanently
# defeating cooldown.

class TurbulenceCooldown:

    def __init__(self, threshold: float = 0.30,
                 duration_hours: int = 48,
                 decay_rate: float = 0.1,
                 grace_ticks: int = 3):
        self.threshold = threshold
        self.duration_hours = duration_hours
        self.decay_rate = decay_rate
        self.grace_ticks = grace_ticks
        self._above_since: Optional[float] = None
        self._below_count: int = 0

    def apply(self, turbulence: float, contestation: float,
              current_time: float) -> Tuple[float, bool]:
        """Returns (adjusted_turbulence, is_decaying)."""
        if contestation > self.threshold:
            self._below_count = 0
            if self._above_since is None:
                self._above_since = current_time
            else:
                elapsed_hours = (current_time - self._above_since) / 3600
                if elapsed_hours > self.duration_hours:
                    excess = elapsed_hours - self.duration_hours
                    factor = max(0.0, 1.0 - self.decay_rate * excess)
                    return turbulence * factor, True
        else:
            self._below_count += 1
            if self._below_count >= self.grace_ticks:
                self._above_since = None
                self._below_count = 0
        return turbulence, False

    def reset(self):
        self._above_since = None
        self._below_count = 0


# ─────────────────────────────────────────────────────────────
# Full Adversary v0 Evaluator
# ─────────────────────────────────────────────────────────────

class AdversaryV0:

    def __init__(self, variant: str = 'A', weight_version: str = 'equal',
                 enable_cooldown: bool = True, use_parkinson: bool = True):
        self.variant = variant
        self.weight_version = weight_version
        self.enable_cooldown = enable_cooldown

        self.turbulence_signal = TurbulenceSignal()
        self.conflict_signal = ConflictSignal() if variant == 'B' else None
        self.vol_surprise_signal = VolSurpriseSignal(use_parkinson=use_parkinson)
        self.contestation = ContestationEngine(variant, weight_version)
        self.haircut_fn = HaircutFunction()
        self.cooldown = TurbulenceCooldown() if enable_cooldown else None

    def evaluate(self, oracle_history: List[OracleTick],
                 candles: List[Candle5m],
                 current_time: Optional[float] = None) -> AdversaryOutput:

        if current_time is None:
            current_time = oracle_history[-1].timestamp

        # Signal 1
        posterior_ts = [(t.timestamp, t.posterior) for t in oracle_history]
        turbulence = self.turbulence_signal.compute(posterior_ts, current_time)

        # Signal 2
        conflict = None
        if self.variant == 'B' and self.conflict_signal is not None:
            l1_ts = [(t.timestamp, t.l1_structural) for t in oracle_history
                     if t.l1_structural is not None]
            l2_ts = [(t.timestamp, t.l2_context) for t in oracle_history
                     if t.l2_context is not None]
            if l1_ts and l2_ts:
                conflict = self.conflict_signal.compute(l1_ts, l2_ts, current_time)

        # Signal 3
        vol_surprise = self.vol_surprise_signal.compute(candles)

        # Cooldown
        cooldown_active = False
        if self.cooldown:
            prelim = self.contestation.score(turbulence, vol_surprise, conflict)
            turbulence, cooldown_active = self.cooldown.apply(
                turbulence, prelim, current_time)

        # Score + contribution
        score = self.contestation.score(turbulence, vol_surprise, conflict)
        contribution = self.contestation.contribution(turbulence, vol_surprise, conflict)

        # Haircut with hysteresis
        haircut, hyst_state = self.haircut_fn.compute(score)

        return AdversaryOutput(
            timestamp=current_time,
            turbulence=turbulence, conflict=conflict, vol_surprise=vol_surprise,
            contestation_score=score, haircut=haircut,
            variant=self.variant, weight_version=self.weight_version,
            contribution=contribution,
            cooldown_active=cooldown_active,
            hysteresis_state=hyst_state,
        )

    def calibrate(self, oracle_history: List[OracleTick]) -> Dict[str, float]:
        posterior_ts = [(t.timestamp, t.posterior) for t in oracle_history]
        denom = self.turbulence_signal.calibrate_denominator(posterior_ts)
        return {'turbulence_norm_denominator': denom}

    def reset_state(self):
        """Reset all stateful components between independent runs."""
        if self.cooldown:
            self.cooldown.reset()
        self.haircut_fn.reset()
