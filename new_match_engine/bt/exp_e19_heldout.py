"""E19 — held-out 일반화 평가: UnifiedPolicy(E10) vs 학습엔 썼으나 *평가 안 한* 9 archetype.

목적: "8/8"이 in-sample 점수(학습=평가 누수)라는 의혹 검증. held-out 적에서도 이기면 일반화 근거,
지면 진짜 프론티어(어느 archetype이 깨지나)를 찾은 것. UnifiedPolicy/Match 파라미터는 E10과 동일.

held-out 집합 (E0 학습 115적엔 포함, E6 `_opps` 평가 8적엔 미포함):
  zoo 중간 인스턴스: A1_PurePursuer, A3_LagAngler, B2_Extender, C2_OneCircleRad,
                     C3_Lufbery, D1_Reactive, D2_LastDitch, E2_Passive
  anchor: anchor_simple
usage: python exp_e19_heldout.py [duration_s]
출력: new_match_engine/replays/research_heldout/unified__<opp>_*/{acmi,csv,report,plot}
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
from replay import next_run_dir, write_acmi_plot, write_csv
from plot_match_3d_nme import analyze_match_files

from exp_e7_champion import _train
from exp_e10_unified import UnifiedPolicy, DS_DA, STUCK_S

ZOO = os.path.join(os.path.dirname(__file__), "..", "opponents", "zoo")
RBASE = os.path.join(os.path.dirname(__file__), "..", "replays", "research_heldout")

# E6 _opps 가 평가에 쓴 5 zoo archetype 을 제외한, 학습에만 쓰인 나머지 archetype.
HELDOUT_ARCH = ["A1_PurePursuer", "A3_LagAngler", "B2_Extender", "C2_OneCircleRad",
                "C3_Lufbery", "D1_Reactive", "D2_LastDitch", "E2_Passive"]


def _heldout_opps():
    reps = {}
    for arch in HELDOUT_ARCH:
        fs = sorted(glob.glob(os.path.join(ZOO, arch + "_*.yaml")))
        if fs:
            reps[arch] = load_bt(fs[len(fs) // 2])   # _opps 와 동일하게 중간 인스턴스
        else:
            print(f"  [warn] zoo 에 {arch}_*.yaml 없음 — 건너뜀", flush=True)
    reps["anchor_simple"] = OPPONENT_BTS["simple"]   # 평가 8적엔 빠졌던 simple anchor
    return reps


def main(dur=300.0, stuck_s=STUCK_S):
    rf, tac = _train(DS_DA)
    gs = GainScheduledLQR([5000, 15000, 25000], [250, 350, 450]).build()
    cfg = AutopilotConfig(KP_PSI=0.25); cfg.MAX_PSI_RATE = math.radians(20.0)
    opps = _heldout_opps(); os.makedirs(RBASE, exist_ok=True)
    print(f"=== E19 held-out 일반화 (UnifiedPolicy E10) 적 {len(opps)} {dur:.0f}s ===\n", flush=True)
    wins = real = kills = 0; cells = []
    for opp_name, opp_fn in opps.items():
        p1, p2 = spawn_adt_neutral(); pol = UnifiedPolicy(rf, tac, bt_hz=10.0, stuck_s=stuck_s)
        m = Match(p1, p2, gs, cfg1=cfg, cfg2=AutopilotConfig(KP_PSI=0.10),
                  control_hz=20, bt_hz=10, log_hz=60)
        res = m.run(tactic_fn1=lambda o: pol.select(p1, p2), tactic_fn2=opp_fn, duration_s=dur)
        win = (res.winner == "agent1") or (res.winner == "draw" and res.health1 > res.health2)
        wins += int(win); kills += int(res.health2 <= 0)
        real += int(res.health2 <= 0 or res.damage_dealt1 >= 40)
        mk = "W" if res.winner == "agent1" else ("L" if res.winner == "agent2"
             else ("w" if res.health1 > res.health2 else "d"))
        cells.append(f"{opp_name.split('_')[-1][:4]}:{mk}({res.damage_dealt1:.0f}/{res.health2:.0f})")
        rd = next_run_dir(RBASE, prefix=f"unified__{opp_name}")
        acmi = os.path.join(rd, "match.acmi"); csvp = os.path.join(rd, "match.csv")
        write_acmi_plot(res.log, acmi, title=f"unified_{opp_name}"); write_csv(res.log, csvp)
        try: analyze_match_files(acmi, meta_path=csvp, out_dir=rd, title=f"unified_{opp_name}", make_plot=True)
        except Exception: pass
        print(f"  {opp_name:<18} {mk} dmg={res.damage_dealt1:.0f} HP {res.health1:.0f}:{res.health2:.0f} "
              f"latch={pol.latch}", flush=True)
    n = len(opps)
    print(f"\n  held-out: 판정 {wins}/{n}, 실력 {real}/{n}, 격추 {kills}  | {' '.join(cells)}", flush=True)
    print(f"  (판정승=HP차/하드덱 포함). replay: {os.path.relpath(RBASE)}", flush=True)


if __name__ == "__main__":
    a = sys.argv[1:]
    main(float(a[0]) if a else 300.0, float(a[1]) if len(a) > 1 else STUCK_S)
