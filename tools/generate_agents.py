"""
가설 기반 에이전트 자동 생성기

bt_optimizer_v3.py의 generate_bt_yaml()을 활용하여
다양한 전술 프로파일의 에이전트를 examples/ 에 생성.

목적: Phase 1 메타데이터의 커버리지 확대
  - 무승부 48% → 공격적 에이전트 추가로 교전 이벤트 증가
  - WEZ 0.9% → 근거리 돌진 에이전트로 WEZ 진입 데이터 증가
  - BFM UNKNOWN 7.6% → 전이 구간을 유도하는 에이전트

Usage:
    python tools/generate_agents.py              # 에이전트 생성
    python tools/generate_agents.py --list       # 생성될 에이전트 목록만 출력
"""

import sys
import yaml
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from tools.bt_optimizer_v3 import generate_bt_yaml

# ============================================================
# 가설별 에이전트 프로파일
# ============================================================

AGENT_PROFILES = {
    # --- 공격 극대화: 무승부 감소, WEZ 이벤트 증가 ---
    "gen_rush": {
        "description": "근거리 돌진 — 최소 거리에서 교전 유도, WEZ 데이터 확보",
        "params": {
            "hard_deck_threshold": 800, "climb_target": 2000,
            "wez_ata_threshold": 12,  # WEZ 진입 조건 완화
            "threat_aa_threshold": 150, "threat_distance": 500,
            "close_combat_distance": 4000,  # 넓은 근거리 판정
            "close_action": "LeadPursuit",
            "default_action": "Pursue",
            "defense_action": "BreakTurn",
            "include_emergency_defense": False,
            "include_altitude_far": False,
            "altitude_advantage_target": 300,
            "pnattack_kp": 1.5, "pnattack_kd": 0.5,
            "include_enemy_wez": False,
            "enemy_wez_distance": 700, "enemy_wez_los": 15,
            "include_offensive_press": True,
            "offensive_press_distance": 5000,  # 항상 공격
            "offensive_press_action": "LeadPursuit",
            "include_is_defensive": False,
            "is_defensive_action": "BarrelRoll",
        }
    },

    "gen_gunfighter": {
        "description": "GunAttack 특화 — 좁은 ATA에서 사격 기회 극대화",
        "params": {
            "hard_deck_threshold": 1000, "climb_target": 2500,
            "wez_ata_threshold": 5,  # 정밀 조준
            "threat_aa_threshold": 120, "threat_distance": 800,
            "close_combat_distance": 2000,
            "close_action": "LeadPursuit",
            "default_action": "LeadPursuit",
            "defense_action": "BreakTurn",
            "include_emergency_defense": True,
            "include_altitude_far": False,
            "altitude_advantage_target": 400,
            "pnattack_kp": 1.2, "pnattack_kd": 0.5,
            "include_enemy_wez": True,
            "enemy_wez_distance": 800, "enemy_wez_los": 15,
            "include_offensive_press": True,
            "offensive_press_distance": 3000,
            "offensive_press_action": "LeadPursuit",
            "include_is_defensive": False,
            "is_defensive_action": "BarrelRoll",
        }
    },

    # --- 방어/회피 특화: DBFM 데이터 보강 ---
    "gen_evader": {
        "description": "극단적 회피 — 항상 방어 기동, DBFM 데이터 확보",
        "params": {
            "hard_deck_threshold": 1200, "climb_target": 3500,
            "wez_ata_threshold": 5,
            "threat_aa_threshold": 100,  # 낮은 임계값 → 자주 방어 발동
            "threat_distance": 1500,     # 넓은 거리 → 자주 방어 발동
            "close_combat_distance": 1500,
            "close_action": "LagPursuit",
            "default_action": "LagPursuit",
            "defense_action": "DefensiveSpiral",
            "include_emergency_defense": True,
            "include_altitude_far": True,
            "altitude_advantage_target": 600,
            "pnattack_kp": 1.0, "pnattack_kd": 0.4,
            "include_enemy_wez": True,
            "enemy_wez_distance": 900, "enemy_wez_los": 25,
            "include_offensive_press": False,
            "offensive_press_distance": 3000,
            "offensive_press_action": "LeadPursuit",
            "include_is_defensive": True,
            "is_defensive_action": "DefensiveSpiral",
        }
    },

    "gen_breaker": {
        "description": "BreakTurn 특화 — 급선회 회피 데이터",
        "params": {
            "hard_deck_threshold": 1000, "climb_target": 3000,
            "wez_ata_threshold": 8,
            "threat_aa_threshold": 110,
            "threat_distance": 1200,
            "close_combat_distance": 2500,
            "close_action": "Pursue",
            "default_action": "Pursue",
            "defense_action": "BreakTurn",
            "include_emergency_defense": True,
            "include_altitude_far": False,
            "altitude_advantage_target": 400,
            "pnattack_kp": 1.0, "pnattack_kd": 0.4,
            "include_enemy_wez": True,
            "enemy_wez_distance": 800, "enemy_wez_los": 20,
            "include_offensive_press": False,
            "offensive_press_distance": 3000,
            "offensive_press_action": "LeadPursuit",
            "include_is_defensive": True,
            "is_defensive_action": "BreakTurn",
        }
    },

    # --- 에너지 전투 특화 ---
    "gen_energy": {
        "description": "에너지 우위 전투 — 고도+속도 우위 유지 후 공격",
        "params": {
            "hard_deck_threshold": 1500, "climb_target": 4000,
            "wez_ata_threshold": 6,
            "threat_aa_threshold": 140,
            "threat_distance": 900,
            "close_combat_distance": 2000,
            "close_action": "LagPursuit",
            "default_action": "Pursue",
            "defense_action": "BarrelRoll",
            "include_emergency_defense": False,
            "include_altitude_far": True,
            "altitude_advantage_target": 800,  # 높은 고도 우위 목표
            "pnattack_kp": 1.0, "pnattack_kd": 0.4,
            "include_enemy_wez": False,
            "enemy_wez_distance": 700, "enemy_wez_los": 15,
            "include_offensive_press": True,
            "offensive_press_distance": 2500,
            "offensive_press_action": "LagPursuit",
            "include_is_defensive": False,
            "is_defensive_action": "BarrelRoll",
        }
    },

    # --- 전이 구간 유도: BFM UNKNOWN 데이터 ---
    "gen_midrange": {
        "description": "중거리 유지 — ATA 50~70° 전이 구간 유도, UNKNOWN BFM 데이터",
        "params": {
            "hard_deck_threshold": 1000, "climb_target": 2500,
            "wez_ata_threshold": 8,
            "threat_aa_threshold": 130,
            "threat_distance": 700,
            "close_combat_distance": 1800,
            "close_action": "PurePursuit",
            "default_action": "LagPursuit",  # Lag = 중거리 유지 경향
            "defense_action": "DefensiveManeuver",
            "include_emergency_defense": False,
            "include_altitude_far": True,
            "altitude_advantage_target": 500,
            "pnattack_kp": 0.9, "pnattack_kd": 0.3,
            "include_enemy_wez": False,
            "enemy_wez_distance": 700, "enemy_wez_los": 15,
            "include_offensive_press": False,
            "offensive_press_distance": 3000,
            "offensive_press_action": "LeadPursuit",
            "include_is_defensive": True,
            "is_defensive_action": "DefensiveManeuver",
        }
    },

    # --- 복합 전술: 모든 브랜치 활성화 ---
    "gen_allbranch": {
        "description": "전 브랜치 활성화 — 모든 선택적 분기 ON, 노드 다양성 극대화",
        "params": {
            "hard_deck_threshold": 1200, "climb_target": 3000,
            "wez_ata_threshold": 8,
            "threat_aa_threshold": 125,
            "threat_distance": 1000,
            "close_combat_distance": 2500,
            "close_action": "LeadPursuit",
            "default_action": "Pursue",
            "defense_action": "DefensiveManeuver",
            "include_emergency_defense": True,
            "include_altitude_far": True,
            "altitude_advantage_target": 500,
            "pnattack_kp": 1.1, "pnattack_kd": 0.4,
            "include_enemy_wez": True,
            "enemy_wez_distance": 750, "enemy_wez_los": 18,
            "include_offensive_press": True,
            "offensive_press_distance": 3500,
            "offensive_press_action": "Pursue",
            "include_is_defensive": True,
            "is_defensive_action": "DefensiveManeuver",
        }
    },
}


def save_agent(name, profile, output_dir):
    bt_dict = generate_bt_yaml(profile["params"])
    bt_dict["name"] = name
    bt_dict["description"] = profile["description"]
    bt_dict["version"] = "gen_v1"

    out_path = output_dir / f"{name}.yaml"
    with open(out_path, 'w', encoding='utf-8') as f:
        yaml.dump(bt_dict, f, default_flow_style=False, allow_unicode=True, sort_keys=False)
    return out_path


def main():
    import argparse
    parser = argparse.ArgumentParser(description="가설 기반 에이전트 자동 생성")
    parser.add_argument("--list", action="store_true", help="생성될 에이전트 목록만 출력")
    parser.add_argument("--output", type=str, default="examples",
                        help="출력 폴더 (기본: examples/)")
    args = parser.parse_args()

    output_dir = PROJECT_ROOT / args.output
    output_dir.mkdir(exist_ok=True)

    if args.list:
        print(f"\n생성 예정 에이전트 ({len(AGENT_PROFILES)}종):\n")
        for name, profile in AGENT_PROFILES.items():
            print(f"  {name:20s} — {profile['description']}")
        return

    print(f"\n에이전트 생성 ({len(AGENT_PROFILES)}종) → {output_dir}\n")
    for name, profile in AGENT_PROFILES.items():
        path = save_agent(name, profile, output_dir)
        print(f"  {name:20s} → {path.name}  ({profile['description']})")

    print(f"\n완료. collect_phase1.py --agents 옵션에 추가 가능:")
    agent_list = " ".join(AGENT_PROFILES.keys())
    print(f"  python tools/collect_phase1.py --agents {agent_list} --probes")


if __name__ == "__main__":
    main()
