"""선회전 궤적 측정 — TWO_CIRCLE 강제 vs 선회하는 적.

측정 먼저 (원칙): 엔진 추력 수정 후 현재 TWO_CIRCLE이 실제로
  - corner speed(320kt) 로 감속/유지하나?
  - 고도(에너지) 유지하나?
  - 적에 각도 이득(advantage↑) 보나?
→ 무엇을 trajectory 층에 추가할지 데이터로 결정.
"""
from __future__ import annotations
import sys, os, math
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "control"))
import numpy as np

from plant import F16Plant
from lqr import GainScheduledLQR
from autopilot import AutopilotConfig
from tactic import Tactic, V_CORNER_KTS
from obs import compute_obs, FT_PER_DEG_LAT
from pilot import Pilot

CTRL_HZ = 20.0


def run_forced(tactic, gs, secs=30.0):
    """ego=강제 tactic, 적=지속 우선회. 시계열 반환."""
    ego = F16Plant(); ego.set_ic(15000.0, 350.0, psi_deg=0.0); ego.trim(); ego.step(5)
    # 적: ego 우측 3000ft, 지속 우선회 (turning fight 상대)
    enm = F16Plant(); enm.set_ic(15000.0, 350.0, psi_deg=0.0)
    enm["ic/long-gc-deg"] = 3000.0 / FT_PER_DEG_LAT
    enm["ic/psi-true-deg"] = 0.0
    enm.fdm.run_ic(); enm.trim(); enm.step(5)

    pilot = Pilot(ego, gs, AutopilotConfig(KP_PSI=0.08), dt=1.0/CTRL_HZ)
    n = max(1, int(round((1.0/CTRL_HZ) / ego.dt)))
    rows = []
    for tick in range(int(secs * CTRL_HZ)):
        u = pilot.step(enm, tactic=tactic)
        ego.set_input(u)
        # 적 지속 우선회 (aileron +0.3)
        eu = enm.get_input(); eu[2] = 0.30; enm.set_input(eu)
        for _ in range(n):
            ego.step(1); enm.step(1)
        o = pilot.last_obs
        rows.append((tick/CTRL_HZ, o.ego_vc_kts, o.ego_alt_ft, o.advantage,
                     o.ata_deg, o.distance_ft, o.enm_vc_kts))
    return np.array(rows)


if __name__ == "__main__":
    print("=" * 68)
    print("  선회전 궤적 측정 — TWO_CIRCLE 강제 vs 지속 우선회 적 (30s)")
    print("=" * 68)
    gs = GainScheduledLQR([5000,15000,25000],[250,350,450]).build()
    r = run_forced(Tactic.TWO_CIRCLE, gs, secs=30.0)

    print(f"\n{'t':>5} {'ego_vc':>7} {'ego_alt':>8} {'advantage':>10} {'ata':>6} {'dist':>6} {'enm_vc':>7}")
    print("-"*56)
    for i in range(0, len(r), int(5*CTRL_HZ)):  # 5초마다
        t,vc,alt,adv,ata,dist,evc = r[i]
        print(f"{t:>5.1f} {vc:>7.1f} {alt:>8.0f} {adv:>+10.2f} {ata:>6.1f} {dist:>6.0f} {evc:>7.1f}")
    t,vc,alt,adv,ata,dist,evc = r[-1]
    print(f"{t:>5.1f} {vc:>7.1f} {alt:>8.0f} {adv:>+10.2f} {ata:>6.1f} {dist:>6.0f} {evc:>7.1f}")

    print("\n진단:")
    print(f"  corner speed(320) 유지? 최종 vc={r[-1][1]:.0f} (목표 320)")
    print(f"  에너지(고도) 유지?     15000→{r[-1][2]:.0f} (Δ{r[-1][2]-15000:+.0f}ft)")
    print(f"  각도 이득?            advantage {r[0][3]:+.2f}→{r[-1][3]:+.2f}")
    print(f"  (advantage 증가 = 각도 이득 = 선회전 이김)")
