"""
공용 pytest fixtures — 시뮬레이션 없는 테스트용 mock 데이터 제공.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))


def make_obs_dict(ata_deg=90.0, distance_ft=5000.0, bfm_situation="OBFM"):
    """테스트용 obs dict (degrees 기준, runner.py _to_deg() 통과 후 형태)."""
    return {
        "distance_ft": distance_ft,
        "ata_deg": ata_deg,
        "aa_deg": 45.0,
        "hca_deg": 90.0,
        "relative_bearing_deg": 0.0,
        "ego_altitude_ft": 15000.0,
        "ego_vc_kts": 400.0,
        "specific_energy_ft": 20000.0,
        "ps_fts": 0.0,
        "energy_diff_ft": 0.0,
        "closure_rate_kts": 100.0,
        "turn_rate_degs": 5.0,
        "alt_gap_ft": 0.0,
        "tau_deg": 60.0,
        "in_wez": False,
        "enm_in_wez": False,
        "in_39_line": False,
        "overshoot_risk": False,
        "energy_advantage": True,
        "alt_advantage": False,
        "spd_advantage": True,
        "bfm_situation": bfm_situation,
    }


@pytest.fixture
def sample_obs():
    return make_obs_dict()


@pytest.fixture
def sample_window():
    return [make_obs_dict(ata_deg=float(i * 4)) for i in range(20)]


@pytest.fixture
def project_root():
    return Path(__file__).parent.parent
