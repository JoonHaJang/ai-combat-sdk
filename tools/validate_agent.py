"""
에이전트 제출 전 검증 도구

사용법:
    python tools/validate_agent.py my_agent.yaml
    python tools/validate_agent.py examples/my_agent.yaml
"""

import argparse
import sys
from pathlib import Path
import yaml

# 프로젝트 루트를 path에 추가
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))


# 허용된 노드 목록
ALLOWED_CONDITIONS = [
    "EnemyInRange", "DistanceBelow", "DistanceAbove", "EnemyInFront", "EnemyBehind",
    "AltitudeAbove", "AltitudeBelow", "BelowHardDeck", "SpeedAbove", "VelocityAbove", "VelocityBelow",
    "IsOffensiveSituation", "IsDefensiveSituation", "IsNeutralSituation", "UnderThreat", "InEnemyWEZ",
    "ATAAbove", "ATABelow", "LOSAbove", "LOSBelow", "RelativeBearingAbove",
    "EnergyHigh", "EnergyHighPs", "SpecificEnergyAbove", "HasSuperior", "NotSuperior",
    "IsMerged", "IsVerticalMove", "IsNotVerticalMove", "IsTurningRight",
]

ALLOWED_ACTIONS = [
    "Pursue", "Evade", "ClimbTo", "DescendTo", "MaintainAltitude", "Accelerate", "Decelerate",
    "TurnLeft", "TurnRight", "Straight",
    "PurePursuit", "LeadPursuit", "LagPursuit",
    "DefensiveManeuver", "BreakTurn", "DefensiveSpiral", "AltitudeAdvantage",
    "HighYoYo", "LowYoYo", "ClimbingTurn", "DescendingTurn", "BarrelRoll",
    "OneCircleFight", "TwoCircleFight", "GunAttack",
]

ALLOWED_COMPOSITES = ["Selector", "Sequence", "Parallel"]

ALLOWED_NODES = ALLOWED_CONDITIONS + ALLOWED_ACTIONS + ALLOWED_COMPOSITES


def validate_node(node: dict, path: str = "root") -> list:
    """노드 유효성 검사. 오류 목록 반환."""
    errors = []
    
    node_type = node.get("type")
    node_name = node.get("name", node_type)
    
    # 타입 또는 이름 확인
    if node_type not in ALLOWED_COMPOSITES:
        if node_type == "Condition" or node_type == "Action":
            if node_name not in ALLOWED_NODES:
                errors.append(f"[{path}] 허용되지 않은 노드: {node_name}")
        elif node_type not in ALLOWED_NODES:
            errors.append(f"[{path}] 허용되지 않은 노드 타입: {node_type}")
    
    # 자식 노드 재귀 검사
    children = node.get("children", [])
    for i, child in enumerate(children):
        child_path = f"{path} > {child.get('name', child.get('type', 'unknown'))}[{i}]"
        errors.extend(validate_node(child, child_path))
    
    return errors


def validate_yaml(yaml_path: Path) -> tuple:
    """YAML 파일 검증. (성공 여부, 오류 목록) 반환."""
    errors = []
    
    # 파일 존재 확인
    if not yaml_path.exists():
        return False, [f"파일을 찾을 수 없습니다: {yaml_path}"]
    
    # YAML 파싱
    try:
        with open(yaml_path, 'r', encoding='utf-8') as f:
            data = yaml.safe_load(f)
    except yaml.YAMLError as e:
        return False, [f"YAML 파싱 오류: {e}"]
    
    # 필수 필드 확인
    if "root" not in data and "tree" not in data:
        errors.append("'root' 또는 'tree' 키가 필요합니다")
        return False, errors
    
    root = data.get("root") or data.get("tree")
    
    # 노드 검증
    node_errors = validate_node(root)
    errors.extend(node_errors)
    
    # 메타데이터 확인 (경고)
    warnings = []
    if "name" not in data:
        warnings.append("⚠️  'name' 필드 권장")
    if "version" not in data:
        warnings.append("⚠️  'version' 필드 권장")
    
    return len(errors) == 0, errors, warnings


def main():
    parser = argparse.ArgumentParser(description="에이전트 YAML 검증")
    parser.add_argument("agent", help="검증할 에이전트 YAML 파일")
    
    args = parser.parse_args()
    
    # 파일 경로 처리
    agent_path = Path(args.agent)
    if not agent_path.exists():
        agent_path = project_root / "examples" / args.agent
        if not agent_path.suffix:
            agent_path = agent_path.with_suffix(".yaml")
    
    print(f"🔍 에이전트 검증: {agent_path.name}")
    print()
    
    success, errors, *rest = validate_yaml(agent_path)
    warnings = rest[0] if rest else []
    
    if warnings:
        for w in warnings:
            print(w)
        print()
    
    if success:
        print("✅ 검증 통과! 제출 가능합니다.")
    else:
        print("❌ 검증 실패:")
        for error in errors:
            print(f"   - {error}")
        sys.exit(1)


if __name__ == "__main__":
    main()
