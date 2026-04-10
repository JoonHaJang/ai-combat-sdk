"""
generate_opponent_pool.py — 체계적 상대 BT 풀 생성기 (SE 1차 원칙)

직교 축에 따라 전술 공간을 분할하고, 각 셀을 채우는 BT를 자동 생성.
168개 경험적 아키타입 대신 ~700개 직교 설계 풀을 만들어
통계적으로 유의한 Universal Claim 검증용으로 사용.

설계 원칙
─────────────────────────────────────────────────────────────
1. 직교 축 (Orthogonal Tactical Axes)
   - Phase Focus     : OBFM / DBFM / HABFM / MIXED
   - Range Preference: GUN(<914ft) / CLOSE(<3000) / MID(<6000) / LONG(>6000)
   - Energy          : PRESERVE / TRADE / IGNORE
   - Aggression      : PASSIVE / BALANCED / AGGRESSIVE
   - Primary Action  : ~30 builtin actions 전수
   - Altitude Bias   : HIGH / LEVEL / LOW

2. 레이어 구조
   L1 Pure single-action      :  90  (action × 속도 프리셋)
   L2 Condition-gated 2-branch: 240  (cond × action × fallback)
   L3 Phase-decomposed 3-branch:120  (phase × range × action)
   L4 Pursue param sweep (LHS):  80
   L5 Orthogonal 4-axis cross : 144
   L6 Counter-strategy(manual):  30
   ─────────────────────────────────
   ≈ 704 opponents

3. 통계 규모
   10 rounds × 704 opp = 7040 matches/eval
   Wilson CI @ 50% WR: ±1.17% (universal claim 가능 수준)

사용:
    python tools/generate_opponent_pool.py              # 전체 생성
    python tools/generate_opponent_pool.py --layer L1   # 특정 레이어
    python tools/generate_opponent_pool.py --count      # 규모만 확인
    python tools/generate_opponent_pool.py --clean      # 이전 풀 삭제 후 재생성
"""

import argparse
import json
import shutil
import sys
from itertools import product
from pathlib import Path

import yaml

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

OUTPUT_DIR = PROJECT_ROOT / "examples" / "opponent_pool"
MANIFEST_PATH = OUTPUT_DIR / "manifest.json"

# ─── 빌트인 Action Space (NODE_REFERENCE 기반) ──────────────────

PURSUIT_ACTIONS = ["LeadPursuit", "PurePursuit", "LagPursuit", "Pursue"]
GUN_ACTIONS = ["GunAttack"]
DEFENSIVE_ACTIONS = ["BreakTurn", "DefensiveSpiral", "DefensiveManeuver",
                     "BarrelRoll", "Evade"]
ENERGY_ACTIONS = ["HighYoYo", "LowYoYo", "ClimbingTurn", "DescendingTurn",
                  "AltitudeAdvantage", "ClimbTo", "DescendTo"]
HABFM_ACTIONS = ["OneCircleFight", "TwoCircleFight", "EnergyFight", "TCFight"]
UTILITY_ACTIONS = ["Straight", "Accelerate", "Decelerate",
                   "TurnLeft", "TurnRight", "MaintainAltitude"]

ALL_ACTIONS = (PURSUIT_ACTIONS + GUN_ACTIONS + DEFENSIVE_ACTIONS
               + ENERGY_ACTIONS + HABFM_ACTIONS + UTILITY_ACTIONS)

# ─── BT 빌더 프리미티브 ────────────────────────────────────────

def _sel(children, name="Root"):
    return {"type": "Selector", "name": name, "children": children}

def _seq(name, children):
    return {"type": "Sequence", "name": name, "children": children}

def _cond(name, **params):
    node = {"type": "Condition", "name": name}
    if params:
        node["params"] = params
    return node

def _act(name, **params):
    node = {"type": "Action", "name": name}
    if params:
        node["params"] = params
    return node

def _hard_deck(alt=1000, recover=3000):
    """모든 BT에 공통. Hard Deck 회피 최우선."""
    return _seq("HardDeck", [
        _cond("BelowHardDeck", threshold_ft=alt),
        _act("ClimbTo", target_altitude_ft=recover),
    ])

def _wrap_yaml(name, description, tree):
    return {
        "name": name,
        "version": "1.0.0",
        "description": description,
        "tree": tree,
    }


# ═══════════════════════════════════════════════════════════════
# Layer 1 — Pure Single Action (90개)
# 각 액션이 기본, 3가지 속도 프리셋으로 파라미터화
# ═══════════════════════════════════════════════════════════════

def gen_layer1_pure():
    records = []
    speed_presets = [
        ("slow",    {"vel_idx": 1}),
        ("medium",  {"vel_idx": 2}),
        ("fast",    {"vel_idx": 4}),
    ]
    for action in ALL_ACTIONS:
        for label, _ in speed_presets:
            name = f"L1_pure_{action.lower()}_{label}"
            # 단순 구조: HardDeck → GunChance → Action
            tree = _sel([
                _hard_deck(),
                _seq("GunChance", [
                    _cond("DistanceBelow", threshold_ft=1000),
                    _cond("ATABelow", threshold_deg=10.0),
                    _act("GunAttack"),
                ]),
                _act(action),
            ])
            records.append(dict(
                name=name,
                layer="L1",
                category="pure",
                primary_action=action,
                speed=label,
                yaml=_wrap_yaml(name, f"L1 Pure: {action} ({label})", tree),
            ))
    return records


# ═══════════════════════════════════════════════════════════════
# Layer 2 — Condition-gated 2-branch (240개)
# IF cond THEN primary ELSE fallback
# ═══════════════════════════════════════════════════════════════

L2_CONDITIONS = [
    ("IsOffensiveSituation", {}),
    ("IsDefensiveSituation", {}),
    ("IsNeutralSituation",   {}),
    ("EnemyInRange",         {}),
    ("DistanceBelow",        {"threshold_ft": 3000}),
    ("AltitudeAbove",        {"min_altitude_ft": 12000}),
    ("IsEnergyAdvantage",    {}),
    ("IsAltAdvantage",       {}),
    ("IsOvershootRisk",      {}),
    ("IsMerged",             {}),
]

L2_PRIMARY = [
    "LeadPursuit", "PurePursuit", "LagPursuit", "GunAttack",
    "BreakTurn", "HighYoYo", "OneCircleFight", "ClimbingTurn",
]

L2_FALLBACK = ["Pursue", "LagPursuit", "ClimbTo"]

def gen_layer2_gated():
    records = []
    for (cname, cparams), primary, fallback in product(L2_CONDITIONS, L2_PRIMARY, L2_FALLBACK):
        name = f"L2_{cname}_{primary}_{fallback}".replace("Is", "")
        primary_branch = _seq(f"If_{cname}", [
            _cond(cname, **cparams),
            _act(primary),
        ])
        if fallback == "ClimbTo":
            fb = _act(fallback, target_altitude_ft=15000)
        else:
            fb = _act(fallback)
        tree = _sel([_hard_deck(), primary_branch, fb])
        records.append(dict(
            name=name, layer="L2", category="gated",
            condition=cname, primary_action=primary, fallback_action=fallback,
            yaml=_wrap_yaml(name, f"L2 Gated: {cname}?{primary}:{fallback}", tree),
        ))
    return records


# ═══════════════════════════════════════════════════════════════
# Layer 3 — Phase-decomposed 3-branch (120개)
# Offensive / Defensive / Neutral 각각에 전용 action
# ═══════════════════════════════════════════════════════════════

L3_OFFENSIVE = ["LeadPursuit", "PurePursuit", "GunAttack", "Pursue", "LagPursuit"]
L3_DEFENSIVE = ["BreakTurn", "DefensiveSpiral", "BarrelRoll", "Evade"]
L3_NEUTRAL   = ["OneCircleFight", "TwoCircleFight", "HighYoYo",
                "ClimbingTurn", "LagPursuit", "EnergyFight"]

def gen_layer3_phase():
    records = []
    i = 0
    for off, dfn, neu in product(L3_OFFENSIVE, L3_DEFENSIVE, L3_NEUTRAL):
        i += 1
        if i > 120:
            break
        name = f"L3_phase_{off}_{dfn}_{neu}"
        tree = _sel([
            _hard_deck(),
            _seq("GunChance", [
                _cond("DistanceBelow", threshold_ft=914),
                _cond("ATABelow", threshold_deg=12.0),
                _act("GunAttack"),
            ]),
            _seq("OffensivePhase", [
                _cond("IsOffensiveSituation"),
                _act(off),
            ]),
            _seq("DefensivePhase", [
                _cond("IsDefensiveSituation"),
                _act(dfn),
            ]),
            _seq("NeutralPhase", [
                _cond("IsNeutralSituation"),
                _act(neu),
            ]),
            _act("Pursue"),
        ])
        records.append(dict(
            name=name, layer="L3", category="phase",
            offensive=off, defensive=dfn, neutral=neu,
            yaml=_wrap_yaml(name, f"L3 Phase: O={off} D={dfn} N={neu}", tree),
        ))
    return records


# ═══════════════════════════════════════════════════════════════
# Layer 4 — YAML-level Threshold LHS Sweep (80개)
# 확실히 지원되는 빌트인 cond params만 LHS 샘플링
# ═══════════════════════════════════════════════════════════════

def _latin_hypercube(n_samples: int, bounds: list, seed: int = 42):
    """간단 Latin Hypercube Sampling (numpy 의존 최소화)."""
    import random
    rng = random.Random(seed)
    dim = len(bounds)
    samples = [[0.0] * dim for _ in range(n_samples)]
    for d, (lo, hi) in enumerate(bounds):
        perm = list(range(n_samples))
        rng.shuffle(perm)
        for i in range(n_samples):
            u = (perm[i] + rng.random()) / n_samples
            samples[i][d] = lo + u * (hi - lo)
    return samples

# (name, lo, hi, is_int)
L4_BOUNDS = [
    ("gun_dist_ft",      600,  2500, True),
    ("gun_ata_deg",      5,    25,   True),
    ("close_dist_ft",    2000, 6000, True),
    ("hard_deck_ft",     800,  1500, True),
    ("recover_alt_ft",   2500, 5000, True),
]

# primary action 순환 (LHS + action variety)
L4_PRIMARY_CYCLE = ["LeadPursuit", "PurePursuit", "LagPursuit", "Pursue",
                    "BreakTurn", "OneCircleFight", "HighYoYo", "ClimbingTurn"]

def gen_layer4_threshold_sweep():
    records = []
    bounds = [(lo, hi) for _, lo, hi, _ in L4_BOUNDS]
    samples = _latin_hypercube(80, bounds, seed=42)
    for i, sample in enumerate(samples):
        values = {name: (int(v) if is_int else round(v, 3))
                  for (name, _, _, is_int), v in zip(L4_BOUNDS, sample)}
        primary = L4_PRIMARY_CYCLE[i % len(L4_PRIMARY_CYCLE)]
        name = f"L4_lhs_{i:03d}_{primary}"
        tree = _sel([
            _seq("HardDeck", [
                _cond("BelowHardDeck", threshold_ft=values["hard_deck_ft"]),
                _act("ClimbTo", target_altitude_ft=values["recover_alt_ft"]),
            ]),
            _seq("GunChance", [
                _cond("DistanceBelow", threshold_ft=values["gun_dist_ft"]),
                _cond("ATABelow", threshold_deg=float(values["gun_ata_deg"])),
                _act("GunAttack"),
            ]),
            _seq("CloseCombat", [
                _cond("DistanceBelow", threshold_ft=values["close_dist_ft"]),
                _act(primary),
            ]),
            _act("Pursue"),
        ])
        records.append(dict(
            name=name, layer="L4", category="threshold_sweep",
            primary_action=primary, thresholds=values,
            yaml=_wrap_yaml(name, f"L4 LHS #{i} primary={primary}", tree),
        ))
    return records


# ═══════════════════════════════════════════════════════════════
# Layer 5 — Orthogonal 4-axis Cross (144개)
# Phase × Range × Energy × Aggression → BT 자동 조립
# ═══════════════════════════════════════════════════════════════

PHASES      = ["OBFM", "DBFM", "HABFM", "MIXED"]
RANGES      = ["GUN", "CLOSE", "MID", "LONG"]
ENERGIES    = ["PRESERVE", "TRADE", "IGNORE"]
AGGRESSIONS = ["PASSIVE", "BALANCED", "AGGRESSIVE"]

def _phase_action(phase, aggression):
    if phase == "OBFM":
        return {"AGGRESSIVE": "LeadPursuit", "BALANCED": "PurePursuit", "PASSIVE": "LagPursuit"}[aggression]
    if phase == "DBFM":
        return {"AGGRESSIVE": "BreakTurn", "BALANCED": "DefensiveSpiral", "PASSIVE": "Evade"}[aggression]
    if phase == "HABFM":
        return {"AGGRESSIVE": "TwoCircleFight", "BALANCED": "OneCircleFight", "PASSIVE": "LagPursuit"}[aggression]
    # MIXED
    return {"AGGRESSIVE": "Pursue", "BALANCED": "Pursue", "PASSIVE": "LagPursuit"}[aggression]

def _range_gate(rng):
    return {
        "GUN":   ("DistanceBelow", {"threshold_ft": 914}),
        "CLOSE": ("DistanceBelow", {"threshold_ft": 3000}),
        "MID":   ("DistanceBelow", {"threshold_ft": 6000}),
        "LONG":  ("DistanceAbove", {"threshold_ft": 3000}),
    }[rng]

def _energy_action(energy):
    return {
        "PRESERVE": "ClimbingTurn",
        "TRADE":    "HighYoYo",
        "IGNORE":   "Straight",
    }[energy]

def gen_layer5_orthogonal():
    records = []
    i = 0
    for phase, rng, energy, agg in product(PHASES, RANGES, ENERGIES, AGGRESSIONS):
        i += 1
        if i > 144:
            break
        name = f"L5_{phase}_{rng}_{energy}_{agg}"
        primary = _phase_action(phase, agg)
        e_act = _energy_action(energy)
        gate_name, gate_params = _range_gate(rng)

        tree = _sel([
            _hard_deck(alt=1200 if energy == "PRESERVE" else 1000),
            _seq("GunChance", [
                _cond("DistanceBelow", threshold_ft=914),
                _cond("ATABelow", threshold_deg=12.0),
                _act("GunAttack"),
            ]),
            _seq(f"RangeGate_{rng}", [
                _cond(gate_name, **gate_params),
                _act(primary),
            ]),
            _seq("EnergyMgmt", [
                _cond("IsNeutralSituation"),
                _act(e_act),
            ]),
            _act("Pursue"),
        ])
        records.append(dict(
            name=name, layer="L5", category="orthogonal",
            phase=phase, range=rng, energy=energy, aggression=agg,
            yaml=_wrap_yaml(name, f"L5 Orth: {phase}/{rng}/{energy}/{agg}", tree),
        ))
    return records


# ═══════════════════════════════════════════════════════════════
# Layer 6 — Counter-strategies (수동 설계 30개)
# 특정 전술에 대한 counter 목적
# ═══════════════════════════════════════════════════════════════

def gen_layer6_counter():
    records = []

    counters = [
        # 에너지 기반 카운터
        ("L6_energy_vertical", "vs LowEnergy: 수직 공격",
         _sel([_hard_deck(), _seq("vertAttack", [
             _cond("IsAltAdvantage"), _act("HighYoYo")]), _act("Pursue")])),
        ("L6_energy_trap", "vs HighEnergy: 저고도 유인",
         _sel([_hard_deck(alt=800), _act("DescendingTurn")])),

        # 거리 기반 카운터
        ("L6_range_extend", "vs Close-in: 거리 확보",
         _sel([_hard_deck(), _seq("ext", [
             _cond("DistanceBelow", threshold_ft=2000), _act("Evade")]),
             _act("Pursue")])),
        ("L6_range_collapse", "vs Long-range: 급접근",
         _sel([_hard_deck(), _seq("acc", [_cond("DistanceAbove", threshold_ft=4000),
                                           _act("Accelerate")]),
               _act("Pursue")])),

        # 기하학 카운터
        ("L6_rollover_attack", "vs Defensive: Rollover lead",
         _sel([_hard_deck(), _seq("rollover", [
             _cond("IsOffensiveSituation"), _act("LeadPursuit")]),
             _act("BarrelRoll")])),
        ("L6_counter_one_circle", "vs OneCircle: TwoCircle 강요",
         _sel([_hard_deck(), _seq("two", [
             _cond("IsOneCircle"), _act("TwoCircleFight")]),
             _act("Pursue")])),
        ("L6_counter_two_circle", "vs TwoCircle: OneCircle 강요",
         _sel([_hard_deck(), _seq("one", [
             _cond("IsTwoCircle"), _act("OneCircleFight")]),
             _act("Pursue")])),

        # 방어 카운터
        ("L6_evasive_spiral", "vs Lead: DefensiveSpiral",
         _sel([_hard_deck(), _seq("spiral", [
             _cond("UnderThreat"), _act("DefensiveSpiral")]),
             _act("Pursue")])),
        ("L6_break_only", "pure break",
         _sel([_hard_deck(), _act("BreakTurn")])),
        ("L6_barrel_spam", "pure barrel roll",
         _sel([_hard_deck(), _act("BarrelRoll")])),

        # 공격 카운터
        ("L6_snapshot", "HighAoA snapshot",
         _sel([_hard_deck(), _seq("snap", [
             _cond("ATABelow", threshold_deg=20),
             _cond("DistanceBelow", threshold_ft=1500),
             _act("GunAttack")]), _act("LagPursuit")])),
        ("L6_continuous_gun", "gun everywhere",
         _sel([_hard_deck(), _act("GunAttack")])),

        # 에너지 전쟁
        ("L6_energy_fight", "full energy fight",
         _sel([_hard_deck(), _act("EnergyFight")])),
        ("L6_tc_fight", "full TC fight",
         _sel([_hard_deck(), _act("TCFight")])),
        ("L6_climb_always", "always climb",
         _sel([_hard_deck(), _act("ClimbTo", target_altitude_ft=25000)])),

        # Hit-and-run
        ("L6_hit_run", "attack then extend",
         _sel([_hard_deck(), _seq("hit", [
             _cond("IsOffensiveSituation"),
             _cond("DistanceBelow", threshold_ft=2000),
             _act("GunAttack")]),
             _seq("run", [
                 _cond("IsDefensiveSituation"),
                 _act("Evade")]),
             _act("Pursue")])),

        # Scissors 유도
        ("L6_scissors_force", "force scissors",
         _sel([_hard_deck(), _seq("sc", [
             _cond("IsMerged"), _act("OneCircleFight")]),
             _act("LagPursuit")])),

        # Altitude extreme
        ("L6_high_alt_camp", "high altitude camping",
         _sel([_hard_deck(alt=1500),
               _seq("stay_high", [
                   _cond("AltitudeBelow", min_altitude_ft=20000),
                   _act("ClimbTo", target_altitude_ft=25000)]),
               _act("LagPursuit")])),
        ("L6_low_alt_predator", "low altitude predator",
         _sel([_hard_deck(alt=700),
               _act("Pursue")])),

        # Velocity extreme
        ("L6_max_speed", "max speed rush",
         _sel([_hard_deck(), _act("Accelerate"), _act("Pursue")])),
        ("L6_min_speed_trap", "slow speed trap",
         _sel([_hard_deck(), _act("Decelerate"), _act("LagPursuit")])),

        # 복합 카운터
        ("L6_adaptive_default", "IsMerged+adaptive",
         _sel([_hard_deck(),
               _seq("merged", [_cond("IsMerged"), _act("LagPursuit")]),
               _seq("off", [_cond("IsOffensiveSituation"), _act("LeadPursuit")]),
               _seq("def", [_cond("IsDefensiveSituation"), _act("BreakTurn")]),
               _act("Pursue")])),
        ("L6_closure_manager", "closure rate manager",
         _sel([_hard_deck(),
               _seq("over", [_cond("ClosureRateAbove", threshold_kts=200),
                             _act("HighYoYo")]),
               _act("LeadPursuit")])),
        ("L6_ps_maximizer", "Ps maximizer",
         _sel([_hard_deck(),
               _seq("ps", [_cond("EnergyHighPs"), _act("LeadPursuit")]),
               _act("ClimbingTurn")])),

        # 퓨어 선회전
        ("L6_pure_turn_left", "pure left turn",
         _sel([_hard_deck(), _act("TurnLeft")])),
        ("L6_pure_turn_right", "pure right turn",
         _sel([_hard_deck(), _act("TurnRight")])),

        # 공격-방어 플립플롭
        ("L6_flipflop_aggressive", "flip-flop aggressive",
         _sel([_hard_deck(),
               _seq("a", [_cond("EnemyInRange"), _act("GunAttack")]),
               _seq("b", [_cond("UnderThreat"), _act("BarrelRoll")]),
               _act("Pursue")])),

        # WEZ 회피
        ("L6_wez_denial", "deny enemy WEZ",
         _sel([_hard_deck(),
               _seq("wez", [_cond("InEnemyWEZ"), _act("DefensiveSpiral")]),
               _act("LagPursuit")])),

        # Overshoot manager
        ("L6_overshoot_guard", "overshoot guard",
         _sel([_hard_deck(),
               _seq("o", [_cond("IsOvershootRisk"), _act("HighYoYo")]),
               _act("LeadPursuit")])),

        # Specific energy manager
        ("L6_specific_energy", "specific energy gate",
         _sel([_hard_deck(),
               _seq("s", [_cond("SpecificEnergyAbove", threshold_ft=15000),
                          _act("LeadPursuit")]),
               _act("ClimbTo", target_altitude_ft=18000)])),
    ]

    for name, desc, tree in counters:
        records.append(dict(
            name=name, layer="L6", category="counter",
            yaml=_wrap_yaml(name, desc, tree),
        ))
    return records


# ═══════════════════════════════════════════════════════════════
# 통합 생성 & 저장
# ═══════════════════════════════════════════════════════════════

LAYERS = {
    "L1": ("Pure single-action",    gen_layer1_pure),
    "L2": ("Gated 2-branch",        gen_layer2_gated),
    "L3": ("Phase-decomposed",      gen_layer3_phase),
    "L4": ("Threshold LHS sweep",   gen_layer4_threshold_sweep),
    "L5": ("Orthogonal 4-axis",     gen_layer5_orthogonal),
    "L6": ("Counter strategies",    gen_layer6_counter),
}


def generate_all(layers=None):
    layers = layers or list(LAYERS.keys())
    all_records = []
    for layer in layers:
        _, fn = LAYERS[layer]
        recs = fn()
        all_records.extend(recs)
    return all_records


def write_pool(records, clean=False):
    if clean and OUTPUT_DIR.exists():
        shutil.rmtree(OUTPUT_DIR)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    by_layer = {}
    for rec in records:
        path = OUTPUT_DIR / f"{rec['name']}.yaml"
        with open(path, "w", encoding="utf-8") as f:
            yaml.dump(rec["yaml"], f, allow_unicode=True, sort_keys=False,
                      default_flow_style=False)
        by_layer.setdefault(rec["layer"], 0)
        by_layer[rec["layer"]] += 1

    manifest = {
        "version": "1.0.0",
        "total_opponents": len(records),
        "layers": {k: {"description": LAYERS[k][0], "count": by_layer.get(k, 0)}
                   for k in LAYERS},
        "opponents": [
            {k: v for k, v in rec.items() if k != "yaml"} | {"yaml_path": f"{rec['name']}.yaml"}
            for rec in records
        ],
    }
    with open(MANIFEST_PATH, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)

    return by_layer


def _print_summary(by_layer, total):
    print(f"\n  Opponent Pool Summary")
    print(f"  {'='*50}")
    for layer_id, (desc, _) in LAYERS.items():
        count = by_layer.get(layer_id, 0)
        print(f"  {layer_id}  {desc:<28s}  {count:>4d}")
    print(f"  {'-'*50}")
    print(f"  Total opponents: {total}")
    print(f"\n  Statistical scale:")
    print(f"    10 rounds × {total} opp  = {10 * total} matches")
    print(f"    5  rounds × {total} opp  = {5 * total} matches")
    # Wilson CI at 50% WR
    import math
    for r in (5, 10):
        n = r * total
        z = 1.96
        p = 0.5
        margin = z * math.sqrt(p * (1-p) / n)
        print(f"    @ {r}R: Wilson CI ±{margin*100:.2f}%")
    print(f"  {'='*50}\n")


def main():
    ap = argparse.ArgumentParser(description="체계적 상대 BT 풀 생성기")
    ap.add_argument("--layer", type=str, default=None,
                    help="특정 레이어만 생성 (L1,L2,L3,L4,L5,L6)")
    ap.add_argument("--count", action="store_true",
                    help="규모만 계산하고 파일 생성 안 함")
    ap.add_argument("--clean", action="store_true",
                    help="기존 풀 삭제 후 재생성")
    args = ap.parse_args()

    layers = [args.layer] if args.layer else None
    records = generate_all(layers)

    if args.count:
        by_layer = {}
        for rec in records:
            by_layer.setdefault(rec["layer"], 0)
            by_layer[rec["layer"]] += 1
        _print_summary(by_layer, len(records))
        return

    by_layer = write_pool(records, clean=args.clean)
    print(f"  [generate_opponent_pool] {len(records)}개 상대 → {OUTPUT_DIR}")
    print(f"  manifest → {MANIFEST_PATH}")
    _print_summary(by_layer, len(records))


if __name__ == "__main__":
    main()
