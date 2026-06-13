"""E29 (self-play) — ADAPTIVE vs base 직접 대결. 보정이 *대등 학습기체*에게 edge를 만드나.

논리: base는 학습된 대등 적(scripted 아님). ADAPTIVE가 base를 이기면 → 보정이 대등상대 edge 생성
= "대칭 교착 ceiling"(loop N+1)을 *우리가 깰 수 있는가* 직접 시험. base-vs-base(무 예상)=기준선.
controller 양측 동일(공정). 여러 spawn으로 side-bias·robustness 확인.
usage: python exp_e29_selfplay.py [dur] [controller]
"""
from __future__ import annotations
import sys, os, math, warnings
warnings.filterwarnings("ignore")
sys.path.insert(0, os.path.dirname(__file__))

from exp_e27_adaptive_subset import AdaptivePolicy
from lqr import GainScheduledLQR
from autopilot import AutopilotConfig
from match import Match
from scenarios import spawn_adt_neutral, spawn_offensive, spawn_defensive
from replay import next_run_dir, write_acmi_plot, write_csv
from plot_match_3d_nme import analyze_match_files
from exp_e7_champion import _train
from exp_e10_unified import DS_DA

RBASE = os.path.join(os.path.dirname(__file__), "..", "replays", "research_selfplay")


def main(dur=200.0, controller="lqr"):
    rf, tac = _train(DS_DA)
    gs = GainScheduledLQR([5000, 15000, 25000], [250, 350, 450]).build()
    cfg = AutopilotConfig(KP_PSI=0.25); cfg.MAX_PSI_RATE = math.radians(20.0)
    os.makedirs(RBASE, exist_ok=True)

    def mk(corr): return AdaptivePolicy(rf, tac, corrections=corr)
    # (label, p1정책 corr, p2정책 corr, spawn)
    cards = [
        ("base    vs base    (대칭 기준선)", False, False, spawn_adt_neutral),
        ("ADAPTIVE vs base    (★ edge 검증)", True,  False, spawn_adt_neutral),
        ("base    vs ADAPTIVE (side swap)",   False, True,  spawn_adt_neutral),
        ("ADAPTIVE vs ADAPTIVE (대칭 기준선)", True,  True,  spawn_adt_neutral),
    ]
    print(f"=== E29 self-play (ADAPTIVE vs base) [ctrl={controller}] {dur:.0f}s ===")
    print(f"{'card':<36}{'승자':<10}{'HP us:opp':>11}{'dmg→':>6}{'dmg←':>6}")
    for label, c1, c2, spawn in cards:
        p1, p2 = spawn()
        pol1, pol2 = mk(c1), mk(c2)
        m = Match(p1, p2, gs, cfg1=cfg, cfg2=AutopilotConfig(KP_PSI=0.25),
                  control_hz=20, bt_hz=10, log_hz=60,
                  controller1=controller, controller2=controller)
        res = m.run(tactic_fn1=lambda o: pol1.select(p1, p2),
                    tactic_fn2=lambda o: pol2.select(p2, p1), duration_s=dur)
        if res.health2 <= 0: w = "us격추"
        elif res.health1 <= 0: w = "opp격추"
        elif res.health1 > res.health2: w = "us판정"
        elif res.health2 > res.health1: w = "opp판정"
        else: w = "무"
        rd = next_run_dir(RBASE, prefix=label.split("(")[0].strip().replace(" ", ""))
        acmi = os.path.join(rd, "match.acmi"); csvp = os.path.join(rd, "match.csv")
        write_acmi_plot(res.log, acmi, title=label); write_csv(res.log, csvp)
        try: analyze_match_files(acmi, meta_path=csvp, out_dir=rd, title=label, make_plot=False)
        except Exception: pass
        print(f"{label:<36}{w:<10}{res.health1:>5.0f}:{res.health2:<5.0f}"
              f"{res.damage_dealt1:>6.0f}{res.damage_dealt2:>6.0f}", flush=True)
    print(f"\n해석: base-vs-base=무(대칭)인데 ADAPTIVE-vs-base=us승이면 → 보정이 대등상대 edge 생성(ceiling 깸).")
    print(f"replay: {os.path.relpath(RBASE)}", flush=True)


if __name__ == "__main__":
    a = sys.argv[1:]
    main(float(a[0]) if a else 200.0, a[1] if len(a) > 1 else "lqr")
