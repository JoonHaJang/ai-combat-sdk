"""
BT Optimizer v2 — Hierarchical Scoring + Expanded Search

Scoring principle (academic + real-world dogfight aligned):
  - True objective: maximize tournament wins (3W + 1D, Elo tiebreaker)
  - Shaped reward: actual HP differential provides gradient within W/D/L tiers
  - Hierarchy guaranteed: worst_win > best_draw > best_loss

Search: Single-pass LHS with local refinement around top candidates.
No sequential phases needed — all in one run.

Usage:
    python tools/bt_optimizer.py --candidates 200          # Full search
    python tools/bt_optimizer.py --validate --rounds 10    # Validate best
    python tools/bt_optimizer.py --tournament              # Tournament mode
"""

import sys
import os
import yaml
import json
import time
import argparse
import multiprocessing as mp
from pathlib import Path
from copy import deepcopy
from functools import partial
from datetime import datetime

import numpy as np

# Project paths
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# Import run_match from parent directory
try:
    from scripts.run_match import run_match
except ImportError:
    # SDK 환경에서는 상대 경로로 import
    sys.path.insert(0, str(PROJECT_ROOT.parent))
    from scripts.run_match import run_match

# ============================================================
# Scoring Constants (Hierarchical: W/D/L dominant, HP shapes)
# ============================================================

WIN_BASE  = 10.0   # Win base score
DRAW_BASE =  1.0   # Draw base score
LOSS_BASE = -5.0   # Loss penalty (1 loss ≈ cost of missing 1-2 wins)
HP_WEIGHT =  2.0   # HP shaping weight (max contribution = ±2.0)
# Guarantees: worst_win(8.0) > best_draw(3.0) > best_loss(-3.0)

# ============================================================
# Parameter Space Definition
# ============================================================

PARAM_SPACE = {
    # --- Condition thresholds ---
    "hard_deck_threshold": {"type": "continuous", "range": (600, 1500)},
    "climb_target": {"type": "continuous", "range": (1500, 4000)},
    "wez_ata_threshold": {"type": "continuous", "range": (3, 12)},
    "threat_aa_threshold": {"type": "continuous", "range": (100, 160)},
    "threat_distance": {"type": "continuous", "range": (400, 1500)},
    "close_combat_distance": {"type": "continuous", "range": (1500, 4000)},

    # --- Action choices ---
    "close_action": {"type": "discrete", "choices": ["LeadPursuit", "Pursue", "LagPursuit", "PurePursuit"]},
    "default_action": {"type": "discrete", "choices": ["Pursue", "LeadPursuit", "LagPursuit"]},
    "defense_action": {"type": "discrete", "choices": ["BreakTurn", "DefensiveManeuver", "DefensiveSpiral", "BarrelRoll"]},

    # --- Structure flags (existing) ---
    "include_emergency_defense": {"type": "discrete", "choices": [True, False]},
    "include_altitude_far": {"type": "discrete", "choices": [True, False]},
    "altitude_advantage_target": {"type": "continuous", "range": (200, 800)},

    # --- PNAttack custom params ---
    "pnattack_kp": {"type": "continuous", "range": (0.8, 2.0)},
    "pnattack_kd": {"type": "continuous", "range": (0.2, 0.8)},

    # ----------------------------------------------------------------
    # NEW (v7.x adaptive branches) — added 2026-02-24
    # Key finding: IsOffensiveSituation at long range helps ace but hurts aggressive.
    # offensive_press_distance controls when the branch activates.
    # ----------------------------------------------------------------

    # Branch: InEnemyWEZ → BreakTurn (evade when opp has us in gun sight)
    "include_enemy_wez":  {"type": "discrete", "choices": [True, False]},
    "enemy_wez_distance": {"type": "continuous", "range": (500, 914)},
    "enemy_wez_los":      {"type": "continuous", "range": (10, 25)},

    # Branch: dist < offensive_press_distance AND IsOffensiveSituation → action
    "include_offensive_press":    {"type": "discrete", "choices": [True, False]},
    "offensive_press_distance":   {"type": "continuous", "range": (914, 5000)},
    "offensive_press_action":     {"type": "discrete", "choices": ["LeadPursuit", "Pursue", "LagPursuit"]},

    # Branch: IsDefensiveSituation → action (replaces per-tick BarrelRoll default)
    "include_is_defensive":   {"type": "discrete", "choices": [True, False]},
    "is_defensive_action":    {"type": "discrete", "choices": ["BarrelRoll", "BreakTurn", "DefensiveManeuver", "DefensiveSpiral"]},
}

OPPONENTS = ["ace", "aggressive", "simple", "defensive", "eagle1", "viper1"]


# ============================================================
# Analysis Helpers (Stage 1 report)
# ============================================================

def _spearman(x, y):
    """Spearman rank correlation (pure Python, no scipy dependency)."""
    n = len(x)
    if n < 3:
        return 0.0

    def _rank(data):
        order = sorted(range(n), key=lambda i: data[i])
        ranks = [0.0] * n
        for rank, idx in enumerate(order):
            ranks[idx] = float(rank + 1)
        return ranks

    rx, ry = _rank(x), _rank(y)
    mean_rx = sum(rx) / n
    mean_ry = sum(ry) / n
    num = sum((rx[i] - mean_rx) * (ry[i] - mean_ry) for i in range(n))
    den = (sum((r - mean_rx) ** 2 for r in rx) * sum((r - mean_ry) ** 2 for r in ry)) ** 0.5
    return num / den if den > 0 else 0.0


def print_param_analysis(explore_results, save_path=None):
    """
    Print parameter correlation analysis after Stage 1 LHS.

    Analyzes 200+ candidates to surface which parameters drive performance:
      [1] Spearman ρ: each continuous param vs total score
      [2] Discrete params: mean score per choice
      [3] offensive_press_distance bins vs ace/aggressive score
      [4] Top-25% vs Bottom-25% discrete param distribution

    If save_path is provided, also writes the report to that file.
    """
    results = [r for r in explore_results if r is not None]
    if len(results) < 10:
        print("  Too few results for parameter analysis.")
        return

    lines = []  # collect lines for optional file save

    def out(s=""):
        print(s)
        lines.append(s)

    out(f"\n{'='*60}")
    out(f"  STAGE 1 PARAMETER ANALYSIS ({len(results)} candidates)")
    out(f"{'='*60}\n")

    # ── [1] Spearman correlation: continuous params vs total score ──
    cont_params = [
        "hard_deck_threshold", "climb_target", "wez_ata_threshold",
        "threat_aa_threshold", "threat_distance", "close_combat_distance",
        "altitude_advantage_target", "pnattack_kp", "pnattack_kd",
        "enemy_wez_distance", "enemy_wez_los", "offensive_press_distance",
    ]
    out("  [1] Spearman rho: continuous param vs total score (|rho| sorted)")
    out(f"  {'Parameter':<28} {'rho':>7}  bar")
    out(f"  {'-'*50}")
    correlations = []
    for pname in cont_params:
        xs, ys = [], []
        for r in results:
            v = r["params"].get(pname)
            if v is not None and isinstance(v, (int, float)):
                xs.append(float(v))
                ys.append(r["score"])
        if len(xs) < 5:
            continue
        rho = _spearman(xs, ys)
        correlations.append((pname, rho))
    correlations.sort(key=lambda x: abs(x[1]), reverse=True)
    for pname, rho in correlations:
        bar = "#" * int(abs(rho) * 20)
        sign = "+" if rho >= 0 else "-"
        out(f"  {pname:<28} {sign}{abs(rho):.3f}  {bar}")

    # ── [2] Discrete params: mean score per choice ──
    disc_params = [
        ("default_action",           ["Pursue", "LeadPursuit", "LagPursuit"]),
        ("close_action",             ["LeadPursuit", "Pursue", "LagPursuit", "PurePursuit"]),
        ("defense_action",           ["BreakTurn", "DefensiveManeuver", "DefensiveSpiral", "BarrelRoll"]),
        ("offensive_press_action",   ["LeadPursuit", "Pursue", "LagPursuit"]),
        ("include_emergency_defense",[True, False]),
        ("include_altitude_far",     [True, False]),
        ("include_enemy_wez",        [True, False]),
        ("include_offensive_press",  [True, False]),
        ("include_is_defensive",     [True, False]),
    ]
    out(f"\n  [2] Discrete params: mean score per choice")
    for pname, choices in disc_params:
        rows = []
        for choice in choices:
            grp = [r["score"] for r in results if r["params"].get(pname) == choice]
            if grp:
                rows.append((str(choice), len(grp), sum(grp) / len(grp)))
        if not rows:
            continue
        out(f"  {pname}:")
        for label, n, mean in rows:
            bar = "#" * max(0, int(mean / 3))
            out(f"    {label:<22} n={n:3d}  mean={mean:7.2f}  {bar}")

    # ── [3] offensive_press_distance bins vs ace/aggressive ──
    press_results = [r for r in results if r["params"].get("include_offensive_press") is True]
    if press_results:
        out(f"\n  [3] offensive_press_distance vs ace/aggressive "
            f"(n={len(press_results)} with include_offensive_press=True)")
        bins = [(914, 2000), (2000, 3000), (3000, 4000), (4000, 5001)]
        for lo, hi in bins:
            grp = [r for r in press_results
                   if lo <= r["params"].get("offensive_press_distance", 0) < hi]
            if not grp:
                continue
            ace_scores, agg_scores = [], []
            for r in grp:
                for opp_key, bucket in [("ace", ace_scores), ("aggressive", agg_scores)]:
                    d = r["details"].get(opp_key, {})
                    s = (d.get("wins", 0) * WIN_BASE
                         + d.get("draws", 0) * DRAW_BASE
                         + d.get("losses", 0) * LOSS_BASE)
                    bucket.append(s)
            ace_mean = sum(ace_scores) / len(ace_scores) if ace_scores else 0.0
            agg_mean = sum(agg_scores) / len(agg_scores) if agg_scores else 0.0
            out(f"    dist [{lo:4d},{hi-1:4d}]:  "
                f"n={len(grp):3d}  ace={ace_mean:6.2f}  agg={agg_mean:6.2f}  "
                f"sum={ace_mean+agg_mean:6.2f}")
    else:
        out(f"\n  [3] No candidates with include_offensive_press=True -- skipping distance analysis")

    # ── [4] Top-25% vs Bottom-25%: discrete param distribution ──
    sorted_r = sorted(results, key=lambda x: x["score"], reverse=True)
    cutoff = max(1, len(sorted_r) // 4)
    top_q = sorted_r[:cutoff]
    bot_q = sorted_r[-cutoff:]
    out(f"\n  [4] Top-25% (n={len(top_q)}) vs Bottom-25% (n={len(bot_q)}) "
        f"-- discrete params (delta >= 15% shown)")
    out(f"  {'param=value':<38}  top%   bot%   delta")
    out(f"  {'-'*58}")
    any_shown = False
    for pname, choices in disc_params:
        for choice in choices:
            t = sum(1 for r in top_q if r["params"].get(pname) == choice)
            b = sum(1 for r in bot_q if r["params"].get(pname) == choice)
            t_pct = t / len(top_q) * 100
            b_pct = b / len(bot_q) * 100
            delta = t_pct - b_pct
            if abs(delta) >= 15:
                marker = "<<<" if abs(delta) >= 30 else ("<<" if abs(delta) >= 20 else "<")
                key = f"{pname}={choice}"
                out(f"  {key:<38} {t_pct:5.0f}%  {b_pct:5.0f}%  {delta:+5.0f}%  {marker}")
                any_shown = True
    if not any_shown:
        out("  (no discrete param shows delta >= 15% between top/bottom quartiles)")

    out(f"\n{'='*60}")
    out(f"  END OF PARAMETER ANALYSIS")
    out(f"{'='*60}\n")

    # ── Save to file if requested ──
    if save_path is not None:
        save_path = Path(save_path)
        save_path.parent.mkdir(parents=True, exist_ok=True)
        with open(save_path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))
        print(f"  [Analysis saved to: {save_path}]")


# ============================================================
# Parameter Sampling
# ============================================================

def perturb_params(params, scale=0.15, rng=None):
    """Create a neighbor by perturbing continuous params and occasionally flipping discrete ones."""
    if rng is None:
        rng = np.random.default_rng()

    new_params = deepcopy(params)
    for name, spec in PARAM_SPACE.items():
        if spec["type"] == "continuous":
            lo, hi = spec["range"]
            delta = (hi - lo) * scale * rng.normal()
            new_val = float(np.clip(params[name] + delta, lo, hi))
            new_params[name] = new_val
        elif spec["type"] == "discrete":
            if rng.random() < 0.15:  # 15% chance to flip
                idx = int(rng.integers(0, len(spec["choices"])))
                new_params[name] = spec["choices"][idx]
    return new_params


def latin_hypercube_sample(n_samples, rng=None):
    """Generate n_samples using Latin Hypercube Sampling for better coverage."""
    if rng is None:
        rng = np.random.default_rng()

    continuous_params = [(name, spec) for name, spec in PARAM_SPACE.items()
                         if spec["type"] == "continuous"]
    discrete_params = [(name, spec) for name, spec in PARAM_SPACE.items()
                       if spec["type"] == "discrete"]

    n_cont = len(continuous_params)
    # LHS: divide each dimension into n_samples strata
    lhs_matrix = np.zeros((n_samples, n_cont))
    for j in range(n_cont):
        perm = rng.permutation(n_samples)
        for i in range(n_samples):
            lhs_matrix[i, j] = (perm[i] + rng.random()) / n_samples

    samples = []
    for i in range(n_samples):
        params = {}
        for j, (name, spec) in enumerate(continuous_params):
            lo, hi = spec["range"]
            params[name] = float(lo + (hi - lo) * lhs_matrix[i, j])

        for name, spec in discrete_params:
            idx = int(rng.integers(0, len(spec["choices"])))
            params[name] = spec["choices"][idx]

        samples.append(params)
    return samples


# ============================================================
# BT Template Generation
# ============================================================

def generate_bt_yaml(params):
    """Convert parameter dict -> BT YAML dict.

    Branch order (priority):
      1. HardDeckAvoidance      (always)
      2. GunEngagement          (always)
      3. InEnemyWEZ → BreakTurn (optional: include_enemy_wez)
      4. OffensivePress         (optional: include_offensive_press)
      5. EmergencyDefense       (optional: include_emergency_defense)
      6. CloseCombat            (always)
      7. IsDefensiveSituation   (optional: include_is_defensive)
      8. default_action [+ optional AltitudeAdvantage]
    """
    children = []

    # 1. Hard Deck Avoidance (always present)
    children.append({
        "type": "Sequence",
        "name": "HardDeckAvoidance",
        "children": [
            {"type": "Condition", "name": "BelowHardDeck",
             "params": {"threshold": int(params["hard_deck_threshold"])}},
            {"type": "Action", "name": "ClimbTo",
             "params": {"target_altitude": int(params["climb_target"])}},
        ]
    })

    # 2. Gun WEZ Engagement (always present)
    children.append({
        "type": "Sequence",
        "name": "GunEngagement",
        "children": [
            {"type": "Condition", "name": "DistanceBelow", "params": {"threshold": 914}},
            {"type": "Condition", "name": "DistanceAbove", "params": {"threshold": 152}},
            {"type": "Condition", "name": "ATABelow",
             "params": {"threshold": round(float(params["wez_ata_threshold"]), 1)}},
            {"type": "Action", "name": "PNAttack"},
        ]
    })

    # 3. InEnemyWEZ → BreakTurn (optional)
    #    Evade immediately when opponent has us in their gun sight.
    if params.get("include_enemy_wez", False):
        children.append({
            "type": "Sequence",
            "name": "ThreatResponse",
            "children": [
                {"type": "Condition", "name": "InEnemyWEZ",
                 "params": {
                     "max_distance": round(float(params["enemy_wez_distance"]), 0),
                     "max_los_angle": round(float(params["enemy_wez_los"]), 1),
                 }},
                {"type": "Action", "name": "BreakTurn"},
            ]
        })

    # 4. OffensivePress: dist < offensive_press_distance AND IsOffensiveSituation → action
    #    KEY: offensive_press_distance controls ACE vs AGGRESSIVE tradeoff.
    #    Full range (914→5000) explored; optimizer finds sweet spot.
    if params.get("include_offensive_press", False):
        children.append({
            "type": "Sequence",
            "name": "OffensivePress",
            "children": [
                {"type": "Condition", "name": "DistanceBelow",
                 "params": {"threshold": int(params["offensive_press_distance"])}},
                {"type": "Condition", "name": "IsOffensiveSituation"},
                {"type": "Action", "name": params.get("offensive_press_action", "LeadPursuit")},
            ]
        })

    # 5. Emergency Defense (optional, classic UnderThreat-based)
    if params["include_emergency_defense"]:
        children.append({
            "type": "Sequence",
            "name": "EmergencyDefense",
            "children": [
                {"type": "Condition", "name": "UnderThreat",
                 "params": {"aa_threshold": float(params["threat_aa_threshold"])}},
                {"type": "Condition", "name": "DistanceBelow",
                 "params": {"threshold": int(params["threat_distance"])}},
                {"type": "Action", "name": params["defense_action"]},
            ]
        })

    # 6. Close Combat (always present)
    children.append({
        "type": "Sequence",
        "name": "CloseCombat",
        "children": [
            {"type": "Condition", "name": "DistanceBelow",
             "params": {"threshold": int(params["close_combat_distance"])}},
            {"type": "Action", "name": params["close_action"]},
        ]
    })

    # 7. IsDefensiveSituation → action (optional, BFM composite condition)
    if params.get("include_is_defensive", False):
        children.append({
            "type": "Sequence",
            "name": "DefensiveEvasion",
            "children": [
                {"type": "Condition", "name": "IsDefensiveSituation"},
                {"type": "Action", "name": params.get("is_defensive_action", "BarrelRoll")},
            ]
        })

    # 8. Default action (with optional altitude advantage)
    if params["include_altitude_far"]:
        children.append({
            "type": "Parallel",
            "name": "FarPursuitWithAltitude",
            "policy": "SuccessOnOne",
            "children": [
                {"type": "Action", "name": params["default_action"]},
                {"type": "Action", "name": "AltitudeAdvantage",
                 "params": {"target_advantage": int(params["altitude_advantage_target"])}},
            ]
        })
    else:
        children.append({
            "type": "Action",
            "name": params["default_action"],
        })

    tree = {
        "name": "alpha1",
        "version": "opt",
        "description": "Optimizer-generated BT",
        "tree": {
            "type": "Selector",
            "children": children,
        }
    }
    return tree


def save_bt_yaml(bt_dict, path):
    """Save BT dict as YAML file."""
    with open(path, 'w', encoding='utf-8') as f:
        yaml.dump(bt_dict, f, default_flow_style=False, allow_unicode=True, sort_keys=False)


# ============================================================
# Fitness Evaluation — Hierarchical Scoring
# ============================================================

def compute_match_score(winner, our_hp, their_hp):
    """Compute score for a single match using hierarchical scoring.

    Hierarchy (guaranteed non-overlapping):
      WIN:  [8.0, 12.0]   — base 10 + hp_shape * 2
      DRAW: [-1.0, 3.0]   — base 1  + hp_shape * 2
      LOSS: [-7.0, -3.0]  — base -5 + hp_shape * 2

    hp_shape = (our_hp - their_hp) / 100.0, clamped to [-1, 1]
    """
    hp_diff = float(our_hp - their_hp) / 100.0
    hp_diff = max(-1.0, min(1.0, hp_diff))

    if winner == "tree1":
        return WIN_BASE + hp_diff * HP_WEIGHT
    elif winner == "draw":
        return DRAW_BASE + hp_diff * HP_WEIGHT
    else:  # tree2 or unknown = loss
        return LOSS_BASE + hp_diff * HP_WEIGHT


def evaluate_fitness(params, rounds_per_opponent=1, worker_id=None, verbose=False):
    """
    Evaluate a parameter set against all opponents.
    Returns (total_score, details_dict).

    Uses hierarchical scoring: W/D/L dominant, HP provides gradient.
    worker_id: unique ID for temp file (multiprocessing safe).
    """
    # Generate and save temp BT with unique name per worker
    bt_dict = generate_bt_yaml(params)
    suffix = f"_{worker_id}" if worker_id is not None else f"_{os.getpid()}"
    # 임시 파일을 logs 폴더에 저장 (submissions 폴더 오염 방지)
    temp_dir = PROJECT_ROOT / "logs" / "temp_bt"
    temp_dir.mkdir(parents=True, exist_ok=True)
    temp_path = temp_dir / f"_temp_opt{suffix}.yaml"
    save_bt_yaml(bt_dict, temp_path)

    total_score = 0.0
    details = {}

    for opponent in OPPONENTS:
        try:
            results = run_match(
                agent1=str(temp_path),
                agent2=opponent,
                rounds=rounds_per_opponent,
                verbose=False,
                save_replay=False,  # no disk I/O during optimization
            )
        except Exception as e:
            if verbose:
                print(f"  Error vs {opponent}: {e}")
            details[opponent] = {
                "wins": 0, "draws": 0, "losses": rounds_per_opponent,
                "score": LOSS_BASE * rounds_per_opponent,
                "avg_hp_diff": 0.0,
            }
            total_score += LOSS_BASE * rounds_per_opponent
            continue

        wins = sum(1 for r in results if r.get("winner") == "tree1")
        draws = sum(1 for r in results if r.get("winner") == "draw")
        losses = rounds_per_opponent - wins - draws

        # Compute per-round scores using actual HP
        opponent_score = 0.0
        total_hp_diff = 0.0
        for r in results:
            our_hp = r.get("tree1_health", 100.0)
            their_hp = r.get("tree2_health", 100.0)
            winner = r.get("winner", "unknown")
            opponent_score += compute_match_score(winner, our_hp, their_hp)
            total_hp_diff += (our_hp - their_hp)

        avg_hp_diff = total_hp_diff / max(1, len(results))
        total_score += opponent_score

        details[opponent] = {
            "wins": wins, "draws": draws, "losses": losses,
            "score": round(opponent_score, 2),
            "avg_hp_diff": round(avg_hp_diff, 1),
        }

    # Clean up temp file
    try:
        temp_path.unlink()
    except Exception:
        pass

    return total_score, details


def _eval_worker(args):
    """Worker function for multiprocessing. Returns (index, score, details)."""
    idx, params, rounds_per_opponent = args
    score, details = evaluate_fitness(params, rounds_per_opponent=rounds_per_opponent)
    return idx, score, details


# ============================================================
# Single-Pass Search: LHS Explore + Top-K Refine
# ============================================================

def run_search(n_candidates=200, n_refine_neighbors=15, n_workers=None, seed=42):
    """
    Single-pass parallel search.
      1. LHS exploration (n_candidates) — 1 round, parallel
      2. Top-10 refinement (n_refine_neighbors each) — 2 rounds, parallel
      3. Top-3 validation — 3 rounds, sequential
    """
    if n_workers is None:
        n_workers = max(1, mp.cpu_count() - 1)  # leave 1 core free

    run_ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    rng = np.random.default_rng(seed)
    total_start = time.time()

    # ── Stage 1: Broad LHS Exploration (parallel) ──
    print(f"\n{'='*60}")
    print(f"  Stage 1: LHS Exploration ({n_candidates} candidates, 2 rounds)")
    print(f"  Workers: {n_workers}")
    print(f"{'='*60}\n")

    candidates = latin_hypercube_sample(n_candidates, rng)

    # ── Known-good baseline seeds (inserted at front for guaranteed coverage) ──

    # v6 best (17W/1D/0L — current champion, no new branches)
    v6_best = {
        "hard_deck_threshold": 1473.5,
        "climb_target": 3191.2,
        "wez_ata_threshold": 3.96,
        "threat_aa_threshold": 151.6,
        "threat_distance": 1135.3,
        "close_combat_distance": 2931.6,
        "altitude_advantage_target": 647.3,
        "pnattack_kp": 0.971,
        "pnattack_kd": 0.453,
        "close_action": "LeadPursuit",
        "default_action": "LagPursuit",
        "defense_action": "BarrelRoll",
        "include_emergency_defense": False,
        "include_altitude_far": False,
        # New params: disabled (pure v6 baseline)
        "include_enemy_wez": False,
        "enemy_wez_distance": 700.0,
        "enemy_wez_los": 15.0,
        "include_offensive_press": False,
        "offensive_press_distance": 3000.0,
        "offensive_press_action": "LeadPursuit",
        "include_is_defensive": False,
        "is_defensive_action": "BarrelRoll",
    }

    # v7.2-like: v6 + IsOffensiveSituation unrestricted (ace 3W, aggressive 3D)
    # Provides optimizer with a known ace-improvement seed to refine from
    v72_seed = {
        "hard_deck_threshold": 1473.5,
        "climb_target": 3191.2,
        "wez_ata_threshold": 3.96,
        "threat_aa_threshold": 151.6,
        "threat_distance": 1135.3,
        "close_combat_distance": 2931.6,
        "altitude_advantage_target": 647.3,
        "pnattack_kp": 0.971,
        "pnattack_kd": 0.453,
        "close_action": "LeadPursuit",
        "default_action": "LagPursuit",
        "defense_action": "BarrelRoll",
        "include_emergency_defense": False,
        "include_altitude_far": False,
        # OffensivePress at full range (= unrestricted IsOffensiveSituation)
        "include_enemy_wez": False,
        "enemy_wez_distance": 700.0,
        "enemy_wez_los": 15.0,
        "include_offensive_press": True,
        "offensive_press_distance": 4999.0,   # effectively unrestricted
        "offensive_press_action": "LeadPursuit",
        "include_is_defensive": False,
        "is_defensive_action": "BarrelRoll",
    }

    # v7.1-like: v6 + InEnemyWEZ + IsOffensiveSituation unrestricted
    v71_seed = {
        "hard_deck_threshold": 1473.5,
        "climb_target": 3191.2,
        "wez_ata_threshold": 3.96,
        "threat_aa_threshold": 151.6,
        "threat_distance": 1135.3,
        "close_combat_distance": 2931.6,
        "altitude_advantage_target": 647.3,
        "pnattack_kp": 0.971,
        "pnattack_kd": 0.453,
        "close_action": "LeadPursuit",
        "default_action": "LagPursuit",
        "defense_action": "BarrelRoll",
        "include_emergency_defense": False,
        "include_altitude_far": False,
        "include_enemy_wez": True,
        "enemy_wez_distance": 700.0,
        "enemy_wez_los": 15.0,
        "include_offensive_press": True,
        "offensive_press_distance": 4999.0,
        "offensive_press_action": "LeadPursuit",
        "include_is_defensive": False,
        "is_defensive_action": "BarrelRoll",
    }

    # Phase-A best (pre-v6, kept for diversity)
    phase_a_best = {
        "hard_deck_threshold": 980.0,
        "climb_target": 2513.0,
        "wez_ata_threshold": 3.7,
        "threat_aa_threshold": 136.2,
        "threat_distance": 1163.0,
        "close_combat_distance": 3871.0,
        "altitude_advantage_target": 201.0,
        "pnattack_kp": 1.42,
        "pnattack_kd": 0.42,
        "close_action": "LeadPursuit",
        "default_action": "LeadPursuit",
        "defense_action": "BarrelRoll",
        "include_emergency_defense": True,
        "include_altitude_far": False,
        "include_enemy_wez": False,
        "enemy_wez_distance": 700.0,
        "enemy_wez_los": 15.0,
        "include_offensive_press": False,
        "offensive_press_distance": 3000.0,
        "offensive_press_action": "LeadPursuit",
        "include_is_defensive": False,
        "is_defensive_action": "BarrelRoll",
    }

    candidates.insert(0, v6_best)
    candidates.insert(1, v72_seed)
    candidates.insert(2, v71_seed)
    candidates.insert(3, phase_a_best)

    # Parallel evaluation — 2 rounds for noise reduction in screening
    work_items = [(i, params, 2) for i, params in enumerate(candidates)]
    explore_results = [None] * len(candidates)

    stage1_start = time.time()
    with mp.Pool(processes=n_workers) as pool:
        for idx, score, details in pool.imap_unordered(_eval_worker, work_items):
            explore_results[idx] = {"params": candidates[idx], "score": score, "details": details}

            wins = sum(d["wins"] for d in details.values())
            draws = sum(d["draws"] for d in details.values())
            losses = sum(d["losses"] for d in details.values())

            done = sum(1 for r in explore_results if r is not None)
            print(f"  [{done:3d}/{len(candidates)}] #{idx+1} score={score:7.2f}  "
                  f"W/D/L={wins}/{draws}/{losses}", flush=True)

    stage1_elapsed = time.time() - stage1_start
    explore_results = [r for r in explore_results if r is not None]
    explore_results.sort(key=lambda x: x["score"], reverse=True)
    print(f"\n  Stage 1 done in {stage1_elapsed/60:.1f}min. Best: {explore_results[0]['score']:.2f}")

    # ── Stage 1 Parameter Analysis Report ──
    logs_dir = PROJECT_ROOT / "logs"
    logs_dir.mkdir(exist_ok=True)
    analysis_path = logs_dir / f"param_analysis_{run_ts}.txt"
    print_param_analysis(explore_results, save_path=analysis_path)

    # ── Stage 2: Refine Top-10 (parallel) ──
    top_k = 10
    print(f"\n{'='*60}")
    print(f"  Stage 2: Refine Top-{top_k} ({n_refine_neighbors} neighbors, 3 rounds)")
    print(f"{'='*60}\n")

    refine_candidates = []
    for ci in range(min(top_k, len(explore_results))):
        base_params = explore_results[ci]["params"]
        refine_candidates.append(base_params)  # re-evaluate base too
        for _ in range(n_refine_neighbors):
            refine_candidates.append(perturb_params(base_params, scale=0.12, rng=rng))

    work_items = [(i, params, 3) for i, params in enumerate(refine_candidates)]
    refine_results = [None] * len(refine_candidates)

    stage2_start = time.time()
    with mp.Pool(processes=n_workers) as pool:
        for idx, score, details in pool.imap_unordered(_eval_worker, work_items):
            refine_results[idx] = {"params": refine_candidates[idx], "score": score, "details": details}

            wins = sum(d["wins"] for d in details.values())
            draws = sum(d["draws"] for d in details.values())
            losses = 18 - wins - draws  # 6 opponents × 3 rounds

            done = sum(1 for r in refine_results if r is not None)
            print(f"  [{done:3d}/{len(refine_candidates)}] score={score:7.2f}  "
                  f"W/D/L={wins}/{draws}/{losses}", flush=True)

    stage2_elapsed = time.time() - stage2_start
    refine_results = [r for r in refine_results if r is not None]
    refine_results.sort(key=lambda x: x["score"], reverse=True)
    print(f"\n  Stage 2 done in {stage2_elapsed/60:.1f}min. Best: {refine_results[0]['score']:.2f}")

    # ── Stage 3: Validate Top-5 (sequential, 5 rounds) ──
    top_validate = 5
    stage3_rounds = 5
    print(f"\n{'='*60}")
    print(f"  Stage 3: Validate Top-{top_validate} ({stage3_rounds} rounds each)")
    print(f"{'='*60}\n")

    final_results = []
    for vi in range(min(top_validate, len(refine_results))):
        params = refine_results[vi]["params"]
        score, details = evaluate_fitness(params, rounds_per_opponent=stage3_rounds)
        final_results.append({"params": params, "score": score, "details": details})

        n_rounds_total = stage3_rounds * len(OPPONENTS)
        wins = sum(d["wins"] for d in details.values())
        draws = sum(d["draws"] for d in details.values())
        losses = n_rounds_total - wins - draws
        print(f"  #{vi+1}: score={score:.2f}  W/D/L={wins}/{draws}/{losses}")
        for opp, d in details.items():
            w, dr, lo = d["wins"], d["draws"], d["losses"]
            hp = d.get("avg_hp_diff", 0)
            tag = "W" if w > lo else ("D" if w == lo and dr > 0 else "L")
            print(f"      vs {opp:12s}: {w}W {dr}D {lo}L  hp_diff={hp:+.0f}  [{tag}]")

    final_results.sort(key=lambda x: x["score"], reverse=True)

    total_elapsed = time.time() - total_start
    print(f"\n{'='*60}")
    print(f"  Search Complete! ({total_elapsed/60:.1f} min)")
    print(f"  Best score: {final_results[0]['score']:.2f}")
    print(f"{'='*60}\n")

    # Save all results — timestamped (history) + latest (for --backtest/--roundrobin)
    serializable = []
    for r in final_results:
        serializable.append({"score": r["score"], "params": r["params"], "details": r["details"]})

    logs_dir = PROJECT_ROOT / "logs"
    logs_dir.mkdir(exist_ok=True)
    ts_path     = logs_dir / f"opt_results_{run_ts}.json"
    latest_path = logs_dir / "opt_results.json"

    for path in [ts_path, latest_path]:
        with open(path, 'w') as f:
            json.dump(serializable, f, indent=2, default=str)

    print(f"  Results saved to: {ts_path}")
    print(f"  Latest copy:      {latest_path}")

    return final_results


# ============================================================
# Validation & Tournament (unchanged logic, new scoring)
# ============================================================

def run_backtest(rounds=20):
    """
    Rigorous back-validation of the best candidate.

    Runs `rounds` matches per opponent (default: 20) to confirm the
    Stage 3 winner is stable — not a lucky artifact of small sample size.

    Also compares against v6 baseline on the same rounds.

    Usage:
        python tools/bt_optimizer.py --backtest --rounds 20
    """
    print(f"\n{'='*60}")
    print(f"  BACK-TEST: Rigorous Validation ({rounds} rounds per opponent)")
    print(f"  Total matches: {rounds * len(OPPONENTS)} per agent")
    print(f"{'='*60}\n")

    # Load optimization results
    logs_dir = PROJECT_ROOT / "logs"
    for path in [logs_dir / "opt_results.json",
                 logs_dir / "opt_phase_b_results.json",
                 logs_dir / "opt_phase_a_results.json"]:
        if path.exists():
            with open(path) as f:
                data = json.load(f)
            print(f"  Loaded from: {path.name}")
            break
    else:
        print("No optimization results found! Run optimizer first.")
        return

    best_params = data[0]["params"]
    print(f"  Optimizer score (Stage 3): {data[0]['score']:.2f}\n")
    print(f"  Params: {json.dumps(best_params, indent=4, default=str)}\n")

    # ── Evaluate best candidate ──
    print(f"  [1/2] Testing optimizer best candidate ({rounds} rounds)...")
    best_score, best_details = evaluate_fitness(best_params, rounds_per_opponent=rounds, verbose=True)

    best_wins  = sum(d["wins"]   for d in best_details.values())
    best_draws = sum(d["draws"]  for d in best_details.values())
    best_losses = rounds * len(OPPONENTS) - best_wins - best_draws

    print(f"\n  BEST CANDIDATE: {best_wins}W {best_draws}D {best_losses}L  (score={best_score:.2f})")
    for opp, d in best_details.items():
        hp = d.get("avg_hp_diff", 0)
        tag = "WIN" if d["wins"] > d["losses"] else ("DRAW" if d["wins"] == d["losses"] else "LOSE")
        print(f"    vs {opp:12s}: {d['wins']}W {d['draws']}D {d['losses']}L  hp={hp:+.1f}  [{tag}]")

    # ── Evaluate v6 baseline for comparison ──
    print(f"\n  [2/2] Testing v6 baseline ({rounds} rounds)...")
    v6_path = PROJECT_ROOT / "submissions" / "alpha1" / "alpha1.yaml"
    from scripts.run_match import run_match as _run_match

    v6_wins = v6_draws = v6_losses = 0
    v6_details = {}
    for opp in OPPONENTS:
        try:
            results = _run_match(
                agent1=str(v6_path),
                agent2=opp,
                rounds=rounds,
                verbose=False,
                save_replay=False,
            )
        except Exception as e:
            print(f"    v6 vs {opp}: error ({e})")
            v6_details[opp] = {"wins": 0, "draws": 0, "losses": rounds, "avg_hp_diff": 0.0}
            v6_losses += rounds
            continue

        w  = sum(1 for r in results if r.get("winner") == "tree1")
        dr = sum(1 for r in results if r.get("winner") == "draw")
        lo = rounds - w - dr
        hp_d = sum(r.get("tree1_health", 100) - r.get("tree2_health", 100) for r in results) / max(1, len(results))
        v6_details[opp] = {"wins": w, "draws": dr, "losses": lo, "avg_hp_diff": hp_d}
        v6_wins += w; v6_draws += dr; v6_losses += lo

    print(f"\n  V6 BASELINE: {v6_wins}W {v6_draws}D {v6_losses}L")
    for opp, d in v6_details.items():
        hp = d.get("avg_hp_diff", 0)
        tag = "WIN" if d["wins"] > d["losses"] else ("DRAW" if d["wins"] == d["losses"] else "LOSE")
        print(f"    vs {opp:12s}: {d['wins']}W {d['draws']}D {d['losses']}L  hp={hp:+.1f}  [{tag}]")

    # ── Summary comparison ──
    print(f"\n{'='*60}")
    print(f"  COMPARISON ({rounds} rounds × {len(OPPONENTS)} opponents = {rounds*len(OPPONENTS)} matches each)")
    print(f"{'='*60}")
    print(f"  Best candidate : {best_wins:2d}W {best_draws:2d}D {best_losses:2d}L  score={best_score:.2f}")
    print(f"  v6 baseline    : {v6_wins:2d}W {v6_draws:2d}D {v6_losses:2d}L")
    if best_wins > v6_wins or (best_wins == v6_wins and best_draws < v6_draws):
        print(f"  => BEST CANDIDATE WINS  (+{best_wins-v6_wins}W, {best_draws-v6_draws:+d}D)")
    elif best_wins == v6_wins and best_draws == v6_draws:
        print(f"  => TIE (same record)")
    else:
        print(f"  => v6 STILL BETTER  ({v6_wins-best_wins}W advantage)")

    # Save backtest result
    bt_ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    logs_dir = PROJECT_ROOT / "logs"
    logs_dir.mkdir(exist_ok=True)
    bt_output = logs_dir / "backtest_results.json"
    with open(bt_output, "w") as f:
        json.dump({
            "rounds_per_opponent": rounds,
            "best_candidate": {
                "score": best_score,
                "total": f"{best_wins}W/{best_draws}D/{best_losses}L",
                "per_opponent": best_details,
                "params": best_params,
            },
            "v6_baseline": {
                "total": f"{v6_wins}W/{v6_draws}D/{v6_losses}L",
                "per_opponent": v6_details,
            }
        }, f, indent=2, default=str)
    print(f"\n  Saved backtest to: {bt_output}")

    # Save best candidate YAML permanently (timestamped)
    bt_dict = generate_bt_yaml(best_params)
    yaml_ts_path = logs_dir / f"best_candidate_{bt_ts}.yaml"
    save_bt_yaml(bt_dict, str(yaml_ts_path))
    print(f"  Saved best candidate YAML: {yaml_ts_path}")


def run_validation(rounds=5):
    """Validate the best BT with more rounds."""
    print(f"\n{'='*60}")
    print(f"  Validation ({rounds} rounds per opponent)")
    print(f"{'='*60}\n")

    # Load best results
    logs_dir = PROJECT_ROOT / "logs"
    for path in [logs_dir / "opt_results.json",
                 logs_dir / "opt_phase_b_results.json",
                 logs_dir / "opt_phase_a_results.json"]:
        if path.exists():
            with open(path) as f:
                data = json.load(f)
            print(f"  Loaded from: {path.name}")
            break
    else:
        print("No optimization results found!")
        return

    best_params = data[0]["params"]
    print(f"  Previous score: {data[0]['score']:.2f}")

    score, details = evaluate_fitness(best_params, rounds_per_opponent=rounds, verbose=True)

    total_wins = sum(d["wins"] for d in details.values())
    total_draws = sum(d["draws"] for d in details.values())
    total_losses = sum(d["losses"] for d in details.values())

    print(f"\nValidation Results:")
    print(f"  Total: {total_wins}W {total_draws}D {total_losses}L")
    print(f"  Score: {score:.2f}")
    print(f"\n  Per opponent:")
    for opp, d in details.items():
        hp = d.get("avg_hp_diff", 0)
        print(f"    vs {opp:12s}: {d['wins']}W {d['draws']}D {d['losses']}L  "
              f"hp_diff={hp:+.0f}")

    # Save as the final alpha1.yaml
    bt_dict = generate_bt_yaml(best_params)
    final_path = PROJECT_ROOT / "submissions" / "alpha1" / "alpha1.yaml"
    save_bt_yaml(bt_dict, final_path)
    print(f"\n  Saved best BT to: {final_path}")
    print(f"  Params: {json.dumps(best_params, indent=2, default=str)}")


def run_tournament(agent_path=None, rounds=3):
    """Run a tournament for a specific BT file."""
    if agent_path is None:
        agent_path = str(PROJECT_ROOT / "submissions" / "alpha1" / "alpha1.yaml")

    print(f"\n{'='*60}")
    print(f"  Tournament: {Path(agent_path).name}")
    print(f"  Rounds per opponent: {rounds}")
    print(f"{'='*60}\n")

    total_wins = 0
    total_draws = 0
    total_losses = 0

    for opponent in OPPONENTS:
        results = run_match(
            agent1=agent_path,
            agent2=opponent,
            rounds=rounds,
            verbose=False,
        )

        wins = sum(1 for r in results if r.get("winner") == "tree1")
        draws = sum(1 for r in results if r.get("winner") == "draw")
        losses = rounds - wins - draws

        total_wins += wins
        total_draws += draws
        total_losses += losses

        # Show HP diff
        hp_diffs = []
        for r in results:
            our_hp = r.get("tree1_health", 100.0)
            their_hp = r.get("tree2_health", 100.0)
            hp_diffs.append(our_hp - their_hp)
        avg_hp = sum(hp_diffs) / max(1, len(hp_diffs))

        status = "WIN" if wins > losses else ("DRAW" if wins == losses else "LOSE")
        print(f"  vs {opponent:12s}: {wins}W {draws}D {losses}L  "
              f"hp_diff={avg_hp:+.0f}  [{status}]")

    print(f"\n  Total: {total_wins}W {total_draws}D {total_losses}L")
    points = total_wins * 3 + total_draws * 1
    max_points = len(OPPONENTS) * rounds * 3
    print(f"  Tournament Points: {points}/{max_points} ({points/max_points*100:.0f}%)")


# ============================================================
# Stage 4: Round-Robin Tournament
# ============================================================

def run_roundrobin(rounds=5, save_replay=True):
    """
    Stage 4: True round-robin tournament among top-5 optimizer candidates + v6 baseline.

    Pool: top-5 from opt_results.json + submissions/alpha1/alpha1.yaml (v6)
    Format: all C(6,2)=15 pairings, `rounds` matches each
    Scoring: 3 pts per win, 1 pt per draw, 0 per loss
    Output: tools/roundrobin_results.json

    Usage:
        python tools/bt_optimizer.py --roundrobin --rounds 5
    """
    from itertools import combinations

    print(f"\n{'='*60}")
    print(f"  Stage 4: Round-Robin Tournament ({rounds} rounds/pairing)")
    print(f"  Pool: top-5 optimizer candidates + v6 baseline")
    print(f"  Matchups: {len(list(combinations(range(6), 2)))} pairings × {rounds} rounds")
    print(f"{'='*60}\n")

    # Load optimization results
    logs_dir = PROJECT_ROOT / "logs"
    for path in [logs_dir / "opt_results.json",
                 logs_dir / "opt_phase_b_results.json",
                 logs_dir / "opt_phase_a_results.json"]:
        if path.exists():
            with open(path) as f:
                data = json.load(f)
            print(f"  Loaded: {path.name} ({len(data)} entries)")
            break
    else:
        print("  ERROR: No optimization results found. Run optimizer first.")
        return

    # ── Build agent pool ──
    logs_dir = PROJECT_ROOT / "logs"
    logs_dir.mkdir(exist_ok=True)
    rr_dir = logs_dir / "roundrobin"
    rr_dir.mkdir(exist_ok=True)

    # Copy custom nodes so PNAttack and other custom actions are available
    import shutil
    src_nodes = PROJECT_ROOT / "submissions" / "alpha1" / "nodes"
    dst_nodes = rr_dir / "nodes"
    if src_nodes.exists():
        if dst_nodes.exists():
            shutil.rmtree(str(dst_nodes))
        shutil.copytree(str(src_nodes), str(dst_nodes))

    agents = []  # list of (label, yaml_path_str)
    n_cands = min(5, len(data))
    for i in range(n_cands):
        entry = data[i]
        params = entry["params"]
        bt_dict = generate_bt_yaml(params)
        tmp_path = rr_dir / f"cand_{i+1}.yaml"
        save_bt_yaml(bt_dict, str(tmp_path))
        agents.append((f"cand_{i+1}(s={entry['score']:.1f})", str(tmp_path)))

    v6_path = PROJECT_ROOT / "submissions" / "alpha1" / "alpha1.yaml"
    agents.append(("v6_baseline", str(v6_path)))

    print(f"  Agents ({len(agents)}):")
    for label, path in agents:
        print(f"    {label}  [{Path(path).name}]")

    # ── Round-robin: all C(n,2) pairings (sequential) ──
    n = len(agents)
    pairings = list(combinations(range(n), 2))
    pts    = {i: 0   for i in range(n)}
    record = {i: {"wins": 0, "draws": 0, "losses": 0} for i in range(n)}
    matchup_log = []

    from scripts.run_match import run_match as _rr_match

    print(f"\n  Running {len(pairings)} pairings...")
    for match_idx, (i, j) in enumerate(pairings):
        label_i, path_i = agents[i]
        label_j, path_j = agents[j]
        try:
            results = _rr_match(
                agent1=path_i,
                agent2=path_j,
                rounds=rounds,
                verbose=False,
                save_replay=save_replay,
            )
        except Exception as e:
            print(f"  [{match_idx+1:2d}/{len(pairings)}] {label_i} vs {label_j}: ERROR {e}")
            matchup_log.append({"a": label_i, "b": label_j, "error": str(e)})
            continue

        wi = sum(1 for r in results if r.get("winner") == "tree1")
        wj = sum(1 for r in results if r.get("winner") == "tree2")
        dr = rounds - wi - wj

        pts[i] += wi * 3 + dr
        pts[j] += wj * 3 + dr
        record[i]["wins"]   += wi;  record[i]["draws"] += dr;  record[i]["losses"] += wj
        record[j]["wins"]   += wj;  record[j]["draws"] += dr;  record[j]["losses"] += wi

        matchup_log.append({"a": label_i, "b": label_j,
                             "a_wins": wi, "b_wins": wj, "draws": dr})
        print(f"  [{match_idx+1:2d}/{len(pairings)}] "
              f"{label_i:<32} vs {label_j:<32}  "
              f"-> {wi}W-{dr}D-{wj}L", flush=True)

    # ── Standings ──
    standing = sorted(range(n), key=lambda i: (pts[i], record[i]["wins"]), reverse=True)
    print(f"\n{'='*60}")
    print(f"  FINAL STANDINGS")
    print(f"{'='*60}")
    print(f"  {'#':<4} {'Agent':<35} {'Pts':>4}  W   D   L")
    print(f"  {'-'*58}")
    for rank, idx in enumerate(standing, 1):
        label, _ = agents[idx]
        rec = record[idx]
        p   = pts[idx]
        flag = "  ← v6 baseline" if "v6_baseline" in label else ""
        print(f"  {rank:<4} {label:<35} {p:>4}  {rec['wins']:>3} {rec['draws']:>3} {rec['losses']:>3}{flag}")

    # Show head-to-head of best candidate vs v6
    v6_idx = n - 1  # always last
    best_idx = standing[0] if standing[0] != v6_idx else standing[1]
    best_label, _ = agents[best_idx]
    best_rec = record[best_idx]
    v6_rec   = record[v6_idx]
    print(f"\n  Head-to-head {best_label} vs v6_baseline:")
    for m in matchup_log:
        if ((m.get("a") == best_label and m.get("b") == "v6_baseline") or
                (m.get("b") == best_label and m.get("a") == "v6_baseline")):
            if "error" not in m:
                is_cand_a = m["a"] == best_label
                cw = m["a_wins"] if is_cand_a else m["b_wins"]
                vw = m["b_wins"] if is_cand_a else m["a_wins"]
                d  = m["draws"]
                verdict = "BEATS v6" if cw > vw else ("TIE" if cw == vw else "LOSES to v6")
                print(f"    cand {cw}W / {d}D / v6 {vw}W  [{verdict}]")

    # ── Save ──
    output_path = logs_dir / "roundrobin_results.json"
    with open(output_path, "w") as f:
        json.dump({
            "rounds_per_pairing": rounds,
            "agents": [label for label, _ in agents],
            "standings": [
                {"rank": rank + 1, "name": agents[idx][0],
                 "points": pts[idx], **record[idx]}
                for rank, idx in enumerate(standing)
            ],
            "matchups": matchup_log,
        }, f, indent=2)
    print(f"\n  Saved to: {output_path}")


# ============================================================
# Main
# ============================================================

def main():
    parser = argparse.ArgumentParser(description="BT Optimizer v2")
    parser.add_argument("--candidates", type=int, default=200,
                        help="Number of LHS candidates (default: 200)")
    parser.add_argument("--refine-neighbors", type=int, default=15,
                        help="Neighbors per top candidate in refinement (default: 15)")
    parser.add_argument("--workers", type=int, default=None,
                        help="Number of parallel workers (default: cpu_count - 1)")
    parser.add_argument("--seed", type=int, default=42, help="Random seed")
    parser.add_argument("--validate", action="store_true", help="Validate best BT")
    parser.add_argument("--backtest", action="store_true",
                        help="Rigorous back-test: run best candidate vs v6 baseline (default 20 rounds)")
    parser.add_argument("--roundrobin", action="store_true",
                        help="Stage 4: round-robin among top-5 candidates + v6 baseline (default 5 rounds)")
    parser.add_argument("--tournament", action="store_true", help="Run tournament")
    parser.add_argument("--rounds", type=int, default=5,
                        help="Rounds for validate/tournament/roundrobin; 20 for backtest (default: 5)")
    parser.add_argument("--agent", type=str, default=None, help="Agent path for tournament")
    args = parser.parse_args()

    if args.backtest:
        backtest_rounds = args.rounds if args.rounds != 5 else 20  # default 20 for backtest
        run_backtest(rounds=backtest_rounds)
    elif args.roundrobin:
        run_roundrobin(rounds=args.rounds, save_replay=True)
    elif args.validate:
        run_validation(rounds=args.rounds)
    elif args.tournament:
        run_tournament(agent_path=args.agent, rounds=args.rounds)
    else:
        run_search(
            n_candidates=args.candidates,
            n_refine_neighbors=args.refine_neighbors,
            n_workers=args.workers,
            seed=args.seed,
        )


if __name__ == "__main__":
    mp.freeze_support()  # Windows multiprocessing safety
    main()
