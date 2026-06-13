"""ADAPTIVE 회귀 테스트 — SE 안전망 (Design-by-Contract: base ⊆ ADAPTIVE).

방법론(docs/NEW_ENGINE_ADAPTIVE_METHODOLOGY.md §0): ADAPTIVE는 base를 부분집합으로 포함.
불변식(자동 검증):
  C1. WIN-보존: base가 *이기는*(판정/격추) 적은 ADAPTIVE도 반드시 이긴다 (승→무/패 회귀 금지).
  C2. 순-무회귀: ADAPTIVE 승수 ≥ base 승수, ADAPTIVE 격추수 ≥ base 격추수.
cost/게이트/보정을 바꿀 때마다 이 테스트가 base-승리 보존을 보증 (D3/ace식 회귀 자동 포착).

fast(기본): 4 대표적 × 120s. full: env NME_REG_FULL=1 → 더 많은 적·긴 시간.
실행: pytest new_match_engine/bt/test_adaptive_regression.py -s   (또는 직접 python)
"""
from __future__ import annotations
import os, sys, math, warnings
warnings.filterwarnings("ignore")
sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "control"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "engine"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "tools"))

from exp_e27_adaptive_subset import AdaptivePolicy
from exp_e22_chaseforce import _opp
from lqr import GainScheduledLQR
from autopilot import AutopilotConfig
from match import Match
from scenarios import spawn_adt_neutral
from exp_e7_champion import _train
from exp_e10_unified import DS_DA

_FULL = os.environ.get("NME_REG_FULL", "") == "1"
# 대표적: base-격추(ace,C2) + base-판정(B1) + ceiling 무(A3). full이면 확장.
OPPS = (["anchor_ace", "C2_OneCircleRad", "B1_EnergyFighter", "A3_LagAngler"]
        if not _FULL else
        ["anchor_ace", "anchor_defensive", "C1_TwoCircleRate", "C2_OneCircleRad",
         "B1_EnergyFighter", "D3_Scissors", "D1_Reactive", "A3_LagAngler", "D2_LastDitch"])
DUR = 120.0 if not _FULL else 180.0


def _outcome(res):
    if res.health2 <= 0 and res.health1 > 0: return "kill"
    if res.health1 > res.health2: return "win"
    if res.health1 < res.health2: return "loss"
    return "draw"


def _run_all():
    rf, tac = _train(DS_DA)
    gs = GainScheduledLQR([5000, 15000, 25000], [250, 350, 450]).build()
    cfg = AutopilotConfig(KP_PSI=0.25); cfg.MAX_PSI_RATE = math.radians(20.0)
    out = {}
    for opp in OPPS:
        row = {}
        for mode in ("base", "ADAPTIVE"):
            p1, p2 = spawn_adt_neutral()
            pol = AdaptivePolicy(rf, tac, corrections=(mode == "ADAPTIVE"))
            m = Match(p1, p2, gs, cfg1=cfg, cfg2=AutopilotConfig(KP_PSI=0.10),
                      control_hz=20, bt_hz=10, log_hz=60, controller1="indi", controller2="lqr")
            res = m.run(tactic_fn1=lambda o: pol.select(p1, p2), tactic_fn2=_opp(opp), duration_s=DUR)
            row[mode] = _outcome(res)
        out[opp] = row
    return out


_RESULTS = None
def _results():
    global _RESULTS
    if _RESULTS is None:
        _RESULTS = _run_all()
        print("\n[회귀 결과]")
        for opp, r in _RESULTS.items():
            flag = "" if _won(r["ADAPTIVE"]) or not _won(r["base"]) else "  ← WIN 회귀!"
            print(f"  {opp:<18} base={r['base']:<5} ADAPTIVE={r['ADAPTIVE']:<5}{flag}")
    return _RESULTS


def _won(o): return o in ("kill", "win")


def test_subset_win_preservation():
    """C1: base가 이기는 적은 ADAPTIVE도 이긴다 (승→무/패 회귀 금지)."""
    r = _results()
    violations = [opp for opp, o in r.items() if _won(o["base"]) and not _won(o["ADAPTIVE"])]
    assert not violations, f"부분집합 위반 — base-승리가 ADAPTIVE서 깨짐: {violations}"


def test_net_non_regression():
    """C2: ADAPTIVE 승수 ≥ base 승수, 격추수 ≥ base 격추수."""
    r = _results()
    bw = sum(_won(o["base"]) for o in r.values())
    aw = sum(_won(o["ADAPTIVE"]) for o in r.values())
    bk = sum(o["base"] == "kill" for o in r.values())
    ak = sum(o["ADAPTIVE"] == "kill" for o in r.values())
    assert aw >= bw, f"승수 회귀: ADAPTIVE {aw} < base {bw}"
    assert ak >= bk, f"격추수 회귀: ADAPTIVE {ak} < base {bk}"


if __name__ == "__main__":
    r = _results()
    bw = sum(_won(o["base"]) for o in r.values()); aw = sum(_won(o["ADAPTIVE"]) for o in r.values())
    bk = sum(o["base"] == "kill" for o in r.values()); ak = sum(o["ADAPTIVE"] == "kill" for o in r.values())
    print(f"\n  base: {bw}승 {bk}격추  |  ADAPTIVE: {aw}승 {ak}격추")
    viol = [o for o, x in r.items() if _won(x["base"]) and not _won(x["ADAPTIVE"])]
    print(f"  WIN-보존 위반: {viol or '없음'}  |  순-무회귀: {'OK' if aw>=bw and ak>=bk else 'FAIL'}")
