"""τ-blended Continuous Policy — PursuitChaseOptimal 의 핵심 정책 함수.

PURSUIT_CHASE_PLAN.md §2.3-2.4 의 합성:
  ∇V_approx = Σ ρ_i · ∇V_i / Σ ρ_i
  u* = -sign(B_d^T · ∇V_approx) · u_max(V_p, alt)
  BT bin = quantize(u*) — 양자화는 마지막 단계만

본 모듈은 BT 노드와 분리되어 단위 테스트 가능 / SMT 검증 가능 / pytest 적용 가능.
"""

from __future__ import annotations

import math
import os
from pathlib import Path
from typing import Optional, Tuple

import numpy as np

# tools.basis 직접 import (BT 노드 컨텍스트에서 작동하도록 explicit path)
import importlib.util as _ilu


_PROJECT_ROOT = Path(__file__).resolve().parents[3]
_TOOLS_BASIS = _PROJECT_ROOT / "tools" / "basis"


def _load_module(name: str, path: Path):
    spec = _ilu.spec_from_file_location(name, path)
    mod = _ilu.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# envelope_f16 → gradient_approximators → tau_functions (의존 순서)
env_mod = _load_module("_env", _TOOLS_BASIS / "envelope_f16.py")
# gradient_approximators 가 envelope_f16 을 from . import 로 부르므로 우회 필요
# 직접 함수만 노출
_grad_path = _TOOLS_BASIS / "gradient_approximators.py"
_tau_path = _TOOLS_BASIS / "tau_functions.py"


def _load_with_env_dep(full_name: str, path: Path):
    """envelope_f16 의존성을 sys.modules 에 주입 + full package name 으로 로드.

    `from . import envelope_f16` 같은 relative import 가 작동하려면:
      1. parent package (tools.basis) 가 sys.modules 에 등록되어야 함
      2. 모듈 자체가 full name (tools.basis.X) 로 spec 생성되어야 함
    """
    import sys
    if "tools" not in sys.modules:
        pkg_tools = type(sys)("tools")
        pkg_tools.__path__ = [str(_PROJECT_ROOT / "tools")]
        sys.modules["tools"] = pkg_tools
    if "tools.basis" not in sys.modules:
        pkg_basis = type(sys)("tools.basis")
        pkg_basis.__path__ = [str(_TOOLS_BASIS)]
        sys.modules["tools.basis"] = pkg_basis
    if "tools.basis.envelope_f16" not in sys.modules:
        sys.modules["tools.basis.envelope_f16"] = env_mod
    return _load_module(full_name, path)


grad_mod = _load_with_env_dep("tools.basis.gradient_approximators", _grad_path)
tau_mod = _load_with_env_dep("tools.basis.tau_functions", _tau_path)


# Public re-exports
optimal_control = grad_mod.optimal_control
all_taus = tau_mod.all_taus
omega_max_rad_s = env_mod.omega_max_rad_s
gamma_rate_max_rad_s = env_mod.gamma_rate_max_rad_s
V_corner_kts = env_mod.V_corner_kts


# ═══════════════════════════════════════════════════════════════════
# obs → 6D state x
# ═══════════════════════════════════════════════════════════════════

def obs_to_state_6d(obs: dict) -> np.ndarray:
    """28-feature obs → (Δx, Δy, Δh, Δψ, V_p, V_e) — V_e 는 closure-based 추정.

    좌표계 (custom_actions.py:113 _obs_to_state 와 일치):
      Δx > 0: 적 우측, Δy > 0: 적 전방, Δh > 0: 적이 위
      sim CSV convention: rb_deg > 0 = LEFT (CCW math) → dx = -dist·sin(rb)
    """
    rb_raw = obs.get("relative_bearing_deg", 0.0)
    rb_deg = rb_raw * 180.0 if abs(rb_raw) <= 1.5 else rb_raw
    dist = float(obs.get("distance_ft", 0.0))
    rb_rad = math.radians(rb_deg)
    dx = -dist * math.sin(rb_rad)
    dy = +dist * math.cos(rb_rad)
    dh = float(obs.get("alt_gap_ft", 0.0))

    hca_raw = obs.get("hca_deg", 0.0)
    hca_deg = hca_raw * 180.0 if abs(hca_raw) <= 1.5 else hca_raw
    dpsi = math.radians(hca_deg)

    V_p = float(obs.get("ego_vc_kts", 386.8))
    # V_e 추정: closure 기반 단순 점추정 (R4 에서 marginalize 로 개선)
    closure = float(obs.get("closure_rate_kts", 0.0))
    V_e = max(160.0, V_p - closure)   # closure = V_p_LOS - V_e_LOS, 1차 근사

    return np.array([dx, dy, dh, dpsi, V_p, V_e], dtype=np.float64)


# ═══════════════════════════════════════════════════════════════════
# u* (continuous) → BT bins (alt, hdg, vel) — quantization 만 last step
# ═══════════════════════════════════════════════════════════════════

def quantize_to_bins(u_star: np.ndarray,
                      V_p: float, alt_ft: float) -> Tuple[int, int, int]:
    """연속 u_star (ω rad/s, γ̇ rad/s, a kts/s) → (alt_bin, hdg_bin, vel_bin).

    Bin convention (BT API):
      alt: 0=max descend, 2=hold, 4=max climb
      hdg: 0=max left, 4=straight, 8=max right  (※ B_d convention: ω>0=좌회전,
            따라서 u_star[0] > 0 → hdg < 4)
      vel: 0=max decel, 2=hold, 4=max accel

    Envelope V-의존 정규화:
      bin = center + round(u_star / u_max(V, alt) · half_range)
    """
    omega, gamma_dot, accel = u_star
    omega_max = env_mod.omega_max_rad_s(V_p, alt_ft) + 1e-6
    gamma_max = env_mod.gamma_rate_max_rad_s(V_p, alt_ft) + 1e-6
    accel_max = 15.0   # TODO: thrust-drag 식 derive

    # hdg: B_d convention 에서 ω > 0 = 좌회전 → bin < 4
    # 따라서 hdg_bin = 4 - round(omega / omega_max * 4)
    hdg_offset = -omega / omega_max * 4.0
    hdg_bin = int(round(4 + hdg_offset))
    hdg_bin = max(0, min(8, hdg_bin))

    # alt: γ̇ > 0 = climb = alt_bin > 2
    alt_offset = gamma_dot / gamma_max * 2.0
    alt_bin = int(round(2 + alt_offset))
    alt_bin = max(0, min(4, alt_bin))

    # vel: a > 0 = accel = vel_bin > 2
    vel_offset = accel / accel_max * 2.0
    vel_bin = int(round(2 + vel_offset))
    vel_bin = max(0, min(4, vel_bin))

    return alt_bin, hdg_bin, vel_bin


# ═══════════════════════════════════════════════════════════════════
# 단일 tick 정책 (PursuitChaseOptimal.update() 가 호출하는 함수)
# ═══════════════════════════════════════════════════════════════════

# ═══════════════════════════════════════════════════════════════════
# HJI LUT lookup (R7) — wire 진정한 V*(x) numerical 해
# ═══════════════════════════════════════════════════════════════════

import numpy as _np

_LUT_PATH = os.environ.get("PURSUIT_LUT_PATH",
                            str(_PROJECT_ROOT / "logs" / "hji" / "V6d_wez_v3.npz"))
_LUT_DATA = None
_LUT_COORDS = None
_LUT_SPACINGS = None


def _load_lut():
    global _LUT_DATA, _LUT_COORDS, _LUT_SPACINGS
    if _LUT_DATA is not None:
        return
    p = Path(_LUT_PATH)
    if not p.exists():
        return
    d = _np.load(p)
    _LUT_DATA = _np.asarray(d["V"])
    _LUT_COORDS = tuple(_np.asarray(d[f"coord_{i}"]) for i in range(6))
    _LUT_SPACINGS = tuple(float(c[1] - c[0]) if len(c) > 1 else 1.0 for c in _LUT_COORDS)


def _grad_V_lut(x: _np.ndarray) -> Tuple[float, _np.ndarray]:
    """LUT 에서 V 와 central-difference ∇V."""
    _load_lut()
    if _LUT_DATA is None:
        return 0.0, _np.zeros(6)
    idx = tuple(int(_np.argmin(_np.abs(_LUT_COORDS[d] - x[d]))) for d in range(6))
    V_val = float(_LUT_DATA[idx])
    grad = _np.zeros(6)
    for d in range(6):
        n_d = _LUT_DATA.shape[d]
        i_p = list(idx); i_m = list(idx)
        i_p[d] = min(idx[d] + 1, n_d - 1)
        i_m[d] = max(idx[d] - 1, 0)
        V_p_d = float(_LUT_DATA[tuple(i_p)])
        V_m_d = float(_LUT_DATA[tuple(i_m)])
        dx_step = max(_LUT_SPACINGS[d], 1e-6)
        grad[d] = (V_p_d - V_m_d) / (2.0 * dx_step)
    return V_val, grad


def _optimal_control_lut(x: _np.ndarray, alt_ft: float) -> Tuple[_np.ndarray, dict]:
    """LUT 기반 직접 정책 — V_adv 우회. R7 검증용."""
    V, grad = _grad_V_lut(x)
    B_d = grad_mod.B_d_matrix(x)
    BtG = B_d.T @ grad
    V_p = x[4]
    omega_max = env_mod.omega_max_rad_s(V_p, alt_ft)
    gamma_dot_max = env_mod.gamma_rate_max_rad_s(V_p, alt_ft)
    accel_max = 15.0
    u_max = _np.array([omega_max, gamma_dot_max, accel_max])
    # Smooth saturation — 같은 typical-magnitude 기반
    # LUT 의 BtG 는 V_adv 보다 크기 차이 큼 → 다른 BTG_SCALE 사용
    BTG_SCALE_LUT = _np.array([300.0, 1000.0, 200.0])  # LUT 실측 ∇V·B_d 기반
    gain = u_max / (BTG_SCALE_LUT + 1e-9)
    u_raw = -BtG * gain
    u_star = _np.clip(u_raw, -u_max, +u_max)
    info = {"V_lut": V, "grad_lut": grad, "BtG": BtG, "u_star": u_star, "u_max": u_max}
    return u_star, info


# Branch dispatcher (RT-1) — hybrid differential game mode 선택
_dispatcher_path = _PROJECT_ROOT / "examples" / "pursuit_chase_v1" / "nodes" / "branch_dispatcher.py"
_dispatcher_mod = _load_module("_branch_dispatcher", _dispatcher_path)
select_branch = _dispatcher_mod.select_branch
cmd_HardDeck = _dispatcher_mod.cmd_HardDeck
cmd_GunEngagement = _dispatcher_mod.cmd_GunEngagement
cmd_OffensivePursuit = _dispatcher_mod.cmd_OffensivePursuit


def compute_action(obs: dict, obs_prev: Optional[dict] = None,
                    alt_ft: Optional[float] = None,
                    obs_history: Optional[list] = None,
                    ) -> Tuple[Tuple[int, int, int], dict]:
    """단일 tick — obs → (alt, hdg, vel) bins.

    환경변수 PURSUIT_POLICY_MODE:
      'hybrid' (default RT-1): branch dispatcher + τ-blend + LUT fallback (PLAN §2.6)
      'vadv':                  R3 의 V_adv τ-blended 정책 (legacy)
      'lut':                   R7 LUT 직접 lookup (V_adv 우회)
      'blend':                 0.5·V_adv + 0.5·LUT (가중 평균)
    """
    if alt_ft is None:
        alt_ft = float(obs.get("ego_altitude_ft", 15000.0))

    # State 추출
    x = obs_to_state_6d(obs)
    V_p = float(obs.get("ego_vc_kts", 386.8))
    policy_mode = os.environ.get("PURSUIT_POLICY_MODE", "hybrid").lower()

    # τ_i 계산 (history wire-up)
    tau_result = all_taus(obs, obs_prev, alt_ft=alt_ft, obs_history=obs_history)
    rhos = tau_result["rhos_normalized"]

    # 정책 mode 분기
    if policy_mode == "hybrid":
        # RT-1: branch dispatcher 우선, TheoremAdaptive 면 τ-blend + LUT
        branch_info = select_branch(obs, alt_ft)
        branch = branch_info["branch"]
        if branch == "HardDeck":
            u_star = _np.array(cmd_HardDeck(obs))
            info = {"mode": "hybrid:HardDeck", "branch_reason": branch_info["reason"],
                    "BtG": _np.zeros(3), "u_max": _np.array([0.35, 0.25, 15.0]), "u_star": u_star}
        elif branch == "GunEngagement":
            u_star = _np.array(cmd_GunEngagement(obs, V_p, alt_ft))
            info = {"mode": "hybrid:GunEng", "branch_reason": branch_info["reason"],
                    "BtG": _np.zeros(3), "u_max": _np.array([0.35, 0.25, 15.0]), "u_star": u_star}
        elif branch == "OffensivePursuit":
            u_star = _np.array(cmd_OffensivePursuit(obs, V_p, alt_ft))
            info = {"mode": "hybrid:OffPursuit", "branch_reason": branch_info["reason"],
                    "BtG": _np.zeros(3), "u_max": _np.array([0.35, 0.25, 15.0]), "u_star": u_star}
        else:
            # TheoremAdaptive — τ-blend + LUT 보조
            rho_sum = rhos["corner"] + rhos["yoyo"] + rhos["ldt"] + rhos["pn"]
            if rho_sum > 0.1:
                # 정리 영역 — V_adv ensemble
                u_vadv, info_vadv = optimal_control(x, rhos, alt_ft=alt_ft)
                u_star = u_vadv
                info = {**info_vadv, "mode": "hybrid:Theorem", "branch_reason": branch_info["reason"]}
            else:
                # 정리 부족 — LUT fallback
                u_lut, info_lut = _optimal_control_lut(x, alt_ft)
                u_star = u_lut
                info = {**info_lut, "mode": "hybrid:LUT", "branch_reason": branch_info["reason"]}
    elif policy_mode == "lut":
        u_star, info = _optimal_control_lut(x, alt_ft)
        info["mode"] = "lut"
    elif policy_mode == "blend":
        u_lut, info_lut = _optimal_control_lut(x, alt_ft)
        u_vadv, info_vadv = optimal_control(x, rhos, alt_ft=alt_ft)
        u_star = 0.5 * u_lut + 0.5 * u_vadv
        info = {**info_vadv, "mode": "blend", "V_lut": info_lut["V_lut"], "u_lut": u_lut, "u_vadv": u_vadv}
    else:
        u_star, info = optimal_control(x, rhos, alt_ft=alt_ft)
        info["mode"] = "vadv"

    # Quantize 마지막에
    alt_bin, hdg_bin, vel_bin = quantize_to_bins(u_star, V_p, alt_ft)

    # mode-별 grad key 통일 (LUT 모드에선 grad_lut, V_adv 에선 grad_approx)
    grad_key = info.get("grad_approx", info.get("grad_lut", _np.zeros(6)))
    if hasattr(grad_key, "tolist"):
        grad_list = grad_key.tolist()
    else:
        grad_list = list(grad_key)

    diag = {
        "x": x.tolist(),
        "u_star": u_star.tolist(),
        "BtG": info["BtG"].tolist(),
        "grad_approx": grad_list,
        "u_max": info["u_max"].tolist(),
        "rhos": rhos,
        "active_intents": tau_result["active_intents"],
        "alt_bin": alt_bin,
        "hdg_bin": hdg_bin,
        "vel_bin": vel_bin,
        "mode": info.get("mode", "vadv"),
    }
    return (alt_bin, hdg_bin, vel_bin), diag


# ═══════════════════════════════════════════════════════════════════
# 진단 CSV 로깅
# ═══════════════════════════════════════════════════════════════════

_CSV_PATH = os.environ.get("PURSUIT_CONT_LOG", "")
_CSV_FILE = None
_CSV_TICK = 0


def _csv_open():
    global _CSV_FILE, _CSV_TICK
    if not _CSV_PATH or _CSV_FILE is not None:
        return _CSV_FILE
    p = Path(_CSV_PATH)
    p.parent.mkdir(parents=True, exist_ok=True)
    _CSV_FILE = open(p, "w", encoding="utf-8")
    header = ("tick,dx,dy,dh,dpsi,V_p,V_e,"
              "u_omega_dps,u_gamma_dps,u_a_kts,"
              "BtG_w,BtG_g,BtG_a,"
              "omega_max_dps,gamma_max_dps,"
              "rho_pn,rho_corner,rho_yoyo,rho_ldt,"
              "phi_corner,phi_yoyo,phi_ldt,"
              "alt_bin,hdg_bin,vel_bin,"
              "active_intents\n")
    _CSV_FILE.write(header)
    _CSV_TICK = 0
    return _CSV_FILE


def log_tick(diag: dict, tau_result: dict):
    global _CSV_TICK
    f = _csv_open()
    if f is None:
        return
    x = diag["x"]
    u = diag["u_star"]
    BtG = diag["BtG"]
    u_max = diag["u_max"]
    rhos = diag["rhos"]
    tc = tau_result["tau_corner"]
    ty = tau_result["tau_yoyo"]
    tl = tau_result["tau_ldt"]
    active = "|".join(diag["active_intents"]) if diag["active_intents"] else "none"
    row = [
        _CSV_TICK,
        f"{x[0]:.1f}", f"{x[1]:.1f}", f"{x[2]:.1f}", f"{x[3]:.3f}",
        f"{x[4]:.1f}", f"{x[5]:.1f}",
        f"{math.degrees(u[0]):.2f}", f"{math.degrees(u[1]):.2f}", f"{u[2]:.2f}",
        f"{BtG[0]:.3e}", f"{BtG[1]:.3e}", f"{BtG[2]:.3e}",
        f"{math.degrees(u_max[0]):.2f}", f"{math.degrees(u_max[1]):.2f}",
        f"{rhos['pn']:.3f}", f"{rhos['corner']:.3f}", f"{rhos['yoyo']:.3f}", f"{rhos['ldt']:.3f}",
        int(tc["phi"]), int(ty["phi"]), int(tl["phi"]),
        diag["alt_bin"], diag["hdg_bin"], diag["vel_bin"],
        active,
    ]
    f.write(",".join(str(v) for v in row) + "\n")
    f.flush()
    _CSV_TICK += 1
