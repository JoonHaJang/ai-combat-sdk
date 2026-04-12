"""
GAP-2: EIM encoder → ProtoNet 텐서 shape 인터페이스 테스트.
시뮬레이션 불필요.
"""
import sys
from pathlib import Path

import pytest
import torch

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from src.intent.encoder import obs_dict_to_tensor, window_to_tensor, OBS_DIM
from src.intent.proto_net import INTENT_CLASSES


def make_obs(ata_deg=90.0, distance_ft=5000.0) -> dict:
    return {
        "distance_ft": distance_ft, "ata_deg": ata_deg,
        "aa_deg": 45.0, "hca_deg": 90.0, "relative_bearing_deg": 0.0,
        "ego_altitude_ft": 15000.0, "ego_vc_kts": 400.0,
        "specific_energy_ft": 20000.0, "ps_fts": 0.0, "energy_diff_ft": 0.0,
        "closure_rate_kts": 100.0, "turn_rate_degs": 5.0,
        "alt_gap_ft": 0.0, "tau_deg": 60.0,
        "in_wez": False, "enm_in_wez": False, "in_39_line": False,
        "overshoot_risk": False, "energy_advantage": True,
        "alt_advantage": False, "spd_advantage": True,
        "bfm_situation": "OBFM",
    }


class TestEIMInterface:
    def test_obs_dim_constant(self):
        """OBS_DIM = 28 (14 cont + 7 bool + 7 bfm)."""
        assert OBS_DIM == 28, f"OBS_DIM={OBS_DIM}, expected 28"

    def test_obs_dict_to_tensor_shape(self):
        obs = make_obs()
        t = obs_dict_to_tensor(obs)
        assert t.shape == (OBS_DIM,)

    def test_window_to_tensor_shape(self):
        window = [make_obs() for _ in range(20)]
        t = window_to_tensor(window)
        assert t.shape == (20, OBS_DIM), f"Expected (20, {OBS_DIM}), got {t.shape}"

    def test_intent_classes_count(self):
        """6개 intent 클래스."""
        assert len(INTENT_CLASSES) == 6, f"Expected 6 intent classes, got {len(INTENT_CLASSES)}"

    def test_intent_classes_contain_neutral_circle(self):
        assert "NEUTRAL_CIRCLE" in INTENT_CLASSES

    def test_intent_classes_all_valid(self):
        expected = {"GUN_ATTACK", "PURSUIT", "DEFENSIVE", "ENERGY",
                    "NEUTRAL_CIRCLE", "NEUTRAL_SCISSORS"}
        assert set(INTENT_CLASSES) == expected, \
            f"Intent classes mismatch: {set(INTENT_CLASSES)} vs {expected}"

    def test_model_file_exists(self):
        model_path = Path(__file__).parent.parent.parent / "models" / "intent_model.pt"
        assert model_path.exists(), f"EIM model not found: {model_path}"

    def test_model_loads_successfully(self):
        model_path = Path(__file__).parent.parent.parent / "models" / "intent_model.pt"
        if not model_path.exists():
            pytest.skip("models/intent_model.pt not found")
        data = torch.load(model_path, map_location="cpu", weights_only=False)
        assert "prototypes" in data, "intent_model.pt missing 'prototypes' key"
        prototypes = data["prototypes"]
        # prototypes는 {intent_class: Tensor(128,)} 딕셔너리
        assert isinstance(prototypes, dict), \
            f"Expected dict, got {type(prototypes)}"
        assert len(prototypes) == 6, \
            f"Expected 6 prototype classes, got {len(prototypes)}"
        assert set(prototypes.keys()) == set(INTENT_CLASSES), \
            f"Prototype keys mismatch: {set(prototypes.keys())}"

    def test_model_prototypes_finite(self):
        model_path = Path(__file__).parent.parent.parent / "models" / "intent_model.pt"
        if not model_path.exists():
            pytest.skip("models/intent_model.pt not found")
        data = torch.load(model_path, map_location="cpu", weights_only=False)
        prototypes = data["prototypes"]
        for cls_name, tensor in prototypes.items():
            assert torch.isfinite(tensor).all(), \
                f"EIM prototype '{cls_name}' contains NaN or Inf — model may be corrupted"
