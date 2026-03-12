"""
Motif Robustness Harness — Oracle Project | March 2026

Four experiments:
  1. Seed Sweep         — motif stability across 20 synthetic worlds
  2. Fragility Ablation — does structural fragility do real work?
  3. Hazard Decay Sweep — sensitivity to kernel decay constant
  4. Prefix Prediction  — can motifs be recognized before collapse?

Usage:
    python motif_harness.py                    # all experiments, 20 seeds
    python motif_harness.py --n-seeds 5        # quick smoke run
    python motif_harness.py --exp seed_sweep   # single experiment
    python motif_harness.py --output-dir /tmp  # custom output dir
"""

import argparse, csv, json, os, time, warnings
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import numpy as np

from run import SyntheticGenerator
from hazard_memory import AdversaryV1
from fragility import generate_synthetic_fragility, compute_fragility_series
from event_forensics import ForensicsEngine, EventCaseFile, TickRecord
from motif_engine import MotifEngine, MotifResult, Motif
from backtest import BacktestEngine


# ─────────────────────────────────────────────────────────────
# Config
# ─────────────────────────────────────────────────────────────

@dataclass
class HarnessConfig:
    n_seeds: int = 20
    seeds: Optional[List[int]] = None
    days: int = 90
    base_decay: float = 0.85
    decay_sweep_values: List[float] = field(default_factory=lambda: [0.75,0.80,0.85,0.90,0.93])
    w_turbulence: float = 0.35
    w_vol_surprise: float = 0.35
    w_posterior_level: float = 0.20
    w_fragility: float = 0.10
    pre_crash_buildup_hours: int = 48
    prefix_horizons_hours: List[float] = field(default_factory=lambda: [12.0,8.0,4.0,2.0])
    min_confidence_for_label: float = 0.50
    output_dir: str = '.'
    verbose: bool = True

    def get_seeds(self):
        return self.seeds if self.seeds else list(range(self.n_seeds))


# ─────────────────────────────────────────────────────────────
# World runner
# ─────────────────────────────────────────────────────────────

@dataclass
class WorldResult:
    seed: int; decay: float; fragility_enabled: bool; n_events: int
    case_files: List[EventCaseFile]; tick_records: List[TickRecord]
    motif_results: List[MotifResult]; backtest_metrics: dict
    timing_score: float; mean_exposure_at_t0: float
    mean_persistence: float; false_positives_per_event: float; detection_rate: float


def _make_adv(oracle, decay, cfg, frag_on, frag_lookup):
    w_frag = cfg.w_fragility if frag_on else 0.0
    w_t = cfg.w_turbulence + (cfg.w_fragility/2 if not frag_on else 0)
    w_v = cfg.w_vol_surprise + (cfg.w_fragility/2 if not frag_on else 0)
    w_l = cfg.w_posterior_level

    class _A(AdversaryV1):
        def evaluate(self, oh, c, ct=None, fragility=None):
            if ct is None: ct = oh[-1].timestamp
            return super().evaluate(oh, c, ct, fragility=frag_lookup(ct) if frag_on else 0.0)

    adv = _A(variant='A', weight_version='equal', hazard_decay=decay,
             w_turbulence=w_t, w_vol_surprise=w_v, w_posterior_level=w_l, w_fragility=w_frag)
    adv.calibrate(oracle); adv.reset()
    return adv


def run_world(seed, decay, cfg, fragility_enabled=True, precomputed=None):
    if precomputed is None:
        gen  = SyntheticGenerator(seed=seed)
        data = gen.generate(days=cfg.days)
        oracle, candles, events = data['oracle_history'], data['candles'], data['crash_events']
        frag_pts = generate_synthetic_fragility([c.timestamp for c in candles], events,
                       pre_crash_buildup_hours=cfg.pre_crash_buildup_hours, seed=seed)
        frag_series = compute_fragility_series(frag_pts)
    else:
        oracle, candles, events = precomputed['oracle'], precomputed['candles'], precomputed['events']
        frag_series = precomputed['frag_series']

    fts = np.array([t for t,_ in frag_series])
    fvs = np.array([s for _,s in frag_series])
    def get_frag(t):
        idx = int(np.searchsorted(fts, t, side='right')) - 1
        return float(fvs[idx]) if idx >= 0 else 0.0

    adv = _make_adv(oracle, decay, cfg, fragility_enabled, get_frag)
    with warnings.catch_warnings():
        warnings.simplefilter('ignore')
        fe = ForensicsEngine(oracle, candles, events)
        fe.run(adv)

    be = BacktestEngine(oracle, candles, events)
    baseline = be.run_baseline()
    adv2 = _make_adv(oracle, decay, cfg, fragility_enabled, get_frag)
    bm   = be.run_adversary(adv2, f's{seed}')
    pvc  = bm.protection_vs_cost(baseline)

    me = MotifEngine(min_confidence_for_label=cfg.min_confidence_for_label)
    me.classify_all(fe.case_files, fe.tick_records)

    agg = fe.aggregate
    return WorldResult(
        seed=seed, decay=decay, fragility_enabled=fragility_enabled,
        n_events=len(events), case_files=fe.case_files, tick_records=fe.tick_records,
        motif_results=me.results, backtest_metrics=pvc,
        timing_score=bm.haircut_timing_score,
        mean_exposure_at_t0=float(np.mean([c.exposure_at_t0 for c in fe.case_files])) if fe.case_files else 1.0,
        mean_persistence=agg.mean_signal_persistence if agg else 0.0,
        false_positives_per_event=agg.false_positive_rate if agg else 0.0,
        detection_rate=agg.detection_rate if agg else 0.0,
    )


def _mf(results):
    if not results: return {}
    c = defaultdict(int)
    for r in results: c[r.motif.value] += 1
    n = len(results)
    return {m: cnt/n for m, cnt in c.items()}


# ─────────────────────────────────────────────────────────────
# Prefix snapshot
# ─────────────────────────────────────────────────────────────

def _horizon_snap(cf, tick_records, horizon_hours):
    import copy
    ht_ts = cf.crash_start - horizon_hours * 3600
    window = [r for r in tick_records if (ht_ts - 86400) <= r.timestamp <= ht_ts]
    if not window: return None
    ht = window[-1]
    s = copy.copy(cf)
    s.crash_start = ht_ts
    s.turbulence_at_t0 = ht.turbulence; s.vol_surprise_at_t0 = ht.vol_surprise
    s.contestation_at_t0 = ht.contestation; s.haircut_at_t0 = ht.haircut
    s.exposure_at_t0 = ht.exposure; s.oracle_posterior_at_t0 = ht.posterior
    s.oracle_cap_at_t0 = ht.oracle_cap; s.fragility_at_t0 = ht.fragility
    s.dominant_signal_at_t0 = ht.dominant_signal; s.adversary_active_at_t0 = ht.haircut < 0.85
    s.fragility_peak_pre24h    = float(max((r.fragility for r in window), default=0.0))
    s.mean_posterior_pre24h    = float(np.mean([r.posterior for r in window]))
    s.mean_exposure_pre24h     = float(np.mean([r.exposure for r in window]))
    s.min_exposure_pre24h      = float(np.min([r.exposure for r in window]))
    s.mean_haircut_pre24h      = float(np.mean([r.haircut for r in window]))
    s.mean_contestation_pre24h = float(np.mean([r.contestation for r in window]))
    s.max_contestation_pre24h  = float(max((r.contestation for r in window), default=0.0))
    persistence = 0
    for r in reversed(window):
        if r.haircut < 0.85: persistence += 1
        else: break
    s.signal_persistence_bars = persistence
    first_act = next((r for r in window if r.haircut < 0.85), None)
    s.warning_lead_hours = (ht_ts - first_act.timestamp)/3600 if first_act else None
    return s


# ─────────────────────────────────────────────────────────────
# Experiment 1 — Seed Sweep
# ─────────────────────────────────────────────────────────────

def run_seed_sweep(cfg):
    seeds = cfg.get_seeds()
    rows = []; all_fracs = defaultdict(list); all_leads = defaultdict(list)
    all_exp = defaultdict(list); all_dd = defaultdict(list)
    timings = []; dets = []; fps = []

    _log(cfg, f"\nExp 1 — Seed Sweep  ({len(seeds)} seeds, decay={cfg.base_decay})")
    for i, seed in enumerate(seeds):
        t0 = time.time()
        _log(cfg, f"  seed {seed:3d}  [{i+1:2d}/{len(seeds)}]", end='  ')
        wr = run_world(seed, cfg.base_decay, cfg, fragility_enabled=True)
        fracs = _mf(wr.motif_results)
        timings.append(wr.timing_score); dets.append(wr.detection_rate)
        fps.append(wr.false_positives_per_event)

        row = {'seed': seed, 'n_events': wr.n_events,
               'timing_score': round(wr.timing_score,4), 'detection_rate': round(wr.detection_rate,4),
               'mean_exposure_at_t0': round(wr.mean_exposure_at_t0,4),
               'mean_persistence': round(wr.mean_persistence,4),
               'false_pos_per_event': round(wr.false_positives_per_event,4)}
        for m in [x.value for x in Motif]:
            f = fracs.get(m, 0.0); row[f'frac_{m}'] = round(f,4); all_fracs[m].append(f)
        for mr in wr.motif_results:
            cf = next((c for c in wr.case_files if c.event_id == mr.event_id), None)
            if cf:
                all_leads[mr.motif.value].append(cf.warning_lead_hours or 0.0)
                all_exp[mr.motif.value].append(cf.exposure_at_t0)
                all_dd[mr.motif.value].append(abs(cf.drawdown_pct))
        rows.append(row)
        _log(cfg, f"{time.time()-t0:.1f}s  {fracs}")

    fm = {m: float(np.mean(v)) for m,v in all_fracs.items() if v}
    fs = {m: float(np.std(v))  for m,v in all_fracs.items() if v}
    stab = {m: round(max(0., 1. - fs[m]/max(fm[m],1e-6)),4) for m in fm}
    sorted_f = sorted(fm.values(), reverse=True)
    sep = round(sorted_f[0]-sorted_f[1],4) if len(sorted_f)>=2 else 1.0
    dom = max(fm, key=lambda m: fm[m]) if fm else 'unknown'

    agg = {'experiment':'seed_sweep','n_seeds':len(seeds),'decay':cfg.base_decay,
           'dominant_motif':dom,
           'motif_fraction_mean':{m:round(v,4) for m,v in fm.items()},
           'motif_fraction_std': {m:round(v,4) for m,v in fs.items()},
           'motif_stability_score':stab, 'motif_separation_score':sep,
           'avg_lead_time_by_motif':{m:round(float(np.mean(v)),2) for m,v in all_leads.items() if v},
           'avg_exposure_by_motif': {m:round(float(np.mean(v)),4) for m,v in all_exp.items()   if v},
           'avg_drawdown_by_motif': {m:round(float(np.mean(v)),4) for m,v in all_dd.items()    if v},
           'timing_score_mean':round(float(np.mean(timings)),4),
           'timing_score_std': round(float(np.std(timings)),4),
           'detection_rate_mean':round(float(np.mean(dets)),4),
           'false_pos_mean':round(float(np.mean(fps)),4)}
    return rows, agg


# ─────────────────────────────────────────────────────────────
# Experiment 2 — Fragility Ablation
# ─────────────────────────────────────────────────────────────

def run_fragility_ablation(cfg):
    seeds = cfg.get_seeds(); rows = []
    summ = {True: defaultdict(list), False: defaultdict(list)}
    _log(cfg, f"\nExp 2 — Fragility Ablation  ({len(seeds)} seeds)")

    for i, seed in enumerate(seeds):
        _log(cfg, f"  seed {seed:3d}  [{i+1:2d}/{len(seeds)}]")
        gen  = SyntheticGenerator(seed=seed); data = gen.generate(days=cfg.days)
        fp   = generate_synthetic_fragility([c.timestamp for c in data['candles']],
                   data['crash_events'], pre_crash_buildup_hours=cfg.pre_crash_buildup_hours, seed=seed)
        shared = {'oracle': data['oracle_history'], 'candles': data['candles'],
                  'events': data['crash_events'],   'frag_series': compute_fragility_series(fp)}

        for frag_on in [True, False]:
            wr = run_world(seed, cfg.base_decay, cfg, fragility_enabled=frag_on, precomputed=shared)
            fracs = _mf(wr.motif_results)
            row = {'seed':seed,'fragility_enabled':frag_on,
                   'timing_score':round(wr.timing_score,4),'detection_rate':round(wr.detection_rate,4),
                   'mean_exposure_at_t0':round(wr.mean_exposure_at_t0,4),
                   'mean_persistence':round(wr.mean_persistence,4),
                   'false_pos_per_event':round(wr.false_positives_per_event,4)}
            for m in [x.value for x in Motif]:
                f = fracs.get(m, 0.0); row[f'frac_{m}'] = round(f,4)
                summ[frag_on][f'frac_{m}'].append(f)
            for k in ('timing_score','detection_rate','mean_exposure_at_t0','mean_persistence','false_pos_per_event'):
                summ[frag_on][k].append(row[k])
            rows.append(row)

    def _mn(d): return {k: round(float(np.mean(v)),4) for k,v in d.items()}
    on_a = _mn(summ[True]); off_a = _mn(summ[False])
    def _d(k): return round(on_a.get(k,0)-off_a.get(k,0),4)

    agg = {'experiment':'fragility_ablation','n_seeds':len(seeds),'decay':cfg.base_decay,
           'with_fragility':on_a,'without_fragility':off_a,
           'delta_on_minus_off':{
               'timing_score':_d('timing_score'),'detection_rate':_d('detection_rate'),
               'mean_exposure_at_t0':_d('mean_exposure_at_t0'),'mean_persistence':_d('mean_persistence'),
               'false_pos_per_event':_d('false_pos_per_event'),
               'frac_quiet_loading_release':_d('frac_quiet_loading_release'),
               'frac_transition_false_alarm':_d('frac_transition_false_alarm')}}
    return rows, agg


# ─────────────────────────────────────────────────────────────
# Experiment 3 — Decay Sweep
# ─────────────────────────────────────────────────────────────

def run_decay_sweep(cfg):
    seeds = cfg.get_seeds(); decays = cfg.decay_sweep_values; rows = []
    summ = {d: defaultdict(list) for d in decays}
    _log(cfg, f"\nExp 3 — Decay Sweep  ({len(seeds)} seeds × {len(decays)} decays)")

    for i, seed in enumerate(seeds):
        _log(cfg, f"  seed {seed:3d}  [{i+1:2d}/{len(seeds)}]")
        gen  = SyntheticGenerator(seed=seed); data = gen.generate(days=cfg.days)
        fp   = generate_synthetic_fragility([c.timestamp for c in data['candles']],
                   data['crash_events'], pre_crash_buildup_hours=cfg.pre_crash_buildup_hours, seed=seed)
        shared = {'oracle': data['oracle_history'], 'candles': data['candles'],
                  'events': data['crash_events'],   'frag_series': compute_fragility_series(fp)}

        for decay in decays:
            wr = run_world(seed, decay, cfg, fragility_enabled=True, precomputed=shared)
            fracs = _mf(wr.motif_results)
            avg_conf = float(np.mean([r.confidence for r in wr.motif_results])) if wr.motif_results else 0.0
            row = {'seed':seed,'decay':decay,
                   'timing_score':round(wr.timing_score,4),'detection_rate':round(wr.detection_rate,4),
                   'mean_exposure_at_t0':round(wr.mean_exposure_at_t0,4),
                   'mean_persistence':round(wr.mean_persistence,4),
                   'false_pos_per_event':round(wr.false_positives_per_event,4),
                   'mean_confidence':round(avg_conf,4)}
            for m in [x.value for x in Motif]:
                f = fracs.get(m,0.0); row[f'frac_{m}'] = round(f,4); summ[decay][f'frac_{m}'].append(f)
            for k in ('timing_score','detection_rate','mean_exposure_at_t0','mean_persistence',
                      'false_pos_per_event','mean_confidence'):
                summ[decay][k].append(row[k])
            rows.append(row)

    per_decay = {str(d): {k:round(float(np.mean(v)),4) for k,v in summ[d].items()} for d in decays}
    best_t  = max(decays, key=lambda d: float(np.mean(summ[d]['timing_score'])))
    best_fp = min(decays, key=lambda d: float(np.mean(summ[d]['false_pos_per_event'])))
    agg = {'experiment':'decay_sweep','n_seeds':len(seeds),'decays_tested':decays,
           'best_decay_by_timing_score':best_t,'best_decay_by_false_positives':best_fp,
           'per_decay':per_decay}
    return rows, agg


# ─────────────────────────────────────────────────────────────
# Experiment 4 — Prefix Prediction
# ─────────────────────────────────────────────────────────────

def run_prefix_prediction(cfg, base_worlds=None):
    horizons = cfg.prefix_horizons_hours
    if base_worlds is None:
        _log(cfg, f"\nExp 4 — Prefix Prediction  (generating {cfg.n_seeds} worlds)")
        base_worlds = [run_world(s, cfg.base_decay, cfg, True) for s in cfg.get_seeds()]
    else:
        _log(cfg, f"\nExp 4 — Prefix Prediction  (reusing {len(base_worlds)} worlds)")

    me = MotifEngine(min_confidence_for_label=cfg.min_confidence_for_label)
    rows = []; hstats = {h: defaultdict(list) for h in horizons}
    conf_mat = {h: defaultdict(int) for h in horizons}

    for wr in base_worlds:
        for cf in wr.case_files:
            true_mr = next((r for r in wr.motif_results if r.event_id == cf.event_id), None)
            if true_mr is None: continue
            true_m = true_mr.motif.value
            for h in horizons:
                snap = _horizon_snap(cf, wr.tick_records, h)
                if snap is None: continue
                pred_mr = me.classify_event(snap, wr.tick_records)
                pred_m  = pred_mr.motif.value
                correct = (pred_m == true_m)
                rows.append({'seed':wr.seed,'event_id':cf.event_id,'horizon_hours':h,
                             'true_motif':true_m,'pred_motif':pred_m,'correct':correct,
                             'confidence':round(pred_mr.confidence,4),'drawdown_pct':round(cf.drawdown_pct,4)})
                hstats[h]['correct'].append(float(correct))
                hstats[h]['confidence'].append(pred_mr.confidence)
                conf_mat[h][(true_m, pred_m)] += 1

    per_h = {}
    for h in horizons:
        acc  = float(np.mean(hstats[h]['correct']))    if hstats[h]['correct']    else 0.0
        conf = float(np.mean(hstats[h]['confidence'])) if hstats[h]['confidence'] else 0.0
        preds = defaultdict(int)
        for (_, p), cnt in conf_mat[h].items(): preds[p] += cnt
        top = max(preds, key=lambda m: preds[m]) if preds else 'unknown'
        per_h[str(h)] = {'accuracy':round(acc,4),'mean_confidence':round(conf,4),
                         'n_predictions':len(hstats[h]['correct']),'top_predicted_motif':top,
                         'confusion':{f'{t}→{p}':cnt for (t,p),cnt in conf_mat[h].items()}}

    acc_by_h = {str(h): round(float(np.mean(hstats[h]['correct'])),4)
                for h in horizons if hstats[h]['correct']}
    agg = {'experiment':'prefix_prediction','n_worlds':len(base_worlds),
           'horizons':horizons,'accuracy_by_horizon':acc_by_h,'per_horizon':per_h}
    return rows, agg


# ─────────────────────────────────────────────────────────────
# Terminal summary
# ─────────────────────────────────────────────────────────────

def print_compact_summary(sa, fa, da, pa):
    print('\n' + '═'*68)
    print('MOTIF ROBUSTNESS HARNESS — FINDINGS')
    print('═'*68)

    print('\n  1. SEED SWEEP')
    dm  = sa.get('dominant_motif','?')
    fm  = sa.get('motif_fraction_mean',{}); fs = sa.get('motif_fraction_std',{})
    stb = sa.get('motif_stability_score',{}); sep = sa.get('motif_separation_score',0)
    print(f'     Dominant motif:   {dm}')
    print(f'     Mean fraction:    {fm.get(dm,0):.1%}  ±{fs.get(dm,0):.1%}')
    print(f'     Stability score:  {stb.get(dm,0):.3f}  (1=perfectly stable across seeds)')
    print(f'     Separation score: {sep:.3f}  (top fraction − runner-up)')
    print(f'     Timing score:     {sa.get("timing_score_mean",0):.3f} ± {sa.get("timing_score_std",0):.3f}')
    print(f'     Detection rate:   {sa.get("detection_rate_mean",0):.3f}')

    print('\n  2. FRAGILITY ABLATION')
    d = fa.get('delta_on_minus_off',{})
    for label, key, note in [
        ('timing_score Δ',             'timing_score',               '+ = fragility helps'),
        ('mean exposure at T0 Δ',      'mean_exposure_at_t0',        '- = fragility helps'),
        ('quiet_loading_release Δ',    'frac_quiet_loading_release',  '+ = reveals structure'),
        ('transition_false_alarm Δ',   'frac_transition_false_alarm', '- = fewer false alarms'),
        ('persistence Δ',              'mean_persistence',            '+ = longer protection'),
    ]:
        v = d.get(key, 0); arrow = '▲' if v > 0 else '▼'
        print(f'     {label:30s}  {arrow}{abs(v):.4f}  ({note})')
    material = abs(d.get('timing_score',0)) > 0.05 or abs(d.get('mean_exposure_at_t0',0)) > 0.02
    print(f'     → Fragility is {"MATERIALLY HELPFUL ✓" if material else "marginal on synthetic data"}')

    print('\n  3. DECAY SWEEP')
    print(f'     Best decay (timing):    {da.get("best_decay_by_timing_score","?")}')
    print(f'     Best decay (false pos): {da.get("best_decay_by_false_positives","?")}')
    print(f'     {"decay":>7}  {"timing":>7}  {"fp/ev":>5}  {"persist":>7}  {"conf":>6}')
    for d_str in sorted(da.get('per_decay',{}), key=float):
        st = da['per_decay'][d_str]
        bar = '█' * int(st.get('timing_score',0)*14)
        print(f'     {d_str:>7}  {st.get("timing_score",0):>7.3f}  '
              f'{st.get("false_pos_per_event",0):>5.2f}  '
              f'{st.get("mean_persistence",0):>7.1f}  '
              f'{st.get("mean_confidence",0):>6.3f}  {bar}')

    print('\n  4. PREFIX PREDICTION')
    acc_h = pa.get('accuracy_by_horizon',{})
    for h_str in sorted(acc_h, key=lambda x: -float(x)):
        ph  = pa.get('per_horizon',{}).get(h_str,{})
        acc = acc_h[h_str]; top = ph.get('top_predicted_motif','?')
        bar = '█' * int(acc*16)
        print(f'     T-{float(h_str):4.0f}h  {bar:<16}  acc={acc:.3f}  top={top[:32]}')
    max_acc = max(acc_h.values(), default=0)
    print(f'     → Motifs {"ARE pre-collapse recognizable ✓" if max_acc > 0.55 else "not clearly pre-collapse predictive"}')
    print('\n' + '═'*68)


# ─────────────────────────────────────────────────────────────
# I/O
# ─────────────────────────────────────────────────────────────

def _wcsv(rows, fp):
    if not rows: warnings.warn(f"No rows: {fp}"); return
    with open(fp,'w',newline='') as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader(); w.writerows(rows)
    print(f"  → {fp}  ({len(rows)} rows)")

def _wjson(data, fp):
    with open(fp,'w') as f: json.dump(data, f, indent=2)
    print(f"  → {fp}")

def _log(cfg, msg, end='\n'):
    if cfg.verbose: print(msg, end=end, flush=True)

def _path(cfg, fname):
    os.makedirs(cfg.output_dir, exist_ok=True)
    return os.path.join(cfg.output_dir, fname)


# ─────────────────────────────────────────────────────────────
# Orchestrator
# ─────────────────────────────────────────────────────────────

def run_all(cfg):
    t_start = time.time()
    print('\n╔══════════════════════════════════════════════════════╗')
    print('║       MOTIF ROBUSTNESS HARNESS  v1                   ║')
    print(f'║  seeds={cfg.n_seeds:<3}  days={cfg.days}  decay={cfg.base_decay}              ║')
    print('╚══════════════════════════════════════════════════════╝')

    t0=time.time(); sr,sa = run_seed_sweep(cfg)
    _log(cfg,f"  Exp 1 done  {time.time()-t0:.1f}s")
    _wcsv(sr, _path(cfg,'seed_sweep_summary.csv'))
    _wjson({'aggregate':sa,'per_seed':sr}, _path(cfg,'seed_sweep_summary.json'))

    t0=time.time(); fr,fa = run_fragility_ablation(cfg)
    _log(cfg,f"  Exp 2 done  {time.time()-t0:.1f}s")
    _wcsv(fr, _path(cfg,'fragility_ablation.csv'))
    _wjson({'aggregate':fa,'per_run':fr}, _path(cfg,'fragility_ablation.json'))

    t0=time.time(); dr,da = run_decay_sweep(cfg)
    _log(cfg,f"  Exp 3 done  {time.time()-t0:.1f}s")
    _wcsv(dr, _path(cfg,'decay_sweep.csv'))
    _wjson({'aggregate':da,'per_run':dr}, _path(cfg,'decay_sweep.json'))

    t0=time.time(); pr,pa = run_prefix_prediction(cfg, base_worlds=None)
    _log(cfg,f"  Exp 4 done  {time.time()-t0:.1f}s")
    _wcsv(pr, _path(cfg,'prefix_prediction.csv'))
    _wjson({'aggregate':pa,'per_prediction':pr}, _path(cfg,'prefix_prediction.json'))

    print_compact_summary(sa, fa, da, pa)
    _log(cfg, f"\nTotal wall time: {time.time()-t_start:.1f}s")


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('--n-seeds',    type=int,   default=20)
    p.add_argument('--days',       type=int,   default=90)
    p.add_argument('--base-decay', type=float, default=0.85)
    p.add_argument('--decays',     nargs='+',  type=float, default=[0.75,0.80,0.85,0.90,0.93])
    p.add_argument('--exp', choices=['seed_sweep','fragility_ablation','decay_sweep',
                                     'prefix_prediction','all'], default='all')
    p.add_argument('--output-dir', type=str,   default='.')
    p.add_argument('--quiet',      action='store_true')
    args = p.parse_args()

    cfg = HarnessConfig(n_seeds=args.n_seeds, days=args.days, base_decay=args.base_decay,
                        decay_sweep_values=args.decays, output_dir=args.output_dir,
                        verbose=not args.quiet)

    if args.exp == 'all':
        run_all(cfg)
    else:
        fn = {'seed_sweep':run_seed_sweep,'fragility_ablation':run_fragility_ablation,
              'decay_sweep':run_decay_sweep,'prefix_prediction':run_prefix_prediction}[args.exp]
        rows, agg = fn(cfg)
        _wcsv(rows, _path(cfg, f'{args.exp}.csv'))
        _wjson({'aggregate':agg,'data':rows}, _path(cfg, f'{args.exp}.json'))
