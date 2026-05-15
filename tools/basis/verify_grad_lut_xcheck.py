"""RT-3 item 2 — ∇V_i ↔ LUT 정합 cross-check.

HANDOVER RT-3:  '∇V_i ↔ LUT 정합 (∇V_corner 가 LUT 의 high-τ_corner 영역에서
                 일치하는지)'

목적: closed-form gradient approximator (`gradient_approximators.py`, R1) 가
산출하는 ∇V 와, 수치 HJI LUT (`logs/hji/V6d_wez_v3.npz`, R7 v3) 의 central-
difference ∇V 가 방향적으로 일치하는지 정량 비교.

방법:
  1. LUT 도메인 안에서 6D state 를 sampling — 그 중 'corner mode 활성' state
     (HCA ∉ [90°,120°] ∧ V_p > V_c-30) 부분집합을 따로 분석.
  2. 각 state 에서:
       g_cf   = closed-form  (grad_V_corner / grad_V_1circle / optimal_control blend)
       g_lut  = LUT central-difference ∇V
  3. cosine similarity + magnitude ratio 분포 보고.

§2.5.9 의 정직 기록 ("12⁶ grid LUT 가 사용 가능한 ∇V 산출 못 함") 의 정량 재확인.
일치하면 LUT 사용 정당, 불일치하면 closed-form regression path 정당 — 어느
쪽이든 honest finding.
"""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np

from tools.basis import envelope_f16 as env
from tools.basis.gradient_approximators import (
    grad_V_corner, grad_V_1circle, grad_V_PN, optimal_control,
    HCA_1C_CENTER_RAD, HCA_2C_CENTER_RAD, SIGMA_REGIME_WIDTH_RAD, _sig,
)

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_LUT_PATH = _PROJECT_ROOT / "logs" / "hji" / "V6d_wez_v3.npz"


def _load_lut():
    d = np.load(_LUT_PATH)
    V = np.asarray(d["V"])
    coords = tuple(np.asarray(d[f"coord_{i}"]) for i in range(6))
    spac = tuple(float(c[1] - c[0]) if len(c) > 1 else 1.0 for c in coords)
    return V, coords, spac


def _grad_V_lut(x, V, coords, spac):
    """LUT nearest-cell V + 6D central-difference ∇V (continuous_policy 와 동일)."""
    idx = tuple(int(np.argmin(np.abs(coords[d] - x[d]))) for d in range(6))
    V_val = float(V[idx])
    grad = np.zeros(6)
    for d in range(6):
        n_d = V.shape[d]
        ip = list(idx); im = list(idx)
        ip[d] = min(idx[d] + 1, n_d - 1)
        im[d] = max(idx[d] - 1, 0)
        step = max(spac[d], 1e-6) * (ip[d] - im[d])
        if step < 1e-9:
            grad[d] = 0.0
        else:
            grad[d] = (float(V[tuple(ip)]) - float(V[tuple(im)])) / step
    return V_val, grad


def _cos_sim(a, b):
    na = np.linalg.norm(a); nb = np.linalg.norm(b)
    if na < 1e-12 or nb < 1e-12:
        return float("nan")
    return float(np.dot(a, b) / (na * nb))


def _is_corner_active(x, alt_ft):
    """corner mode 활성 근사 (state-space): HCA ∉ [90°,120°] ∧ V_p > V_c-30."""
    hca_deg = math.degrees(abs(x[3]))
    V_c = env.V_corner_kts(alt_ft)
    return ((hca_deg > 120.0) or (hca_deg < 90.0)) and (x[4] > V_c - 30.0)


def run(n_samples: int = 4000, seed: int = 42, alt_ft: float = 15000.0):
    if not _LUT_PATH.exists():
        print(f"  LUT 없음: {_LUT_PATH} — hji_solve_v3.py 먼저 실행")
        return False
    V, coords, spac = _load_lut()
    print(f"  LUT: {_LUT_PATH.name}  shape={V.shape}  "
          f"V range [{V.min():+.0f}, {V.max():+.0f}]")

    rng = np.random.default_rng(seed)
    lo = np.array([coords[d][0] for d in range(6)])
    hi = np.array([coords[d][-1] for d in range(6)])

    rows_all, rows_corner = [], []
    for _ in range(n_samples):
        x = lo + rng.random(6) * (hi - lo)
        # closed-form: corner(2c) + 1circle + 전체 blend
        _, g_2c = grad_V_corner(x, alt_ft)
        _, g_1c = grad_V_1circle(x, alt_ft)
        # τ_corner=1 일 때의 blend (optimal_control 내부 1c/2c σ-blend 와 동일)
        hca = abs(x[3])
        s1 = _sig((HCA_1C_CENTER_RAD - hca) / SIGMA_REGIME_WIDTH_RAD)
        s2 = _sig((hca - HCA_2C_CENTER_RAD) / SIGMA_REGIME_WIDTH_RAD)
        g_corner_blend = (s1 * g_1c + s2 * g_2c) / (s1 + s2 + 1e-9)
        _, g_pn = grad_V_PN(x, V_c_kts=env.V_corner_kts(alt_ft))
        # LUT
        _, g_lut = _grad_V_lut(x, V, coords, spac)

        rec = {
            "cos_2c":     _cos_sim(g_2c, g_lut),
            "cos_1c":     _cos_sim(g_1c, g_lut),
            "cos_corner": _cos_sim(g_corner_blend, g_lut),
            "cos_pn":     _cos_sim(g_pn, g_lut),
            "lut_norm":   float(np.linalg.norm(g_lut)),
            "cf_norm":    float(np.linalg.norm(g_corner_blend)),
        }
        rows_all.append(rec)
        if _is_corner_active(x, alt_ft):
            rows_corner.append(rec)

    def report(rows, label):
        if not rows:
            print(f"  [{label}] (no samples)")
            return
        n = len(rows)
        def stat(key):
            vals = np.array([r[key] for r in rows], dtype=float)
            vals = vals[~np.isnan(vals)]
            if len(vals) == 0:
                return "  n/a"
            return (f"mean={vals.mean():+.3f} median={np.median(vals):+.3f} "
                    f"|cos|>0.5: {100*np.mean(np.abs(vals)>0.5):.0f}%")
        print(f"  [{label}]  N={n}")
        print(f"     cos(∇V_corner_blend, ∇V_LUT): {stat('cos_corner')}")
        print(f"     cos(∇V_2circle,      ∇V_LUT): {stat('cos_2c')}")
        print(f"     cos(∇V_1circle,      ∇V_LUT): {stat('cos_1c')}")
        print(f"     cos(∇V_PN,           ∇V_LUT): {stat('cos_pn')}")
        ln = np.array([r["lut_norm"] for r in rows])
        cf = np.array([r["cf_norm"] for r in rows])
        print(f"     ‖∇V_LUT‖    : mean={ln.mean():.2e}  median={np.median(ln):.2e}")
        print(f"     ‖∇V_corner‖ : mean={cf.mean():.2e}  median={np.median(cf):.2e}")

    print()
    report(rows_all, "LUT 도메인 전역")
    print()
    report(rows_corner, "high-τ_corner 영역 (HCA∉[90,120] ∧ V_p>V_c-30)")
    print()
    # 판정: cosine 평균이 ~0 이면 LUT ∇V 와 closed-form 무관 — §2.5.9 재확인
    corner_cos = np.array([r["cos_corner"] for r in rows_corner], dtype=float)
    corner_cos = corner_cos[~np.isnan(corner_cos)]
    aligned = len(corner_cos) > 0 and abs(corner_cos.mean()) > 0.3
    print(f"  판정: high-τ_corner 영역 cos 평균 = "
          f"{corner_cos.mean():+.3f}  →  "
          f"{'정합 (LUT ∇V 유효)' if aligned else '불일치 (§2.5.9 재확인: 12⁶ LUT ∇V 약함 → closed-form regression path 정당)'}")
    return True


def main():
    print("=" * 72)
    print("  RT-3 item 2 — ∇V_i ↔ LUT cross-check")
    print("=" * 72)
    ok = run()
    print("=" * 72)
    return ok


if __name__ == "__main__":
    import sys
    sys.exit(0 if main() else 1)
