"""
expand_archetypes.py — 168개 BT 아키타입 자동 생성기

Prototypical Network 메타 학습용 클래스 균형 확보 (비대칭 카운트):
  GUN_ATTACK  × 40 — 가장 희소한 클래스 집중 보강
  PURSUIT     ×  8 — 기존 데이터 충분
  DEFENSIVE   × 20 — 현재 충분, 약간 보강
  ENERGY      × 30 — 추가 다양성 필요
  NEUTRAL     × 30 — 추가 다양성 필요
  SCISSORS    × 40 — 신규 6번째 클래스 (alpha2 커스텀 노드 사용)
  ────────────────
  합계        168

SCISSORS 아키타입은 examples/archetypes/nodes/ 공유 디렉토리의
ScissorsAccel, ReengageClimb, IsScissors, IsDisengaging 노드를 사용.

Usage:
    python tools/expand_archetypes.py              # 생성
    python tools/expand_archetypes.py --list       # 목록만 출력
    python tools/expand_archetypes.py --manifest   # manifest JSON만 출력
"""

import sys
import json
import yaml
import argparse
from pathlib import Path
from itertools import product

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

OUTPUT_DIR = PROJECT_ROOT / "examples" / "archetypes"
MANIFEST_PATH = PROJECT_ROOT / "examples" / "archetypes" / "manifest.json"

# ──────────────────────────────────────────────
# Intent label → 설명
# ──────────────────────────────────────────────
INTENT_CLASSES = {
    "GUN_ATTACK":  "GunAttack/WEZ 진입 중심 전술",
    "PURSUIT":     "LeadPursuit/PurePursuit 공격 추격",
    "DEFENSIVE":   "BreakTurn/DefensiveSpiral 방어 회피",
    "ENERGY":      "HighYoYo/ClimbingTurn 에너지 기동",
    "NEUTRAL":     "LagPursuit/OneCircleFight Lufbery 선회",
    "SCISSORS":    "ScissorsAccel/ReengageClimb UNKNOWN BFM 세분화",
}

# 클래스별 목표 아키타입 수 (비대칭 — 희소 클래스 우선 보강)
ARCHETYPE_COUNTS = {
    "GUN_ATTACK":  40,
    "PURSUIT":      8,
    "DEFENSIVE":   20,
    "ENERGY":      30,
    "NEUTRAL":     30,
    "SCISSORS":    40,
}

# active_node → intent 매핑 (학습 레이블 생성용)
NODE_TO_INTENT = {
    "GunAttack":         "GUN_ATTACK",
    "PNAttack":          "GUN_ATTACK",
    "LeadPursuit":       "PURSUIT",
    "PurePursuit":       "PURSUIT",
    "Pursue":            "PURSUIT",
    "PNPursuit":         "PURSUIT",
    "LagPursuit":        "NEUTRAL",
    "OneCircleFight":    "NEUTRAL",
    "BreakTurn":         "DEFENSIVE",
    "DefensiveManeuver": "DEFENSIVE",
    "DefensiveSpiral":   "DEFENSIVE",
    "BarrelRoll":        "DEFENSIVE",
    "HighYoYo":          "ENERGY",
    "ClimbingTurn":      "ENERGY",
    "AltitudeAdvantage": "ENERGY",
    "ClimbTo":           "ENERGY",
    "ScissorsAccel":     "SCISSORS",
    "ReengageClimb":     "SCISSORS",
}

# 기존 에이전트 → intent 매핑 (manifest에 포함)
EXISTING_AGENT_INTENT = {
    "simple":          "NEUTRAL",
    "aggressive":      "PURSUIT",
    "defensive":       "DEFENSIVE",
    "eagle1":          "PURSUIT",
    "ace":             "GUN_ATTACK",
    "viper1":          "GUN_ATTACK",
    "golden":          "GUN_ATTACK",
    "gen_rush":        "PURSUIT",
    "gen_gunfighter":  "GUN_ATTACK",
    "gen_evader":      "DEFENSIVE",
    "gen_breaker":     "DEFENSIVE",
    "gen_energy":      "ENERGY",
    "gen_midrange":    "NEUTRAL",
    "gen_allbranch":   "NEUTRAL",
    "probe_wez":       "GUN_ATTACK",
    "probe_defensive": "DEFENSIVE",
    "probe_energy":    "ENERGY",
    "probe_obfm":      "PURSUIT",
    "probe_habfm":     "NEUTRAL",
}

# ──────────────────────────────────────────────
# BT YAML 빌더 함수들 (intent별 특화)
# ──────────────────────────────────────────────

def _seq(name, children):
    return {"type": "Sequence", "name": name, "children": children}

def _cond(name, **params):
    n = {"type": "Condition", "name": name}
    if params:
        n["params"] = params
    return n

def _act(name, **params):
    n = {"type": "Action", "name": name}
    if params:
        n["params"] = params
    return n


def build_gun_attack_bt(variant: dict) -> dict:
    """GUN_ATTACK 아키타입 — WEZ 진입 + GunAttack 극대화."""
    wez_dist   = variant["wez_dist"]    # 914~2000 ft
    wez_ata    = variant["wez_ata"]     # 5~25 deg
    close_dist = variant["close_dist"]  # 3000~6000 ft
    def_action = variant["def_action"]  # BreakTurn / LagPursuit

    return {
        "type": "Selector",
        "children": [
            _seq("HardDeck", [
                _cond("BelowHardDeck", threshold_ft=800),
                _act("ClimbTo", target_altitude_ft=2500),
            ]),
            _seq("WEZAttack", [
                _cond("DistanceBelow", threshold_ft=wez_dist),
                _cond("ATABelow", threshold_deg=float(wez_ata)),
                _act("GunAttack"),
            ]),
            _seq("CloseApproach", [
                _cond("IsOffensiveSituation"),
                _cond("DistanceBelow", threshold_ft=close_dist),
                _act("LeadPursuit"),
            ]),
            _seq("FarApproach", [
                _cond("IsOffensiveSituation"),
                _act("PurePursuit"),
            ]),
            _act(def_action),
        ]
    }


def build_pursuit_bt(variant: dict) -> dict:
    """PURSUIT 아키타입 — 공격적 추격, 거리 줄이기."""
    close_dist   = variant["close_dist"]   # 4000~9000 ft
    close_action = variant["close_action"] # LeadPursuit / PurePursuit
    far_action   = variant["far_action"]   # Pursue / LeadPursuit
    use_circle   = variant["use_circle"]   # OneCircleFight 포함 여부

    children = [
        _seq("HardDeck", [
            _cond("BelowHardDeck", threshold_ft=1000),
            _act("ClimbTo", target_altitude_ft=2500),
        ]),
        _seq("GunOpportunity", [
            _cond("DistanceBelow", threshold_ft=1500),
            _cond("ATABelow", threshold_deg=12.0),
            _act("GunAttack"),
        ]),
    ]
    if use_circle:
        children.append(_seq("CircleFight", [
            _cond("IsOffensiveSituation"),
            _cond("DistanceBelow", threshold_ft=close_dist),
            _act("OneCircleFight"),
        ]))
    children += [
        _seq("CloseChase", [
            _cond("DistanceBelow", threshold_ft=close_dist),
            _act(close_action),
        ]),
        _act(far_action),
    ]
    return {"type": "Selector", "children": children}


def build_defensive_bt(variant: dict) -> dict:
    """DEFENSIVE 아키타입 — 위협 감지 시 즉시 회피."""
    aa_thresh  = variant["aa_thresh"]   # 120~170 deg (후방 위협)
    dist_limit = variant["dist_limit"]  # 3000~8000 ft
    evasion1   = variant["evasion1"]    # BreakTurn / DefensiveSpiral
    evasion2   = variant["evasion2"]    # BarrelRoll / DefensiveManeuver
    counter    = variant["counter"]     # LagPursuit / LeadPursuit

    return {
        "type": "Selector",
        "children": [
            _seq("HardDeck", [
                _cond("BelowHardDeck", threshold_ft=1200),
                _act("ClimbTo", target_altitude_ft=3000),
            ]),
            _seq("GunIfChance", [
                _cond("DistanceBelow", threshold_ft=1000),
                _cond("ATABelow", threshold_deg=10.0),
                _act("GunAttack"),
            ]),
            _seq("ImminentThreat", [
                _cond("IsDefensiveSituation"),
                _cond("UnderThreat", aa_threshold_deg=float(aa_thresh)),
                _cond("DistanceBelow", threshold_ft=dist_limit),
                _act(evasion1),
            ]),
            _seq("ModerateDefense", [
                _cond("IsDefensiveSituation"),
                _act(evasion2),
            ]),
            _seq("CounterAttack", [
                _cond("IsOffensiveSituation"),
                _act(counter),
            ]),
            _act("LagPursuit"),
        ]
    }


def build_energy_bt(variant: dict) -> dict:
    """ENERGY 아키타입 — 고도/에너지 우위 구축."""
    alt_thresh     = variant["alt_thresh"]     # 10000~18000 ft (HighYoYo 임계)
    climb_target   = variant["climb_target"]   # 12000~25000 ft
    adv_target     = variant["adv_target"]     # 500~2000 ft
    yoyo_or_climb  = variant["yoyo_or_climb"]  # HighYoYo / ClimbingTurn

    return {
        "type": "Selector",
        "children": [
            _seq("HardDeck", [
                _cond("BelowHardDeck", threshold_ft=1500),
                _act("ClimbTo", target_altitude_ft=4000),
            ]),
            _seq("GunOpportunity", [
                _cond("DistanceBelow", threshold_ft=1500),
                _cond("ATABelow", threshold_deg=12.0),
                _act("GunAttack"),
            ]),
            _seq("EnergyRecovery", [
                _cond("AltitudeBelow", min_altitude_ft=alt_thresh),
                _act(yoyo_or_climb),
            ]),
            _seq("NeutralClimb", [
                _cond("IsNeutralSituation"),
                _act("ClimbingTurn", direction="auto"),
            ]),
            {
                "type": "Parallel",
                "name": "AltAdvantage",
                "policy": "SuccessOnOne",
                "children": [
                    _act("Pursue"),
                    _act("AltitudeAdvantage", target_advantage_ft=adv_target),
                ]
            },
            _act("ClimbTo", target_altitude_ft=climb_target),
        ]
    }


def build_scissors_bt(variant: dict) -> dict:
    """SCISSORS 아키타입 — UNKNOWN BFM 세분화 커스텀 노드 사용.

    IsScissors → ScissorsAccel: Scissors 교착 탈출
    IsDisengaging → ReengageClimb: 이탈 후 재접근
    IsNearOffensive → LeadPursuit: 공격 기회 추구
    Default: Pursue

    nodes/custom_actions.py + nodes/custom_conditions.py 필요
    (examples/archetypes/nodes/ 공유 디렉토리 참조)
    """
    ata_min      = variant["ata_min"]
    ata_max      = variant["ata_max"]
    closure_max  = variant["closure_max"]
    heading_gain = variant["heading_gain"]
    reengage_gain = variant["reengage_gain"]

    return {
        "type": "Selector",
        "children": [
            _seq("HardDeck", [
                _cond("BelowHardDeck", threshold_ft=1200),
                _act("ClimbTo", target_altitude_ft=3000),
            ]),
            _seq("GunChance", [
                _cond("DistanceBelow", threshold_ft=914),
                _cond("ATABelow", threshold_deg=8.0),
                _act("GunAttack"),
            ]),
            _seq("ScissorsEscape", [
                _cond("IsScissors",
                      ata_min=float(ata_min),
                      ata_max=float(ata_max),
                      closure_max_kts=float(closure_max)),
                _act("ScissorsAccel", heading_gain=float(heading_gain)),
            ]),
            _seq("ReengageFromDisengage", [
                _cond("IsDisengaging",
                      ata_min=float(ata_max),
                      closure_max_kts=-50.0),
                _act("ReengageClimb", heading_gain=float(reengage_gain)),
            ]),
            _seq("NearOffensiveAttack", [
                _cond("IsNearOffensive", ata_max=float(ata_min)),
                _act("LeadPursuit"),
            ]),
            _act("Pursue"),
        ]
    }


def build_neutral_bt(variant: dict) -> dict:
    """NEUTRAL 아키타입 — Lufbery/HABFM 선회 전술."""
    circle_dist = variant["circle_dist"]  # 6000~15000 ft
    use_high_yoyo = variant["use_high_yoyo"]  # ATA > 45시 HighYoYo
    lag_or_lag2   = variant["lag_action"]  # LagPursuit (default)

    children = [
        _seq("HardDeck", [
            _cond("BelowHardDeck", threshold_ft=1000),
            _act("ClimbTo", target_altitude_ft=3000),
        ]),
        _seq("GunOpportunity", [
            _cond("DistanceBelow", threshold_ft=1200),
            _cond("ATABelow", threshold_deg=10.0),
            _act("GunAttack"),
        ]),
    ]
    if use_high_yoyo:
        children.append(_seq("HighYoYoEscape", [
            _cond("IsNeutralSituation"),
            _cond("ATAAbove", threshold_deg=50),
            _act("HighYoYo"),
        ]))
    children += [
        _seq("LufberyCircle", [
            _cond("IsNeutralSituation"),
            _cond("DistanceBelow", threshold_ft=circle_dist),
            _act("OneCircleFight"),
        ]),
        _seq("NeutralDefault", [
            _cond("IsNeutralSituation"),
            _act(lag_or_lag2),
        ]),
        _act("LagPursuit"),
    ]
    return {"type": "Selector", "children": children}


# ──────────────────────────────────────────────
# 변형 파라미터 그리드 (intent별 20개씩)
# ──────────────────────────────────────────────

def _gun_variants():
    """GUN_ATTACK 40개 — WEZ 거리/각도/근접액션 조합 전수."""
    variants = []
    for wez_dist, wez_ata, close_dist, def_action in product(
        [600, 914, 1200, 1500, 2000],
        [5, 8, 12, 18, 25],
        [3000, 4500, 6000, 8000],
        ["LagPursuit", "BreakTurn"],
    ):
        variants.append(dict(
            wez_dist=wez_dist, wez_ata=wez_ata,
            close_dist=close_dist, def_action=def_action
        ))
    step = max(1, len(variants) // 40)
    return variants[::step][:40]


def _pursuit_variants():
    """PURSUIT 8개 — 기존 데이터 충분, 최소 다양성."""
    variants = []
    for close_dist, close_action, far_action, use_circle in product(
        [4000, 6000, 8000, 9000],
        ["LeadPursuit", "PurePursuit"],
        ["Pursue", "LeadPursuit"],
        [True, False],
    ):
        variants.append(dict(
            close_dist=close_dist, close_action=close_action,
            far_action=far_action, use_circle=use_circle
        ))
    step = max(1, len(variants) // 8)
    return variants[::step][:8]


def _defensive_variants():
    """DEFENSIVE 20개."""
    variants = []
    for aa_thresh, dist_limit, evasion1, evasion2 in product(
        [120, 140, 150, 160],
        [3000, 5000, 7000],
        ["BreakTurn", "DefensiveSpiral"],
        ["BarrelRoll", "DefensiveManeuver"],
    ):
        variants.append(dict(
            aa_thresh=aa_thresh, dist_limit=dist_limit,
            evasion1=evasion1, evasion2=evasion2,
            counter="LagPursuit"
        ))
    step = max(1, len(variants) // 20)
    return variants[::step][:20]


def _energy_variants():
    """ENERGY 30개 — 고도/에너지 기동 다양성 확대."""
    variants = []
    for alt_thresh, climb_target, adv_target, yoyo_or_climb in product(
        [8000, 10000, 12000, 14764, 16000],
        [12000, 15000, 18000, 22000],
        [500, 1000, 2000],
        ["HighYoYo", "ClimbingTurn"],
    ):
        variants.append(dict(
            alt_thresh=alt_thresh, climb_target=climb_target,
            adv_target=adv_target, yoyo_or_climb=yoyo_or_climb
        ))
    step = max(1, len(variants) // 30)
    return variants[::step][:30]


def _neutral_variants():
    """NEUTRAL 30개 — Lufbery/HABFM 다양성 확대."""
    variants = []
    for circle_dist, use_high_yoyo, lag_action in product(
        [5000, 6000, 8000, 10000, 13000, 15000],
        [True, False],
        ["LagPursuit", "OneCircleFight"],
    ):
        variants.append(dict(
            circle_dist=circle_dist,
            use_high_yoyo=use_high_yoyo,
            lag_action=lag_action
        ))
    step = max(1, len(variants) // 30)
    return variants[::step][:30]


def _scissors_variants():
    """SCISSORS 40개 — UNKNOWN BFM 세분화 (ScissorsAccel/ReengageClimb 사용)."""
    variants = []
    for ata_min, ata_max, closure_max, heading_gain, reengage_gain in product(
        [40.0, 45.0, 50.0],
        [65.0, 70.0, 75.0],
        [-10.0, 0.0, 20.0],
        [0.4, 0.5, 0.6],
        [0.6, 0.7, 0.8],
    ):
        variants.append(dict(
            ata_min=ata_min, ata_max=ata_max,
            closure_max=closure_max,
            heading_gain=heading_gain,
            reengage_gain=reengage_gain,
        ))
    step = max(1, len(variants) // 40)
    return variants[::step][:40]


# ──────────────────────────────────────────────
# 아키타입 레코드 생성
# ──────────────────────────────────────────────

INTENT_CONFIG = {
    "GUN_ATTACK": (_gun_variants,       build_gun_attack_bt),
    "PURSUIT":    (_pursuit_variants,   build_pursuit_bt),
    "DEFENSIVE":  (_defensive_variants, build_defensive_bt),
    "ENERGY":     (_energy_variants,    build_energy_bt),
    "NEUTRAL":    (_neutral_variants,   build_neutral_bt),
    "SCISSORS":   (_scissors_variants,  build_scissors_bt),
}


def generate_all_archetypes():
    """모든 아키타입 YAML dict + manifest 레코드 반환."""
    records = []
    for intent, (var_fn, bt_fn) in INTENT_CONFIG.items():
        variants = var_fn()
        for i, variant in enumerate(variants):
            name = f"arch_{intent.lower()}_{i:02d}"
            tree = bt_fn(variant)
            yaml_dict = {
                "name": name,
                "version": "1.0.0",
                "description": f"{INTENT_CLASSES[intent]} — variant {i:02d}",
                "tree": tree,
            }
            records.append({
                "name": name,
                "intent": intent,
                "variant_idx": i,
                "variant_params": variant,
                "yaml": yaml_dict,
            })
    return records


def build_manifest(new_records):
    """기존 에이전트 + 새 아키타입 통합 manifest."""
    manifest = {
        "version": "2.0.0",
        "intent_classes": INTENT_CLASSES,
        "node_to_intent": NODE_TO_INTENT,
        "agents": {},
    }
    # 기존 에이전트
    for agent, intent in EXISTING_AGENT_INTENT.items():
        manifest["agents"][agent] = {
            "intent": intent,
            "source": "existing",
            "yaml_path": None,
        }
    # 새 아키타입
    for rec in new_records:
        manifest["agents"][rec["name"]] = {
            "intent": rec["intent"],
            "source": "archetype",
            "yaml_path": str(OUTPUT_DIR / f"{rec['name']}.yaml"),
            "variant_params": rec["variant_params"],
        }
    return manifest


def write_archetypes(records):
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    for rec in records:
        path = OUTPUT_DIR / f"{rec['name']}.yaml"
        with open(path, "w", encoding="utf-8") as f:
            yaml.dump(rec["yaml"], f, allow_unicode=True, sort_keys=False,
                      default_flow_style=False)
    print(f"[expand_archetypes] {len(records)}개 아키타입 → {OUTPUT_DIR}/")


def write_manifest(manifest):
    with open(MANIFEST_PATH, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)
    print(f"[expand_archetypes] manifest → {MANIFEST_PATH}")
    total = len(manifest["agents"])
    by_class = {}
    for info in manifest["agents"].values():
        by_class.setdefault(info["intent"], 0)
        by_class[info["intent"]] += 1
    print("\n  Intent 분포:")
    for cls, cnt in sorted(by_class.items()):
        print(f"    {cls:<16} {cnt:>3}개")
    print(f"  총 {total}개 에이전트")


# ──────────────────────────────────────────────
# CLI
# ──────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser(description="BT 아키타입 100개 생성기")
    ap.add_argument("--list",     action="store_true", help="생성 목록만 출력")
    ap.add_argument("--manifest", action="store_true", help="manifest JSON만 출력")
    args = ap.parse_args()

    records = generate_all_archetypes()
    manifest = build_manifest(records)

    if args.list:
        for rec in records:
            print(f"  {rec['name']:<30} [{rec['intent']}]")
        print(f"\n총 {len(records)}개 (기존 포함 {len(manifest['agents'])}개)")
        return

    if args.manifest:
        print(json.dumps(manifest, ensure_ascii=False, indent=2))
        return

    write_archetypes(records)
    write_manifest(manifest)


if __name__ == "__main__":
    main()
