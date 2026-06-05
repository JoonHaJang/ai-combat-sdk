"""GA fuzz log mining: knob → per-opp outcome hypothesis extraction.

GA가 생성한 logs/fuzz_genetic/gen_*.json 을 묶어:
  1. **Per-knob × per-opp Spearman correlation** — 어떤 knob을 올리면 어떤 opp의 dmg가 변하는가
  2. **Win-cluster knob signature** — 특정 opp을 hit 한 variants vs miss 한 variants 의 knob 평균/std
  3. **Trade-off pairs** — knob A 증가 시 opp X 증가 + opp Y 감소 (동시 가능?)
  4. **Recommended per-opp settings** — opp 별 best variant 의 knob 통계

출력:
  logs/knowledge/ga_hypotheses.json  — JSON 구조화 결과
  stdout — human-readable summary

사용자 요청 (2026-05-28): GA 결과 기반 가정/전술 mining → lookup table → cost_branch_selector.py 수정 → 더 큰 GA round.
"""
import json
import statistics
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GA_DIR = ROOT / "logs/fuzz_genetic"
OUT_PATH = ROOT / "logs/knowledge/ga_hypotheses.json"

KNOBS = ["STUCK_THR", "STUCK_MAX", "LAMBDA_D", "LAMBDA_OFFENSIVE", "LAMBDA_CUTOFF",
         "LAMBDA_BREAK", "LAMBDA_HIGHYOYO", "LAMBDA_DIVE", "LAMBDA_TCV", "LAMBDA_EXT"]


def load_all_variants() -> list[dict]:
    """모든 gen_*.json 에서 (variant, detail) 추출."""
    rows = []
    for gf in sorted(GA_DIR.glob("gen_*.json")):
        d = json.load(open(gf, encoding="utf-8"))
        for e in d["all"]:
            rows.append({"src": gf.name, "variant": e["variant"],
                         "score": e["score"], "detail": e["detail"]})
    return rows


def spearman(xs: list, ys: list) -> float:
    """Spearman rank correlation."""
    n = len(xs)
    if n < 3:
        return 0.0
    def ranks(vals):
        srt = sorted(range(n), key=lambda i: vals[i])
        r = [0.0] * n
        for i, idx in enumerate(srt):
            r[idx] = i + 1
        return r
    rx, ry = ranks(xs), ranks(ys)
    mx = sum(rx) / n
    my = sum(ry) / n
    num = sum((rx[i]-mx)*(ry[i]-my) for i in range(n))
    den_x = sum((rx[i]-mx)**2 for i in range(n)) ** 0.5
    den_y = sum((ry[i]-my)**2 for i in range(n)) ** 0.5
    return num / (den_x * den_y) if den_x*den_y else 0.0


def per_knob_per_opp_correlation(rows: list[dict]) -> dict:
    """각 (knob, opp_cell) 쌍의 Spearman 상관."""
    # cell 별 row 필터 (R1/R2/R3 cell이 달라서 None 무시)
    out = {}
    all_cells = set()
    for r in rows:
        all_cells.update(r["detail"].keys())
    for cell in sorted(all_cells):
        cell_rows = [r for r in rows if cell in r["detail"]]
        if len(cell_rows) < 6:
            continue
        ys = [r["detail"][cell] for r in cell_rows]
        cell_corr = {}
        for k in KNOBS:
            xs = [r["variant"][k] for r in cell_rows]
            cell_corr[k] = round(spearman(xs, ys), 3)
        out[cell] = {"n": len(cell_rows), "corr": cell_corr}
    return out


def win_cluster_signature(rows: list[dict], dmg_threshold: float = 15.0) -> dict:
    """각 opp_cell 에서 dmg >= threshold (hit) vs < threshold (miss) variants 의 knob mean."""
    out = {}
    all_cells = set()
    for r in rows:
        all_cells.update(r["detail"].keys())
    for cell in sorted(all_cells):
        hits = [r for r in rows if r["detail"].get(cell, 0) >= dmg_threshold]
        misses = [r for r in rows if 0 < r["detail"].get(cell, 0) < dmg_threshold]
        zeros = [r for r in rows if r["detail"].get(cell, -1) == 0]
        if len(hits) < 3:
            continue
        hit_stats = {}
        miss_stats = {}
        for k in KNOBS:
            h = [r["variant"][k] for r in hits]
            m = [r["variant"][k] for r in misses + zeros] if (misses or zeros) else []
            hit_stats[k] = {
                "mean": round(statistics.mean(h), 2),
                "std": round(statistics.stdev(h), 2) if len(h) > 1 else 0,
                "n": len(h),
            }
            if m:
                miss_stats[k] = {
                    "mean": round(statistics.mean(m), 2),
                    "std": round(statistics.stdev(m), 2) if len(m) > 1 else 0,
                    "n": len(m),
                }
        # which knobs differ most (Cohen's d)
        diff_score = {}
        for k in KNOBS:
            if k in miss_stats:
                pooled_std = ((hit_stats[k]["std"]**2 + miss_stats[k]["std"]**2)/2)**0.5
                if pooled_std > 0:
                    d = (hit_stats[k]["mean"] - miss_stats[k]["mean"]) / pooled_std
                    diff_score[k] = round(d, 2)
        out[cell] = {
            "n_hits": len(hits),
            "n_misses_or_zeros": len(misses) + len(zeros),
            "hit_knobs": hit_stats,
            "miss_knobs": miss_stats,
            "discriminating_knobs": dict(sorted(diff_score.items(),
                                                key=lambda x: -abs(x[1]))[:5]),
        }
    return out


def find_tradeoff_pairs(corr: dict, min_abs: float = 0.4) -> list[dict]:
    """동일 knob 이 opp A correlation > +0.4 AND opp B correlation < -0.4 인 쌍."""
    cells = list(corr.keys())
    pairs = []
    for k in KNOBS:
        positives = [(c, corr[c]["corr"][k]) for c in cells if corr[c]["corr"][k] > min_abs]
        negatives = [(c, corr[c]["corr"][k]) for c in cells if corr[c]["corr"][k] < -min_abs]
        for p, pcor in positives:
            for n, ncor in negatives:
                pairs.append({"knob": k, "boost_cell": p, "boost_corr": pcor,
                              "hurt_cell": n, "hurt_corr": ncor,
                              "tension": round(pcor - ncor, 2)})
    pairs.sort(key=lambda x: -x["tension"])
    return pairs[:20]


def best_per_opp(rows: list[dict]) -> dict:
    """각 opp (cells 합산) 에서 best dmg variant 의 knob."""
    out = {}
    opps = set()
    for r in rows:
        for cell in r["detail"]:
            opps.add(cell.split("@")[0])
    for opp in sorted(opps):
        # sum across scenarios for this opp
        scored = []
        for r in rows:
            opp_cells = [v for k, v in r["detail"].items() if k.startswith(opp + "@")]
            if opp_cells:
                scored.append({"total": sum(opp_cells), "row": r})
        scored.sort(key=lambda x: -x["total"])
        if scored and scored[0]["total"] > 0:
            top3 = scored[:3]
            knob_mean = {k: round(statistics.mean(
                [s["row"]["variant"][k] for s in top3]), 2) for k in KNOBS}
            out[opp] = {
                "top1_dmg": round(scored[0]["total"], 1),
                "top1_variant": scored[0]["row"]["variant"],
                "top3_knob_mean": knob_mean,
                "n_engaged_variants": sum(1 for s in scored if s["total"] > 0),
            }
    return out


def main():
    rows = load_all_variants()
    print(f"=== Loaded {len(rows)} variants from {GA_DIR} ===\n")

    print("=== 1. Per-knob × per-opp Spearman correlation (|corr| >= 0.3) ===")
    corr = per_knob_per_opp_correlation(rows)
    for cell in sorted(corr.keys()):
        strong = {k: v for k, v in corr[cell]["corr"].items() if abs(v) >= 0.3}
        if strong:
            print(f"  {cell:>40s} (n={corr[cell]['n']:>2}):")
            for k, v in sorted(strong.items(), key=lambda x: -abs(x[1])):
                arrow = "↑" if v > 0 else "↓"
                print(f"    {k:>18s} {arrow} corr={v:+.2f}")

    print("\n=== 2. Win-cluster discriminating knobs (Cohen's d, dmg>=15) ===")
    sig = win_cluster_signature(rows)
    for cell in sorted(sig.keys()):
        s = sig[cell]
        if s["n_hits"] < 3 or not s["discriminating_knobs"]:
            continue
        print(f"  {cell:>40s} (hits={s['n_hits']}, misses={s['n_misses_or_zeros']}):")
        for k, d in s["discriminating_knobs"].items():
            if abs(d) >= 0.5:
                hit_m = s["hit_knobs"][k]["mean"]
                miss_m = s["miss_knobs"].get(k, {}).get("mean", "-")
                print(f"    {k:>18s}  hits={hit_m:>6}  miss={miss_m:>6}  d={d:+.2f}")

    print("\n=== 3. Trade-off pairs (same knob: opp A↑ & opp B↓ both >|0.4|) ===")
    pairs = find_tradeoff_pairs(corr)
    for p in pairs[:10]:
        print(f"  {p['knob']:>18s}: +{p['boost_cell']:>30s} ({p['boost_corr']:+.2f}) "
              f"| -{p['hurt_cell']:>30s} ({p['hurt_corr']:+.2f})  tension={p['tension']}")

    print("\n=== 4. Best variant per opponent (top-1 + top-3 knob mean) ===")
    bests = best_per_opp(rows)
    for opp, b in sorted(bests.items(), key=lambda x: -x[1]["top1_dmg"]):
        print(f"  {opp:>30s}: top1_dmg={b['top1_dmg']:>6.1f}  "
              f"engaged={b['n_engaged_variants']:>2}/{len(rows)}")
        if b["top1_dmg"] >= 10:
            knobs_str = "  ".join(f"{k}={v}" for k, v in b["top3_knob_mean"].items())
            print(f"    top3 mean: {knobs_str}")

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps({
        "n_variants": len(rows),
        "knobs": KNOBS,
        "correlation": corr,
        "win_cluster_signature": sig,
        "tradeoff_pairs": pairs,
        "best_per_opp": bests,
    }, indent=2, ensure_ascii=False))
    print(f"\nSaved: {OUT_PATH}")


if __name__ == "__main__":
    main()
