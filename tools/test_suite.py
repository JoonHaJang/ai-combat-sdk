"""
자동 검증 테스트 스위트 — Phase 1b

BT 에이전트의 구조적 정합성을 자동 검증.
매치를 돌리기 전에 "이 에이전트가 제대로 구성되어 있는가"를 확인.

사용법:
    python tools/test_suite.py adaptive_eagle
    python tools/test_suite.py adaptive_eagle --all
    python tools/test_suite.py adaptive_eagle --test name_collision
"""

import sys
import importlib
import argparse
from pathlib import Path

import yaml

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# ─── 빌트인 노드 목록 (NODE_REFERENCE.md 기반) ───────────────

BUILTIN_CONDITIONS = {
    "EnemyInRange", "DistanceBelow", "DistanceAbove",
    "AltitudeAbove", "AltitudeBelow", "BelowHardDeck",
    "VelocityAbove", "VelocityBelow",
    "IsOffensiveSituation", "IsDefensiveSituation", "IsNeutralSituation",
    "ATAAbove", "ATABelow", "UnderThreat",
    "LOSAbove", "LOSBelow", "InEnemyWEZ",
    "EnergyHighPs", "SpecificEnergyAbove", "IsMerged",
    "Is39Line", "IsOvershootRisk", "IsTargetInSight",
    "IsOneCircle", "IsTwoCircle",
    "IsEnergyAdvantage", "IsAltAdvantage", "IsSpdAdvantage",
    "EnergyDiffAbove", "ClosureRateAbove", "ClosureRateBelow", "TurnRateAbove",
    # pyd 내부 (문서 미기재이지만 존재 확인됨)
    "IsCircularOrbit",
}

BUILTIN_ACTIONS = {
    "MaintainAltitude", "Accelerate", "Decelerate", "Straight",
    "TurnLeft", "TurnRight",
    "ClimbTo", "DescendTo", "AltitudeAdvantage",
    "Pursue", "LeadPursuit", "PurePursuit", "LagPursuit",
    "DefensiveManeuver", "BreakTurn", "DefensiveSpiral",
    "ClimbingTurn", "DescendingTurn", "BarrelRoll", "HighYoYo", "LowYoYo",
    "OneCircleFight", "TwoCircleFight", "GunAttack",
    "Evade",
    "OvershootAvoidance", "EnergyFight", "TCFight",
}

BUILTIN_NODES = BUILTIN_CONDITIONS | BUILTIN_ACTIONS


# ─── YAML 파싱 유틸 ──────────────────────────────────────────

def _resolve_agent(name: str) -> Path:
    """에이전트 이름 → YAML 파일 경로."""
    if "/" in name or "\\" in name:
        p = Path(name)
        if not p.is_absolute():
            p = PROJECT_ROOT / name
        if p.exists():
            return p

    for pattern in [
        PROJECT_ROOT / "submissions" / name / f"{name}.yaml",
        PROJECT_ROOT / "examples" / f"{name}.yaml",
        PROJECT_ROOT / "examples" / name / f"{name}.yaml",
    ]:
        if pattern.exists():
            return pattern

    raise FileNotFoundError(f"Agent not found: {name}")


def _extract_node_names(tree_node: dict, names: set = None) -> set:
    """YAML 트리에서 사용된 모든 노드 이름 재귀 추출."""
    if names is None:
        names = set()
    if isinstance(tree_node, dict):
        name = tree_node.get("name")
        if name:
            names.add(name)
        for child in tree_node.get("children", []):
            _extract_node_names(child, names)
    return names


def _extract_leaf_node_names(tree_node: dict, names: set = None) -> set:
    """YAML 트리에서 Action/Condition 타입 노드 이름만 추출 (Sequence/Selector name 제외)."""
    if names is None:
        names = set()
    if isinstance(tree_node, dict):
        node_type = tree_node.get("type", "")
        name = tree_node.get("name")
        if name and node_type in ("Action", "Condition"):
            names.add(name)
        for child in tree_node.get("children", []):
            _extract_leaf_node_names(child, names)
    return names


def _extract_custom_node_names(tree_node: dict, custom_only: set = None) -> set:
    """YAML 트리에서 빌트인이 아닌 Action/Condition 노드 이름만 추출."""
    leaf_names = _extract_leaf_node_names(tree_node)
    return leaf_names - BUILTIN_NODES


def _load_init_imports(agent_dir: Path) -> set:
    """nodes/ 패키지 전체에서 import/정의된 클래스명 추출.

    __init__.py + custom_actions.py + custom_conditions.py 모두 스캔하여
    re-export 패턴(from external import X)도 포착.
    """
    imported = set()

    nodes_dir = agent_dir / "nodes"
    if not nodes_dir.exists():
        return imported

    for py_file in nodes_dir.glob("*.py"):
        for line in py_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith("#") or not line:
                continue
            # from ... import A, B, C 패턴
            if "import" in line:
                parts = line.split("import", 1)
                if len(parts) == 2:
                    names_str = parts[1].replace("(", "").replace(")", "")
                    for name in names_str.split(","):
                        name = name.strip().split("#")[0].strip()
                        if name and name[0].isupper():
                            imported.add(name)
            # class ClassName 패턴
            if line.startswith("class ") and "(" in line:
                cls_name = line.split("class ", 1)[1].split("(")[0].strip()
                if cls_name:
                    imported.add(cls_name)

    return imported


def _load_init_params(agent_dir: Path, class_name: str) -> set:
    """커스텀 노드 클래스의 __init__ 파라미터명 추출."""
    for py_file in (agent_dir / "nodes").glob("*.py"):
        if py_file.name == "__init__.py":
            continue
        text = py_file.read_text(encoding="utf-8")
        # 간단한 파싱: class ClassName 찾고 def __init__ 의 파라미터 추출
        in_class = False
        for line in text.splitlines():
            if f"class {class_name}" in line:
                in_class = True
                continue
            if in_class and "def __init__" in line:
                # self, name="X", param1=1.0, param2=2.0 에서 파라미터 추출
                sig = line.split("(", 1)[1].rsplit(")", 1)[0] if "(" in line else ""
                params = set()
                for part in sig.split(","):
                    part = part.strip()
                    if "=" in part:
                        pname = part.split("=")[0].strip().split(":")[ 0].strip()
                        if pname not in ("self", "name"):
                            params.add(pname)
                return params
            if in_class and line.strip() and not line.startswith(" ") and not line.startswith("\t"):
                if "class " in line:
                    in_class = False
    return set()


def _extract_yaml_params(tree_node: dict, result: dict = None) -> dict:
    """YAML 트리에서 {노드명: {파라미터명 set}} 추출."""
    if result is None:
        result = {}
    if isinstance(tree_node, dict):
        name = tree_node.get("name")
        params = tree_node.get("params", {})
        if name and params:
            result[name] = set(params.keys())
        for child in tree_node.get("children", []):
            _extract_yaml_params(child, result)
    return result


# ─── 테스트 함수들 ───────────────────────────────────────────

class TestResult:
    def __init__(self, name: str, passed: bool, message: str):
        self.name = name
        self.passed = passed
        self.message = message

    def __str__(self):
        tag = "PASS" if self.passed else "FAIL"
        return f"  [{tag}] {self.name}: {self.message}"


def test_name_collision(yaml_path: Path, tree: dict, agent_dir: Path) -> TestResult:
    """커스텀 노드명이 pyd 빌트인과 충돌하지 않는지 검증."""
    custom_names = _extract_custom_node_names(tree)
    init_imports = _load_init_imports(agent_dir)
    all_custom = custom_names | init_imports

    collisions = all_custom & BUILTIN_NODES
    if collisions:
        return TestResult(
            "name_collision",
            False,
            f"빌트인과 동명 충돌: {collisions} — pyd가 우선하여 커스텀 무시됨"
        )
    return TestResult("name_collision", True, f"충돌 없음 (커스텀 {len(all_custom)}개)")


def test_yaml_init_match(yaml_path: Path, tree: dict, agent_dir: Path) -> TestResult:
    """YAML params의 키가 커스텀 노드 __init__ 파라미터와 일치하는지 검증."""
    yaml_params = _extract_yaml_params(tree)
    custom_names = _extract_custom_node_names(tree)
    mismatches = []

    for node_name in custom_names:
        if node_name not in yaml_params:
            continue
        init_params = _load_init_params(agent_dir, node_name)
        if not init_params:
            continue
        yaml_keys = yaml_params[node_name]
        unknown = yaml_keys - init_params
        if unknown:
            mismatches.append(f"{node_name}: YAML에 {unknown} 있지만 __init__에 없음")

    if mismatches:
        return TestResult("yaml_init_match", False, "; ".join(mismatches))
    return TestResult("yaml_init_match", True, "YAML params ↔ __init__ 일치")


def test_init_imports(yaml_path: Path, tree: dict, agent_dir: Path) -> TestResult:
    """YAML에서 참조하는 커스텀 노드가 __init__.py에 import되어 있는지 검증."""
    custom_in_yaml = _extract_custom_node_names(tree)
    if not custom_in_yaml:
        return TestResult("init_imports", True, "커스텀 노드 없음")

    init_file = agent_dir / "nodes" / "__init__.py"
    if not init_file.exists():
        return TestResult(
            "init_imports", False,
            f"nodes/__init__.py 없음 — 커스텀 노드 {custom_in_yaml} 로딩 불가"
        )

    imported = _load_init_imports(agent_dir)
    missing = custom_in_yaml - imported
    if missing:
        return TestResult(
            "init_imports", False,
            f"__init__.py에 미import: {missing} — 빌트인 fallback 또는 로딩 실패"
        )
    return TestResult("init_imports", True, f"모든 커스텀 노드 import 확인 ({len(custom_in_yaml)}개)")


def test_dead_code(yaml_path: Path, tree: dict, agent_dir: Path) -> TestResult:
    """__init__.py에 import되었지만 YAML에서 미사용인 클래스 검출."""
    imported = _load_init_imports(agent_dir)
    used_in_yaml = _extract_node_names(tree)
    unused = imported - used_in_yaml - {"BaseAction"}  # BaseAction은 상속용

    if unused:
        return TestResult(
            "dead_code", False,
            f"import 되었으나 YAML 미사용: {unused}"
        )
    return TestResult("dead_code", True, "dead code 없음")


def test_tree_structure(yaml_path: Path, tree: dict, agent_dir: Path) -> TestResult:
    """트리 최상위가 Selector이고, 첫 브랜치가 HardDeck 회피인지 검증."""
    issues = []

    root_type = tree.get("type")
    if root_type != "Selector":
        issues.append(f"루트가 {root_type} (Selector 권장)")

    children = tree.get("children", [])
    if not children:
        issues.append("children 비어있음")
    else:
        first = children[0]
        first_name = first.get("name", "")
        first_children = first.get("children", [])
        has_harddeck = False
        for child in first_children:
            if child.get("name") in ("BelowHardDeck",):
                has_harddeck = True
                break
        if not has_harddeck and "HardDeck" not in first_name:
            issues.append("첫 브랜치에 BelowHardDeck 없음 — Hard Deck 패배 위험")

    if issues:
        return TestResult("tree_structure", False, "; ".join(issues))
    return TestResult("tree_structure", True, f"구조 정상 ({len(children)} 브랜치)")


# ─── 전체 실행 ───────────────────────────────────────────────

ALL_TESTS = {
    "name_collision": test_name_collision,
    "yaml_init_match": test_yaml_init_match,
    "init_imports": test_init_imports,
    "dead_code": test_dead_code,
    "tree_structure": test_tree_structure,
}


def run_tests(agent_name: str, tests: list = None) -> list:
    """지정된 테스트 실행, 결과 리스트 반환."""
    yaml_path = _resolve_agent(agent_name)
    agent_dir = yaml_path.parent

    with open(yaml_path, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    tree = data.get("tree", {})

    if tests is None:
        tests = list(ALL_TESTS.keys())

    results = []
    for test_name in tests:
        fn = ALL_TESTS.get(test_name)
        if fn is None:
            results.append(TestResult(test_name, False, f"Unknown test: {test_name}"))
            continue
        try:
            result = fn(yaml_path, tree, agent_dir)
        except Exception as e:
            result = TestResult(test_name, False, f"Exception: {e}")
        results.append(result)

    return results


def main():
    parser = argparse.ArgumentParser(description="BT 에이전트 자동 검증 테스트")
    parser.add_argument("agent", help="테스트할 에이전트 이름")
    parser.add_argument("--test", type=str, default=None,
                        help="특정 테스트만 실행 (name_collision, yaml_init_match, init_imports, dead_code, tree_structure)")
    parser.add_argument("--all", action="store_true",
                        help="모든 테스트 실행 (기본)")

    args = parser.parse_args()

    tests = [args.test] if args.test else None

    print(f"\n  Testing: {args.agent}")
    print(f"  {'='*50}")

    results = run_tests(args.agent, tests)

    passed = sum(1 for r in results if r.passed)
    failed = sum(1 for r in results if not r.passed)

    for r in results:
        print(r)

    print(f"\n  Result: {passed} passed, {failed} failed")
    if failed > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
