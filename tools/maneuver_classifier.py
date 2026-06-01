"""매 tick 적 maneuver mode 분류 (2026-06-01).

사용자 통찰: 1-circle / 2-circle / 직진 / 도망 등 BFM mode 를 데이터로 사전 예측 가능.
선회반경 R = V / omega + 선회율 omega + 거리 변화 등 derived metrics 활용.

Modes:
  STRAIGHT_RUN — 적 omega < 2°/s + dist 증가 (도주)
  ONE_CIRCLE   — 적/우리 omega 반대 부호 (mirror turn, radius fight)
  TWO_CIRCLE   — 적/우리 omega 같은 부호 (rate fight)
  LOOSE_TURN   — 적 omega 2-5°/s
  TIGHT_TURN   — 적 omega > 5°/s, 우리는 미정
  SCISSORS     — 적 omega 부호 frequent change

usage:
    python tools/maneuver_classifier.py <meta_csv>
"""
from __future__ import annotations
import sys, csv, glob
from collections import Counter
from pathlib import Path


def to_float(v, default=0.0):
    try: return float(v)
    except: return default


def deg(v): return to_float(v) / 180.0


def classify_maneuver(window):
    """window = list of N step dicts. Returns mode string + derived metrics dict."""
    if len(window) < 10:
        return "UNKNOWN", {}
    # opp aa 변화율 → opp omega
    opp_aas = [deg(r["aa_deg"]) for r in window]
    opp_omega = (opp_aas[-1] - opp_aas[0]) / (len(opp_aas) * 0.1)   # deg/s (env step 0.05s × 10 = 1s for 10 steps)

    # rel_b 변화율 → 우리 omega proxy
    rbs = [deg(r["relative_bearing_deg"]) for r in window]
    us_omega = (rbs[-1] - rbs[0]) / (len(rbs) * 0.1)

    # dist 변화율
    dists = [to_float(r["distance_ft"]) for r in window]
    d_dist = dists[-1] - dists[0]
    dist_now = dists[-1]

    # opp vc proxy
    us_vc = to_float(window[-1]["ego_vc_kts"])
    closure = to_float(window[-1]["closure_rate_kts"])
    opp_vc = max(100.0, us_vc - closure)
    # 선회반경 R = V / omega (ft). V = kts × 1.688 ft/s, omega = deg/s × π/180 rad/s
    if abs(opp_omega) > 0.1:
        opp_R = (opp_vc * 1.688) / (abs(opp_omega) * 3.14159 / 180.0)
    else:
        opp_R = 999999.0

    # 분류
    if abs(opp_omega) < 2.0:
        mode = "STRAIGHT_RUN" if d_dist > 500 else "STRAIGHT_HOLD"
    elif abs(opp_omega) > 5.0:
        if abs(us_omega) > 5.0:
            sign_us = 1 if us_omega > 0 else -1
            sign_op = 1 if opp_omega > 0 else -1
            if sign_us * sign_op < 0:
                mode = "ONE_CIRCLE"
            else:
                mode = "TWO_CIRCLE"
        else:
            mode = "TIGHT_TURN"
    else:
        mode = "LOOSE_TURN"

    return mode, {
        "opp_omega": opp_omega, "us_omega": us_omega,
        "opp_R_ft": opp_R, "opp_vc": opp_vc,
        "d_dist": d_dist, "dist": dist_now,
    }


def analyze(path):
    with open(path) as f:
        rows = list(csv.DictReader(f))
    us = [r for r in rows if r["tree_name"] == "pursuit_chase_btcost"]
    opp = [r for r in rows if r["tree_name"] != "pursuit_chase_btcost"]
    name = Path(path).stem.split("_vs_")[-1].replace("_meta", "")

    print(f"\n{'='*80}\n {name}  ({len(opp)} ticks)\n{'='*80}")
    print(f"\n매 30 env step 적 maneuver 분류:")
    print(f"{'step':>5} | {'mode':<14} | {'opp_om':>7} | {'us_om':>7} | {'opp_R':>7} | {'opp_vc':>6} | {'dist':>5}")
    mode_seq = []
    for i in range(20, len(opp), 30):
        window = opp[max(0, i-10):i]
        mode, metrics = classify_maneuver(window)
        mode_seq.append(mode)
        if i % 60 == 20:   # 매 60 step (3초) 출력
            print(f"  {i:>4d} | {mode:<14s} | {metrics.get('opp_omega', 0):>+6.1f}° | "
                  f"{metrics.get('us_omega', 0):>+6.1f}° | {metrics.get('opp_R_ft', 0):>5.0f}f | "
                  f"{metrics.get('opp_vc', 0):>4.0f}k | {metrics.get('dist', 0):>5.0f}")
    print(f"\n총 mode 분포 (매 30 step sample):")
    for m, c in Counter(mode_seq).most_common():
        print(f"  {c:4d}  {m}")


if __name__ == "__main__":
    paths = []
    for p in sys.argv[1:]:
        paths.extend(sorted(glob.glob(p)))
    if not paths:
        print("usage: python maneuver_classifier.py <meta_csv> [...]")
        sys.exit(1)
    for p in paths:
        analyze(p)
