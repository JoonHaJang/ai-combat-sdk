"""교전 전수 계측 — phase sequencing 설계 전 데이터 추출.

bt_vs_bt head-on 매치를 매 BT-tick 계측:
  - 선택된 tactic (양측)
  - obs 전부 (advantage, ata, aa, dist, closure, energy_diff, bank, vc, alt)
  - setpoint (psi*, h*, v*)
분석:
  1. tactic timeline (시간순)
  2. tactic histogram (체류시간)
  3. 전환 지점 (transition)
  4. 문제 진단 (분리/고도하강/각도손실 — 어느 tactic 중)
출력: CSV (data/) + 콘솔 분석.
"""
from __future__ import annotations
import sys, os, math
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "control"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "engine"))
import numpy as np

from plant import F16Plant
from lqr import GainScheduledLQR
from autopilot import AutopilotConfig
from obs import compute_obs, FT_PER_DEG_LAT
from pilot import Pilot
from judge import HealthGauge, wez_damage, judge, Victory
from tactic import Tactic
from tactic_selector import select_tactic, _specific_energy_ft

CTRL_HZ = 20.0; BT_HZ = 10.0; DWELL = 0.3
CDT = 1.0/CTRL_HZ


def run_instrumented(gs, duration_s=60.0):
    """bt_vs_bt head-on, 매 tick 전수 로깅."""
    p1 = F16Plant(); p1.set_ic(15000.0, 350.0, psi_deg=0.0); p1.trim(); p1.step(5)
    p2 = F16Plant(); p2.set_ic(15000.0, 350.0, psi_deg=180.0)
    p2["ic/lat-gc-deg"] = 3000.0/FT_PER_DEG_LAT; p2["ic/psi-true-deg"]=180.0
    p2.fdm.run_ic(); p2.trim(); p2.step(5)

    pilot1 = Pilot(p1, gs, AutopilotConfig(KP_PSI=0.08), dt=CDT)
    pilot2 = Pilot(p2, gs, AutopilotConfig(KP_PSI=0.08), dt=CDT)
    h1, h2 = HealthGauge(), HealthGauge()

    n_sub = max(1, int(round(CDT/p1.dt)))
    bt_every = max(1, int(round(CTRL_HZ/BT_HZ)))
    max_ticks = int(round(duration_s/CDT))
    t1 = t2 = Tactic.LEVEL_FLIGHT; age1 = age2 = 0.0
    rows = []

    for tick in range(max_ticks):
        o12 = compute_obs(p1, p2); o21 = compute_obs(p2, p1)
        # BT 결정 + dwell
        if tick % bt_every == 0:
            prop1 = select_tactic(o12); prop2 = select_tactic(o21)
            if prop1 != t1 and age1 >= DWELL: t1, age1 = prop1, 0.0
            else: age1 += CDT
            if prop2 != t2 and age2 >= DWELL: t2, age2 = prop2, 0.0
            else: age2 += CDT
        else:
            age1 += CDT; age2 += CDT

        u1 = pilot1.step(p2, tactic=t1); u2 = pilot2.step(p1, tactic=t2)
        p1.set_input(u1); p2.set_input(u2)
        # u = [thr, elev, ail, rud] (autopilot.py 순서)
        u1_thr, u1_elev, u1_ail, u1_rud = float(u1[0]), float(u1[1]), float(u1[2]), float(u1[3])
        u2_thr, u2_elev, u2_ail, u2_rud = float(u2[0]), float(u2[1]), float(u2[2]), float(u2[3])
        # WEZ
        d2 = wez_damage(o12.ata_deg, o12.distance_ft, CDT)
        d1 = wez_damage(o21.ata_deg, o21.distance_ft, CDT)
        if d2>0: h2.take_damage(d2)
        if d1>0: h1.take_damage(d1)
        for _ in range(n_sub): p1.step(1); p2.step(1)

        ediff = (_specific_energy_ft(o12.ego_alt_ft, o12.ego_vc_kts)
                 - _specific_energy_ft(o12.enm_alt_ft, o12.enm_vc_kts))
        rows.append(dict(
            t=tick*CDT, tac1=t1.name, tac2=t2.name,
            adv=o12.advantage, ata=o12.ata_deg, aa=o12.aa_deg, relb=o12.rel_b_deg,
            dist=o12.distance_ft, clos=o12.closure_kts, ediff=ediff,
            ego_alt=o12.ego_alt_ft, ego_vc=o12.ego_vc_kts,
            ego_bank=o12.ego_phi_deg, enm_bank=o12.enm_phi_deg,
            sp_psi=pilot1.last_setpoint.psi_star_deg, sp_h=pilot1.last_setpoint.h_star_ft,
            sp_v=pilot1.last_setpoint.v_star_kts, H1=h1.health, H2=h2.health,
            u1_thr=u1_thr, u1_elev=u1_elev, u1_ail=u1_ail, u1_rud=u1_rud,
            u2_thr=u2_thr, u2_elev=u2_elev, u2_ail=u2_ail, u2_rud=u2_rud,
        ))
        res = judge(p1["position/h-sl-ft"], p2["position/h-sl-ft"], h1.health, h2.health, tick+1, max_ticks)
        if res.condition != Victory.NONE:
            break
    return rows


if __name__ == "__main__":
    print("="*72); print("  교전 전수 계측 — bt_vs_bt head-on (phase sequencing 설계용)"); print("="*72)
    gs = GainScheduledLQR([5000,15000,25000],[250,350,450]).build()
    rows = run_instrumented(gs, 60.0)

    # ── 1. tactic timeline (2초마다, p1 기준) ─────────────────────────────
    print("\n[1] Tactic timeline (p1)")
    print(f"{'t':>5} {'tactic1':<16} {'adv':>6} {'ata':>5} {'dist':>6} {'clos':>5} {'alt':>6} {'vc':>5}")
    for r in rows[::int(2*CTRL_HZ)]:
        print(f"{r['t']:>5.1f} {r['tac1']:<16} {r['adv']:>+6.2f} {r['ata']:>5.0f} "
              f"{r['dist']:>6.0f} {r['clos']:>+5.0f} {r['ego_alt']:>6.0f} {r['ego_vc']:>5.0f}")

    # ── 2. histogram ──────────────────────────────────────────────────────
    print("\n[2] Tactic 체류시간 (p1)")
    from collections import Counter
    cnt = Counter(r['tac1'] for r in rows)
    for tac, c in cnt.most_common():
        print(f"  {tac:<18} {c*CDT:>6.1f}s  ({100*c/len(rows):>4.0f}%)")

    # ── 3. 전환 ───────────────────────────────────────────────────────────
    print("\n[3] Tactic 전환 (p1)")
    prev = None
    for r in rows:
        if r['tac1'] != prev:
            print(f"  t={r['t']:>5.1f}  → {r['tac1']:<16} (adv={r['adv']:+.2f} ata={r['ata']:.0f} dist={r['dist']:.0f} clos={r['clos']:+.0f})")
            prev = r['tac1']

    # ── 4. 문제 진단 ──────────────────────────────────────────────────────
    print("\n[4] 문제 진단")
    dists = [r['dist'] for r in rows]; alts = [r['ego_alt'] for r in rows]; advs=[r['adv'] for r in rows]
    imax = int(np.argmax(dists)); imin_alt = int(np.argmin(alts)); imax_adv=int(np.argmax(advs))
    print(f"  최대 분리: t={rows[imax]['t']:.1f}s dist={dists[imax]:.0f}ft (tactic={rows[imax]['tac1']})")
    print(f"  최저 고도: t={rows[imin_alt]['t']:.1f}s alt={alts[imin_alt]:.0f}ft (시작15000, Δ{alts[imin_alt]-15000:+.0f})")
    print(f"  최대 advantage: t={rows[imax_adv]['t']:.1f}s adv={advs[imax_adv]:+.2f} "
          f"ata={rows[imax_adv]['ata']:.0f} (이때 tactic={rows[imax_adv]['tac1']}, gun전환 됐나?)")
    print(f"  최종: H1={rows[-1]['H1']:.0f} H2={rows[-1]['H2']:.0f} t={rows[-1]['t']:.1f}s")

    # ── CSV 저장 ──────────────────────────────────────────────────────────
    datadir = os.path.join(os.path.dirname(__file__), "..", "data")
    os.makedirs(datadir, exist_ok=True)
    path = os.path.join(datadir, "engagement_headon.csv")
    with open(path, "w") as f:
        cols = list(rows[0].keys()); f.write(",".join(cols)+"\n")
        for r in rows:
            f.write(",".join(f"{r[c]:.4f}" if isinstance(r[c],float) else str(r[c]) for c in cols)+"\n")
    print(f"\n  전수 데이터: {os.path.relpath(path)} ({len(rows)} ticks)")
