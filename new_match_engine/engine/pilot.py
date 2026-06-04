"""Pilot — obs → tactic → guidance → autopilot → u 전체 체인 (1 에이전트).

파이프라인 (단위 경계 명시):
  compute_obs(ego, enm)         → Observation  (°/ft/kts, 직접관측)
  suggest_tactic / BT           → Tactic enum
  GuidanceLayer.compute(t, obs) → Setpoint     (°/ft/kts)
  Autopilot.step(sp)            → u [thr,elev,ail,rud]  (단위변환은 autopilot 내부)
  plant.set_input(u); plant.step()

★ 단위/부호 일관성: obs(°/ft/kts) → guidance(°/ft/kts) → autopilot(경계서 fps/rad 변환).
  guidance.Obs.from_observation 이 obs 키→guidance 매핑 (메모리 규약 준수).
"""
from __future__ import annotations
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "control"))

import numpy as np
from plant import F16Plant
from lqr import GainScheduledLQR
from autopilot import Autopilot, AutopilotConfig
from guidance import GuidanceLayer, Obs, suggest_tactic
from tactic import Tactic
from obs import compute_obs, Observation


class Pilot:
    """단일 전투기 AI 파일럿 — 전체 제어 체인."""

    def __init__(self, plant: F16Plant, lqr: GainScheduledLQR,
                 config: AutopilotConfig | None = None, dt: float = 0.1):
        self.plant     = plant
        self.guidance  = GuidanceLayer()
        self.autopilot = Autopilot(plant, lqr, config, dt)
        self.last_obs:     Observation | None = None
        self.last_tactic:  Tactic | None = None
        self.last_setpoint = None

    def step(self, enm_plant: F16Plant, tactic: Tactic | None = None,
             center=(0.0, 0.0, 0.0)) -> np.ndarray:
        """1 BT-tick: 관측 → 전술 → setpoint → u.

        tactic=None → suggest_tactic (rule-based). BT 연결 시 tactic 직접 주입.
        center: NED 기준점 (lat, lon, alt_ft).
        """
        obs = compute_obs(self.plant, enm_plant, *center)
        gobs = Obs.from_observation(obs)

        if tactic is None:
            tactic = suggest_tactic(gobs)

        sp = self.guidance.compute(tactic, obs)
        u  = self.autopilot.step(sp)

        self.last_obs      = obs
        self.last_tactic   = tactic
        self.last_setpoint = sp
        return u


if __name__ == "__main__":
    from obs import FT_PER_DEG_LAT
    from autopilot import FT_S_TO_KNOT, RAD_TO_DEG, _iPSI

    print("▶ Pilot 통합 — ego(피아식별) vs 직진 적기, 전 체인 동작")
    print()

    # 공유 LQR (한 번만 빌드)
    gs = GainScheduledLQR([5000,15000,25000],[250,350,450]).build()

    # ego: 북향, enm: 동쪽 4000ft 에서 동향 직진 (passive)
    ego = F16Plant(); ego.set_ic(15000.0, 350.0, psi_deg=0.0); ego.trim(); ego.step(5)
    enm = F16Plant(); enm.set_ic(15000.0, 350.0, psi_deg=90.0)
    enm["ic/long-gc-deg"] = 4000.0 / FT_PER_DEG_LAT
    enm["ic/psi-true-deg"] = 90.0
    enm.fdm.run_ic(); enm.trim(); enm.step(5)

    pilot = Pilot(ego, gs, AutopilotConfig(KP_PSI=0.08))

    # ★ PURE_PURSUIT 강제 — 적(우측 90°)을 향해 추격하는지 검증.
    #   기대: rel_b → 0 (적 정면), ata → 0 (nose-on), 우선회(u_ail>0).
    FORCED = Tactic.PURE_PURSUIT

    print(f"강제 tactic = {FORCED.name} (적 우측 90°→ 추격 검증)")
    print(f"{'t':>5}  {'ego_psi':>7}  {'rel_b':>6}  {'ata':>6}  "
          f"{'adv':>6}  {'dist':>6}  {'u_ail':>6}")
    print("-" * 60)

    DT_SIM = ego.dt
    N = int(0.1 / DT_SIM)

    for tick in range(200):  # 20s
        u = pilot.step(enm, tactic=FORCED)
        ego.set_input(u)
        for _ in range(N):
            ego.step(1)
        # 적도 직진 비행 (trim 입력 유지)
        for _ in range(N):
            enm.step(1)

        if tick % 20 == 0:
            o = pilot.last_obs
            print(f"{tick*0.1:>5.1f}  "
                  f"{o.ego_psi_deg:>7.1f}  {o.rel_b_deg:>+6.1f}  {o.ata_deg:>6.1f}  "
                  f"{o.advantage:>+6.2f}  {o.distance_ft:>6.0f}  "
                  f"{pilot.autopilot.state.u_aileron:>+6.3f}")

    o = pilot.last_obs
    print()
    print(f"최종: tactic={pilot.last_tactic.name}  ata={o.ata_deg:.1f}°  "
          f"advantage={o.advantage:+.2f}  dist={o.distance_ft:.0f}ft")
    # NaN/inf 체크
    arr = np.array(list(o.as_dict().values()))
    print(f"obs NaN/inf 없음: {bool(np.all(np.isfinite(arr)))}")
