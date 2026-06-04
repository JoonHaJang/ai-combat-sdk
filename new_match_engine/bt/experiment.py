"""BFM 교리 실험 하네스 — 시나리오·tactic 조합 → plot 검증.

누적 교리(graphify/cost_branch/메모리)를 새 엔진에서 직접 실험하고
plot_match_3d_nme 로 검증 (phase lock 180°=figure-8, WEZ dwell, Es_diff).

usage:
    python experiment.py <exp_name>
      figure8   : two-circle vs 선회하는 적 → 180° phase lock 나오나?
      onecircle : one-circle vs 선회 적
      vs_straight : selector vs 직진 적 (baseline)
"""
from __future__ import annotations
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "control"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "engine"))

from run_nme import run_match           # 통합 러너 (300s, event log, replay)
from tactic import Tactic, MATCH_DURATION_S
from tactic_selector import select_tactic

# ★ 모든 실험 = 원본 동일조건: ADT Neutral spawn + 300s(5분).
EXPERIMENTS = {
    # figure-8: 양측 TWO_CIRCLE → 같은방향 선회전 → figure-8 기대
    "figure8": dict(
        t1=lambda o: Tactic.TWO_CIRCLE, t2=lambda o: Tactic.TWO_CIRCLE,
        desc="양측 TWO_CIRCLE → 180° phase lock(figure-8) 검증",
    ),
    "onecircle": dict(
        t1=lambda o: Tactic.ONE_CIRCLE, t2=lambda o: Tactic.ONE_CIRCLE,
        desc="양측 ONE_CIRCLE → nose-to-nose 동심원",
    ),
    "vs_straight": dict(
        t1=select_tactic, t2=lambda o: Tactic.LEVEL_FLIGHT,
        desc="selector vs 직진 적 (baseline)",
    ),
    "sel_vs_sel": dict(
        t1=select_tactic, t2=select_tactic,
        desc="selector 대칭 (교착 예상)",
    ),
    "rate_win": dict(
        t1=lambda o: Tactic.TWO_CIRCLE, t2=lambda o: Tactic.PURE_PURSUIT,
        desc="우리 TWO_CIRCLE(corner) vs 적 PURE_PURSUIT → out-rate 승리?",
    ),
    "sel_turn": dict(
        t1=select_tactic, t2=lambda o: Tactic.TWO_CIRCLE,
        desc="우리 selector vs 적 TWO_CIRCLE → selector 대응 검증",
    ),
}


def run(name, duration_s=MATCH_DURATION_S):
    if name not in EXPERIMENTS:
        print(f"실험 없음: {name}. 가능: {list(EXPERIMENTS)}"); return
    e = EXPERIMENTS[name]
    print(f"=== 실험 [{name}] {e['desc']}  (원본 동일: ADT neutral, {duration_s:.0f}s) ===")
    return run_match(e["t1"], e["t2"], label=name, duration_s=duration_s)


if __name__ == "__main__":
    run(sys.argv[1] if len(sys.argv) > 1 else "figure8")
