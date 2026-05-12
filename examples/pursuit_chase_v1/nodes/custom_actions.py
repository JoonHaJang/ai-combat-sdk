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
from pathlib import Path

import numpy as np
import py_trees

logger = logging.getLogger(__name__)


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

        # Lookup table lazy-load (첫 update 시 1회만)
        self._V = None
        self._coords = None  # tuple of 6 axis coordinates
        self._spacings = None  # bin width per dim

    def setup(self, **kwargs):
        # 명시적 setup 단계가 있다면 미리 로드
        if self._V is None:
            self._load_value_table()
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

        Sim CSV convention (canonical 검증으로 도출):
          - relative_bearing_deg: LEFT positive, RIGHT negative (math CCW convention)
          - canonical (적이 우리 우측): sim 값 -90°
          → dx 계산 시 부호 flip 필요: dx = -dist * sin(rb_rad)
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
        # 좌표계 정합 (CCW 양수 → HJI body frame: 우측 +): 부호 flip on x
        dx = -dist * np.sin(rb_rad)  # rb=-90 (sim 우측) → dx=+dist (HJI 우측)
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
        u_star = np.where(BtG > 0, -bounds, +bounds)

        # Quantize threshold: |BtG_i| / |bound_i| 가 작으면 명령 hold
        # 정규화된 gradient 크기로 비교
        for i in range(3):
            if bounds[i] > 0:
                normalized_grad = abs(BtG[i]) * bounds[i] / (abs(V) + 100.0)
                if normalized_grad < self.action_quantize_thresh:
                    u_star[i] = 0.0  # hold

        info = {"V": V, "grad": grad, "BtG": BtG, "u_star": u_star}
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

    # ─── update — BT tick callback ────────────────────────────

    def update(self):
        # Lazy-load value table
        if self._V is None:
            self._load_value_table()

        obs = self._obs()

        # HJI value table 없으면 fallback (basic pursuit)
        if self._V is None or obs is None:
            # bearing 기반 단순 추격 fallback
            rb_raw = (obs or {}).get("relative_bearing_deg", 0.0)
            rb_deg = rb_raw * 180.0 if abs(rb_raw) <= 1.5 else rb_raw
            hdg_bin = max(0, min(8, int(round(rb_deg / 22.5)) + 4))
            self.set_action(2, hdg_bin, 3)
            return py_trees.common.Status.SUCCESS

        # 정상 경로: HJI lookup → optimal control
        try:
            x = self._obs_to_state(obs)
            u_star, info = self._optimal_control(x)
            alt, hdg, vel = self._u_to_bt_action(u_star)

            # Safety: hard deck 보호 (alt 매우 낮으면 descent 차단)
            ego_alt = float(obs.get("ego_altitude_ft", 10000))
            if ego_alt < 2000 and alt < 2:
                alt = 3  # 강제 상승

            self.set_action(alt, hdg, vel)
        except Exception as e:
            logger.warning(f"[PursuitChaseOptimal] update error: {e}")
            self.set_action(2, 4, 3)  # safe fallback

        return py_trees.common.Status.SUCCESS
