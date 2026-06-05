"""Phase C Extended — Pursuit_Chase_BT 대규모 매치 평가.

목적:
  E7 자가대전 100 매치 + E8 다양 상대 풀 평가 + E9 archetype sampling.
  Full 1500 tick (5분 매치) 사용. 병렬 실행 (ProcessPoolExecutor).

실행:
  python tools/run_phase_c_extended.py --workers 4 --self-play 100 --vs-named 10
  python tools/run_phase_c_extended.py --workers 4 --quick     # 빠른 sanity: self=20, named=3
  python tools/run_phase_c_extended.py --resume                # 기존 결과 집계만

출력:
  logs/c_extended/E7_selfplay/*.csv + *_result.json
  logs/c_extended/E8_named/<opponent>/*.csv + *_result.json
  logs/c_extended/E9_archetypes/<archetype>/*.csv + *_result.json
  logs/c_extended/summary.json  — 전체 통계
"""

from __future__ import annotations

import sys
import os
import json
import time
import argparse
from pathlib import Path
from concurrent.futures import ProcessPoolExecutor, as_completed
from collections import Counter, defaultdict

os.environ.setdefault("PYTHONIOENCODING", "utf-8")
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, ValueError):
    pass

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# 명명된 상대 풀 (examples/) — Tier 별 분류
NAMED_OPPONENTS = [
    # Tier 1: basic baseline
    "simple", "aggressive", "defensive", "horizontal_flight",
    # Tier 2: named character agents
    "ace", "eagle2",
    # Tier 3: hypothesis-generated agents (gen_*)
    "gen_rush", "gen_gunfighter", "gen_evader", "gen_breaker",
    "gen_energy", "gen_midrange", "gen_allbranch",
    # Tier 4: tactical probes (probe_*)
    "probe_defensive", "probe_energy", "probe_gun_aggro",
    "probe_gun_close", "probe_habfm", "probe_obfm", "probe_wez",
]

# Archetype sampling (174 개 중 cross-section)
ARCHETYPE_SAMPLES = [
    "examples/archetypes/arch_defensive_00.yaml",
    "examples/archetypes/arch_defensive_05.yaml",
    "examples/archetypes/arch_defensive_10.yaml",
    # 추가 archetypes 자동 sampling — main 에서 동적
]


def run_one_match(args_tuple):
    """단일 매치 실행 (worker 함수)."""
    agent1, agent2, output_dir, label = args_tuple
    try:
        # scripts.run_match.run_match 임포트는 worker 안에서 (spawn overhead)
        from scripts.run_match import run_match
        results = run_match(
            agent1=agent1,
            agent2=agent2,
            rounds=1,
            verbose=False,
            metadata_log=output_dir,
        )
        if results:
            r = results[0]
            return {
                "label": label,
                "agent1": agent1,
                "agent2": agent2,
                "winner": r.get("winner", "?"),
                "tree1_hp": r.get("tree1_health", 0),
                "tree2_hp": r.get("tree2_health", 0),
                "total_steps": r.get("total_steps", 0),
                "error": None,
            }
        return {"label": label, "agent1": agent1, "agent2": agent2,
                "winner": "no_result", "error": "empty_results"}
    except Exception as e:
        return {"label": label, "agent1": agent1, "agent2": agent2,
                "winner": "error", "error": str(e)}


def aggregate_results(results: list, our_agent="pursuit_chase_v1"):
    """결과 list → 통계 집계."""
    n = len(results)
    if n == 0:
        return {"n": 0}

    wins = losses = draws = errors = 0
    hp_us = []
    hp_them = []
    steps = []
    error_msgs = []

    for r in results:
        if r.get("error"):
            errors += 1
            error_msgs.append(r["error"])
            continue
        w = r.get("winner", "")
        a1, a2 = r.get("agent1", ""), r.get("agent2", "")
        hp1, hp2 = r.get("tree1_hp", 0), r.get("tree2_hp", 0)
        # 우리가 agent1 또는 agent2?
        if our_agent in str(a1):
            our_hp, their_hp = hp1, hp2
            our_won = (w == "tree1") or (w == "A")
            they_won = (w == "tree2") or (w == "B")
        else:
            our_hp, their_hp = hp2, hp1
            our_won = (w == "tree2") or (w == "B")
            they_won = (w == "tree1") or (w == "A")

        hp_us.append(our_hp)
        hp_them.append(their_hp)
        steps.append(r.get("total_steps", 0))

        if w in ("draw", "tie", None) or w == "":
            draws += 1
        elif our_won:
            wins += 1
        elif they_won:
            losses += 1
        else:
            # winner 가 모호하면 HP 비교
            if our_hp > their_hp:
                wins += 1
            elif our_hp < their_hp:
                losses += 1
            else:
                draws += 1

    n_valid = n - errors
    return {
        "n": n,
        "n_valid": n_valid,
        "win": wins,
        "loss": losses,
        "draw": draws,
        "error": errors,
        "win_pct": 100 * wins / n_valid if n_valid else 0,
        "loss_pct": 100 * losses / n_valid if n_valid else 0,
        "draw_pct": 100 * draws / n_valid if n_valid else 0,
        "hp_us_mean": float(sum(hp_us) / len(hp_us)) if hp_us else None,
        "hp_them_mean": float(sum(hp_them) / len(hp_them)) if hp_them else None,
        "steps_mean": float(sum(steps) / len(steps)) if steps else None,
        "steps_max": max(steps) if steps else 0,
        "error_msgs": error_msgs[:3],  # sample only
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--workers", type=int, default=4, help="parallel workers (default 4)")
    parser.add_argument("--self-play", type=int, default=100, help="self-play matches (E7)")
    parser.add_argument("--vs-named", type=int, default=10, help="vs each named opponent (E8)")
    parser.add_argument("--vs-archetypes", type=int, default=0, help="vs each archetype sample (E9)")
    parser.add_argument("--quick", action="store_true", help="quick sanity: 20 self + 3 named + 0 arch")
    parser.add_argument("--resume", action="store_true", help="aggregate existing results only")
    parser.add_argument("--our-agent", type=str, default="pursuit_chase_v1")
    args = parser.parse_args()

    if args.quick:
        args.self_play = 20
        args.vs_named = 3
        args.vs_archetypes = 0

    base_dir = PROJECT_ROOT / "logs" / "c_extended"
    base_dir.mkdir(parents=True, exist_ok=True)

    print(f"\n{'='*80}")
    print(f"  Phase C Extended — Pursuit_Chase_BT 대규모 매치 평가")
    print(f"{'='*80}")
    print(f"  Our agent      : {args.our_agent}")
    print(f"  Workers        : {args.workers}")
    print(f"  E7 self-play   : {args.self_play} 매치")
    print(f"  E8 vs named    : {args.vs_named} × {len(NAMED_OPPONENTS)} 적 = {args.vs_named * len(NAMED_OPPONENTS)} 매치")
    print(f"  E9 archetypes  : {args.vs_archetypes} × N samples (0 = skip)")
    print(f"  Output         : {base_dir}")

    # 매치 작업 list 빌드
    tasks = []

    # E7: self-play
    if args.self_play > 0:
        out_dir = base_dir / "E7_selfplay"
        out_dir.mkdir(exist_ok=True)
        for i in range(args.self_play):
            tasks.append((args.our_agent, args.our_agent, str(out_dir), f"E7/round{i}"))

    # E8: named opponents
    e8_labels = {}
    if args.vs_named > 0:
        for opp in NAMED_OPPONENTS:
            out_dir = base_dir / "E8_named" / opp
            out_dir.mkdir(parents=True, exist_ok=True)
            for i in range(args.vs_named):
                label = f"E8/{opp}/round{i}"
                e8_labels[label] = opp
                tasks.append((args.our_agent, opp, str(out_dir), label))

    # E9: archetype samples
    e9_labels = {}
    if args.vs_archetypes > 0:
        # 174 archetypes 중 균등 sampling
        arch_dir = PROJECT_ROOT / "examples" / "archetypes"
        all_archs = sorted(arch_dir.glob("*.yaml"))
        if all_archs:
            step = max(1, len(all_archs) // 10)  # 10개 sample
            archs = all_archs[::step][:10]
            for arch_path in archs:
                arch_name = arch_path.stem
                out_dir = base_dir / "E9_archetypes" / arch_name
                out_dir.mkdir(parents=True, exist_ok=True)
                rel_path = f"examples/archetypes/{arch_path.name}"
                for i in range(args.vs_archetypes):
                    label = f"E9/{arch_name}/round{i}"
                    e9_labels[label] = arch_name
                    tasks.append((args.our_agent, rel_path, str(out_dir), label))

    n_total = len(tasks)
    print(f"\n  총 매치: {n_total}")
    print(f"  추정 시간: {n_total * 15 / args.workers / 60:.1f} 분 (worker={args.workers}, 매치당 ~15s)")

    if args.resume:
        print(f"\n  ⚠ Resume 모드 — 매치 실행 건너뜀, 기존 결과 집계만.")
        # TODO: 기존 _result.json 들 로드해서 집계
        return

    # 실행
    print(f"\n  {'-'*70}\n  매치 실행 시작...\n  {'-'*70}\n")
    t_start = time.time()
    results_all = []
    completed = 0

    with ProcessPoolExecutor(max_workers=args.workers) as exe:
        futures = {exe.submit(run_one_match, task): task for task in tasks}
        for future in as_completed(futures):
            r = future.result()
            results_all.append(r)
            completed += 1
            elapsed = time.time() - t_start
            eta = elapsed / completed * (n_total - completed)
            label = r.get("label", "?")
            winner = r.get("winner", "?")
            err = r.get("error")
            status = "ERR" if err else f"W={winner}"
            if completed % 5 == 0 or completed == n_total:
                print(f"  [{completed:4d}/{n_total}] {elapsed:6.1f}s elapsed, ETA {eta:6.1f}s   ({label} {status})")

    t_end = time.time()
    print(f"\n  실행 완료: {t_end - t_start:.1f}초 ({(t_end-t_start)/60:.1f}분)")

    # ─── 집계 ──
    print(f"\n{'='*80}")
    print(f"  결과 집계")
    print(f"{'='*80}")

    # E7: self-play
    e7_results = [r for r in results_all if r.get("label", "").startswith("E7/")]
    if e7_results:
        e7_agg = aggregate_results(e7_results, args.our_agent)
        print(f"\n  [E7] Self-play (vs 자기 자신):")
        print(f"    N: {e7_agg['n_valid']}/{e7_agg['n']}  Win: {e7_agg['win']} ({e7_agg['win_pct']:.1f}%)  Loss: {e7_agg['loss']} ({e7_agg['loss_pct']:.1f}%)  Draw: {e7_agg['draw']} ({e7_agg['draw_pct']:.1f}%)")
        print(f"    HP mean: us={e7_agg['hp_us_mean']:.1f}  them={e7_agg['hp_them_mean']:.1f}")
        print(f"    Steps mean: {e7_agg['steps_mean']:.0f}  max: {e7_agg['steps_max']}")

    # E8: per opponent
    e8_by_opp = defaultdict(list)
    for r in results_all:
        label = r.get("label", "")
        if label.startswith("E8/"):
            parts = label.split("/")
            if len(parts) >= 2:
                e8_by_opp[parts[1]].append(r)

    if e8_by_opp:
        print(f"\n  [E8] vs Named Opponents:")
        print(f"    {'Opponent':<22} {'N':>4} {'Win':>5} {'Loss':>5} {'Draw':>5} {'HP us':>7} {'HP them':>8}")
        print(f"    {'-'*22} {'-'*4} {'-'*5} {'-'*5} {'-'*5} {'-'*7} {'-'*8}")
        total_w = total_l = total_d = 0
        for opp in NAMED_OPPONENTS:
            if opp in e8_by_opp:
                agg = aggregate_results(e8_by_opp[opp], args.our_agent)
                total_w += agg["win"]
                total_l += agg["loss"]
                total_d += agg["draw"]
                hp_us = f"{agg['hp_us_mean']:.1f}" if agg['hp_us_mean'] is not None else "-"
                hp_them = f"{agg['hp_them_mean']:.1f}" if agg['hp_them_mean'] is not None else "-"
                print(f"    {opp:<22} {agg['n_valid']:>4} {agg['win']:>5} {agg['loss']:>5} {agg['draw']:>5} {hp_us:>7} {hp_them:>8}")
        n_e8 = total_w + total_l + total_d
        if n_e8 > 0:
            print(f"    {'-'*22} {'-'*4} {'-'*5} {'-'*5} {'-'*5} {'-'*7} {'-'*8}")
            print(f"    {'TOTAL':<22} {n_e8:>4} {total_w:>5} {total_l:>5} {total_d:>5}  ({100*total_w/n_e8:.1f}% / {100*total_l/n_e8:.1f}% / {100*total_d/n_e8:.1f}%)")

    # E9: per archetype
    e9_by_arch = defaultdict(list)
    for r in results_all:
        label = r.get("label", "")
        if label.startswith("E9/"):
            parts = label.split("/")
            if len(parts) >= 2:
                e9_by_arch[parts[1]].append(r)
    if e9_by_arch:
        print(f"\n  [E9] vs Archetype Samples:")
        for arch, ress in sorted(e9_by_arch.items()):
            agg = aggregate_results(ress, args.our_agent)
            print(f"    {arch}: W={agg['win']} L={agg['loss']} D={agg['draw']}")

    # 통합 summary JSON
    summary = {
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "duration_s": t_end - t_start,
        "our_agent": args.our_agent,
        "config": {
            "workers": args.workers,
            "self_play": args.self_play,
            "vs_named": args.vs_named,
            "vs_archetypes": args.vs_archetypes,
        },
        "E7_selfplay": aggregate_results(e7_results, args.our_agent) if e7_results else None,
        "E8_per_opponent": {opp: aggregate_results(r, args.our_agent) for opp, r in e8_by_opp.items()},
        "E9_per_archetype": {arch: aggregate_results(r, args.our_agent) for arch, r in e9_by_arch.items()},
    }
    summary_path = base_dir / "summary.json"
    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)
    print(f"\n  Summary saved: {summary_path}")


if __name__ == "__main__":
    main()
