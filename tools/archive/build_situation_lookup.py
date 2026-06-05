"""기존 tactical_lookup + GA hypotheses 통합 → situation_state_lookup.json.

3 가지 컴포넌트 결합:
  1. tactical_lookup.json — (state_key) → recommended branch (BT-zoo 데이터, 적 무관)
  2. ga_hypotheses.json — per-opp knob signature + trade-off pairs
  3. situation classifier — 첫 30 tick obs 로 on_to_on / chase 분류

출력: logs/knowledge/situation_state_lookup.json
  {
    "situation_classifier": {
      "on_to_on": {"dist_min": 2500, "aa_min": 150, "first_n_ticks": 30},
      "chase":    {"dist_max": 3000, "aa_max": 90,  "closure_min": 50}
    },
    "state_recommendation": {
      "<state_key>": {"node": "...", "confidence": 0.0-1.0, "n": int}
    },
    "situation_knob_set": {
      "on_to_on": {STUCK_THR: ..., LAMBDA_*: ...},
      "chase":    {STUCK_THR: ..., LAMBDA_*: ...}
    }
  }

cost_branch_selector.py 가 runtime 에 이 lookup 을 읽어 dispatch.
"""
import json
from collections import defaultdict, Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TACTICAL_IN = ROOT / "logs/knowledge/tactical_lookup.json"
GA_HYPOS_IN = ROOT / "logs/knowledge/ga_hypotheses.json"
OUT_PATH = ROOT / "logs/knowledge/situation_state_lookup.json"


def aggregate_tactical_lookup(tac: dict) -> dict:
    """state_key → recommended branch (가장 자주, tick_wr 가중치 평균)."""
    states = tac.get("states", {})
    out = {}
    for state_key, opp_data in states.items():
        # opp_data = {"aggressive": {...}, "defensive": {...}}
        if not isinstance(opp_data, dict):
            continue
        # collect (node, weight) candidates
        nodes = []
        for opp_name, rec in opp_data.items():
            if not isinstance(rec, dict):
                continue
            node = rec.get("node")
            tick_wr = rec.get("tick_wr", 0)
            n = rec.get("n", 0)
            if node and tick_wr >= 0.7 and n >= 20:
                weight = tick_wr * min(n, 100)
                nodes.append((node, weight, opp_name, tick_wr, n))
        if not nodes:
            continue
        # majority vote weighted by tick_wr × n
        node_weights = defaultdict(float)
        for node, w, _, _, _ in nodes:
            node_weights[node] += w
        best_node = max(node_weights, key=node_weights.get)
        total_w = sum(node_weights.values())
        confidence = node_weights[best_node] / total_w if total_w else 0
        avg_n = sum(n for _, _, _, _, n in nodes if _ == best_node) // max(1, sum(1 for nn, _, _, _, _ in nodes if nn == best_node))
        out[state_key] = {
            "node": best_node,
            "confidence": round(confidence, 2),
            "n_opps": len([n for n in nodes if n[0] == best_node]),
            "best_opps": [n[2] for n in nodes if n[0] == best_node][:3],
        }
    return out


def derive_situation_knob_sets(ga_hypos: dict) -> dict:
    """ga_hypotheses 의 win-cluster signature 로부터 on_to_on / chase 별 best knob.

    on_to_on = bt_vs_bt scenario, chase = tail_chase scenario.
    각 시나리오에 적합한 winning knob signature 를 opp 별로 추출 + 평균.
    """
    sig = ga_hypos.get("win_cluster_signature", {})
    KNOBS = ga_hypos.get("knobs", [])
    situation_signatures = {"on_to_on": defaultdict(list), "chase": defaultdict(list)}
    for cell, info in sig.items():
        if info["n_hits"] < 3:
            continue
        situation = "on_to_on" if "@bt_vs_bt" in cell else ("chase" if "@tail_chase" in cell else None)
        if not situation:
            continue
        hit_knobs = info.get("hit_knobs", {})
        for k in KNOBS:
            if k in hit_knobs:
                situation_signatures[situation][k].append(hit_knobs[k]["mean"])
    out = {}
    for sit in ("on_to_on", "chase"):
        if not situation_signatures[sit]:
            continue
        knob_mean = {}
        for k in KNOBS:
            vals = situation_signatures[sit].get(k, [])
            if vals:
                knob_mean[k] = round(sum(vals) / len(vals), 2)
        out[sit] = knob_mean
    return out


def derive_per_opp_winning_signature(ga_hypos: dict) -> dict:
    """각 opp 의 best variant knob set — fallback dispatch 용."""
    bests = ga_hypos.get("best_per_opp", {})
    out = {}
    for opp, b in bests.items():
        if b["top1_dmg"] >= 15:
            out[opp] = b["top3_knob_mean"]
    return out


def main():
    if not TACTICAL_IN.exists() or not GA_HYPOS_IN.exists():
        print(f"MISSING: {TACTICAL_IN} or {GA_HYPOS_IN}")
        return
    tac = json.load(open(TACTICAL_IN, encoding="utf-8"))
    ga = json.load(open(GA_HYPOS_IN, encoding="utf-8"))

    state_rec = aggregate_tactical_lookup(tac)
    situation_knobs = derive_situation_knob_sets(ga)
    per_opp_knobs = derive_per_opp_winning_signature(ga)

    out = {
        "bin_edges": tac.get("bin_edges", {}),
        "situation_classifier": {
            "on_to_on": {
                "description": "head-on spawn (bt_vs_bt scenario)",
                "rules": {
                    "dist_ft_min": 2500,
                    "aa_deg_min": 150,
                    "first_n_ticks": 30,
                    "closure_kts_min": 50
                }
            },
            "chase": {
                "description": "chase / tail position (tail_chase scenario)",
                "rules": {
                    "dist_ft_max": 3500,
                    "ata_deg_max": 60,
                    "first_n_ticks": 30
                }
            }
        },
        "state_recommendation": state_rec,
        "situation_knob_set": situation_knobs,
        "per_opp_knob_set": per_opp_knobs,
        "source": {
            "tactical_lookup": str(TACTICAL_IN.relative_to(ROOT)),
            "ga_hypotheses": str(GA_HYPOS_IN.relative_to(ROOT)),
            "n_states": len(state_rec),
            "n_situations": len(situation_knobs),
            "n_opp_signatures": len(per_opp_knobs),
        }
    }
    OUT_PATH.write_text(json.dumps(out, indent=2, ensure_ascii=False))
    print(f"Saved: {OUT_PATH}")
    print(f"  States with recommendation: {len(state_rec)}")
    print(f"  Situations: {list(situation_knobs.keys())}")
    print(f"  Opps with signature: {list(per_opp_knobs.keys())}")
    print()
    print("=== Situation knob sets (mean across hits) ===")
    for sit, ks in situation_knobs.items():
        print(f"  {sit}:")
        for k, v in ks.items():
            print(f"    {k}={v}")
    print()
    print("=== Sample state recommendations (top 10) ===")
    sorted_states = sorted(state_rec.items(),
                           key=lambda x: -x[1]["confidence"])[:10]
    for sk, rec in sorted_states:
        # parse state_key
        parts = sk.split("_")
        ata_b, dist_b, clos_b, e_b = parts[:4] if len(parts) >= 4 else (sk, "?", "?", "?")
        be = out["bin_edges"]
        try:
            ata_range = f"ata={be['ata'][int(ata_b)]}-{be['ata'][int(ata_b)+1]}°"
            dist_range = f"dist={be['dist'][int(dist_b)]}-{be['dist'][int(dist_b)+1]}ft"
        except (IndexError, ValueError):
            ata_range = dist_range = "?"
        print(f"  {sk:>10s} ({ata_range}, {dist_range}): "
              f"{rec['node']:>20s}  conf={rec['confidence']:.2f}  n_opps={rec['n_opps']}")


if __name__ == "__main__":
    main()
