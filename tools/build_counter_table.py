"""Build counter_table_proposal from tactical patterns + BT YAML params.

Takes output of mine_tactical_patterns.py and cross-references each winning
(state, node) pair with the YAML parameters of the BT versions that won.

Output: logs/knowledge/counter_table_proposal_v3.json with per-state
recommendations including concrete parameter values.
"""
import argparse
import json
from collections import defaultdict
from pathlib import Path

import yaml


BT_WR_DEFAULT = {
    "adaptive_eagle":         {"aggressive": 0.50, "defensive": 1.00},
    "adaptive_eagle_v51":     {"aggressive": 0.00, "defensive": 1.00},
    "adaptive_eagle_v6":      {"aggressive": 0.00, "defensive": 0.80},
    "adaptive_eagle_v6h2":    {"aggressive": 0.00, "defensive": 0.60},
    "adaptive_eagle_v6h4":    {"aggressive": 0.00, "defensive": 1.00},
    "adaptive_eagle_v6h5a":   {"aggressive": 0.00, "defensive": 1.00},
    "adaptive_eagle_v6h5b":   {"aggressive": 0.00, "defensive": 0.60},
    "adaptive_eagle_v6h5c":   {"aggressive": 0.80, "defensive": 0.00},
    "adaptive_eagle_v6h_e1":  {"aggressive": 0.00, "defensive": 0.00},
    "adaptive_eagle_v6h_e1b": {"aggressive": 0.00, "defensive": 0.40},
    "adaptive_eagle_v6h_e1c": {"aggressive": 0.00, "defensive": 1.00},
    "adaptive_eagle_v6h_e1d": {"aggressive": 0.00, "defensive": 1.00},
    "adaptive_eagle_v7":      {"aggressive": 0.00, "defensive": 0.00},
    "adaptive_eagle_v8":      {"aggressive": 0.60, "defensive": 0.00},
    "adaptive_eagle_v9":      {"aggressive": 0.00, "defensive": 0.60},
}

BT_YAML_PATHS = {bt: f"examples/{bt}/{bt}.yaml" for bt in BT_WR_DEFAULT}


def walk_tree(node, bt_name, out):
    if not isinstance(node, dict):
        return
    name = node.get("name", "")
    params = node.get("params", {}) or {}
    if name and params:
        out[name][bt_name].append(params)
    for child in node.get("children", []) or []:
        walk_tree(child, bt_name, out)


def collect_yaml_params(bt_files):
    bt_nodes = defaultdict(lambda: defaultdict(list))
    for bt, rel in bt_files.items():
        p = Path(rel)
        if not p.exists():
            continue
        doc = yaml.safe_load(open(p, encoding="utf-8"))
        walk_tree(doc.get("tree", {}), bt, bt_nodes)
    return bt_nodes


def build(records, bt_nodes, bt_wr, win_thr=0.7, avoid_thr=0.3, min_n=50):
    recs_raw = defaultdict(list)
    for r in records:
        if r["win_rate"] is None:
            continue
        wl = r["n_W"] + r["n_L"]
        if wl < min_n:
            continue
        if r["win_rate"] < win_thr:
            continue
        w_bts = r["W_BTs"]
        if not w_bts:
            continue
        best_bt = max(w_bts, key=lambda b: bt_wr.get(b, {}).get(r["opp"], 0))
        params_for_node = bt_nodes.get(r["node"], {}).get(best_bt, [])
        params = params_for_node[0] if params_for_node else {}
        recs_raw[r["opp"]].append({
            "state": r["state"],
            "state_key": r["state_key"],
            "recommended_node": r["node"],
            "recommended_params": params,
            "source_bt": best_bt,
            "bt_match_wr": bt_wr.get(best_bt, {}).get(r["opp"], 0),
            "tick_wr": r["win_rate"],
            "support_n": wl,
            "d_dist_expected": r["d_dist_W"],
            "d_ata_expected": r["d_ata_W"],
            "d_closure_expected": r["d_closure_W"],
            "d_e_expected": r["d_e_W"],
            "all_W_BTs": w_bts,
        })

    final = {}
    for opp, cands in recs_raw.items():
        by_state = defaultdict(list)
        for rec in cands:
            by_state[tuple(rec["state_key"])].append(rec)
        dedup = []
        for state, group in by_state.items():
            group.sort(key=lambda x: (-x["bt_match_wr"], -x["tick_wr"], -x["support_n"]))
            dedup.append(group[0])
        dedup.sort(key=lambda r: (-r["bt_match_wr"], -r["tick_wr"]))
        final[opp] = dedup

    avoid = {}
    for opp in ("aggressive", "defensive"):
        avoid_list = []
        for r in records:
            if r["opp"] != opp:
                continue
            if r["win_rate"] is None or r["win_rate"] > avoid_thr:
                continue
            wl = r["n_W"] + r["n_L"]
            if wl < min_n:
                continue
            avoid_list.append({
                "state": r["state"],
                "state_key": r["state_key"],
                "avoid_node": r["node"],
                "tick_wr": r["win_rate"],
                "n_L": r["n_L"],
                "n_W": r["n_W"],
            })
        avoid_list.sort(key=lambda r: (r["tick_wr"], -r["n_L"]))
        avoid[opp] = avoid_list

    return final, avoid


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--patterns", default="logs/knowledge/tactical_patterns_v2.json")
    ap.add_argument("--out", default="logs/knowledge/counter_table_proposal_v3.json")
    ap.add_argument("--win-thr", type=float, default=0.7)
    ap.add_argument("--avoid-thr", type=float, default=0.3)
    ap.add_argument("--min-n", type=int, default=50)
    args = ap.parse_args()

    records = json.load(open(args.patterns, encoding="utf-8"))
    bt_nodes = collect_yaml_params(BT_YAML_PATHS)
    final, avoid = build(records, bt_nodes, BT_WR_DEFAULT,
                         win_thr=args.win_thr, avoid_thr=args.avoid_thr,
                         min_n=args.min_n)

    out = {
        "generated_from": "logs/matches/all_eagles_vs_agg_def",
        "thresholds": {"win_thr": args.win_thr, "avoid_thr": args.avoid_thr, "min_n": args.min_n},
        "recommend": final,
        "avoid": avoid,
        "bt_match_wr": BT_WR_DEFAULT,
        "notes": [
            "recommend: state -> (node, params) with WR>=win_thr and n>=min_n",
            "params taken from the BT with best match-level WR among winners",
            "avoid: state -> (node) with WR<=avoid_thr and n>=min_n",
        ],
    }

    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    json.dump(out, open(args.out, "w", encoding="utf-8"),
              ensure_ascii=False, indent=2)

    for opp in ("aggressive", "defensive"):
        print(f"\n== vs {opp}: {len(final[opp])} recommendations, {len(avoid[opp])} AVOID patterns ==")
        print("TOP 10 recommendations:")
        for r in final[opp][:10]:
            s = r["state"]
            p = r["recommended_params"]
            pstr = ", ".join(f"{k}={v}" for k, v in p.items()) if p else "(no params)"
            label = f"[ATA {s['ata']:>7s} DIST {s['dist']:>5s} CLOS {s['closure']:>6s} E {s['e_diff']:>6s}]"
            print(f"  {label} -> {r['recommended_node']}")
            print(f"     params: {pstr}")
            src = f"src={r['source_bt']} match_WR={r['bt_match_wr']:.0%} tick_WR={r['tick_wr']:.0%} n={r['support_n']}"
            print(f"     {src}")
        print("TOP 5 AVOID:")
        for r in avoid[opp][:5]:
            s = r["state"]
            label = f"[ATA {s['ata']:>7s} DIST {s['dist']:>5s} CLOS {s['closure']:>6s} E {s['e_diff']:>6s}]"
            print(f"  {label} avoid {r['avoid_node']} (losing {r['n_L']} ticks, WR {r['tick_wr']:.0%})")

    print(f"\nSaved: {args.out}")


if __name__ == "__main__":
    main()
