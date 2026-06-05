"""Scan all BT node classes' TUNABLE_PARAMS and inject concrete defaults
into counter_table_proposal_v3.json.

For each recommendation, pulls defaults from the source_bt's node class so
the recommended params are grounded in the actual winning BT's implementation.
"""
import argparse
import ast
import json
from collections import defaultdict
from pathlib import Path


BT_NODE_DIRS = {
    "adaptive_eagle":         "examples/adaptive_eagle/nodes",
    "adaptive_eagle_v51":     "examples/adaptive_eagle_v51/nodes",
    "adaptive_eagle_v6":      "examples/adaptive_eagle_v6/nodes",
    "adaptive_eagle_v6h2":    "examples/adaptive_eagle_v6h2/nodes",
    "adaptive_eagle_v6h4":    "examples/adaptive_eagle_v6h4/nodes",
    "adaptive_eagle_v6h5a":   "examples/adaptive_eagle_v6h5a/nodes",
    "adaptive_eagle_v6h5b":   "examples/adaptive_eagle_v6h5b/nodes",
    "adaptive_eagle_v6h5c":   "examples/adaptive_eagle_v6h5c/nodes",
    "adaptive_eagle_v6h_e1":  "examples/adaptive_eagle_v6h_e1/nodes",
    "adaptive_eagle_v6h_e1b": "examples/adaptive_eagle_v6h_e1b/nodes",
    "adaptive_eagle_v6h_e1c": "examples/adaptive_eagle_v6h_e1c/nodes",
    "adaptive_eagle_v6h_e1d": "examples/adaptive_eagle_v6h_e1d/nodes",
    "adaptive_eagle_v7":      "examples/adaptive_eagle_v7/nodes",
    "adaptive_eagle_v8":      "examples/adaptive_eagle_v8/nodes",
    "adaptive_eagle_v9":      "examples/adaptive_eagle_v9/nodes",
}


def literal(node):
    """Best-effort literal eval (handles negatives, tuples, lists, numbers, strings)."""
    try:
        return ast.literal_eval(node)
    except Exception:
        try:
            return ast.unparse(node)
        except Exception:
            return None


def extract_tunable_params(file_path: Path):
    """Parse a .py file and return {ClassName: {param_name: {default, range, choices, type}}}."""
    try:
        tree = ast.parse(file_path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    out = {}
    for cls in tree.body:
        if not isinstance(cls, ast.ClassDef):
            continue
        for stmt in cls.body:
            if not isinstance(stmt, ast.Assign):
                continue
            if not (len(stmt.targets) == 1
                    and isinstance(stmt.targets[0], ast.Name)
                    and stmt.targets[0].id == "TUNABLE_PARAMS"):
                continue
            if not isinstance(stmt.value, ast.Dict):
                continue
            params = {}
            for k_node, v_node in zip(stmt.value.keys, stmt.value.values):
                if not isinstance(k_node, ast.Constant):
                    continue
                key = k_node.value
                entry = {}
                if isinstance(v_node, ast.Dict):
                    for ek, ev in zip(v_node.keys, v_node.values):
                        if isinstance(ek, ast.Constant):
                            entry[ek.value] = literal(ev)
                params[key] = entry
            if params:
                out[cls.name] = params
    return out


def build_registry():
    """{bt: {ClassName: {param: {default, range, choices, type}}}}"""
    registry = {}
    for bt, rel in BT_NODE_DIRS.items():
        p = Path(rel)
        if not p.exists():
            continue
        merged = {}
        for py in p.glob("*.py"):
            if py.name == "__init__.py":
                continue
            merged.update(extract_tunable_params(py))
        registry[bt] = merged
    return registry


def defaults_only(params_dict):
    """Return {param: default} extracting default from entry dict."""
    return {k: v.get("default") for k, v in params_dict.items() if v.get("default") is not None}


def enrich_proposal(proposal_path: Path, registry: dict, out_path: Path):
    data = json.load(open(proposal_path, encoding="utf-8"))
    stats = {"hits": 0, "misses": 0, "no_tunable": 0}

    for opp in ("aggressive", "defensive"):
        for rec in data["recommend"].get(opp, []):
            node = rec["recommended_node"]
            src = rec["source_bt"]
            src_defaults = {}
            if src in registry and node in registry[src]:
                src_defaults = defaults_only(registry[src][node])
                if src_defaults:
                    stats["hits"] += 1
                else:
                    stats["no_tunable"] += 1
            else:
                stats["misses"] += 1
            rec["node_defaults"] = src_defaults
            # Preserve existing yaml-override params (already in recommended_params)
            # effective = defaults | yaml override
            effective = dict(src_defaults)
            effective.update(rec.get("recommended_params", {}) or {})
            rec["effective_params"] = effective

    data["node_registry_summary"] = {
        bt: {cls: list(p.keys()) for cls, p in nodes.items()}
        for bt, nodes in registry.items()
    }
    data["enrichment_stats"] = stats

    json.dump(data, open(out_path, "w", encoding="utf-8"),
              ensure_ascii=False, indent=2)
    return stats, data


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--proposal", default="logs/knowledge/counter_table_proposal_v3.json")
    ap.add_argument("--out", default="logs/knowledge/counter_table_proposal_v3.json")
    args = ap.parse_args()

    registry = build_registry()
    bt_with_nodes = sum(1 for v in registry.values() if v)
    total_classes = sum(len(v) for v in registry.values())
    print(f"Registry built: {bt_with_nodes} BTs, {total_classes} node classes total")

    stats, data = enrich_proposal(Path(args.proposal), registry, Path(args.out))
    print(f"Enrichment: hits={stats['hits']}, misses={stats['misses']}, no_tunable={stats['no_tunable']}")
    print(f"Saved: {args.out}")

    print("\n=== Sample enriched recommendations (vs aggressive, top 5) ===")
    for rec in data["recommend"]["aggressive"][:5]:
        s = rec["state"]
        print(f"\n[ATA {s['ata']} DIST {s['dist']} CLOS {s['closure']} E {s['e_diff']}]")
        print(f"  node      : {rec['recommended_node']}")
        print(f"  source    : {rec['source_bt']} (match WR {rec['bt_match_wr']:.0%}, tick WR {rec['tick_wr']:.0%}, n={rec['support_n']})")
        print(f"  defaults  : {rec.get('node_defaults', {}) or '(none)'}")
        print(f"  effective : {rec.get('effective_params', {}) or '(none)'}")

    print("\n=== Sample enriched recommendations (vs defensive, top 5) ===")
    for rec in data["recommend"]["defensive"][:5]:
        s = rec["state"]
        print(f"\n[ATA {s['ata']} DIST {s['dist']} CLOS {s['closure']} E {s['e_diff']}]")
        print(f"  node      : {rec['recommended_node']}")
        print(f"  source    : {rec['source_bt']} (match WR {rec['bt_match_wr']:.0%}, tick WR {rec['tick_wr']:.0%}, n={rec['support_n']})")
        print(f"  defaults  : {rec.get('node_defaults', {}) or '(none)'}")
        print(f"  effective : {rec.get('effective_params', {}) or '(none)'}")


if __name__ == "__main__":
    main()
