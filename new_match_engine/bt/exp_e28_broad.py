"""E28 (loop N+2) — ADAPTIVE subset을 *전체집합*(held-out 9 + 대표 8)에 평가.

방법론: A3/D2(ceiling)에 집착 말고, subset+보정이 *전체 적*의 격추수↑·무승부↓를 내나 측정.
base(RF) vs ADAPTIVE(base+게이트보정), 동일 harness, controller=indi(C3). 단일변수=보정 on/off.
가정: 부분집합이라 base 무회귀 + 일부 판정/무 → 격추/승 상향(B2처럼).
usage: python exp_e28_broad.py [dur] [controller]
"""
from __future__ import annotations
import sys, os, math, warnings
warnings.filterwarnings("ignore")
sys.path.insert(0, os.path.dirname(__file__))

from exp_e27_adaptive_subset import AdaptivePolicy
from exp_e22_chaseforce import _opp
from lqr import GainScheduledLQR
from autopilot import AutopilotConfig
from match import Match
from scenarios import spawn_adt_neutral
from replay import next_run_dir, write_acmi_plot, write_csv
from exp_e7_champion import _train
from exp_e10_unified import DS_DA

RBASE = os.path.join(os.path.dirname(__file__), "..", "replays", "research_broad")
# 대표 8 (학습-평가) + held-out 9
REP = ["A2_GunTracker", "B1_EnergyFighter", "C1_TwoCircleRate", "D3_Scissors", "E1_AdaptiveAce",
       "anchor_aggressive", "anchor_defensive", "anchor_ace"]
HELD = ["A1_PurePursuer", "A3_LagAngler", "B2_Extender", "C2_OneCircleRad", "C3_Lufbery",
        "D1_Reactive", "D2_LastDitch", "E2_Passive", "anchor_simple"]
OPPS = REP + HELD


def main(dur=180.0, controller="indi"):
    rf, tac = _train(DS_DA)
    gs = GainScheduledLQR([5000, 15000, 25000], [250, 350, 450]).build()
    cfg = AutopilotConfig(KP_PSI=0.25); cfg.MAX_PSI_RATE = math.radians(20.0)
    os.makedirs(RBASE, exist_ok=True)
    print(f"=== E28 broad: ADAPTIVE subset vs base, 전체 {len(OPPS)}적 [ctrl={controller}] {dur:.0f}s ===")
    print(f"{'opp':<18}{'base':>14}{'ADAPTIVE':>16}{'Δ':>6}")
    tally = {"base": [0, 0, 0], "ADAPTIVE": [0, 0, 0]}  # [win, kill, draw]
    for opp_name in OPPS:
        row = {}
        for mode in ["base", "ADAPTIVE"]:
            p1, p2 = spawn_adt_neutral()
            pol = AdaptivePolicy(rf, tac, corrections=(mode == "ADAPTIVE"))
            m = Match(p1, p2, gs, cfg1=cfg, cfg2=AutopilotConfig(KP_PSI=0.10),
                      control_hz=20, bt_hz=10, log_hz=60, controller1=controller, controller2="lqr")
            res = m.run(tactic_fn1=lambda o: pol.select(p1, p2), tactic_fn2=_opp(opp_name), duration_s=dur)
            kill = res.health2 <= 0
            win = (res.winner == "agent1") or (res.winner == "draw" and res.health1 > res.health2)
            draw = (not win) and res.health1 == res.health2
            mk = "격추" if kill else ("판정" if win else ("무" if draw else "패"))
            tally[mode][0] += int(win); tally[mode][1] += int(kill); tally[mode][2] += int(draw)
            row[mode] = (mk, res.damage_dealt1, res.health2)
            rd = next_run_dir(RBASE, prefix=f"{opp_name}__{mode}")
            write_acmi_plot(res.log, os.path.join(rd, "match.acmi"), title=f"{opp_name}_{mode}")
            write_csv(res.log, os.path.join(rd, "match.csv"))
        bm, bd, _ = row["base"]; am, ad, _ = row["ADAPTIVE"]
        delta = "↑" if (ad > bd + 5 or (am == "격추" and bm != "격추")) else ("↓" if (bd > ad + 5 or (bm == "격추" and am != "격추")) else "=")
        tag = " ◀held" if opp_name in HELD else ""
        print(f"{opp_name:<18}{bm+f'({bd:.0f})':>14}{am+f'({ad:.0f})':>16}{delta:>6}{tag}", flush=True)
    print(f"\n  base    : 승{tally['base'][0]} 격추{tally['base'][1]} 무{tally['base'][2]}")
    print(f"  ADAPTIVE: 승{tally['ADAPTIVE'][0]} 격추{tally['ADAPTIVE'][1]} 무{tally['ADAPTIVE'][2]}")
    print(f"  replay: {os.path.relpath(RBASE)}", flush=True)


if __name__ == "__main__":
    a = sys.argv[1:]
    main(float(a[0]) if a else 180.0, a[1] if len(a) > 1 else "indi")
