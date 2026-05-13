"""
stl_falsification.py — Phase C: STL Falsification with Robust Semantics.

BFM 검증 속성(capture, no-loss 등)을 Signal Temporal Logic 으로 표현하고,
sample 된 trajectory에 대해 robust semantics 로 만족도를 정량화. 음수 robustness =
반례 (counterexample) → 알고리즘이 실제로 실패하는 입력 발견.

Reference:
    - Maler, Nickovic (2004) "Monitoring Temporal Properties of Continuous
      Signals", FORMATS.
    - Fainekos, Pappas (2009) "Robustness of Temporal Logic Specifications
      for Continuous-Time Signals", Theoretical Computer Science.
    - Donzé (2010) "Breach, A Toolbox for Verification and Parameter
      Synthesis of Hybrid Systems", CAV.

본 구현은 외부 의존(RTAMT, Breach) 없이 minimal STL 인터프리터.
discrete-time, bounded interval 형식만 지원 (충분).

실행:
    python stl_falsification.py --n 100
    python stl_falsification.py --n 200 --bound zero
    python stl_falsification.py --n 100 --target capture
"""

from __future__ import annotations

import argparse
import math
import os
import sys
import time
from dataclasses import dataclass, field
from typing import Callable, Optional

# parent import
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np

from sim_dogfight_verify import run_scenario
from canonical_perturbation import (
    PerturbationBound, DEFAULT_BOUND, sample_init, sample_policy,
)


# ════════════════════════════════════════════════════════════════════════
# Minimal STL with Robust Semantics
#
# Signal: 이산 시간 t_0, t_1, ..., t_N 에서 변수값 dict.
# robustness ρ(φ, x, t):
#   ρ(x_i op c) = c - x_i (≤) or x_i - c (≥) ; 양수 = 만족, 음수 = 위반.
#   ρ(¬φ)      = -ρ(φ)
#   ρ(φ ∧ ψ)   = min(ρ(φ), ρ(ψ))
#   ρ(φ ∨ ψ)   = max(ρ(φ), ρ(ψ))
#   ρ(F[a,b]φ) = max ρ(φ, t+τ)  for τ ∈ [a,b]
#   ρ(G[a,b]φ) = min ρ(φ, t+τ)  for τ ∈ [a,b]
# ════════════════════════════════════════════════════════════════════════

@dataclass
class Signal:
    """Trajectory: 이산 시간 + 각 변수 값 array."""
    t: np.ndarray                       # shape (N,)
    values: dict[str, np.ndarray]       # name → shape (N,) array

    def __len__(self) -> int:
        return len(self.t)


class STLNode:
    """Base — 모든 노드가 robustness(signal, t_idx) → float."""
    def robustness(self, sig: Signal, t_idx: int = 0) -> float:
        raise NotImplementedError


@dataclass
class Atomic(STLNode):
    """variable op threshold — base proposition.
    op: '<', '>', '<=', '>=', '==' (== 는 |x-c|<eps 처리)."""
    var: str
    op: str
    threshold: float
    eps: float = 1e-3   # for ==

    def robustness(self, sig: Signal, t_idx: int = 0) -> float:
        v = sig.values[self.var][t_idx]
        if self.op in (">", ">="):
            return float(v - self.threshold)
        if self.op in ("<", "<="):
            return float(self.threshold - v)
        if self.op == "==":
            return float(self.eps - abs(v - self.threshold))
        raise ValueError(f"Unknown op: {self.op}")


@dataclass
class Not(STLNode):
    child: STLNode
    def robustness(self, sig: Signal, t_idx: int = 0) -> float:
        return -self.child.robustness(sig, t_idx)


@dataclass
class And(STLNode):
    children: list
    def robustness(self, sig: Signal, t_idx: int = 0) -> float:
        return min(c.robustness(sig, t_idx) for c in self.children)


@dataclass
class Or(STLNode):
    children: list
    def robustness(self, sig: Signal, t_idx: int = 0) -> float:
        return max(c.robustness(sig, t_idx) for c in self.children)


@dataclass
class Eventually(STLNode):
    """F[t_lo, t_hi] φ — bounded eventually."""
    child: STLNode
    t_lo: float = 0.0
    t_hi: float = math.inf
    def robustness(self, sig: Signal, t_idx: int = 0) -> float:
        # window indices
        t_now = sig.t[t_idx]
        i_lo = int(np.searchsorted(sig.t, t_now + self.t_lo))
        i_hi = (len(sig) if math.isinf(self.t_hi)
                else int(np.searchsorted(sig.t, t_now + self.t_hi, side="right")))
        i_lo = max(i_lo, 0); i_hi = min(i_hi, len(sig))
        if i_lo >= i_hi:
            return -math.inf
        return max(self.child.robustness(sig, i) for i in range(i_lo, i_hi))


@dataclass
class Globally(STLNode):
    """G[t_lo, t_hi] φ — bounded always."""
    child: STLNode
    t_lo: float = 0.0
    t_hi: float = math.inf
    def robustness(self, sig: Signal, t_idx: int = 0) -> float:
        t_now = sig.t[t_idx]
        i_lo = int(np.searchsorted(sig.t, t_now + self.t_lo))
        i_hi = (len(sig) if math.isinf(self.t_hi)
                else int(np.searchsorted(sig.t, t_now + self.t_hi, side="right")))
        i_lo = max(i_lo, 0); i_hi = min(i_hi, len(sig))
        if i_lo >= i_hi:
            return math.inf
        return min(self.child.robustness(sig, i) for i in range(i_lo, i_hi))


# ════════════════════════════════════════════════════════════════════════
# BFM Properties as STL formulas
# ════════════════════════════════════════════════════════════════════════

# Property variables (run_scenario log 에서 추출):
#   ata, aa, hca, dist, closure, alt_gap (각 틱 측정)

# WEZ 정의: sim 의 is_victory()와 정확 일치.
#   기본:  ATA<12 ∧ 500<dist<3000 ∧ cl>0
#   확장:  AA>45 일 때 dist 상한 4000 (꼬리 추격 — 적 사격 불가 + 정렬 우수)
# STL 형식: (ATA<12 ∧ dist>500 ∧ cl>0) ∧ (dist<3000 ∨ (AA>45 ∧ dist<4000))
WEZ = And([
    Atomic("ata", "<", 12.0),
    Atomic("dist", ">", 500.0),
    Atomic("closure", ">", 0.0),
    Or([
        Atomic("dist", "<", 3000.0),
        And([
            Atomic("aa", ">", 45.0),
            Atomic("dist", "<", 4000.0),
        ]),
    ]),
])

# 적 WEZ — 좌우 대칭 (ATA ↔ AA, AA의 dist 확장은 비대칭으로 적용 안 함)
ENEMY_WEZ = And([
    Atomic("aa",  "<", 12.0),
    Atomic("dist", ">", 500.0),
    Atomic("closure", ">", 0.0),
    Atomic("dist", "<", 3000.0),
])

# φ_capture: 매치 종료 전 어느 시점이든 우리 WEZ 만족
phi_capture = Eventually(WEZ, t_lo=0.0, t_hi=300.0)

# φ_safe: 매치 동안 적이 우리 WEZ 안 잡음
phi_safe = Globally(Not(ENEMY_WEZ), t_lo=0.0, t_hi=300.0)

# φ_overall: 매치 승리 = capture AND safe
phi_overall = And([phi_capture, phi_safe])

# φ_sustained_attack: WEZ 진입 후 ≥ 0.6초 (3틱) 유지 (sim 의 ≥3틱 WIN 조건과 일치)
phi_sustained = Eventually(
    Globally(WEZ, t_lo=0.0, t_hi=0.6),
    t_lo=0.0, t_hi=300.0,
)


# ════════════════════════════════════════════════════════════════════════
# Trajectory recorder
# ════════════════════════════════════════════════════════════════════════

def run_and_extract_signal(init: dict, policy: str, max_ticks: int = 1500,
                           dt: float = 0.2) -> tuple[Signal, dict]:
    """run_scenario 실행 후 log → STL Signal 변환.

    log tuple 형식 (sim_dogfight_verify.py:943-945):
      (tick, ata, dist, closure, branch, mode, t_th, t_op,
       speed, tr, radius, aa, hca, alt_gap)
    """
    result = run_scenario(init, policy, max_ticks=max_ticks, verbose=False)
    log = result["log"]
    if not log:
        empty = np.zeros(1)
        return Signal(t=np.array([0.0]),
                      values={"ata": empty, "aa": empty, "hca": empty,
                              "dist": empty, "closure": empty, "alt_gap": empty}
                      ), result

    n = len(log)
    t      = np.arange(n, dtype=float) * dt
    ata    = np.array([row[1]  for row in log])
    dist   = np.array([row[2]  for row in log])
    cl     = np.array([row[3]  for row in log])
    aa     = np.array([row[11] for row in log])
    hca    = np.array([row[12] for row in log])
    alt_gap= np.array([row[13] for row in log])

    sig = Signal(t=t, values={
        "ata": ata, "aa": aa, "hca": hca,
        "dist": dist, "closure": cl, "alt_gap": alt_gap,
    })
    return sig, result


# ════════════════════════════════════════════════════════════════════════
# Falsification main loop
# ════════════════════════════════════════════════════════════════════════

@dataclass
class FalsificationResult:
    n_total: int
    n_violations: int             # ρ ≤ 0
    worst_input: Optional[dict]   # 가장 ρ 작은 시나리오
    worst_policy: Optional[str]
    worst_robustness: float
    worst_outcome: str
    rho_distribution: list[tuple[str, float, str]]   # (policy, rho, outcome)


def falsify(spec: STLNode, n: int = 100,
            bound: PerturbationBound = DEFAULT_BOUND,
            max_ticks: int = 1500,
            seed: int = 0,
            verbose: bool = False) -> FalsificationResult:
    """spec 위반 입력 탐색 (random sampling, 향후 gradient/genetic 확장 가능).

    ρ ≤ 0 = spec 위반 (counterexample).
    """
    rng = np.random.default_rng(seed)
    n_viol = 0; worst_rho = math.inf
    worst = (None, None, "")
    rhos: list[tuple[str, float, str]] = []

    for i in range(n):
        init = sample_init(bound, rng)
        policy = sample_policy(bound, rng)
        sig, result = run_and_extract_signal(init, policy, max_ticks)
        rho = spec.robustness(sig, t_idx=0)
        rhos.append((policy, rho, result["outcome"]))
        if rho <= 0:
            n_viol += 1
        if rho < worst_rho:
            worst_rho = rho
            worst = (init, policy, result["outcome"])
        if verbose:
            sym = "✗" if rho <= 0 else "✓"
            print(f"  [{i+1:3d}/{n}] {sym}  policy={policy:9s}  ρ={rho:+.3f}  "
                  f"outcome={result['outcome']}")

    return FalsificationResult(
        n_total=n, n_violations=n_viol,
        worst_input=worst[0], worst_policy=worst[1],
        worst_robustness=worst_rho, worst_outcome=worst[2],
        rho_distribution=rhos,
    )


# ════════════════════════════════════════════════════════════════════════
# CLI + 분석
# ════════════════════════════════════════════════════════════════════════

SPEC_REGISTRY = {
    "capture":  ("Eventually WEZ within 300s", phi_capture),
    "safe":     ("Globally not enemy WEZ", phi_safe),
    "overall":  ("capture AND safe", phi_overall),
    "sustained":("WEZ sustained ≥ 1s", phi_sustained),
}

BOUND_PRESETS = {
    "default": DEFAULT_BOUND,
    "zero":    PerturbationBound.zero(),
    "relaxed": PerturbationBound.relaxed(),
}


def analyze_per_policy(rhos: list[tuple[str, float, str]]):
    """정책별 robustness 분포 + outcome — 어느 정책이 spec 위반하는가."""
    from collections import defaultdict
    per: dict[str, list[tuple[float, str]]] = defaultdict(list)
    for p, r, o in rhos:
        per[p].append((r, o))
    print("\n  policy별 분포:")
    print(f"  {'policy':10s}  {'N':>3s}  {'avg ρ':>8s}  {'min ρ':>8s}  "
          f"{'max ρ':>8s}  {'WIN':>3s}  {'DRAW':>4s}  {'LOSS':>4s}  "
          f"{'#viol':>5s}")
    for policy, lst in sorted(per.items()):
        rs = [r for r, _ in lst]
        outs = [o for _, o in lst]
        n = len(lst)
        viol = sum(1 for r in rs if r <= 0)
        wins = sum(1 for o in outs if o == "WIN")
        draws= sum(1 for o in outs if o == "DRAW")
        losses=sum(1 for o in outs if o == "LOSS")
        print(f"  {policy:10s}  {n:3d}  {sum(rs)/n:+8.3f}  {min(rs):+8.3f}  "
              f"{max(rs):+8.3f}  {wins:3d}  {draws:4d}  {losses:4d}  {viol:5d}")


def main():
    parser = argparse.ArgumentParser(
        description="Phase C — STL falsification of BFM properties.")
    parser.add_argument("--n", type=int, default=100)
    parser.add_argument("--target", choices=list(SPEC_REGISTRY.keys()),
                        default="capture",
                        help="Spec 선택 (default: capture)")
    parser.add_argument("--bound", choices=list(BOUND_PRESETS.keys()),
                        default="zero",
                        help="Perturbation bound (default: zero — 정확 canonical)")
    parser.add_argument("--max-ticks", type=int, default=1500)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    spec_desc, spec = SPEC_REGISTRY[args.target]
    bound = BOUND_PRESETS[args.bound]

    print("=" * 70)
    print("  STL Falsification — Phase C")
    print("=" * 70)
    print(f"  Spec target:   {args.target} — {spec_desc}")
    print(f"  Bound:         {args.bound}")
    print(f"  N samples:     {args.n}")
    print(f"  Seed:          {args.seed}")
    print()

    t0 = time.time()
    res = falsify(spec, n=args.n, bound=bound, max_ticks=args.max_ticks,
                  seed=args.seed, verbose=args.verbose)
    elapsed = time.time() - t0

    print()
    print("=" * 70)
    print("  Result")
    print("=" * 70)
    print(f"  N total:           {res.n_total}")
    print(f"  Violations (ρ≤0): {res.n_violations} ({100*res.n_violations/res.n_total:.1f}%)")
    print(f"  Worst ρ:           {res.worst_robustness:+.3f}")
    print(f"  Worst policy:      {res.worst_policy}")
    print(f"  Worst outcome:     {res.worst_outcome}")
    print(f"  Elapsed:           {elapsed:.1f}s")

    analyze_per_policy(res.rho_distribution)

    if res.worst_input:
        print()
        print("=" * 70)
        print("  Worst-case input (counterexample)")
        print("=" * 70)
        print(f"  init: {res.worst_input}")
        print(f"  policy: {res.worst_policy}")


if __name__ == "__main__":
    main()
