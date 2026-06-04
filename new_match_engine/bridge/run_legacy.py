"""CLI — legacy .yaml BT 두 개를 new_engine 백엔드로 1경기 실행.

usage:
  python -m new_match_engine.bridge.run_legacy aggressive ace
  python -m new_match_engine.bridge.run_legacy aggressive ace --controller indi --replay
  python -m new_match_engine.bridge.run_legacy path/to/a.yaml path/to/b.yaml

이름만 주면 ai-combat-core-main/.../examples/{name}.yaml 로 해석 (legacy 적 풀).
"""
from __future__ import annotations
import os, sys, argparse

_HERE = os.path.dirname(__file__)
_PROOT = os.path.abspath(os.path.join(_HERE, "..", ".."))
if _PROOT not in sys.path:
    sys.path.insert(0, _PROOT)

from new_match_engine.bridge import BehaviorTreeMatch

_YAML_DIR = os.path.join(_PROOT, "ai-combat-core-main", "ai-combat-core-main", "examples")


def _resolve(name: str) -> str:
    if os.path.sep in name or name.endswith(".yaml") or os.path.isabs(name):
        return name
    return os.path.join(_YAML_DIR, name + ".yaml")


def main():
    ap = argparse.ArgumentParser(description="legacy .yaml vs .yaml on new_engine")
    ap.add_argument("tree1"); ap.add_argument("tree2")
    ap.add_argument("--controller", default="lqr", choices=["lqr", "indi"])
    ap.add_argument("--replay", action="store_true", help="Tacview .acmi 저장")
    ap.add_argument("--max-steps", type=int, default=0)
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()

    t1, t2 = _resolve(args.tree1), _resolve(args.tree2)
    replay = None
    if args.replay:
        rd = os.path.join(_HERE, "..", "replays")
        os.makedirs(rd, exist_ok=True)
        replay = os.path.join(rd, f"bridge_{args.tree1}_vs_{args.tree2}_{args.controller}.acmi")

    print("=" * 64)
    print(f"  bridge — {args.tree1} vs {args.tree2}  [engine={args.controller}]")
    print("=" * 64)
    m = BehaviorTreeMatch(t1, t2, max_steps=args.max_steps, controller=args.controller)
    res = m.run(replay_path=replay, verbose=not args.quiet)
    print(f"\n  winner={res.winner}  condition={res.condition}  steps={res.total_steps}")
    print(f"  H1={res.health1_val:.1f}  H2={res.health2_val:.1f}  "
          f"dmg1={res.tree1_reward:.1f}  dmg2={res.tree2_reward:.1f}")
    if replay:
        print(f"  replay: {os.path.relpath(replay, _PROOT)}")


if __name__ == "__main__":
    main()
