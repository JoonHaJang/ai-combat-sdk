"""
Counter-Strategy Builder

Analyzes StepLogger CSV files to build an empirical counter-strategy table.

Pipeline
--------
  1. Run matches with StepLogger enabled in alpha1_adaptive.yaml:

       python scripts/run_match.py \\
           --agent submissions/alpha1/alpha1_adaptive.yaml \\
           --opponent ace --rounds 3

     (Uncomment the StepLogger block in alpha1_adaptive.yaml first.)

  2. Analyze the resulting CSV files:

       python tools/counter_strategy_builder.py --log-dir logs/alpha1 --opponent ace

  3. Check the counter-strategy table output.

Usage
-----
    # Analyze one log file
    python tools/counter_strategy_builder.py --log logs/alpha1/steps_123.csv --opponent ace

    # Analyze all logs in a directory
    python tools/counter_strategy_builder.py --log-dir logs/alpha1 --opponent ace

    # Test the classifier with built-in test cases
    python tools/opponent_classifier.py --test --opponent ace

    # Run a quick validation tournament
    python tools/bt_optimizer.py --tournament --agent submissions/alpha1/alpha1_adaptive.yaml
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import defaultdict
from pathlib import Path

# Make project importable
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# Import from same directory
try:
    from opponent_classifier import classify_opponent, OpponentMode
except ImportError:
    # SDK 환경에서는 tools 경로로 import
    from tools.opponent_classifier import classify_opponent, OpponentMode


# ---------------------------------------------------------------------------
# Log analysis
# ---------------------------------------------------------------------------

def analyze_log_file(log_path: str | Path, opponent_type: str | None = None) -> dict:
    """Read one StepLogger CSV and classify each step."""
    rows = []
    with open(log_path, newline='', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            parsed = {}
            for k, v in row.items():
                try:
                    parsed[k] = float(v)
                except (ValueError, TypeError):
                    parsed[k] = v
            rows.append(parsed)

    mode_counts: dict[str, int] = defaultdict(int)
    prev_mode = None
    transitions: list[tuple[int, str]] = []

    for row in rows:
        result = classify_opponent(row, opponent_type=opponent_type)
        mode = result['mode']
        mode_counts[mode] += 1
        if mode != prev_mode:
            transitions.append((int(float(row.get('step', 0))), mode))
            prev_mode = mode

    total = len(rows)
    mode_pcts = {m: round(c / total * 100, 1) for m, c in mode_counts.items()} if total else {}

    return {
        'file': str(log_path),
        'total_steps': total,
        'mode_counts': dict(mode_counts),
        'mode_pcts': mode_pcts,
        'transitions': transitions,
    }


def analyze_directory(log_dir: str | Path, opponent_type: str | None = None) -> dict:
    """Aggregate analysis over all CSV files in a directory."""
    log_dir = Path(log_dir)
    csv_files = sorted(log_dir.glob('steps_*.csv'))

    if not csv_files:
        print(f'No steps_*.csv files found in {log_dir}')
        return {}

    combined_counts: dict[str, int] = defaultdict(int)
    all_files = []

    for path in csv_files:
        result = analyze_log_file(path, opponent_type=opponent_type)
        all_files.append(result)
        for mode, count in result['mode_counts'].items():
            combined_counts[mode] += count

    total = sum(combined_counts.values())
    combined_pcts = {m: round(c / total * 100, 1) for m, c in combined_counts.items()} if total else {}

    return {
        'log_dir': str(log_dir),
        'files_analyzed': len(csv_files),
        'total_steps': total,
        'mode_counts': dict(combined_counts),
        'mode_pcts': combined_pcts,
        'per_file': all_files,
    }


# ---------------------------------------------------------------------------
# Counter-strategy table printer
# ---------------------------------------------------------------------------

COUNTER_TABLE = {
    OpponentMode.HARD_DECK: {
        'obs_signature': 'opp_alt < 600m (estimated from ego_altitude + alt_gap)',
        'opp_action': 'ClimbTo (altitude recovery, temporarily non-threatening)',
        'our_best': 'LeadPursuit or PNAttack — press attack while opp is occupied',
        'rationale': 'Opponent is in emergency recovery, not attacking. '
                     'This is the highest-value offensive window.',
    },
    OpponentMode.GUN_ATTACK: {
        'obs_signature': 'distance 152-914m + opp_ata_proxy < 12° (aa_deg > 0.93)',
        'opp_action': 'GunAttack / PNAttack — firing at us',
        'our_best': 'BreakTurn — hard lateral turn to exit LOS cone immediately',
        'rationale': 'We are in opponent\'s WEZ. Every 0.2s costs ~5 HP. Break now.',
    },
    OpponentMode.DEFENSIVE: {
        'obs_signature': 'aa_deg < 0.39 (we are within 70° of opp\'s 6 o\'clock)',
        'opp_action': 'BreakTurn / DefensiveManeuver / HighYoYo (opponent evading)',
        'our_best': 'LeadPursuit — cut inside the evading aircraft\'s turn circle',
        'rationale': 'Opponent is reacting defensively; LeadPursuit creates WEZ shot '
                     'before they complete the maneuver.',
    },
    OpponentMode.OFFENSIVE: {
        'obs_signature': 'aa_deg > 0.72 (opp has our 6 o\'clock)',
        'opp_action': 'LeadPursuit / Pursue / ViperStrike (opponent attacking us)',
        'our_best': 'BarrelRoll or DefensiveSpiral — create overshoot, break lock',
        'rationale': 'Opponent is inside our turn circle. BarrelRoll forces an '
                     'overshoot and resets the geometry.',
    },
    OpponentMode.NEUTRAL_1C: {
        'obs_signature': 'tc_type == "1-circle" (HCA < 90°, same-direction turns)',
        'opp_action': 'OneCircleFight / ClimbingTurn (tight spiral)',
        'our_best': 'LeadPursuit + decel — tightest turn wins 1-circle fight',
        'rationale': 'In 1-circle, both aircraft spiral inward. The one with '
                     'tighter turn radius (lower speed, higher bank) gets the shot.',
    },
    OpponentMode.NEUTRAL_2C: {
        'obs_signature': 'tc_type == "2-circle" (HCA ≥ 90°, opposing turns)',
        'opp_action': 'TwoCircleFight / Pursue (energy fight, wider arcs)',
        'our_best': 'LagPursuit + maintain energy — wait for geometry to improve',
        'rationale': 'In 2-circle, aircraft arc away then re-merge. '
                     'Energy advantage determines who gets the next merge shot.',
    },
}


def print_counter_table():
    """Print the static counter-strategy reference table."""
    print('\n' + '=' * 70)
    print('  COUNTER-STRATEGY REFERENCE TABLE')
    print('=' * 70)
    for mode, info in COUNTER_TABLE.items():
        print(f'\n  [{mode}]')
        print(f'  Obs Signature : {info["obs_signature"]}')
        print(f'  Opp Action    : {info["opp_action"]}')
        print(f'  Our Best      : {info["our_best"]}')
        print(f'  Rationale     : {info["rationale"]}')
    print()


# ---------------------------------------------------------------------------
# Mutation experiment runner
# ---------------------------------------------------------------------------

def run_mutation_experiment(opponent_base: str, n_rounds: int = 5) -> None:
    """Compare alpha1 v6 vs v7-adaptive against an opponent.

    Prints W/D/L for both versions to compare impact of adaptive logic.
    """
    # Import run_match
    try:
        from scripts.run_match import run_match
    except ImportError:
        sys.path.insert(0, str(PROJECT_ROOT.parent))
        from scripts.run_match import run_match

    agents = {
        'v6 (stable)':   'submissions/alpha1/alpha1.yaml',
        'v7 (adaptive)': 'submissions/alpha1/alpha1_adaptive.yaml',
    }

    print(f'\n{"=" * 60}')
    print(f'  Mutation Experiment: vs {opponent_base} ({n_rounds} rounds)')
    print(f'{"=" * 60}\n')

    for label, agent_path in agents.items():
        results = run_match(
            agent1=str(PROJECT_ROOT / agent_path),
            agent2=opponent_base,
            rounds=n_rounds,
            verbose=False,
        )
        wins   = sum(1 for r in results if r.get('winner') == 'tree1')
        draws  = sum(1 for r in results if r.get('winner') == 'draw')
        losses = n_rounds - wins - draws
        hp_diffs = [r.get('tree1_health', 100) - r.get('tree2_health', 100)
                    for r in results]
        avg_hp = sum(hp_diffs) / max(1, len(hp_diffs))

        status = 'WIN' if wins > losses else ('DRAW' if wins == losses else 'LOSE')
        print(f'  {label:20s}: {wins}W {draws}D {losses}L  '
              f'avg_hp_diff={avg_hp:+.0f}  [{status}]')

    print()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description='Counter-Strategy Builder')
    parser.add_argument('--log', type=str, help='Single StepLogger CSV to analyze')
    parser.add_argument('--log-dir', type=str, help='Directory of StepLogger CSVs')
    parser.add_argument('--opponent', type=str, default=None,
                        choices=['ace', 'aggressive', 'simple', 'defensive',
                                 'eagle1', 'viper1'],
                        help='Opponent type for prediction refinement')
    parser.add_argument('--table', action='store_true',
                        help='Print static counter-strategy reference table')
    parser.add_argument('--experiment', action='store_true',
                        help='Run v6 vs v7-adaptive comparison experiment')
    parser.add_argument('--rounds', type=int, default=3,
                        help='Rounds for --experiment (default: 3)')
    args = parser.parse_args()

    if args.table:
        print_counter_table()

    if args.log:
        result = analyze_log_file(args.log, opponent_type=args.opponent)
        print(json.dumps(result, indent=2))
        
        # 결과를 logs 폴더에 저장
        logs_dir = PROJECT_ROOT / "logs"
        logs_dir.mkdir(exist_ok=True)
        log_name = Path(args.log).stem
        output_path = logs_dir / f"{log_name}_analysis.json"
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(result, f, indent=2)
        print(f"\n분석 결과 저장: {output_path}")

    if args.log_dir:
        result = analyze_directory(args.log_dir, opponent_type=args.opponent)
        print(f'\nAggregated Analysis: {result["files_analyzed"]} files, '
              f'{result["total_steps"]} steps')
        print('\nOpponent Mode Distribution:')
        for mode, pct in sorted(result['mode_pcts'].items(),
                                key=lambda x: -x[1]):
            bar = '█' * int(pct / 2)
            print(f'  {mode:20s} {pct:5.1f}%  {bar}')
        
        # 결과를 logs 폴더에 저장
        logs_dir = PROJECT_ROOT / "logs"
        logs_dir.mkdir(exist_ok=True)
        dir_name = Path(args.log_dir).name
        output_path = logs_dir / f"{dir_name}_aggregated_analysis.json"
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(result, f, indent=2)
        print(f'\n분석 결과 저장: {output_path}')

    if args.experiment:
        opponents = ([args.opponent] if args.opponent
                     else ['ace', 'aggressive', 'simple', 'defensive', 'eagle1', 'viper1'])
        for opp in opponents:
            run_mutation_experiment(opp, n_rounds=args.rounds)

    if not any([args.table, args.log, args.log_dir, args.experiment]):
        # Default: print table + run experiment
        print_counter_table()
        print('Run with --experiment to compare v6 vs v7-adaptive.')
        print('Run with --log-dir logs/alpha1 to analyze StepLogger output.')


if __name__ == '__main__':
    main()
