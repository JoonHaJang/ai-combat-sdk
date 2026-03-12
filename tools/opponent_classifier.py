"""
Opponent State Classifier

Given our 19-dimensional observation dict (OUR perspective), infers which BT
branch the opponent is likely executing.

Core geometric insight
----------------------
The obs dict describes our relationship to the opponent:

  aa_deg  (0–1, = AA/180°):
      0 → we are at the OPPONENT'S 6 o'clock (we have offensive rear-aspect).
          Opponent's own aa_deg from their view → HIGH → their UnderThreat fires.
          → Opponent enters DEFENSIVE branch.
      1 → we are at the OPPONENT'S 12 o'clock (we're exposed, opp has our rear).
          → Opponent stays OFFENSIVE.

  ata_deg (0–1, = ATA/180°):
      0 → our nose points directly at opponent (we're aimed at them).
      1 → we're pointed away.

  distance: symmetric, both agents see the same value.

  tc_type: '1-circle' if HCA < 90° (same-direction turns),
           '2-circle' if HCA ≥ 90° (opposing turns).

  energy_diff: OUR energy - THEIR energy. Positive → we're faster/higher.

Usage
-----
    from tools.opponent_classifier import classify_opponent, OpponentMode

    mode_info = classify_opponent(obs, opponent_type='ace')
    print(mode_info['mode'], mode_info['likely_action'], mode_info['counter'])

    # Or just get the mode string
    mode = classify_opponent(obs)['mode']
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Opponent mode constants
# ---------------------------------------------------------------------------

class OpponentMode:
    HARD_DECK     = 'HARD_DECK'       # opp near ground → ClimbTo active
    GUN_ATTACK    = 'GUN_ATTACK'      # opp has us in WEZ → about to fire
    DEFENSIVE     = 'DEFENSIVE'       # we're at opp's rear → opp evading
    OFFENSIVE     = 'OFFENSIVE'       # opp has our rear → opp pursuing
    NEUTRAL_1C    = 'NEUTRAL_1CIRCLE' # 1-circle turn fight
    NEUTRAL_2C    = 'NEUTRAL_2CIRCLE' # 2-circle / energy fight


# ---------------------------------------------------------------------------
# Opponent-type-specific action predictions
# ---------------------------------------------------------------------------

_DEFENSIVE_ACTIONS = {
    'ace':        'DefensiveManeuver / BreakTurn / HighYoYo (DBFM tree)',
    'aggressive': 'Pursue (no dedicated defense)',
    'simple':     'Pursue (no dedicated defense)',
    'defensive':  'DefensiveManeuver (aa_threshold=120°)',
    'eagle1':     'DefensiveManeuver (aa_threshold=120°)',
    'viper1':     'DefensiveManeuver (IsDefensiveSituation)',
}

_OFFENSIVE_ACTIONS = {
    'ace':        'LeadPursuit / OneCircleFight / LagPursuit (OBFM tree)',
    'aggressive': 'Pursue (aggressive params: close_range=2500)',
    'simple':     'Pursue',
    'defensive':  'LeadPursuit (DistanceBelow 2000m)',
    'eagle1':     'LeadPursuit (DistanceBelow 2500m)',
    'viper1':     'ViperStrike (custom TAU-based action)',
}

_NEUTRAL_1C_ACTIONS = {
    'ace':        'OneCircleFight (IsNeutralSituation branch)',
    'aggressive': 'Pursue',
    'simple':     'Pursue',
    'defensive':  'Pursue',
    'eagle1':     'Pursue',
    'viper1':     'Pursue or ViperStrike',
}

_NEUTRAL_2C_ACTIONS = {
    'ace':        'ClimbingTurn(auto) / HighYoYo (IsNeutralSituation)',
    'aggressive': 'Pursue + Accelerate (parallel)',
    'simple':     'Pursue',
    'defensive':  'Pursue',
    'eagle1':     'Pursue',
    'viper1':     'Pursue',
}

# ---------------------------------------------------------------------------
# Counter-strategy recommendations
# ---------------------------------------------------------------------------

_COUNTERS = {
    OpponentMode.HARD_DECK:  'PURSUE_AGGRESSIVE — opp is recovering altitude, press attack',
    OpponentMode.GUN_ATTACK: 'BREAK_TURN — evade immediately, opp is firing',
    OpponentMode.DEFENSIVE:  'PRESS_ATTACK — opp is evading, LeadPursuit to cut corners',
    OpponentMode.OFFENSIVE:  'EVASION — barrel roll or defensive spiral to break lock',
    OpponentMode.NEUTRAL_1C: 'ONE_CIRCLE — tight turn + decel, fight for inside radius',
    OpponentMode.NEUTRAL_2C: 'ENERGY_FIGHT — maintain energy, LagPursuit, wait for WEZ',
}


# ---------------------------------------------------------------------------
# Main classifier
# ---------------------------------------------------------------------------

def classify_opponent(obs: dict, opponent_type: str | None = None) -> dict:
    """Infer opponent's current BT branch from our observation dict.

    Parameters
    ----------
    obs : dict
        The observation dict from our agent's blackboard.
    opponent_type : str, optional
        One of 'ace', 'aggressive', 'simple', 'defensive', 'eagle1', 'viper1'.
        If None, returns generic predictions.

    Returns
    -------
    dict with keys:
        mode          : str (OpponentMode constant)
        confidence    : float 0–1
        likely_action : str (human-readable description)
        counter       : str (recommended counter-strategy)
        details       : str (reasoning)
    """
    aa       = obs.get('aa_deg', 0.5) * 180   # 0=opp rear, 180=opp front
    ata      = obs.get('ata_deg', 0.5) * 180   # 0=we aim at opp
    distance = obs.get('distance', 5000.0)
    tc_type  = obs.get('tc_type', '2-circle')
    energy_diff = obs.get('energy_diff', 0.0)  # positive → we have advantage
    alt_gap  = obs.get('alt_gap', 0.0)          # positive → opp is above
    ego_alt  = obs.get('ego_altitude', 5000.0)

    # Estimated opponent altitude
    opp_alt  = ego_alt + alt_gap

    def _action(table):
        return table.get(opponent_type, 'unknown (generic opponent)') \
               if opponent_type else 'unknown (no opponent type given)'

    # ── 1. HARD DECK: opponent near crash altitude ──────────────────────────
    if opp_alt < 600:
        return {
            'mode': OpponentMode.HARD_DECK,
            'confidence': 0.90,
            'likely_action': 'ClimbTo (emergency altitude recovery)',
            'counter': _COUNTERS[OpponentMode.HARD_DECK],
            'details': f'Opp altitude ~{opp_alt:.0f}m < 600m → BelowHardDeck fires → ClimbTo active',
        }

    # ── 2. GUN_ATTACK: opponent has us in their WEZ ─────────────────────────
    # Proxy for opponent's ATA = how well they're pointing at us.
    # If we're at their 12-o'clock (our aa is HIGH), they're pointing at us.
    # Opponent's ATA proxy ≈ (1 - our aa_deg) * 180
    opp_ata_proxy = (1.0 - obs.get('aa_deg', 0.5)) * 180
    if 152 < distance < 914 and opp_ata_proxy < 12:
        return {
            'mode': OpponentMode.GUN_ATTACK,
            'confidence': 0.80,
            'likely_action': 'GunAttack / PNAttack (WEZ engagement)',
            'counter': _COUNTERS[OpponentMode.GUN_ATTACK],
            'details': (f'dist={distance:.0f}m in WEZ range, opp_ata_proxy={opp_ata_proxy:.0f}° '
                        f'→ opponent likely firing'),
        }

    # ── 3. DEFENSIVE: we have rear-aspect on opponent ───────────────────────
    # Our aa_deg low (< 0.4) → we're at opp's 6 o'clock → opp's aa is HIGH →
    # opp's UnderThreat(aa_threshold) fires → defensive branch active
    if aa < 70:
        conf = 0.85 - aa / 300  # higher confidence when aa is very low
        action = _action(_DEFENSIVE_ACTIONS)

        # Refine for ace (DBFM sub-branches)
        if opponent_type == 'ace':
            if aa < 30:
                action = 'BreakTurn (ace DBFM: aa > 130° threshold)'
            elif aa < 50:
                action = 'DefensiveManeuver (ace DBFM: aa > 100° threshold)'
            else:
                action = 'HighYoYo or AltitudeAdvantage (ace DBFM)'

        return {
            'mode': OpponentMode.DEFENSIVE,
            'confidence': round(conf, 2),
            'likely_action': action,
            'counter': _COUNTERS[OpponentMode.DEFENSIVE],
            'details': (f'Our aa={aa:.0f}° → we are at opp rear → '
                        f'opp UnderThreat/IsDefensive fires'),
        }

    # ── 4. OFFENSIVE: opponent has rear-aspect on us ────────────────────────
    # Our aa_deg high → we're in opp's front hemisphere → opp is behind us →
    # opp is in attack/pursuit mode
    if aa > 130:
        action = _action(_OFFENSIVE_ACTIONS)
        return {
            'mode': OpponentMode.OFFENSIVE,
            'confidence': 0.75,
            'likely_action': action,
            'counter': _COUNTERS[OpponentMode.OFFENSIVE],
            'details': (f'Our aa={aa:.0f}° → opp at our 6 o\'clock → '
                        f'opp IsOffensive/Pursue active'),
        }

    # ── 5. NEUTRAL — turn fight geometry ────────────────────────────────────
    if tc_type == '1-circle':
        action = _action(_NEUTRAL_1C_ACTIONS)
        return {
            'mode': OpponentMode.NEUTRAL_1C,
            'confidence': 0.70,
            'likely_action': action,
            'counter': _COUNTERS[OpponentMode.NEUTRAL_1C],
            'details': ('1-circle turn (HCA < 90°): same-direction spiral, '
                        'inside radius wins'),
        }
    else:
        action = _action(_NEUTRAL_2C_ACTIONS)
        return {
            'mode': OpponentMode.NEUTRAL_2C,
            'confidence': 0.68,
            'likely_action': action,
            'counter': _COUNTERS[OpponentMode.NEUTRAL_2C],
            'details': ('2-circle turn (HCA ≥ 90°): opposing arcs, '
                        'energy state determines outcome'),
        }


# ---------------------------------------------------------------------------
# Step-log analysis: batch classification over a CSV log file
# ---------------------------------------------------------------------------

def analyze_log(log_path: str, opponent_type: str | None = None) -> dict:
    """Read a StepLogger CSV and classify each step.

    Returns a summary dict:
        total_steps  : int
        mode_counts  : {mode: count}
        mode_pcts    : {mode: percentage}
        transitions  : list of (step, mode) tuples where mode changed
    """
    import csv

    rows = []
    with open(log_path, newline='', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            # Convert numeric fields
            parsed = {}
            for k, v in row.items():
                try:
                    parsed[k] = float(v)
                except (ValueError, TypeError):
                    parsed[k] = v
            rows.append(parsed)

    mode_counts: dict[str, int] = {}
    transitions = []
    prev_mode = None

    for row in rows:
        result = classify_opponent(row, opponent_type=opponent_type)
        mode = result['mode']
        mode_counts[mode] = mode_counts.get(mode, 0) + 1

        if mode != prev_mode:
            transitions.append((int(row.get('step', 0)), mode))
            prev_mode = mode

    total = len(rows)
    mode_pcts = {m: round(c / total * 100, 1) for m, c in mode_counts.items()} if total else {}

    return {
        'total_steps': total,
        'mode_counts': mode_counts,
        'mode_pcts': mode_pcts,
        'transitions': transitions,
    }


# ---------------------------------------------------------------------------
# CLI: quick test / single-obs debug
# ---------------------------------------------------------------------------

if __name__ == '__main__':
    import argparse
    import json
    import sys
    from pathlib import Path

    parser = argparse.ArgumentParser(description='Classify opponent state from observation')
    parser.add_argument('--test', action='store_true', help='Run built-in test cases')
    parser.add_argument('--log', type=str, help='Analyze a StepLogger CSV file')
    parser.add_argument('--opponent', type=str, default=None,
                        help='Opponent type (ace/aggressive/simple/defensive/eagle1/viper1)')
    args = parser.parse_args()

    if args.log:
        result = analyze_log(args.log, opponent_type=args.opponent)
        print(json.dumps(result, indent=2))
        
        # 결과를 logs 폴더에 저장
        try:
            # PROJECT_ROOT 계산 (이 파일이 tools/ 안에 있으므로)
            script_dir = Path(__file__).parent
            project_root = script_dir.parent
            logs_dir = project_root / "logs"
            logs_dir.mkdir(exist_ok=True)
            
            log_name = Path(args.log).stem
            output_path = logs_dir / f"{log_name}_classification.json"
            with open(output_path, 'w', encoding='utf-8') as f:
                json.dump(result, f, indent=2)
            print(f"\n분석 결과 저장: {output_path}")
        except Exception as e:
            print(f"\n경고: 결과 저장 실패 - {e}")
        
        sys.exit(0)

    if args.test:
        test_cases = [
            ('WE are at opp rear (offensive)',
             {'aa_deg': 0.1, 'ata_deg': 0.1, 'distance': 2000, 'tc_type': '1-circle',
              'energy_diff': 300, 'alt_gap': 0, 'ego_altitude': 4000}),
            ('OPP is at our rear (defensive)',
             {'aa_deg': 0.85, 'ata_deg': 0.8, 'distance': 1500, 'tc_type': '2-circle',
              'energy_diff': -200, 'alt_gap': -100, 'ego_altitude': 4000}),
            ('Opp near hard deck',
             {'aa_deg': 0.3, 'ata_deg': 0.2, 'distance': 3000, 'tc_type': '2-circle',
              'energy_diff': 500, 'alt_gap': -3800, 'ego_altitude': 4000}),
            ('Opp in WEZ (gun attack)',
             {'aa_deg': 0.95, 'ata_deg': 0.5, 'distance': 500, 'tc_type': '1-circle',
              'energy_diff': 0, 'alt_gap': 0, 'ego_altitude': 4000}),
            ('Neutral 1-circle',
             {'aa_deg': 0.5, 'ata_deg': 0.5, 'distance': 1800, 'tc_type': '1-circle',
              'energy_diff': 0, 'alt_gap': 0, 'ego_altitude': 4000}),
        ]

        for desc, obs in test_cases:
            r = classify_opponent(obs, opponent_type=args.opponent or 'ace')
            print(f'\n[{desc}]')
            print(f'  Mode:    {r["mode"]} (conf={r["confidence"]})')
            print(f'  Opp:     {r["likely_action"]}')
            print(f'  Counter: {r["counter"]}')
            print(f'  Why:     {r["details"]}')
