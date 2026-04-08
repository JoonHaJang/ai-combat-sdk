"""
collect_gun.py — GUN_ATTACK 데이터 집중 수집

probe_gun_aggro / probe_gun_close × 전체 기본 에이전트 × N 라운드
Windows spawn 호환 (freeze_support 포함)
"""
import sys
import multiprocessing as mp
from pathlib import Path
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

GUN_PROBES = ["probe_gun_aggro", "probe_gun_close"]
OPPONENTS = [
    "simple", "aggressive", "defensive", "eagle1", "ace", "viper1", "golden",
    "gen_rush", "gen_gunfighter", "gen_evader", "gen_breaker", "gen_energy",
    "gen_midrange", "gen_allbranch",
]
ROUNDS   = 5
WORKERS  = 8
OUTPUT_DIR = str(PROJECT_ROOT / "logs" / "metadata")


def run_one(args):
    from scripts.run_match import run_match
    a1, a2 = args
    try:
        results = run_match(agent1=a1, agent2=a2, rounds=1, verbose=False,
                            metadata_log=OUTPUT_DIR)
        if results:
            r = results[0]
            return (a1, a2, r.get("winner", "?"),
                    r.get("tree1_health", 0), r.get("tree2_health", 0), None)
        return (a1, a2, "no_result", 0, 0, None)
    except Exception as e:
        return (a1, a2, "error", 0, 0, str(e))


def run_batch(batch):
    return [run_one(a) for a in batch]


def main():
    Path(OUTPUT_DIR).mkdir(parents=True, exist_ok=True)

    pairs = []
    for probe in GUN_PROBES:
        for opp in OPPONENTS:
            for _ in range(ROUNDS):
                pairs.append((probe, opp))
                pairs.append((opp, probe))

    total = len(pairs)
    print(f"총 {total}매치 수집 시작 (workers={WORKERS})...")
    start = datetime.now()
    done = wins = draws = losses = errors = 0

    chunk = max(1, total // (WORKERS * 4))
    batches = [pairs[s:s + chunk] for s in range(0, total, chunk)]

    with ProcessPoolExecutor(max_workers=WORKERS) as ex:
        futures = {ex.submit(run_batch, b): b for b in batches}
        for fut in as_completed(futures):
            for res in fut.result():
                a1, a2, winner, hp1, hp2, err = res
                done += 1
                if err:        errors += 1
                elif winner == "tree1": wins += 1
                elif winner == "draw":  draws += 1
                else:                  losses += 1
                if done % 20 == 0:
                    elapsed = (datetime.now() - start).total_seconds()
                    eta = elapsed / done * (total - done) if done else 0
                    print(f"  {done}/{total}  W/D/L/E={wins}/{draws}/{losses}/{errors}"
                          f"  ETA {eta/60:.1f}m", flush=True)

    elapsed = (datetime.now() - start).total_seconds()
    print(f"완료: {total}매치  W/D/L/E={wins}/{draws}/{losses}/{errors}"
          f"  소요={elapsed/60:.1f}분")


if __name__ == "__main__":
    mp.freeze_support()
    main()
