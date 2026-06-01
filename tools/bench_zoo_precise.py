"""정확한 5x bench (2026-05-31).

기존 /tmp/h5_bench.py 의 'wins = sum(d>0)' 는 health_adv judge 무시. 본 도구는:
  - dmg dealt/taken regex
  - judge 결과 ("승자: X [reason]") 직접 파싱 → WIN/DRAW/LOSS
  - dmg 분포 (mean/std/min/max/individual)

usage:
    python tools/bench_zoo_precise.py [--n-runs 5] [--opps simple,defensive,...]
"""
from __future__ import annotations
import argparse, re, statistics, subprocess, sys
from pathlib import Path

DMG_RE = re.compile(r"(\S+):\s+[\d.]+\s+HP\s*\(데미지\s+([\d.]+)\s+가함\)")
JUDGE_RE = re.compile(r"승자:\s+(\S+)\s+\[([^\]]+)\]")
OUR_BT = "pursuit_chase_btcost"

PLAIN = ["simple", "defensive", "aggressive", "ace"]
ADAPTIVE = ["v6", "v6h2", "v6h4", "v6h5a", "v6h5b", "v6h5c",
            "v6h_e1", "v6h_e1b", "v6h_e1c", "v6h_e1d",
            "v7", "v8", "v9", "v10", "v11_code", "v51"]


def opp_full(o):
    return o if o in PLAIN else f"adaptive_eagle_{o}"


def run_one(opp, root):
    cmd = ["python", "scripts/run_match.py",
           "--agent1", f"examples/pursuit_chase_v1/pursuit_chase_btcost.yaml",
           "--agent2", opp_full(opp), "--rounds", "1",
           "--max-steps", "1500", "--scenario", "bt_vs_bt"]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=300, cwd=root)
    out = r.stdout + r.stderr
    # parse dmg per agent
    dmg = {}
    for m in DMG_RE.finditer(out):
        name, val = m.group(1), float(m.group(2))
        dmg[name] = val
    # "X: N HP (데미지 D 가함)" → "X 가 D damage 받음" 의미 (한국어 문법: 가함 = applied to subject).
    # 그러므로 적이 받은 dmg = 우리가 가한 dmg.
    taken = dmg.get(OUR_BT, 0.0)
    dealt = sum(v for k, v in dmg.items() if k != OUR_BT) or 0.0
    # parse judge result
    jm = JUDGE_RE.search(out)
    if jm:
        winner, reason = jm.group(1), jm.group(2)
        if winner == OUR_BT:
            verdict = "WIN"
        elif winner == "무승부":
            verdict = "DRAW"
        else:
            verdict = "LOSS"
    else:
        verdict = "?"
        reason = ""
    return dealt, taken, verdict, reason


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n-runs", type=int, default=5)
    ap.add_argument("--opps", default=",".join(PLAIN + ADAPTIVE))
    args = ap.parse_args()

    root = Path(".").resolve()
    opps = args.opps.split(",")
    tot_dealt = 0.0
    tot_taken = 0.0
    tot_wins = 0
    tot_draws = 0
    tot_losses = 0
    tot_runs = 0
    print(f"{'opp':<14} {'dealt mean±std':18} {'taken':>7} {'verdicts':30} {'individual dmg'}")
    print("-" * 110)
    for opp in opps:
        deals, takens, verds = [], [], []
        for _ in range(args.n_runs):
            d, t, v, _ = run_one(opp, root)
            deals.append(d); takens.append(t); verds.append(v)
        dm = statistics.mean(deals)
        ds = statistics.stdev(deals) if len(deals) > 1 else 0.0
        tm = statistics.mean(takens)
        win = sum(1 for v in verds if v == "WIN")
        drw = sum(1 for v in verds if v == "DRAW")
        los = sum(1 for v in verds if v == "LOSS")
        tot_dealt += sum(deals)
        tot_taken += sum(takens)
        tot_wins += win; tot_draws += drw; tot_losses += los
        tot_runs += args.n_runs
        ind = " ".join(f"{d:5.1f}" for d in deals)
        v_str = f"W={win} D={drw} L={los}"
        print(f"{opp:<14} {dm:6.2f}±{ds:5.1f}      {tm:6.2f} {v_str:30} {ind}", flush=True)
    print("-" * 110)
    print(f"=== TOTAL: dealt={tot_dealt:.1f} taken={tot_taken:.1f} "
          f"W={tot_wins} D={tot_draws} L={tot_losses} / {tot_runs} ===")


if __name__ == "__main__":
    main()
