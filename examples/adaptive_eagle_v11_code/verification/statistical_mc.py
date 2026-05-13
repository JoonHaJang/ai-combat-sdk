"""
statistical_mc.py — Statistical Model Checking for WIN rate.

P(WIN | canonical perturbation) 의 정량적 추론:
  (a) Wilson score interval (Wilson 1927) — 점추정의 95% CI
  (b) Wald SPRT (Sequential Probability Ratio Test, Wald 1945) — H₀ vs H₁ 결정

Reference:
    - VERIFICATION_METHODOLOGY.md §2.7
    - Younes, Simmons (2002) "Probabilistic Verification of Discrete
      Event Systems Using Acceptance Sampling", CAV.
    - Legay, Delahaye, Bensalem (2010) "Statistical Model Checking: An
      Overview", RV.

실행:
    python statistical_mc.py --n 50          # Wilson CI with N=50 trials
    python statistical_mc.py --sprt          # SPRT for H₀: p≥0.85
    python statistical_mc.py --bound default # default | zero | relaxed
"""

from __future__ import annotations

import argparse
import math
import os
import sys
import time
from dataclasses import dataclass

# parent (sim_dogfight_verify) import
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np

from sim_dogfight_verify import run_scenario
from canonical_perturbation import (
    PerturbationBound,
    DEFAULT_BOUND,
    sample_init,
    sample_policy,
    canonical_init,
)


# ─── Wilson Score Interval ────────────────────────────────────────────────

def wilson_ci(n_success: int, n_total: int, alpha: float = 0.05) -> tuple[float, float, float]:
    """Wilson score interval for binomial proportion.

    Wilson 1927 — small N에서 잘 작동, normal approximation보다 정확.

    Returns:
        (point_estimate, ci_low, ci_high)
    """
    if n_total == 0:
        return (0.0, 0.0, 1.0)
    p = n_success / n_total
    z = 1.959963984540054 if abs(alpha - 0.05) < 1e-9 else _normal_quantile(1 - alpha / 2)
    z2 = z * z
    denom = 1 + z2 / n_total
    center = (p + z2 / (2 * n_total)) / denom
    half = z * math.sqrt(p * (1 - p) / n_total + z2 / (4 * n_total * n_total)) / denom
    return (p, max(0.0, center - half), min(1.0, center + half))


def _normal_quantile(q: float) -> float:
    """Approximate inverse standard normal CDF (Beasley-Springer-Moro)."""
    # 단순 근사 (q ∈ (0,1)). 95%만 쓰면 표준값 1.96 사용.
    if q == 0.5:
        return 0.0
    sign = 1 if q > 0.5 else -1
    p = q if q > 0.5 else 1 - q
    t = math.sqrt(-2.0 * math.log(1 - p))
    c = [2.515517, 0.802853, 0.010328]
    d = [1.432788, 0.189269, 0.001308]
    num = c[0] + c[1] * t + c[2] * t * t
    den = 1 + d[0] * t + d[1] * t * t + d[2] * t * t * t
    return sign * (t - num / den)


# ─── Wald SPRT ────────────────────────────────────────────────────────────

@dataclass
class SPRTResult:
    decision: str        # "ACCEPT_H0" | "REJECT_H0" | "INCONCLUSIVE"
    n: int               # 사용된 trial 수
    n_success: int       # WIN 수
    p_hat: float         # 점추정
    ci_low: float        # Wilson 95% CI 하한
    ci_high: float       # Wilson 95% CI 상한


def wald_sprt(p0: float, p1: float, alpha: float, beta: float,
              trial_runner, max_n: int = 500, verbose: bool = False) -> SPRTResult:
    """Wald 1945 sequential probability ratio test.

    H₀: P(success) = p₀
    H₁: P(success) = p₁     (p₀ ≠ p₁)

    Type I error ≤ α (false reject of H₀)
    Type II error ≤ β (false accept of H₀)

    log(B) = log(β / (1-α))      <- accept H₀
    log(A) = log((1-β) / α)      <- reject H₀
    cum_log_lr = Σ x_i · log(p₁/p₀) + (1-x_i) · log((1-p₁)/(1-p₀))

    Args:
        trial_runner: zero-arg callable, returns 1 (success) or 0 (failure).
        max_n: 강제 종료 한계.
    """
    log_a = math.log(beta / (1 - alpha))
    log_b = math.log((1 - beta) / alpha)
    log_lr_pos = math.log(p1 / p0)
    log_lr_neg = math.log((1 - p1) / (1 - p0))

    cum = 0.0; n_succ = 0; n = 0
    for n in range(1, max_n + 1):
        x = trial_runner()
        if x:
            cum += log_lr_pos
            n_succ += 1
        else:
            cum += log_lr_neg
        if verbose and n % 5 == 0:
            print(f"  [SPRT] n={n:3d}  succ={n_succ:3d}  log_lr={cum:+.3f}  "
                  f"(accept≤{log_a:.3f}, reject≥{log_b:.3f})")
        if cum <= log_a:
            p_hat, lo, hi = wilson_ci(n_succ, n)
            return SPRTResult("ACCEPT_H0", n, n_succ, p_hat, lo, hi)
        if cum >= log_b:
            p_hat, lo, hi = wilson_ci(n_succ, n)
            return SPRTResult("REJECT_H0", n, n_succ, p_hat, lo, hi)

    p_hat, lo, hi = wilson_ci(n_succ, n)
    return SPRTResult("INCONCLUSIVE", n, n_succ, p_hat, lo, hi)


# ─── Trial Runner — sim_dogfight_verify wrapper ───────────────────────────

class CanonicalTrialRunner:
    """canonical perturbation에서 1개 sample → run_scenario → WIN/LOSS/DRAW.

    Returns:
        1 if WIN, 0 otherwise (LOSS or DRAW).
    """
    def __init__(self, bound: PerturbationBound = DEFAULT_BOUND,
                 max_ticks: int = 1500, seed: int = 0):
        self.bound = bound
        self.max_ticks = max_ticks
        self.rng = np.random.default_rng(seed)
        self.outcomes: list[str] = []      # 사후 분석용 — WIN/LOSS/DRAW
        self.policies: list[str] = []      # 사후 분석용 — 어떤 정책이 fail 했나

    def __call__(self) -> int:
        init = sample_init(self.bound, self.rng)
        policy = sample_policy(self.bound, self.rng)
        result = run_scenario(init, policy, max_ticks=self.max_ticks, verbose=False)
        outcome = result["outcome"]
        self.outcomes.append(outcome)
        self.policies.append(policy)
        return 1 if outcome == "WIN" else 0


# ─── Fixed-N estimation ───────────────────────────────────────────────────

def fixed_n_estimate(runner: CanonicalTrialRunner, n: int, verbose: bool = False) -> SPRTResult:
    """N 시행 후 Wilson CI 보고."""
    n_succ = 0
    t0 = time.time()
    for i in range(n):
        x = runner()
        n_succ += x
        if verbose:
            elapsed = time.time() - t0
            rate = (i + 1) / max(elapsed, 1e-9)
            print(f"  [{i+1:3d}/{n}] WIN_rate so far: {n_succ}/{i+1} = "
                  f"{n_succ/(i+1):.3f}  (~{rate:.1f} trials/s)")
    p_hat, lo, hi = wilson_ci(n_succ, n)
    return SPRTResult("FIXED_N", n, n_succ, p_hat, lo, hi)


# ─── Outcome 분포 분석 ────────────────────────────────────────────────────

def outcome_distribution(outcomes: list[str]) -> dict:
    """WIN/LOSS/DRAW 분포 + 각각의 95% Wilson CI."""
    n = len(outcomes)
    n_win  = sum(1 for o in outcomes if o == "WIN")
    n_loss = sum(1 for o in outcomes if o == "LOSS")
    n_draw = sum(1 for o in outcomes if o == "DRAW")
    return {
        "N": n,
        "WIN":  {"count": n_win,  "rate": n_win/n  if n else 0,
                 "ci95": wilson_ci(n_win, n)},
        "LOSS": {"count": n_loss, "rate": n_loss/n if n else 0,
                 "ci95": wilson_ci(n_loss, n)},
        "DRAW": {"count": n_draw, "rate": n_draw/n if n else 0,
                 "ci95": wilson_ci(n_draw, n)},
    }


def print_dist(d: dict):
    print(f"  N={d['N']}")
    for k in ["WIN", "LOSS", "DRAW"]:
        v = d[k]
        _, lo, hi = v["ci95"]
        print(f"  {k:5s}: {v['count']:3d}  rate={v['rate']:.3f}  "
              f"95% CI=[{lo:.3f}, {hi:.3f}]")


# ─── CLI ──────────────────────────────────────────────────────────────────

BOUND_PRESETS = {
    "default": DEFAULT_BOUND,
    "zero":    PerturbationBound.zero(),
    "relaxed": PerturbationBound.relaxed(),
}


def main():
    parser = argparse.ArgumentParser(
        description="Statistical Model Checking for sim_dogfight_verify WIN rate.")
    parser.add_argument("--n", type=int, default=50,
                        help="Fixed-N trial 수 (default 50)")
    parser.add_argument("--sprt", action="store_true",
                        help="Wald SPRT (H₀: p≥p₀, H₁: p<p₀) 실행")
    parser.add_argument("--p0", type=float, default=0.85,
                        help="SPRT H₀ 임계 (default 0.85)")
    parser.add_argument("--p1", type=float, default=0.75,
                        help="SPRT H₁ 임계 (default 0.75)")
    parser.add_argument("--alpha", type=float, default=0.05,
                        help="Type I error (default 0.05)")
    parser.add_argument("--beta", type=float, default=0.05,
                        help="Type II error (default 0.05)")
    parser.add_argument("--bound", choices=list(BOUND_PRESETS.keys()),
                        default="default", help="Perturbation bound preset")
    parser.add_argument("--max-ticks", type=int, default=1500)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    bound = BOUND_PRESETS[args.bound]
    print("=" * 70)
    print("  Statistical Model Checking — sim_dogfight_verify WIN rate")
    print("=" * 70)
    print(f"  Bound preset:  {args.bound}")
    print(f"    pos_ft:    ±{bound.pos_ft}")
    print(f"    alt_ft:    ±{bound.alt_ft}")
    print(f"    spd_kts:   ±{bound.spd_kts}")
    print(f"    hdg_deg:   ±{bound.hdg_deg}")
    print(f"    policies:  {bound.policy_weights}")
    print(f"  Max ticks:     {args.max_ticks}")
    print(f"  Seed:          {args.seed}")
    print()

    runner = CanonicalTrialRunner(bound, args.max_ticks, args.seed)
    t0 = time.time()

    if args.sprt:
        print(f"Running Wald SPRT  (H₀: p≥{args.p0},  H₁: p<{args.p1},  "
              f"α={args.alpha}, β={args.beta}) ...")
        result = wald_sprt(args.p0, args.p1, args.alpha, args.beta,
                           runner, max_n=500, verbose=args.verbose)
    else:
        print(f"Running fixed-N estimation  (N={args.n}) ...")
        result = fixed_n_estimate(runner, args.n, verbose=args.verbose)

    elapsed = time.time() - t0

    print()
    print("=" * 70)
    print("  Result")
    print("=" * 70)
    print(f"  Decision:        {result.decision}")
    print(f"  N (trials run):  {result.n}")
    print(f"  WIN count:       {result.n_success} / {result.n}")
    print(f"  Point estimate:  {result.p_hat:.3f}")
    print(f"  95% Wilson CI:   [{result.ci_low:.3f}, {result.ci_high:.3f}]")
    print(f"  Elapsed:         {elapsed:.1f}s "
          f"(~{result.n/max(elapsed,1e-9):.2f} trials/s)")
    print()

    print("=" * 70)
    print("  Outcome distribution")
    print("=" * 70)
    print_dist(outcome_distribution(runner.outcomes))


if __name__ == "__main__":
    main()
