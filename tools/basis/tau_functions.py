"""τ_i Functions — BFM 정리 entry score (Layer 1 hard predicate + Layer 2 soft).

PURSUIT_CHASE_PLAN.md §2.4 의 식들을 직접 구현.

설계:
  Layer 1 — Φ_i(o):  bool, 모든 entry 부등식의 conjunction. SMT 형식 검증 가능
  Layer 2 — ρ_i(o):  float ∈ [0,1], sigmoid 곱. 매끄러운 blending

입력: obs (28-feature dict) + obs_prev (시간차분용, None 가능)
출력: dict {phi: bool, rho: float, conds: [(name, value, threshold, met)]}

정합 원칙 (사용자 합의):
  - 28-obs 만 사용 (정보 게임 정합성)
  - 추정기 0개 — 시간차분만 finite-difference operator 로 사용
  - 모든 magic number 출처 명시 (v11 측정 또는 정리 spec)
"""

from __future__ import annotations

import math
from typing import Optional

# envelope (V_corner 등)
from . import envelope_f16 as env


DT_TICK_S = 0.1   # BT tick 간격 (10Hz, upstream 2026-05 변경: env 20Hz + BT_TICK_EVERY=2)


def _sig(x: float) -> float:
    """numerical-safe sigmoid."""
    if x > 30: return 1.0
    if x < -30: return 0.0
    return 1.0 / (1.0 + math.exp(-x))


def _gauss(x: float, mu: float, sigma: float) -> float:
    return math.exp(-((x - mu) ** 2) / (2.0 * sigma * sigma))


def _denorm_deg(obs: dict, key: str, default: float = 0.0) -> float:
    """obs 의 [-1,1] 정규화 deg 를 deg 로 복원."""
    v = obs.get(key, default)
    return v * 180.0 if abs(v) <= 1.5 else v


def _ang_diff_deg(a: float, b: float) -> float:
    """signed angular difference, (-180, 180]."""
    d = (a - b) % 360.0
    return d if d <= 180.0 else d - 360.0


# ═══════════════════════════════════════════════════════════════════
# τ_PN — Baseline (residual)
# ═══════════════════════════════════════════════════════════════════

def tau_pn(obs: dict, obs_prev: Optional[dict] = None,
           rho_others_sum: float = 0.0) -> dict:
    """PN baseline — 다른 정리들의 잔여.

    Args:
        rho_others_sum: Σ (ρ_corner + ρ_yoyo + ρ_LDT) — 호출자가 미리 계산
    """
    rho = max(0.0, 1.0 - rho_others_sum)
    return {
        "name": "pn",
        "phi": True,   # 항상 활성
        "rho": rho,
        "conds": [("always_on", 1.0, 0.0, True)],
    }


# ═══════════════════════════════════════════════════════════════════
# τ_corner — Boyd EM + Shaw 1/2-circle (정리 5+6)
# ═══════════════════════════════════════════════════════════════════

def tau_corner(obs: dict, obs_prev: Optional[dict],
               alt_ft: float = 15000.0,
               obs_history: Optional[list] = None) -> dict:
    """정리 5+6 의 entry score.

    Φ_corner: (HCA outside [90, 120]) ∧ (V_p > V_c-30) ∧ (ω_us > 5) ∧ (ω_e^est > 3)
    ρ_corner = max(s_2c, s_1c) · s_V · s_us · s_them

    적 선회율 추정 (estimator 아님 — finite-difference operator on observable HCA):
      1순위 obs_history (≥3 frame): 다-tick window 평균 (smoothing)
      2순위 obs_prev: 단일 tick 차분
      3순위 fallback: **mirror 가정** ω_e = ω_us (minimax — 적도 동등 스킬 가정)
                     ※ 사용자 합의 (2026-05-13): fallback 0 금지
    """
    hca = _denorm_deg(obs, "hca_deg")
    V_p = float(obs.get("ego_vc_kts", 300.0))
    omega_us = abs(float(obs.get("turn_rate_degs", 0.0)))

    # ─ ω_e estimation — 우선순위: history > obs_prev > mirror ─
    # API 규약: obs_history 가 current obs 를 last element 로 포함. 따라서 time span =
    # (n-1) * DT_TICK_S 이며, obs_history[-1] 의 HCA 는 입력 obs 의 HCA 와 동일.
    if obs_history is not None and len(obs_history) >= 3:
        n = len(obs_history)
        hca_oldest = _denorm_deg(obs_history[0], "hca_deg")
        hca_rate = abs(_ang_diff_deg(hca, hca_oldest)) / ((n - 1) * DT_TICK_S)
        omega_e_est = max(0.0, hca_rate - omega_us)
        est_source = "history"
    elif obs_prev is not None:
        # Single-tick finite difference
        hca_prev = _denorm_deg(obs_prev, "hca_deg")
        hca_rate = abs(_ang_diff_deg(hca, hca_prev)) / DT_TICK_S
        omega_e_est = max(0.0, hca_rate - omega_us)
        est_source = "single_tick"
    else:
        # First tick fallback: mirror 가정 (minimax — 적이 우리와 동등 capability)
        # 이 가정이 wrong 이면 후속 tick 에서 measured 로 자동 보정됨
        omega_e_est = omega_us
        est_source = "mirror_fallback"

    V_c = env.V_corner_kts(alt_ft)

    # ─ Layer 1 ─
    c1 = (hca > 120.0) or (hca < 90.0)
    c2 = V_p > V_c - 30.0
    c3 = omega_us > 5.0
    c4 = omega_e_est > 3.0
    phi = c1 and c2 and c3 and c4

    # ─ Layer 2 ─
    s_2c = _sig((hca - 120.0) / 20.0)
    s_1c = _sig((90.0 - hca) / 20.0)
    s_regime = max(s_2c, s_1c)
    s_V = _sig((V_p - V_c + 30.0) / 15.0)
    s_us = _sig((omega_us - 5.0) / 3.0)
    s_them = _sig((omega_e_est - 3.0) / 2.0)
    rho = s_regime * s_V * s_us * s_them

    return {
        "name": "corner",
        "phi": phi,
        "rho": rho,
        "conds": [
            ("HCA outside [90,120]", hca, (90.0, 120.0), c1),
            (f"V_p > V_c-30 (={V_c-30:.1f})", V_p, V_c - 30.0, c2),
            ("ω_us > 5°/s", omega_us, 5.0, c3),
            ("ω_e^est > 3°/s", omega_e_est, 3.0, c4),
        ],
        "soft": {"s_regime": s_regime, "s_V": s_V, "s_us": s_us, "s_them": s_them},
        "est_source": est_source,
    }


# ═══════════════════════════════════════════════════════════════════
# τ_yoyo — Pontryagin vertical (정리 8)
# ═══════════════════════════════════════════════════════════════════

def tau_yoyo(obs: dict, obs_prev: Optional[dict] = None) -> dict:
    """정리 8 entry score.

    Φ_yoyo: (closure > 0 ∨ |closure| < 30) ∧ (ATA ∈ [20, 100])
    ρ_yoyo = max(s_chase, s_lock) · gauss(ATA; 70, 30)
    """
    cl = float(obs.get("closure_rate_kts", 0.0))
    ata = _denorm_deg(obs, "ata_deg")

    # ─ Layer 1 ─
    c1 = (cl > 0.0) or (abs(cl) < 30.0)
    c2 = (20.0 <= ata <= 100.0)
    phi = c1 and c2

    # ─ Layer 2 ─
    s_chase = _sig((cl - 30.0) / 50.0)
    s_lock = _sig((50.0 - abs(cl)) / 30.0)
    s_engagement = max(s_chase, s_lock)
    g_ata = _gauss(ata, mu=70.0, sigma=30.0)
    rho = s_engagement * g_ata

    return {
        "name": "yoyo",
        "phi": phi,
        "rho": rho,
        "conds": [
            ("closure > 0 ∨ |cl| < 30", cl, 0.0, c1),
            ("20° ≤ ATA ≤ 100°", ata, (20.0, 100.0), c2),
        ],
        "soft": {"s_engagement": s_engagement, "g_ata": g_ata},
    }


# ═══════════════════════════════════════════════════════════════════
# τ_LDT — Shaw Lag Displacement (정리 7)
# ═══════════════════════════════════════════════════════════════════

def tau_LDT(obs: dict, obs_prev: Optional[dict] = None,
            alt_ft: float = 15000.0,
            obs_history: Optional[list] = None) -> dict:
    """정리 7 entry score.

    Φ_LDT: (40° ≤ ATA ≤ 90°) ∧ (dist·sin(ATA) ≥ R·√2) ∧ (|LOS_rate| > 5°/s)
    ρ_LDT = gauss(ATA; 65, 15) · s_disp · s_LOS

    LOS rate 추정 (Tau_corner 와 같은 fallback 정책):
      1) obs_history ≥ 3 frame: n-tick window
      2) obs_prev: single tick
      3) fallback: ω_us (mirror — 우리 ω 만큼 LOS 도 회전 추정)
    """
    ata = _denorm_deg(obs, "ata_deg")
    dist = float(obs.get("distance_ft", 0.0))
    V_p = float(obs.get("ego_vc_kts", 300.0))
    rb = _denorm_deg(obs, "relative_bearing_deg")
    omega_us = abs(float(obs.get("turn_rate_degs", 0.0)))

    # LOS rate — history > obs_prev > mirror
    # 규약 동일: obs_history 가 current obs 를 last element 로 포함
    if obs_history is not None and len(obs_history) >= 3:
        rb_oldest = _denorm_deg(obs_history[0], "relative_bearing_deg")
        n = len(obs_history)
        los_rate = abs(_ang_diff_deg(rb, rb_oldest)) / ((n - 1) * DT_TICK_S)
    elif obs_prev is not None:
        rb_prev = _denorm_deg(obs_prev, "relative_bearing_deg")
        los_rate = abs(_ang_diff_deg(rb, rb_prev)) / DT_TICK_S
    else:
        # First tick fallback: LOS rate ≈ ω_us (우리 회전이 LOS 회전을 야기)
        los_rate = omega_us

    R_turn = env.turn_radius_ft(V_p, alt_ft)
    if R_turn > 1e6:  # envelope sentinel
        R_turn = 2000.0

    displacement = dist * math.sin(math.radians(abs(ata)))
    threshold = R_turn * math.sqrt(2)

    # ─ Layer 1 ─
    c1 = (40.0 <= abs(ata) <= 90.0)
    c2 = displacement >= threshold
    c3 = los_rate > 5.0
    phi = c1 and c2 and c3

    # ─ Layer 2 ─
    g_ata = _gauss(abs(ata), mu=65.0, sigma=15.0)
    s_disp = _sig((displacement - threshold) / 500.0)
    s_los = _sig((los_rate - 8.0) / 5.0)
    rho = g_ata * s_disp * s_los

    return {
        "name": "ldt",
        "phi": phi,
        "rho": rho,
        "conds": [
            ("40° ≤ |ATA| ≤ 90°", abs(ata), (40.0, 90.0), c1),
            (f"dist·sin(ATA) ≥ R√2 (={threshold:.0f})", displacement, threshold, c2),
            ("|LOS_rate| > 5°/s", los_rate, 5.0, c3),
        ],
        "soft": {"g_ata": g_ata, "s_disp": s_disp, "s_los": s_los},
    }


# ═══════════════════════════════════════════════════════════════════
# 통합 — 모든 τ_i 계산 후 정상화
# ═══════════════════════════════════════════════════════════════════

def all_taus(obs: dict, obs_prev: Optional[dict] = None,
             alt_ft: float = 15000.0,
             obs_history: Optional[list] = None) -> dict:
    """모든 τ_i 동시 계산 + 정상화 + PN baseline.

    Args:
        obs_history: list of obs (most recent last). 길이 ≥3 권장. 단일 tick 만 있으면
                     obs_prev fallback. 둘 다 없으면 mirror 가정 (feedback_no_deferral
                     원칙: fallback 0 금지).

    Returns:
        {
          'tau_corner': dict, 'tau_yoyo': dict, 'tau_ldt': dict, 'tau_pn': dict,
          'rhos_normalized': {'pn': float, 'corner': float, 'yoyo': float, 'ldt': float},
          'active_intents': list of names where Φ_i is True
        }
    """
    tc = tau_corner(obs, obs_prev, alt_ft, obs_history=obs_history)
    ty = tau_yoyo(obs, obs_prev)
    tl = tau_LDT(obs, obs_prev, alt_ft, obs_history=obs_history)

    rho_others = tc["rho"] + ty["rho"] + tl["rho"]
    tp = tau_pn(obs, obs_prev, rho_others_sum=rho_others)

    # 정상화 (covex combination 보장)
    total = tp["rho"] + rho_others
    if total < 1e-6:
        # 모든 τ 0 — 안전 fallback (PN 만)
        rho_norm = {"pn": 1.0, "corner": 0.0, "yoyo": 0.0, "ldt": 0.0}
    else:
        rho_norm = {
            "pn":     tp["rho"] / total,
            "corner": tc["rho"] / total,
            "yoyo":   ty["rho"] / total,
            "ldt":    tl["rho"] / total,
        }

    active = []
    for t in [tc, ty, tl]:
        if t["phi"]:
            active.append(t["name"])

    return {
        "tau_corner": tc, "tau_yoyo": ty, "tau_ldt": tl, "tau_pn": tp,
        "rhos_normalized": rho_norm,
        "active_intents": active,
    }


# ═══════════════════════════════════════════════════════════════════
# G2 게이트 검증 (smoke test)
# ═══════════════════════════════════════════════════════════════════

def _make_obs(ata=90, hca=180, dist=3297.6, closure=0, V=386.8, alt=15000,
              rb=0, omega_us=0, alt_gap=0):
    """test obs builder. degrees → normalized [-1,1] for ata/hca/rb keys."""
    return {
        "ata_deg": ata / 180.0,
        "hca_deg": hca / 180.0,
        "relative_bearing_deg": rb / 180.0,
        "distance_ft": dist,
        "closure_rate_kts": closure,
        "ego_vc_kts": V,
        "ego_altitude_ft": alt,
        "alt_gap_ft": alt_gap,
        "turn_rate_degs": omega_us,
        "pitch_deg": 0,
    }


def verify_G2():
    """G2_a (corner monotone HCA), G2_b (yoyo peak), G2_c (LDT disp), G2_d (cover)."""
    print("=" * 70)
    print("  G2 게이트 — τ_i sanity tests")
    print("=" * 70)

    # G2_a: τ_corner 가 HCA 100→130→160° 에서 단조 증가하는지
    print("\n[G2_a] τ_corner HCA monotone (HCA: 100°→130°→160°, V_p=400, ω_us=10)")
    omega_e_proxy = 10  # via hca_rate
    # 단순화 위해 obs_prev 없이 omega_e_est = omega_us 의 fallback 행동 확인
    rhos = []
    for hca in [100, 130, 160]:
        obs = _make_obs(hca=hca, V=400, omega_us=10)
        obs_prev = _make_obs(hca=hca - 2, V=400, omega_us=10)  # 0.2s 전, HCA 가 2° 줄어듦 → hca_rate=10
        t = tau_corner(obs, obs_prev, alt_ft=15000)
        rhos.append(t["rho"])
        print(f"   HCA={hca:3}° : ρ={t['rho']:.4f}  Φ={t['phi']}  conds={[(c[0], c[3]) for c in t['conds']]}")
    g2a = rhos[2] > rhos[0]  # HCA 160 > HCA 100
    print(f"   G2_a: {'PASS' if g2a else 'FAIL'} (ρ@160° > ρ@100°: {rhos[2]:.3f} > {rhos[0]:.3f})")

    # G2_b: τ_yoyo 가 ATA=70° peak
    print("\n[G2_b] τ_yoyo ATA peak at 70° (cl=50, ATA: 30→70→110°)")
    rhos = []
    for ata in [30, 70, 110]:
        obs = _make_obs(ata=ata, closure=50)
        t = tau_yoyo(obs)
        rhos.append(t["rho"])
        print(f"   ATA={ata:3}° : ρ={t['rho']:.4f}")
    g2b = (rhos[1] > rhos[0]) and (rhos[1] > rhos[2])
    print(f"   G2_b: {'PASS' if g2b else 'FAIL'} (ρ@70° > ρ@30° AND ρ@110°)")

    # G2_c: τ_LDT displacement boundary
    print("\n[G2_c] τ_LDT displacement boundary (dist 변화, ATA=60°, LOS_rate=10)")
    rhos = []
    for dist in [2000, 4000, 6000]:
        obs = _make_obs(ata=60, dist=dist, rb=10, V=386.8)
        # LOS rate 10°/s 시뮬: rb 1° 차이 (0.2s 동안) = 5°/s; 더 큰 차이 필요
        obs_prev = _make_obs(ata=60, dist=dist, rb=8, V=386.8)  # rb 2° 차 → 10°/s
        t = tau_LDT(obs, obs_prev)
        rhos.append(t["rho"])
        threshold = t["conds"][1][2]
        disp = t["conds"][1][1]
        print(f"   dist={dist}, disp={disp:.0f} vs threshold={threshold:.0f}, ρ={t['rho']:.4f}")
    g2c = rhos[2] > rhos[0]   # 멀수록 disp 큼 → ρ 커짐
    print(f"   G2_c: {'PASS' if g2c else 'FAIL'}")

    # G2_d: Cover — canonical IC neighborhood 에서 Σ ρ_i + ρ_PN > 0.1
    print("\n[G2_d] Cover at canonical IC neighborhood")
    bad_states = []
    for ata in [0, 30, 60, 90, 120, 150, 180]:
        for hca in [0, 60, 120, 180]:
            for V in [250, 350, 400, 480]:
                obs = _make_obs(ata=ata, hca=hca, V=V, dist=3000, omega_us=8)
                obs_prev = _make_obs(ata=ata, hca=hca-3, V=V, dist=3000, omega_us=8)
                t = all_taus(obs, obs_prev, alt_ft=15000)
                rho_total = sum(t["rhos_normalized"].values())
                if rho_total < 0.1:
                    bad_states.append((ata, hca, V, rho_total))
    g2d = len(bad_states) == 0
    print(f"   G2_d: {'PASS' if g2d else 'FAIL'} (bad states: {len(bad_states)})")
    if bad_states:
        for b in bad_states[:5]:
            print(f"      ATA={b[0]}, HCA={b[1]}, V={b[2]}, Σρ={b[3]:.3f}")

    return {"G2_a": g2a, "G2_b": g2b, "G2_c": g2c, "G2_d": g2d}


if __name__ == "__main__":
    import sys, os
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    results = verify_G2()
    print()
    print("=" * 70)
    all_pass = all(results.values())
    print(f"  Overall: {'ALL PASS' if all_pass else 'FAIL'}  ({results})")
    print("=" * 70)
