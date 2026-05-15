"""RT-3 item 1 — G2_d Cover Property: SMT proof (Z3).

PLAN §2.4.8 게이트 G2_d:  ∀x ∈ canonical_neighborhood,  Σ_m τ_m(x) > ε
HANDOVER RT-3:           'dReal/Z3 로 ... Σ τ_m(x) > ε'

`tau_functions.verify_G2` 의 G2_d 는 유한 grid 열거 (7×4×4 = 112 점) — *증명* 이
아니라 spot-check. 본 모듈은 Z3 로 **연속 영역 전체** 에 대해 cover 를 증명한다.

────────────────────────────────────────────────────────────────────────
핵심 관찰 — `all_taus()` 정규화 구조 분석
────────────────────────────────────────────────────────────────────────
  rho_others = ρ_corner + ρ_yoyo + ρ_ldt           (tau_functions.all_taus)
  ρ_pn       = max(0, 1 - rho_others)              (tau_pn)
  total      = ρ_pn + rho_others
             = max(0, 1 - r) + r       where r := rho_others
  Σ τ_m(normalized) = total / total = 1            (total > 1e-6 분기)
                    = 1                            (total ≤ 1e-6 분기 → {pn:1})

→ cover property 는 `total ≥ ε` 로 환원되고, total 은 r 에 대한 **1변수
  piecewise-linear** 함수. Z3 의 LRA (linear real arithmetic) 는 이에 대해
  decision-complete → δ-근사 아닌 *exact* 증명.

전제(premise) `r ≥ 0` 의 정당화:
  r = ρ_corner + ρ_yoyo + ρ_ldt, 각 ρ_m 은 sigmoid/gaussian 의 곱.
  sigmoid ∈ (0,1), gaussian ∈ (0,1] → ρ_m ∈ [0,1] → r ∈ [0,3].
  (이 lemma 도 아래 prove_rho_in_unit_interval 에서 Z3 로 검증.)

산출: 두 정리 모두 UNSAT(부정) ⟹ 증명 완료.
"""

from __future__ import annotations

import z3


def prove_cover(eps: float = 0.1, verbose: bool = True) -> bool:
    """정리 1 — ∀ r = rho_others ≥ 0:  total(r) = max(0,1-r)+r ≥ 1  ( > ε ).

    Z3 LRA 로 부정 (∃ r ≥ 0: total < 1) 이 UNSAT 임을 보여 증명.
    total ≥ 1 ⟹ Σ τ_m ≥ ε (∀ ε ≤ 1) AND degenerate `total < 1e-6` 분기 unreachable.
    """
    r = z3.Real("rho_others")               # ρ_corner + ρ_yoyo + ρ_ldt
    rho_pn = z3.If(1 - r > 0, 1 - r, 0)      # tau_pn: max(0, 1 - rho_others)
    total = rho_pn + r                       # all_taus: total = ρ_pn + rho_others

    s = z3.Solver()
    s.add(r >= 0)                            # premise (lemma 아래에서 검증)
    s.add(total < 1)                         # 부정: cover 위반 시도
    res = s.check()
    proven = (res == z3.unsat)

    if verbose:
        print("  [정리 1] ∀ r ≥ 0:  total = max(0,1-r)+r ≥ 1")
        if proven:
            print(f"     Z3: ¬(total≥1) is UNSAT  →  PROVEN  (⟹ Σ τ_m ≥ 1 > ε={eps})")
            print(f"     따름: total ≥ 1 > 1e-6  →  all_taus 의 degenerate 분기 unreachable")
        else:
            m = s.model()
            print(f"     Z3: SAT — 반례 r = {m[r]}  →  FAIL")
    return proven


def prove_rho_in_unit_interval(verbose: bool = True) -> bool:
    """정리 2 (lemma) — 각 ρ_m ∈ [0,1].

    ρ_corner = s_regime·s_V·s_us·s_them  (4 factors)
    ρ_yoyo   = s_engagement·g_ata        (2 factors)
    ρ_ldt    = g_ata·s_disp·s_los        (3 factors)

    각 factor 는 sigmoid ∈ (0,1) 또는 gaussian ∈ (0,1].  sound abstraction:
    각 factor 를 [0,1] 자유변수로 치환 → '[0,1] 원소들의 곱 ∈ [0,1]' 을 Z3
    nonlinear 로 증명 (sigmoid/gauss 의 실제 치역이 [0,1] 의 부분집합이므로 sound).
    """
    all_ok = True
    for name, k in [("ρ_corner", 4), ("ρ_yoyo", 2), ("ρ_ldt", 3)]:
        factors = [z3.Real(f"{name}_f{i}") for i in range(k)]
        s = z3.Solver()
        for f in factors:
            s.add(f >= 0, f <= 1)            # sigmoid/gauss 치역 ⊆ [0,1] (sound)
        prod = factors[0]
        for f in factors[1:]:
            prod = prod * f
        # 부정: ∃ factors ∈ [0,1]^k :  prod < 0  ∨  prod > 1
        s.add(z3.Or(prod < 0, prod > 1))
        res = s.check()
        ok = (res == z3.unsat)
        all_ok = all_ok and ok
        if verbose:
            status = "PROVEN  (∈ [0,1])" if ok else f"FAIL ({res})"
            print(f"  [정리 2] {name} = ∏ {k} factors ∈ [0,1]:  {status}")
    # rho_others = ρ_corner + ρ_yoyo + ρ_ldt ∈ [0,3]  → premise r ≥ 0 정당
    if verbose and all_ok:
        print("     따름: rho_others = Σ(3개) ∈ [0,3]  →  정리 1 의 전제 r ≥ 0 정당화")
    return all_ok


def main() -> bool:
    print("=" * 72)
    print("  RT-3 item 1 — G2_d Cover Property — SMT Proof (Z3)")
    print("=" * 72)
    print(f"  Z3 version: {z3.get_version_string()}")
    print()
    t2 = prove_rho_in_unit_interval()
    print()
    t1 = prove_cover()
    print()
    print("=" * 72)
    ok = t1 and t2
    print(f"  결과: {'ALL PROVEN — G2_d cover 는 canonical_neighborhood 전체에서 성립' if ok else 'FAIL'}")
    print("=" * 72)
    return ok


if __name__ == "__main__":
    import sys
    sys.exit(0 if main() else 1)
