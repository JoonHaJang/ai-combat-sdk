"""교환 검증 — bridge.BehaviorTreeMatch 가 legacy core 의 진짜 드롭인인지 *증명*.

3중 검증:
  [1] API 패리티  — legacy 생성자/`.run()` 인자가 bridge 에 모두 존재(드롭인 가능).
  [2] side-by-side — 동일 .yaml 쌍·동일 max_steps 를 legacy(.pyd) vs bridge(new_engine)
                     양 백엔드로 실행, *동일 인터페이스*로 결과 반환 확인(값은 RNN≠LQR 이라 다를 수 있음).
  [3] 드롭인 소비자 — scripts/run_match.py:230 의 getattr 패턴이 bridge 결과에 그대로 동작.

실행: python -m new_match_engine.bridge.verify_swap
"""
from __future__ import annotations
import os, sys, inspect, io, contextlib

_HERE = os.path.dirname(__file__)
_PROOT = os.path.abspath(os.path.join(_HERE, "..", ".."))
if _PROOT not in sys.path:
    sys.path.insert(0, _PROOT)

_YD = next((c for c in (
    os.path.join(_HERE, "..", "opponents"),                                            # ★ 번들(우선)
    os.path.join(_PROOT, "ai-combat-core-main", "ai-combat-core-main", "examples"),    # sdk vendored
    os.path.join(_PROOT, "examples"))                                                  # core 자신
    if os.path.isfile(os.path.join(c, "ace.yaml"))),
    os.path.join(_HERE, "..", "opponents"))
_PAIRS = [("aggressive", "simple"), ("ace", "defensive"), ("aggressive", "ace")]
_MAX_STEPS = 1500     # 75s (20Hz) — 빠르되 의미있게

PASS, FAIL = "PASS ✓", "FAIL ✗"


def _y(name):
    return os.path.join(_YD, name + ".yaml")


def _run(cls, t1, t2, **kw):
    """매치 1회 — JSBSim 잡음 억제하고 (winner, steps, H1, H2) 반환."""
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        m = cls(_y(t1), _y(t2), config_name="1v1/NoWeapon/bt_vs_bt",
                max_steps=_MAX_STEPS, **kw)
        r = m.run(replay_path=None, verbose=False)
    winner = getattr(r, "winner", "?")
    steps = getattr(r, "steps", getattr(r, "total_steps", -1))
    h1 = m.health1.current_health if getattr(m, "health1", None) else float("nan")
    h2 = m.health2.current_health if getattr(m, "health2", None) else float("nan")
    return winner, steps, h1, h2, r


def main():
    print("=" * 78)
    print("  엔진 교환 검증 — bridge(new_engine) ↔ legacy core 드롭인 증명")
    print("=" * 78)
    results = {}

    # ── [1] API 패리티 ──────────────────────────────────────────────────────
    print("\n[1] API 패리티 (legacy 인자 ⊆ bridge 인자 = 드롭인 가능)")
    from src.match.runner import BehaviorTreeMatch as Legacy
    from new_match_engine.bridge import BehaviorTreeMatch as Bridge
    lp = set(list(inspect.signature(Legacy.__init__).parameters)[1:])
    bp = set(list(inspect.signature(Bridge.__init__).parameters)[1:])
    lr = set(list(inspect.signature(Legacy.run).parameters)[1:])
    br = set(list(inspect.signature(Bridge.run).parameters)[1:])
    ctor_ok = lp.issubset(bp)
    run_ok = lr.issubset(br)
    print(f"    생성자: legacy={sorted(lp)}")
    print(f"            bridge⊇legacy? {ctor_ok}  (bridge 추가: {sorted(bp - lp)})")
    print(f"    run()  : legacy={sorted(lr)}  bridge⊇? {run_ok}")
    results["[1] API 패리티"] = ctor_ok and run_ok
    print(f"    → {PASS if results['[1] API 패리티'] else FAIL}")

    # ── [2] side-by-side ────────────────────────────────────────────────────
    print(f"\n[2] side-by-side — 동일 .yaml·동일 인터페이스로 양 백엔드 실행 (max_steps={_MAX_STEPS})")
    print(f"    {'matchup':<22}{'backend':<10}{'winner':<8}{'steps':>6}{'H1':>7}{'H2':>7}")
    sbs_ok = True
    for t1, t2 in _PAIRS:
        for label, cls, kw in (("legacy(.pyd)", Legacy, {}),
                               ("new(LQR)", Bridge, {"controller": "lqr"}),
                               ("new(INDI)", Bridge, {"controller": "indi"})):
            try:
                w, st, h1, h2, _ = _run(cls, t1, t2, **kw)
                print(f"    {t1+' vs '+t2:<22}{label:<10}{w:<8}{st:>6}{h1:>7.1f}{h2:>7.1f}")
            except Exception as e:
                print(f"    {t1+' vs '+t2:<22}{label:<10}ERROR: {type(e).__name__} {str(e)[:40]}")
                sbs_ok = False
    results["[2] 양 백엔드 동일 인터페이스 실행"] = sbs_ok
    print(f"    → {PASS if sbs_ok else FAIL}  (winner/HP 값은 RNN≠LQR 이라 다를 수 있음 — 인터페이스 동일성이 핵심)")

    # ── [3] 드롭인 소비자 패턴 ───────────────────────────────────────────────
    print("\n[3] 드롭인 소비자 — scripts/run_match.py:230 getattr 패턴이 bridge 에 동작")
    w, st, h1, h2, r = _run(Bridge, "ace", "simple", controller="lqr")
    # scripts/run_match.py 그대로
    steps = getattr(r, "steps", getattr(r, "total_steps", "N/A"))
    et = getattr(r, "elapsed_time", getattr(r, "duration_seconds", "N/A"))
    r1 = getattr(r, "tree1_reward", 0.0)
    r2 = getattr(r, "tree2_reward", 0.0)
    winner = getattr(r, "winner", "unknown")
    consumer_ok = (steps != "N/A" and et != "N/A" and winner in ("tree1", "tree2", "draw"))
    print(f"    winner={winner} steps={steps} dur={et:.1f}s reward1={r1:.1f} reward2={r2:.1f}")
    print(f"    (reward=damage_dealt 대용; winner∈{{tree1,tree2,draw}} = legacy 명명 규약)")
    results["[3] 드롭인 소비자 패턴"] = consumer_ok
    print(f"    → {PASS if consumer_ok else FAIL}")

    # ── 종합 ────────────────────────────────────────────────────────────────
    print("\n" + "=" * 78)
    allok = all(results.values())
    for k, v in results.items():
        print(f"  {PASS if v else FAIL}  {k}")
    print("=" * 78)
    print(f"  {'✅ 교환 검증 통과 — bridge 는 legacy core 의 드롭인이며 백엔드는 new_engine' if allok else '❌ 일부 실패'}")
    print("=" * 78)
    return 0 if allok else 1


if __name__ == "__main__":
    sys.exit(main())
