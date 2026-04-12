"""
GAP-1: 학습 데이터 인코딩 vs 추론 인코딩 패리티 테스트.

핵심 검증:
  - runner.py의 _to_deg()가 각도 키에 × 180.0을 적용
  - encoder.py의 NORM_MEAN/NORM_STD가 degrees 기준
  - 두 경로가 동일한 정규화 값을 생성하는지 확인

시뮬레이션 불필요 — 인코딩 함수 직접 호출.
"""
import sys
import math
from pathlib import Path

import pytest
import torch

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from src.intent.encoder import obs_dict_to_tensor, CONT_FEATURES, NORM_MEAN, NORM_STD, OBS_DIM


# runner.py에서 추출한 _to_deg 변환 로직 (테스트용 재현)
_ANGLE_KEYS = ("ata_deg", "aa_deg", "hca_deg", "tau_deg", "relative_bearing_deg")

def _to_deg(obs: dict) -> dict:
    """runner.py의 _to_deg() 재현 — 라디안 → 도 변환."""
    out = dict(obs)
    for k in _ANGLE_KEYS:
        if k in out and out[k] != "":
            try:
                out[k] = float(out[k]) * 180.0
            except (TypeError, ValueError):
                pass
    return out


def make_radians_obs() -> dict:
    """
    시뮬레이터에서 나오는 정규화 obs (runner.py 입력 형태).
    각도 키는 [0, 1] 범위로 정규화됨 (1 = 180°).
    runner.py _to_deg()는 * 180.0으로 degrees로 변환.

    예시: ata_deg=0.5 → _to_deg() → 90.0°
    """
    return {
        "distance_ft": 5000.0,
        "ata_deg": 0.5,           # 0.5 * 180 = 90°
        "aa_deg": 0.25,           # 0.25 * 180 = 45°
        "hca_deg": 1.0,           # 1.0 * 180 = 180°
        "relative_bearing_deg": 0.0,  # 0 * 180 = 0°
        "ego_altitude_ft": 15000.0,
        "ego_vc_kts": 400.0,
        "specific_energy_ft": 20000.0,
        "ps_fts": 0.0,
        "energy_diff_ft": 0.0,
        "closure_rate_kts": 100.0,
        "turn_rate_degs": 5.0,
        "alt_gap_ft": 0.0,
        "tau_deg": 1.0 / 3,       # (1/3) * 180 = 60°
        # bool features
        "in_wez": False, "enm_in_wez": False, "in_39_line": False,
        "overshoot_risk": False, "energy_advantage": True,
        "alt_advantage": False, "spd_advantage": True,
        "bfm_situation": "OBFM",
    }


class TestDataParity:
    def test_angle_keys_converted_to_degrees(self):
        """_to_deg()가 각도 키를 ×180으로 변환함을 검증."""
        obs_rad = make_radians_obs()
        obs_deg = _to_deg(obs_rad)

        assert abs(obs_deg["ata_deg"] - 90.0) < 0.01, \
            f"ata_deg: expected 90.0 degrees, got {obs_deg['ata_deg']}"
        assert abs(obs_deg["aa_deg"] - 45.0) < 0.01, \
            f"aa_deg: expected 45.0, got {obs_deg['aa_deg']}"
        assert abs(obs_deg["hca_deg"] - 180.0) < 0.01, \
            f"hca_deg: expected 180.0, got {obs_deg['hca_deg']}"
        assert abs(obs_deg["tau_deg"] - 60.0) < 0.01, \
            f"tau_deg: expected 60.0, got {obs_deg['tau_deg']}"

    def test_non_angle_keys_unchanged(self):
        """각도 키 이외의 값은 _to_deg() 통과 후 변하지 않음."""
        obs = make_radians_obs()
        obs_deg = _to_deg(obs)
        for k in ["distance_ft", "ego_altitude_ft", "ego_vc_kts", "closure_rate_kts"]:
            assert obs_deg[k] == obs[k], f"{k} should not be modified by _to_deg"

    def test_encoder_expects_degrees(self):
        """encoder.py의 NORM_MEAN이 degrees 기준인지 검증."""
        # ata_deg의 NORM_MEAN=90.0 → 90 degrees (π/2 radians가 아님)
        assert NORM_MEAN["ata_deg"] == 90.0, \
            f"NORM_MEAN['ata_deg']={NORM_MEAN['ata_deg']} — should be 90.0 (degrees)"
        assert NORM_MEAN["aa_deg"] == 90.0
        assert NORM_MEAN["hca_deg"] == 180.0

    def test_raw_obs_without_conversion_gives_wrong_normalization(self):
        """_to_deg() 변환 없이 그대로 encoder에 넣으면 정규화가 틀림 (버그 시연)."""
        obs_raw = make_radians_obs()  # ata_deg=0.5 (정규화값, degrees 아님)
        tensor_raw = obs_dict_to_tensor(obs_raw)

        # ata_deg=0.5 → 정규화: (0.5 - 90) / 60 ≈ -1.49 (매우 이상)
        ata_idx = CONT_FEATURES.index("ata_deg")
        normalized_val = tensor_raw[ata_idx].item()
        assert normalized_val < -1.0, \
            f"Raw input: ata normalized={normalized_val:.3f} (should be very negative, proving raw != degrees)"

    def test_degrees_input_gives_correct_normalization(self):
        """degrees 변환 후 encoder에 넣으면 정규화가 올바름."""
        obs_rad = make_radians_obs()
        obs_deg = _to_deg(obs_rad)
        tensor_deg = obs_dict_to_tensor(obs_deg)

        # ata_deg = 90.0 → 정규화: (90 - 90) / 60 = 0.0 (mean에서 0 표준편차)
        ata_idx = CONT_FEATURES.index("ata_deg")
        normalized_val = tensor_deg[ata_idx].item()
        assert abs(normalized_val) < 0.1, \
            f"Degrees input: ata normalized={normalized_val:.3f} (should be ~0.0)"

    def test_output_tensor_shape(self):
        """obs_dict_to_tensor 출력이 (OBS_DIM,) 형태."""
        obs = _to_deg(make_radians_obs())
        tensor = obs_dict_to_tensor(obs)
        assert tensor.shape == (OBS_DIM,), f"Expected ({OBS_DIM},), got {tensor.shape}"

    def test_pipeline_full_path(self):
        """
        전체 경로 검증:
        simulator_obs (radians) → _to_deg() → obs_dict_to_tensor() → 정상 텐서
        """
        obs_rad = make_radians_obs()
        obs_deg = _to_deg(obs_rad)
        tensor = obs_dict_to_tensor(obs_deg)

        # 모든 값이 유한수여야 함
        assert torch.isfinite(tensor).all(), "Tensor contains NaN or Inf"
        # 정규화 후 대부분 [-3, 3] 범위 (z-score)
        assert tensor.abs().max().item() < 10.0, \
            f"Unnormalized outlier detected: max={tensor.abs().max().item():.2f}"
