"""Match loop — 1v1 결정론 매치 (새 엔진).

루프 (control tick = dt, 기본 0.1s = 10Hz):
  1. obs 계산 (양방향: obs12=plant1공격, obs21=plant2공격)
  2. 각 pilot: tactic 선택 → guidance → autopilot → u
  3. u 적용 + JSBSim step (dt)
  4. WEZ 데미지 (judge.wez_damage, dt) → health 차감
  5. judge 판정 (hard deck → health=0 → timeout)

★ WEZ ATA: 각 공격자 기준 obs.ata_deg 사용 (judge.py 규약).
  plant1→plant2: obs12.ata_deg / plant2→plant1: obs21.ata_deg. distance 동일.

★ 데미지 적분: 원본은 dt=0.2s 체크, 우리는 control dt(0.1s) 체크.
  데미지=dps×dt 적분이라 cadence 무관하게 총량 동일. max_steps=duration/dt.
"""
from __future__ import annotations
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "control"))
from dataclasses import dataclass
from typing import Callable, Optional

import numpy as np
from plant import F16Plant
from lqr import GainScheduledLQR
from autopilot import AutopilotConfig
from tactic import Tactic, MATCH_DURATION_S
from obs import compute_obs, Observation
from pilot import Pilot
from judge import HealthGauge, wez_damage, judge, Victory, JudgeResult

_G = 32.174; _KT = 1.68781
def _spec_e(alt_ft, vc_kts):
    v = vc_kts * _KT
    return alt_ft + v*v/(2*_G)


@dataclass
class MatchResult:
    winner: Optional[str]        # "agent1"/"agent2"/"draw"
    condition: Victory
    steps: int                   # control tick 수
    time_s: float
    health1: float
    health2: float
    damage_dealt1: float
    damage_dealt2: float
    log: list = None             # 로그 행 (log_hz>0 시), None 이면 미수집
    events: list = None          # event log: [(t_s, kind, msg), ...]


# tactic 선택기 타입: (Observation) -> Tactic | None(=suggest_tactic)
TacticFn = Callable[[Observation], Optional[Tactic]]


class Match:
    """1v1 매치 엔진 (multi-rate).

    rate 구조:
      물리   : JSBSim 내부 120Hz (고정, 가장 finest)
      제어   : control_hz (기본 20Hz) — autopilot/guidance/WEZ/judge
      로깅   : log_hz (기본 0=off; 최대 120Hz) — 궤적 분해능

    데미지 적분: WEZ 매 제어틱 dt=1/control_hz. ∫dps·dt 라 cadence 무관 총량동일,
    짧은 WEZ窗 포착은 control_hz 높을수록↑.
    """

    def __init__(self, plant1: F16Plant, plant2: F16Plant,
                 lqr: GainScheduledLQR,
                 cfg1: AutopilotConfig | None = None,
                 cfg2: AutopilotConfig | None = None,
                 control_hz: float = 20.0,
                 bt_hz: float = 10.0,
                 dwell_s: float = 0.3,
                 log_hz: float = 120.0):
        """rate 결정 (전부 분석 기반, 2026-06-02):
          physics 120Hz(plant.dt) · control 20Hz · BT 10Hz · dwell 0.3s · log 120Hz
          정수비 6:2:1. BT>10Hz 는 거동 동일·연산만↑(무이득). dwell 은 1틱 chatter 제거.
        """
        self.p1, self.p2 = plant1, plant2
        self.control_hz = control_hz
        self.bt_hz = bt_hz
        self.dwell_s = dwell_s
        self.log_hz = log_hz
        self.control_dt = 1.0 / control_hz
        self.pilot1 = Pilot(plant1, lqr, cfg1, self.control_dt)  # autopilot PI dt=control_dt
        self.pilot2 = Pilot(plant2, lqr, cfg2, self.control_dt)
        self.h1 = HealthGauge()
        self.h2 = HealthGauge()
        # tactic dwell 상태 (chatter 방지)
        self._t1 = Tactic.LEVEL_FLIGHT; self._t2 = Tactic.LEVEL_FLIGHT
        self._t1_age = 0.0; self._t2_age = 0.0
        # event log 상태 (전환 감지용)
        self._events: list = []
        self._wez1_on = False; self._wez2_on = False   # WEZ 활성 (1→2, 2→1)
        self._hp1_mile = 100; self._hp2_mile = 100      # HP 마일스톤(25 단위)
        self._hd_warn1 = False; self._hd_warn2 = False  # hard deck 경고

    def _emit(self, t: float, kind: str, msg: str):
        self._events.append((t, kind, msg))

    def _dwell_tactic(self, proposed, cur, age):
        """dwell 적용: age < dwell 이면 전환 거부 → (선택된 tactic, 새 age)."""
        if proposed is not None and proposed != cur and age >= self.dwell_s:
            return proposed, 0.0
        return cur, age + self.control_dt

    def _log_row(self, t: float, o12, o21, u1=None, u2=None) -> dict:
        """로그 1행 — 물리값 직접 (분해능 최대). u=[thr,elev,ail,rud]."""
        if u1 is None: u1 = (0.0, 0.0, 0.0, 0.0)
        if u2 is None: u2 = (0.0, 0.0, 0.0, 0.0)
        return {
            "t": t,
            "alt1": self.p1["position/h-sl-ft"], "alt2": self.p2["position/h-sl-ft"],
            "lat1": self.p1["position/lat-gc-deg"], "lon1": self.p1["position/long-gc-deg"],
            "lat2": self.p2["position/lat-gc-deg"], "lon2": self.p2["position/long-gc-deg"],
            "psi1": self.p1["attitude/psi-deg"], "psi2": self.p2["attitude/psi-deg"],
            "phi1": self.p1["attitude/phi-deg"], "phi2": self.p2["attitude/phi-deg"],
            "theta1": self.p1["attitude/theta-deg"], "theta2": self.p2["attitude/theta-deg"],
            "vc1": self.p1["velocities/vc-kts"], "vc2": self.p2["velocities/vc-kts"],
            "H1": self.h1.health, "H2": self.h2.health,
            "dist": o12.distance_ft, "ata12": o12.ata_deg, "ata21": o21.ata_deg,
            "aa12": o12.aa_deg, "aa21": o21.aa_deg,
            "clos12": o12.closure_kts, "relb12": o12.rel_b_deg, "adv12": o12.advantage,
            # 조종면 [thr,elev,ail,rud] (plot RollControlInput= 등)
            "thr1": u1[0], "elev1": u1[1], "ail1": u1[2], "rud1": u1[3],
            "thr2": u2[0], "elev2": u2[1], "ail2": u2[2], "rud2": u2[3],
            # ── plot_match_3d_nme meta 컬럼 (Tactic/advantage/setpoint 패널) ──
            "tac1": self._t1.name, "tac2": self._t2.name,
            "adv": o12.advantage, "ata": o12.ata_deg, "aa": o12.aa_deg,
            "relb": o12.rel_b_deg, "clos": o12.closure_kts,
            "ego_alt": o12.ego_alt_ft, "ego_vc": o12.ego_vc_kts,
            "ego_bank": o12.ego_phi_deg, "enm_bank": o12.enm_phi_deg,
            "ediff": _spec_e(o12.ego_alt_ft, o12.ego_vc_kts)
                     - _spec_e(o12.enm_alt_ft, o12.enm_vc_kts),
            "sp_psi": self.pilot1.last_setpoint.psi_star_deg if self.pilot1.last_setpoint else 0.0,
            "sp_h": self.pilot1.last_setpoint.h_star_ft if self.pilot1.last_setpoint else 0.0,
            "sp_v": self.pilot1.last_setpoint.v_star_kts if self.pilot1.last_setpoint else 0.0,
            "u1_thr": u1[0], "u1_elev": u1[1], "u1_ail": u1[2], "u1_rud": u1[3],
            "u2_thr": u2[0], "u2_elev": u2[1], "u2_ail": u2[2], "u2_rud": u2[3],
        }

    def run(self,
            tactic_fn1: TacticFn | None = None,
            tactic_fn2: TacticFn | None = None,
            duration_s: float = MATCH_DURATION_S,
            verbose: bool = False) -> MatchResult:
        dt_phys   = self.p1.dt                          # 1/120
        cdt       = self.control_dt                     # 1/control_hz
        n_ctrl    = max(1, int(round(cdt / dt_phys)))   # 제어틱당 물리 substep
        bt_every  = max(1, int(round(self.control_hz / self.bt_hz)))  # BT는 control 몇틱마다
        max_ticks = int(round(duration_s / cdt))
        log_every = (max(1, int(round((1.0/self.log_hz) / dt_phys)))
                     if self.log_hz > 0 else 0)          # 물리 substep 단위 로깅 간격
        log = [] if log_every else None

        phys = 0
        for tick in range(1, max_ticks + 1):
            # ── obs (매 제어틱 — 조준점 추적용) ──────────────────────────
            o12 = compute_obs(self.p1, self.p2)   # p1 공격
            o21 = compute_obs(self.p2, self.p1)   # p2 공격

            # ── BT 결정 (bt_every 틱마다) + dwell (chatter 방지) ─────────
            if (tick - 1) % bt_every == 0:
                p1_prop = tactic_fn1(o12) if tactic_fn1 else None
                p2_prop = tactic_fn2(o21) if tactic_fn2 else None
                # tactic_fn=None → pilot 내부 suggest_tactic. dwell 위해 명시화.
                if tactic_fn1 is None:
                    from guidance import Obs as _O, suggest_tactic as _st
                    p1_prop = _st(_O.from_observation(o12))
                if tactic_fn2 is None:
                    from guidance import Obs as _O, suggest_tactic as _st
                    p2_prop = _st(_O.from_observation(o21))
                _prev1, _prev2 = self._t1, self._t2
                self._t1, self._t1_age = self._dwell_tactic(p1_prop, self._t1, self._t1_age)
                self._t2, self._t2_age = self._dwell_tactic(p2_prop, self._t2, self._t2_age)
                tnow = tick * cdt
                if self._t1 != _prev1:
                    self._emit(tnow, "TACTIC1", f"A1 {_prev1.name} → {self._t1.name}")
                if self._t2 != _prev2:
                    self._emit(tnow, "TACTIC2", f"A2 {_prev2.name} → {self._t2.name}")
            else:
                self._t1_age += cdt; self._t2_age += cdt

            # ── 제어 (현 tactic 고정, guidance setpoint 는 매틱 재계산) ──
            u1 = self.pilot1.step(self.p2, tactic=self._t1)
            u2 = self.pilot2.step(self.p1, tactic=self._t2)
            self.p1.set_input(u1); self.p2.set_input(u2)

            # ── WEZ 데미지 (제어틱 dt) — obs 는 step 前 기하 ──────────────
            dmg_to_2 = wez_damage(o12.ata_deg, o12.distance_ft, cdt)
            dmg_to_1 = wez_damage(o21.ata_deg, o21.distance_ft, cdt)
            tnow = tick * cdt
            if dmg_to_2 > 0:
                self.h2.take_damage(dmg_to_2); self.h1.deal_damage(dmg_to_2)
            if dmg_to_1 > 0:
                self.h1.take_damage(dmg_to_1); self.h2.deal_damage(dmg_to_1)
            # ── event: WEZ 진입/이탈 (A1→A2 기준) ─────────────────────────
            if (dmg_to_2 > 0) != self._wez1_on:
                self._wez1_on = dmg_to_2 > 0
                self._emit(tnow, "WEZ1",
                           f"A1 WEZ {'ENTER' if self._wez1_on else 'EXIT '} "
                           f"ata={o12.ata_deg:.0f}° d={o12.distance_ft:.0f}ft")
            if (dmg_to_1 > 0) != self._wez2_on:
                self._wez2_on = dmg_to_1 > 0
                self._emit(tnow, "WEZ2",
                           f"A2 WEZ {'ENTER' if self._wez2_on else 'EXIT '} "
                           f"ata={o21.ata_deg:.0f}° d={o21.distance_ft:.0f}ft")
            # ── event: HP 마일스톤 (25단위) ───────────────────────────────
            while self.h2.health <= self._hp2_mile - 25:
                self._hp2_mile -= 25
                self._emit(tnow, "HP2", f"A2 HP → {self._hp2_mile} (A1 피해 누적 {self.h1.damage_dealt:.0f})")
            while self.h1.health <= self._hp1_mile - 25:
                self._hp1_mile -= 25
                self._emit(tnow, "HP1", f"A1 HP → {self._hp1_mile} (A2 피해 누적 {self.h2.damage_dealt:.0f})")
            # ── event: hard deck 경고 (1500ft 미만) ───────────────────────
            if (self.p1["position/h-sl-ft"] < 1500.0) != self._hd_warn1:
                self._hd_warn1 = not self._hd_warn1
                if self._hd_warn1:
                    self._emit(tnow, "HDECK1", f"A1 HARD DECK 경고 alt={self.p1['position/h-sl-ft']:.0f}ft")
            if (self.p2["position/h-sl-ft"] < 1500.0) != self._hd_warn2:
                self._hd_warn2 = not self._hd_warn2
                if self._hd_warn2:
                    self._emit(tnow, "HDECK2", f"A2 HARD DECK 경고 alt={self.p2['position/h-sl-ft']:.0f}ft")

            # ── 물리 substep (n_ctrl 회) + 고Hz 로깅 ─────────────────────
            for _ in range(n_ctrl):
                self.p1.step(1); self.p2.step(1)
                phys += 1
                if log_every and phys % log_every == 0:
                    log.append(self._log_row(phys * dt_phys, o12, o21, u1, u2))

            # ── judge ────────────────────────────────────────────────────
            alt1 = self.p1["position/h-sl-ft"]; alt2 = self.p2["position/h-sl-ft"]
            res = judge(alt1, alt2, self.h1.health, self.h2.health, tick, max_ticks)

            if verbose and tick % int(self.control_hz) == 0:   # ~1초마다
                print(f"  t={tick*cdt:5.1f}s  H1={self.h1.health:5.1f} H2={self.h2.health:5.1f}  "
                      f"dist={o12.distance_ft:6.0f}ft ata12={o12.ata_deg:5.1f} ata21={o21.ata_deg:5.1f}  "
                      f"alt1={alt1:5.0f} alt2={alt2:5.0f}")

            if res.condition != Victory.NONE:
                self._emit(tick*cdt, "RESULT",
                           f"{res.winner} 승 ({res.condition.value}) "
                           f"H1={self.h1.health:.0f} H2={self.h2.health:.0f}")
                return MatchResult(res.winner, res.condition, tick, tick*cdt,
                                   self.h1.health, self.h2.health,
                                   self.h1.damage_dealt, self.h2.damage_dealt, log, self._events)

        self._emit(max_ticks*cdt, "RESULT",
                   f"draw (timeout) H1={self.h1.health:.0f} H2={self.h2.health:.0f}")
        return MatchResult("draw", Victory.TIMEOUT, max_ticks, max_ticks*cdt,
                           self.h1.health, self.h2.health,
                           self.h1.damage_dealt, self.h2.damage_dealt, log, self._events)


if __name__ == "__main__":
    from obs import FT_PER_DEG_LAT

    print("=" * 64)
    print("  Match 엔진 end-to-end 검증")
    print("=" * 64)

    gs = GainScheduledLQR([5000,15000,25000],[250,350,450]).build()

    # ── 시나리오: p1 이 p2 뒤 800ft (WEZ 내) nose-on, 둘 다 직진 ──────────
    #   기대: p1 이 p2 에 데미지 → p2 HP=0 → p1(agent1) 승.
    print("\n[시나리오 A] p1 이 p2 6시 800ft nose-on, 둘 다 LEVEL_FLIGHT 직진")
    p1 = F16Plant(); p1.set_ic(15000.0, 350.0, psi_deg=0.0); p1.trim(); p1.step(5)
    p2 = F16Plant(); p2.set_ic(15000.0, 350.0, psi_deg=0.0)
    p2["ic/lat-gc-deg"] = 800.0 / FT_PER_DEG_LAT   # p2 가 800ft 북쪽 (p1 앞)
    p2["ic/psi-true-deg"] = 0.0
    p2.fdm.run_ic(); p2.trim(); p2.step(5)

    # 제어 20Hz, 로깅 120Hz (물리 매 substep)
    m = Match(p1, p2, gs, control_hz=20.0, log_hz=120.0)
    lvl = lambda o: Tactic.LEVEL_FLIGHT
    res = m.run(tactic_fn1=lvl, tactic_fn2=lvl, duration_s=30.0, verbose=True)

    print(f"\n  결과: winner={res.winner}  condition={res.condition.value}")
    print(f"        t={res.time_s:.1f}s  H1={res.health1:.1f}  H2={res.health2:.1f}")
    print(f"        p1 데미지누적={res.damage_dealt1:.1f}  p2 데미지누적={res.damage_dealt2:.1f}")
    print(f"        로그 행 수={len(res.log) if res.log else 0}  "
          f"(120Hz × {res.time_s:.1f}s ≈ {int(120*res.time_s)})")

    ok = (res.winner == "agent1" and res.condition == Victory.HEALTH_ZERO)
    print(f"\n  {'✅ PASS' if ok else '❌ FAIL'} — p1 이 WEZ 데미지로 승리 (agent1/health_zero 기대)")

    # ── control_hz 영향 검증: 10Hz vs 20Hz 데미지 적분 총량 동일성 ───────
    print("\n[검증] control_hz 10 vs 20 — 데미지 적분 총량 일관성")
    for hz in (10.0, 20.0, 40.0):
        a = F16Plant(); a.set_ic(15000.0, 350.0, psi_deg=0.0); a.trim(); a.step(5)
        b = F16Plant(); b.set_ic(15000.0, 350.0, psi_deg=0.0)
        b["ic/lat-gc-deg"] = 800.0 / FT_PER_DEG_LAT; b["ic/psi-true-deg"] = 0.0
        b.fdm.run_ic(); b.trim(); b.step(5)
        mm = Match(a, b, gs, control_hz=hz)
        r = mm.run(tactic_fn1=lvl, tactic_fn2=lvl, duration_s=10.0)
        print(f"  {hz:4.0f}Hz → kill t={r.time_s:5.2f}s  p1데미지={r.damage_dealt1:6.1f}  "
              f"winner={r.winner}")
