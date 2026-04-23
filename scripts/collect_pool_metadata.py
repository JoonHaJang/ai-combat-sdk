"""
Collect metadata CSVs by running one agent vs a filtered subset of the opponent pool.

Usage:
    # Full 695 pool regeneration (excluded from git, ~100m)
    python scripts/collect_pool_metadata.py \
        --agent examples/adaptive_eagle_v9/adaptive_eagle_v9.yaml \
        --exclude-layer L7 \
        --output logs/metadata/v9_vs_695pool

    # L7-only (gap-targeted, ~15m)
    python scripts/collect_pool_metadata.py \
        --agent examples/adaptive_eagle_v9/adaptive_eagle_v9.yaml \
        --layer L7 \
        --output logs/metadata/v9_vs_L7
"""
import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.run_match import run_match

POOL_DIR = Path("examples/opponent_pool")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--agent", required=True, help="Path to agent1 YAML")
    ap.add_argument("--output", required=True, help="Metadata output directory")
    ap.add_argument("--layer", default=None, help="Only include this layer (e.g. L7)")
    ap.add_argument("--exclude-layer", default=None, help="Exclude this layer (e.g. L7)")
    ap.add_argument("--rounds", type=int, default=1)
    args = ap.parse_args()

    manifest = json.load(open(POOL_DIR / "manifest.json", encoding="utf-8"))
    opps = manifest["opponents"]
    if args.layer:
        opps = [o for o in opps if o.get("layer") == args.layer]
    if args.exclude_layer:
        opps = [o for o in opps if o.get("layer") != args.exclude_layer]

    out_dir = Path(args.output)
    out_dir.mkdir(parents=True, exist_ok=True)

    t0 = time.time()
    done = err = 0
    total = len(opps)
    print(f"Collecting {total} matches → {out_dir}", file=sys.stderr)

    for opp in opps:
        opp_path = str(POOL_DIR / opp["yaml_path"])
        try:
            run_match(
                agent1=args.agent,
                agent2=opp_path,
                rounds=args.rounds,
                verbose=False,
                metadata_log=str(out_dir),
            )
            done += 1
            if done % 20 == 0:
                elapsed = time.time() - t0
                eta = elapsed / done * (total - done)
                print(f"[{done}/{total}] {elapsed:.0f}s, ETA {eta/60:.1f}m", file=sys.stderr)
        except Exception as e:
            err += 1
            print(f"  ERROR {opp['name']}: {e}", file=sys.stderr)

    print(f"DONE: {done} matches, {err} errors, {(time.time()-t0)/60:.1f}m", file=sys.stderr)


if __name__ == "__main__":
    main()
