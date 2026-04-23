"""Transform counter_table_proposal_v3.json into a flat runtime-efficient
lookup table keyed by state bin index.

Output format:
{
  "bin_edges": {
    "ata": [0,30,60,90,120,150,180],
    "dist": [0,1000,3000,6000,10000,20000],
    "closure": [-400,-100,0,100,400],
    "e_diff": [-10000,-3000,0,3000,10000]
  },
  "states": {
    "3_4_0_3": {
      "aggressive": {"node": "SmartLagPursuit", "tick_wr": 0.97, "n": 58, "params": {...}},
      "defensive": {"node": "SmartLowYoYo", ...}
    }
  }
}

At runtime the BT node:
  1. reads current observation
  2. computes (ata_bin, dist_bin, closure_bin, e_bin)
  3. key = "a_d_c_e"
  4. picks aggressive or defensive entry based on EIM intent (or both if uncertain)
"""
import argparse
import json
from collections import defaultdict
from pathlib import Path


BIN_EDGES = {
    "ata":     [0, 30, 60, 90, 120, 150, 180],
    "dist":    [0, 1000, 3000, 6000, 10000, 20000],
    "closure": [-400, -100, 0, 100, 400],
    "e_diff":  [-10000, -3000, 0, 3000, 10000],
}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--proposal", default="logs/knowledge/counter_table_proposal_v3.json")
    ap.add_argument("--out", default="logs/knowledge/tactical_lookup.json")
    args = ap.parse_args()

    prop = json.load(open(args.proposal, encoding="utf-8"))
    states = defaultdict(dict)

    for opp in ("aggressive", "defensive"):
        for rec in prop["recommend"].get(opp, []):
            a, d, c, e = rec["state_key"]
            key = f"{a}_{d}_{c}_{e}"
            states[key][opp] = {
                "node": rec["recommended_node"],
                "tick_wr": rec["tick_wr"],
                "n": rec["support_n"],
                "source_bt": rec["source_bt"],
                "params": rec.get("effective_params", {}),
                "expected_dd": rec["d_dist_expected"],
                "expected_dclosure": rec["d_closure_expected"],
            }

    avoid = defaultdict(dict)
    for opp in ("aggressive", "defensive"):
        for rec in prop["avoid"].get(opp, []):
            a, d, c, e = rec["state_key"]
            key = f"{a}_{d}_{c}_{e}"
            avoid[key].setdefault(opp, []).append(rec["avoid_node"])

    out = {
        "bin_edges": BIN_EDGES,
        "states": dict(states),
        "avoid": dict(avoid),
        "source": "logs/knowledge/counter_table_proposal_v3.json",
        "n_state_cells": len(states),
        "n_avoid_cells": len(avoid),
    }

    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    json.dump(out, open(args.out, "w", encoding="utf-8"),
              ensure_ascii=False, indent=2)
    print(f"Saved: {args.out}")
    print(f"  state cells with recommendations: {len(states)}")
    print(f"  state cells with avoid patterns:  {len(avoid)}")
    # Coverage check
    both = sum(1 for v in states.values() if "aggressive" in v and "defensive" in v)
    agg_only = sum(1 for v in states.values() if "aggressive" in v and "defensive" not in v)
    def_only = sum(1 for v in states.values() if "defensive" in v and "aggressive" not in v)
    print(f"  both agg+def: {both}, agg-only: {agg_only}, def-only: {def_only}")


if __name__ == "__main__":
    main()
