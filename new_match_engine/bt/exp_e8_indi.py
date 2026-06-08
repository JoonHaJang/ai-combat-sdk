"""E8 — INDI 대 LQR 내측 제어기 A/B (같은 정책·적·길이).

질문: INDI 내측이 LQR보다 교전/격추를 늘리나(특히 nose-chaser 닫기). 16장 검증은 INDI 우위가
깊은 고받음각+모델불확실에서만이라 일반 교전에선 작을 수 있다 — 가정 말고 측정.
방법: 최고 정책 cleanRF_H60 을 controller=lqr 와 indi 로 각각 같은 8적·canonical neutral·300s.
      격추+결정타·WEZ dwell 비교. replay 저장.

usage: python exp_e8_indi.py [duration_s]
"""
from __future__ import annotations
import sys, os, math
import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "control"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "engine"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "tools"))

from lqr import GainScheduledLQR
from autopilot import AutopilotConfig
from match import Match
from scenarios import spawn_adt_neutral
from exp_e6_winrate import ContPolicy, _opps
from exp_e7_champion import _train, DS_H60
from replay import next_run_dir, write_acmi_plot, write_csv
from plot_match_3d_nme import analyze_match_files

RBASE = os.path.join(os.path.dirname(__file__), "..", "replays", "research_indi")


def main(dur=300.0):
    rf60, tac60 = _train(DS_H60)
    gs = GainScheduledLQR([5000, 15000, 25000], [250, 350, 450]).build()
    cfg = AutopilotConfig(KP_PSI=0.25); cfg.MAX_PSI_RATE = math.radians(20.0)
    opps = _opps(); os.makedirs(RBASE, exist_ok=True)
    print(f"=== E8 INDI 대 LQR (정책=cleanRF_H60, 적 {len(opps)}, neutral {dur:.0f}s) ===\n")
    print(f"  {'제어기':<8}{'판정':>6}{'실력':>6}{'격추':>6}  적별(판정(dmg))")
    for ctrl in ["lqr", "indi"]:
        wins = real = kills = 0; cells = []
        for opp_name, opp_fn in opps.items():
            p1, p2 = spawn_adt_neutral(); pol = ContPolicy(rf60, tac60)
            try:
                m = Match(p1, p2, gs, cfg1=cfg, cfg2=AutopilotConfig(KP_PSI=0.10),
                          control_hz=20, bt_hz=10, log_hz=60,
                          controller1=ctrl, controller2="lqr")
                res = m.run(tactic_fn1=lambda o: pol.select(p1, p2), tactic_fn2=opp_fn, duration_s=dur)
            except Exception as e:
                print(f"   [FAIL {ctrl} {opp_name}] {repr(e)[:80]}"); cells.append(f"{opp_name[:4]}:ERR"); continue
            win = (res.winner == "agent1") or (res.winner == "draw" and res.health1 > res.health2)
            wins += int(win); kills += int(res.health2 <= 0)
            real += int(res.health2 <= 0 or res.damage_dealt1 >= 40)
            mk = "W" if res.winner == "agent1" else ("L" if res.winner == "agent2" else "d")
            cells.append(f"{opp_name.split('_')[-1][:4]}:{mk}({res.damage_dealt1:.0f})")
            rd = next_run_dir(RBASE, prefix=f"{ctrl}__{opp_name}")
            acmi = os.path.join(rd, "match.acmi"); csvp = os.path.join(rd, "match.csv")
            write_acmi_plot(res.log, acmi, title=f"{ctrl}_{opp_name}"); write_csv(res.log, csvp)
            try: analyze_match_files(acmi, meta_path=csvp, out_dir=rd, title=f"{ctrl}_{opp_name}", make_plot=True)
            except Exception: pass
        print(f"  {ctrl:<8}{wins:>4}/8{real:>4}/8{kills:>6}  {' '.join(cells)}", flush=True)
    print(f"\n  실력=격추+결정타(dmg≥40). replay: {os.path.relpath(RBASE)}")


if __name__ == "__main__":
    main(float(sys.argv[1]) if len(sys.argv) > 1 else 300.0)
