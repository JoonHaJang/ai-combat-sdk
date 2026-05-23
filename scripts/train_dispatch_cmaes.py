"""β-2 — CMA-ES 학습 of dispatch NN (numpy MLP).

Policy: 13 obs → tanh(W1·x + b1) → W2·h + b2 → argmax → mode index ∈ {pn, corner, yoyo, ldt, T, ipa}

Fitness:
    - aggressive 매치 N_AGG 회 → avg (HP_us_final - HP_them_final + W_us - W_them)
    - simple/defensive 매치 N_SAFE 회 → R7 hard-gate fitness penalty
    - Total fitness = aggressive_score - R7_penalty (maximize)

Usage:
    python scripts/train_dispatch_cmaes.py --generations 5 --popsize 8 --hidden 16
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import numpy as np


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("--generations", type=int, default=3)
    p.add_argument("--popsize", type=int, default=8)
    p.add_argument("--hidden", type=int, default=16)
    p.add_argument("--n_aggressive", type=int, default=2, help="매 candidate aggressive 매치 수")
    p.add_argument("--n_safe", type=int, default=1, help="매 candidate simple/defensive 매치 수")
    p.add_argument("--sigma0", type=float, default=0.3)
    p.add_argument("--save_dir", type=str, default="models/dispatch_cmaes")
    p.add_argument("--seed", type=int, default=42)
    return p.parse_args()


OBS_DIM = 13
N_MODES = 6


def vec_to_weights(vec: np.ndarray, hidden: int) -> dict:
    """flat vector → MLP weights dict."""
    p1 = OBS_DIM * hidden
    p2 = hidden
    p3 = hidden * N_MODES
    p4 = N_MODES
    assert vec.size == p1 + p2 + p3 + p4, f"vec size {vec.size} != {p1+p2+p3+p4}"
    idx = 0
    W1 = vec[idx:idx+p1].reshape(OBS_DIM, hidden); idx += p1
    b1 = vec[idx:idx+p2]; idx += p2
    W2 = vec[idx:idx+p3].reshape(hidden, N_MODES); idx += p3
    b2 = vec[idx:idx+p4]
    return {"W1": W1, "b1": b1, "W2": W2, "b2": b2}


def run_match(weights_path: Path, opponent: str, match_log_dir: Path, idx: int) -> dict:
    """1 매치 실행 후 result.json 파싱."""
    log_dir = match_log_dir / f"{opponent}_{idx}"
    log_dir.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env["BETA_NN_WEIGHTS"] = str(weights_path)
    cmd = [
        sys.executable, str(PROJECT_ROOT / "scripts" / "run_match.py"),
        "--agent1", "pursuit_chase_v1", "--agent2", opponent,
        "--rounds", "1", "--quiet",
        "--metadata-log", str(log_dir),
    ]
    proc = subprocess.run(cmd, cwd=str(PROJECT_ROOT), env=env,
                           capture_output=True, text=True, timeout=180)
    # Find result.json
    rjs = list(log_dir.glob("*_result.json"))
    if not rjs:
        return {"winner": "error", "tree1_hp": 0.0, "tree2_hp": 100.0, "error": proc.stderr[-200:]}
    return json.loads(rjs[0].read_text(encoding="utf-8"))


def evaluate_candidate(vec: np.ndarray, args, save_dir: Path, gen: int, idx: int) -> float:
    """Returns fitness to MINIMIZE (CMA-ES convention). 즉 -score."""
    weights = vec_to_weights(vec, args.hidden)
    weights_path = save_dir / f"gen{gen}_cand{idx}.npz"
    np.savez(weights_path, **weights)

    log_dir = save_dir / "matches" / f"gen{gen}_cand{idx}"
    aggressive_scores = []
    safe_penalties = []

    for i in range(args.n_aggressive):
        r = run_match(weights_path, "aggressive", log_dir, i)
        # aggressive score: HP_us - HP_them + W_us_bonus (per outcome)
        score = (r.get("tree1_hp", 0) - r.get("tree2_hp", 100))
        if r.get("winner") == "tree1":
            score += 50.0   # WIN bonus
        elif r.get("winner") == "tree2":
            score -= 100.0  # LOSS huge penalty
        aggressive_scores.append(score)

    # R7: simple WIN >= baseline 5/5 강제
    for opp in ["simple", "defensive"]:
        for i in range(args.n_safe):
            r = run_match(weights_path, opp, log_dir, 100 + i)
            if r.get("winner") != "tree1":
                # NOT WIN → 큰 penalty
                safe_penalties.append(200.0)
            else:
                safe_penalties.append(0.0)

    fitness = sum(aggressive_scores) / len(aggressive_scores) - sum(safe_penalties)
    # CMA-ES minimizes → return -fitness
    return -fitness


def main():
    args = parse_args()
    save_dir = Path(args.save_dir); save_dir.mkdir(parents=True, exist_ok=True)
    print(f"[train] save_dir: {save_dir}")
    print(f"[train] gens: {args.generations}, popsize: {args.popsize}, hidden: {args.hidden}")
    print(f"[train] matches per candidate: aggressive×{args.n_aggressive} + simple×{args.n_safe} + defensive×{args.n_safe}")

    import cma
    n_params = OBS_DIM * args.hidden + args.hidden + args.hidden * N_MODES + N_MODES
    print(f"[train] NN params: {n_params}")

    # Initial weights: small random (around 0)
    x0 = np.zeros(n_params)
    es = cma.CMAEvolutionStrategy(x0, args.sigma0, {
        "popsize": args.popsize,
        "seed": args.seed,
        "verbose": -9,
    })

    best_fit = float("inf")
    best_vec = None
    for gen in range(args.generations):
        t0 = time.time()
        solutions = es.ask()
        fitnesses = []
        for ci, sol in enumerate(solutions):
            fit = evaluate_candidate(sol, args, save_dir, gen, ci)
            fitnesses.append(fit)
            if fit < best_fit:
                best_fit = fit; best_vec = sol.copy()
            print(f"  gen{gen} cand{ci}: fitness = {-fit:.2f} (score, higher=better)")
        es.tell(solutions, fitnesses)
        dt = time.time() - t0
        print(f"[train] gen{gen} done in {dt:.0f}s, best score so far = {-best_fit:.2f}")

    # Save best
    if best_vec is not None:
        best_weights = vec_to_weights(best_vec, args.hidden)
        best_path = save_dir / "best_weights.npz"
        np.savez(best_path, **best_weights)
        print(f"\n[train] BEST: score={-best_fit:.2f}, saved → {best_path}")


if __name__ == "__main__":
    main()
