"""상황 × tactic 매트릭스 — 특정 상황에서 어느 tactic이 유리한지 데이터 누적.

★ 데이터 기반 상황별 전술 (메모리 situation-conditional-vision).
  단순 상황(canonical spawn) × 단순 적(직진) × 우리 tactic 전수 → 유리도 측정.
  단순→복합으로 확장(적 거동 추가). 결과 CSV 누적 → 상황별 cost/dispatch 근거.

usage:
  python situation_matrix.py            # 전 상황 × 전 tactic sweep → 표 + CSV
  python situation_matrix.py offensive  # 특정 상황만
"""
from __future__ import annotations
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "control"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "engine"))

from lqr import GainScheduledLQR
from autopilot import AutopilotConfig
from match import Match
from scenarios import SITUATIONS
from obs import compute_obs
from tactic import Tactic, WEZ_ATA_DEG, WEZ_MIN_FT, WEZ_MAX_FT

# 평가할 우리 tactic (핵심 BFM 전수)
SWEEP_TACTICS = [
    Tactic.PURE_PURSUIT, Tactic.LEAD_PURSUIT, Tactic.LAG_PURSUIT, Tactic.GUN_TRACK,
    Tactic.ONE_CIRCLE, Tactic.TWO_CIRCLE, Tactic.HIGH_YOYO, Tactic.LOW_YOYO,
    Tactic.BREAK_TURN, Tactic.EXTENSION,
]
# 적 거동 (basic=직진. 추후 복합: 선회/반응형 추가)
OPPONENTS = {
    "straight": lambda o: Tactic.LEVEL_FLIGHT,
}

_AGGR_CFG = AutopilotConfig(KP_PSI=0.25)  # 직진 적 격파 검증된 aggressive 선회
import math
_AGGR_CFG.MAX_PSI_RATE = math.radians(20.0)

_GS = None
def _gs():
    global _GS
    if _GS is None:
        _GS = GainScheduledLQR([5000, 15000, 25000], [250, 350, 450]).build()
    return _GS


def run_cell(situation_fn, our_tactic, opp_fn, duration_s=60.0):
    """1 셀: 상황×tactic×적 1회 매치 → 지표 dict."""
    p1, p2 = situation_fn()
    m = Match(p1, p2, _gs(), cfg1=_AGGR_CFG, cfg2=AutopilotConfig(KP_PSI=0.10),
              control_hz=20, bt_hz=10, log_hz=0)
    wez = [0]; mind = [1e9]
    def t1(o):
        o2 = compute_obs(p1, p2)
        mind[0] = min(mind[0], o2.distance_ft)
        if o2.ata_deg < WEZ_ATA_DEG and WEZ_MIN_FT <= o2.distance_ft <= WEZ_MAX_FT:
            wez[0] += 1
        return our_tactic
    res = m.run(tactic_fn1=t1, tactic_fn2=opp_fn, duration_s=duration_s)
    ofin = compute_obs(p1, p2)
    return dict(winner=res.winner, dmg=res.damage_dealt1, taken=res.damage_dealt2,
                final_adv=ofin.advantage, min_dist=mind[0], wez_ticks=wez[0],
                t=res.time_s)


def run_matrix(situations=None, duration_s=60.0):
    sits = situations or list(SITUATIONS)
    rows = []
    print(f"\n{'='*78}\n  상황 × tactic 매트릭스 (적=직진, {duration_s:.0f}s)  — 유리도 데이터\n{'='*78}")
    for sit in sits:
        print(f"\n[{sit}]  {'tactic':<20}{'win':>6}{'dmg':>6}{'taken':>6}{'fin_adv':>8}{'minD':>7}{'WEZ':>5}")
        best = (None, -1e9)
        for tac in SWEEP_TACTICS:
            r = run_cell(SITUATIONS[sit], tac, OPPONENTS["straight"], duration_s)
            # 유리도 score: dmg - taken + WEZ dwell 가중
            score = r["dmg"] - r["taken"] + r["wez_ticks"] * 0.05
            if score > best[1]:
                best = (tac.name, score)
            win = "✓" if r["winner"] == "agent1" else ("✗" if r["winner"] == "agent2" else "·")
            print(f"         {tac.name:<20}{win:>6}{r['dmg']:>6.0f}{r['taken']:>6.0f}"
                  f"{r['final_adv']:>+8.2f}{r['min_dist']:>7.0f}{r['wez_ticks']:>5}")
            rows.append(dict(situation=sit, tactic=tac.name, **r))
        print(f"         → ★ 최우세: {best[0]}")
    # CSV 누적
    out = os.path.join(os.path.dirname(__file__), "..", "results_situation_matrix.csv")
    _append_csv(out, rows)
    print(f"\n데이터 누적: {os.path.relpath(out)}  (+{len(rows)} rows)")
    return rows


def _append_csv(path, rows):
    if not rows:
        return
    cols = ["situation", "tactic", "winner", "dmg", "taken", "final_adv",
            "min_dist", "wez_ticks", "t"]
    new = not os.path.exists(path)
    with open(path, "a", encoding="utf-8") as f:
        if new:
            f.write(",".join(cols) + "\n")
        for r in rows:
            f.write(",".join(f"{r[c]:.4f}" if isinstance(r[c], float) else str(r[c])
                             for c in cols) + "\n")


if __name__ == "__main__":
    sits = sys.argv[1:] if len(sys.argv) > 1 else None
    run_matrix(sits)
