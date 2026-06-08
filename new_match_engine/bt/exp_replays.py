"""실험 replay 생성 — 더블체크 필수 (feedback-replays-mandatory).

설계 적 archetype별 대표 1개 + 앵커 4개를 배포 정책(TreePolicy)과 canonical neutral spawn 에서
매치 → replay(.acmi) + csv + events + report.txt + plot.png 저장.
목적: 적이 교리대로 싸우는지(strawman/오설계 아닌지) + 우리 정책 응답을 눈으로 더블체크.

usage: python exp_replays.py [duration_s]
출력: new_match_engine/replays/research/<archetype>_*/{match.acmi, match.csv, report.txt, plot.png}
"""
from __future__ import annotations
import sys, os, glob, math

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "control"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "engine"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "tools"))

from lqr import GainScheduledLQR
from autopilot import AutopilotConfig
from match import Match
from scenarios import spawn_adt_neutral
from opponents import OPPONENT_BTS
from yaml_bt import load_bt
from tree_policy import TreePolicy
from replay import next_run_dir, write_acmi_plot, write_csv
from plot_match_3d_nme import analyze_match_files

ZOO = os.path.join(os.path.dirname(__file__), "..", "opponents", "zoo")
RBASE = os.path.join(os.path.dirname(__file__), "..", "replays", "research")


def _representatives():
    """archetype별 대표 1개(중앙 변주) + 앵커 4."""
    by_arch = {}
    for f in sorted(glob.glob(os.path.join(ZOO, "*.yaml"))):
        arch = os.path.basename(f).rsplit("_", 1)[0]
        by_arch.setdefault(arch, []).append(f)
    reps = []
    for arch, files in by_arch.items():
        f = files[len(files) // 2]                       # 중앙 변주
        reps.append((arch, load_bt(f)))
    for name, fn in OPPONENT_BTS.items():
        reps.append((f"anchor_{name}", fn))
    return reps


def main(duration_s=200.0):
    gs = GainScheduledLQR([5000, 15000, 25000], [250, 350, 450]).build()
    cfg = AutopilotConfig(KP_PSI=0.25); cfg.MAX_PSI_RATE = math.radians(20.0)
    reps = _representatives()
    print(f"=== 실험 replay 생성: {len(reps)}개 매치 (canonical neutral, {duration_s:.0f}s) ===")
    os.makedirs(RBASE, exist_ok=True)
    summary = []
    for arch, opp_fn in reps:
        p1, p2 = spawn_adt_neutral()
        pol = TreePolicy()
        m = Match(p1, p2, gs, cfg1=cfg, cfg2=AutopilotConfig(KP_PSI=0.10),
                  control_hz=20, bt_hz=10, log_hz=60)
        res = m.run(tactic_fn1=lambda o: pol.select(p1, p2), tactic_fn2=opp_fn,
                    duration_s=duration_s)
        win = (res.winner == "agent1") or (res.winner == "draw" and res.health1 > res.health2)
        mk = "W" if res.winner == "agent1" else ("L" if res.winner == "agent2"
             else ("w" if res.health1 > res.health2 else ("d" if res.health1 == res.health2 else "l")))
        rd = next_run_dir(RBASE, prefix=arch)
        acmi = os.path.join(rd, "match.acmi"); csvp = os.path.join(rd, "match.csv")
        write_acmi_plot(res.log, acmi, title=arch)
        write_csv(res.log, csvp)
        with open(os.path.join(rd, "events.log"), "w", encoding="utf-8") as f:
            for t, k, msg in (res.events or []):
                f.write(f"[{t:7.2f}s] {k:8s} {msg}\n")
        try:
            analyze_match_files(acmi, meta_path=csvp, out_dir=rd, title=arch, make_plot=True)
        except Exception as e:
            print(f"   [analyze skip {arch}] {repr(e)[:70]}")
        summary.append((arch, mk, res.damage_dealt1, res.damage_taken1 if hasattr(res, "damage_taken1") else 0.0,
                        res.health1, res.health2))
        print(f"  {arch:<20} {mk}  dmg={res.damage_dealt1:5.1f}  HP {res.health1:3.0f}:{res.health2:3.0f}  → {os.path.basename(rd)}")

    W = sum(1 for _, mk, *_ in summary if mk in ("W", "w"))
    print(f"\n  우리 정책 {W}/{len(summary)} 우세. replay: {os.path.relpath(RBASE)}/<archetype>_*")
    print(f"  각 폴더: match.acmi(Tacview) + match.csv + events.log + report.txt + plot.png")


if __name__ == "__main__":
    main(float(sys.argv[1]) if len(sys.argv) > 1 else 200.0)
