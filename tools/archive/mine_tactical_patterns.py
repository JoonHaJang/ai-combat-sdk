"""Mine tactical patterns from match metadata.

Aggregates per (opponent, state_bin, active_node) tick-level outcomes
across all BTs to compute state-conditional win rates and Δobs stats.

Usage:
    python tools/mine_tactical_patterns.py \
        --matches logs/matches/all_eagles_vs_agg_def \
        --out logs/knowledge/tactical_patterns_v2.json
"""
import argparse
import csv
import json
import re
from collections import defaultdict
from pathlib import Path


def bin_ata(a):  return min(int(max(a, 0) // 30), 5)
def bin_dist(d):
    for i, th in enumerate([1000, 3000, 6000, 10000]):
        if d < th:
            return i
    return 4
def bin_closure(c):
    for i, th in enumerate([-100, 0, 100]):
        if c < th:
            return i
    return 3
def bin_e(e):
    for i, th in enumerate([-3000, 0, 3000]):
        if e < th:
            return i
    return 3


STATE_LABELS = {
    "ata": ["0-30", "30-60", "60-90", "90-120", "120-150", "150-180"],
    "dist": ["<1k", "1-3k", "3-6k", "6-10k", ">10k"],
    "closure": ["<-100", "-100-0", "0-100", ">100"],
    "e_diff": ["<-3k", "-3k-0", "0-3k", ">3k"],
}


FNAME_PAT = re.compile(
    r"\d{8}_\d{6}_(.+?)_vs_(aggressive|defensive)_round(\d+)"
)


def parse_outcomes(match_dir: Path):
    outcomes = {}
    for jp in match_dir.glob("*_result.json"):
        m = FNAME_PAT.match(jp.stem)
        if not m:
            continue
        bt, opp, _ = m.groups()
        d = json.load(open(jp, encoding="utf-8"))
        hp1, hp2 = d.get("tree1_hp", 0), d.get("tree2_hp", 0)
        winner = (d.get("winner") or "").lower()
        if "tree1" in winner or bt == winner:
            oc = "W"
        elif "tree2" in winner or opp == winner:
            oc = "L"
        else:
            if hp1 == hp2:
                oc = "D"
            else:
                oc = "W" if hp1 > hp2 else "L"
        key = jp.stem.replace("_meta_result", "_meta")
        outcomes[key] = (bt, opp, oc, hp1, hp2)
    return outcomes


def aggregate(match_dir: Path, outcomes: dict):
    agg = defaultdict(lambda: {
        "W_ticks": 0, "L_ticks": 0, "D_ticks": 0,
        "W_BTs": set(), "L_BTs": set(),
        "d_dist_W": [], "d_dist_L": [],
        "d_ata_W": [], "d_ata_L": [],
        "d_closure_W": [], "d_closure_L": [],
        "d_e_W": [], "d_e_L": [],
    })
    parsed = 0
    for cp in match_dir.glob("*_meta.csv"):
        key = cp.stem
        if key not in outcomes:
            continue
        bt, opp, oc, _, _ = outcomes[key]
        prev = None
        with open(cp, encoding="utf-8") as f:
            for row in csv.DictReader(f):
                if not row.get("agent_id", "").startswith("A"):
                    continue
                try:
                    ata = float(row["ata_deg"])
                    dist = float(row["distance_ft"])
                    clos = float(row["closure_rate_kts"])
                    ediff = float(row["energy_diff_ft"])
                    node = row.get("active_node", "?") or "?"
                except (ValueError, KeyError):
                    continue
                state = (bin_ata(ata), bin_dist(dist),
                         bin_closure(clos), bin_e(ediff))
                if prev is not None:
                    dd = dist - prev[1]
                    da = ata - prev[0]
                    dc = clos - prev[2]
                    de = ediff - prev[3]
                    e = agg[(opp, state, node)]
                    if oc == "W":
                        e["W_ticks"] += 1
                        e["W_BTs"].add(bt)
                        e["d_dist_W"].append(dd); e["d_ata_W"].append(da)
                        e["d_closure_W"].append(dc); e["d_e_W"].append(de)
                    elif oc == "L":
                        e["L_ticks"] += 1
                        e["L_BTs"].add(bt)
                        e["d_dist_L"].append(dd); e["d_ata_L"].append(da)
                        e["d_closure_L"].append(dc); e["d_e_L"].append(de)
                    else:
                        e["D_ticks"] += 1
                prev = (ata, dist, clos, ediff, state, node)
        parsed += 1
    return agg, parsed


def safe_avg(xs):
    return sum(xs) / len(xs) if xs else 0.0


def build_records(agg, min_ticks=20):
    records = []
    for (opp, state, node), e in agg.items():
        tot = e["W_ticks"] + e["L_ticks"] + e["D_ticks"]
        if tot < min_ticks:
            continue
        wl = e["W_ticks"] + e["L_ticks"]
        wr = e["W_ticks"] / wl if wl > 0 else None
        records.append({
            "opp": opp,
            "state": {
                "ata": STATE_LABELS["ata"][state[0]],
                "dist": STATE_LABELS["dist"][state[1]],
                "closure": STATE_LABELS["closure"][state[2]],
                "e_diff": STATE_LABELS["e_diff"][state[3]],
            },
            "state_key": list(state),
            "node": node,
            "n_W": e["W_ticks"], "n_L": e["L_ticks"], "n_D": e["D_ticks"],
            "win_rate": round(wr, 3) if wr is not None else None,
            "W_BTs": sorted(e["W_BTs"]),
            "L_BTs": sorted(e["L_BTs"]),
            "d_dist_W": round(safe_avg(e["d_dist_W"]), 2),
            "d_dist_L": round(safe_avg(e["d_dist_L"]), 2),
            "d_ata_W": round(safe_avg(e["d_ata_W"]), 3),
            "d_ata_L": round(safe_avg(e["d_ata_L"]), 3),
            "d_closure_W": round(safe_avg(e["d_closure_W"]), 2),
            "d_closure_L": round(safe_avg(e["d_closure_L"]), 2),
            "d_e_W": round(safe_avg(e["d_e_W"]), 1),
            "d_e_L": round(safe_avg(e["d_e_L"]), 1),
        })
    return records


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--matches", required=True, action="append",
                    help="Match directory. Can be repeated to combine multiple sources.")
    ap.add_argument("--out", required=True)
    ap.add_argument("--min-ticks", type=int, default=20)
    args = ap.parse_args()

    from collections import defaultdict as _dd
    agg = _dd(lambda: {
        "W_ticks": 0, "L_ticks": 0, "D_ticks": 0,
        "W_BTs": set(), "L_BTs": set(),
        "d_dist_W": [], "d_dist_L": [],
        "d_ata_W": [], "d_ata_L": [],
        "d_closure_W": [], "d_closure_L": [],
        "d_e_W": [], "d_e_L": [],
    })
    total_parsed = 0
    for match_dir_str in args.matches:
        match_dir = Path(match_dir_str)
        outcomes = parse_outcomes(match_dir)
        print(f"[{match_dir}] outcomes: {len(outcomes)}")
        sub_agg, parsed = aggregate(match_dir, outcomes)
        total_parsed += parsed
        for key, v in sub_agg.items():
            e = agg[key]
            for fld in ("W_ticks", "L_ticks", "D_ticks"):
                e[fld] += v[fld]
            e["W_BTs"].update(v["W_BTs"])
            e["L_BTs"].update(v["L_BTs"])
            for fld in ("d_dist_W", "d_dist_L", "d_ata_W", "d_ata_L",
                        "d_closure_W", "d_closure_L", "d_e_W", "d_e_L"):
                e[fld].extend(v[fld])
    print(f"Matches parsed (total): {total_parsed}")
    print(f"Aggregated (opp, state, node) cells: {len(agg)}")

    records = build_records(agg, min_ticks=args.min_ticks)
    print(f"Records after min_ticks={args.min_ticks} filter: {len(records)}")

    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    json.dump(records, open(args.out, "w", encoding="utf-8"),
              ensure_ascii=False, indent=2)
    print(f"Saved: {args.out}")


if __name__ == "__main__":
    main()
