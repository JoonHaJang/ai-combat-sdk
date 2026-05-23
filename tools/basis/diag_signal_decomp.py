"""M1.3 — aggressive misperception 의 책임 부위 (H1/H2/H3) 판정.

SUPERPLAN_v2 §3 Phase 1 M1.3.

입력: `logs/regression/m12/{simple,defensive,aggressive}_n{1,2,3}_ticks.csv`
     (M1.1 의 신규 컬럼 포함: gPN_dist/head, gC_dist/head, gLDT_dist/head, gYoyo_dist/head,
      gT_dist/head, closure_kts, V_e_raw, V_e_clamp, mode)

출력: 표준출력 + `docs/diag/aggressive_signal_decomposition.md`.

판정 기준 (사전 등록, SUPERPLAN_v2 §2):
  H1 (V_dist ω-zero): aggressive 매치의 `dist>8000` tick 에서
       |gPN_dist|/(|gPN_head|+ε) >> 1 *그리고* simple 매치에선 그렇지 않음.
       즉 `aggressive 에서 dist 방향 ∇V 가 강한데 ω 채널로 못 가서 안 닫힘`.
  H2 (V_target sprint 부호 함정): aggressive 매치의 `u_a < 0` 비율 ≫ simple, 그 순간
       V_e_clamp=1 빈도 ↑.
  H3 (dispatcher routing): 분기 점유율에서 aggressive 가 `hybrid:Theorem` ≥ 50%,
       그 안에서 rho_corner > rho_pn.
"""

from __future__ import annotations

import csv
import glob
import math
import os
from collections import Counter
from pathlib import Path


M12_DIR = Path("logs/regression/m12")
OUT_MD = Path("docs/diag/aggressive_signal_decomposition.md")


def _load_match(csv_path: Path) -> list[dict]:
    rows = []
    with open(csv_path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for r in reader:
            rows.append(r)
    return rows


def _to_float(s: str, default: float = 0.0) -> float:
    try:
        return float(s)
    except (ValueError, TypeError):
        return default


def _dist(row: dict) -> float:
    dx = _to_float(row.get("dx", "0"))
    dy = _to_float(row.get("dy", "0"))
    dh = _to_float(row.get("dh", "0"))
    return math.sqrt(dx * dx + dy * dy + dh * dh)


def analyze(opponent: str) -> dict:
    files = sorted(M12_DIR.glob(f"{opponent}_n*_ticks.csv"))
    if not files:
        return {"opponent": opponent, "n_files": 0}

    all_rows = []
    for f in files:
        all_rows.extend(_load_match(f))

    n = len(all_rows)
    if n == 0:
        return {"opponent": opponent, "n_files": len(files), "n_ticks": 0}

    # H1 signal: gPN_dist 와 gPN_head 의 분포 (dist>8000 영역)
    long_range = [r for r in all_rows if _dist(r) > 8000.0]
    medium_range = [r for r in all_rows if 3000.0 <= _dist(r) <= 8000.0]
    short_range = [r for r in all_rows if _dist(r) < 3000.0]

    def _ratio_stats(rows: list[dict]) -> dict:
        if not rows:
            return {"n": 0}
        ratios = []
        dist_mags = []
        head_mags = []
        for r in rows:
            d = abs(_to_float(r.get("gPN_dist", "0")))
            h = _to_float(r.get("gPN_head", "0"))
            dist_mags.append(d)
            head_mags.append(h)
            if h > 1e-12:
                ratios.append(d / h)
        ratios.sort()
        return {
            "n": len(rows),
            "median_dist_to_head": ratios[len(ratios) // 2] if ratios else float("nan"),
            "mean_|gPN_dist|": sum(dist_mags) / len(dist_mags) if dist_mags else 0.0,
            "mean_|gPN_head|": sum(head_mags) / len(head_mags) if head_mags else 0.0,
        }

    h1 = {
        "long_range_>8000ft": _ratio_stats(long_range),
        "medium_range_3000_8000": _ratio_stats(medium_range),
        "short_range_<3000ft": _ratio_stats(short_range),
    }

    # H2 signal: u_a < 0 비율 + V_e_clamp 빈도
    n_acc_neg = sum(1 for r in all_rows if _to_float(r.get("u_a_kts", "0")) < 0)
    n_clamp = sum(1 for r in all_rows if _to_float(r.get("V_e_clamp", "0")) > 0.5)
    n_clamp_and_acc_neg = sum(
        1 for r in all_rows
        if _to_float(r.get("V_e_clamp", "0")) > 0.5 and _to_float(r.get("u_a_kts", "0")) < 0
    )
    h2 = {
        "u_a<0_frac": n_acc_neg / n,
        "V_e_clamp_frac": n_clamp / n,
        "u_a<0_AND_clamp_frac": n_clamp_and_acc_neg / n,
    }

    # H3 signal: 분기 점유율 + 분기 내 τ 평균
    branches = Counter(r.get("mode", "?") for r in all_rows)
    theorem_rows = [r for r in all_rows if r.get("mode", "") == "hybrid:Theorem"]
    if theorem_rows:
        mean_rho_pn = sum(_to_float(r.get("rho_pn", "0")) for r in theorem_rows) / len(theorem_rows)
        mean_rho_corner = sum(_to_float(r.get("rho_corner", "0")) for r in theorem_rows) / len(theorem_rows)
        mean_rho_ldt = sum(_to_float(r.get("rho_ldt", "0")) for r in theorem_rows) / len(theorem_rows)
        mean_rho_yoyo = sum(_to_float(r.get("rho_yoyo", "0")) for r in theorem_rows) / len(theorem_rows)
    else:
        mean_rho_pn = mean_rho_corner = mean_rho_ldt = mean_rho_yoyo = 0.0
    h3 = {
        "branch_occupancy": {k: v / n for k, v in branches.most_common()},
        "theorem_frac": branches.get("hybrid:Theorem", 0) / n,
        "theorem_mean_rho_pn": mean_rho_pn,
        "theorem_mean_rho_corner": mean_rho_corner,
        "theorem_mean_rho_ldt": mean_rho_ldt,
        "theorem_mean_rho_yoyo": mean_rho_yoyo,
    }

    return {
        "opponent": opponent,
        "n_files": len(files),
        "n_ticks": n,
        "H1": h1,
        "H2": h2,
        "H3": h3,
    }


def _fmt_h1(h1: dict) -> str:
    lines = []
    for k, v in h1.items():
        if v.get("n", 0) == 0:
            lines.append(f"  - {k}: (no ticks)")
            continue
        lines.append(
            f"  - {k}: n={v['n']} median|gPN_dist|/|gPN_head|={v['median_dist_to_head']:.3f} "
            f"mean|gPN_dist|={v['mean_|gPN_dist|']:.3e} mean|gPN_head|={v['mean_|gPN_head|']:.3e}"
        )
    return "\n".join(lines)


def _fmt_h3(h3: dict) -> str:
    lines = [f"  - theorem_frac={h3['theorem_frac']:.3f}",
             f"  - theorem mean ρ: pn={h3['theorem_mean_rho_pn']:.3f} "
             f"corner={h3['theorem_mean_rho_corner']:.3f} "
             f"ldt={h3['theorem_mean_rho_ldt']:.3f} "
             f"yoyo={h3['theorem_mean_rho_yoyo']:.3f}",
             "  - branch occupancy:"]
    for b, frac in h3["branch_occupancy"].items():
        lines.append(f"    · {b}: {frac:.3f}")
    return "\n".join(lines)


def _verdict(stats: dict) -> dict:
    """판정 — aggressive vs simple 비교."""
    agg = stats["aggressive"]
    sim = stats["simple"]

    # H1 verdict: aggressive long-range 에서 |gPN_dist|/|gPN_head| 가 simple 보다 *현저히 큼*
    agg_lr = agg["H1"]["long_range_>8000ft"]
    sim_lr = sim["H1"]["long_range_>8000ft"]
    agg_ratio = agg_lr.get("median_dist_to_head", 0.0) if agg_lr.get("n", 0) else 0.0
    sim_ratio = sim_lr.get("median_dist_to_head", 0.0) if sim_lr.get("n", 0) else 0.0
    h1_verdict = "CONFIRMED" if (agg_ratio > 2.0 and agg_ratio > 2.0 * max(sim_ratio, 0.01)) else "WEAK/REJECTED"

    # H2 verdict: aggressive u_a<0 비율 ≫ simple, 그리고 V_e_clamp 활성
    h2_verdict = "CONFIRMED" if (
        agg["H2"]["u_a<0_frac"] > 1.5 * sim["H2"]["u_a<0_frac"] + 0.05
        and agg["H2"]["V_e_clamp_frac"] > 0.20
    ) else "WEAK/REJECTED"

    # H3 verdict: aggressive 의 theorem_frac ≥ 0.5 그리고 ρ_corner > ρ_pn
    h3_verdict = "CONFIRMED" if (
        agg["H3"]["theorem_frac"] >= 0.5
        and agg["H3"]["theorem_mean_rho_corner"] > agg["H3"]["theorem_mean_rho_pn"]
    ) else "WEAK/REJECTED"

    return {"H1": h1_verdict, "H2": h2_verdict, "H3": h3_verdict,
            "agg_long_range_ratio": agg_ratio, "sim_long_range_ratio": sim_ratio}


def main():
    stats = {}
    for opp in ["simple", "defensive", "aggressive"]:
        stats[opp] = analyze(opp)
        s = stats[opp]
        print(f"\n=== {opp} (files={s['n_files']}, ticks={s.get('n_ticks', 0)}) ===")
        if s.get("n_ticks", 0) == 0:
            continue
        print("H1 (∇V_pn dist vs head projection):")
        print(_fmt_h1(s["H1"]))
        print(f"H2 u_a<0 frac={s['H2']['u_a<0_frac']:.3f}  V_e_clamp frac={s['H2']['V_e_clamp_frac']:.3f}  "
              f"AND={s['H2']['u_a<0_AND_clamp_frac']:.3f}")
        print("H3 branch / theorem ρ:")
        print(_fmt_h3(s["H3"]))

    verdict = _verdict(stats)
    print("\n=== VERDICT (aggressive 책임 부위) ===")
    for k, v in verdict.items():
        print(f"  {k}: {v}")

    # Markdown 저장
    OUT_MD.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT_MD, "w", encoding="utf-8") as f:
        f.write("# M1.3 aggressive 책임 부위 분석 — 2026-05-16\n\n")
        f.write("SUPERPLAN_v2 §3 Phase 1 M1.3. 입력: `logs/regression/m12/*_ticks.csv` (n=3 매치 × 3 적).\n\n")
        f.write("## Verdict\n\n")
        f.write("| 가설 | 결과 | 근거 |\n|---|---|---|\n")
        f.write(f"| H1 (V_dist ω-zero, long-range) | **{verdict['H1']}** | "
                f"aggressive median |gPN_dist|/|gPN_head|@>8000ft = {verdict['agg_long_range_ratio']:.3f} "
                f"vs simple = {verdict['sim_long_range_ratio']:.3f} |\n")
        f.write(f"| H2 (V_target 자발 감속) | **{verdict['H2']}** | "
                f"agg u_a<0 frac = {stats['aggressive']['H2']['u_a<0_frac']:.3f} "
                f"vs sim = {stats['simple']['H2']['u_a<0_frac']:.3f}, "
                f"agg V_e_clamp = {stats['aggressive']['H2']['V_e_clamp_frac']:.3f} |\n")
        f.write(f"| H3 (dispatcher routing) | **{verdict['H3']}** | "
                f"agg theorem_frac = {stats['aggressive']['H3']['theorem_frac']:.3f}, "
                f"theorem ρ_corner={stats['aggressive']['H3']['theorem_mean_rho_corner']:.3f} "
                f"vs ρ_pn={stats['aggressive']['H3']['theorem_mean_rho_pn']:.3f} |\n")
        f.write("\n## 상세\n\n")
        for opp in ["simple", "defensive", "aggressive"]:
            s = stats[opp]
            f.write(f"### {opp} (n={s.get('n_ticks', 0)} ticks across {s['n_files']} matches)\n\n")
            if s.get("n_ticks", 0) == 0:
                f.write("(no data)\n\n")
                continue
            f.write("**H1 — ∇V_pn 의 LOS-radial vs LOS-tangential 분해 (range bucket 별)**:\n\n")
            f.write("```\n" + _fmt_h1(s["H1"]) + "\n```\n\n")
            f.write(f"**H2** — `u_a<0` frac = {s['H2']['u_a<0_frac']:.3f}, "
                    f"`V_e_clamp` frac = {s['H2']['V_e_clamp_frac']:.3f}, "
                    f"intersection = {s['H2']['u_a<0_AND_clamp_frac']:.3f}\n\n")
            f.write("**H3 — 분기 점유 + Theorem 안 ρ 평균**:\n\n")
            f.write("```\n" + _fmt_h3(s["H3"]) + "\n```\n\n")
        f.write("\n*Phase 2 진입* — confirmed 가설의 수리적 재유도 작업 (SUPERPLAN_v2 §3 Phase 2 A/B).\n")

    print(f"\n→ wrote {OUT_MD}")


if __name__ == "__main__":
    main()
