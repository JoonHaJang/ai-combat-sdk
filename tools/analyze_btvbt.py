"""R15-H2 (2026-05-29): bt_vs_bt 매치 약점 분석 + 패턴 그룹화.

각 매치 CSV → 매치 단위 metrics + tick-by-tick 분석 → pattern grouping.

매치 단위 metrics:
  - peak_closure_tick, peak_closure_kts
  - min_dist_tick, min_dist_ft
  - wez_us_count: 우리가 WEZ 안에 있는 tick 수 (ata<12 + 500<dist<3000)
  - wez_opp_count: 적이 우리 잡은 tick 수
  - sub_situation 시간 점유율
  - chosen branch 시간 점유율
  - critical_window: dist<2000 + closure>0 인 구간

pattern grouping:
  - WIN (우리 WEZ_us_count > 0) → SHOOTABLE
  - DRAW + closure 음수 우세 → MUTUAL_EXTEND
  - DRAW + closure 양수 우세 (가까운 dist) → MUTUAL_LUFBERY
  - DRAW + closure ~0 → STALEMATE_MERGE
"""
import csv
import sys
from pathlib import Path
from collections import Counter


def parse_csv(path: Path) -> list[dict]:
    rows = []
    with open(path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            try:
                row["tick"] = int(row["tick"])
                row["dist"] = float(row["dist"])
                row["closure"] = float(row["closure"])
                row["ata"] = float(row["ata"])
                row["aa"] = float(row["aa"])
                row["pos_adv"] = float(row["pos_adv"])
                row["alt_b"] = int(row["alt_b"]) if row["alt_b"] else -1
                row["hdg_b"] = int(row["hdg_b"]) if row["hdg_b"] else -1
                row["vel_b"] = int(row["vel_b"]) if row["vel_b"] else -1
            except (ValueError, KeyError):
                continue
            rows.append(row)
    return rows


def analyze_match(opp: str, csv_path: Path) -> dict:
    rows = parse_csv(csv_path)
    if not rows:
        return {"opp": opp, "ticks": 0, "error": "empty"}

    n = len(rows)
    branches = Counter(r["chosen"] for r in rows)
    sub_situations = Counter(
        r["chosen"].replace("SUB_", "") for r in rows if r["chosen"].startswith("SUB_")
    )

    # closure / dist 통계
    closures = [r["closure"] for r in rows]
    dists = [r["dist"] for r in rows]
    peak_closure = max(closures)
    peak_closure_tick = closures.index(peak_closure)
    min_dist = min(dists)
    min_dist_tick = dists.index(min_dist)

    # WEZ 관련 — 우리 측 (ata 작고 dist 적정)
    wez_us = sum(1 for r in rows if r["ata"] < 12 and 500 < r["dist"] < 3000)
    # 우리가 잡을 뻔 (ata 30 안 + WEZ 거리)
    near_wez_us = sum(1 for r in rows if r["ata"] < 30 and 500 < r["dist"] < 3000)
    # 우리가 잡혔던 적이 우리 6시 + 거리 짧음 (적 ata < 12 추정용 = 우리 aa < 12 in 6시 convention)
    # 코드에서 aa < 12 = 적이 우리 6시 - 적 nose 우리 향함 의미
    wez_opp = sum(1 for r in rows if r["aa"] < 12 and 500 < r["dist"] < 3000)

    # critical window: dist < 2000 + closure 양수 (접근 중)
    critical = [r for r in rows if r["dist"] < 2000 and r["closure"] > 0]

    # 평균 dist / closure
    avg_dist = sum(dists) / n
    avg_closure = sum(closures) / n

    # 행동 시간 점유 (vel=4 max throttle 사용 비율)
    max_thr = sum(1 for r in rows if r["vel_b"] == 4) / max(1, n)
    decel = sum(1 for r in rows if r["vel_b"] in (0, 1)) / max(1, n)
    hard_turn = sum(1 for r in rows if r["hdg_b"] in (0, 8)) / max(1, n)

    return {
        "opp": opp,
        "ticks": n,
        "branches": dict(branches.most_common(6)),
        "sub_situations": dict(sub_situations),
        "peak_closure_kts": peak_closure,
        "peak_closure_tick": peak_closure_tick,
        "min_dist_ft": min_dist,
        "min_dist_tick": min_dist_tick,
        "wez_us_count": wez_us,
        "near_wez_us_count": near_wez_us,
        "wez_opp_count": wez_opp,
        "critical_ticks": len(critical),
        "avg_dist": avg_dist,
        "avg_closure": avg_closure,
        "max_throttle_pct": round(max_thr * 100, 1),
        "decel_pct": round(decel * 100, 1),
        "hard_turn_pct": round(hard_turn * 100, 1),
    }


def classify_pattern(m: dict, dmg_dealt: float, dmg_taken: float) -> str:
    """Match pattern 분류."""
    if dmg_dealt > 10:
        return "SHOOTABLE"
    if dmg_dealt > 0:
        return "TINY_WIN"
    if dmg_taken > 10:
        return "BEAT_BY_OPP"
    # 모든 stalemate
    if m["wez_us_count"] > 0:
        return "WEZ_TOUCHED_NO_DMG"
    if m["avg_closure"] < -100:
        return "MUTUAL_EXTEND"
    if m["min_dist_ft"] < 2500 and m["critical_ticks"] > 20:
        return "MUTUAL_LUFBERY"
    return "STALEMATE_MERGE"


def main():
    log_dir = Path("logs/r15_btvbt")
    # damage data (last run)
    dmg_results = {
        "simple": (2.8, 0), "defensive": (0, 0), "aggressive": (0, 0), "ace": (20.9, 0),
        "adaptive_eagle_v6": (0, 0), "adaptive_eagle_v6h2": (0, 0), "adaptive_eagle_v6h4": (0, 0),
        "adaptive_eagle_v6h5a": (0, 0), "adaptive_eagle_v6h5b": (0.1, 0), "adaptive_eagle_v6h5c": (0, 0),
        "adaptive_eagle_v6h_e1": (0, 0), "adaptive_eagle_v6h_e1b": (0, 0),
        "adaptive_eagle_v6h_e1c": (0, 0), "adaptive_eagle_v6h_e1d": (0, 0),
        "adaptive_eagle_v7": (0, 0), "adaptive_eagle_v8": (0, 0),
        "adaptive_eagle_v9": (0, 0), "adaptive_eagle_v10": (0, 0),
        "adaptive_eagle_v11_code": (0, 0), "adaptive_eagle_v51": (0, 0),
    }

    analyses = []
    for opp in dmg_results:
        csv_path = log_dir / f"{opp}.csv"
        if not csv_path.exists():
            print(f"SKIP {opp}: no CSV")
            continue
        m = analyze_match(opp, csv_path)
        dmg_d, dmg_t = dmg_results[opp]
        m["dmg_dealt"] = dmg_d
        m["dmg_taken"] = dmg_t
        m["pattern"] = classify_pattern(m, dmg_d, dmg_t)
        analyses.append(m)

    # 패턴별 그룹화
    by_pattern = {}
    for a in analyses:
        by_pattern.setdefault(a["pattern"], []).append(a)

    print("\n=== R15-H2 bt_vs_bt 매치 분석 ===")
    print(f"{'opp':<22} {'pat':<22} {'minD':>5} {'maxCl':>6} {'wezUS':>5} {'avgCl':>6} {'thr%':>5} {'turn%':>5} {'top_subSit'}")
    for p in sorted(by_pattern.keys()):
        print(f"\n--- {p} ({len(by_pattern[p])} opps) ---")
        for a in by_pattern[p]:
            top_sub = max(a["sub_situations"].items(), key=lambda x: x[1])[0] if a["sub_situations"] else "-"
            sub_pct = (
                f"{top_sub}/{a['sub_situations'].get(top_sub, 0)}"
                if top_sub != "-"
                else "-"
            )
            print(
                f"{a['opp']:<22} {a['pattern']:<22} "
                f"{a['min_dist_ft']:>5.0f} {a['peak_closure_kts']:>6.0f} "
                f"{a['wez_us_count']:>5} {a['avg_closure']:>6.0f} "
                f"{a['max_throttle_pct']:>5} {a['hard_turn_pct']:>5} "
                f"{sub_pct}"
            )

    print("\n=== 추가 통계 ===")
    pattern_counts = {p: len(by_pattern[p]) for p in by_pattern}
    print(f"패턴 분포: {pattern_counts}")
    avg_branches = Counter()
    for a in analyses:
        for b, c in a["branches"].items():
            avg_branches[b] += c
    print(f"\n전체 branch 사용 (모든 매치 합계 top 10):")
    for b, c in avg_branches.most_common(10):
        print(f"  {b:<24} {c}")


if __name__ == "__main__":
    main()
