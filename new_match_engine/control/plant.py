"""F-16 plant wrapper — standalone JSBSim (별도 연구 스택).

매치 엔진(.pyd)과 무관. pip `jsbsim` + 로컬 F-16 XML(native FLCS 포함)을 plant로 쓴다.
인용: "runs in JSBSim, ... very accurate for modeling aerodynamics [15][16]".

상태 벡터(제어 설계용 종/횡 표준 12-state 의 부분집합):
    x = [V(fps), alpha(rad), theta(rad), q(rad/s),      # 종(longitudinal)
         beta(rad), phi(rad), p(rad/s), r(rad/s),       # 횡(lateral-directional)
         h(ft), psi(rad)]                               # 항법(guidance)
입력 u = [throttle(0..1), elevator(-1..1), aileron(-1..1), rudder(-1..1)]
    (JSBSim fcs/*-cmd-norm 경유 → native FLCS 안정성증강 적용 후 조종면)
"""
from __future__ import annotations
import os
import numpy as np

try:
    import jsbsim
except ImportError as e:  # pragma: no cover
    raise ImportError("pip install jsbsim  (standalone, 매치 .pyd 와 별개)") from e

# 로컬 JSBSim 데이터 루트 (aircraft/engine/systems 완비, F-16 native FLCS 포함)
DEFAULT_ROOT = os.path.abspath(os.path.join(
    os.path.dirname(__file__),
    "..", "..", "ai-combat-core-main", "ai-combat-core-main",
    "external_repo", "AIP_knowledge_Base", "JSBSim",
))

# 상태/입력 property 매핑 (JSBSim property tree)
STATE_PROPS = {
    "V":     "velocities/vt-fps",        # true airspeed
    "alpha": "aero/alpha-rad",
    "theta": "attitude/theta-rad",
    "q":     "velocities/q-rad_sec",
    "beta":  "aero/beta-rad",
    "phi":   "attitude/phi-rad",
    "p":     "velocities/p-rad_sec",
    "r":     "velocities/r-rad_sec",
    "h":     "position/h-sl-ft",
    "psi":   "attitude/psi-rad",
}
STATE_ORDER = ["V", "alpha", "theta", "q", "beta", "phi", "p", "r", "h", "psi"]

INPUT_PROPS = {
    "throttle": "fcs/throttle-cmd-norm[0]",
    "elevator": "fcs/elevator-cmd-norm",
    "aileron":  "fcs/aileron-cmd-norm",
    "rudder":   "fcs/rudder-cmd-norm",
}
INPUT_ORDER = ["throttle", "elevator", "aileron", "rudder"]


class F16Plant:
    """JSBSim F-16 — 제어 연구용 결정론 plant."""

    def __init__(self, root: str = DEFAULT_ROOT, model: str = "f16", dt: float | None = None):
        self.fdm = jsbsim.FGFDMExec(root)
        self.fdm.set_debug_level(0)
        if not self.fdm.load_model(model):
            raise RuntimeError(f"JSBSim load_model('{model}') 실패 (root={root})")
        if dt is not None:
            self.fdm.set_dt(dt)
        self.root = root

    # --- 초기화 / trim -------------------------------------------------
    def set_ic(self, alt_ft: float, vc_kts: float, gamma_deg: float = 0.0,
               psi_deg: float = 0.0):
        f = self.fdm
        f["ic/h-sl-ft"] = float(alt_ft)
        f["ic/vc-kts"] = float(vc_kts)
        f["ic/gamma-deg"] = float(gamma_deg)
        f["ic/psi-true-deg"] = float(psi_deg)
        f.run_ic()
        self.start_engines()   # ★ 엔진 시동 (미시동 시 thrust=0 → 무동력 활공 버그)
        return self

    def start_engines(self):
        """엔진 시동 — 미시동 시 thrust≈0 (램항력만) → 모든 속도제어 무력화.

        ★ 반드시 호출. run_ic 후 init_running(-1)로 전 엔진 running 상태로.
        검증: 시동 전 thrust=−1383lbs(드래그), 시동 후 +17116lbs.
        """
        try:
            self.fdm.get_propulsion().init_running(-1)   # 전 엔진 시동
        except Exception:
            try:
                self.fdm["propulsion/engine[0]/set-running"] = 1
            except Exception:
                pass
        return self

    def trim(self, mode: int = 1):
        """in-air trim (mode 1). 실패해도 예외 대신 False 반환."""
        try:
            self.fdm["simulation/do_simple_trim"] = mode
            return True
        except Exception:
            return False

    # --- step / 접근 ---------------------------------------------------
    @property
    def dt(self) -> float:
        return self.fdm.get_delta_t()

    def step(self, n: int = 1):
        for _ in range(n):
            self.fdm.run()
        return self

    def get_state(self) -> np.ndarray:
        f = self.fdm
        return np.array([f[STATE_PROPS[k]] for k in STATE_ORDER], dtype=float)

    def get_state_dict(self) -> dict:
        f = self.fdm
        return {k: f[STATE_PROPS[k]] for k in STATE_ORDER}

    def set_input(self, u: np.ndarray):
        f = self.fdm
        for k, val in zip(INPUT_ORDER, u):
            f[INPUT_PROPS[k]] = float(val)
        return self

    def get_input(self) -> np.ndarray:
        f = self.fdm
        return np.array([f[INPUT_PROPS[k]] for k in INPUT_ORDER], dtype=float)

    def __getitem__(self, prop):
        return self.fdm[prop]

    def __setitem__(self, prop, val):
        self.fdm[prop] = val

    # --- state capture / restore (실엔진 rollout 용) --------------------
    #   JSBSim 은 직접 serialize 가 없어 IC 속성으로 12-DOF 상태 복원.
    #   FCS 내부 적분/조종면 위치는 재설정 → <1s transient (선택용 rollout 엔 무해).
    _CAP_PROPS = (
        "position/lat-gc-rad", "position/long-gc-rad", "position/h-sl-ft",
        "velocities/u-fps", "velocities/v-fps", "velocities/w-fps",
        "attitude/phi-rad", "attitude/theta-rad", "attitude/psi-rad",
        "velocities/p-rad_sec", "velocities/q-rad_sec", "velocities/r-rad_sec",
    )
    _CAP_TO_IC = {
        "position/lat-gc-rad":  "ic/lat-gc-rad",
        "position/long-gc-rad": "ic/long-gc-rad",
        "position/h-sl-ft":     "ic/h-sl-ft",
        "velocities/u-fps":     "ic/u-fps",
        "velocities/v-fps":     "ic/v-fps",
        "velocities/w-fps":     "ic/w-fps",
        "attitude/phi-rad":     "ic/phi-rad",
        "attitude/theta-rad":   "ic/theta-rad",
        "attitude/psi-rad":     "ic/psi-true-rad",
        "velocities/p-rad_sec": "ic/p-rad_sec",
        "velocities/q-rad_sec": "ic/q-rad_sec",
        "velocities/r-rad_sec": "ic/r-rad_sec",
    }

    def capture_state(self) -> dict:
        """현재 비행상태 스냅샷 (위치·자세·body속도·rates + 입력). restore_state 로 복원."""
        f = self.fdm
        snap = {p: f[p] for p in self._CAP_PROPS}
        snap["_u"] = self.get_input()
        return snap

    def restore_state(self, snap: dict):
        """capture_state 스냅샷으로 복원 (IC 경유 run_ic). 엔진 재시동·입력 복원."""
        f = self.fdm
        for prop, ic in self._CAP_TO_IC.items():
            f[ic] = snap[prop]
        f.run_ic()
        self.start_engines()
        self.set_input(snap["_u"])
        return self


if __name__ == "__main__":
    # first-light: load / trim / step
    p = F16Plant()
    p.set_ic(alt_ft=15000.0, vc_kts=350.0)
    print("trim:", p.trim())
    p.step(5)
    s = p.get_state_dict()
    print(f"dt={p.dt:.4f}")
    print(f"alt={s['h']:.1f}ft  V={s['V']:.1f}fps  alpha={np.degrees(s['alpha']):.2f}deg  "
          f"theta={np.degrees(s['theta']):.2f}deg")
    print(f"phi={np.degrees(s['phi']):.2f}deg  psi={np.degrees(s['psi']):.2f}deg  "
          f"q={s['q']:.4f} p={s['p']:.4f} r={s['r']:.4f}")
    print("u(trim)=", np.round(p.get_input(), 4))
