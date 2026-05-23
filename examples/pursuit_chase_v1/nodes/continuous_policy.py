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


def _load_module_with_preregister(name: str, path: Path):
    """@dataclass 가 sys.modules 등록 필요 — selective pre-register variant.
    dynamics_f16_6d.py 처럼 module-level @dataclass 가 있는 파일 전용.
    """
    import sys
    spec = _ilu.spec_from_file_location(name, path)
    mod = _ilu.module_from_spec(spec)
    sys.modules[name] = mod
    try:
        spec.loader.exec_module(mod)
    except Exception:
        sys.modules.pop(name, None)
        raise
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
# B'-0 (Model B' running cost): WEZ damage rate
_wez_path = _TOOLS_BASIS / "wez_damage_rate.py"
wez_mod = _load_module("tools.basis.wez_damage_rate", _wez_path)
# dynamics_f16_6d.py 는 module-level @dataclass 가 있어 pre-register 필수
_dyn_path = _TOOLS_BASIS / "dynamics_f16_6d.py"
import sys as _sys
if "tools" not in _sys.modules:
    _pkg_tools = type(_sys)("tools"); _pkg_tools.__path__ = [str(_PROJECT_ROOT / "tools")]
    _sys.modules["tools"] = _pkg_tools
if "tools.basis" not in _sys.modules:
    _pkg_basis = type(_sys)("tools.basis"); _pkg_basis.__path__ = [str(_TOOLS_BASIS)]
    _sys.modules["tools.basis"] = _pkg_basis
if "tools.basis.envelope_f16" not in _sys.modules:
    _sys.modules["tools.basis.envelope_f16"] = env_mod
dyn_mod = _load_module_with_preregister("tools.basis.dynamics_f16_6d", _dyn_path)


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

    좌표계 (dynamics_f16_6d_hj.py 와 일치 — LUT 도 이 convention 으로 solve):
      Δx > 0: 적 우측, Δy > 0: 적 전방, Δh > 0: 적이 위
      sim convention (RT-1.3 stub 실측 확정): rb_deg > 0 = RIGHT
      (README + side_flag 일치; rb=-90° ↔ side_flag=-1 ↔ 적 좌측)
      → dx = +dist·sin(rb)  [rb>0 우측 → dx>0 우측]
    """
    rb_raw = obs.get("relative_bearing_deg", 0.0)
    rb_deg = rb_raw * 180.0 if abs(rb_raw) <= 1.5 else rb_raw
    dist = float(obs.get("distance_ft", 0.0))
    rb_rad = math.radians(rb_deg)
    dx = +dist * math.sin(rb_rad)
    dy = +dist * math.cos(rb_rad)
    dh = float(obs.get("alt_gap_ft", 0.0))

    hca_raw = obs.get("hca_deg", 0.0)
    hca_deg = hca_raw * 180.0 if abs(hca_raw) <= 1.5 else hca_raw
    dpsi = math.radians(hca_deg)

    V_p = float(obs.get("ego_vc_kts", 386.8))
    # V_e 추정: closure 기반 단순 점추정. Stage-2 버그 수정 — 비-stern 기하에선
    # closure 에 각속도 성분이 섞여 V_e 가 폭주(측정상 1260kts) → F-16 envelope
    # [160,420] 으로 clamp (적도 equal-spec F-16, 물리적으로 bounded).
    closure = float(obs.get("closure_rate_kts", 0.0))
    V_e = min(480.0, max(160.0, V_p - closure))

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
cmd_HardDeck = _dispatcher_mod.cmd_HardDeck            # 안전 분기 (∇V 무관)
cmd_DefensiveBreak = _dispatcher_mod.cmd_DefensiveBreak  # 위협 회피 (escape, ∇V 무관)
cmd_TurnAround = _dispatcher_mod.cmd_TurnAround        # 적 후방+도망 → 결정적 hard-turn
cmd_ZoomClimb = _dispatcher_mod.cmd_ZoomClimb          # 도망적 장거리 → PE 축적 climb
# cmd_GunEngagement/OffensivePursuit/OrbitBreak — superseded by ∇V-derived
# optimal_control mode-τ mapping below (PLAN §2.6.5). 참조 구현은 branch_dispatcher.py 에 유지.


def compute_action(obs: dict, obs_prev: Optional[dict] = None,
                    alt_ft: Optional[float] = None,
                    obs_history: Optional[list] = None,
                    prev_branch: str = "",
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

    # BFM mode → τ 매핑 (PLAN §2.6.2/§2.6.5): branch dispatcher 가 mode 를 선택하고,
    # 명령은 그 mode 의 *verified* ∇V 에서 optimal_control 로 산출 — heuristic gain 제거.
    #   GunEngagement/OffensivePursuit → m_2 PN (∇V_PN: ATA→0 + dist→d_WEZ)
    #     + m_T (ZEM capture-time, H1 lemma 회피 — V_PN 의 V_dist ω+a 채널 ≡ 0 보완)
    #   LagPursuit                     → m_5 LDT (∇V_LDT: overshoot 변위 누적)
    #   OrbitBreak                     → m_3/m_4 corner + PN (energy 비대칭 + 적 방향 유지)
    _MODE_TAU = {
        "GunEngagement":    {"pn": 1.0},
        "OffensivePursuit": {"pn": 0.6, "T": 0.4},    # m_T 추가 — closing-favorable regime
        "EnergyRecovery":   {"corner": 1.0},          # 순수 직진 가속 — 선회 시 바로 재고갈 (Boyd EM)
        "LagPursuit":       {"ldt": 1.0},
        "OrbitBreak":       {"pn": 0.5, "corner": 0.5},   # {0.3,0.7} 시도 → 양쪽 회귀. 균형 유지.
        # "LongRangeClosing" REVERTED 2026-05-16 (C1) — simple 보존했으나 defensive 3W→0W 회귀.
        "InitialPhaseAccel": {"corner": 1.0},   # B'-2 (2026-05-16): mutual beam IC V_p 보존
        "PatientApproach":   {"corner": 0.7, "pn": 0.3},   # 2026-05-16: V_p 보존 + 작은 PN turn (white-box exploit)
        "AggressiveCloseMerge": {"T": 0.7, "pn": 0.3},    # B-1 (2026-05-16): trend-based, Heron 패턴.
                                                           # V_T dominant (capture-time close-merge) + ATA-aim stabilization.
    }

    # 정책 mode 분기
    _mpc_succeeded = False   # mpc 성공 시 아래 hybrid/lut/blend/else 분기 스킵
    if policy_mode == "mpc":
        # Phase 1 MPC — design ref: docs/PHASE1_MPC_DESIGN.md
        # try-except → fallback to hybrid (회귀 0 보장)
        try:
            from ..mpc import state as _mpc_st
            from ..mpc import features as _mpc_feat
            from ..mpc.adversary.oracle import OracleAdversary
            from ..mpc.solvers.mppi import MPPISolver
            from ..mpc.tau_param.piecewise_constant import PiecewiseConstant3Segment
            from .branch_dispatcher_v2 import select_branch_v2, SAFETY_CMD
            # singleton init (모듈 scope cache 권장 — 일단 매 tick 재생성 비용 작음)
            global _MPC_SOLVER_CACHE, _MPC_ADV_CACHE, _MPC_PARAMS_CACHE
            try:
                _MPC_SOLVER_CACHE
            except NameError:
                _MPC_SOLVER_CACHE = MPPISolver(
                    tau_param=PiecewiseConstant3Segment(H=10),
                    N_samples=int(os.environ.get("MPC_N_SAMPLES", "32")),
                    H=10, lambda_temp=0.1, sigma=0.15, seed=42,
                )
                _MPC_ADV_CACHE = {}
                _MPC_PARAMS_CACHE = None
            bt_type = os.environ.get("ADVERSARY_BT_TYPE", "pursue")
            if bt_type not in _MPC_ADV_CACHE:
                _MPC_ADV_CACHE[bt_type] = OracleAdversary(bt_type)
            adversary = _MPC_ADV_CACHE[bt_type]
            # state + features
            z = _mpc_st.obs_to_state_12d(obs)
            feat_ext = _mpc_feat.DefaultFeatureExtractor()
            features = feat_ext.extract(z, obs, history=obs_history)
            # dispatcher v2
            br = select_branch_v2(obs, alt_ft, features)
            if not br.get("use_mpc", True):
                # SAFETY tier — heuristic cmd
                u_star = _np.array(SAFETY_CMD[br["branch"]](obs))
                info = {"mode": f"mpc:safety:{br['branch']}", "branch_reason": br["reason"],
                        "BtG": _np.zeros(3), "u_max": _np.array([0.35, 0.25, 15.0]), "u_star": u_star}
            else:
                # CONTEXT tier — MPPI
                tau_traj, mpc_info = _MPC_SOLVER_CACHE.solve(
                    z0=z, admissible=br["admissible"],
                    adversary=adversary, features_init=features,
                    prior_params=_MPC_PARAMS_CACHE,
                )
                # warm-start for next tick
                _MPC_PARAMS_CACHE = _MPC_SOLVER_CACHE.tau_param.shift_warm_start(
                    mpc_info["params_new"])
                # extract τ_0 → optimal_control
                tau_0 = mpc_info["tau_0"]
                u_star, info = optimal_control(x, tau_0, alt_ft=alt_ft)
                info["mode"] = f"mpc:{br['branch']}"
                info["branch_reason"] = br["reason"]
                info["mpc_elapsed_ms"] = mpc_info["elapsed_ms"]
                info["mpc_cost_min"] = mpc_info["cost_min"]
                info["tau_0"] = tau_0
            _mpc_succeeded = True
        except Exception as e:
            # fallback: hybrid (회귀 0 보장)
            policy_mode = "hybrid"
            print(f"[MPC fallback] {repr(e)}")

    if not _mpc_succeeded and policy_mode == "hybrid":
        # RT-1: branch dispatcher 우선, TheoremAdaptive 면 τ-blend + LUT
        branch_info = select_branch(obs, alt_ft, prev_branch=prev_branch,
                                     obs_history=obs_history)
        branch = branch_info["branch"]
        if branch == "HardDeck":
            # 안전 분기 — game-theoretic mode 아님 (강제 상승), heuristic 유지
            u_star = _np.array(cmd_HardDeck(obs))
            info = {"mode": "hybrid:HardDeck", "branch_reason": branch_info["reason"],
                    "BtG": _np.zeros(3), "u_max": _np.array([0.35, 0.25, 15.0]), "u_star": u_star}
        elif branch == "DefensiveBreak":
            # 위협 회피 — escape maneuver (capture ∇V 의 반대), heuristic safety
            u_star = _np.array(cmd_DefensiveBreak(obs))
            info = {"mode": "hybrid:DefensiveBreak", "branch_reason": branch_info["reason"],
                    "BtG": _np.zeros(3), "u_max": _np.array([0.35, 0.25, 15.0]), "u_star": u_star}
        elif branch == "BreakInduce":
            # γ (2026-05-16): 적 강한 closing 유도 break. DefensiveBreak 와 동일 cmd 사용.
            u_star = _np.array(cmd_DefensiveBreak(obs))
            info = {"mode": "hybrid:BreakInduce", "branch_reason": branch_info["reason"],
                    "BtG": _np.zeros(3), "u_max": _np.array([0.35, 0.25, 15.0]), "u_star": u_star}
        elif branch == "TurnAround":
            # 적 후방+도망 → 결정적 max-turn (τ-blend 우회, FP-robust)
            u_star = _np.array(cmd_TurnAround(obs))
            info = {"mode": "hybrid:TurnAround", "branch_reason": branch_info["reason"],
                    "BtG": _np.zeros(3), "u_max": _np.array([0.35, 0.25, 15.0]), "u_star": u_star}
        elif branch == "ZoomClimb":
            # 도망적 장거리 → PE 축적 climb (Boyd EM banking)
            u_star = _np.array(cmd_ZoomClimb(obs))
            info = {"mode": "hybrid:ZoomClimb", "branch_reason": branch_info["reason"],
                    "BtG": _np.zeros(3), "u_max": _np.array([0.35, 0.25, 15.0]), "u_star": u_star}
        elif branch in _MODE_TAU:
            # ∇V-derived 명령 — 해당 BFM mode 의 verified closed-form gradient
            u_star, info = optimal_control(x, _MODE_TAU[branch], alt_ft=alt_ft)
            info["mode"] = f"hybrid:{branch}"
            info["branch_reason"] = branch_info["reason"]
        else:
            # TheoremAdaptive — full τ-blend + LUT 보조
            # [α/α'/α''/α''' REVERTED 2026-05-16]: anticipatory rollout 13 cycle 누적 학습
            #   모두 R7 위반 (특히 α''' 가 simple 5W→2W/3L 처음 LOSS 야기) 또는 aggressive 무진전.
            #   결정: DSBT §6.1 (a) symmetric trap 의 *결정적 경험 증명* — Model A 안에서
            #         dispatcher/anticipatory 변경으로 aggressive Nash 깨기 불가.
            #   다음: Model B' (running cost HP 누적) 또는 RL 학습 path.
            #   anticipatory 코드 자체는 보존 (학습 자산, 미래 cycle 의 baseline).
            # β NN inference (env var BETA_NN_WEIGHTS set 시) — Theorem 자리 대체
            beta_features = _beta_obs_features(obs, x, V_p)
            beta_mode_idx = _beta_inference(beta_features)
            rho_sum = rhos["corner"] + rhos["yoyo"] + rhos["ldt"] + rhos["pn"]
            if beta_mode_idx >= 0:
                beta_mode = _BETA_MODES[beta_mode_idx]
                u_star, info = optimal_control(x, _BETA_MODE_TAU[beta_mode], alt_ft=alt_ft)
                info["mode"] = f"hybrid:β:{beta_mode}"
                info["branch_reason"] = branch_info["reason"]
                info["beta_mode_idx"] = beta_mode_idx
            elif rho_sum > 0.1:
                u_star, info = optimal_control(x, rhos, alt_ft=alt_ft)
                info["mode"] = "hybrid:Theorem"
                info["branch_reason"] = branch_info["reason"]
            else:
                # 정리 부족 — LUT fallback
                u_star, info = _optimal_control_lut(x, alt_ft)
                info["mode"] = "hybrid:LUT"
                info["branch_reason"] = branch_info["reason"]
    elif not _mpc_succeeded and policy_mode == "lut":
        u_star, info = _optimal_control_lut(x, alt_ft)
        info["mode"] = "lut"
    elif not _mpc_succeeded and policy_mode == "blend":
        u_lut, info_lut = _optimal_control_lut(x, alt_ft)
        u_vadv, info_vadv = optimal_control(x, rhos, alt_ft=alt_ft)
        u_star = 0.5 * u_lut + 0.5 * u_vadv
        info = {**info_vadv, "mode": "blend", "V_lut": info_lut["V_lut"], "u_lut": u_lut, "u_vadv": u_vadv}
    elif not _mpc_succeeded:
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

    # ─ M1.1 진단 컬럼 (SUPERPLAN_v2 §3 Phase 1) — read-only logging, 정책 변경 0 ─
    # 각 ∇V_i 의 spatial gradient (axes 0:3 = Δx, Δy, Δh) 를 LOS-radial vs LOS-tangential 분해.
    # H1 lemma 의 *경험적 신호*: aggressive 매치에서 (dist 방향 / heading 방향) 비율 분포.
    dx0, dy0, dh0 = float(x[0]), float(x[1]), float(x[2])
    dist_xyz = math.sqrt(dx0 * dx0 + dy0 * dy0 + dh0 * dh0) + 1e-9
    r_hat = (dx0 / dist_xyz, dy0 / dist_xyz, dh0 / dist_xyz)

    def _proj_dh(g6) -> Tuple[float, float]:
        if g6 is None:
            return 0.0, 0.0
        try:
            g = _np.asarray(g6).ravel()
            gx, gy, gh = float(g[0]), float(g[1]), float(g[2])
            g_norm = math.sqrt(gx * gx + gy * gy + gh * gh)
            d_proj = gx * r_hat[0] + gy * r_hat[1] + gh * r_hat[2]
            h_proj = max(0.0, g_norm - abs(d_proj))
            return d_proj, h_proj
        except Exception:
            return 0.0, 0.0

    gPN_d, gPN_h = _proj_dh(info.get("grad_pn"))
    gC_d, gC_h = _proj_dh(info.get("grad_corner"))
    gLDT_d, gLDT_h = _proj_dh(info.get("grad_ldt"))
    gYoyo_d, gYoyo_h = _proj_dh(info.get("grad_yoyo"))
    gT_d, gT_h = _proj_dh(info.get("grad_T"))

    closure_kts = float(obs.get("closure_rate_kts", 0.0))
    V_e_raw = V_p - closure_kts                                # pre-clamp 추정
    V_e_clamp_active = 1 if (V_e_raw < 160.0 or V_e_raw > 480.0) else 0

    # B'-0 (2026-05-16, Model B' running cost) — WEZ damage rate D(x).
    # PLAN §0.8: D(x) = 25 · w_ATA · w_dist. logging only (정책 변경 0).
    ata_us_deg = math.degrees(math.atan2(abs(dx0), dy0)) if dy0 > 0 else 90.0
    aa_deg_obs = abs(_np.asarray(obs.get("aa_deg", 0.0)).item() if hasattr(obs.get("aa_deg", 0.0), 'item') else float(obs.get("aa_deg", 0.0)))
    aa_deg_obs = aa_deg_obs * 180.0 if aa_deg_obs <= 1.5 else aa_deg_obs   # denormalize
    ata_them_deg = abs(180.0 - aa_deg_obs)   # 적의 nose↔우리 각 ≈ π - AA
    dist_ft = dist_xyz
    D_us_hps = wez_mod.damage_rate(ata_us_deg, dist_ft, closure_kts=max(closure_kts, 0.01))
    D_them_hps = wez_mod.damage_rate(ata_them_deg, dist_ft, closure_kts=max(-closure_kts, 0.01))
    D_diff_hps = D_us_hps - D_them_hps

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
        "gPN_dist": gPN_d, "gPN_head": gPN_h,
        "gC_dist": gC_d,   "gC_head": gC_h,
        "gLDT_dist": gLDT_d, "gLDT_head": gLDT_h,
        "gYoyo_dist": gYoyo_d, "gYoyo_head": gYoyo_h,
        "gT_dist": gT_d, "gT_head": gT_h,
        "V_e_raw": V_e_raw, "V_e_clamp": V_e_clamp_active,
        "closure_kts": closure_kts,
        # B'-0 Model B' running cost (PLAN §0.8 / §11.7)
        "D_us_hps": D_us_hps, "D_them_hps": D_them_hps, "D_diff_hps": D_diff_hps,
        "ata_us_deg_dyn": ata_us_deg, "ata_them_deg_dyn": ata_them_deg,
        # MPC-specific fields (Phase 1) — None if not mpc mode
        "branch_reason": info.get("branch_reason"),
        "tau_0": info.get("tau_0"),
        "mpc_elapsed_ms": info.get("mpc_elapsed_ms"),
        "mpc_cost_min": info.get("mpc_cost_min"),
    }
    return (alt_bin, hdg_bin, vel_bin), diag


# ═══════════════════════════════════════════════════════════════════
# β — Learned Dispatch Policy (small NN inference, numpy only)
# ═══════════════════════════════════════════════════════════════════

# Env var BETA_NN_WEIGHTS=path/to/weights.npz 설정 시 활성.
# Theorem 분기 자리에서 NN 이 6 modes (pn, corner, yoyo, ldt, T, ipa) 중 argmax 선택.
# 학습은 별도 script (scripts/train_dispatch_cmaes.py).

_BETA_NN_PATH = os.environ.get("BETA_NN_WEIGHTS", "")
_BETA_NN_WEIGHTS = None
_BETA_MODES = ["pn", "corner", "yoyo", "ldt", "T", "ipa"]
_BETA_MODE_TAU = {
    "pn":     {"pn": 1.0},
    "corner": {"corner": 1.0},
    "yoyo":   {"yoyo": 1.0},
    "ldt":    {"ldt": 1.0},
    "T":      {"T": 1.0},
    "ipa":    {"corner": 1.0},   # InitialPhaseAccel mode
}


def _load_beta_weights():
    global _BETA_NN_WEIGHTS
    if not _BETA_NN_PATH or _BETA_NN_WEIGHTS is not None:
        return _BETA_NN_WEIGHTS
    try:
        data = _np.load(_BETA_NN_PATH)
        _BETA_NN_WEIGHTS = {k: data[k] for k in data.files}
        return _BETA_NN_WEIGHTS
    except Exception as e:
        print(f"[β] weights load failed ({_BETA_NN_PATH}): {e}")
        _BETA_NN_WEIGHTS = {}   # 빈 dict — 더 시도 안 함
        return _BETA_NN_WEIGHTS


def _beta_obs_features(obs: dict, x: _np.ndarray, V_p: float) -> _np.ndarray:
    """13-feature normalized obs for NN."""
    ata = float(obs.get("ata_deg", 0.0));  ata = ata * 180.0 if abs(ata) <= 1.5 else ata
    aa = float(obs.get("aa_deg", 0.0));    aa = aa * 180.0 if abs(aa) <= 1.5 else aa
    hca = float(obs.get("hca_deg", 0.0));  hca = hca * 180.0 if abs(hca) <= 1.5 else hca
    dist = float(obs.get("distance_ft", 0.0))
    closure = float(obs.get("closure_rate_kts", 0.0))
    alt_gap = float(obs.get("alt_gap_ft", 0.0))
    return _np.array([
        ata / 180.0, aa / 180.0, hca / 180.0,
        dist / 10000.0, closure / 200.0, alt_gap / 5000.0,
        V_p / 500.0,
        float(x[3]) / math.pi,                # dpsi
        float(x[0]) / 10000.0, float(x[1]) / 10000.0, float(x[2]) / 5000.0,  # dx, dy, dh
        float(obs.get("ps_fts", 0.0)) / 1000.0,
        1.0 if obs.get("energy_advantage", False) else 0.0,
    ], dtype=_np.float64)


def _beta_inference(features: _np.ndarray) -> int:
    """numpy MLP inference (W1, b1, W2, b2). Returns mode index argmax."""
    w = _load_beta_weights()
    if not w or "W1" not in w:
        return -1   # 비활성
    h = _np.tanh(features @ w["W1"] + w["b1"])
    logits = h @ w["W2"] + w["b2"]
    return int(_np.argmax(logits))


# ═══════════════════════════════════════════════════════════════════
# α — Anticipatory Rollout (DSBT §3.3 trajectory-space scoring)
# ═══════════════════════════════════════════════════════════════════

# Candidate primitives — 단일 mode 활성 one-hot τ
_ANTICIPATORY_CANDIDATES = [
    ("pn",     {"pn": 1.0}),
    ("corner", {"corner": 1.0}),
    ("yoyo",   {"yoyo": 1.0}),
    ("ldt",    {"ldt": 1.0}),
    ("T",      {"T": 1.0}),
]

# Rollout 파라미터 — DSBT §7.2 권장 (H ∈ [2,3]s @ 10Hz BT)
_ROLLOUT_HORIZON = 10        # 1.0s lookahead
_ROLLOUT_DT = 0.1            # 100ms per step (BT tick)
_ROLLOUT_MARGIN = 0.02       # baseline 대비 우위 마진 threshold (작음 → anticipatory 자주 채택)


def _instant_reward(x_state: _np.ndarray) -> float:
    """WEZ payoff differential: w_us(ATA) - w_them(AA).

    w(θ) = max(0, 1 - θ/12°) — WEZ cone 안 일 때 양수 (1 at ATA=0, 0 at ATA≥12°).
    """
    ata = float(dyn_mod.compute_ata_deg(x_state))
    aa = float(dyn_mod.compute_aa_deg(x_state))
    # 거리도 고려 — WEZ 범위 [500, 3000] ft 안
    dx, dy, dh = float(x_state[0]), float(x_state[1]), float(x_state[2])
    dist = (dx * dx + dy * dy + dh * dh) ** 0.5
    w_dist = 1.0 if 500.0 <= dist <= 3000.0 else max(0.0, 1.0 - abs(dist - 1750.0) / 5000.0)
    w_us = max(0.0, 1.0 - ata / 12.0) * w_dist
    w_them = max(0.0, 1.0 - aa / 12.0) * w_dist
    return w_us - w_them


def _enemy_pn_pursue(x_state: _np.ndarray) -> _np.ndarray:
    """적 PN-pursue 모델 (α'' 의 한 branch)."""
    dx, dy, dpsi = float(x_state[0]), float(x_state[1]), float(x_state[3])
    cos_p, sin_p = math.cos(-dpsi), math.sin(-dpsi)
    us_x_in_enemy = -dx * cos_p - (-dy) * sin_p
    us_y_in_enemy = -dx * sin_p + (-dy) * cos_p
    enemy_ata = math.atan2(us_x_in_enemy, us_y_in_enemy)
    omega_e = max(-0.3, min(0.3, -0.5 * enemy_ata))
    return _np.array([omega_e, 0.0, 0.0])


def _enemy_extending(x_state: _np.ndarray) -> _np.ndarray:
    """적 extending — 적이 우리 *반대* 향해 회전 (도주). PN-pursue 의 부호 반전."""
    pn = _enemy_pn_pursue(x_state)
    return _np.array([-pn[0], 0.0, 0.0])


# α''' (2026-05-16, DSBT §7.2 robust): 3 adversary 모델 ensemble.
_ADVERSARY_MODELS = ["passive", "pursue", "extend"]


def _adversary_action(model: str, x_state: _np.ndarray) -> _np.ndarray:
    if model == "pursue":
        return _enemy_pn_pursue(x_state)
    if model == "extend":
        return _enemy_extending(x_state)
    return _np.zeros(3)  # passive


def _rollout_payoff_single(x_init: _np.ndarray, taus: dict, alt_ft: float, adv_model: str,
                            horizon: int = _ROLLOUT_HORIZON, dt: float = _ROLLOUT_DT) -> float:
    x = _np.asarray(x_init, dtype=_np.float64).copy()
    payoff = 0.0
    for _ in range(horizon):
        try:
            u_p, _ = optimal_control(x, taus, alt_ft=alt_ft)
        except Exception:
            return 0.0
        u_e = _adversary_action(adv_model, x)
        try:
            xdot = dyn_mod.dynamics(x, u_p, u_e)
        except Exception:
            return 0.0
        x = x + dt * xdot
        payoff = payoff + dt * _instant_reward(x)
    return float(payoff)


def _rollout_payoff(x_init: _np.ndarray, taus: dict, alt_ft: float, obs_current: dict,
                     horizon: int = _ROLLOUT_HORIZON, dt: float = _ROLLOUT_DT) -> float:
    """α''' — 3 adversary 모델 평균 payoff (robust DSBT, §7.2 (k) Bayesian belief uniform).

    closure 분류 의존 (α'') 제거. 모든 adversary 가정 *동시* 고려.
    aggressive (PN-pursue) + defensive (extend) + 중립 모두에 robust.
    """
    payoffs = [_rollout_payoff_single(x_init, taus, alt_ft, m, horizon, dt)
               for m in _ADVERSARY_MODELS]
    return sum(payoffs) / len(payoffs)


def _theorem_anticipatory(x: _np.ndarray, rhos: dict, alt_ft: float, obs_current: dict):
    """Theorem 분기 anticipatory variant — α'' (closure-aware adversary)."""
    baseline_payoff = _rollout_payoff(x, rhos, alt_ft, obs_current)
    cand_payoffs = {}
    for name, taus in _ANTICIPATORY_CANDIDATES:
        cand_payoffs[name] = _rollout_payoff(x, taus, alt_ft, obs_current)
    best_name = max(cand_payoffs, key=cand_payoffs.get)
    best_payoff = cand_payoffs[best_name]
    if best_payoff > baseline_payoff + _ROLLOUT_MARGIN:
        u_star, info = optimal_control(x, dict(_ANTICIPATORY_CANDIDATES)[best_name], alt_ft=alt_ft)
        info["mode"] = f"hybrid:Theorem:α:{best_name}"
        info["antic_payoffs"] = cand_payoffs
        info["antic_baseline"] = baseline_payoff
    else:
        u_star, info = optimal_control(x, rhos, alt_ft=alt_ft)
        info["mode"] = "hybrid:Theorem"
        info["antic_payoffs"] = cand_payoffs
        info["antic_baseline"] = baseline_payoff
    return u_star, info


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
              "mode,active_intents,"
              # ─ M1.1 진단 컬럼 (∇V_i 의 dist/heading projection + V_e clamp) ─
              "gPN_dist,gPN_head,gC_dist,gC_head,"
              "gLDT_dist,gLDT_head,gYoyo_dist,gYoyo_head,"
              "gT_dist,gT_head,"
              "closure_kts,V_e_raw,V_e_clamp,"
              # B'-0 Model B' running cost
              "D_us_hps,D_them_hps,D_diff_hps,ata_us_dyn,ata_them_dyn\n")
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
        diag.get("mode", "?"),
        active,
        # M1.1 진단 컬럼
        f"{diag.get('gPN_dist', 0.0):.3e}", f"{diag.get('gPN_head', 0.0):.3e}",
        f"{diag.get('gC_dist', 0.0):.3e}",  f"{diag.get('gC_head', 0.0):.3e}",
        f"{diag.get('gLDT_dist', 0.0):.3e}", f"{diag.get('gLDT_head', 0.0):.3e}",
        f"{diag.get('gYoyo_dist', 0.0):.3e}", f"{diag.get('gYoyo_head', 0.0):.3e}",
        f"{diag.get('gT_dist', 0.0):.3e}", f"{diag.get('gT_head', 0.0):.3e}",
        f"{diag.get('closure_kts', 0.0):.2f}",
        f"{diag.get('V_e_raw', 0.0):.2f}",
        int(diag.get("V_e_clamp", 0)),
        # B'-0 Model B' running cost
        f"{diag.get('D_us_hps', 0.0):.4f}",
        f"{diag.get('D_them_hps', 0.0):.4f}",
        f"{diag.get('D_diff_hps', 0.0):.4f}",
        f"{diag.get('ata_us_deg_dyn', 0.0):.2f}",
        f"{diag.get('ata_them_deg_dyn', 0.0):.2f}",
    ]
    f.write(",".join(str(v) for v in row) + "\n")
    f.flush()
    _CSV_TICK += 1
