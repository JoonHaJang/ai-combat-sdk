"""run_match.py — ★ canonical 평가 표준 진입점 (메모리 match-canonical-initial-condition).

평가는 반드시 spawn_adt_neutral (90° beam, anti-parallel, 3000ft). 임의 spawn 금지.
적 = legacy .yaml (yaml_bt 인터프리터) — .yaml 인터페이스 호환 (구엔진 적 그대로).
우리 정책 = TreePolicy (RF + 상황 독립 dispatch).

표준 체인:
  spawn_adt_neutral(beam) → TreePolicy(obs→tactic) → guidance → autopilot → LQR → JSBSim
                                                                    ↓
                                                       WEZ → health → judge
출력: 매 경기 별도 폴더 (match.acmi + match.csv + report.txt + plot.png).

usage:
  python run_match.py                # canonical beam vs 4 적(.yaml) → N/4
  python run_match.py ace            # 단일 적
"""
from __future__ import annotations
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "control"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "engine"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "tools"))

from autopilot import AutopilotConfig
from scenarios import spawn_adt_neutral
from replay import next_run_dir, write_acmi_plot, write_csv
from yaml_bt import load_bt
from tree_policy import TreePolicy
from plot_match_3d_nme import analyze_match_files
from match_harness import run_engine_match     # ★ 엔진 실행 단일 진실 (scripts/run_match 와 공유)

# legacy .yaml 적 (yaml_bt 해석). 평가 4적 (메모리: spawn 은 beam 고정, 적만 다양).
def _find_examples_dir(here):
    """opponent .yaml(ace 등) 이 든 examples/ 를 robust 하게 — new_match_engine 이 core 안
    (../../examples) 이든 sdk 안(../../ai-combat-core-main/.../examples) 이든.
    ★ vendored core 를 *먼저* 찾는다(sdk 원동작 보존; sdk 의 examples/ 는 내용이 달라 혼동).
      core 배포 시엔 vendored 가 없어 ../../examples(core 자신) 사용."""
    for c in (os.path.join(here, "..", "..", "ai-combat-core-main",
                           "ai-combat-core-main", "examples"),    # sdk vendored (우선)
              os.path.join(here, "..", "..", "examples")):        # core 자신
        if os.path.isfile(os.path.join(c, "ace.yaml")):
            return c
    return os.path.join(here, "..", "..", "examples")


_YAML_DIR = _find_examples_dir(os.path.dirname(__file__))
OPPONENTS = ["simple", "aggressive", "defensive", "ace"]


def run_one(opp_name, rbase, duration_s=300.0, controller="lqr"):
    """canonical beam vs 단일 .yaml 적 1경기 → (win, res, rel_dir). replay+report 저장.

    엔진 실행은 run_engine_match(단일 진실, scripts/run_match 와 공유). canonical 고유 =
    side1=TreePolicy(우리 정책) + cfg2=적 핸디캡(KP_PSI=0.10) + report/plot 산출.
    """
    p1, p2 = spawn_adt_neutral()                 # ★ canonical beam (90° anti-parallel 3000ft)
    pol = TreePolicy()                            # RF + dispatch (경기마다 새로 — state 리셋)
    opp_fn = load_bt(os.path.join(_YAML_DIR, opp_name + ".yaml"))   # ★ .yaml 적
    res = run_engine_match(
        p1, p2,
        tactic_fn1=lambda o: pol.select(p1, p2),
        tactic_fn2=opp_fn,
        controller=controller,
        cfg2=AutopilotConfig(KP_PSI=0.10),       # 적 핸디캡 (canonical 고유 평가설정)
        duration_s=duration_s)
    win = (res.winner == "agent1") or (res.winner == "draw" and res.health1 > res.health2)
    rd = next_run_dir(rbase, prefix=f"canon_{opp_name}")
    acmi = os.path.join(rd, "match.acmi"); csvp = os.path.join(rd, "match.csv")
    write_acmi_plot(res.log, acmi, title=f"canonical_beam_vs_{opp_name}")
    write_csv(res.log, csvp)
    try:
        analyze_match_files(acmi, meta_path=csvp, out_dir=rd, title=f"beam_vs_{opp_name}")
    except Exception as e:
        print(f"    [analyze skip {opp_name}] {e}")
    return win, res, os.path.relpath(rd)


if __name__ == "__main__":
    rbase = os.path.join(os.path.dirname(__file__), "..", "replays")
    opps = [sys.argv[1]] if len(sys.argv) > 1 else OPPONENTS
    print("=" * 64)
    print("  CANONICAL 평가 — spawn_adt_neutral(beam) vs .yaml 적 / TreePolicy")
    print("  (엔진 실행 = match_harness.run_engine_match, scripts/run_match 와 단일 진실 공유)")
    print("=" * 64)
    W = 0
    for opp in opps:
        win, res, rd = run_one(opp, rbase)
        mk = ("W" if res.winner == "agent1" else
              ("L" if res.winner == "agent2" else
               ("w" if res.health1 > res.health2 else
                ("l" if res.health1 < res.health2 else "d"))))
        if win:
            W += 1
        print(f"  beam vs {opp:<11}: {mk}  H1={res.health1:5.1f} H2={res.health2:5.1f} "
              f"dmg={res.damage_dealt1:5.1f}  [{rd}]")
    print(f"\n  ★ CANONICAL 승률: {W}/{len(opps)}")
