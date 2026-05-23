"""12D joint state z + 6D relative 변환 + Es 도출.

design ref: PHASE1_MPC_DESIGN.md §3.

원칙:
    - 추정 step 0. 모든 값은 obs 직접 or 사칙연산.
    - opp ω 는 *유일하게 모르는 값* — Phase 1 = 0 가정. (history 누적 후 finite-diff 가능).
    - V_opp 도출 = Es 기반 (closure 기반보다 정확).
"""

from __future__ import annotations

import math

import numpy as np


G_FT_S2 = 32.174   # ft/s²
KTS_TO_FPS = 1.68781

# state index (per-side 6D)
IDX_X = 0
IDX_Y = 1
IDX_H = 2
IDX_PSI = 3
IDX_V = 4
IDX_OMEGA = 5

# joint 12D: us = [0:6], opp = [6:12]
SLICE_US = slice(0, 6)
SLICE_OPP = slice(6, 12)


def _denorm_deg(obs: dict, key: str, default: float = 0.0) -> float:
    """obs value 가 normalized (±1.5 이내) 면 ×180, else raw."""
    v = obs.get(key, default)
    return v * 180.0 if abs(v) <= 1.5 else v


def obs_to_state_12d(obs: dict) -> np.ndarray:
    """28 obs → 12D joint state z = (x_us, x_opp).

    좌표계:
        us frame origin (0,0,h_us), us heading ψ_us=0 (body axis 정의)
        opp 는 us frame 에서 relative bearing + distance + alt_gap.

    per-side: x = (x, y, h, ψ, V, ω_turn)
        x, y: ft (us 기준 east/north 같은 frame)
        h: ft (msl)
        ψ: rad (heading)
        V: kts (calibrated)
        ω: rad/s (turn rate, horizontal)
    """
    # === us side ===
    h_us = float(obs.get("ego_altitude_ft", 15000.0))
    V_us = float(obs.get("ego_vc_kts", 386.8))
    # turn_rate_degs is in deg/s → convert to rad/s
    omega_us_deg_s = float(obs.get("turn_rate_degs", 0.0))
    # turn_rate_degs may also be normalized (some env conventions); detect by magnitude
    if abs(omega_us_deg_s) <= 1.5:
        omega_us_deg_s *= 180.0
    omega_us = math.radians(omega_us_deg_s)

    x_us = np.array([0.0, 0.0, h_us, 0.0, V_us, omega_us])

    # === opp side ===
    rb_deg = _denorm_deg(obs, "relative_bearing_deg")
    rb_rad = math.radians(rb_deg)
    dist = float(obs.get("distance_ft", 0.0))
    dx = dist * math.sin(rb_rad)
    dy = dist * math.cos(rb_rad)

    alt_gap = float(obs.get("alt_gap_ft", 0.0))
    h_opp = h_us + alt_gap

    hca_deg = _denorm_deg(obs, "hca_deg")
    psi_opp = math.radians(hca_deg)

    # V_opp via Es (more accurate than closure-based)
    # Es_us = h_us + V_us²/(2g)  [V in fps]
    # energy_diff_ft = Es_us - Es_opp  → Es_opp = Es_us - energy_diff
    V_us_fps = V_us * KTS_TO_FPS
    Es_us = h_us + V_us_fps ** 2 / (2.0 * G_FT_S2)
    energy_diff = float(obs.get("energy_diff_ft", 0.0))
    Es_opp = Es_us - energy_diff
    # V_opp_fps² = 2g (Es_opp - h_opp), clamp non-negative
    V_opp_fps_sq = max(0.0, 2.0 * G_FT_S2 * (Es_opp - h_opp))
    V_opp_fps = math.sqrt(V_opp_fps_sq)
    V_opp = V_opp_fps / KTS_TO_FPS
    # fallback: if obs is missing energy_diff or value is nonsense, use closure-based estimate
    if not math.isfinite(V_opp) or V_opp < 100.0 or V_opp > 800.0:
        closure = float(obs.get("closure_rate_kts", 0.0))
        V_opp = max(160.0, min(480.0, V_us - closure))

    omega_opp = 0.0   # Phase 1: unknown → 0. history 누적 후 finite-diff 도입 가능.

    x_opp = np.array([dx, dy, h_opp, psi_opp, V_opp, omega_opp])

    return np.concatenate([x_us, x_opp])


def z_to_relative_6d(z: np.ndarray) -> np.ndarray:
    """12D z → 기존 6D relative x = (Δx, Δy, Δh, Δψ, V_p, V_e).

    *기존 optimal_control / ∇V_i 호환용*. RT-1.3 convention 그대로.
    """
    x_us = z[SLICE_US]
    x_opp = z[SLICE_OPP]
    dx = x_opp[IDX_X] - x_us[IDX_X]
    dy = x_opp[IDX_Y] - x_us[IDX_Y]
    dh = x_opp[IDX_H] - x_us[IDX_H]
    dpsi = x_opp[IDX_PSI] - x_us[IDX_PSI]
    V_p = x_us[IDX_V]
    V_e = x_opp[IDX_V]
    return np.array([dx, dy, dh, dpsi, V_p, V_e])


# ──────────────────────────────────────────────────────────────────
# derived quantities (geometry, energy, turn radius)
# ──────────────────────────────────────────────────────────────────


def specific_energy_ft(h_ft: float, V_kts: float) -> float:
    """Es = h + V²/(2g). Boyd EM."""
    V_fps = V_kts * KTS_TO_FPS
    return h_ft + V_fps ** 2 / (2.0 * G_FT_S2)


def turn_radius_ft(V_kts: float, omega_rad_s: float, eps: float = 1e-3) -> float:
    """R = V/ω. V in fps, ω in rad/s."""
    V_fps = V_kts * KTS_TO_FPS
    return V_fps / max(abs(omega_rad_s), eps)


def geometry_from_z(z: np.ndarray) -> dict:
    """z → geometry dict: dist, ata, aa, hca, closure (instantaneous)."""
    x_us = z[SLICE_US]
    x_opp = z[SLICE_OPP]
    dx = x_opp[IDX_X] - x_us[IDX_X]
    dy = x_opp[IDX_Y] - x_us[IDX_Y]
    dh = x_opp[IDX_H] - x_us[IDX_H]
    dist = math.sqrt(dx * dx + dy * dy + dh * dh)
    # ATA = angle from our nose (ψ_us) to opp position vector
    # us nose points along (sin ψ_us, cos ψ_us)
    nose_us = np.array([math.sin(x_us[IDX_PSI]), math.cos(x_us[IDX_PSI])])
    to_opp = np.array([dx, dy])
    horiz_dist = math.sqrt(dx * dx + dy * dy) + 1e-9
    cos_ata = float(np.dot(nose_us, to_opp / horiz_dist))
    cos_ata = max(-1.0, min(1.0, cos_ata))
    ata_deg = math.degrees(math.acos(cos_ata))
    # AA = angle from opp nose to us
    nose_opp = np.array([math.sin(x_opp[IDX_PSI]), math.cos(x_opp[IDX_PSI])])
    to_us = -to_opp
    cos_aa = float(np.dot(nose_opp, to_us / horiz_dist))
    cos_aa = max(-1.0, min(1.0, cos_aa))
    aa_deg = math.degrees(math.acos(cos_aa))
    # HCA = ψ_opp - ψ_us reduced to [0,180]
    hca_raw = math.degrees(x_opp[IDX_PSI] - x_us[IDX_PSI])
    hca_deg = abs(((hca_raw + 180.0) % 360.0) - 180.0)
    return {
        "dist_ft": dist,
        "ata_deg": ata_deg,
        "aa_deg": aa_deg,
        "hca_deg": hca_deg,
    }


def _self_test():
    """sanity: obs_to_state_12d → z_to_relative_6d round-trip ≈ obs_to_state_6d."""
    obs = {
        "ego_altitude_ft": 15000.0,
        "ego_vc_kts": 386.8,
        "turn_rate_degs": 2.0,
        "relative_bearing_deg": 30.0,
        "distance_ft": 5000.0,
        "alt_gap_ft": 200.0,
        "hca_deg": 60.0,
        "energy_diff_ft": -500.0,
        "closure_rate_kts": 10.0,
    }
    z = obs_to_state_12d(obs)
    x_rel = z_to_relative_6d(z)
    print(f"z = {z}")
    print(f"x_rel = {x_rel}")
    print(f"geometry = {geometry_from_z(z)}")
    print(f"Es_us = {specific_energy_ft(15000, 386.8):.1f} ft")
    print(f"R_us = {turn_radius_ft(386.8, math.radians(2.0)):.1f} ft")
    # smoke check
    assert len(z) == 12
    assert len(x_rel) == 6
    print("[state.py] self-test PASS")


if __name__ == "__main__":
    _self_test()
