"""
GAP-1+3: vector_to_params ↔ params_to_vector 역변환 정확도 단위 테스트.
시뮬레이션 없음 — 순수 수학 함수 검증.
"""
import sys
import math
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from tools.adaptive_optimizer import (
    vector_to_params,
    params_to_vector,
    PARAM_DEFS,
    N_DIMS,
)


class TestVectorEncoding:
    def test_roundtrip_default_vector(self):
        """기본 벡터(0.5) → params → vector 역변환 손실 없음."""
        x = np.full(N_DIMS, 0.5)
        params = vector_to_params(x)
        x_rt = params_to_vector(params)
        # 연속 파라미터는 정확히 복원
        for i, (name, ptype, spec) in enumerate(PARAM_DEFS):
            if ptype == "cont":
                assert abs(x_rt[i] - 0.5) < 1e-9, f"{name}: roundtrip failed ({x_rt[i]} ≠ 0.5)"

    def test_roundtrip_random_vectors(self):
        """랜덤 벡터의 연속 파라미터 역변환 정확도."""
        rng = np.random.default_rng(42)
        for _ in range(50):
            x = rng.uniform(0.0, 1.0, N_DIMS)
            params = vector_to_params(x)
            x_rt = params_to_vector(params)
            for i, (name, ptype, spec) in enumerate(PARAM_DEFS):
                if ptype == "cont":
                    assert abs(x_rt[i] - x[i]) < 1e-6, \
                        f"{name}: x={x[i]:.4f} → rt={x_rt[i]:.4f}"

    def test_vector_bounds_enforced(self):
        """클리핑 경계 밖의 입력도 유효한 params 반환."""
        x_low = np.full(N_DIMS, -1.0)
        x_high = np.full(N_DIMS, 2.0)
        params_low = vector_to_params(x_low)
        params_high = vector_to_params(x_high)

        for i, (name, ptype, spec) in enumerate(PARAM_DEFS):
            if ptype == "cont":
                lo, hi = spec
                assert lo <= params_low[name] <= hi, f"{name} out of range"
                assert lo <= params_high[name] <= hi, f"{name} out of range"

    def test_disc_params_valid_choices(self):
        """이산 파라미터가 항상 정의된 choices에 속함."""
        x = np.full(N_DIMS, 0.5)
        params = vector_to_params(x)
        for name, ptype, spec in PARAM_DEFS:
            if ptype == "disc":
                assert params[name] in spec, \
                    f"{name}={params[name]} not in {spec}"

    def test_n_dims_matches_param_defs(self):
        """N_DIMS가 PARAM_DEFS 길이와 일치."""
        assert N_DIMS == len(PARAM_DEFS), \
            f"N_DIMS={N_DIMS} ≠ len(PARAM_DEFS)={len(PARAM_DEFS)}"

    def test_eim_confidence_range(self):
        """eim_confidence 파라미터 범위 [0.15, 0.50] 검증."""
        eim_def = next((d for d in PARAM_DEFS if d[0] == "eim_confidence"), None)
        assert eim_def is not None, "eim_confidence not found in PARAM_DEFS"
        assert eim_def[1] == "cont"
        lo, hi = eim_def[2]
        assert lo == 0.15, f"eim_confidence lo={lo}, expected 0.15"
        assert hi == 0.50, f"eim_confidence hi={hi}, expected 0.50"

    def test_enable_energy_is_disc(self):
        """enable_energy가 이산 파라미터이고 [True, False] choices."""
        energy_def = next((d for d in PARAM_DEFS if d[0] == "enable_energy"), None)
        assert energy_def is not None, "enable_energy not found in PARAM_DEFS"
        assert energy_def[1] == "disc"
        assert True in energy_def[2] and False in energy_def[2]

    def test_cycle2_best_params_loads(self):
        """Cycle 2 best_params.json이 정상적으로 로드됨.
        NOTE: cycle_2 벡터 길이(104)는 Phase D 확장 후 N_DIMS(113)와 다를 수 있음 — warm-start 정상.
        """
        import json
        best_path = Path(__file__).parent.parent.parent / "logs" / "cycle_2" / "best_params.json"
        if not best_path.exists():
            pytest.skip("cycle_2/best_params.json not found")

        with open(best_path) as f:
            saved = json.load(f)

        assert "vector" in saved, "best_params.json missing 'vector' key"
        vec = np.array(saved["vector"])
        # 벡터 길이는 저장 당시 N_DIMS와 같음 (현재 N_DIMS와 달라도 무방)
        assert len(vec) > 0, "vector is empty"
        assert "score" in saved, "best_params.json missing 'score' key"
        assert saved["score"] > 0, f"Expected positive score, got {saved['score']}"
