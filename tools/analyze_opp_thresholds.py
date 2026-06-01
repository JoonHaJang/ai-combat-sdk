"""적 관측값 → 임계값 도출 도구 (2026-05-31).

사용자 framework A: 하드코딩된 임계값(closure>-50, dist<6000, OFFP_FAR_DIST=7000 등)을
적 관측값 분포에서 도출. 매치 metadata CSV → opp_vc/omega_opp/R_opp/closure 시계열 통계.

usage:
    python tools/analyze_opp_thresholds.py logs/metadata/*aggressive*.csv
        → AGG 특성 통계 + 권장 임계값
"""
from __future__ import annotations
import sys, csv, glob, statistics
from pathlib import Path


def load(path):
    with open(path) as f:
        return list(csv.DictReader(f))


def split(rows, our_name="pursuit_chase_btcost"):
    us = [r for r in rows if r["tree_name"] == our_name]
    opp = [r for r in rows if r["tree_name"] != our_name]
    return us, opp


def to_float(v, default=0.0):
    try: return float(v)
    except: return default


def angle_deg(v): return to_float(v) / 180.0   # metadata logger × 180


def stats(values, label, unit=""):
    if not values: return f"{label}: (no data)"
    v = sorted(values)
    n = len(v)
    return (f"{label:20s} n={n:4d} "
            f"min={v[0]:7.1f}{unit} "
            f"p10={v[int(n*0.10)]:7.1f}{unit} "
            f"p50={v[n//2]:7.1f}{unit} "
            f"p90={v[int(n*0.90)]:7.1f}{unit} "
            f"max={v[-1]:7.1f}{unit} "
            f"mean={statistics.mean(v):7.1f}{unit}")


def phase(s):
    s = int(s)
    if s < 30:  return "A spawn 0-30"
    if s < 100: return "B 30-100"
    if s < 300: return "C 100-300"
    if s < 800: return "D 300-800"
    return "E 800+"


def analyze(path):
    rows = load(path)
    us, opp = split(rows)
    name = Path(path).stem.replace("_meta", "").split("_vs_")[-1]
    print(f"\n{'='*70}\n {name}  ({len(us)} ticks)\n{'='*70}")

    # 1. 적 절대 능력 (opp vel, opp omega/turn rate 추정, opp alt)
    opp_vc = [to_float(r["ego_vc_kts"]) for r in opp]
    opp_alt = [to_float(r["ego_altitude_ft"]) for r in opp]
    # opp omega 추정 — opp aa 변화량
    opp_aa = [angle_deg(r["aa_deg"]) for r in opp]
    opp_omega_proxy = [abs(opp_aa[i] - opp_aa[i-1]) * 10.0  # rad/tick → deg/s @10Hz
                       for i in range(1, len(opp_aa))]
    # turn radius proxy: V² / (g·tan(roll)). roll 없으니 V만으로 fairly rough
    # R_opp = V^2 / (g * tan(roll)). roll 정보가 있나?
    opp_roll = [abs(to_float(r["roll_deg"]) / 180.0) for r in opp]

    print(stats(opp_vc, "opp velocity", "kt"))
    print(stats(opp_alt, "opp altitude", "ft"))
    print(stats(opp_omega_proxy, "opp |omega|", "°/s"))
    print(stats(opp_roll, "opp |roll|", "°"))

    # 2. 상대 관측값 — 우리 vs 적
    closure = [to_float(r["closure_rate_kts"]) for r in us]
    dist = [to_float(r["distance_ft"]) for r in us]
    ata = [angle_deg(r["ata_deg"]) for r in us]
    aa = [angle_deg(r["aa_deg"]) for r in us]
    hca = [angle_deg(r["hca_deg"]) for r in us]
    print()
    print(stats(closure, "closure", "kt"))
    print(stats(dist, "distance", "ft"))
    print(stats(ata, "ata", "°"))
    print(stats(aa, "aa", "°"))
    print(stats(hca, "hca", "°"))

    # 3. Phase 별 핵심 변수 — closure 변화 패턴이 적 분류 key
    print("\n--- 적 도주 시그니처 (phase 별) ---")
    for p in ["A spawn 0-30", "B 30-100", "C 100-300", "D 300-800", "E 800+"]:
        idx = [i for i, r in enumerate(us) if phase(r["step"]) == p]
        if not idx: continue
        c = [closure[i] for i in idx]
        d = [dist[i] for i in idx]
        ov = [opp_vc[i] for i in idx]
        # 핵심 적-분류 시그널: closure mean (도주 적은 매우 음수), opp vel (도주 적은 가속)
        print(f"  {p:18s} closure_mean={statistics.mean(c):7.1f} "
              f"closure_p10={sorted(c)[int(len(c)*0.10)]:7.1f} "
              f"dist_mean={statistics.mean(d):6.0f} "
              f"opp_vc_mean={statistics.mean(ov):4.0f} ")

    # 4. 결과 시그니처 — 우리 dmg, 적 hp
    final_us_hp = to_float(us[-1]["ego_health"])
    final_opp_hp = to_float(opp[-1]["ego_health"])
    print(f"\nFINAL: us_HP={final_us_hp:.0f} opp_HP={final_opp_hp:.0f}")


if __name__ == "__main__":
    paths = []
    for pattern in sys.argv[1:]:
        paths.extend(sorted(glob.glob(pattern)))
    if not paths:
        print("usage: python analyze_opp_thresholds.py <glob1> [glob2] ...")
        sys.exit(1)
    for p in paths:
        analyze(p)
