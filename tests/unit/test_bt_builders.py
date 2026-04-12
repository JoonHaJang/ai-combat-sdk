"""
GAP-3: BT 빌더 함수 단위 테스트.
generate_bt_yaml(), _cond_node(), _action_node() 구조 검증.
시뮬레이션 없음.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from tools.adaptive_optimizer import (
    generate_bt_yaml,
    _cond_node,
    _action_node,
    vector_to_params,
    PARAM_DEFS,
    N_DIMS,
)
import numpy as np


def default_params():
    return vector_to_params(np.full(N_DIMS, 0.5))


class TestCondActionNodes:
    def test_cond_node_type(self):
        p = default_params()
        node = _cond_node("CustomOrbitDetector", p)
        assert node["type"] == "Condition"
        assert node["name"] == "CustomOrbitDetector"

    def test_action_node_type(self):
        p = default_params()
        node = _action_node("HeadOnBreak", p)
        assert node["type"] == "Action"
        assert node["name"] == "HeadOnBreak"

    def test_node_params_extracted(self):
        p = default_params()
        node = _cond_node("CustomOrbitDetector", p)
        # CustomOrbitDetector has TUNABLE_PARAMS so should have params
        assert "params" in node, "CustomOrbitDetector should have params"

    def test_unknown_node_no_params(self):
        p = default_params()
        node = _action_node("LeadPursuit", p)  # builtin, no tunable params
        # Either no 'params' key, or empty params
        if "params" in node:
            assert node["params"] == {}


class TestGenerateBtYaml:
    def test_root_is_selector(self):
        p = default_params()
        bt = generate_bt_yaml(p)
        assert bt["tree"]["type"] == "Selector"

    def test_first_child_is_harddeck(self):
        p = default_params()
        bt = generate_bt_yaml(p)
        first = bt["tree"]["children"][0]
        assert first["name"] == "HardDeckAvoidance", \
            f"First branch must be HardDeckAvoidance, got {first['name']}"

    def test_harddeck_threshold_in_range(self):
        p = default_params()
        bt = generate_bt_yaml(p)
        harddeck = bt["tree"]["children"][0]
        below_cond = harddeck["children"][0]
        assert below_cond["name"] == "BelowHardDeck"
        threshold = below_cond["params"]["threshold_ft"]
        assert 1000 <= threshold <= 1500, f"threshold_ft={threshold} out of range"

    def test_eim_branch_has_intent_is(self):
        p = default_params()
        p["enable_eim"] = True
        bt = generate_bt_yaml(p)
        eim_branch = next(
            (c for c in bt["tree"]["children"] if c.get("name") == "IntentAdaptiveEscape"),
            None
        )
        assert eim_branch is not None, "IntentAdaptiveEscape branch missing with enable_eim=True"
        intent_node = eim_branch["children"][0]
        assert intent_node["name"] == "EnemyIntentIs"
        assert "min_confidence" in intent_node["params"]

    def test_eim_disabled_removes_branch(self):
        p = default_params()
        p["enable_eim"] = False
        bt = generate_bt_yaml(p)
        names = [c.get("name") for c in bt["tree"]["children"]]
        assert "IntentAdaptiveEscape" not in names

    def test_eim_confidence_injected(self):
        p = default_params()
        p["enable_eim"] = True
        p["eim_confidence"] = 0.42
        bt = generate_bt_yaml(p)
        eim_branch = next(
            c for c in bt["tree"]["children"] if c.get("name") == "IntentAdaptiveEscape"
        )
        conf = eim_branch["children"][0]["params"]["min_confidence"]
        assert abs(conf - 0.42) < 0.01, f"Expected 0.42, got {conf}"

    def test_all_children_have_type(self):
        p = default_params()
        bt = generate_bt_yaml(p)
        for child in bt["tree"]["children"]:
            assert "type" in child, f"Child {child.get('name')} missing 'type'"

    def test_energy_branches_when_enabled(self):
        p = default_params()
        p["enable_energy"] = True
        bt = generate_bt_yaml(p)
        names = [c.get("name") for c in bt["tree"]["children"]]
        assert "EnergyRecovery" in names, "EnergyRecovery branch missing with enable_energy=True"
        assert "EnergyAttack" in names, "EnergyAttack branch missing with enable_energy=True"

    def test_cycle2_best_yaml_parses(self):
        import yaml
        best_path = Path(__file__).parent.parent.parent / "logs" / "cycle_2" / "best.yaml"
        if not best_path.exists():
            pytest.skip("cycle_2/best.yaml not found")
        with open(best_path) as f:
            doc = yaml.safe_load(f)
        assert "tree" in doc
        assert doc["tree"]["type"] == "Selector"
        assert doc["tree"]["children"][0].get("name") in [
            "HardDeckAvoidance", None
        ], "First branch should be HardDeckAvoidance"
