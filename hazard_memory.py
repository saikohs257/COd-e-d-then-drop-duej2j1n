"""
Hazard Memory — Adversary v1
Oracle Project | March 2026

Fixes the time-axis bug in Adversary v0:
  v0 activates on signal transitions, then deactivates when signals quiet.
  v1 accumulates hazard across time and decays slowly — skepticism persists
  through occupied danger, not just initial transitions.

The root cause diagnosed from event traces:
  TurbulenceSignal measures VELOCITY of posterior change.
  When posterior stabilizes at a high level (e.g. 0.68 for 8 hours),
  velocity → 0, turbulence → 0, haircut → 1.0.
  The Adversary reads "calm" from what is a sustained dangerous environment.

The fix:
  Replace the instantaneous contestation → haircut mapping with a
  state variable (hazard_score) that integrates signals over time.
  hazard_t = decay * hazard_{t-1} + (1 - decay) * signal_strength_t
  haircut  = sigmoid(hazard_t)

Four signals feed the hazard kernel:
  1. posterior_turbulence  — velocity of Oracle belief change (from v0)
  2. vol_surprise          — microstructure stress (from v0)
  3. posterior_level       — absolute level of Oracle posterior
                            (new — the missing piece for occupied danger)
  4. fragility             — structural leverage crowding (OI + funding persistence)
                            from fragility.StructuralFragilitySignal

Design invariants preserved from v0:
  - Adversary can only REDUCE exposure (haircut ∈ [floor, 1.0])
  - floor = 0.30 (Adversary never vetoes)
  - Fully compatible with existing AdversaryOutput, BacktestEngine, ForensicsEngine
  - AdversaryV0 is untouched — AdversaryV1 is a subclass

Integration:
  adv = AdversaryV1(variant='A', weight_version='equal')
  adv.calibrate(oracle_history)
  output = adv.evaluate(oracle_history, candles, current_time)
  # output.haircut now reflects hazard memory, not instantaneous contestation
  # output.signals_raw includes 'hazard_score' and 'posterior_level'
"""

import numpy as np
from typing import List, Optional
from signals import (
    OracleTick, Candle5m, AdversaryV0, AdversaryOutput,
    TurbulenceSignal, VolSurpriseSignal, ConflictSignal,
    ContestationEngine, HaircutFunction, TurbulenceCooldown,
)


# ─────────────────────────────────────────────────────────────
# Posterior Level Signal
# ─────────────────────────────────────────────────────────────

class PosteriorLevelSignal:
    """
    Converts absolute Oracle posterior level into a [0,1] risk signal.

    This is the missing piece in v0. Turbulence measures velocity —
    how fast the posterior is changing. But a posterior sitting at 0.70
    for 10 hours is genuinely dangerous, even though velocity = 0.

    The level signal captures occupied danger: extended time in a
    structurally elevated risk regime.

    Dead zone:
      Below `threshold`, the posterior is in a safe regime and this
      signal contributes nothing. This prevents the level signal from
      producing chronic low-level haircuts during normal operation.

      Threshold calibrated to the 70th percentile of posterior distribution
      in calm markets. Default 0.35 — recalibrate from real data.

    Posterior level is intentionally weighted lower than turbulence
    and vol_surprise in the hazard kernel. The Oracle already handles
    level via oracle_cap — this signal adds the cross-time integration
    that cap alone cannot provide.
    """

    def __init__(self, threshold: float = 0.35):
        """
        Args:
            threshold: Posterior below this contributes zero to hazard.
                       Should be calibrated to the 70th pctile of calm-market posteriors.
        """
        assert 0.0 < threshold < 1.0
        self.threshold = threshold

    def compute(self, posterior: float) -> float:
        """
        Map posterior level to a [0, 1] level signal.

        Linear ramp from 0 at threshold to 1 at posterior=1.0.
        """
        if posterior <= self.threshold:
            return 0.0
        return (posterior - self.threshold) / (1.0 - self.threshold)

    def calibrate_threshold(
        self,
        posterior_history: List[tuple],
        calm_percentile: float = 70.0,
    ) -> float:
        """
        Set threshold to `calm_percentile` of the full posterior distribution.

        Rationale: anything below the 70th percentile is 'normal' variation
        and should not accumulate hazard via the level signal alone.

        Args:
            posterior_history: [(timestamp, posterior), ...] sorted ascending
            calm_percentile:   percentile to use as the safe/dangerous boundary

        Returns:
            calibrated threshold (also stored in self.threshold)
        """
        if len(posterior_history) < 10:
            return self.threshold

        values = [p for _, p in posterior_history]
        calibrated = float(np.percentile(values, calm_percentile))
        # Hard bounds: must stay in a sensible range
        self.threshold = float(np.clip(calibrated, 0.20, 0.65))
        return self.threshold


# ─────────────────────────────────────────────────────────────
# Hazard Kernel
# ─────────────────────────────────────────────────────────────

class HazardKernel:
    """
    Exponentially weighted integrator over signal inputs.

    hazard_t = decay * hazard_{t-1} + (1 - decay) * signal_strength_t

    Where signal_strength_t is a weighted blend of:
      turbulence     — velocity of Oracle belief change
      vol_surprise   — microstructure stress
      posterior_level — absolute level in danger territory
      fragility       — structural leverage crowding (OI + funding persistence)

    Hazard accumulates when signals are repeatedly elevated.
    Hazard decays slowly when signals quiet.
    A single brief spike produces only small hazard.
    Sustained moderate signals build significant hazard.

    This creates the hysteresis that v0 was missing:
    the system cannot instantly return to "safe" after a danger period.

    Decay parameter:
      decay = 0.85 means ~6h half-life of accumulated hazard.
      After 6h of silence, hazard decays to ~37% of peak.
      After 12h of silence, hazard decays to ~14% of peak.
      After 24h, ~2% of peak (effectively gone).

      Half-life formula: t_half = log(0.5) / log(decay) [in ticks]
      At hourly Oracle cadence: decay=0.85 → half-life ≈ 4.3 ticks ≈ 4.3h.

    The kernel is tick-cadence-agnostic when initialized with tick_interval_hours.
    Internally it adjusts the per-tick decay to match the desired half-life.
    """

    def __init__(
        self,
        decay: float = 0.85,
        w_turbulence: float = 0.40,
        w_vol_surprise: float = 0.40,
        w_posterior_level: float = 0.20,
        w_fragility: float = 0.00,
        tick_interval_hours: float = 1.0,
        target_halflife_hours: float = None,
    ):
        """
        Args:
            decay:                 Per-tick exponential decay (0 < decay < 1).
                                   Higher = slower decay = longer memory.
            w_turbulence:          Weight on turbulence signal ∈ [0, 1].
            w_vol_surprise:        Weight on vol_surprise signal ∈ [0, 1].
            w_posterior_level:     Weight on posterior_level signal ∈ [0, 1].
            w_fragility:           Weight on structural fragility signal ∈ [0, 1].
            tick_interval_hours:   Time between Oracle ticks (default 1h).
                                   Used only if target_halflife_hours is set.
            target_halflife_hours: If set, overrides `decay` to achieve the target
                                   half-life in wall-clock hours. Recommended over
                                   setting decay directly.
        """
        total_w = w_turbulence + w_vol_surprise + w_posterior_level + w_fragility
        assert abs(total_w - 1.0) < 1e-9, (
            f"Hazard kernel weights must sum to 1.0, got {total_w:.6f}. "
            f"Weights: turb={w_turbulence}, vol={w_vol_surprise}, "
            f"level={w_posterior_level}, fragility={w_fragility}"
        )
        assert 0.0 < decay < 1.0, f"decay must be in (0, 1), got {decay}"

        self.w_turbulence = w_turbulence
        self.w_vol_surprise = w_vol_surprise
        self.w_posterior_level = w_posterior_level
        self.w_fragility = w_fragility
        self.tick_interval_hours = tick_interval_hours

        if target_halflife_hours is not None:
            # Override decay to hit the target half-life
            # hazard decays by factor `decay` each tick
            # after n ticks: hazard_n = decay^n * hazard_0
            # half-life: 0.5 = decay^(t_half / tick_interval)
            ticks_per_halflife = target_halflife_hours / tick_interval_hours
            self.decay = float(0.5 ** (1.0 / ticks_per_halflife))
        else:
            self.decay = decay

        self._hazard: float = 0.0

    def update(
        self,
        turbulence: float,
        vol_surprise: float,
        posterior_level: float,
        fragility: float = 0.0,
    ) -> float:
        """
        Advance the hazard state by one tick.

        Args:
            turbulence:       TurbulenceSignal output ∈ [0, 1]
            vol_surprise:     VolSurpriseSignal output ∈ [0, 1]
            posterior_level:  PosteriorLevelSignal output ∈ [0, 1]
            fragility:        StructuralFragilitySignal output ∈ [0, 1]
                              Pass 0.0 when no OI/funding data is available.

        Returns:
            Updated hazard score ∈ [0, 1]
        """
        signal_strength = (
            self.w_turbulence      * turbulence +
            self.w_vol_surprise    * vol_surprise +
            self.w_posterior_level * posterior_level +
            self.w_fragility       * fragility
        )
        signal_strength = float(np.clip(signal_strength, 0.0, 1.0))

        self._hazard = self.decay * self._hazard + (1.0 - self.decay) * signal_strength
        self._hazard = float(np.clip(self._hazard, 0.0, 1.0))

        return self._hazard

    @property
    def hazard(self) -> float:
        """Current hazard score ∈ [0, 1]. Read-only."""
        return self._hazard

    @property
    def halflife_hours(self) -> float:
        """Effective half-life of accumulated hazard in hours."""
        if self.decay <= 0 or self.decay >= 1:
            return float('inf')
        ticks = np.log(0.5) / np.log(self.decay)
        return ticks * self.tick_interval_hours

    def reset(self, initial_hazard: float = 0.0):
        """Reset hazard state. Call before each backtest run."""
        self._hazard = float(np.clip(initial_hazard, 0.0, 1.0))

    def peek(self) -> float:
        """Return current hazard without advancing state. For inspection only."""
        return self._hazard


# ─────────────────────────────────────────────────────────────
# Hazard Haircut Function
# ─────────────────────────────────────────────────────────────

class HazardHaircutFunction:
    """
    Maps hazard score → exposure multiplier via sigmoid.

    Replaces v0's piecewise-linear mapping from contestation score.

    The sigmoid is the natural function here because:
    - Hazard is an accumulator, not a raw signal — its extremes are meaningful
    - We want smooth behavior around the midpoint, not linear ramps
    - The floor is enforced as a hard constraint (Adversary never vetoes)

    Hazard dead zone:
      Below `dead_zone`, hazard is treated as zero (haircut = 1.0).
      This prevents accumulated baseline noise from imposing micro-haircuts.
      The dead zone is wider than v0's threshold_low because hazard integrates
      over time — even a flat 0.10 hazard represents real accumulated signal.

    Sigmoid parameters:
      midpoint = 0.50   → haircut is 0.65 when hazard = 0.5 (moderate protection)
      steepness = 10.0  → transition from ~1.0 to ~0.3 over hazard range [0.3, 0.7]

    Calibration target:
      hazard = 0.0  → haircut = 1.00  (no protection)
      hazard = 0.3  → haircut ≈ 0.90  (light)
      hazard = 0.5  → haircut ≈ 0.65  (moderate)
      hazard = 0.7  → haircut ≈ 0.38  (strong)
      hazard = 1.0  → haircut ≈ 0.30  (floor)
    """

    def __init__(
        self,
        midpoint: float = 0.50,
        steepness: float = 10.0,
        floor: float = 0.30,
        dead_zone: float = 0.15,
    ):
        """
        Args:
            midpoint:   Hazard level at which haircut = midpoint of floor..1.0 range.
            steepness:  Sigmoid slope. Higher = sharper transition.
            floor:      Minimum haircut (same as v0 floor, must not change).
            dead_zone:  Hazard below this → haircut = 1.0 (no protection).
        """
        assert 0.0 <= dead_zone < midpoint < 1.0
        assert 0.0 < floor < 1.0
        self.midpoint = midpoint
        self.steepness = steepness
        self.floor = floor
        self.dead_zone = dead_zone

    def compute(self, hazard: float) -> float:
        """
        Map hazard score to haircut multiplier ∈ [floor, 1.0].

        Args:
            hazard: Current hazard score ∈ [0, 1]

        Returns:
            haircut ∈ [floor, 1.0]
        """
        hazard = float(np.clip(hazard, 0.0, 1.0))

        if hazard < self.dead_zone:
            return 1.0

        # Decreasing sigmoid: high hazard → low haircut
        sig = 1.0 / (1.0 + np.exp(self.steepness * (hazard - self.midpoint)))

        # Map sigmoid output [0, 1] to haircut range [floor, 1.0]
        return float(np.clip(self.floor + (1.0 - self.floor) * sig, self.floor, 1.0))

    def describe(self) -> str:
        """Print the mapping at key hazard levels for inspection."""
        lines = ["HazardHaircutFunction mapping:"]
        for h in [0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0]:
            hc = self.compute(h)
            bar = '█' * int(hc * 20)
            lines.append(f"  hazard={h:.1f}  haircut={hc:.4f}  {bar}")
        return "\n".join(lines)


# ─────────────────────────────────────────────────────────────
# Adversary V1 — Drop-in replacement for AdversaryV0
# ─────────────────────────────────────────────────────────────

class AdversaryV1(AdversaryV0):
    """
    Adversary v1: replaces instantaneous contestation haircut with hazard memory.

    Inherits all signal computation from AdversaryV0.
    Replaces only the final haircut step.

    The contestation score is still computed and stored in the output —
    it now feeds the hazard kernel as one input, not directly to the haircut.

    Changes from v0:
      + HazardKernel accumulates risk over time (new)
      + PosteriorLevelSignal adds level awareness (new)
      + HazardHaircutFunction maps hazard → haircut via sigmoid (new)
      - TurbulenceCooldown is disabled by default in v1
        (the hazard kernel's decay serves the same anti-chronic-paranoia role
        but without the hard reset that caused v0's persistence failures)

    Backward compatibility:
      - Same evaluate() signature as AdversaryV0
      - Same AdversaryOutput fields — consumers unchanged
      - 'hazard_score' and 'posterior_level' added to signals_raw
      - contestation_score in output reflects raw contestation (as in v0)
        so forensics comparisons remain valid

    Usage:
        adv = AdversaryV1(variant='A', weight_version='equal')
        adv.calibrate(oracle_history)   # same calibration call as v0
        output = adv.evaluate(oracle_history, candles, current_time)
        exposure = oracle_cap * output.haircut
    """

    def __init__(
        self,
        variant: str = 'A',
        weight_version: str = 'equal',
        # Hazard kernel parameters
        hazard_decay: float = 0.85,
        hazard_halflife_hours: float = None,
        w_turbulence: float = 0.40,
        w_vol_surprise: float = 0.40,
        w_posterior_level: float = 0.20,
        w_flow_direction: float = 0.00,  # kept for backward compat; prefer w_fragility
        w_fragility: float = 0.00,
        # Haircut function parameters
        sigmoid_midpoint: float = 0.50,
        sigmoid_steepness: float = 10.0,
        haircut_floor: float = 0.30,
        hazard_dead_zone: float = 0.15,
        # Posterior level signal
        posterior_level_threshold: float = 0.35,
    ):
        """
        Args:
            variant, weight_version: passed to AdversaryV0
            hazard_decay:            per-tick decay (overridden if hazard_halflife_hours set)
            hazard_halflife_hours:   if set, decay is derived to match this half-life
            w_*:                     hazard kernel input weights (must sum to 1.0).
                                     w_fragility replaces the old w_flow_direction slot.
            sigmoid_*:               haircut sigmoid shape parameters
            haircut_floor:           minimum haircut (must match constitutional constraint)
            hazard_dead_zone:        hazard below this → no haircut
            posterior_level_threshold: posterior below this contributes zero level signal
        """
        # v1 disables v0's TurbulenceCooldown by default.
        # Reason: the hazard kernel's exponential decay is the correct
        # anti-chronic-paranoia mechanism. The hard reset in TurbulenceCooldown
        # was the proximate cause of v0's persistence failures (Category A events).
        super().__init__(
            variant=variant,
            weight_version=weight_version,
            enable_cooldown=False,
        )

        self.posterior_level_signal = PosteriorLevelSignal(
            threshold=posterior_level_threshold
        )

        # Resolve backward compat: w_flow_direction maps to w_fragility if set
        _w_fragility = w_fragility if w_fragility > 0.0 else w_flow_direction

        self.hazard_kernel = HazardKernel(
            decay=hazard_decay,
            w_turbulence=w_turbulence,
            w_vol_surprise=w_vol_surprise,
            w_posterior_level=w_posterior_level,
            w_fragility=_w_fragility,
            target_halflife_hours=hazard_halflife_hours,
        )

        self.hazard_haircut_fn = HazardHaircutFunction(
            midpoint=sigmoid_midpoint,
            steepness=sigmoid_steepness,
            floor=haircut_floor,
            dead_zone=hazard_dead_zone,
        )

    def evaluate(
        self,
        oracle_history: List[OracleTick],
        candles: List[Candle5m],
        current_time: float = None,
        fragility: float = 0.0,
    ) -> AdversaryOutput:
        """
        Run Adversary v1 evaluation.

        Computes all v0 signals, feeds them into the hazard kernel,
        maps hazard → haircut via sigmoid.

        The contestation_score field in AdversaryOutput reflects the
        raw v0 contestation (for forensics continuity). The haircut
        reflects the hazard-based computation.

        Args:
            oracle_history: Oracle ticks with at least 4h history
            candles:        5-min candles with at least 28h history
            current_time:   Override eval time (defaults to last oracle tick)
            fragility:      StructuralFragilitySignal score ∈ [0, 1].
                            Pass 0.0 (default) when OI/funding data is unavailable.
                            The hazard kernel weight w_fragility must be set > 0
                            at construction for this to have effect.

        Returns:
            AdversaryOutput — same structure as v0, haircut now hazard-based
        """
        if current_time is None:
            current_time = oracle_history[-1].timestamp

        # ── Step 1: Compute all raw signals (inherited from v0) ──

        posterior_ts = [(t.timestamp, t.posterior) for t in oracle_history]
        turbulence = self.turbulence_signal.compute(posterior_ts, current_time)

        conflict = None
        if self.variant == 'B' and self.conflict_signal is not None:
            l1_ts = [(t.timestamp, t.l1_structural) for t in oracle_history
                     if t.l1_structural is not None]
            l2_ts = [(t.timestamp, t.l2_context) for t in oracle_history
                     if t.l2_context is not None]
            if l1_ts and l2_ts:
                conflict = self.conflict_signal.compute(l1_ts, l2_ts, current_time)

        vol_surprise = self.vol_surprise_signal.compute(candles)

        # ── Step 2: Posterior level signal (new in v1) ──

        current_posterior = oracle_history[-1].posterior
        posterior_level = self.posterior_level_signal.compute(current_posterior)

        # ── Step 3: Raw contestation score (v0 compatible, for diagnostics) ──

        contestation_score = self.contestation.score(turbulence, vol_surprise, conflict)

        # ── Step 4: Update hazard kernel ──

        hazard = self.hazard_kernel.update(
            turbulence=turbulence,
            vol_surprise=vol_surprise,
            posterior_level=posterior_level,
            fragility=float(np.clip(fragility, 0.0, 1.0)),
        )

        # ── Step 5: Hazard → haircut via sigmoid ──

        haircut = self.hazard_haircut_fn.compute(hazard)

        return AdversaryOutput(
            timestamp=current_time,
            turbulence=turbulence,
            conflict=conflict,
            vol_surprise=vol_surprise,
            contestation_score=contestation_score,  # v0-compatible field
            haircut=haircut,                         # now hazard-based
            variant=self.variant,
            weight_version=self.weight_version,
            signals_raw={
                'turbulence_raw': turbulence,
                'conflict_raw': conflict if conflict is not None else -1.0,
                'vol_surprise_raw': vol_surprise,
                'posterior_level': posterior_level,
                'fragility_score': float(fragility),
                'contestation_raw': contestation_score,
                'hazard_score': hazard,
                'hazard_halflife_hours': self.hazard_kernel.halflife_hours,
                'cooldown_active': False,  # v1 does not use cooldown
            },
        )

    def calibrate(self, oracle_history: List[OracleTick]) -> dict:
        """
        Calibrate v1 parameters from historical data.

        Runs v0 turbulence calibration + calibrates posterior level threshold.

        Returns dict of calibrated parameters for logging.
        """
        # v0 turbulence calibration
        posterior_ts = [(t.timestamp, t.posterior) for t in oracle_history]
        turb_denom = self.turbulence_signal.calibrate_denominator(posterior_ts)

        # v1 posterior level threshold
        level_threshold = self.posterior_level_signal.calibrate_threshold(posterior_ts)

        return {
            'turbulence_norm_denominator': turb_denom,
            'posterior_level_threshold': level_threshold,
            'hazard_decay': self.hazard_kernel.decay,
            'hazard_halflife_hours': self.hazard_kernel.halflife_hours,
        }

    def reset(self):
        """Reset all stateful components. Call before each backtest run."""
        self.hazard_kernel.reset()
        if self.cooldown:
            self.cooldown.reset()


# ─────────────────────────────────────────────────────────────
# Decay Calibration Utilities
# ─────────────────────────────────────────────────────────────

def calibrate_decay_from_events(
    crash_events_durations_hours: List[float],
    target_coverage_factor: float = 1.5,
) -> float:
    """
    Suggest a decay parameter based on the typical crash event duration.

    Rationale: hazard should remain meaningfully elevated through the
    acute phase of a typical event. If events typically last D hours,
    the half-life should be D * coverage_factor.

    Args:
        crash_events_durations_hours: list of observed event durations in hours
        target_coverage_factor:       how many half-lives to cover the event

    Returns:
        Suggested decay per tick (assumes hourly Oracle cadence)
    """
    if not crash_events_durations_hours:
        return 0.85  # default

    median_duration = float(np.median(crash_events_durations_hours))
    target_halflife = median_duration * target_coverage_factor
    # At hourly cadence: decay = 0.5 ^ (1/halflife_in_ticks)
    decay = float(0.5 ** (1.0 / target_halflife))
    return float(np.clip(decay, 0.70, 0.95))


def describe_decay(decay: float, tick_interval_hours: float = 1.0) -> str:
    """Human-readable description of a decay constant."""
    if decay <= 0 or decay >= 1:
        return f"decay={decay} (invalid)"
    halflife_ticks = np.log(0.5) / np.log(decay)
    halflife_hours = halflife_ticks * tick_interval_hours
    pct_after_6h  = decay ** (6.0  / tick_interval_hours) * 100
    pct_after_12h = decay ** (12.0 / tick_interval_hours) * 100
    pct_after_24h = decay ** (24.0 / tick_interval_hours) * 100
    return (
        f"decay={decay:.3f}  "
        f"half-life={halflife_hours:.1f}h  "
        f"remaining after 6h={pct_after_6h:.0f}%  "
        f"12h={pct_after_12h:.0f}%  "
        f"24h={pct_after_24h:.0f}%"
    )


# ─────────────────────────────────────────────────────────────
# Smoke Test
# ─────────────────────────────────────────────────────────────

def _smoke_test():
    """
    Verifies the module in isolation, without running a full backtest.
    Checks contract invariants and the core persistence behavior.
    """
    print("Hazard Memory v1 smoke test...")
    print()

    # ── 1. Decay description ──
    for d in [0.75, 0.85, 0.90, 0.95]:
        print(f"  {describe_decay(d)}")
    print()

    # ── 2. Haircut mapping ──
    hf = HazardHaircutFunction()
    print(hf.describe())
    print()

    # ── 3. Kernel behavior ──
    kernel = HazardKernel(decay=0.85, w_turbulence=0.40, w_vol_surprise=0.40,
                          w_posterior_level=0.20, w_fragility=0.00)
    level_sig = PosteriorLevelSignal(threshold=0.35)

    print("Kernel behavior test: 6h strong signal → silence:")
    for h in range(20):
        turb = 0.8 if h < 6 else 0.0
        vol  = 0.5 if h < 6 else 0.0
        post = 0.7 if h < 6 else 0.3
        lev  = level_sig.compute(post)
        hz   = kernel.update(turb, vol, lev)
        hc   = hf.compute(hz)
        bar  = '█' * int((1.0 - hc) * 20)
        phase = 'SIGNAL' if h < 6 else 'SILENCE'
        print(f"  h={h:2d} [{phase}]  hazard={hz:.4f}  haircut={hc:.4f}  reduction={bar}")

    # ── 4. Contract invariants ──
    kernel.reset()
    all_pass = True

    for _ in range(100):
        hz = kernel.update(
            turbulence=float(np.random.uniform(0, 1)),
            vol_surprise=float(np.random.uniform(0, 1)),
            posterior_level=float(np.random.uniform(0, 1)),
        )
        hc = hf.compute(hz)
        assert 0.0 <= hz <= 1.0, f"hazard out of bounds: {hz}"
        assert 0.30 <= hc <= 1.0, f"haircut out of bounds: {hc}"

    print()
    print("Contract invariants (100 random inputs): PASSED ✓")

    # ── 5. Persistence test ──
    kernel.reset()

    # 3 ticks of strong signal
    for _ in range(3):
        kernel.update(turbulence=1.0, vol_surprise=1.0, posterior_level=1.0)
    peak_hazard = kernel.hazard

    # 12 ticks of silence — hazard should still be non-trivial
    for _ in range(12):
        kernel.update(turbulence=0.0, vol_surprise=0.0, posterior_level=0.0)
    after_silence = kernel.hazard

    assert after_silence > 0.01, f"Hazard decayed too fast: {after_silence:.4f} after 12h"
    print(f"Persistence test: peak={peak_hazard:.4f} → after 12h silence={after_silence:.4f}  PASSED ✓")

    print()
    print("All smoke tests PASSED ✓")


if __name__ == '__main__':
    _smoke_test()
