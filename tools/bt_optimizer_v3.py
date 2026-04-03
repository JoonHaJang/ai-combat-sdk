"""
BT Optimizer v3 — CMA-ES + Deterministic 1-Round Evaluation

Key improvements over v2:
  1. CMA-ES replaces LHS+perturb → 3-5x better convergence in 21D space
  2. 1 round per opponent (deterministic sim = no noise) → 3x more unique evals
  3. Discrete params encoded as continuous [0,1] → sliced into choices
  4. Full CSV metadata collection for Phase 1 analysis

Usage:
    python tools/bt_optimizer_v3.py --budget 400              # CMA-ES search
    python tools/bt_optimizer_v3.py --tournament               # Test best
    python tools/bt_optimizer_v3.py --analyze-logs             # Analyze CSV metadata
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
from datetime import datetime

import numpy as np

# Project paths
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from scripts.run_match import run_match

# ============================================================
# Scoring (same hierarchy as v2 for comparison)
# ============================================================

WIN_BASE  = 10.0
DRAW_BASE =  1.0
LOSS_BASE = -5.0
HP_WEIGHT =  2.0

OPPONENTS = ["ace", "aggressive", "simple", "defensive", "eagle1", "viper1"]

# ============================================================
# Parameter Space — CMA-ES Encoding
# ============================================================

# Ordered list of parameters with their encoding info
PARAM_DEFS = [
    # (name, type, range_or_choices)
    # Continuous params: CMA-ES searches in [0,1], scaled to [lo,hi]
    # Discrete params: CMA-ES searches in [0,1], sliced into N bins
    ("hard_deck_threshold",     "cont", (600, 1500)),
    ("climb_target",            "cont", (1500, 4000)),
    ("wez_ata_threshold",       "cont", (3, 12)),
    ("threat_aa_threshold",     "cont", (100, 160)),
    ("threat_distance",         "cont", (400, 1500)),
    ("close_combat_distance",   "cont", (1500, 4000)),
    ("altitude_advantage_target","cont", (200, 800)),
    ("pnattack_kp",             "cont", (0.8, 2.0)),
    ("pnattack_kd",             "cont", (0.2, 0.8)),
    ("enemy_wez_distance",      "cont", (500, 914)),
    ("enemy_wez_los",           "cont", (10, 25)),
    ("offensive_press_distance","cont", (914, 5000)),
    # Discrete params
    ("close_action",            "disc", ["LeadPursuit", "Pursue", "LagPursuit", "PurePursuit"]),
    ("default_action",          "disc", ["Pursue", "LeadPursuit", "LagPursuit"]),
    ("defense_action",          "disc", ["BreakTurn", "DefensiveManeuver", "DefensiveSpiral", "BarrelRoll"]),
    ("include_emergency_defense","disc", [True, False]),
    ("include_altitude_far",    "disc", [True, False]),
    ("include_enemy_wez",       "disc", [True, False]),
    ("include_offensive_press", "disc", [True, False]),
    ("offensive_press_action",  "disc", ["LeadPursuit", "Pursue", "LagPursuit"]),
    ("include_is_defensive",    "disc", [True, False]),
    ("is_defensive_action",     "disc", ["BarrelRoll", "BreakTurn", "DefensiveManeuver", "DefensiveSpiral"]),
]

N_DIMS = len(PARAM_DEFS)  # 21


def vector_to_params(x):
    """Convert CMA-ES vector [0,1]^21 → parameter dict."""
    params = {}
    for i, (name, ptype, spec) in enumerate(PARAM_DEFS):
        val = np.clip(x[i], 0.0, 1.0)
        if ptype == "cont":
            lo, hi = spec
            params[name] = float(lo + (hi - lo) * val)
        else:  # disc
            idx = int(val * len(spec))
            idx = min(idx, len(spec) - 1)
            params[name] = spec[idx]
    return params


def params_to_vector(params):
    """Convert parameter dict → CMA-ES vector [0,1]^21."""
    x = np.zeros(N_DIMS)
    for i, (name, ptype, spec) in enumerate(PARAM_DEFS):
        val = params[name]
        if ptype == "cont":
            lo, hi = spec
            x[i] = (val - lo) / (hi - lo)
        else:
            try:
                idx = spec.index(val)
                x[i] = (idx + 0.5) / len(spec)
            except ValueError:
                x[i] = 0.5
    return x


# ============================================================
# BT Template (reuse v2 logic)
# ============================================================

def generate_bt_yaml(params):
    """Convert parameter dict -> BT YAML dict (same structure as v2)."""
    children = []

    # 1. Hard Deck Avoidance (always)
    children.append({
        "type": "Sequence", "name": "HardDeckAvoidance",
        "children": [
            {"type": "Condition", "name": "BelowHardDeck",
             "params": {"threshold_ft": int(params["hard_deck_threshold"])}},
            {"type": "Action", "name": "ClimbTo",
             "params": {"target_altitude_ft": int(params["climb_target"])}},
        ]
    })

    # 2. Gun WEZ Engagement (always)
    # GunAttack: 표준 노드 (PNAttack은 golden 커스텀 노드 전용)
    children.append({
        "type": "Sequence", "name": "GunEngagement",
        "children": [
            {"type": "Condition", "name": "DistanceBelow", "params": {"threshold_ft": 914}},
            {"type": "Condition", "name": "DistanceAbove", "params": {"threshold_ft": 152}},
            {"type": "Condition", "name": "ATABelow",
             "params": {"threshold_deg": round(float(params["wez_ata_threshold"]), 1)}},
            {"type": "Action", "name": "GunAttack"},
        ]
    })

    # 3. InEnemyWEZ → BreakTurn (optional)
    if params.get("include_enemy_wez", False):
        children.append({
            "type": "Sequence", "name": "ThreatResponse",
            "children": [
                {"type": "Condition", "name": "InEnemyWEZ",
                 "params": {
                     "max_distance_ft": round(float(params["enemy_wez_distance"]), 0),
                     "max_los_angle_deg": round(float(params["enemy_wez_los"]), 1),
                 }},
                {"type": "Action", "name": "BreakTurn"},
            ]
        })

    # 4. OffensivePress (optional)
    if params.get("include_offensive_press", False):
        children.append({
            "type": "Sequence", "name": "OffensivePress",
            "children": [
                {"type": "Condition", "name": "DistanceBelow",
                 "params": {"threshold_ft": int(params["offensive_press_distance"])}},
                {"type": "Condition", "name": "IsOffensiveSituation"},
                {"type": "Action", "name": params.get("offensive_press_action", "LeadPursuit")},
            ]
        })

    # 5. Emergency Defense (optional)
    if params.get("include_emergency_defense", False):
        children.append({
            "type": "Sequence", "name": "EmergencyDefense",
            "children": [
                {"type": "Condition", "name": "UnderThreat",
                 "params": {"aa_threshold_deg": float(params["threat_aa_threshold"])}},
                {"type": "Condition", "name": "DistanceBelow",
                 "params": {"threshold_ft": int(params["threat_distance"])}},
                {"type": "Action", "name": params["defense_action"]},
            ]
        })

    # 6. Close Combat (always)
    children.append({
        "type": "Sequence", "name": "CloseCombat",
        "children": [
            {"type": "Condition", "name": "DistanceBelow",
             "params": {"threshold_ft": int(params["close_combat_distance"])}},
            {"type": "Action", "name": params["close_action"]},
        ]
    })

    # 7. IsDefensiveSituation (optional)
    if params.get("include_is_defensive", False):
        children.append({
            "type": "Sequence", "name": "DefensiveEvasion",
            "children": [
                {"type": "Condition", "name": "IsDefensiveSituation"},
                {"type": "Action", "name": params.get("is_defensive_action", "BarrelRoll")},
            ]
        })

    # 8. Default action
    if params.get("include_altitude_far", False):
        children.append({
            "type": "Parallel", "name": "FarPursuitWithAltitude",
            "policy": "SuccessOnOne",
            "children": [
                {"type": "Action", "name": params["default_action"]},
                {"type": "Action", "name": "AltitudeAdvantage",
                 "params": {"target_advantage_ft": int(params["altitude_advantage_target"])}},
            ]
        })
    else:
        children.append({"type": "Action", "name": params["default_action"]})

    return {
        "name": "alpha1", "version": "opt_v3",
        "description": "CMA-ES optimized BT",
        "tree": {"type": "Selector", "children": children}
    }


def save_bt_yaml(bt_dict, path):
    with open(path, 'w', encoding='utf-8') as f:
        yaml.dump(bt_dict, f, default_flow_style=False, allow_unicode=True, sort_keys=False)


# ============================================================
# Fitness Evaluation — 1 Round (Deterministic)
# ============================================================

def compute_match_score(winner, our_hp, their_hp):
    hp_diff = max(-1.0, min(1.0, float(our_hp - their_hp) / 100.0))
    if winner == "tree1":
        return WIN_BASE + hp_diff * HP_WEIGHT
    elif winner == "draw":
        return DRAW_BASE + hp_diff * HP_WEIGHT
    else:
        return LOSS_BASE + hp_diff * HP_WEIGHT


def evaluate_fitness(params, worker_id=None, collect_csv=False):
    """Evaluate a parameter set: 1 round per opponent (deterministic).

    If collect_csv=True, saves CSV logs for metadata analysis (Phase 1).
    """
    bt_dict = generate_bt_yaml(params)
    suffix = f"_{worker_id}" if worker_id is not None else f"_{os.getpid()}"
    temp_dir = PROJECT_ROOT / "logs" / "temp_bt"
    temp_dir.mkdir(parents=True, exist_ok=True)
    temp_path = temp_dir / f"_temp_v3{suffix}.yaml"
    save_bt_yaml(bt_dict, temp_path)

    total_score = 0.0
    details = {}

    # Phase 1 metadata directory — collect_csv=True 시 per-step CSV + result JSON 저장
    meta_dir = None
    if collect_csv:
        meta_dir = str(PROJECT_ROOT / "logs" / "metadata")

    for opponent in OPPONENTS:
        try:
            results = run_match(
                agent1=str(temp_path),
                agent2=opponent,
                rounds=1,  # deterministic: 1 round is sufficient
                verbose=False,
                metadata_log=meta_dir if collect_csv else None,
            )
        except Exception as e:
            details[opponent] = {"wins": 0, "draws": 0, "losses": 1,
                                 "score": LOSS_BASE, "hp_diff": 0.0}
            total_score += LOSS_BASE
            continue

        if not results:
            details[opponent] = {"wins": 0, "draws": 0, "losses": 1,
                                 "score": LOSS_BASE, "hp_diff": 0.0}
            total_score += LOSS_BASE
            continue

        r = results[0]
        winner = r.get("winner", "unknown")
        our_hp = r.get("tree1_health", 100.0)
        their_hp = r.get("tree2_health", 100.0)
        score = compute_match_score(winner, our_hp, their_hp)
        total_score += score

        w = 1 if winner == "tree1" else 0
        d = 1 if winner == "draw" else 0
        l = 1 - w - d
        details[opponent] = {
            "wins": w, "draws": d, "losses": l,
            "score": round(score, 2),
            "hp_diff": round(our_hp - their_hp, 1),
        }

    try:
        temp_path.unlink()
    except Exception:
        pass

    return total_score, details


def _eval_worker_cma(args):
    """Worker: evaluate a CMA-ES vector."""
    idx, x_vec, collect_csv = args
    params = vector_to_params(x_vec)
    score, details = evaluate_fitness(params, worker_id=idx, collect_csv=collect_csv)
    return idx, score, details, params


# ============================================================
# CMA-ES Search
# ============================================================

def run_cma_search(budget=400, n_workers=None, seed=42, collect_csv=False):
    """
    CMA-ES optimization.

    budget: total number of fitness evaluations
    Each eval = 6 opponents × 1 round × ~6.5s = ~40s
    With parallel workers, wall time = budget/n_workers × 40s
    """
    import cma

    if n_workers is None:
        n_workers = max(1, mp.cpu_count() - 1)

    run_ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    logs_dir = PROJECT_ROOT / "logs"
    logs_dir.mkdir(exist_ok=True)

    print(f"\n{'='*60}")
    print(f"  BT Optimizer v3 — CMA-ES Search")
    print(f"  Budget: {budget} evaluations")
    print(f"  Workers: {n_workers}")
    print(f"  Dimensions: {N_DIMS}")
    print(f"  1 round/opponent (deterministic)")
    print(f"{'='*60}\n")

    # Start from v6 best (known good)
    v6_best = {
        "hard_deck_threshold": 1473.5, "climb_target": 3191.2,
        "wez_ata_threshold": 3.96, "threat_aa_threshold": 151.6,
        "threat_distance": 1135.3, "close_combat_distance": 2931.6,
        "altitude_advantage_target": 647.3,
        "pnattack_kp": 0.971, "pnattack_kd": 0.453,
        "close_action": "LeadPursuit", "default_action": "LagPursuit",
        "defense_action": "BarrelRoll",
        "include_emergency_defense": False, "include_altitude_far": False,
        "include_enemy_wez": False, "enemy_wez_distance": 700.0,
        "enemy_wez_los": 15.0, "include_offensive_press": False,
        "offensive_press_distance": 3000.0,
        "offensive_press_action": "LeadPursuit",
        "include_is_defensive": False, "is_defensive_action": "BarrelRoll",
    }

    x0 = params_to_vector(v6_best)
    sigma0 = 0.25  # initial step size (moderate exploration)

    # CMA-ES options
    popsize = min(n_workers * 2, 40)  # population size per generation
    opts = {
        'seed': seed,
        'maxfevals': budget,
        'popsize': popsize,
        'bounds': [0, 1],  # all dims in [0,1]
        'verbose': -1,     # suppress cma internal output
        'tolfun': 1e-6,
    }

    es = cma.CMAEvolutionStrategy(x0, sigma0, opts)

    all_results = []
    total_evals = 0
    best_score = -999
    best_params = None
    gen = 0
    total_start = time.time()

    while not es.stop() and total_evals < budget:
        gen += 1
        solutions = es.ask()  # list of vectors
        n_sol = len(solutions)

        # Parallel evaluation
        work_items = [(i, sol, collect_csv) for i, sol in enumerate(solutions)]
        scores = [None] * n_sol

        with mp.Pool(processes=min(n_workers, n_sol)) as pool:
            for idx, score, details, params in pool.imap_unordered(_eval_worker_cma, work_items):
                scores[idx] = score
                total_evals += 1

                w = sum(d["wins"] for d in details.values())
                d_cnt = sum(d["draws"] for d in details.values())
                l = 6 - w - d_cnt

                all_results.append({
                    "params": params, "score": score, "details": details,
                    "generation": gen,
                })

                if score > best_score:
                    best_score = score
                    best_params = params

                print(f"  [gen {gen:3d}] [{total_evals:4d}/{budget}] "
                      f"score={score:7.2f}  W/D/L={w}/{d_cnt}/{l}"
                      f"{'  *** NEW BEST' if score == best_score else ''}",
                      flush=True)

        # CMA-ES minimizes, we maximize → negate
        es.tell(solutions, [-s for s in scores])

    elapsed = time.time() - total_start

    # Sort all results
    all_results.sort(key=lambda x: x["score"], reverse=True)

    print(f"\n{'='*60}")
    print(f"  CMA-ES Complete!")
    print(f"  Total evals: {total_evals}")
    print(f"  Wall time: {elapsed/60:.1f} min")
    print(f"  Best score: {best_score:.2f}")
    print(f"  Generations: {gen}")
    print(f"{'='*60}\n")

    # Print best result details
    best_entry = all_results[0]
    print(f"  Best candidate details:")
    for opp, d in best_entry["details"].items():
        tag = "W" if d["wins"] > 0 else ("D" if d["draws"] > 0 else "L")
        print(f"    vs {opp:12s}: {d['wins']}W {d['draws']}D {d['losses']}L  "
              f"hp={d['hp_diff']:+.0f}  [{tag}]")

    # Save results
    save_data = [{
        "score": r["score"], "params": r["params"],
        "details": r["details"], "generation": r["generation"]
    } for r in all_results[:20]]  # top 20

    ts_path = logs_dir / f"opt_v3_results_{run_ts}.json"
    latest_path = logs_dir / "opt_v3_results.json"
    for path in [ts_path, latest_path]:
        with open(path, 'w') as f:
            json.dump(save_data, f, indent=2, default=str)

    print(f"  Results: {ts_path}")

    # Save best as YAML
    bt_dict = generate_bt_yaml(best_params)
    best_yaml = logs_dir / f"best_v3_{run_ts}.yaml"
    save_bt_yaml(bt_dict, str(best_yaml))
    print(f"  Best YAML: {best_yaml}")

    return all_results


# ============================================================
# Tournament (reuse from v2)
# ============================================================

def run_tournament(agent_path=None, rounds=3):
    if agent_path is None:
        # Try v3 results first, then v2
        for p in [PROJECT_ROOT / "logs" / "opt_v3_results.json",
                  PROJECT_ROOT / "logs" / "opt_results.json"]:
            if p.exists():
                with open(p) as f:
                    data = json.load(f)
                best_params = data[0]["params"]
                bt_dict = generate_bt_yaml(best_params)
                tmp = PROJECT_ROOT / "logs" / "temp_bt" / "_tournament.yaml"
                tmp.parent.mkdir(parents=True, exist_ok=True)
                save_bt_yaml(bt_dict, str(tmp))
                agent_path = str(tmp)
                print(f"  Loaded from: {p.name}")
                break
        else:
            print("No optimization results found!")
            return

    print(f"\n{'='*60}")
    print(f"  Tournament: {Path(agent_path).name}  ({rounds} rounds)")
    print(f"{'='*60}\n")

    total_w = total_d = total_l = 0
    for opp in OPPONENTS:
        results = run_match(agent1=agent_path, agent2=opp,
                           rounds=rounds, verbose=False)
        w = sum(1 for r in results if r.get("winner") == "tree1")
        d = sum(1 for r in results if r.get("winner") == "draw")
        l = rounds - w - d
        total_w += w; total_d += d; total_l += l

        hp = sum(r.get("tree1_health", 100) - r.get("tree2_health", 100)
                 for r in results) / max(1, len(results))
        tag = "WIN" if w > l else ("DRAW" if w == l else "LOSE")
        print(f"  vs {opp:12s}: {w}W {d}D {l}L  hp={hp:+.0f}  [{tag}]")

    pts = total_w * 3 + total_d
    print(f"\n  Total: {total_w}W {total_d}D {total_l}L  "
          f"Points: {pts}/{len(OPPONENTS)*rounds*3}")


# ============================================================
# Main
# ============================================================

def main():
    parser = argparse.ArgumentParser(description="BT Optimizer v3 (CMA-ES)")
    parser.add_argument("--budget", type=int, default=400,
                        help="Total fitness evaluations (default: 400)")
    parser.add_argument("--workers", type=int, default=None,
                        help="Parallel workers (default: cpu_count - 1)")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--tournament", action="store_true")
    parser.add_argument("--rounds", type=int, default=3)
    parser.add_argument("--agent", type=str, default=None)
    parser.add_argument("--collect-csv", action="store_true",
                        help="Phase 1: save per-step metadata CSV + result JSON for every match")
    args = parser.parse_args()

    if args.tournament:
        run_tournament(agent_path=args.agent, rounds=args.rounds)
    else:
        run_cma_search(budget=args.budget, n_workers=args.workers, seed=args.seed,
                       collect_csv=args.collect_csv)


if __name__ == "__main__":
    mp.freeze_support()
    main()
