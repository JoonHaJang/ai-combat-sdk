"""Intents — 명명된 전술 분기 (BFM 정리 기반 두-층 표현).

각 Intent 는:
  Layer 1 — Hard predicate Φ_i(x): 정리 entry 조건 부등식의 conjunction
  Layer 2 — Soft score ρ_i(x): 같은 식들의 sigmoid 곱 (blending 용)
  Action — Φ_i=True 시 (alt_bin, hdg_bin, vel_bin) 산출 + 단계 diagnostic

분기 선택 (PursuitChaseOptimal 에서):
  branch* = first i where Φ_i(x)=True (priority order)
  Φ_i 모두 False → HJI fallback

설계 원칙 (사용자 지침):
  - 분기 진입은 raw threshold 가 아니라 **정리에서 유도된 식** 의 값으로 결정.
  - 결정은 legible: tick 별 (intent, Φ 조건별 boolean, ρ, action, phase) 로깅 가능.
  - 채점 기준은 불변. BT 가 정리에 부합하지 않으면 BT 가 바뀐다.
"""

from __future__ import annotations

import math
from collections import deque
from typing import Tuple, Dict, Any

import numpy as np


# ─── 물리·envelope 상수 (sim_dogfight_verify.py 와 일치) ─────────
KTS_TO_FPS = 1.6878
OMEGA_MAX_DEG = 19.16
V_CORNER_KTS = 350.0
V_MAX_KTS = 420.0
V_MIN_KTS = 160.0
G_FT_S2 = 32.174


def _sigmoid(x: float) -> float:
    if x > 20: return 1.0
    if x < -20: return 0.0
    return 1.0 / (1.0 + math.exp(-x))


def _gauss(x: float, mu: float, sigma: float) -> float:
    return math.exp(-((x - mu) ** 2) / (2.0 * sigma * sigma))


def _denorm_deg(obs: dict, key: str, default: float = 0.0) -> float:
    """obs 의 [-1,1] 정규화 도 값을 deg 로 복원. 이미 deg 면 그대로."""
    v = obs.get(key, default)
    return v * 180.0 if abs(v) <= 1.5 else v


def unpack_obs(obs: dict) -> dict:
    """28-feature obs → 표준 물리량 dict (deg, kts, ft)."""
    return {
        "ata":     _denorm_deg(obs, "ata_deg"),
        "aa":      _denorm_deg(obs, "aa_deg"),
        "hca":     _denorm_deg(obs, "hca_deg"),
        "rb":      _denorm_deg(obs, "relative_bearing_deg"),
        "closure": float(obs.get("closure_rate_kts", 0.0)),
        "dist":    float(obs.get("distance_ft", 0.0)),
        "alt_gap": float(obs.get("alt_gap_ft", 0.0)),
        "alt":     float(obs.get("ego_altitude_ft", 10000.0)),
        "v_us":    float(obs.get("ego_vc_kts", 300.0)),
        "pitch":   float(obs.get("pitch_deg", 0.0)),
        "tr":      float(obs.get("turn_rate_degs", 0.0)),
    }


# ─── Intent base class ──────────────────────────────────────────

class Intent:
    name: str = "Base"
    theorem: str = "none"

    def __init__(self, history_len: int = 10):
        self._history = deque(maxlen=history_len)

    def evaluate(self, obs: dict) -> Tuple[bool, float, dict]:
        """Returns (Φ: bool, ρ: float in [0,1], diag: dict)."""
        raise NotImplementedError

    def action(self, obs: dict) -> Tuple[int, int, int, dict]:
        """Returns (alt_bin, hdg_bin, vel_bin, action_diag)."""
        raise NotImplementedError

    def update_history(self, obs: dict) -> None:
        self._history.append(unpack_obs(obs))

    # ─── 공통 helper ─────────────────────────────────────────
    @staticmethod
    def rb_to_hdg_bin(rb_deg: float) -> int:
        """relative_bearing → hdg bin (0=hard left ↶, 4=straight, 8=hard right ↷).

        Sim CSV convention: rb_deg > 0 → 적 우측 (CCW math),
                            rb_deg < 0 → 적 좌측.
        Bin convention:     bin > 4 → 우선회, bin < 4 → 좌선회.
        ⟹ bin = 4 + clamp(rb_deg / 22.5, -4, 4)
        """
        rb = ((rb_deg + 180.0) % 360.0) - 180.0  # normalize to (-180, 180]
        offset = rb / 22.5
        bin_idx = int(round(4 + offset))
        return max(0, min(8, bin_idx))


# ─── Intent 1: HighYoYoBait (정리 8 — Pontryagin 수직 평면 최적 제어) ─

class HighYoYoBait(Intent):
    """정리 8 (Pontryagin 수직 BFM): 적 alt-track lag 활용 수직 bang-bang.

    Layer 1 — Φ_yoyo (4 conjuncts):
      ① closure > 20 kts                — chase 진행 중 (이탈 아님)
      ② 20° ≤ ATA ≤ 70°                 — 정렬 가능 범위
      ③ Ps_margin > 0                    — 우리 에너지 헤드룸 (수직 기동 자원)
      ④ τ_alt_enemy > 0.5 s              — 적 수직 응답 lag (착취 가능)

    Layer 2 — ρ_yoyo = σ(①) · gauss(②) · σ(③) · σ(④)

    Action:
      Phase 1 (climb): alt_gap < 1500 ft ∧ pitch < 25° → max climb + 코너속도
      Phase 2 (dive):  alt_gap ≥ 1500 ft ∨ pitch ≥ 25° → max descend + 적 방위 가속
    """
    name = "HighYoYoBait"
    theorem = "정리 8 (Pontryagin vertical bang-bang)"

    # ─ Layer 1 식들 (각각 단일 방정식, 정리 8 entry 조건) ─

    @staticmethod
    def _eq_closure(u: dict) -> float:
        """식 ① closure rate (kts). +20 임계."""
        return u["closure"]

    @staticmethod
    def _eq_ata(u: dict) -> float:
        """식 ② ATA (deg). [20, 70] 영역."""
        return u["ata"]

    @staticmethod
    def _eq_ps_margin(u: dict) -> float:
        """식 ③ Ps_margin proxy (kts equivalent).

        근사: Ps_us ≈ V_us - V_corner (실 Boyd Ps 의 1차 proxy).
        +30 offset 으로 코너속도 ± 30kts 내면 헤드룸 충분으로 간주.
        엄밀한 Ps = (T-D)V/W - n·g·V/V_max 는 thrust·drag 추정 필요 →
        측정 가능 obs 만 사용하는 보수 proxy 채택.
        """
        return u["v_us"] - V_CORNER_KTS + 30.0

    def _eq_tau_alt(self, u: dict) -> float:
        """식 ④ τ_alt_enemy (sec) — 적 수직 응답 시상수 추정.

        측정 원리: 우리가 γ 변화시킨 직후 alt_gap 변화량이 작으면 적이 빠르게 track →
                  τ_alt 작음. 변화량이 크면 적 lag 큼 → τ_alt 큼.

        엄밀: τ_alt = - log|alt_gap_residual / alt_gap_init| / Δt — 1차 시상수.
        실 매치 obs 만으로 ID 어려우니 비례식 proxy:
          τ_alt ≈ base + (|Δalt_gap| / max(|Δpitch_us| · K, ε))
          base = 0.2s (즉시 응답 한계),  K=50ft/deg (geometric)

        history 부족 (3 tick 미만) 또는 우리 pitch 변화 없으면 default 0.8s
        (offensive 정책 측정치, BFM_FOUND §10.1).
        """
        if len(self._history) < 3:
            return 0.8
        h = list(self._history)[-3:]
        d_alt_gap = abs(h[-1]["alt_gap"] - h[0]["alt_gap"])
        d_pitch_us = abs(h[-1]["pitch"] - h[0]["pitch"])
        if d_pitch_us < 1.0:
            return 0.8
        K_ft_per_deg = 50.0
        proxy = 0.2 + d_alt_gap / (d_pitch_us * K_ft_per_deg + 1e-6)
        return float(np.clip(proxy, 0.2, 2.5))

    def evaluate(self, obs: dict) -> Tuple[bool, float, dict]:
        u = unpack_obs(obs)

        v_closure = self._eq_closure(u)
        v_ata     = self._eq_ata(u)
        v_ps      = self._eq_ps_margin(u)
        v_tau     = self._eq_tau_alt(u)

        # ─── Layer 1 hard predicate ───────────────────────
        c1 = v_closure > 20.0
        c2 = (20.0 <= v_ata <= 70.0)
        c3 = v_ps > 0.0
        c4 = v_tau > 0.5
        phi = c1 and c2 and c3 and c4

        # ─── Layer 2 soft score ───────────────────────────
        s1 = _sigmoid((v_closure - 20.0) / 20.0)
        s2 = _gauss(v_ata, mu=45.0, sigma=20.0)
        s3 = _sigmoid(v_ps / 30.0)
        s4 = _sigmoid((v_tau - 0.5) / 0.3)
        rho = s1 * s2 * s3 * s4

        diag = {
            "phi": phi,
            "rho": rho,
            "cond": [
                ("closure>20",   round(v_closure, 1), c1),
                ("20<=ATA<=70",  round(v_ata, 1),     c2),
                ("Ps_margin>0",  round(v_ps, 1),      c3),
                ("tau_alt>0.5",  round(v_tau, 2),     c4),
            ],
            "soft": [round(s1, 3), round(s2, 3), round(s3, 3), round(s4, 3)],
        }
        return phi, rho, diag

    def action(self, obs: dict) -> Tuple[int, int, int, dict]:
        u = unpack_obs(obs)

        # Phase 결정 (Pontryagin bang-bang 의 switch surface)
        in_dive = (u["alt_gap"] >= 1500.0) or (u["pitch"] >= 25.0)

        hdg_bin = self.rb_to_hdg_bin(u["rb"])

        if not in_dive:
            # ── Phase 1: climb (정점 까지 pull-up) ──
            alt_bin = 4  # max climb (γ_max)
            if u["v_us"] > V_CORNER_KTS + 5.0:
                vel_bin = 1   # decel to V_corner
            elif u["v_us"] < V_CORNER_KTS - 5.0:
                vel_bin = 3   # mild accel toward V_corner
            else:
                vel_bin = 2   # hold V_corner
            phase = "climb"
        else:
            # ── Phase 2: invert dive ──
            alt_bin = 0   # max descend
            vel_bin = 3   # 가속 (dive + thrust)
            phase = "dive"

        diag = {
            "phase":     phase,
            "alt_bin":   alt_bin,
            "hdg_bin":   hdg_bin,
            "vel_bin":   vel_bin,
            "alt_gap":   round(u["alt_gap"], 0),
            "pitch":     round(u["pitch"], 1),
            "v_us":      round(u["v_us"], 1),
            "rb":        round(u["rb"], 1),
        }
        return alt_bin, hdg_bin, vel_bin, diag


# ─── Registry ───────────────────────────────────────────────────
# 우선순위 순. 사용자 지침: 분기 추가는 정리 entry 조건이 명확한 것부터.
INTENT_ORDER = [HighYoYoBait]
