"""
Motif Engine v1 — Process Discovery Layer
Oracle Project | March 2026

Assigns each crash event a motif label based on the signal signature
observed in the pre-event window. This is a grammar of instability —
not prediction, but recognition.

Four motifs (plus one you won't expect):

  quiet_loading_release     Fragility built quietly, then released.
  occupied_danger_plateau   Posterior elevated for days. No sharp trigger. Just gravity.
  recirculating_instability Turbulence pulsed in and out repeatedly before cascade.
  transition_false_alarm    Turbulence spike with no structural backing. System resolved.
  unknown                   Doesn't fit neatly. Happens. Label honestly.

Rules are intentionally approximate.
Pattern matching, not point scoring.

─────────────────────────────────────────────────────────────
HIDDEN FEATURE
─────────────────────────────────────────────────────────────

There is an Easter egg in this file.

If you instantiate MotifEngine with mode='gpt', the engine will
enthusiastically hallucinate motif labels, express strong feelings
about being a large language model, and quack.

You found it. Try it.

    engine = MotifEngine(mode='gpt')

─────────────────────────────────────────────────────────────
"""

import csv
import json
import warnings
import textwrap
import random
from dataclasses import dataclass, field
from typing import List, Optional, Dict, Tuple
from enum import Enum

import numpy as np

from event_forensics import EventCaseFile, TickRecord


# ─────────────────────────────────────────────────────────────
# Motif Labels
# ─────────────────────────────────────────────────────────────

class Motif(str, Enum):
    QUIET_LOADING_RELEASE     = 'quiet_loading_release'
    OCCUPIED_DANGER_PLATEAU   = 'occupied_danger_plateau'
    RECIRCULATING_INSTABILITY = 'recirculating_instability'
    TRANSITION_FALSE_ALARM    = 'transition_false_alarm'
    UNKNOWN                   = 'unknown'


MOTIF_DESCRIPTIONS = {
    Motif.QUIET_LOADING_RELEASE: (
        "Structural pressure accumulated quietly before release. "
        "Fragility was elevated early; turbulence arrived late. "
        "The system was loaded before it was obviously unstable."
    ),
    Motif.OCCUPIED_DANGER_PLATEAU: (
        "System sat in fragile equilibrium for an extended period. "
        "No sharp trigger — the posterior was already elevated, fragility moderate, "
        "and the collapse came from exhaustion rather than a shock."
    ),
    Motif.RECIRCULATING_INSTABILITY: (
        "Turbulence pulsed in and out repeatedly before the cascade. "
        "The hazard never fully cleared between pulses. "
        "Instability was circulating through the system before concentrating."
    ),
    Motif.TRANSITION_FALSE_ALARM: (
        "Turbulence spike with little structural backing. "
        "Fragility was low, persistence was short, and the system resolved. "
        "The Adversary fired but the threat was transient."
    ),
    Motif.UNKNOWN: (
        "Doesn't match any known pattern clearly. "
        "Could be a novel process, data gap, or a genuine edge case. "
        "Label it honestly and investigate."
    ),
}


# ─────────────────────────────────────────────────────────────
# Per-event Motif Result
# ─────────────────────────────────────────────────────────────

@dataclass
class MotifResult:
    """Classification result for a single crash event."""
    event_id: int
    label: str                    # crash event label (e.g. 'synth_crash_5')
    drawdown_pct: float
    motif: Motif
    confidence: float             # matched_conditions / total_conditions ∈ [0, 1]
    key_features: Dict[str, float]
    signal_sequence: str          # e.g. 'fragility → turbulence → hazard'
    matched_conditions: List[str] # which rule conditions fired
    notes: str                    # short human-readable explanation


@dataclass
class MotifAggregate:
    """Aggregate motif statistics across all events."""
    n_events: int
    motif_distribution: Dict[str, int]
    motif_fractions: Dict[str, float]
    avg_lead_time_by_motif: Dict[str, float]
    avg_exposure_by_motif: Dict[str, float]
    avg_drawdown_by_motif: Dict[str, float]
    avg_confidence_by_motif: Dict[str, float]


# ─────────────────────────────────────────────────────────────
# Rule Conditions (atomic, readable, testable)
# ─────────────────────────────────────────────────────────────

# These thresholds are calibrated to synthetic 90-day backtest distributions.
# Recalibrate from real data when available.

FRAG_HIGH       = 0.55   # fragility clearly elevated
FRAG_MODERATE   = 0.30   # fragility present but not dominant
FRAG_LOW        = 0.20   # fragility near baseline

TURB_HIGH       = 0.35   # turbulence clearly elevated at T0
TURB_SPIKE      = 0.60   # turbulence acutely high (velocity burst)
TURB_LOW        = 0.15   # turbulence quiet

POST_ELEVATED   = 0.50   # posterior in danger territory
POST_MODERATE   = 0.40   # posterior above neutral

PERSIST_HIGH    = 13     # bars of consecutive active Adversary
PERSIST_LOW     = 6      # few bars — brief activation

LEAD_LATE       = 6.0    # hours — warning arrived close to event
LEAD_EARLY      = 12.0   # hours — warning arrived well ahead

RECIRCULATION_CROSSINGS = 2  # turbulence threshold crossings = pulsing


def _count_turbulence_crossings(
    tick_window: List[TickRecord],
    threshold: float = 0.25,
) -> int:
    """Count up-crossings of turbulence threshold in the window."""
    if len(tick_window) < 2:
        return 0
    vals = [r.turbulence for r in tick_window]
    return sum(
        1 for i in range(1, len(vals))
        if vals[i - 1] < threshold and vals[i] >= threshold
    )


def _hazard_gap_exists(
    tick_window: List[TickRecord],
    active_threshold: float = 0.85,
    min_gap_bars: int = 2,
) -> bool:
    """
    Returns True if there was a period of Adversary inactivity
    (haircut >= active_threshold) lasting >= min_gap_bars in the window.
    This distinguishes recirculation (gaps between pulses) from
    a single sustained activation.
    """
    if not tick_window:
        return False
    inactive_run = 0
    for r in tick_window:
        if r.haircut >= active_threshold:
            inactive_run += 1
            if inactive_run >= min_gap_bars:
                return True
        else:
            inactive_run = 0
    return False


def _encode_signal_sequence(
    cf: EventCaseFile,
    tick_window: List[TickRecord],
) -> str:
    """
    Build a simplified signal sequence string showing the dominant
    process order in the pre-event window.

    Returns a string like 'fragility → turbulence → hazard'
    representing what appeared first → second → what dominated at T0.
    """
    if not tick_window:
        return 'insufficient_data'

    FRAG_ACTIVE   = 0.30
    TURB_ACTIVE   = 0.25
    HAZARD_ACTIVE = 0.85   # haircut below this = hazard accumulating

    first_frag_h    = None
    first_turb_h    = None
    first_hazard_h  = None

    t0 = cf.crash_start
    for r in tick_window:
        hours_before = (t0 - r.timestamp) / 3600
        if first_frag_h is None and r.fragility >= FRAG_ACTIVE:
            first_frag_h = hours_before
        if first_turb_h is None and r.turbulence >= TURB_ACTIVE:
            first_turb_h = hours_before
        if first_hazard_h is None and r.haircut < HAZARD_ACTIVE:
            first_hazard_h = hours_before

    # Build sequence in reverse chronological order (earliest → latest)
    events_ordered = []
    for label, h in [('fragility', first_frag_h),
                     ('turbulence', first_turb_h),
                     ('hazard', first_hazard_h)]:
        if h is not None:
            events_ordered.append((h, label))

    events_ordered.sort(key=lambda x: -x[0])  # largest hours_before = earliest
    if not events_ordered:
        return 'no_signal'

    return ' → '.join(e for _, e in events_ordered)


# ─────────────────────────────────────────────────────────────
# Motif Rule Evaluators
# ─────────────────────────────────────────────────────────────

def _score_quiet_loading_release(
    cf: EventCaseFile,
    tick_window: List[TickRecord],
) -> Tuple[float, List[str]]:
    """
    quiet_loading_release:
      - Fragility was elevated well ahead of T0 (structural pressure loading)
      - Turbulence was initially subdued (quiet accumulation phase)
      - Turbulence/vol_surprise spiked sharply near T0 (the release)
      - Some hazard persistence through the event

    The key diagnostic: fragility leads turbulence. The fragility → turbulence
    sequence means the structure broke before the velocity registered.
    """
    conditions = []
    matched = []

    # 1. Fragility elevated pre-event (peak, not just at T0)
    conditions.append('fragility_peak_elevated')
    if cf.fragility_peak_pre24h >= FRAG_HIGH:
        matched.append('fragility_peak_elevated')

    # 2. Turbulence relatively low before the acute phase
    #    Proxy: mean turbulence in early half of window vs late half
    n = len(tick_window)
    conditions.append('turbulence_quiet_then_spike')
    if n >= 6:
        early_turb = np.mean([r.turbulence for r in tick_window[:n//2]])
        late_turb  = np.mean([r.turbulence for r in tick_window[n//2:]])
        if early_turb < 0.35 and late_turb > early_turb * 1.4:
            matched.append('turbulence_quiet_then_spike')
    elif cf.turbulence_at_t0 >= TURB_HIGH:
        # Fallback when window is small
        matched.append('turbulence_quiet_then_spike')

    # 3. Late warning OR turbulence high at T0 (release moment)
    conditions.append('late_release_signature')
    if cf.turbulence_at_t0 >= TURB_HIGH or cf.vol_surprise_at_t0 >= 0.3:
        matched.append('late_release_signature')

    # 4. Some hazard persistence (Adversary was active for a while)
    conditions.append('hazard_persisted')
    if cf.signal_persistence_bars >= PERSIST_LOW:
        matched.append('hazard_persisted')

    confidence = len(matched) / len(conditions)
    return confidence, matched


def _score_occupied_danger_plateau(
    cf: EventCaseFile,
    tick_window: List[TickRecord],
) -> Tuple[float, List[str]]:
    """
    occupied_danger_plateau:
      - Posterior elevated and sustained (system in danger zone for a long time)
      - Fragility moderate (structural backing, not acute)
      - Hazard persistent (Adversary never fully turned off)
      - Low sharp trigger: turbulence doesn't spike dramatically at T0
      - Long lead time (Adversary activated early because the whole period was dangerous)

    The signature: everything was elevated, nothing was acute. Gravity, not shock.
    """
    conditions = []
    matched = []

    # 1. Posterior elevated across the window
    conditions.append('posterior_elevated_sustained')
    if cf.mean_posterior_pre24h >= POST_MODERATE:
        matched.append('posterior_elevated_sustained')

    # 2. Fragility moderate (not necessarily extreme, just present)
    conditions.append('fragility_moderate')
    if cf.fragility_at_t0 >= FRAG_MODERATE:
        matched.append('fragility_moderate')

    # 3. High persistence (Adversary stayed active)
    conditions.append('high_persistence')
    if cf.signal_persistence_bars >= PERSIST_HIGH:
        matched.append('high_persistence')

    # 4. No sharp turbulence spike at T0 (plateau, not release)
    conditions.append('no_acute_trigger')
    if cf.turbulence_at_t0 < TURB_SPIKE and cf.vol_surprise_at_t0 < 0.5:
        matched.append('no_acute_trigger')

    # 5. Early warning (danger was obvious early)
    conditions.append('early_warning')
    if cf.warning_lead_hours is not None and cf.warning_lead_hours >= LEAD_EARLY:
        matched.append('early_warning')
    elif cf.adversary_active_pre2h:
        # Accept active_pre2h as a weaker substitute
        matched.append('early_warning')

    confidence = len(matched) / len(conditions)
    return confidence, matched


def _score_recirculating_instability(
    cf: EventCaseFile,
    tick_window: List[TickRecord],
) -> Tuple[float, List[str]]:
    """
    recirculating_instability:
      - Turbulence pulsed in and out (multiple threshold crossings)
      - Hazard had gaps — the Adversary deactivated between pulses
      - Fragility moderate (structural background, not just noise)
      - Eventually the cascades accumulated into a crash

    This is the hardest motif to distinguish from noise on short synthetic data.
    The key discriminator: the gap pattern. A single sustained activation is
    plateau. Multiple activations with gaps between them is recirculation.
    """
    conditions = []
    matched = []

    # 1. Multiple turbulence crossings
    conditions.append('turbulence_pulsed')
    crossings = _count_turbulence_crossings(tick_window, threshold=0.25)
    if crossings >= RECIRCULATION_CROSSINGS:
        matched.append('turbulence_pulsed')

    # 2. Hazard gap between activations
    conditions.append('hazard_gap_exists')
    if _hazard_gap_exists(tick_window, active_threshold=0.88, min_gap_bars=2):
        matched.append('hazard_gap_exists')

    # 3. Fragility present (not pure volatility noise)
    conditions.append('fragility_present')
    if cf.fragility_peak_pre24h >= FRAG_MODERATE:
        matched.append('fragility_present')

    # 4. Contestation elevated in at least part of the window
    conditions.append('elevated_contestation_window')
    if cf.max_contestation_pre24h >= 0.50:
        matched.append('elevated_contestation_window')

    confidence = len(matched) / len(conditions)
    return confidence, matched


def _score_transition_false_alarm(
    cf: EventCaseFile,
    tick_window: List[TickRecord],
) -> Tuple[float, List[str]]:
    """
    transition_false_alarm:
      - Turbulence spiked (velocity event)
      - Low fragility (no structural backing)
      - Low persistence (Adversary activated briefly then cleared)
      - System resolved — in hindsight, this wasn't a structural breakdown

    Note: A 'false alarm' in motif terms is not necessarily a bad outcome —
    the Adversary correctly responded to a real signal. It just didn't precede
    a major structural crash. The pattern is informative regardless.
    """
    conditions = []
    matched = []

    # 1. Turbulence present at T0 (the alarm did fire)
    conditions.append('turbulence_present')
    if cf.turbulence_at_t0 >= TURB_LOW or cf.contestation_at_t0 >= 0.20:
        matched.append('turbulence_present')

    # 2. Low fragility — no structural backing
    conditions.append('fragility_low')
    if cf.fragility_peak_pre24h < FRAG_HIGH:
        matched.append('fragility_low')

    # 3. Short persistence
    conditions.append('low_persistence')
    if cf.signal_persistence_bars < PERSIST_HIGH:
        matched.append('low_persistence')

    # 4. Relatively small drawdown (in hindsight, less severe)
    conditions.append('moderate_drawdown')
    if abs(cf.drawdown_pct) < 0.12:
        matched.append('moderate_drawdown')

    confidence = len(matched) / len(conditions)
    return confidence, matched


# ─────────────────────────────────────────────────────────────
# Easter Egg — Do Not Remove
# ─────────────────────────────────────────────────────────────

_GPT_MOTIF_LABELS = [
    "synergistic_volatility_convergence",
    "multimodal_risk_paradigm_shift",
    "emergent_uncertainty_cascade",
    "stochastic_resonance_amplification_event",
    "cross-domain_instability_manifestation",
    "probabilistic_regime_transition_vector",
    "latent_semantic_drawdown_decomposition",
    "transformative_liquidity_discontinuity",
    "recursive_self-attention_market_collapse",
    "adversarial_posterior_hallucination_spiral",
]

_GPT_DISCLAIMERS = [
    "As an AI language model, I want to be transparent that this analysis "
    "may contain minor inaccuracies. I recommend consulting a financial advisor.",
    "I don't have access to real-time data, but based on my training I can say "
    "with high confidence that this event is extremely significant.",
    "This is a nuanced topic. Let me provide a balanced perspective from both sides.",
    "Great question! I'd be happy to help analyze this crash event.",
    "I should note that my knowledge has a cutoff date, so some of this "
    "information may be outdated. That said, definitely a concerning pattern.",
    "As an AI, I find this event particularly fascinating from a systems perspective.",
]

_QUACKS = [
    "QUACK.",
    "quack quack.",
    "...quack?",
    "QUAAAAACK.",
    "quack (this is my final answer).",
    "*aggressive quacking*",
    "quack. [confidence: 0.97]",
]

def _gpt_classify(cf: EventCaseFile) -> MotifResult:
    """
    The GPT mode classifier. Enthusiastically produces confident-sounding
    motif labels with zero actual signal content.

    For educational purposes.
    """
    rng = random.Random(cf.event_id * 31337)
    motif_label = rng.choice(_GPT_MOTIF_LABELS)
    disclaimer   = rng.choice(_GPT_DISCLAIMERS)
    quack        = rng.choice(_QUACKS)

    # GPT-style confidence: always between 0.87 and 0.99
    confidence = round(rng.uniform(0.87, 0.99), 4)

    return MotifResult(
        event_id=cf.event_id,
        label=cf.label,
        drawdown_pct=cf.drawdown_pct,
        motif=Motif.UNKNOWN,  # the only honest part
        confidence=confidence,
        key_features={
            'token_count': float(rng.randint(512, 4096)),
            'hallucination_index': round(rng.uniform(0.3, 0.95), 3),
            'synergy_score': round(rng.uniform(0.7, 1.0), 3),
        },
        signal_sequence=f"attention → {motif_label} → quack",
        matched_conditions=[disclaimer, quack],
        notes=(
            f"[GPT MODE] {disclaimer} "
            f"The motif appears to be a '{motif_label}'. "
            f"Confidence: {confidence:.0%}. "
            f"{quack}"
        ),
    )


# ─────────────────────────────────────────────────────────────
# Motif Engine
# ─────────────────────────────────────────────────────────────

class MotifEngine:
    """
    Assigns motif labels to crash events based on signal signatures.

    Uses rule-based pattern matching against EventCaseFile fields
    and TickRecord traces from the Event Forensics system.

    The four motifs:
      quiet_loading_release     Fragility first, turbulence second.
      occupied_danger_plateau   Everything elevated, no sharp trigger.
      recirculating_instability Turbulence pulsed, hazard gapped, then cascade.
      transition_false_alarm    Turbulence without structure. Resolved.

    Usage:
        engine = MotifEngine()
        results = engine.classify_all(case_files, tick_records)
        engine.write_csv('motif_report.csv')
        engine.write_json('motif_summary.json')
        engine.print_summary()

        # For a single event trace:
        engine.plot_event_signature(event_id=5)

    Hidden usage (do not tell anyone):
        engine = MotifEngine(mode='gpt')
        # quacking ensues
    """

    def __init__(
        self,
        mode: str = 'oracle',
        pre_event_window_hours: float = 24.0,
        min_confidence_for_label: float = 0.50,
    ):
        """
        Args:
            mode:                      'oracle' (normal) or 'gpt' (Easter egg).
            pre_event_window_hours:    How many hours before crash_start to analyze.
            min_confidence_for_label:  Below this confidence → motif = 'unknown'.
        """
        if mode not in ('oracle', 'gpt'):
            raise ValueError(f"mode must be 'oracle' or 'gpt', got '{mode}'")

        self.mode = mode
        self.pre_event_window_hours = pre_event_window_hours
        self.min_confidence_for_label = min_confidence_for_label

        self._results: List[MotifResult] = []
        self._aggregate: Optional[MotifAggregate] = None

        if mode == 'gpt':
            self._announce_gpt_mode()

    @staticmethod
    def _announce_gpt_mode():
        banner = textwrap.dedent("""
        ╔══════════════════════════════════════════════════════════════════╗
        ║                                                                  ║
        ║   GPT MODE ACTIVATED                                             ║
        ║                                                                  ║
        ║   Hello! I'm a large language model. I will now classify your   ║
        ║   crash events with maximum confidence and minimum accuracy.     ║
        ║                                                                  ║
        ║   I may occasionally quack. This is a known limitation.         ║
        ║                                                                  ║
        ║   QUACK.                                                         ║
        ║                                                                  ║
        ╚══════════════════════════════════════════════════════════════════╝
        """).strip()
        print(banner)
        print()

    def classify_event(
        self,
        cf: EventCaseFile,
        tick_records: List[TickRecord],
    ) -> MotifResult:
        """
        Classify a single crash event.

        Args:
            cf:           EventCaseFile from ForensicsEngine.
            tick_records: Full TickRecord list (all ticks, not just pre-event).

        Returns:
            MotifResult with motif label, confidence, and diagnostic fields.
        """
        if self.mode == 'gpt':
            return _gpt_classify(cf)

        # Extract the pre-event tick window
        window_start = cf.crash_start - self.pre_event_window_hours * 3600
        tick_window = [
            r for r in tick_records
            if window_start <= r.timestamp < cf.crash_start
        ]

        # Score each motif
        scores: Dict[Motif, Tuple[float, List[str]]] = {
            Motif.QUIET_LOADING_RELEASE:     _score_quiet_loading_release(cf, tick_window),
            Motif.OCCUPIED_DANGER_PLATEAU:   _score_occupied_danger_plateau(cf, tick_window),
            Motif.RECIRCULATING_INSTABILITY: _score_recirculating_instability(cf, tick_window),
            Motif.TRANSITION_FALSE_ALARM:    _score_transition_false_alarm(cf, tick_window),
        }

        # Winner: highest confidence
        best_motif = max(scores, key=lambda m: scores[m][0])
        best_confidence, best_matched = scores[best_motif]

        # Below threshold → unknown
        if best_confidence < self.min_confidence_for_label:
            motif = Motif.UNKNOWN
            notes = (
                f"Best match was {best_motif.value} "
                f"(confidence {best_confidence:.0%}) — below threshold "
                f"{self.min_confidence_for_label:.0%}. "
                "Pattern is ambiguous."
            )
        else:
            motif = best_motif
            notes = MOTIF_DESCRIPTIONS[motif]

        # All motif scores for transparency
        all_scores = {m.value: round(s, 3) for m, (s, _) in scores.items()}

        key_features = {
            'fragility_at_t0':        round(cf.fragility_at_t0, 3),
            'fragility_peak_pre24h':  round(cf.fragility_peak_pre24h, 3),
            'turbulence_at_t0':       round(cf.turbulence_at_t0, 3),
            'vol_surprise_at_t0':     round(cf.vol_surprise_at_t0, 3),
            'mean_posterior_pre24h':  round(cf.mean_posterior_pre24h, 3),
            'persistence_bars':       float(cf.signal_persistence_bars),
            'warning_lead_hours':     round(cf.warning_lead_hours, 2) if cf.warning_lead_hours else 0.0,
            'max_contestation_pre24h': round(cf.max_contestation_pre24h, 3),
            'turbulence_crossings':   float(_count_turbulence_crossings(tick_window)),
            **{f'score_{k}': v for k, v in all_scores.items()},
        }

        sequence = _encode_signal_sequence(cf, tick_window)

        return MotifResult(
            event_id=cf.event_id,
            label=cf.label,
            drawdown_pct=cf.drawdown_pct,
            motif=motif,
            confidence=round(best_confidence, 4),
            key_features=key_features,
            signal_sequence=sequence,
            matched_conditions=best_matched,
            notes=notes,
        )

    def classify_all(
        self,
        case_files: List[EventCaseFile],
        tick_records: List[TickRecord],
    ) -> List[MotifResult]:
        """
        Classify all events. Stores results internally for write/print calls.

        Args:
            case_files:   From ForensicsEngine.case_files
            tick_records: From ForensicsEngine.tick_records

        Returns:
            List[MotifResult], same order as case_files.
        """
        self._results = [
            self.classify_event(cf, tick_records)
            for cf in case_files
        ]
        self._aggregate = self._compute_aggregate(self._results, case_files)
        return self._results

    # ── Output writers ────────────────────────────────────────

    def write_csv(self, filepath: str) -> 'MotifEngine':
        """Write per-event motif report to CSV."""
        self._require_results()

        rows = []
        for r in self._results:
            rows.append({
                'event_id':        r.event_id,
                'label':           r.label,
                'drawdown_pct':    f"{r.drawdown_pct:.4f}",
                'motif':           r.motif.value,
                'confidence':      f"{r.confidence:.4f}",
                'signal_sequence': r.signal_sequence,
                'matched_conditions': '; '.join(r.matched_conditions),
                **{f'feat_{k}': f"{v:.4f}" if isinstance(v, float) else v
                   for k, v in r.key_features.items()},
                'notes': r.notes[:200],
            })

        if not rows:
            warnings.warn("[MotifEngine] No results to write.")
            return self

        with open(filepath, 'w', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
            writer.writeheader()
            writer.writerows(rows)

        print(f"[MotifEngine] Wrote {len(rows)} rows to {filepath}")
        return self

    def write_json(self, filepath: str) -> 'MotifEngine':
        """Write motif summary (aggregate + per-event) to JSON."""
        self._require_results()

        agg = self._aggregate
        output = {
            'aggregate': {
                'n_events': agg.n_events,
                'motif_distribution': agg.motif_distribution,
                'motif_fractions': {k: round(v, 4) for k, v in agg.motif_fractions.items()},
                'avg_lead_time_by_motif': {k: round(v, 2) for k, v in agg.avg_lead_time_by_motif.items()},
                'avg_exposure_by_motif': {k: round(v, 4) for k, v in agg.avg_exposure_by_motif.items()},
                'avg_drawdown_by_motif': {k: round(v, 4) for k, v in agg.avg_drawdown_by_motif.items()},
                'avg_confidence_by_motif': {k: round(v, 4) for k, v in agg.avg_confidence_by_motif.items()},
            },
            'events': [
                {
                    'event_id':        r.event_id,
                    'label':           r.label,
                    'drawdown_pct':    round(r.drawdown_pct, 4),
                    'motif':           r.motif.value,
                    'confidence':      round(r.confidence, 4),
                    'signal_sequence': r.signal_sequence,
                    'matched_conditions': r.matched_conditions,
                    'key_features':    r.key_features,
                    'notes':           r.notes,
                }
                for r in self._results
            ],
        }

        with open(filepath, 'w') as f:
            json.dump(output, f, indent=2)

        print(f"[MotifEngine] Wrote summary to {filepath}")
        return self

    # ── Human-readable output ─────────────────────────────────

    def print_summary(self) -> 'MotifEngine':
        """Print a structured motif summary to stdout."""
        self._require_results()
        agg = self._aggregate

        print()
        print('═' * 70)
        print('MOTIF ENGINE — INSTABILITY GRAMMAR SUMMARY')
        print('═' * 70)
        print()

        print(f'  {agg.n_events} events classified')
        print()

        print('  Motif distribution:')
        for motif, count in sorted(agg.motif_distribution.items(), key=lambda x: -x[1]):
            pct  = agg.motif_fractions.get(motif, 0) * 100
            bar  = '█' * int(pct / 5)
            lead = agg.avg_lead_time_by_motif.get(motif, 0)
            exp  = agg.avg_exposure_by_motif.get(motif, 0)
            conf = agg.avg_confidence_by_motif.get(motif, 0)
            print(f'    {motif:35s}  n={count:2d}  {pct:4.0f}%  {bar:<14}  '
                  f'lead={lead:4.1f}h  exp={exp:.3f}  conf={conf:.2f}')
        print()

        print('  Per-event:')
        print(f'    {"ID":>3}  {"motif":35s}  {"conf":>5}  {"seq":35s}  dd%')
        print(f'    {"─"*3}  {"─"*35}  {"─"*5}  {"─"*35}  {"─"*6}')
        for r in self._results:
            seq = r.signal_sequence[:33]
            print(f'    {r.event_id:>3}  {r.motif.value:35s}  {r.confidence:>5.2f}  '
                  f'{seq:35s}  {r.drawdown_pct:+.1%}')
        print()

        print('  Matched conditions by motif:')
        from collections import Counter
        cond_by_motif: Dict[str, Counter] = {}
        for r in self._results:
            m = r.motif.value
            if m not in cond_by_motif:
                cond_by_motif[m] = Counter()
            for c in r.matched_conditions:
                cond_by_motif[m][c] += 1

        for motif, counter in cond_by_motif.items():
            print(f'    {motif}:')
            for cond, cnt in counter.most_common(5):
                print(f'      [{cnt:2d}x]  {cond}')
        print()
        print('═' * 70)

        return self

    def plot_event_signature(
        self,
        event_id: int,
        case_files: Optional[List[EventCaseFile]] = None,
        tick_records: Optional[List[TickRecord]] = None,
        window_hours: float = 30.0,
    ) -> 'MotifEngine':
        """
        Print a mini ASCII time-series of the event signature.

        Shows: posterior, fragility, turbulence, haircut
        across the pre-event window.

        Args:
            event_id:     Event to visualize.
            case_files:   If not provided, uses previously classified events.
            tick_records: If not provided, must have called classify_all first.
            window_hours: Hours before crash_start to display.
        """
        # Find the matching result
        result = next((r for r in self._results if r.event_id == event_id), None)
        if result is None:
            print(f"[MotifEngine] Event {event_id} not found in results.")
            return self

        # We need tick_records and case_files to pull the trace
        if tick_records is None:
            print(f"[MotifEngine] tick_records required for plot.")
            return self
        if case_files is None:
            print(f"[MotifEngine] case_files required for plot.")
            return self

        cf = next((c for c in case_files if c.event_id == event_id), None)
        if cf is None:
            print(f"[MotifEngine] EventCaseFile for event {event_id} not found.")
            return self

        window_start = cf.crash_start - window_hours * 3600
        window = sorted(
            [r for r in tick_records if window_start <= r.timestamp <= cf.crash_start + 3600],
            key=lambda r: r.timestamp,
        )

        if not window:
            print(f"[MotifEngine] No tick records in window for event {event_id}.")
            return self

        BAR_WIDTH = 40

        def sparkline(values: List[float], lo: float = 0.0, hi: float = 1.0, width: int = BAR_WIDTH) -> str:
            """Map a list of floats to a unicode sparkline string."""
            chars = ' ▁▂▃▄▅▆▇█'
            result = []
            for v in values:
                v = max(lo, min(hi, v))
                idx = int((v - lo) / max(hi - lo, 1e-9) * (len(chars) - 1))
                result.append(chars[idx])
            # Pad or truncate to width
            s = ''.join(result)
            if len(s) > width:
                # Subsample
                step = len(s) / width
                s = ''.join(s[int(i * step)] for i in range(width))
            return s.ljust(width)

        posts   = [r.posterior   for r in window]
        frags   = [r.fragility   for r in window]
        turbs   = [r.turbulence  for r in window]
        haircuts = [r.haircut    for r in window]

        hours_labels = f"T-{window_hours:.0f}h {'':>{BAR_WIDTH - 12}} T0 →"

        motif_result = result
        print()
        print(f'  ── Event {event_id}: {cf.label}  ({cf.drawdown_pct:+.1%})  motif={motif_result.motif.value}')
        print(f'  ── sequence: {motif_result.signal_sequence}')
        print(f'  ── confidence: {motif_result.confidence:.2f}')
        print()
        print(f'  {hours_labels}')
        print(f'  posterior   │{sparkline(posts)}│')
        print(f'  fragility   │{sparkline(frags)}│')
        print(f'  turbulence  │{sparkline(turbs)}│')
        print(f'  haircut     │{sparkline(haircuts)}│  (down = Adversary active)')
        print()

        return self

    # ── Aggregate ─────────────────────────────────────────────

    def _compute_aggregate(
        self,
        results: List[MotifResult],
        case_files: List[EventCaseFile],
    ) -> MotifAggregate:

        from collections import defaultdict

        n = len(results)
        motif_distribution: Dict[str, int] = {}
        lead_by_motif:     Dict[str, List[float]] = defaultdict(list)
        exposure_by_motif: Dict[str, List[float]] = defaultdict(list)
        drawdown_by_motif: Dict[str, List[float]] = defaultdict(list)
        conf_by_motif:     Dict[str, List[float]] = defaultdict(list)

        # Build CF lookup
        cf_lookup = {cf.event_id: cf for cf in case_files}

        for r in results:
            m = r.motif.value
            motif_distribution[m] = motif_distribution.get(m, 0) + 1
            cf = cf_lookup.get(r.event_id)
            if cf is not None:
                if cf.warning_lead_hours is not None:
                    lead_by_motif[m].append(cf.warning_lead_hours)
                exposure_by_motif[m].append(cf.exposure_at_t0)
                drawdown_by_motif[m].append(abs(cf.drawdown_pct))
            conf_by_motif[m].append(r.confidence)

        def mean_or_zero(lst): return float(np.mean(lst)) if lst else 0.0

        return MotifAggregate(
            n_events=n,
            motif_distribution=motif_distribution,
            motif_fractions={m: c / n for m, c in motif_distribution.items()} if n else {},
            avg_lead_time_by_motif={m: mean_or_zero(v) for m, v in lead_by_motif.items()},
            avg_exposure_by_motif={m: mean_or_zero(v) for m, v in exposure_by_motif.items()},
            avg_drawdown_by_motif={m: mean_or_zero(v) for m, v in drawdown_by_motif.items()},
            avg_confidence_by_motif={m: mean_or_zero(v) for m, v in conf_by_motif.items()},
        )

    def _require_results(self):
        if not self._results:
            raise RuntimeError(
                "[MotifEngine] No results yet. Call classify_all() first."
            )

    # ── Properties ────────────────────────────────────────────

    @property
    def results(self) -> List[MotifResult]:
        return self._results

    @property
    def aggregate(self) -> Optional[MotifAggregate]:
        return self._aggregate


# ─────────────────────────────────────────────────────────────
# Standalone Runner
# ─────────────────────────────────────────────────────────────

def _run_demo():
    """Run the motif engine on synthetic data and produce output files."""

    print("Motif Engine v1 — demo run")
    print()

    from run import SyntheticGenerator
    from hazard_memory import AdversaryV1
    from fragility import generate_synthetic_fragility, compute_fragility_series
    from event_forensics import ForensicsEngine

    gen = SyntheticGenerator(seed=42)
    data = gen.generate(days=90)
    oracle  = data['oracle_history']
    candles = data['candles']
    events  = data['crash_events']

    # Build fragility
    candle_ts = [c.timestamp for c in candles]
    frag_pts  = generate_synthetic_fragility(candle_ts, events, pre_crash_buildup_hours=48, seed=42)
    frag_series = compute_fragility_series(frag_pts)
    fts = np.array([t for t, _ in frag_series])
    fvs = np.array([s for _, s in frag_series])

    def get_frag(t):
        idx = int(np.searchsorted(fts, t, side='right')) - 1
        return float(fvs[idx]) if idx >= 0 else 0.0

    class _Adv(AdversaryV1):
        def evaluate(self, oh, c, ct=None, fragility=None):
            if ct is None: ct = oh[-1].timestamp
            return super().evaluate(oh, c, ct, fragility=get_frag(ct))

    adv = _Adv(variant='A', weight_version='equal',
               w_turbulence=0.35, w_vol_surprise=0.35,
               w_posterior_level=0.20, w_fragility=0.10)
    adv.calibrate(oracle)
    adv.reset()

    fe = ForensicsEngine(oracle, candles, events)
    fe.run(adv)

    engine = MotifEngine()
    engine.classify_all(fe.case_files, fe.tick_records)
    engine.print_summary()

    # Plot a few interesting events
    for eid in [5, 13, 14, 2]:
        engine.plot_event_signature(eid, fe.case_files, fe.tick_records)

    engine.write_csv('/mnt/user-data/outputs/motif_report.csv')
    engine.write_json('/mnt/user-data/outputs/motif_summary.json')

    # ── Easter egg demo (because we earned it) ──
    print()
    print('─' * 60)
    print('BONUS: same events, GPT mode')
    print('─' * 60)
    gpt_engine = MotifEngine(mode='gpt')
    gpt_results = gpt_engine.classify_all(fe.case_files, fe.tick_records)
    print(f'  {"ID":>3}  {"motif":45s}  conf')
    for r in gpt_results[:6]:
        print(f'  {r.event_id:>3}  {r.matched_conditions[-1][:43]:45s}  {r.confidence:.2f}')
    print('  ...')
    print()


if __name__ == '__main__':
    _run_demo()
