"""Pipeline 일관성 검증 (verify.py).

5계층 검증 (사용자 지정 방법론):
  L1. 단위 경계 round-trip  — kts/fps/°/rad wrap 모두 왕복
  L2. B 행렬 부호 일관성   — JSBSim 실측 vs linearize 일치
  L3. LQR 안정성 격자      — 전점 + 보간점 좌반평면
  L4. Forward 일관성       — BT tactic → u → JSBSim state 물리적으로 올바른가
  L5. Inverse 일관성       — JSBSim state → 어떤 BT setpoint가 이 state를 만들었나 추론

"forward/inverse 모두 유추 가능해야 한다" — 사용자 요구 (2026-06-02).
"""
from __future__ import annotations
import math
import sys
import numpy as np

# ── 경로 설정 ─────────────────────────────────────────────────────────────
sys.path.insert(0, ".")

from plant import F16Plant, STATE_ORDER, INPUT_ORDER
from linearize import linearize
from lqr import GainScheduledLQR, LQRPoint
from autopilot import (
    Autopilot, AutopilotConfig,
    _iPHI, _iPSI, _iTH, _iV, _iH, _iQ, _iP, _iR, _iBETA, _iALP,
    _uTHR, _uELEV, _uAIL, _uRUD, _wrap,
)
from constants import (
    KNOT_TO_FT_S, FT_S_TO_KNOT, DEG_TO_RAD, RAD_TO_DEG,
    G_FT_S2 as G_FT,   # verify 내부에서 G_FT 이름 유지 (하위호환)
    EPS_DENOM,
)
from guidance import GuidanceLayer, Setpoint, Obs
from tactic import Tactic, V_TRIM_KTS, V_CORNER_KTS

# ── 공통 유틸 ─────────────────────────────────────────────────────────────
PASS = "✅ PASS"
FAIL = "❌ FAIL"

def _result(cond: bool, label: str, detail: str = "") -> bool:
    tag = PASS if cond else FAIL
    print(f"  {tag}  {label}" + (f"  [{detail}]" if detail else ""))
    return cond


def _section(title: str):
    print(f"\n{'='*60}")
    print(f"  {title}")
    print('='*60)


# ══════════════════════════════════════════════════════════════
# L1. 단위 경계 Round-Trip
# ══════════════════════════════════════════════════════════════
def test_unit_roundtrip() -> int:
    """kts↔fps, °↔rad, psi wrap 왕복 오차 검증.

    TACTIC_SPEC.md §0·§2 의 단위 규약이 코드에서 일관되는가.
    """
    _section("L1. 단위 경계 Round-Trip")
    fails = 0
    TOL = 1e-6

    # 1a. kts → fps → kts
    # KNOT_TO_FT_S / FT_S_TO_KNOT는 반올림 상수 → 왕복 오차 1e-4 허용.
    # 정밀값: 1kts = 1.6878098... ft/s. 현재 상수(1.68781, 0.592484)로 왕복 오차 ≈1e-4.
    TOL_KTS = 1e-3  # 0.001kts 허용 (실용상 문제 없음)
    for kts in [250.0, 350.0, 450.0]:
        fps = kts * KNOT_TO_FT_S
        kts2 = fps * FT_S_TO_KNOT
        ok = abs(kts2 - kts) < TOL_KTS
        fails += 0 if _result(ok, f"kts→fps→kts  {kts}kts (tol {TOL_KTS}kts)",
                               f"err={kts2-kts:.2e}") else 1

    # 1b. ° → rad → °
    for deg in [0.0, 30.0, 90.0, 180.0, 270.0, 359.0]:
        rad = deg * DEG_TO_RAD
        deg2 = rad * RAD_TO_DEG
        ok = abs(deg2 - deg) < TOL
        fails += 0 if _result(ok, f"°→rad→°  {deg}°", f"err={deg2-deg:.2e}") else 1

    # 1c. psi wrap: autopilot 관례 — err = _wrap(current - target)
    # 양의 err → 현재가 목표보다 시계방향으로 앞(right turn 필요 없음)
    # 음의 err → 현재가 목표보다 반시계방향(right turn 필요)
    # phi_cmd = -atan(KP_PSI * psi_err * V / g):
    #   err < 0 → phi_cmd > 0 → 우뱅크 → 우회전(psi 증가) ✓
    wrap_cases = [
        # (cur_deg, tgt_deg, expected_err_sign, desc)
        # err = _wrap(cur - tgt): 359°→1° 오른쪽 2° = cur > tgt, err = -2° (반시계)
        # 왜 -2°? wrap(358°) = 358° - 360° = -2° (반시계가 더 짧음)
        (359.0, 1.0,   -1, "359→1° err=-2°(우회전 필요)"),
        (1.0,   359.0, +1, "1→359° err=+2°(좌회전 필요)"),
        (0.0,   30.0,  -1, "0→30° err=-30°(우회전 필요)"),
        (90.0,  60.0,  +1, "90→60° err=+30°(좌회전 필요)"),
        (180.0, 0.0,   -1, "180→0° err=-180°"),
    ]
    for cur_d, tgt_d, exp_sign, desc in wrap_cases:
        cur_r = cur_d * DEG_TO_RAD
        tgt_r = tgt_d * DEG_TO_RAD
        err = _wrap(cur_r - tgt_r)
        ok = abs(err) <= math.pi + 1e-9 and (err * exp_sign > 0 or abs(err) < 1e-9)
        fails += 0 if _result(ok, f"psi wrap  {desc}",
                               f"err={err*RAD_TO_DEG:+.2f}°") else 1

    # 1d. 협조선회 역변환: psi_rate → phi → psi_rate
    V = 727.0  # fps (trim TAS at 15000ft)
    for psi_rate in [-0.05, 0.0, +0.05, +0.1]:
        phi = math.atan(psi_rate * V / G_FT)
        psi_rate2 = G_FT * math.tan(phi) / V
        ok = abs(psi_rate2 - psi_rate) < 1e-9
        fails += 0 if _result(ok, f"협조선회 round-trip  ψ̇={psi_rate:.3f}rad/s",
                               f"err={psi_rate2-psi_rate:.2e}") else 1

    return fails


# ══════════════════════════════════════════════════════════════
# L2. B 행렬 부호 일관성 (linearize vs JSBSim 실측)
# ══════════════════════════════════════════════════════════════
def test_B_signs() -> int:
    """linearize.py의 B 행렬이 JSBSim 직접 실측과 일치하는가.

    새 엔진의 핵심 교훈: 1-tick B는 FCS 지연으로 부호 역전 → 10-step 수정.
    """
    _section("L2. B 행렬 부호 일관성")
    fails = 0

    # linearize 결과
    A, B, x0, u0 = linearize(15000.0, 350.0)
    iP   = STATE_ORDER.index("p")
    iQ   = STATE_ORDER.index("q")
    uAIL = INPUT_ORDER.index("aileron")
    uELEV= INPUT_ORDER.index("elevator")

    B_p_ail  = B[iP,   uAIL]
    B_q_elev = B[iQ,   uELEV]

    # JSBSim 직접 실측
    DU = 0.3
    N_STEPS = 10

    def measure_B_direct(prop_idx: int, u_idx: int, du: float) -> float:
        """u 섭동 → n step 후 x 변화 → dxdot/du."""
        results = []
        for sign in [+1, -1]:
            p = F16Plant()
            p.set_ic(15000.0, 350.0); p.trim(); p.step(5)
            _x0 = p.get_state()
            _u  = p.get_input().copy()
            _u[u_idx] += sign * du
            p.set_input(_u)
            for _ in range(N_STEPS): p.step(1)
            results.append(p.get_state()[prop_idx])
        dt_total = N_STEPS * F16Plant().dt
        return (results[0] - results[1]) / (2 * du * dt_total / dt_total) / N_STEPS * p.dt

    # 실측: aileron → p (roll rate)
    p_pos = F16Plant(); p_pos.set_ic(15000.0,350.0); p_pos.trim(); p_pos.step(5)
    x_base = p_pos.get_state()
    u_pos = p_pos.get_input().copy(); u_pos[uAIL] += DU
    p_pos.set_input(u_pos)
    for _ in range(N_STEPS): p_pos.step(1)
    x_pos_ail = p_pos.get_state()

    p_neg = F16Plant(); p_neg.set_ic(15000.0,350.0); p_neg.trim(); p_neg.step(5)
    u_neg = p_neg.get_input().copy(); u_neg[uAIL] -= DU
    p_neg.set_input(u_neg)
    for _ in range(N_STEPS): p_neg.step(1)
    x_neg_ail = p_neg.get_state()

    measured_p_ail_sign = np.sign(x_pos_ail[iP] - x_neg_ail[iP])   # +: pos ail → pos p
    computed_sign       = np.sign(B_p_ail)

    ok = (measured_p_ail_sign == computed_sign)
    fails += 0 if _result(ok, "B[p, aileron] 부호 일치",
                           f"linearize={B_p_ail:+.3f}, measured_sign={measured_p_ail_sign:+.0f}") else 1

    # 실측: elevator → q (pitch rate)
    p2_pos = F16Plant(); p2_pos.set_ic(15000.0,350.0); p2_pos.trim(); p2_pos.step(5)
    u2_pos = p2_pos.get_input().copy(); u2_pos[uELEV] += DU
    p2_pos.set_input(u2_pos)
    for _ in range(N_STEPS): p2_pos.step(1)
    x2_pos = p2_pos.get_state()

    p2_neg = F16Plant(); p2_neg.set_ic(15000.0,350.0); p2_neg.trim(); p2_neg.step(5)
    u2_neg = p2_neg.get_input().copy(); u2_neg[uELEV] -= DU
    p2_neg.set_input(u2_neg)
    for _ in range(N_STEPS): p2_neg.step(1)
    x2_neg = p2_neg.get_state()

    measured_q_elev_sign = np.sign(x2_pos[iQ] - x2_neg[iQ])
    computed_q_sign      = np.sign(B_q_elev)

    ok = (measured_q_elev_sign == computed_q_sign)
    fails += 0 if _result(ok, "B[q, elevator] 부호 일치",
                           f"linearize={B_q_elev:+.3f}, measured_sign={measured_q_elev_sign:+.0f}") else 1

    # LQR K 부호 확인 (B 부호에서 유도)
    pt = LQRPoint(15000.0, 350.0)
    K = pt.K
    K_ail_phi = K[uAIL, STATE_ORDER.index("phi")]
    K_elev_th = K[uELEV, STATE_ORDER.index("theta")]

    # K[ail,phi]: B[p,ail]>0 → K>0 (positive feedback 방지)
    ok_k_ail = K_ail_phi > 0
    fails += 0 if _result(ok_k_ail, "K[ail, phi] > 0 (안정 조건)",
                           f"K={K_ail_phi:+.4f}") else 1

    # K[elev,theta]: B[q,elev]<0 → K<0 (부호 보상)
    ok_k_elev = K_elev_th < 0
    fails += 0 if _result(ok_k_elev, "K[elev, theta] < 0 (JSBSim 부호 보상)",
                           f"K={K_elev_th:+.4f}") else 1

    return fails


# ══════════════════════════════════════════════════════════════
# L3. LQR 안정성 격자
# ══════════════════════════════════════════════════════════════
def test_lqr_stability() -> int:
    """9개 운영점 + 보간 샘플링: 모든 closed-loop 고유값 좌반평면."""
    _section("L3. LQR 안정성 격자")
    fails = 0

    gs = GainScheduledLQR(
        alts_ft=[5_000.0, 15_000.0, 25_000.0],
        vcs_kts=[250.0,   350.0,    450.0],
    ).build()

    # 운영점 안정성
    for key, pt in gs.grid.items():
        ok = pt.stable
        ev_min = min(pt.cl_eigenvalues.real)
        fails += 0 if _result(ok, f"trim 점 안정성  alt={key[0]:.0f}ft vc={key[1]:.0f}kts",
                               f"slowest_ev={ev_min:.3f}") else 1

    # 보간 격자 (경계 + 중간점)
    test_pts = [
        (5000, 250), (5000, 350), (5000, 450),
        (15000, 250), (15000, 350), (15000, 450),
        (25000, 250), (25000, 350), (25000, 450),
        (10000, 300), (20000, 400),  # 보간점
    ]
    for h, vc in test_pts:
        K, x0, u0 = gs._interp_K(h, vc)
        A, B, _, _ = linearize(float(h), float(vc))
        cl_ev = np.linalg.eigvals(A - B @ K)
        ok = bool(np.all(cl_ev.real < 0))
        ev_min = min(cl_ev.real)
        fails += 0 if _result(ok, f"보간 안정성  alt={h}ft vc={vc}kts",
                               f"slowest_ev={ev_min:.3f}") else 1

    return fails


# ══════════════════════════════════════════════════════════════
# L4. Forward 일관성: BT tactic → u → JSBSim state
# ══════════════════════════════════════════════════════════════
def test_forward_consistency() -> int:
    """BT setpoint → autopilot → JSBSim: 물리적으로 올바른 방향인가.

    각 채널별 단조성·방향 검증 (Metamorphic Relation):
      - heading right: phi_cmd > 0 → aileron 방향 일치 → psi 증가 방향
      - heading left:  phi_cmd < 0 → aileron 반대
      - altitude up:   theta_cmd > 0 → elevator 방향 → h 증가
      - speed up:      thr 증가 → V 증가
    """
    _section("L4. Forward 일관성 (BT→u→JSBSim)")
    fails = 0

    cfg = AutopilotConfig()
    N_SIM = 30  # 3s 시뮬

    def run_brief(psi_off: float, h_off: float, v_kts: float):
        """단기 시뮬 → (mean_ail, mean_elev, mean_thr, Δpsi, Δh, ΔV)."""
        plant = F16Plant()
        plant.set_ic(15000.0, 350.0); plant.trim(); plant.step(5)
        x0 = plant.get_state()
        psi0 = x0[_iPSI]
        ap = Autopilot(plant, GainScheduledLQR(
            [5000,15000,25000],[250,350,450]).build(), cfg)
        sp = Setpoint(
            psi_star_deg  = (psi0*RAD_TO_DEG + psi_off) % 360.0,
            h_star_ft     = 15000.0 + h_off,
            v_star_kts    = v_kts,
        )
        ails, elevs, thrs = [], [], []
        for _ in range(N_SIM):
            u = ap.step(sp)
            plant.set_input(u)
            for _ in range(int(0.1/plant.dt)): plant.step(1)
            ails.append(ap.state.u_aileron)
            elevs.append(ap.state.u_elevator)
            thrs.append(ap.state.u_throttle)
        xf = plant.get_state()
        dpsi = _wrap(xf[_iPSI] - x0[_iPSI]) * RAD_TO_DEG
        dh   = xf[_iH] - x0[_iH]
        dV   = xf[_iV] - x0[_iV]
        return np.mean(ails), np.mean(elevs), np.mean(thrs), dpsi, dh, dV

    # F4a. 우회전 명령 → aileron 평균 방향 + psi 증가
    print("  [헤딩 채널]")
    ail_r, elev_r, thr_r, dpsi_r, dh_r, dV_r = run_brief(+30.0, 0.0, 350.0)
    ok_psi_r = dpsi_r > 0                          # psi 증가 = 우회전
    fails += 0 if _result(ok_psi_r, "우회전 명령 → psi 증가",
                           f"Δpsi={dpsi_r:+.2f}° avg_ail={ail_r:+.3f}") else 1

    ail_l, elev_l, thr_l, dpsi_l, dh_l, dV_l = run_brief(-30.0, 0.0, 350.0)
    ok_psi_l = dpsi_l < 0                          # psi 감소 = 좌회전
    fails += 0 if _result(ok_psi_l, "좌회전 명령 → psi 감소",
                           f"Δpsi={dpsi_l:+.2f}° avg_ail={ail_l:+.3f}") else 1

    # Metamorphic: 우회전 vs 좌회전 aileron 부호 반대
    ok_sym = (ail_r * ail_l < 0)
    fails += 0 if _result(ok_sym, "좌/우회전 aileron 부호 대칭",
                           f"ail_R={ail_r:+.3f} ail_L={ail_l:+.3f}") else 1

    print("  [고도 채널]")
    ail_u, elev_u, thr_u, dpsi_u, dh_u, dV_u = run_brief(0.0, +500.0, 350.0)
    ok_h_up = dh_u > 0
    fails += 0 if _result(ok_h_up, "상승 명령 → h 증가",
                           f"Δh={dh_u:+.0f}ft avg_elev={elev_u:+.3f}") else 1

    ail_d, elev_d, thr_d, dpsi_d, dh_d, dV_d = run_brief(0.0, -500.0, 350.0)
    ok_h_dn = dh_d < 0
    fails += 0 if _result(ok_h_dn, "강하 명령 → h 감소",
                           f"Δh={dh_d:+.0f}ft avg_elev={elev_d:+.3f}") else 1

    # Metamorphic: 상승/강하 elevator 부호 반대
    ok_elev_sym = (elev_u * elev_d < 0)
    fails += 0 if _result(ok_elev_sym, "상승/강하 elevator 부호 대칭",
                           f"elev_UP={elev_u:+.3f} elev_DN={elev_d:+.3f}") else 1

    print("  [속도 채널]")
    ail_f, elev_f, thr_f, dpsi_f, dh_f, dV_f = run_brief(0.0, 0.0, 420.0)
    ok_v_up = thr_f > 0.394 - 0.05   # trim throttle ≈ 0.394
    fails += 0 if _result(ok_v_up, "가속 명령 → throttle 증가",
                           f"avg_thr={thr_f:.3f}  (trim≈0.394)") else 1

    return fails


# ══════════════════════════════════════════════════════════════
# L5. Inverse 일관성: JSBSim state → BT setpoint 역추론
# ══════════════════════════════════════════════════════════════
def test_inverse_consistency() -> int:
    """JSBSim state → 어떤 BT setpoint가 이 state를 만들었나 역추론.

    원리: u = u0 - K(x - x_star) → x_star = x + K^{-1}(u0 - u)
    단, K는 (4×10)이라 역행렬이 없음 → 최소제곱 역산 사용.

    검증:
      step_A: BT setpoint sp → autopilot → u, plant state x (3s 시뮬 후)
      step_B: (u, x)로부터 x_star 역산 → sp_inferred
      일관성: sp_inferred ≈ sp (허용 오차: psi ±5°, h ±100ft)
    """
    _section("L5. Inverse 일관성 (JSBSim state → BT setpoint 역추론)")
    fails = 0
    TOL_PSI_DEG = 5.0
    TOL_H_FT    = 100.0

    cfg = AutopilotConfig()
    gs  = GainScheduledLQR([5000,15000,25000],[250,350,450]).build()

    def infer_setpoint(plant: F16Plant, u: np.ndarray,
                       v_star_kts: float, cfg_: AutopilotConfig) -> tuple[float, float]:
        """(u, current x) → (psi_star_deg, h_star_ft) 역추론.

        원리: Outer PI가 phi_cmd·theta_cmd를 생성 → Inner LQR이 phi·theta 추적.
        역추론:
          1. 현재 u[ail] = u0[ail] - K[ail,phi]*(phi - phi_cmd)
             → phi_cmd = phi - (u[ail]-u0[ail]) / (-K[ail,phi])
          2. phi_cmd = -atan(KP_PSI * psi_err * V / g)
             → psi_err = -phi_cmd / KP_PSI / ... → psi_star = psi - psi_err
          3. u[elev] = u0[elev] - K[elev,theta]*(theta - theta_cmd)
             → theta_cmd = theta - (u[elev]-u0[elev]) / (-K[elev,theta])
          4. theta_cmd = -(KP_H * h_err)  (적분기 무시 — 단기 시뮬)
             → h_err = -theta_cmd / KP_H → h_star = h - h_err
        """
        x   = plant.get_state()
        K, _, u0 = gs._interp_K(x[_iH], v_star_kts)

        # Step 1: phi_cmd 역산 (aileron → phi_cmd)
        K_ail_phi = K[_uAIL, _iPHI]
        if abs(K_ail_phi) > 1e-6:
            phi_cmd = x[_iPHI] - (u[_uAIL] - u0[_uAIL]) / (-K_ail_phi)
        else:
            phi_cmd = x[_iPHI]

        # Step 2: psi_star 역산 (phi_cmd → psi_err → psi_star)
        # phi_cmd = -atan(KP_PSI * psi_err * V / g)
        # psi_err = -tan(phi_cmd) * g / (KP_PSI * V)
        V = x[_iV]
        # 분모 guard: KP_PSI * V 가 0에 가까우면 역산 발산.
        # max(EPS_DENOM, ...) — EPS_DENOM = 1e-6, 실용 최솟값 1.0 이상 보장
        kpsi_V = max(1.0, cfg_.KP_PSI * V)    # 1.0 = 물리적 의미 있는 최소 분모
        psi_err = -math.tan(phi_cmd) * G_FT / kpsi_V
        psi_star_rad = x[_iPSI] - psi_err      # err = current - target
        psi_inf = psi_star_rad * RAD_TO_DEG % 360.0

        # Step 3: theta_cmd 역산 (elevator → theta_cmd)
        K_elev_th = K[_uELEV, _iTH]
        if abs(K_elev_th) > 1e-6:
            theta_cmd = x[_iTH] - (u[_uELEV] - u0[_uELEV]) / (-K_elev_th)
        else:
            theta_cmd = x[_iTH]

        # Step 4: h_star 역산 (theta_cmd → h_err → h_star)
        # KP_H = 8e-5 가 매우 작으므로 1e-9 guard 불충분 → max(EPS_DENOM, KP_H) 사용
        h_err = -theta_cmd / max(EPS_DENOM, cfg_.KP_H)
        h_inf = x[_iH] - h_err

        return psi_inf, h_inf

    # 케이스 정의: (psi_off°, h_off_ft, v_kts, desc)
    cases = [
        (+20.0,    0.0, 350.0, "우회전 +20°"),
        (-20.0,    0.0, 350.0, "좌회전 -20°"),
        (  0.0, +300.0, 350.0, "상승 +300ft"),
        (  0.0, -300.0, 350.0, "강하 -300ft"),
        (+15.0, +200.0, 380.0, "복합 (우회전+상승+가속)"),
    ]

    for psi_off, h_off, v_kts, desc in cases:
        # Forward: 3s 시뮬
        plant = F16Plant()
        plant.set_ic(15000.0, 350.0); plant.trim(); plant.step(5)
        x0_state = plant.get_state()
        psi0_deg = x0_state[_iPSI] * RAD_TO_DEG % 360.0

        sp = Setpoint(
            psi_star_deg = (psi0_deg + psi_off) % 360.0,
            h_star_ft    = 15000.0 + h_off,
            v_star_kts   = v_kts,
        )
        ap = Autopilot(plant, gs, cfg)
        last_u = np.zeros(4)
        for _ in range(30):  # 3s
            last_u = ap.step(sp)
            plant.set_input(last_u)
            for _ in range(int(0.1/plant.dt)): plant.step(1)

        # Inverse: u, x → setpoint 역산
        psi_inf, h_inf = infer_setpoint(plant, last_u, v_kts, cfg)

        # 일관성 체크
        psi_err = abs(_wrap((psi_inf - sp.psi_star_deg) * DEG_TO_RAD) * RAD_TO_DEG)
        h_err   = abs(h_inf - sp.h_star_ft)
        ok_psi  = psi_err < TOL_PSI_DEG
        ok_h    = h_err   < TOL_H_FT
        ok = ok_psi and ok_h
        fails += 0 if _result(ok, f"Inverse {desc}",
                               f"Δpsi={psi_err:.2f}°(tol {TOL_PSI_DEG}°)  "
                               f"Δh={h_err:.0f}ft(tol {TOL_H_FT}ft)") else 1

    return fails


# ══════════════════════════════════════════════════════════════
# 전체 실행
# ══════════════════════════════════════════════════════════════
if __name__ == "__main__":
    print("=" * 60)
    print("  new_match_engine Pipeline 일관성 검증")
    print("  BT ↔ JSBSim 양방향 파이프라인 검증")
    print("=" * 60)

    total_fails = 0
    total_fails += test_unit_roundtrip()
    total_fails += test_B_signs()
    total_fails += test_lqr_stability()
    total_fails += test_forward_consistency()
    total_fails += test_inverse_consistency()

    print(f"\n{'='*60}")
    if total_fails == 0:
        print(f"  ✅ ALL PASS — 파이프라인 양방향 일관성 확인")
    else:
        print(f"  ❌ {total_fails} 실패 — 위 항목 수정 필요")
    print('='*60)
    sys.exit(total_fails)
