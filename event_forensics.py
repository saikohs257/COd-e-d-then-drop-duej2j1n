"""
Event Forensics Engine — Oracle Project
March 2026

Turns backtest runs into structured event case files.

The system currently runs backtests but does not explain events.
This module closes that gap.

For every crash event it answers:
  - When did risk first appear?
  - Which signal triggered first?
  - How early was the warning?
  - How persistent was it?
  - Did the Adversary act or miss?
  - What failure category does this event belong to?

Outputs:
  events_report.csv      — one row per event, all metrics
  event_summary.json     — aggregate stats + per-event case files

Architecture:
  This module does NOT modify the Adversary or Oracle.
  It is a pure observer: it replays the backtest tick-by-tick,
  collecting full AdversaryOutput at each tick, then post-processes
  the tick trace against each crash event.

Usage:
  from event_forensics import ForensicsEngine, detect_crash_events

  engine = ForensicsEngine(oracle_history, candles, crash_events)
  engine.run(adversary)
  engine.write_csv('events_report.csv')
  engine.write_json('event_summary.json')
"""

import json
import csv
import warnings
import numpy as np
from dataclasses import dataclass, field, asdict
from typing import List, Dict, Optional, Tuple

from signals import OracleTick, Candle5m, AdversaryV0, AdversaryOutput
from backtest import Crash72Event


# ─────────────────────────────────────────────────────────────
# Failure Taxonomy
# From execution plan Section 5 — treated as law here.
# ─────────────────────────────────────────────────────────────

FAILURE_TAXONOMY = {
    'A': 'transition_without_persistence',
    'B': 'fragility_blindness',
    'C': 'false_calm_miss',
    'D': 'chronic_paranoia',
    'E': 'oracle_already_sufficient',
    'F': 'good_skepticism',
}

# Classification thresholds
HAIRCUT_ACTIVE_THRESHOLD = 0.99       # haircut < this = Adversary is doing something
MEANINGFUL_HAIRCUT = 0.85             # haircut < this = meaningful reduction
EARLY_WARNING_HOURS = 4.0             # lead time > this = "early" warning
PERSISTENCE_MIN_BARS = 3              # consecutive active bars to count as persistent
FALSE_CALM_MAX_POSTERIOR = 0.35       # oracle posterior was low → false calm
PARANOIA_OCCUPANCY_THRESHOLD = 0.50   # >50% of non-event time active = chronic paranoia


# ─────────────────────────────────────────────────────────────
# Data Structures
# ─────────────────────────────────────────────────────────────

@dataclass
class TickRecord:
    """
    Full state at a single Oracle tick, after Adversary evaluation.
    This is the raw trace that event forensics operates on.
    """
    timestamp: float
    price: float
    oracle_cap: float
    posterior: float
    exposure: float          # oracle_cap * haircut
    haircut: float
    contestation: float
    turbulence: float
    vol_surprise: float
    conflict: Optional[float]
    dominant_signal: str     # which signal contributed most this tick
    cooldown_active: bool
    fragility: float = 0.0   # StructuralFragilitySignal score ∈ [0, 1]; 0 if not provided


@dataclass
class EventCaseFile:
    """
    Complete forensic record for a single crash event.
    Maps directly to one row in events_report.csv and one entry in event_summary.json.
    """
    # Identity
    event_id: int
    label: str
    drawdown_pct: float

    # Timing
    crash_start: float           # Unix timestamp
    trough_time: float           # Unix timestamp of price trough
    recovery_start: float        # Unix timestamp of first recovery bar

    # Pre-event signal state
    first_warning_time: Optional[float]    # When Adversary first activated before event
    warning_lead_hours: Optional[float]    # Hours before crash_start the warning fired
    oracle_posterior_at_t0: float          # Posterior at crash_start
    oracle_cap_at_t0: float                # Oracle cap at crash_start
    exposure_at_t0: float                  # Actual exposure at crash_start
    haircut_at_t0: float                   # Adversary haircut at crash_start

    # Signal values at crash_start
    turbulence_at_t0: float
    vol_surprise_at_t0: float
    contestation_at_t0: float
    dominant_signal_at_t0: str
    fragility_at_t0: float           # StructuralFragilitySignal at crash_start (0 if unavailable)
    fragility_peak_pre24h: float     # Max fragility in 24h before crash_start

    # Pre-event window (24h before crash_start)
    mean_exposure_pre24h: float
    min_exposure_pre24h: float
    mean_haircut_pre24h: float
    mean_contestation_pre24h: float
    mean_posterior_pre24h: float

    # Adversary behavior
    adversary_active_at_t0: bool     # Was haircut < HAIRCUT_ACTIVE_THRESHOLD at T0?
    adversary_active_pre2h: bool     # Active in the 2h window before T0?
    signal_persistence_bars: int     # Consecutive active bars ending at T0
    max_contestation_pre24h: float   # Peak threat level in the 24h window

    # False signal accounting
    false_warnings_pre7d: int        # Active periods > 2h with no crash in next 24h

    # Oracle vs Adversary attribution
    oracle_contribution: str         # 'primary', 'secondary', 'inactive'
    adversary_contribution: str      # 'primary', 'secondary', 'inactive', 'redundant'

    # Failure taxonomy
    failure_category: str            # A/B/C/D/E/F from taxonomy
    failure_label: str               # Human-readable label


@dataclass
class ForensicsAggregate:
    """Aggregate statistics across all events."""
    n_events: int
    detection_rate: float            # Fraction of events where Adversary was active at T0
    mean_lead_time_hours: float      # Mean warning lead time (detected events only)
    median_lead_time_hours: float
    mean_signal_persistence: float
    mean_exposure_at_t0: float
    mean_exposure_pre24h: float
    false_positive_rate: float       # False warnings per event
    category_counts: Dict[str, int]  # Failure taxonomy distribution
    dominant_signal_distribution: Dict[str, float]  # fraction each signal dominated at T0


# ─────────────────────────────────────────────────────────────
# Crash Event Detection from Price Series
# ─────────────────────────────────────────────────────────────

def detect_crash_events(
    candles: List[Candle5m],
    drawdown_threshold: float = -0.10,
    window_hours: int = 48,
    min_separation_hours: int = 24,
) -> List[Crash72Event]:
    """
    Identify drawdown events exceeding threshold within a rolling window.

    Args:
        candles:               5-min candles sorted ascending
        drawdown_threshold:    Maximum drawdown to trigger (e.g. -0.10 = -10%)
        window_hours:          Rolling window to measure drawdown within
        min_separation_hours:  Minimum time between distinct events (deduplication)

    Returns:
        List[Crash72Event] sorted by start_time

    Algorithm:
        For each candle, look forward `window_hours` and find the peak-to-trough.
        If the drawdown exceeds threshold, record an event from the peak to the trough.
        Advance past the trough before looking for the next event.
    """
    if not candles:
        return []

    window_candles = window_hours * 12        # 5-min candles per hour
    separation_candles = min_separation_hours * 12
    prices = [c.close for c in candles]
    timestamps = [c.timestamp for c in candles]
    n = len(candles)
    events = []
    i = 0

    while i < n - 2:
        window_end = min(i + window_candles, n)
        window_prices = prices[i:window_end]
        peak_local = window_prices[0]
        trough_val = peak_local
        trough_local_idx = 0

        for j, p in enumerate(window_prices):
            if p < trough_val:
                trough_val = p
                trough_local_idx = j

        drawdown = (trough_val - peak_local) / peak_local if peak_local > 0 else 0.0

        if drawdown <= drawdown_threshold:
            trough_global_idx = i + trough_local_idx

            # Find recovery: first bar after trough that exceeds trough + 2%
            recovery_idx = trough_global_idx
            recovery_threshold = trough_val * 1.02
            for k in range(trough_global_idx + 1, min(trough_global_idx + window_candles, n)):
                if prices[k] >= recovery_threshold:
                    recovery_idx = k
                    break

            events.append(Crash72Event(
                start_time=timestamps[i],
                end_time=timestamps[trough_global_idx],
                drawdown_pct=drawdown,
                label=f'detected_{len(events):03d}',
            ))

            # Advance past trough + separation to avoid overlapping events
            i = trough_global_idx + separation_candles
        else:
            i += 1

    return events


def find_trough_and_recovery(
    candles: List[Candle5m],
    event_start: float,
    search_hours: int = 72,
) -> Tuple[float, float]:
    """
    Given an event start time, find the price trough and first recovery timestamp.

    Returns:
        (trough_time, recovery_time) as Unix timestamps
        recovery_time is trough_time if no recovery found within search_hours
    """
    window_candles = search_hours * 12
    timestamps = np.array([c.timestamp for c in candles])
    prices = np.array([c.close for c in candles])

    start_idx = int(np.searchsorted(timestamps, event_start, side='left'))
    end_idx = min(start_idx + window_candles, len(candles))

    if start_idx >= len(candles):
        return event_start, event_start

    window_prices = prices[start_idx:end_idx]
    window_ts = timestamps[start_idx:end_idx]

    trough_local = int(np.argmin(window_prices))
    trough_time = float(window_ts[trough_local])
    trough_price = float(window_prices[trough_local])

    # Recovery: first bar after trough where price > trough * 1.02
    recovery_time = trough_time
    recovery_threshold = trough_price * 1.02
    for k in range(trough_local + 1, len(window_prices)):
        if window_prices[k] >= recovery_threshold:
            recovery_time = float(window_ts[k])
            break

    return trough_time, recovery_time


# ─────────────────────────────────────────────────────────────
# Tick-Level Replay Engine
# ─────────────────────────────────────────────────────────────

class TickReplayer:
    """
    Replays the full backtest tick-by-tick, collecting AdversaryOutput at every tick.

    This is separate from BacktestEngine deliberately — BacktestEngine discards
    per-tick signal values after computing metrics. The ForensicsEngine needs them.

    The replay is intentionally stateless across events: each tick is evaluated
    with the history available up to that point, matching production behavior.
    """

    def __init__(self, oracle_history: List[OracleTick], candles: List[Candle5m]):
        self.oracle_history = sorted(oracle_history, key=lambda t: t.timestamp)
        self.candles = sorted(candles, key=lambda c: c.timestamp)
        self._candle_ts = np.array([c.timestamp for c in self.candles])

    def replay(self, adversary: AdversaryV0) -> List[TickRecord]:
        """
        Run the full replay. Returns one TickRecord per Oracle tick.

        For ticks with insufficient history, signals default to 0 and
        haircut defaults to 1.0 (no Adversary action).
        """
        adversary.cooldown.reset() if adversary.cooldown else None
        min_candles = adversary.vol_surprise_signal.total_candles_needed
        records: List[TickRecord] = []

        # Build price series: nearest candle close to each Oracle tick
        tick_prices = self._build_tick_prices()

        for i, tick in enumerate(self.oracle_history):
            history_slice = self.oracle_history[:i + 1]
            candle_window = self._get_candle_window(tick.timestamp, min_candles + 50)

            if len(candle_window) < min_candles or len(history_slice) < 5:
                # Warmup: no Adversary action yet
                records.append(TickRecord(
                    timestamp=tick.timestamp,
                    price=tick_prices[i],
                    oracle_cap=tick.oracle_cap,
                    posterior=tick.posterior,
                    exposure=tick.oracle_cap,
                    haircut=1.0,
                    contestation=0.0,
                    turbulence=0.0,
                    vol_surprise=0.0,
                    conflict=None,
                    dominant_signal='none',
                    cooldown_active=False,
                    fragility=0.0,
                ))
                continue

            output: AdversaryOutput = adversary.evaluate(history_slice, candle_window, tick.timestamp)
            exposure = tick.oracle_cap * output.haircut

            records.append(TickRecord(
                timestamp=tick.timestamp,
                price=tick_prices[i],
                oracle_cap=tick.oracle_cap,
                posterior=tick.posterior,
                exposure=exposure,
                haircut=output.haircut,
                contestation=output.contestation_score,
                turbulence=output.turbulence,
                vol_surprise=output.vol_surprise,
                conflict=output.conflict,
                dominant_signal=self._dominant_signal(output),
                cooldown_active=bool(output.signals_raw.get('cooldown_active', False)),
                fragility=float(output.signals_raw.get('fragility_score', 0.0)),
            ))

        return records

    def _build_tick_prices(self) -> List[float]:
        prices = []
        for tick in self.oracle_history:
            idx = int(np.searchsorted(self._candle_ts, tick.timestamp, side='right')) - 1
            idx = max(0, min(idx, len(self.candles) - 1))
            prices.append(self.candles[idx].close)
        return prices

    def _get_candle_window(self, end_time: float, num_candles: int) -> List[Candle5m]:
        idx = int(np.searchsorted(self._candle_ts, end_time, side='right'))
        start = max(0, idx - num_candles)
        return self.candles[start:idx]

    @staticmethod
    def _dominant_signal(output: AdversaryOutput) -> str:
        """Which signal contributed the most to contestation this tick."""
        candidates = {
            'turbulence': output.turbulence,
            'vol_surprise': output.vol_surprise,
        }
        if output.conflict is not None:
            candidates['conflict'] = output.conflict

        if not any(v > 0 for v in candidates.values()):
            return 'none'

        return max(candidates, key=candidates.get)


# ─────────────────────────────────────────────────────────────
# Per-Event Forensics
# ─────────────────────────────────────────────────────────────

class EventForensics:
    """
    Computes the full forensic case file for a single crash event,
    given the complete tick trace.
    """

    def __init__(self, tick_records: List[TickRecord]):
        self._records = tick_records
        self._timestamps = np.array([r.timestamp for r in tick_records])

    def analyze(self, event: Crash72Event, event_id: int,
                candles: List[Candle5m]) -> EventCaseFile:
        """
        Build a complete EventCaseFile for the given crash event.
        """
        # Find trough and recovery from candles
        trough_time, recovery_time = find_trough_and_recovery(candles, event.start_time)

        # Tick at T0 (crash_start)
        t0_record = self._record_at(event.start_time)

        # Pre-24h window records
        pre24h = self._records_in_window(
            event.start_time - 86400,
            event.start_time,
        )

        # Pre-2h window records
        pre2h = self._records_in_window(
            event.start_time - 7200,
            event.start_time,
        )

        # First warning: first tick in 24h pre-window where haircut is meaningfully active
        first_warning_time, warning_lead_hours = self._find_first_warning(
            event.start_time, lookback_hours=24
        )

        # Signal persistence at T0: consecutive active bars ending at T0
        persistence = self._persistence_at(event.start_time)

        # False warnings in 7-day pre-event window
        false_warnings = self._count_false_warnings(
            event.start_time - 7 * 86400,
            event.start_time,
        )

        # Oracle vs Adversary attribution
        oracle_contribution, adversary_contribution = self._attribute_protection(
            t0_record, pre24h
        )

        # Failure taxonomy classification
        category, label = self._classify(
            t0_record=t0_record,
            pre24h=pre24h,
            pre2h=pre2h,
            first_warning_time=first_warning_time,
            warning_lead_hours=warning_lead_hours,
            persistence=persistence,
            oracle_contribution=oracle_contribution,
        )

        return EventCaseFile(
            event_id=event_id,
            label=event.label,
            drawdown_pct=event.drawdown_pct,
            crash_start=event.start_time,
            trough_time=trough_time,
            recovery_start=recovery_time,
            first_warning_time=first_warning_time,
            warning_lead_hours=warning_lead_hours,
            oracle_posterior_at_t0=t0_record.posterior if t0_record else 0.0,
            oracle_cap_at_t0=t0_record.oracle_cap if t0_record else 1.0,
            exposure_at_t0=t0_record.exposure if t0_record else 1.0,
            haircut_at_t0=t0_record.haircut if t0_record else 1.0,
            turbulence_at_t0=t0_record.turbulence if t0_record else 0.0,
            vol_surprise_at_t0=t0_record.vol_surprise if t0_record else 0.0,
            contestation_at_t0=t0_record.contestation if t0_record else 0.0,
            dominant_signal_at_t0=t0_record.dominant_signal if t0_record else 'none',
            fragility_at_t0=t0_record.fragility if t0_record else 0.0,
            fragility_peak_pre24h=float(np.max([r.fragility for r in pre24h])) if pre24h else 0.0,
            mean_exposure_pre24h=float(np.mean([r.exposure for r in pre24h])) if pre24h else (t0_record.exposure if t0_record else 1.0),
            min_exposure_pre24h=float(np.min([r.exposure for r in pre24h])) if pre24h else (t0_record.exposure if t0_record else 1.0),
            mean_haircut_pre24h=float(np.mean([r.haircut for r in pre24h])) if pre24h else 1.0,
            mean_contestation_pre24h=float(np.mean([r.contestation for r in pre24h])) if pre24h else 0.0,
            mean_posterior_pre24h=float(np.mean([r.posterior for r in pre24h])) if pre24h else 0.0,
            adversary_active_at_t0=(t0_record.haircut < HAIRCUT_ACTIVE_THRESHOLD) if t0_record else False,
            adversary_active_pre2h=any(r.haircut < HAIRCUT_ACTIVE_THRESHOLD for r in pre2h),
            signal_persistence_bars=persistence,
            max_contestation_pre24h=float(np.max([r.contestation for r in pre24h])) if pre24h else 0.0,
            false_warnings_pre7d=false_warnings,
            oracle_contribution=oracle_contribution,
            adversary_contribution=adversary_contribution,
            failure_category=category,
            failure_label=label,
        )

    # ── Internal helpers ──────────────────────────────────────

    def _record_at(self, target_time: float) -> Optional[TickRecord]:
        """Nearest record to target_time. Returns None if no records."""
        if not self._records:
            return None
        idx = int(np.searchsorted(self._timestamps, target_time, side='right')) - 1
        idx = max(0, min(idx, len(self._records) - 1))
        # Reject if more than 2h away
        if abs(self._records[idx].timestamp - target_time) > 7200:
            return None
        return self._records[idx]

    def _records_in_window(self, start: float, end: float) -> List[TickRecord]:
        """All records with timestamp in [start, end)."""
        return [r for r in self._records if start <= r.timestamp < end]

    def _find_first_warning(
        self, crash_start: float, lookback_hours: int
    ) -> Tuple[Optional[float], Optional[float]]:
        """
        Find the first tick in the lookback window where the Adversary was meaningfully active.

        Returns (first_warning_time, lead_hours).
        Returns (None, None) if no warning was issued.
        """
        window_start = crash_start - lookback_hours * 3600
        window = self._records_in_window(window_start, crash_start)

        for record in window:
            if record.haircut < MEANINGFUL_HAIRCUT:
                lead_hours = (crash_start - record.timestamp) / 3600
                return record.timestamp, lead_hours

        return None, None

    def _persistence_at(self, crash_start: float) -> int:
        """
        Count consecutive active bars immediately before crash_start.
        'Active' means haircut < HAIRCUT_ACTIVE_THRESHOLD.
        """
        # Get all records before crash_start, reverse order
        pre = [r for r in self._records if r.timestamp < crash_start]
        pre.reverse()

        count = 0
        for record in pre:
            if record.haircut < HAIRCUT_ACTIVE_THRESHOLD:
                count += 1
            else:
                break

        return count

    def _count_false_warnings(self, window_start: float, window_end: float) -> int:
        """
        Count distinct 'active periods' in the window that were NOT followed
        by a crash within 24h.

        A 'false warning' is a run of ≥2 consecutive active ticks where
        the next 24h contained no crash (measured against oracle posterior < 0.5).

        Conservative: only counts clear false alarms.
        """
        window = self._records_in_window(window_start, window_end)
        false_count = 0
        in_active_run = False
        run_start_time = None
        run_length = 0

        for i, record in enumerate(window):
            is_active = record.haircut < HAIRCUT_ACTIVE_THRESHOLD

            if is_active and not in_active_run:
                in_active_run = True
                run_start_time = record.timestamp
                run_length = 1

            elif is_active and in_active_run:
                run_length += 1

            elif not is_active and in_active_run:
                # Run ended — check if it was a false alarm
                # False: run lasted ≥2 bars AND posterior at run start was low
                if run_length >= 2:
                    run_start_record = self._record_at(run_start_time)
                    if run_start_record and run_start_record.posterior < FALSE_CALM_MAX_POSTERIOR:
                        false_count += 1

                in_active_run = False
                run_start_time = None
                run_length = 0

        return false_count

    def _attribute_protection(
        self,
        t0_record: Optional[TickRecord],
        pre24h: List[TickRecord],
    ) -> Tuple[str, str]:
        """
        Determine whether protection at this event came primarily from:
          - Oracle (cap was already low before Adversary acted)
          - Adversary (haircut provided meaningful additional reduction)
          - Both
          - Neither

        Returns (oracle_contribution, adversary_contribution)
        Each is: 'primary', 'secondary', 'redundant', or 'inactive'
        """
        if not t0_record:
            return 'inactive', 'inactive'

        # Oracle contribution: how much did the cap alone reduce exposure?
        # High if oracle_cap was already well below 1.0
        oracle_cap_reduction = 1.0 - t0_record.oracle_cap
        oracle_active = oracle_cap_reduction > 0.15

        # Adversary contribution: how much additional reduction beyond oracle_cap?
        adversary_reduction = t0_record.oracle_cap - t0_record.exposure
        adversary_active = adversary_reduction > 0.05

        # Pre-24h mean to assess sustained vs point-in-time
        mean_cap = np.mean([r.oracle_cap for r in pre24h]) if pre24h else t0_record.oracle_cap
        mean_exposure = np.mean([r.exposure for r in pre24h]) if pre24h else t0_record.exposure
        sustained_adversary = (mean_cap - mean_exposure) > 0.05

        # Attribution logic
        if oracle_active and adversary_active:
            oracle_contribution = 'primary' if oracle_cap_reduction > adversary_reduction else 'secondary'
            adversary_contribution = 'secondary' if oracle_cap_reduction > adversary_reduction else 'primary'
        elif oracle_active and not adversary_active:
            oracle_contribution = 'primary'
            adversary_contribution = 'redundant'
        elif not oracle_active and adversary_active:
            oracle_contribution = 'inactive'
            adversary_contribution = 'primary'
        else:
            oracle_contribution = 'inactive'
            adversary_contribution = 'inactive'

        return oracle_contribution, adversary_contribution

    def _classify(
        self,
        t0_record: Optional[TickRecord],
        pre24h: List[TickRecord],
        pre2h: List[TickRecord],
        first_warning_time: Optional[float],
        warning_lead_hours: Optional[float],
        persistence: int,
        oracle_contribution: str,
    ) -> Tuple[str, str]:
        """
        Assign a failure taxonomy category to this event.
        Returns (category_letter, full_label).

        Priority order for assignment:
          F  Good skepticism (Adversary worked well)
          E  Oracle already sufficient (Adversary redundant)
          A  Transition without persistence (activated then died)
          C  False calm miss (posterior low, missed entirely)
          B  Fragility blindness (moderate posterior, still missed)
          D  Chronic paranoia (active too broadly — checked at aggregate level, not per-event)
        """
        if not t0_record:
            return 'B', FAILURE_TAXONOMY['B']

        active_at_t0 = t0_record.haircut < HAIRCUT_ACTIVE_THRESHOLD
        early_warning = (warning_lead_hours is not None and
                         warning_lead_hours >= EARLY_WARNING_HOURS)
        persistent = persistence >= PERSISTENCE_MIN_BARS
        oracle_primary = oracle_contribution == 'primary'
        posterior_was_low = t0_record.posterior < FALSE_CALM_MAX_POSTERIOR

        # F — Good skepticism: early, persistent warning, meaningful haircut
        if active_at_t0 and early_warning and persistent and not oracle_primary:
            return 'F', FAILURE_TAXONOMY['F']

        # F — also good if active in pre2h with meaningful reduction
        mean_pre2h_haircut = np.mean([r.haircut for r in pre2h]) if pre2h else 1.0
        if mean_pre2h_haircut < MEANINGFUL_HAIRCUT and active_at_t0:
            return 'F', FAILURE_TAXONOMY['F']

        # E — Oracle already sufficient: oracle cap was already doing the work
        if oracle_primary and not active_at_t0:
            return 'E', FAILURE_TAXONOMY['E']

        # A — Transition without persistence: warned but didn't hold
        if first_warning_time is not None and not active_at_t0:
            return 'A', FAILURE_TAXONOMY['A']

        # C — False calm miss: posterior was low, no warning at all
        if not active_at_t0 and posterior_was_low:
            return 'C', FAILURE_TAXONOMY['C']

        # B — Fragility blindness: posterior elevated but Adversary still missed
        if not active_at_t0:
            return 'B', FAILURE_TAXONOMY['B']

        # Active but no early warning (reacted at T0 or after)
        return 'A', FAILURE_TAXONOMY['A']


# ─────────────────────────────────────────────────────────────
# Main Forensics Engine
# ─────────────────────────────────────────────────────────────

class ForensicsEngine:
    """
    Orchestrates the full forensics pipeline.

    Usage:
        engine = ForensicsEngine(oracle_history, candles, crash_events)
        engine.run(adversary)
        engine.write_csv('events_report.csv')
        engine.write_json('event_summary.json')
        engine.print_summary()
    """

    def __init__(
        self,
        oracle_history: List[OracleTick],
        candles: List[Candle5m],
        crash_events: List[Crash72Event],
    ):
        self.oracle_history = sorted(oracle_history, key=lambda t: t.timestamp)
        self.candles = sorted(candles, key=lambda c: c.timestamp)
        self.crash_events = sorted(crash_events, key=lambda e: e.start_time)

        self._tick_records: List[TickRecord] = []
        self._case_files: List[EventCaseFile] = []
        self._aggregate: Optional[ForensicsAggregate] = None
        self._has_run = False

    def run(self, adversary: AdversaryV0) -> 'ForensicsEngine':
        """
        Execute full forensics pipeline.
        Step 1: Replay all ticks, collecting AdversaryOutput at each.
        Step 2: For each crash event, build a forensic case file.
        Step 3: Compute aggregate statistics.
        Returns self for chaining.
        """
        print(f"[ForensicsEngine] Replaying {len(self.oracle_history)} ticks "
              f"against {len(self.crash_events)} crash events...")

        # Step 1: Tick-level replay
        replayer = TickReplayer(self.oracle_history, self.candles)
        self._tick_records = replayer.replay(adversary)
        print(f"[ForensicsEngine] Replay complete. {len(self._tick_records)} tick records.")

        # Filter crash events to those within data range
        oracle_start = self.oracle_history[0].timestamp if self.oracle_history else 0
        oracle_end = self.oracle_history[-1].timestamp if self.oracle_history else 0
        valid_events = [
            e for e in self.crash_events
            if oracle_start <= e.start_time <= oracle_end
        ]
        skipped = len(self.crash_events) - len(valid_events)
        if skipped:
            warnings.warn(f"[ForensicsEngine] {skipped} crash events outside Oracle range — skipped.")

        # Step 2: Per-event case files
        forensics = EventForensics(self._tick_records)
        self._case_files = []
        for i, event in enumerate(valid_events):
            case = forensics.analyze(event, event_id=i, candles=self.candles)
            self._case_files.append(case)

        print(f"[ForensicsEngine] {len(self._case_files)} case files built.")

        # Step 3: Aggregate
        self._aggregate = self._compute_aggregate()
        self._has_run = True

        return self

    def write_csv(self, filepath: str) -> 'ForensicsEngine':
        """Write per-event report to CSV. One row per crash event."""
        self._require_run()

        if not self._case_files:
            warnings.warn("[ForensicsEngine] No case files to write.")
            return self

        # Flatten case files to dicts
        rows = []
        for cf in self._case_files:
            row = {
                'event_id': cf.event_id,
                'label': cf.label,
                'drawdown_pct': f"{cf.drawdown_pct:.4f}",
                'crash_start': cf.crash_start,
                'trough_time': cf.trough_time,
                'recovery_start': cf.recovery_start,
                'first_warning_time': cf.first_warning_time if cf.first_warning_time else '',
                'warning_lead_hours': f"{cf.warning_lead_hours:.2f}" if cf.warning_lead_hours is not None else '',
                'oracle_posterior_at_t0': f"{cf.oracle_posterior_at_t0:.4f}",
                'oracle_cap_at_t0': f"{cf.oracle_cap_at_t0:.4f}",
                'exposure_at_t0': f"{cf.exposure_at_t0:.4f}",
                'haircut_at_t0': f"{cf.haircut_at_t0:.4f}",
                'turbulence_at_t0': f"{cf.turbulence_at_t0:.4f}",
                'vol_surprise_at_t0': f"{cf.vol_surprise_at_t0:.4f}",
                'contestation_at_t0': f"{cf.contestation_at_t0:.4f}",
                'dominant_signal_at_t0': cf.dominant_signal_at_t0,
                'fragility_at_t0': f"{cf.fragility_at_t0:.4f}",
                'fragility_peak_pre24h': f"{cf.fragility_peak_pre24h:.4f}",
                'mean_exposure_pre24h': f"{cf.mean_exposure_pre24h:.4f}",
                'min_exposure_pre24h': f"{cf.min_exposure_pre24h:.4f}",
                'mean_haircut_pre24h': f"{cf.mean_haircut_pre24h:.4f}",
                'mean_contestation_pre24h': f"{cf.mean_contestation_pre24h:.4f}",
                'mean_posterior_pre24h': f"{cf.mean_posterior_pre24h:.4f}",
                'adversary_active_at_t0': cf.adversary_active_at_t0,
                'adversary_active_pre2h': cf.adversary_active_pre2h,
                'signal_persistence_bars': cf.signal_persistence_bars,
                'max_contestation_pre24h': f"{cf.max_contestation_pre24h:.4f}",
                'false_warnings_pre7d': cf.false_warnings_pre7d,
                'oracle_contribution': cf.oracle_contribution,
                'adversary_contribution': cf.adversary_contribution,
                'failure_category': cf.failure_category,
                'failure_label': cf.failure_label,
            }
            rows.append(row)

        with open(filepath, 'w', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
            writer.writeheader()
            writer.writerows(rows)

        print(f"[ForensicsEngine] CSV written: {filepath}")
        return self

    def write_json(self, filepath: str) -> 'ForensicsEngine':
        """Write aggregate summary + all case files to JSON."""
        self._require_run()

        output = {
            'aggregate': self._aggregate_to_dict(),
            'events': [],
        }

        for cf in self._case_files:
            output['events'].append({
                'event_id': cf.event_id,
                'label': cf.label,
                'drawdown_pct': round(cf.drawdown_pct, 4),
                'crash_start': cf.crash_start,
                'trough_time': cf.trough_time,
                'recovery_start': cf.recovery_start,
                'warning': {
                    'first_warning_time': cf.first_warning_time,
                    'warning_lead_hours': round(cf.warning_lead_hours, 2) if cf.warning_lead_hours is not None else None,
                    'adversary_active_at_t0': cf.adversary_active_at_t0,
                    'adversary_active_pre2h': cf.adversary_active_pre2h,
                    'signal_persistence_bars': cf.signal_persistence_bars,
                },
                'signals_at_t0': {
                    'oracle_posterior': round(cf.oracle_posterior_at_t0, 4),
                    'oracle_cap': round(cf.oracle_cap_at_t0, 4),
                    'exposure': round(cf.exposure_at_t0, 4),
                    'haircut': round(cf.haircut_at_t0, 4),
                    'turbulence': round(cf.turbulence_at_t0, 4),
                    'vol_surprise': round(cf.vol_surprise_at_t0, 4),
                    'contestation': round(cf.contestation_at_t0, 4),
                    'dominant_signal': cf.dominant_signal_at_t0,
                    'fragility': round(cf.fragility_at_t0, 4),
                    'fragility_peak_pre24h': round(cf.fragility_peak_pre24h, 4),
                },
                'pre24h_window': {
                    'mean_exposure': round(cf.mean_exposure_pre24h, 4),
                    'min_exposure': round(cf.min_exposure_pre24h, 4),
                    'mean_haircut': round(cf.mean_haircut_pre24h, 4),
                    'mean_contestation': round(cf.mean_contestation_pre24h, 4),
                    'max_contestation': round(cf.max_contestation_pre24h, 4),
                    'mean_posterior': round(cf.mean_posterior_pre24h, 4),
                },
                'attribution': {
                    'oracle_contribution': cf.oracle_contribution,
                    'adversary_contribution': cf.adversary_contribution,
                    'false_warnings_pre7d': cf.false_warnings_pre7d,
                },
                'taxonomy': {
                    'failure_category': cf.failure_category,
                    'failure_label': cf.failure_label,
                },
            })

        with open(filepath, 'w') as f:
            json.dump(output, f, indent=2)

        print(f"[ForensicsEngine] JSON written: {filepath}")
        return self

    def print_summary(self) -> 'ForensicsEngine':
        """Print a human-readable summary to stdout."""
        self._require_run()
        agg = self._aggregate

        print()
        print("=" * 72)
        print("EVENT FORENSICS SUMMARY")
        print("=" * 72)
        print(f"  Events analyzed:       {agg.n_events}")
        print(f"  Detection rate:        {agg.detection_rate:.1%}  (Adversary active at T0)")
        print(f"  Mean lead time:        {agg.mean_lead_time_hours:.1f}h  (detected events only)")
        print(f"  Median lead time:      {agg.median_lead_time_hours:.1f}h")
        print(f"  Mean persistence:      {agg.mean_signal_persistence:.1f} bars")
        print(f"  Mean exposure at T0:   {agg.mean_exposure_at_t0:.4f}")
        print(f"  Mean exposure pre-24h: {agg.mean_exposure_pre24h:.4f}")
        print(f"  False positives/event: {agg.false_positive_rate:.2f}")
        print()
        print("  Failure Taxonomy Distribution:")
        for cat, count in sorted(agg.category_counts.items()):
            label = FAILURE_TAXONOMY.get(cat, cat)
            pct = count / max(1, agg.n_events)
            bar = '█' * count + '░' * (agg.n_events - count)
            print(f"    {cat} [{label:35s}]  {count:2d}  {pct:4.0%}  {bar}")
        print()
        print("  Dominant Signal at T0:")
        for sig, frac in sorted(agg.dominant_signal_distribution.items(), key=lambda x: -x[1]):
            print(f"    {sig:15s}  {frac:.1%}")
        print()

        # Per-event table
        print("  Per-Event Case Files:")
        print(f"  {'ID':>3}  {'Label':20s}  {'DD%':>6}  {'Lead':>6}  {'Cat'}  {'Adversary'}  {'Dominant'}")
        print(f"  {'─'*3}  {'─'*20}  {'─'*6}  {'─'*6}  {'─'*3}  {'─'*9}  {'─'*12}")
        for cf in self._case_files:
            lead_str = f"{cf.warning_lead_hours:.1f}h" if cf.warning_lead_hours is not None else "  ——"
            active_str = "✓ active" if cf.adversary_active_at_t0 else "✗ silent"
            print(
                f"  {cf.event_id:>3}  {cf.label[:20]:20s}  "
                f"{cf.drawdown_pct:+6.1%}  {lead_str:>6}  "
                f"  {cf.failure_category}  {active_str}  {cf.dominant_signal_at_t0}"
            )

        print()
        print("=" * 72)
        return self

    # ── Private helpers ───────────────────────────────────────

    def _require_run(self):
        if not self._has_run:
            raise RuntimeError("Call run(adversary) before writing output.")

    def _compute_aggregate(self) -> ForensicsAggregate:
        if not self._case_files:
            return ForensicsAggregate(
                n_events=0, detection_rate=0.0,
                mean_lead_time_hours=0.0, median_lead_time_hours=0.0,
                mean_signal_persistence=0.0, mean_exposure_at_t0=0.0,
                mean_exposure_pre24h=0.0, false_positive_rate=0.0,
                category_counts={}, dominant_signal_distribution={},
            )

        n = len(self._case_files)
        detected = [cf for cf in self._case_files if cf.adversary_active_at_t0]
        lead_times = [cf.warning_lead_hours for cf in self._case_files
                      if cf.warning_lead_hours is not None]

        category_counts: Dict[str, int] = {}
        for cf in self._case_files:
            category_counts[cf.failure_category] = category_counts.get(cf.failure_category, 0) + 1

        dominant_counts: Dict[str, int] = {}
        for cf in self._case_files:
            sig = cf.dominant_signal_at_t0
            dominant_counts[sig] = dominant_counts.get(sig, 0) + 1
        dominant_dist = {k: v / n for k, v in dominant_counts.items()}

        total_false = sum(cf.false_warnings_pre7d for cf in self._case_files)

        return ForensicsAggregate(
            n_events=n,
            detection_rate=len(detected) / n,
            mean_lead_time_hours=float(np.mean(lead_times)) if lead_times else 0.0,
            median_lead_time_hours=float(np.median(lead_times)) if lead_times else 0.0,
            mean_signal_persistence=float(np.mean([cf.signal_persistence_bars for cf in self._case_files])),
            mean_exposure_at_t0=float(np.mean([cf.exposure_at_t0 for cf in self._case_files])),
            mean_exposure_pre24h=float(np.mean([cf.mean_exposure_pre24h for cf in self._case_files])),
            false_positive_rate=total_false / n,
            category_counts=category_counts,
            dominant_signal_distribution=dominant_dist,
        )

    def _aggregate_to_dict(self) -> dict:
        agg = self._aggregate
        return {
            'n_events': agg.n_events,
            'detection_rate': round(agg.detection_rate, 4),
            'mean_lead_time_hours': round(agg.mean_lead_time_hours, 2),
            'median_lead_time_hours': round(agg.median_lead_time_hours, 2),
            'mean_signal_persistence_bars': round(agg.mean_signal_persistence, 2),
            'mean_exposure_at_t0': round(agg.mean_exposure_at_t0, 4),
            'mean_exposure_pre24h': round(agg.mean_exposure_pre24h, 4),
            'false_positive_rate_per_event': round(agg.false_positive_rate, 4),
            'failure_taxonomy': {
                cat: {
                    'count': count,
                    'fraction': round(count / max(1, agg.n_events), 4),
                    'label': FAILURE_TAXONOMY.get(cat, cat),
                }
                for cat, count in agg.category_counts.items()
            },
            'dominant_signal_distribution': {
                k: round(v, 4) for k, v in agg.dominant_signal_distribution.items()
            },
        }

    # ── Public accessors ──────────────────────────────────────

    @property
    def case_files(self) -> List[EventCaseFile]:
        self._require_run()
        return self._case_files

    @property
    def tick_records(self) -> List[TickRecord]:
        self._require_run()
        return self._tick_records

    @property
    def aggregate(self) -> Optional[ForensicsAggregate]:
        return self._aggregate
