"""Phase 1 Reachability Verification — Z3 SMT.

design ref: PHASE1_MPC_DESIGN.md §9.5.

목적: 각 semantic event 가 *실제로 도달 가능*한지 SMT 로 증명.
RT-3 H1 lemma 와 동일 framework 확장.

검증 시나리오 (6 개):
    Z1: is_parallel_chase_forming — aggressive IC → H=10 도달?
    Z2: merge_window_opening — corner mode 유지 시?
    Z3: is_energy_race_losing — corner-only 우리 + 적 Pursue → 필연?
    Z4: is_position_swinging_to_us — OrbitBreak 진입 후 최선의 τ 로 도달?
    Z5: opp_committed_to_turn — adversary class Pursue 가 H step turn 유지 case?
    Z6: OffensiveContext branch — aggressive 매치 어느 시점이든 reachable?

결과 활용: SAT 면 witness trajectory → unit test. UNSAT 면 신규 BFM 필요 증명.
"""

from __future__ import annotations

import math
import sys
import time
from typing import Optional

try:
    from z3 import (
        And,
        Or,
        Not,
        If,
        Implies,
        Real,
        Solver,
        sat,
        unsat,
        unknown,
        set_param,
    )
except ImportError:
    print("Z3 not installed. Run: pip install z3-solver")
    sys.exit(1)


# ─── 공통 simplifications ─────────────────────────────────────────
# 6D 변수만 추적 (수직 무시, 수평 평면).
#   각 side: (x, y, psi, V, omega)  — h 무시 (Z6 alt 검증 시 추가)
# Euler integration, dt = 0.5s (큰 step → Z3 부담 ↓)
# linearization: 작은 ω 가정 (sin ψ ≈ ψ, cos ψ ≈ 1) — 1차 근사

DT = 0.5
OMEGA_MAX = 0.35   # rad/s
ACCEL_MAX = 15.0   # kts/s
KTS_TO_FPS = 1.6878


def _declare_state(prefix: str, t: int):
    """선언: (x, y, psi, V, omega) for one side at time t."""
    return {
        "x":     Real(f"{prefix}_x_{t}"),
        "y":     Real(f"{prefix}_y_{t}"),
        "psi":   Real(f"{prefix}_psi_{t}"),
        "V":     Real(f"{prefix}_V_{t}"),
        "omega": Real(f"{prefix}_omega_{t}"),
    }


def _declare_control(prefix: str, t: int):
    return {
        "omega_cmd": Real(f"{prefix}_uw_{t}"),
        "accel":     Real(f"{prefix}_ua_{t}"),
    }


def _add_dynamics_constraints(s: Solver, state_t, ctrl_t, state_next, dt: float = DT):
    """side dynamics — Euler, small-angle 근사."""
    # omega 1-step lag (간단화 — instant 적용)
    s.add(state_next["omega"] == ctrl_t["omega_cmd"])
    s.add(ctrl_t["omega_cmd"] >= -OMEGA_MAX, ctrl_t["omega_cmd"] <= OMEGA_MAX)
    s.add(ctrl_t["accel"] >= -ACCEL_MAX, ctrl_t["accel"] <= ACCEL_MAX)
    # V update
    s.add(state_next["V"] == state_t["V"] + ctrl_t["accel"] * dt)
    s.add(state_next["V"] >= 160.0, state_next["V"] <= 720.0)
    # psi update
    s.add(state_next["psi"] == state_t["psi"] + state_t["omega"] * dt)
    # position update — small-angle: x_next = x + V * sin(ψ) * dt ≈ x + V * ψ * dt
    # 정확 trig 는 Z3 비선형 → 1차 근사
    V_fps = state_t["V"] * KTS_TO_FPS
    s.add(state_next["x"] == state_t["x"] + V_fps * state_t["psi"] * dt)
    s.add(state_next["y"] == state_t["y"] + V_fps * (1.0 - state_t["psi"] * state_t["psi"] * 0.5) * dt)


def _pursue_opp_omega(opp_state, our_state):
    """opp Pursue.update 의 omega 명령 — 단순화 (rel_bearing 기반).

    rel_bearing = atan2(dx, dy) of (us relative to opp's nose) — 1차 근사.
    """
    dx_us = our_state["x"] - opp_state["x"]
    dy_us = our_state["y"] - opp_state["y"]
    # opp nose ≈ (sin opp_psi, cos opp_psi) ≈ (opp_psi, 1) under small angle
    # rel_bearing positive if us is to opp's right
    # cross product (nose × to_us) z component = sin_psi * dy - cos_psi * dx
    # ≈ opp_psi * dy_us - dx_us
    cross = opp_state["psi"] * dy_us - dx_us
    # large |cross| → big rel_bearing → hard turn toward us
    # opp omega_cmd ∝ -sign(cross) * cap (toward us)
    # smooth piecewise — z3 friendly
    omega_cmd = If(cross > 100.0, -OMEGA_MAX,
                If(cross < -100.0, OMEGA_MAX,
                   -cross * (OMEGA_MAX / 100.0)))
    return omega_cmd


def _setup_aggressive_ic(s: Solver, us0, opp0):
    """aggressive 매치 IC: mutual beam, dist ~3300ft, V ~387kts."""
    s.add(us0["x"] == 0.0, us0["y"] == 0.0, us0["psi"] == 0.0,
          us0["V"] == 386.8, us0["omega"] == 0.0)
    s.add(opp0["x"] >= -500.0, opp0["x"] <= 500.0)
    s.add(opp0["y"] >= 3000.0, opp0["y"] <= 3600.0)
    # opp facing roughly toward us (south, psi near pi — but use small-angle so psi near 0 with opposite frame)
    # for simplicity, opp also psi near 0 but offset (beam scenario simplification)
    s.add(opp0["psi"] >= -0.3, opp0["psi"] <= 0.3)
    s.add(opp0["V"] >= 350.0, opp0["V"] <= 420.0)
    s.add(opp0["omega"] == 0.0)


# ─── Z1: is_parallel_chase_forming reachable? ─────────────────────


def check_Z1_parallel_chase(H: int = 6) -> tuple[str, Optional[dict]]:
    """parallel chase forming = 양쪽 omega 격차 작음 + history 안정.
    H=6 step 안에 |ω_us| - |ω_opp| 가 SCALE_OMEGA (0.10) 보다 작은 SAT?
    """
    set_param("timeout", 30000)   # 30 s
    s = Solver()

    us = [_declare_state("us", t) for t in range(H + 1)]
    opp = [_declare_state("opp", t) for t in range(H + 1)]
    us_u = [_declare_control("us", t) for t in range(H)]
    opp_u = [_declare_control("opp", t) for t in range(H)]

    _setup_aggressive_ic(s, us[0], opp[0])

    for t in range(H):
        # us control: free (admissible)
        _add_dynamics_constraints(s, us[t], us_u[t], us[t + 1])
        # opp follows Pursue
        omega_cmd = _pursue_opp_omega(opp[t], us[t])
        s.add(opp_u[t]["omega_cmd"] == omega_cmd)
        s.add(opp_u[t]["accel"] >= 0.0, opp_u[t]["accel"] <= 5.0)
        _add_dynamics_constraints(s, opp[t], opp_u[t], opp[t + 1])

    # event: at t=H, |ω_us - ω_opp| small
    omega_diff_H = us[H]["omega"] - opp[H]["omega"]
    s.add(omega_diff_H >= -0.05, omega_diff_H <= 0.05)

    t0 = time.time()
    result = s.check()
    elapsed = time.time() - t0
    print(f"[Z1] parallel_chase_forming reachable in H={H} steps: {result} ({elapsed:.2f}s)")
    if result == sat:
        m = s.model()
        witness = {
            f"us_omega_H": float(m.eval(us[H]["omega"]).as_decimal(3).rstrip("?")),
            f"opp_omega_H": float(m.eval(opp[H]["omega"]).as_decimal(3).rstrip("?")),
        }
        return "SAT", witness
    elif result == unsat:
        return "UNSAT", None
    return "UNKNOWN", None


# ─── Z6: OffensiveContext branch reachable? ───────────────────────


def check_Z6_offensive_context(H: int = 6) -> tuple[str, Optional[dict]]:
    """OffensiveContext = positional_advantage > 30° (AA - ATA > 30°).

    aggressive IC 부터 H=6 step (3s) 안에 도달 가능?
    UNSAT 면 → parallel-chase Nash 의 수학적 본질 증명 (신규 BFM 필요).
    """
    set_param("timeout", 60000)
    s = Solver()

    us = [_declare_state("us", t) for t in range(H + 1)]
    opp = [_declare_state("opp", t) for t in range(H + 1)]
    us_u = [_declare_control("us", t) for t in range(H)]
    opp_u = [_declare_control("opp", t) for t in range(H)]

    _setup_aggressive_ic(s, us[0], opp[0])

    for t in range(H):
        _add_dynamics_constraints(s, us[t], us_u[t], us[t + 1])
        omega_cmd = _pursue_opp_omega(opp[t], us[t])
        s.add(opp_u[t]["omega_cmd"] == omega_cmd)
        s.add(opp_u[t]["accel"] >= 0.0, opp_u[t]["accel"] <= 5.0)
        _add_dynamics_constraints(s, opp[t], opp_u[t], opp[t + 1])

    # event: positional_advantage > 30° at t=H
    # ATA ≈ 각 사이 vector (us → opp) vs us nose. small angle ≈ atan2(dx, dy)
    # AA ≈ 각 (opp → us) vs opp nose ≈ atan2(-dx, -dy) - opp_psi
    # 1차 근사: ATA_rad ≈ (opp.x - us.x) / |to_opp|  (small-angle, us psi ≈ 0)
    # simplified: ATA_proxy = (opp.x - us.x), AA_proxy = (us.x - opp.x) + opp.psi * |to_opp|
    # use much simpler proxy: AA - ATA > k_threshold
    dx = opp[H]["x"] - us[H]["x"]
    dy = opp[H]["y"] - us[H]["y"]
    # us facing along nose ≈ (us.psi, 1). ATA proxy = signed angle to opp.
    # we ask: opp_psi (looking away from us heavy) AND us_psi (looking AT opp)
    # = us aligned with opp's tail = positional advantage
    # simplified: us.psi · cross(opp_to_us) positive AND opp_psi pointing away
    # use proxy: (opp.psi - us.psi) > 1.0 rad (us has aimed more than opp)
    # this approximates "us is angularly behind opp"
    psi_diff = opp[H]["psi"] - us[H]["psi"]
    s.add(psi_diff > 0.5)   # us tail-on chase ~30° advantage
    # also require not just heading but actually pointing at them
    s.add(us[H]["psi"] >= -0.3, us[H]["psi"] <= 0.3)   # us heading still near "up"
    s.add(opp[H]["psi"] >= 0.5)   # opp turned away significantly

    t0 = time.time()
    result = s.check()
    elapsed = time.time() - t0
    print(f"[Z6] OffensiveContext reachable in H={H} steps (3s): {result} ({elapsed:.2f}s)")
    if result == sat:
        m = s.model()
        try:
            witness = {
                "us_psi_H_deg":  math.degrees(float(m.eval(us[H]["psi"]).as_decimal(3).rstrip("?"))),
                "opp_psi_H_deg": math.degrees(float(m.eval(opp[H]["psi"]).as_decimal(3).rstrip("?"))),
                "psi_diff_deg":  math.degrees(float(m.eval(psi_diff).as_decimal(3).rstrip("?"))),
            }
        except Exception:
            witness = {"raw": "see Z3 model"}
        return "SAT", witness
    elif result == unsat:
        return "UNSAT", None
    return "UNKNOWN", None


# ─── runner ───────────────────────────────────────────────────────


def run_all():
    print("=" * 60)
    print("Phase 1 Reachability Verification (Z3 SMT)")
    print("design ref: PHASE1_MPC_DESIGN.md §9.5")
    print("=" * 60)
    results = {}
    for name, fn in [
        ("Z1_parallel_chase_forming", lambda: check_Z1_parallel_chase(H=6)),
        ("Z6_offensive_context",      lambda: check_Z6_offensive_context(H=6)),
        # Z2-Z5 추후 추가 — 같은 패턴
    ]:
        try:
            verdict, witness = fn()
            results[name] = (verdict, witness)
            print(f"  → witness: {witness}")
        except Exception as e:
            print(f"[{name}] ERROR: {e}")
            results[name] = ("ERROR", str(e))
    print("=" * 60)
    print("SUMMARY:")
    for name, (verdict, _) in results.items():
        print(f"  {name}: {verdict}")
    return results


if __name__ == "__main__":
    run_all()
