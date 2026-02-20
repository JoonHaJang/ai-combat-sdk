from pathlib import Path
import yaml
from typing import List, Dict
import importlib.util
import sys

class ValidationResult:
    def __init__(self, success: bool, errors: List[str], warnings: List[str]):
        self.success = success
        self.errors = errors
        self.warnings = warnings

class SubmissionValidator:
    """제출물 유효성 검사 클래스"""
    
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

    # 제한 설정
    MAX_NODES = 100
    MAX_DEPTH = 20

    def validate(self, yaml_path: str) -> ValidationResult:
        """제출물 검증 메인 함수"""
        path = Path(yaml_path)

        # 1. 파일 존재 확인
        if not path.exists():
            return ValidationResult(False, [f"파일을 찾을 수 없습니다: {path}"], [])

        # 2. YAML 파싱
        try:
            with open(path, 'r', encoding='utf-8') as f:
                data = yaml.safe_load(f)
        except yaml.YAMLError as e:
            return ValidationResult(False, [f"YAML 파싱 오류: {e}"], [])
        except Exception as e:
            return ValidationResult(False, [f"파일 읽기 오류: {e}"], [])

        # 커스텀 노드 목록 로드
        custom_nodes = self._load_custom_nodes(path.parent)
        
        return self.validate_data(data, custom_nodes)

    def validate_data(self, data: dict, custom_nodes: Dict[str, List[str]] = None) -> ValidationResult:
        """이미 파싱된 데이터 검증"""
        errors = []
        warnings = []

        if not isinstance(data, dict):
             return ValidationResult(False, ["YAML 형식이 올바르지 않습니다 (Dictionary 구조여야 함)"], [])

        # 3. 필수 필드 확인
        has_root = "root" in data
        has_tree = "tree" in data

        if not has_root and not has_tree:
            errors.append("'root' 또는 'tree' 키가 필요합니다")
            return ValidationResult(False, errors, warnings)

        root_value = data.get("root") if has_root else None
        tree_value = data.get("tree") if has_tree else None

        if has_root and root_value is not None:
            root_node = root_value
        elif has_tree and tree_value is not None:
            root_node = tree_value
        else:
            errors.append("'root' 또는 'tree' 값이 비어 있습니다 (null)")
            return ValidationResult(False, errors, warnings)

        if has_root and has_tree and root_value is not None and tree_value is not None and root_value != tree_value:
            warnings.append("⚠️  'root'와 'tree'가 모두 존재하며 값이 다릅니다. 'root'를 우선 사용합니다")

        # 4. 노드 검증
        node_errors = self._validate_node_recursive(root_node, custom_nodes)
        errors.extend(node_errors)

        # 5. 복잡도 검사
        complexity_errors = self.check_complexity(root_node)
        errors.extend(complexity_errors)

        # 6. 메타데이터 확인 (경고)
        if "name" not in data:
            warnings.append("⚠️  'name' 필드 권장")
        if "version" not in data:
            warnings.append("⚠️  'version' 필드 권장")

        return ValidationResult(len(errors) == 0, errors, warnings)

    def _validate_node_recursive(self, node: dict, custom_nodes: Dict[str, List[str]] = None, path: str = "root") -> List[str]:
        """노드 재귀 검증"""
        errors = []
        
        if not isinstance(node, dict):
            return [f"[{path}] 노드는 Dictionary여야 합니다"]

        node_type = node.get("type")
        node_name = node.get("name", node_type)

        if not node_type:
            return [f"[{path}] 'type' 필드가 누락되었습니다"]

        # 타입 또는 이름 확인
        if node_type not in self.ALLOWED_COMPOSITES:
            if node_type == "Condition" or node_type == "Action":
                # 커스텀 노드 허용 목록 확인
                allowed_nodes = self.ALLOWED_NODES.copy()
                if custom_nodes:
                    allowed_nodes.extend(custom_nodes.get(node_type, []))
                
                if node_name not in allowed_nodes:
                    errors.append(f"[{path}] 허용되지 않은 노드: {node_name}")
            elif node_type not in self.ALLOWED_NODES:
                errors.append(f"[{path}] 허용되지 않은 노드 타입: {node_type}")
        
        # 자식 노드 재귀 검사
        children = node.get("children", [])
        if not isinstance(children, list):
             errors.append(f"[{path}] 'children'은 리스트여야 합니다")
        else:
            for i, child in enumerate(children):
                if isinstance(child, dict):
                    child_label = child.get('name', child.get('type', 'unknown'))
                else:
                    child_label = type(child).__name__
                child_path = f"{path} > {child_label}[{i}]"
                errors.extend(self._validate_node_recursive(child, custom_nodes, child_path))
        
        return errors

    def get_stats(self, root: dict) -> dict:
        """트리 통계 반환 (노드 수, 깊이)"""
        return {
            "node_count": self._count_nodes(root),
            "depth": self._calculate_depth(root),
        }

    def check_complexity(self, root: dict) -> List[str]:
        """복잡도 제한 검사"""
        errors = []
        
        # 노드 수 계산
        total_nodes = self._count_nodes(root)
        if total_nodes > self.MAX_NODES:
            errors.append(f"총 노드 수가 제한을 초과했습니다: {total_nodes}/{self.MAX_NODES}")

        # 깊이 계산
        max_depth = self._calculate_depth(root)
        if max_depth > self.MAX_DEPTH:
            errors.append(f"트리 깊이가 제한을 초과했습니다: {max_depth}/{self.MAX_DEPTH}")
            
        return errors

    def _count_nodes(self, node: dict) -> int:
        if not isinstance(node, dict):
            return 0
        count = 1
        for child in node.get("children", []):
            count += self._count_nodes(child)
        return count

    def _calculate_depth(self, node: dict) -> int:
        if not isinstance(node, dict):
            return 0
        if not node.get("children"):
            return 1
        
        max_child_depth = 0
        for child in node.get("children", []):
            depth = self._calculate_depth(child)
            if depth > max_child_depth:
                max_child_depth = depth
        
        return 1 + max_child_depth

    def _load_custom_nodes(self, submission_dir: Path) -> Dict[str, List[str]]:
        """커스텀 노드 목록 로드
        
        Args:
            submission_dir: 제출 폴더 경로 (submissions/{name}/)
            
        Returns:
            {'Action': ['CustomAction1', ...], 'Condition': ['CustomCondition1', ...]} 형태의 딕셔너리
        """
        custom_nodes = {'Action': [], 'Condition': []}
        
        nodes_dir = submission_dir / "nodes"
        if not nodes_dir.exists():
            return custom_nodes
        
        # 커스텀 액션 로드
        actions_file = nodes_dir / "custom_actions.py"
        if actions_file.exists():
            try:
                module_name = f"custom_actions_{submission_dir.name}"
                spec = importlib.util.spec_from_file_location(module_name, actions_file)
                module = importlib.util.module_from_spec(spec)
                sys.modules[module_name] = module
                spec.loader.exec_module(module)
                
                # py_trees.behaviour.Behaviour를 상속받은 클래스만 추출 (간접 상속 포함)
                def is_behaviour_subclass(cls):
                    if not isinstance(cls, type):
                        return False
                    for base in cls.__mro__:  # Method Resolution Order 확인
                        if 'Behaviour' in base.__name__:
                            return True
                    return False
                
                for attr_name in dir(module):
                    attr = getattr(module, attr_name)
                    if is_behaviour_subclass(attr) and attr_name not in ['BaseAction']:  # 베이스 클래스 제외
                        custom_nodes['Action'].append(attr_name)
            except Exception as e:
                # 커스텀 노드 로드 실패는 경고만 남기고 계속 진행
                print(f"⚠️  커스텀 액션 로드 실패: {e}")
        
        # 커스텀 조건 로드
        conditions_file = nodes_dir / "custom_conditions.py"
        if conditions_file.exists():
            try:
                module_name = f"custom_conditions_{submission_dir.name}"
                spec = importlib.util.spec_from_file_location(module_name, conditions_file)
                module = importlib.util.module_from_spec(spec)
                sys.modules[module_name] = module
                spec.loader.exec_module(module)
                
                # py_trees.behaviour.Behaviour를 상속받은 클래스만 추출 (간접 상속 포함)
                def is_behaviour_subclass(cls):
                    if not isinstance(cls, type):
                        return False
                    for base in cls.__mro__:  # Method Resolution Order 확인
                        if 'Behaviour' in base.__name__:
                            return True
                    return False
                
                for attr_name in dir(module):
                    attr = getattr(module, attr_name)
                    if is_behaviour_subclass(attr) and attr_name not in ['BaseCondition']:  # 베이스 클래스 제외
                        custom_nodes['Condition'].append(attr_name)
            except Exception as e:
                # 커스텀 노드 로드 실패는 경고만 남기고 계속 진행
                print(f"⚠️  커스텀 조건 로드 실패: {e}")
        
        return custom_nodes
