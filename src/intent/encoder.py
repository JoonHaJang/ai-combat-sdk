"""
encoder.py — TacticalEncoder

K-step 적 관측값 시퀀스 → 고정 크기 embedding 벡터.

입력 features (28개):
  연속형 (14): distance_ft, ata_deg, aa_deg, hca_deg,
               relative_bearing_deg, ego_altitude_ft, ego_vc_kts,
               specific_energy_ft, ps_fts, energy_diff_ft,
               closure_rate_kts, turn_rate_degs, alt_gap_ft, tau_deg
  이진형  (7):  in_wez, enm_in_wez, in_39_line, overshoot_risk,
               energy_advantage, alt_advantage, spd_advantage
  BFM one-hot (7): OBFM, DBFM, HABFM, UNKNOWN,
                   UNK_NEAR_OFF, UNK_SCISSORS, UNK_DISENGAGING
"""

import torch
import torch.nn as nn

# ──────────────────────────────────────────────
# Feature 정의
# ──────────────────────────────────────────────

CONT_FEATURES = [
    "distance_ft", "ata_deg", "aa_deg", "hca_deg",
    "relative_bearing_deg", "ego_altitude_ft", "ego_vc_kts",
    "specific_energy_ft", "ps_fts", "energy_diff_ft",
    "closure_rate_kts", "turn_rate_degs", "alt_gap_ft", "tau_deg",
]

BOOL_FEATURES = [
    "in_wez", "enm_in_wez", "in_39_line", "overshoot_risk",
    "energy_advantage", "alt_advantage", "spd_advantage",
]

# BFM 상황 one-hot (7개): 기본 4 + UNKNOWN 세분화 3
BFM_CLASSES = [
    "OBFM", "DBFM", "HABFM", "UNKNOWN",
    "UNK_NEAR_OFF",      # UNKNOWN + ATA<45° (공격 직전)
    "UNK_SCISSORS",      # UNKNOWN + 45°≤ATA<70° + closure<0 (Scissors 교착)
    "UNK_DISENGAGING",   # UNKNOWN + ATA≥70° or closure≥0 (이탈 중)
]

ALL_FEATURES = CONT_FEATURES + BOOL_FEATURES + BFM_CLASSES
OBS_DIM = len(ALL_FEATURES)   # 14 + 7 + 7 = 28

# 연속형 feature 정규화 통계 (Phase 1 기준 추정값, 학습 후 업데이트)
NORM_MEAN = {
    "distance_ft":          15000.0,
    "ata_deg":               90.0,
    "aa_deg":                90.0,
    "hca_deg":              180.0,
    "relative_bearing_deg":  0.0,
    "ego_altitude_ft":    15000.0,
    "ego_vc_kts":           400.0,
    "specific_energy_ft": 20000.0,
    "ps_fts":                 0.0,
    "energy_diff_ft":         0.0,
    "closure_rate_kts":       0.0,
    "turn_rate_degs":         0.0,
    "alt_gap_ft":             0.0,
    "tau_deg":                0.0,
}
NORM_STD = {
    "distance_ft":         10000.0,
    "ata_deg":               60.0,
    "aa_deg":                60.0,
    "hca_deg":              100.0,
    "relative_bearing_deg": 90.0,
    "ego_altitude_ft":    10000.0,
    "ego_vc_kts":           100.0,
    "specific_energy_ft":  5000.0,
    "ps_fts":              500.0,
    "energy_diff_ft":     5000.0,
    "closure_rate_kts":    200.0,
    "turn_rate_degs":       10.0,
    "alt_gap_ft":         5000.0,
    "tau_deg":              60.0,
}


def obs_dict_to_tensor(obs: dict) -> torch.Tensor:
    """단일 obs dict → feature 벡터 (OBS_DIM,)."""
    vec = []
    for f in CONT_FEATURES:
        val = float(obs.get(f, 0.0))
        val = (val - NORM_MEAN[f]) / (NORM_STD[f] + 1e-8)
        vec.append(val)
    for f in BOOL_FEATURES:
        raw = obs.get(f, False)
        if isinstance(raw, str):
            raw = raw.lower() == "true"
        vec.append(float(bool(raw)))
    bfm = obs.get("bfm_situation", "UNKNOWN")
    for cls in BFM_CLASSES:
        vec.append(1.0 if bfm == cls else 0.0)
    return torch.tensor(vec, dtype=torch.float32)


def window_to_tensor(window: list[dict]) -> torch.Tensor:
    """K개 obs dict 리스트 → (K, OBS_DIM) 텐서."""
    return torch.stack([obs_dict_to_tensor(o) for o in window])


# ──────────────────────────────────────────────
# TacticalEncoder
# ──────────────────────────────────────────────

class TacticalEncoder(nn.Module):
    """
    GRU 기반 시퀀스 인코더.
    입력: (batch, K, OBS_DIM)
    출력: (batch, embed_dim) L2-정규화 embedding
    """

    def __init__(
        self,
        obs_dim: int = OBS_DIM,
        hidden_dim: int = 128,
        num_layers: int = 2,
        embed_dim: int = 64,
        dropout: float = 0.1,
    ):
        super().__init__()
        self.obs_dim   = obs_dim
        self.embed_dim = embed_dim

        self.gru = nn.GRU(
            input_size=obs_dim,
            hidden_size=hidden_dim,
            num_layers=num_layers,
            batch_first=True,
            dropout=dropout if num_layers > 1 else 0.0,
        )
        self.proj = nn.Sequential(
            nn.Linear(hidden_dim, hidden_dim),
            nn.ReLU(),
            nn.Dropout(dropout),
            nn.Linear(hidden_dim, embed_dim),
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        """
        x: (batch, K, obs_dim)
        returns: (batch, embed_dim)  — L2 normalized
        """
        _, h = self.gru(x)          # h: (num_layers, batch, hidden_dim)
        h_last = h[-1]              # (batch, hidden_dim) — 마지막 레이어
        emb = self.proj(h_last)     # (batch, embed_dim)
        return nn.functional.normalize(emb, dim=-1)

    def encode_window(self, window: list[dict]) -> torch.Tensor:
        """단일 K-step window (list of obs dict) → (embed_dim,) 벡터."""
        x = window_to_tensor(window).unsqueeze(0)   # (1, K, OBS_DIM)
        self.eval()
        with torch.no_grad():
            return self.forward(x).squeeze(0)
