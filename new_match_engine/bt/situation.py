"""Feature 기반 BFM 상황 분류 — 단일 advantage 스칼라 금지.

★ 출처: ai-combat-core-main/src/control/bfm_classifier.py (사용자 검증 분류).
  advantage 1개로 뭉개면 (ata0/aa90 vs ata90/aa0 가 같은 advantage) 상황 구분 불가.
  → ata·aa 분리 + 거리 + 에너지 + HCA + closure 다중 feature 로 분류.

새 obs(Observation)에서 직접 계산:
  HCA(heading crossing) = |wrap(ego_psi − enm_psi)|  (head-on → 180)
  Es = alt + V²/2g (에너지). energy_advantage = Es_us > Es_op + margin
  in_39_line ≈ aa < 90 (적 후방반구 점유)
우선순위: DBFM(방어) > OBFM(공격) > HABFM(중립). 방어가 최위험이라 최우선.
"""
from __future__ import annotations
import math

# ★ 물리 기반 상호배타 상황 (측정 확인: 교전유형마다 지배 물리량 다름)
#   CHASE  = 속도벡터 정렬(HCA↓) → 속도(closure) 지배. 최적 = max speed.
#   CIRCLE = 속도벡터 교차(HCA↑) → 선회율 ω·반경 R 지배. 최적 = corner speed.
#   DEFENSIVE = 적이 우리 뒤 위협 → 적 WEZ 거부. (최우선)
DEFENSIVE, CHASE, CIRCLE = "DEFENSIVE", "CHASE", "CIRCLE"
OFFENSIVE, NEUTRAL = "CHASE", "CIRCLE"   # 하위호환 alias (구 코드용)

HCA_ALIGNED_MAX = 45.0   # HCA<이값 = 속도벡터 정렬(추격), 이상 = 교차(선회전)

_G = 32.174
_KT_FPS = 1.68781


def _wrap180(deg):
    return (deg + 180.0) % 360.0 - 180.0


def _es_ft(alt_ft, vc_kts):
    v = vc_kts * _KT_FPS
    return alt_ft + v * v / (2.0 * _G)


class Geom:
    """obs → BFM feature 묶음 (CombatGeometry 대응). o = compute_obs(us, opp)."""
    __slots__ = ("ata", "aa", "dist", "cr", "hca", "es_us", "es_op",
                 "energy_adv", "energy_def", "in_39", "adv")

    def __init__(self, o):
        self.ata = o.ata_deg
        self.aa = o.aa_deg
        self.dist = o.distance_ft
        self.cr = o.closure_kts                              # +접근
        self.hca = abs(_wrap180(o.ego_psi_deg - o.enm_psi_deg))
        self.es_us = _es_ft(o.ego_alt_ft, o.ego_vc_kts)
        self.es_op = _es_ft(o.enm_alt_ft, o.enm_vc_kts)
        # ★ deadband: 우위/열세 사이 중립 구간 (±200ft). 동등을 '열세'로 오판 금지.
        self.energy_adv = self.es_us > self.es_op + 200.0   # 명확한 우위
        self.energy_def = self.es_us < self.es_op - 200.0   # 명확한 열세 (≠ not adv)
        self.in_39 = self.aa < 90.0                         # 적 후방반구
        self.adv = o.advantage


def is_offensive(g: Geom) -> bool:
    """OBFM: ata<45 ∧ aa<100 ∧ 유효거리 ∧ (에너지우위 ∨ 3-9line). WEZ근접 강제."""
    wez_approaching = (g.ata < 20.0 and g.dist < 3280.0)
    positional = (g.ata < 45.0 and g.aa < 100.0)
    valid_dist = (1800.0 < g.dist < 18000.0)
    bonus = (g.energy_adv or g.in_39)
    return wez_approaching or (positional and valid_dist and bonus)


def is_defensive(g: Geom) -> bool:
    """DBFM: (aa>90 ∧ ata>60) ∨ (근거리 ∧ aa>135) ∨ (에너지열세 ∧ 접근 ∧ ata>45)."""
    positional_threat = (g.aa > 90.0 and g.ata > 60.0)
    proximity_threat = (g.dist < 3000.0 and g.aa > 135.0)
    # ★ 명확한 에너지 열세(energy_def)일 때만 — 동등(중립)을 방어로 오판 금지.
    energy_threat = (g.energy_def and g.cr > 30.0 and g.ata > 45.0)
    return positional_threat or proximity_threat or energy_threat


def is_neutral(g: Geom) -> bool:
    """HABFM: HCA>90(head-on) ∨ 원거리(>18000ft)."""
    return (g.hca > 90.0) or (g.dist > 18000.0)


def classify(o) -> str:
    """obs(우리 관점) → 물리 기반 상호배타 상황.

    우선순위: DEFENSIVE(최위험) > CHASE(정렬·속도) > CIRCLE(교차·선회율).
    ★ 측정 근거: chase 는 속도(max), circle 은 선회율(corner speed) 지배 — 속도선호 반대
      → 반드시 분리. HCA(속도벡터 교차각)로 판별.
    """
    g = Geom(o)
    # ★ DEFENSIVE = 즉각 위협만 (적 근접 + 우리 전방노출). 광범위 방어 금지 —
    #   적이 뒤에 있어도 가깝지 않으면 CIRCLE 로 out-rate(반격)가 옳다.
    if g.dist < 4000.0 and g.aa > 110.0:
        return DEFENSIVE      # 적 근접·우리 조준권 = 회피 필수
    # 비방어 → 속도벡터 정렬도(HCA)로 chase vs circle 분리
    if g.hca < HCA_ALIGNED_MAX and g.aa < 90.0:
        return CHASE          # 정렬 + 적 후방반구 = 직선추격(속도 지배)
    return CIRCLE             # 교차(headon·merge·선회전 포함) = 선회율/반경 지배 → out-rate


if __name__ == "__main__":
    import sys, os
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "control"))
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "engine"))
    from scenarios import SITUATIONS
    from obs import compute_obs
    print("feature 분류 검증 (단일 advantage vs feature):")
    print(f"{'situation':<14}{'ata':>5}{'aa':>5}{'dist':>7}{'hca':>5}{'adv':>6}{'eAdv':>5}  → {'classify':<10}")
    for name, sp in SITUATIONS.items():
        p1, p2 = sp(); o = compute_obs(p1, p2); g = Geom(o)
        print(f"{name:<14}{g.ata:>5.0f}{g.aa:>5.0f}{g.dist:>7.0f}{g.hca:>5.0f}"
              f"{g.adv:>+6.2f}{str(g.energy_adv):>5}  → {classify(o):<10}")
