"""PursuitChaseOptimal — HJI lookup 기반 최적 추격 액션.

수학적 기초:
  HJI 수치해로 산출된 value function V*(x) 의 gradient ∇V*(x) 와
  control-affine dynamics 의 disturbance_jacobian B_d(x) 를 결합해
  u_p* = argmin_p [(B_d^T ∇V)·p] s.t. p ∈ box(constraints)
  ⟹ box-corner 해 u_p,i* = -sign((B_d^T ∇V)_i) · u_i,max

상태 추출 (28-feature obs → 6D state):
  dx_rel  = dist · sin(relative_bearing_rad)        — 적 우측 위치
  dy_rel  = dist · cos(relative_bearing_rad)        — 적 전방 위치
  dh      = alt_gap_ft                              — 고도 차
  dpsi    = (hca_deg) · π/180                       — 상대 heading
  V_p     = ego_vc_kts                              — 우리 속도
  V_e     ≈ V_p + adjustment (보수적 동등 가정, 또는 closure 로 추정)

BT 액션 매핑 (u_p* ∈ continuous → 3-tuple discrete bins):
  alt ∈ {0..4}, 2=hold, 4=max climb, 0=max descend
  hdg ∈ {0..8}, 4=straight, 0=hard left, 8=hard right
  vel ∈ {0..4}, 2=hold, 4=max accel, 0=max decel
"""

import logging
import os
from pathlib import Path

import numpy as np
import py_trees

# τ-blended 연속 정책 (R3) — PLAN §2.3-2.4 의 합성
# BT 노드 loader 가 패키지 컨텍스트 없이 individual file 로 import 하므로 명시 경로 로드
import importlib.util as _ilu
_cont_path = Path(__file__).parent / "continuous_policy.py"
_spec = _ilu.spec_from_file_location("_pursuit_continuous", _cont_path)
_cont_mod = _ilu.module_from_spec(_spec)
_spec.loader.exec_module(_cont_mod)
compute_action = _cont_mod.compute_action
log_tick = _cont_mod.log_tick
all_taus = _cont_mod.all_taus

logger = logging.getLogger(__name__)

# ─── Intent decision 로깅 (S3) ─────────────────────────────────
INTENT_CSV_PATH = os.environ.get("PURSUIT_INTENT_LOG", "")
_INTENT_FILE = None
_INTENT_TICK = 0


def _intent_log_open(intent_names):
    global _INTENT_FILE, _INTENT_TICK
    if not INTENT_CSV_PATH:
        return None
    if _INTENT_FILE is None:
        path = Path(INTENT_CSV_PATH)
        path.parent.mkdir(parents=True, exist_ok=True)
        _INTENT_FILE = open(path, "w", encoding="utf-8")
        # header: tick, chosen, phase, alt, hdg, vel, plus per-intent phi/rho/conditions
        cols = ["tick", "chosen", "phase", "alt", "hdg", "vel",
                "ata", "closure", "alt_gap", "v_us", "pitch", "rb"]
        for name in intent_names:
            cols += [f"{name}_phi", f"{name}_rho",
                     f"{name}_c1", f"{name}_c2", f"{name}_c3", f"{name}_c4"]
        _INTENT_FILE.write(",".join(cols) + "\n")
        _INTENT_TICK = 0
    return _INTENT_FILE


def _intent_log(obs_phys, chosen_name, phase, alt, hdg, vel, all_diags, intent_names):
    global _INTENT_TICK
    f = _intent_log_open(intent_names)
    if f is None:
        return
    row = [_INTENT_TICK, chosen_name, phase, alt, hdg, vel,
           round(obs_phys["ata"], 1), round(obs_phys["closure"], 1),
           round(obs_phys["alt_gap"], 0), round(obs_phys["v_us"], 1),
           round(obs_phys["pitch"], 1), round(obs_phys["rb"], 1)]
    for name in intent_names:
        d = all_diags.get(name, {})
        row.append(int(d.get("phi", False)))
        row.append(round(d.get("rho", 0.0), 4))
        conds = d.get("cond", [])
        for i in range(4):
            if i < len(conds):
                row.append(int(conds[i][2]))
            else:
                row.append("")
    f.write(",".join(str(v) for v in row) + "\n")
    f.flush()
    _INTENT_TICK += 1

# ─── Level 1 진단 로깅 ─────────────────────────────────────────
# 환경변수 PURSUIT_DIAG_CSV 가 설정되면 per-tick CSV 로그를 남긴다.
#   PURSUIT_DIAG_CSV=logs/diag/pursuit_diag.csv python scripts/run_match.py ...
DIAG_CSV_PATH = os.environ.get("PURSUIT_DIAG_CSV", "")
_DIAG_FILE = None
_DIAG_TICK = 0


def _diag_open():
    global _DIAG_FILE, _DIAG_TICK
    if not DIAG_CSV_PATH:
        return None
    if _DIAG_FILE is None:
        path = Path(DIAG_CSV_PATH)
        path.parent.mkdir(parents=True, exist_ok=True)
        _DIAG_FILE = open(path, "w", encoding="utf-8")
        _DIAG_FILE.write(
            "tick,dx,dy,dh,dpsi,Vp,Ve,V,gV0,gV1,gV2,gV3,gV4,gV5,"
            "BtG_w,BtG_g,BtG_a,u_w,u_g,u_a,alt,hdg,vel,clamped_w,clamped_g,clamped_a\n"
        )
        _DIAG_TICK = 0
    return _DIAG_FILE


def _diag_log(x, V, grad, BtG, u_star_raw, u_star, alt, hdg, vel):
    global _DIAG_TICK
    f = _diag_open()
    if f is None:
        return
    # clamped flags: raw 가 비제로였는데 quantize 로 0 으로 만든 경우
    clamped = [int(abs(u_star_raw[i]) > 1e-9 and abs(u_star[i]) < 1e-9) for i in range(3)]
    row = [_DIAG_TICK, x[0], x[1], x[2], x[3], x[4], x[5], V,
           grad[0], grad[1], grad[2], grad[3], grad[4], grad[5],
           BtG[0], BtG[1], BtG[2],
           u_star[0], u_star[1], u_star[2],
           alt, hdg, vel,
           clamped[0], clamped[1], clamped[2]]
    f.write(",".join(f"{v:.6g}" if isinstance(v, float) else str(v) for v in row) + "\n")
    f.flush()
    _DIAG_TICK += 1


# ─── BaseAction ─────────────────────────────────────────────────

class BaseAction(py_trees.behaviour.Behaviour):
    def __init__(self, name: str):
        super().__init__(name)
        self.blackboard = self.attach_blackboard_client()
        self.blackboard.register_key(key="observation", access=py_trees.common.Access.READ)
        self.blackboard.register_key(key="action", access=py_trees.common.Access.WRITE)

    def set_action(self, alt: int, hdg: int, vel: int):
        self.blackboard.action = [alt, hdg, vel]

    def _obs(self):
        return self.blackboard.observation


# ─── F-16 envelope (HJI dynamics 와 일치) ──────────────────────

KTS_TO_FPS = 1.6878098571012
OMEGA_MAX_DEG = 19.16
OMEGA_MAX_RAD = OMEGA_MAX_DEG * np.pi / 180.0
GAMMA_MAX_RAD = np.pi * 30.0 / 180.0
ACCEL_MAX_KTS = 15.0


# ─── PursuitChaseOptimal ────────────────────────────────────────

class PursuitChaseOptimal(BaseAction):
    """HJI value lookup 기반 최적 추격 / 회피.

    Params:
        value_table_path: 6D V*(x) lookup .npz 파일 경로
          (생성: python tools/basis/hji_solve_6d.py --save ...)
        action_quantize_thresh: 명령 임계 (이하면 'hold'); 0.1 ~ 0.4 권장
    """
    TUNABLE_PARAMS = {
        "action_quantize_thresh": {"type": "cont", "range": (0.05, 0.4), "default": 0.15},
    }

    def __init__(self, name="PursuitChaseOptimal",
                 value_table_path: str = "logs/hji/V6d_sphere_12bin.npz",
                 action_quantize_thresh: float = 0.15):
        super().__init__(name)
        self.value_table_path = value_table_path
        self.action_quantize_thresh = float(action_quantize_thresh)

        # Lookup table — R3 정책에선 미사용 (PN baseline 이 cover). LUT 는 R5 G2_d
        # 가 SMT counter-example 발견 시에만 활성 (R7 7D 재솔브 후). 현재 dead path.
        self._V = None
        self._coords = None
        self._spacings = None

        # obs_prev (시간차분용 — τ 함수의 HCA rate, LOS rate 계산)
        self._obs_prev = None

    def setup(self, **kwargs):
        # 명시적 setup 단계가 있다면 미리 로드
        if self._V is None:
            self._load_value_table()
        # per-match 상태 명시 초기화 (히스테리시스용 prev_branch 등 — update() 의
        # hasattr 가드 대신 setup 에서 명시. 매치 간 깨끗한 상태 보장.)
        self._prev_branch = ""
        self._obs_history = []
        return True

    def _load_value_table(self):
        """value_table_path 에서 .npz lookup 로드."""
        path = Path(self.value_table_path)
        if not path.is_absolute():
            # PROJECT_ROOT 기준 상대 경로
            here = Path(__file__).resolve()
            # examples/pursuit_chase_v1/nodes/custom_actions.py → project_root
            project_root = here.parent.parent.parent.parent
            path = project_root / path

        if not path.exists():
            logger.warning(f"[PursuitChaseOptimal] value table 없음: {path}")
            self._V = None
            return

        data = np.load(path)
        self._V = np.asarray(data["V"])
        self._coords = tuple(np.asarray(data[f"coord_{i}"]) for i in range(6))
        self._spacings = tuple(float(c[1] - c[0]) if len(c) > 1 else 1.0
                               for c in self._coords)
        logger.info(f"[PursuitChaseOptimal] loaded V table {self._V.shape} from {path}")

    # ─── obs → state 변환 ──────────────────────────────────────

    def _obs_to_state(self, obs) -> np.ndarray:
        """28-feature obs → 6D HJI state (dx, dy, dh, dpsi, V_p, V_e).

        좌표계 정의 (HJI dynamics_f16_6d_hj.py 와 일치):
          dx > 0  → 적이 우리 우측 (+x_body)
          dy > 0  → 적이 우리 전방 (+y_body, nose direction)
          dh > 0  → 적이 우리 위
          dpsi    → 적 heading - 우리 heading (rad)

        Sim convention (RT-1.3 hdg stub 실측으로 확정):
          - relative_bearing_deg: RIGHT positive, LEFT negative (README + side_flag 일치)
          - canonical: 적이 우리 좌측, sim 값 rb=-90° (side_flag=-1)
          → dx = +dist * sin(rb_rad)  (rb>0 우측 → dx>0 우측, dynamics convention 일치)
        """
        # 거리 / 방위
        rb_raw = obs.get("relative_bearing_deg", 0.0)
        # 정규화 [-1, 1] 형식이면 × 180. 이미 도 단위면 그대로.
        if abs(rb_raw) <= 1.5:
            rb_deg = rb_raw * 180.0
        else:
            rb_deg = rb_raw
        dist = float(obs.get("distance_ft", 0.0))
        rb_rad = rb_deg * np.pi / 180.0
        # 좌표계 정합 (sim rb>0=우측 [RT-1.3 실측] → HJI body frame 우측 +)
        dx = +dist * np.sin(rb_rad)  # rb=+90 (적 우측) → dx=+dist (HJI 우측)
        dy = +dist * np.cos(rb_rad)  # rb=0 (전방) → dy=+dist

        dh = float(obs.get("alt_gap_ft", 0.0))

        hca_raw = obs.get("hca_deg", 0.0)
        if abs(hca_raw) <= 1.5:
            hca_deg = hca_raw * 180.0
        else:
            hca_deg = hca_raw
        # HCA 는 두 heading 벡터 사이 각도 (0~180°). 부호는 모호.
        # 일관성 위해 양수 유지. HJI dynamics 가 cos(dpsi) 만 사용하므로 부호 영향 작음.
        dpsi = hca_deg * np.pi / 180.0

        V_p = float(obs.get("ego_vc_kts", 386.8))
        # V_e 추정: 동등 스펙 가정 (1차 근사)
        V_e = V_p

        return np.array([dx, dy, dh, dpsi, V_p, V_e], dtype=np.float64)

    # ─── V*(x) lookup + gradient (central differences) ────────

    def _grad_V_nearest(self, x: np.ndarray) -> tuple[float, np.ndarray]:
        """Nearest-neighbor V 와 6D central-difference gradient 반환.

        Returns:
            (V, grad_V) where grad_V shape (6,)
        """
        if self._V is None:
            return 0.0, np.zeros(6)

        # 각 차원에서 가장 가까운 grid index
        idx = []
        for d in range(6):
            c = self._coords[d]
            i = int(np.argmin(np.abs(c - x[d])))
            idx.append(i)
        idx = tuple(idx)

        V_val = float(self._V[idx])

        # central difference gradient
        grad = np.zeros(6)
        for d in range(6):
            n_d = self._V.shape[d]
            i_plus = list(idx); i_minus = list(idx)
            if idx[d] + 1 < n_d:
                i_plus[d] = idx[d] + 1
                V_plus = float(self._V[tuple(i_plus)])
            else:
                V_plus = V_val
            if idx[d] - 1 >= 0:
                i_minus[d] = idx[d] - 1
                V_minus = float(self._V[tuple(i_minus)])
            else:
                V_minus = V_val
            dx_step = max(self._spacings[d], 1e-6)
            grad[d] = (V_plus - V_minus) / (2.0 * dx_step)

        return V_val, grad

    # ─── B_d(x): pursuer (우리) 제어 jacobian ─────────────────

    @staticmethod
    def _disturbance_jacobian(x: np.ndarray) -> np.ndarray:
        """B_d(x) — 6x3 matrix. u_p = (omega_p, gamma_p, a_p)."""
        dx, dy, _, _, V_p, _ = x
        Vp_fts = V_p * KTS_TO_FPS
        return np.array([
            [ dy,    0.0,    0.0],    # dx
            [-dx,    0.0,    0.0],    # dy
            [0.0,   -Vp_fts, 0.0],    # dh
            [-1.0,   0.0,    0.0],    # dpsi
            [0.0,    0.0,    1.0],    # V_p
            [0.0,    0.0,    0.0],    # V_e
        ])

    # ─── 최적 제어 u_p* ────────────────────────────────────────

    def _optimal_control(self, x: np.ndarray) -> tuple[np.ndarray, dict]:
        """u_p* = argmin_p [(B_d^T ∇V) · p] s.t. p ∈ box.

        box-corner 해:  u_p,i* = -sign((B_d^T ∇V)_i) · upper_bound_i
        """
        V, grad = self._grad_V_nearest(x)
        B_d = self._disturbance_jacobian(x)
        # (B_d^T @ grad) shape (3,)
        BtG = B_d.T @ grad

        # control_space = [omega_max, gamma_max, accel_max]
        bounds = np.array([OMEGA_MAX_RAD, GAMMA_MAX_RAD, ACCEL_MAX_KTS])

        # Box corner — minimize (BtG · p) → if BtG_i > 0, p_i = -bound (min effect)
        u_star_raw = np.where(BtG > 0, -bounds, +bounds).astype(np.float64)
        u_star = u_star_raw.copy()

        # Quantize threshold (F1 수정): channel-별 BtG·bound 의 절대 크기를
        # 모든 채널의 |BtG·bound| 합으로 정규화. 단위-자가일관, scale-invariant.
        # |BtG_i|·bound_i = (i-채널 제어가 V 에 미치는 1-step 최대 영향)
        chan_strength = np.abs(BtG) * bounds  # shape (3,)
        total = chan_strength.sum()
        norm_grads = chan_strength / (total + 1e-9)
        for i in range(3):
            if norm_grads[i] < self.action_quantize_thresh:
                u_star[i] = 0.0  # hold

        info = {"V": V, "grad": grad, "BtG": BtG,
                "u_star": u_star, "u_star_raw": u_star_raw,
                "norm_grads": norm_grads}
        return u_star, info

    # ─── u* → BT 명령 ──────────────────────────────────────────

    @staticmethod
    def _u_to_bt_action(u_star: np.ndarray) -> tuple[int, int, int]:
        """(omega, gamma, accel) → (alt, hdg, vel) discrete bins.

        Convention:
          - hdg: 0=hard left, 4=straight, 8=hard right (9 bins, center 4)
          - alt: 0=max descend, 2=hold, 4=max climb (5 bins)
          - vel: 0=max decel, 2=hold, 4=max accel (5 bins)

        u_star convention:
          - u_star[0] = omega: 양수 → 우선회 → hdg > 4
          - u_star[1] = gamma: 양수 → 상승 → alt > 2
          - u_star[2] = accel: 양수 → 가속 → vel > 2
        """
        omega, gamma, accel = u_star

        # hdg
        if abs(omega) < 1e-3:
            hdg_bin = 4
        else:
            hdg_bin = 4 + round(omega / OMEGA_MAX_RAD * 4)
            hdg_bin = int(max(0, min(8, hdg_bin)))

        # alt
        if abs(gamma) < 1e-3:
            alt_bin = 2
        else:
            alt_bin = 2 + round(gamma / GAMMA_MAX_RAD * 2)
            alt_bin = int(max(0, min(4, alt_bin)))

        # vel
        if abs(accel) < 1e-3:
            vel_bin = 2
        else:
            vel_bin = 2 + round(accel / ACCEL_MAX_KTS * 2)
            vel_bin = int(max(0, min(4, vel_bin)))

        return alt_bin, hdg_bin, vel_bin

    # ─── HJI fallback (정리 영역 밖일 때만) ───────────────────

    def _hji_fallback_action(self, obs) -> tuple[int, int, int, dict]:
        """모든 intent Φ_i=False 시 LUT 기반 명령. Level 1 진단된 chattering 한계 있음."""
        if self._V is None:
            # bearing 기반 단순 추격 fallback
            rb_raw = obs.get("relative_bearing_deg", 0.0)
            rb_deg = rb_raw * 180.0 if abs(rb_raw) <= 1.5 else rb_raw
            hdg_bin = max(0, min(8, int(round(rb_deg / 22.5)) + 4))
            return 2, hdg_bin, 3, {"phase": "rb_fallback"}

        x = self._obs_to_state(obs)
        u_star, info = self._optimal_control(x)
        alt, hdg, vel = self._u_to_bt_action(u_star)
        # Level 1 진단 CSV (옵션) 는 별도 path 로 유지
        _diag_log(x, info["V"], info["grad"], info["BtG"],
                  info["u_star_raw"], info["u_star"], alt, hdg, vel)
        return alt, hdg, vel, {"phase": "hji_lut", "V": float(info["V"])}

    # ─── update — BT tick callback (R3 τ-blended 연속 정책) ─────

    HISTORY_LEN = 5   # τ_corner / τ_LDT 의 다-tick window 길이

    def update(self):
        obs = self._obs()
        if obs is None:
            self.set_action(2, 4, 3)
            return py_trees.common.Status.SUCCESS

        try:
            # ─── obs_history 보유 (rolling buffer, 최신 last) ───
            if not hasattr(self, "_obs_history"):
                self._obs_history = []
            self._obs_history.append(obs)
            if len(self._obs_history) > self.HISTORY_LEN:
                self._obs_history = self._obs_history[-self.HISTORY_LEN:]

            obs_prev = self._obs_history[-2] if len(self._obs_history) >= 2 else None
            history_for_taus = self._obs_history if len(self._obs_history) >= 3 else None

            # ─── 단일 tick — τ-blended 연속 정책 ───
            # prev_branch — EnergyRecovery 히스테리시스용 (per-match node state)
            if not hasattr(self, "_prev_branch"):
                self._prev_branch = ""
            alt_ft = float(obs.get("ego_altitude_ft", 15000.0))
            (alt, hdg, vel), diag = compute_action(
                obs, obs_prev=obs_prev, alt_ft=alt_ft,
                obs_history=history_for_taus,
                prev_branch=self._prev_branch,
            )
            # diag["mode"] = "hybrid:<branch>" → 다음 tick 히스테리시스용 저장
            self._prev_branch = str(diag.get("mode", "")).split(":")[-1]

            # ─── Hard deck safety override ───
            ego_alt = alt_ft
            if ego_alt < 2000 and alt < 2:
                alt = 3   # 강제 상승

            # ─── CSV 로깅 (PURSUIT_CONT_LOG 환경변수) ───
            tau_result = all_taus(obs, obs_prev, alt_ft=alt_ft,
                                   obs_history=history_for_taus)
            log_tick(diag, tau_result)

            self.set_action(alt, hdg, vel)
        except Exception as e:
            logger.warning(f"[PursuitChaseOptimal] update error: {e}")
            self.set_action(2, 4, 3)

        return py_trees.common.Status.SUCCESS
