"""E51 — 결정적 매치 replay 복원 (replay 규율 [[feedback-replays-mandatory]] 준수, 더블체크용).

스캔서 생략했던 핵심결과를 .acmi + report.txt + plot.png 로 영구저장:
  ① A3 base = 무 (draw)         ② A3 t0강제 LEAD→GUN = 승 (winnable 증거)
  ③ D2 t0강제 = 무 (uncatchable) ④ ace classifier = 격 (승자 보존 증거)
usage: python exp_e51_save_replays.py
"""
from __future__ import annotations
import sys, os, math, warnings, re
warnings.filterwarnings("ignore")
sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "control"))

from exp_e22_chaseforce import _opp
from exp_e27_adaptive_subset import AdaptivePolicy
from exp_e47_response_loop import two_phase
from lqr import GainScheduledLQR
from autopilot import AutopilotConfig
from match import Match
from scenarios import spawn_adt_neutral
from obs import compute_obs
from tactic import Tactic as T
from replay import next_run_dir, write_acmi_plot, write_csv
from plot_match_3d_nme import analyze_match_files
from exp_e7_champion import _train
from exp_e10_unified import DS_DA

RBASE = os.path.join(os.path.dirname(__file__), "..", "replays", "research_final")


def save(tag, p1, p2, res):
    rd = next_run_dir(RBASE, prefix=tag)
    acmi = os.path.join(rd, "match.acmi"); csvp = os.path.join(rd, "match.csv")
    write_acmi_plot(res.log, acmi, title=tag); write_csv(res.log, csvp)
    wez = "?"; mind = "?"
    try:
        analyze_match_files(acmi, meta_path=csvp, out_dir=rd, title=tag, make_plot=True)
        t = open(os.path.join(rd, "report.txt"), encoding="utf-8", errors="ignore").read()
        wez = (re.search(r"WEZ\(us\):\s*(\d+)", t) or [0, "?"])[1]
        mind = (re.search(r"min=(\d+)", t) or [0, "?"])[1]
    except Exception as e:
        print("  analyze err", e)
    return os.path.relpath(rd), wez, mind


def run(tag, opp, fn_build, rf, tac, gs, cfg, dur=200.0):
    p1, p2 = spawn_adt_neutral()
    fn = fn_build(p1, p2, rf, tac)
    m = Match(p1, p2, gs, cfg1=cfg, cfg2=AutopilotConfig(KP_PSI=0.10),
              control_hz=20, bt_hz=10, log_hz=60, controller1="indi", controller2="lqr")
    res = m.run(tactic_fn1=lambda o: fn(o), tactic_fn2=lambda o: _opp(opp)(compute_obs(p2, p1)), duration_s=dur)
    mk = "격추" if res.health2 <= 0 else ("판정승" if res.health1 > res.health2 else ("패" if res.health1 < res.health2 else "무"))
    rel, wez, mind = save(tag, p1, p2, res)
    print(f"{tag:<22}{mk:<6} dmg={res.damage_dealt1:>3.0f} HP {res.health1:.0f}:{res.health2:.0f}  WEZ={wez} minD={mind}m  → {rel}", flush=True)


def main():
    rf, tac = _train(DS_DA)
    gs = GainScheduledLQR([5000, 15000, 25000], [250, 350, 450]).build()
    cfg = AutopilotConfig(KP_PSI=0.25); cfg.MAX_PSI_RATE = math.radians(20.0)
    os.makedirs(RBASE, exist_ok=True)
    print("=== E51 결정적 매치 replay 복원 (acmi+report+plot) ===", flush=True)

    def base_build(p1, p2, rf, tac):
        ap = AdaptivePolicy(rf, tac, corrections=True); return lambda o: ap.select(p1, p2)
    def force_build(p1, p2, rf, tac):
        return two_phase(p1, p2, T.LEAD_PURSUIT, T.GUN_TRACK)

    run("A3_base_DRAW", "A3_LagAngler", base_build, rf, tac, gs, cfg)            # ① 무
    run("A3_force_WIN", "A3_LagAngler", force_build, rf, tac, gs, cfg)           # ② 승(winnable 증거)
    run("D2_force_NOKILL", "D2_LastDitch", force_build, rf, tac, gs, cfg)        # ③ 무(uncatchable)
    run("ace_base_KILL", "anchor_ace", base_build, rf, tac, gs, cfg)             # ④ 격(승자 보존)
    print(f"\n전부 저장: {os.path.relpath(RBASE)}", flush=True)


if __name__ == "__main__":
    main()
