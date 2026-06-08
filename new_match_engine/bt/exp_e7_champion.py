"""E7 — 배포 챔피언(현 BT) 대 이번 실험 정책 비교 (같은 적·길이).

질문: 최근 BT(tree_policy.TreePolicy = policy_value.pkl 챔피언 + 손-규칙)가 이번 실험의
순수 연속RF(clean H=25 라벨)보다 강한가. 왜인가.
방법: 같은 적 8종 × canonical neutral × 같은 duration 으로 챔피언과 연속RF(clean) 둘 다 평가.
      실력승(격추+결정타)·격추·WEZ dwell 비교. replay+report+plot 저장.

usage: python exp_e7_champion.py [duration_s]
"""
from __future__ import annotations
import sys, os, glob, math
import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "control"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "engine"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "tools"))

from lqr import GainScheduledLQR
from autopilot import AutopilotConfig
from match import Match
from scenarios import spawn_adt_neutral
from opponents import OPPONENT_BTS
from yaml_bt import load_bt
from tactic import Tactic
from tree_policy import TreePolicy
from exp_e6_winrate import ContPolicy, _opps
from replay import next_run_dir, write_acmi_plot, write_csv
from plot_match_3d_nme import analyze_match_files
from sklearn.ensemble import RandomForestRegressor

RBASE = os.path.join(os.path.dirname(__file__), "..", "replays", "research_champion")
DS = os.path.join(os.path.dirname(__file__), "..", "results_research_dataset.npz")


def main(dur=300.0):
    d = np.load(DS, allow_pickle=True)
    rf = RandomForestRegressor(n_estimators=150, max_depth=10, min_samples_leaf=6,
                               n_jobs=-1, random_state=0).fit(d["X"], d["Y"])
    tac = list(d["tactics"])
    gs = GainScheduledLQR([5000, 15000, 25000], [250, 350, 450]).build()
    cfg = AutopilotConfig(KP_PSI=0.25); cfg.MAX_PSI_RATE = math.radians(20.0)
    opps = _opps(); os.makedirs(RBASE, exist_ok=True)
    print(f"=== E7 챔피언 대 clean-연속RF (적 {len(opps)}, neutral {dur:.0f}s) ===\n")
    policies = [
        ("champion", lambda: TreePolicy()),                 # 배포 챔피언(8-tactic pkl + 손-규칙)
        ("cleanRF",  lambda: ContPolicy(rf, tac)),          # 이번 실험 연속RF(clean H=25)
    ]
    print(f"  {'정책':<10}{'판정':>6}{'실력':>6}{'격추':>6}  매치별(적:판정(dmg,WEZdwell))")
    for pname, fac in policies:
        wins = real = kills = 0; cells = []
        for opp_name, opp_fn in opps.items():
            p1, p2 = spawn_adt_neutral(); pol = fac()
            m = Match(p1, p2, gs, cfg1=cfg, cfg2=AutopilotConfig(KP_PSI=0.10),
                      control_hz=20, bt_hz=10, log_hz=60)
            res = m.run(tactic_fn1=lambda o: pol.select(p1, p2), tactic_fn2=opp_fn, duration_s=dur)
            win = (res.winner == "agent1") or (res.winner == "draw" and res.health1 > res.health2)
            wins += int(win); kills += int(res.health2 <= 0)
            real += int(res.health2 <= 0 or res.damage_dealt1 >= 40)
            mk = "W" if res.winner == "agent1" else ("L" if res.winner == "agent2" else "d")
            cells.append(f"{opp_name.split('_')[-1][:4]}:{mk}({res.damage_dealt1:.0f})")
            rd = next_run_dir(RBASE, prefix=f"{pname}__{opp_name}")
            acmi = os.path.join(rd, "match.acmi"); csvp = os.path.join(rd, "match.csv")
            write_acmi_plot(res.log, acmi, title=f"{pname}_{opp_name}"); write_csv(res.log, csvp)
            try: analyze_match_files(acmi, meta_path=csvp, out_dir=rd, title=f"{pname}_{opp_name}", make_plot=True)
            except Exception as e: print(f"   [plot skip] {repr(e)[:50]}")
        print(f"  {pname:<10}{wins:>4}/8{real:>4}/8{kills:>6}  {' '.join(cells)}", flush=True)
    print(f"\n  실력 = 격추+결정타(dmg≥40). replay: {os.path.relpath(RBASE)}")


if __name__ == "__main__":
    main(float(sys.argv[1]) if len(sys.argv) > 1 else 300.0)
