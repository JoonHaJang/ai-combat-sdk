"""Observation Space — 1v1 BT-dogfight gym.

설계 근거 (논문 매핑, 2026-06-02 검토):
  - Pope et al. 2021 (DARPA AlphaDogfight, JSBSim 6-DOF 1v1):
      적의 Euler angles(φ,θ,ψ) + angular rates(p,q,r) 직접 관측 → 본 설계 채택.
  - Imitative RL 2024 §4.2: 적 heading/pitch/roll 직접 (14-dim).
  - DBRL 2024: oppo_plane_attitude(heading,pitch,roll) 직접.
  - H-MARL 2025 §4.2: BFM 기하(ATA/AA/offset) 파생값 제공 → Layer B 채택.
  - "perfect information setting" (H-MARL §3.1) — 전투기간 데이터 공유 가정.

구조 (2-layer):
  Layer A. 물리 원천값 (raw, 100% 정확) — ownship + opponent 직접 관측.
  Layer B. BFM 기하 (pre-computed) — BT node 편의용 파생값.

단위 규약 (TACTIC_SPEC.md §0, precision-policy 메모리 준수):
  각도 → 도(°)   |  고도 → ft MSL  |  속도 → kts  |  거리 → ft
  각속도 → °/s   |  부호: 우+/좌−, 상승+/강하−, 접근+/이격−
  ★ 연속값 유지 — 5×9×5 bin 같은 이산화 금지 (분해능 손실 방지).

핵심 개선:
  기존 omega_opp_signed 42-tick 재구성(90%) → enm_r_dps 직접 관측(100%) 으로 대체.
  기존 turn_rate(절대값) → ego_p/r 부호값 직접.
"""
from __future__ import annotations
import math
from dataclasses import dataclass, asdict

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "control"))
from constants import FT_S_TO_KNOT, KNOT_TO_FT_S, RAD_TO_DEG, DEG_TO_RAD, M_TO_FT

# ── JSBSim property 이름 (plant.py 와 동일 계열) ──────────────────────────
P_LAT   = "position/lat-gc-deg"
P_LON   = "position/long-gc-deg"
P_ALT   = "position/h-sl-ft"          # ft MSL
P_VN    = "velocities/v-north-fps"    # fps
P_VE    = "velocities/v-east-fps"
P_VD    = "velocities/v-down-fps"
P_VC    = "velocities/vc-kts"         # kts (CAS)
P_PHI   = "attitude/phi-deg"          # ° roll
P_THETA = "attitude/theta-deg"        # ° pitch
P_PSI   = "attitude/psi-deg"          # ° heading 0~360
P_P     = "velocities/p-rad_sec"      # rad/s roll rate
P_Q     = "velocities/q-rad_sec"      # rad/s pitch rate
P_R     = "velocities/r-rad_sec"      # rad/s yaw rate
P_ALPHA = "aero/alpha-deg"
P_BETA  = "aero/beta-deg"
P_NX    = "accelerations/n-pilot-x-norm"   # G
P_NZ    = "accelerations/n-pilot-z-norm"   # G
P_THR   = "fcs/throttle-cmd-norm[0]"

# 지구 반경 (flat-earth 근사용) — 위경도 1도 → ft 변환
FT_PER_DEG_LAT = 364000.0   # 위도 1° ≈ 364,000 ft (≈ 60 NM)


def _wrap180(deg: float) -> float:
    """각도 → [−180, +180]. 상대 방위 부호 처리."""
    return (deg + 180.0) % 360.0 - 180.0


@dataclass
class Observation:
    """1v1 dogfight 관측. 모든 값 연속(float). 단위는 필드명 접미사 명시.

    Layer A — ownship (직접, 100%)
    Layer A — opponent (직접 관측, perfect-info 가정)
    Layer B — BFM 기하 (파생)
    """
    # ── Layer A. Ownship (raw, 100% 정확) ─────────────────────────────
    ego_alt_ft:      float   # ft MSL, 절대
    ego_vc_kts:      float   # kts, 절대
    ego_phi_deg:     float   # ° roll,    부호 (우+/좌−) ★ 우리 선회방향
    ego_theta_deg:   float   # ° pitch,   부호 (상승+)
    ego_psi_deg:     float   # ° heading, 0~360 절대
    ego_p_dps:       float   # °/s roll rate,  부호
    ego_q_dps:       float   # °/s pitch rate, 부호
    ego_r_dps:       float   # °/s yaw rate,   부호 ★ 우리 선회율(부호)
    ego_alpha_deg:   float   # ° 받음각
    ego_beta_deg:    float   # ° 사이드슬립
    ego_nx_g:        float   # G  종방향 가속도
    ego_nz_g:        float   # G  수직 가속도 (선회 G)
    ego_throttle:    float   # [0,1]
    ego_health:      float   # 0~100

    # ── Layer A. Opponent (직접 관측, perfect-info) ──────────────────
    enm_alt_ft:      float   # ft MSL
    enm_vc_kts:      float   # kts
    enm_phi_deg:     float   # ° roll  ★ 적 선회방향 (100%, omega_opp_signed 대체)
    enm_theta_deg:   float   # ° pitch
    enm_psi_deg:     float   # ° heading 0~360 ★ 적 진행방향 (100%)
    enm_p_dps:       float   # °/s roll rate
    enm_r_dps:       float   # °/s yaw rate ★ 적 선회율 (100%, omega_opp_degs 대체)
    enm_health:      float   # 0~100

    # ── Layer B. BFM 기하 (파생) ─────────────────────────────────────
    distance_ft:     float   # ft, 절대 거리
    rel_b_deg:       float   # ° 적 상대방위, 부호 (우+/좌−) [−180,180]
    ata_deg:         float   # ° Antenna Train Angle, 0~180 절대 (WEZ 조건)
    aa_deg:          float   # ° Aspect Angle, 0~180 절대
    closure_kts:     float   # kts, 부호 (+접근/−이격)
    advantage:       float   # [−1,+1] BFM 위치우위 = 1−(ata+aa)/180
                             #   +1=적6시 nose-on(완벽공격), 0=head-on(중립),
                             #   −1=우리6시 피격(완벽방어). aa−ata 대체(2026-06-02).
    alt_gap_ft:      float   # ft, 부호 (+우리가 위)

    def as_dict(self) -> dict:
        return asdict(self)


def _ned(plant, lat0: float, lon0: float, alt0_ft: float):
    """플랜트의 (lat,lon,alt) → 기준점 대비 local NED (ft)."""
    lat = plant[P_LAT]; lon = plant[P_LON]; alt = plant[P_ALT]
    cos_lat = math.cos(math.radians(lat0))
    north_ft = (lat - lat0) * FT_PER_DEG_LAT
    east_ft  = (lon - lon0) * FT_PER_DEG_LAT * cos_lat
    down_ft  = -(alt - alt0_ft)
    return north_ft, east_ft, down_ft


def compute_obs(ego, enm,
                center_lat: float | None = None,
                center_lon: float | None = None,
                center_alt_ft: float = 0.0) -> Observation:
    """ego·enm plant(F16Plant) → Observation.

    ego, enm: F16Plant 인스턴스 (property 접근 가능).
    center_*: NED 기준점. None(기본) → ego 현재 위치 사용.
      ★ cos(lat) 보정이 center_lat 기준이라 ego lat 을 써야 경도거리 정확
        (center_lat=0 고정 시 고위도서 경도거리 1/cos 만큼 과대 — 버그).
    """
    if center_lat is None:
        center_lat = ego[P_LAT]
        center_lon = ego[P_LON]
    # ── Ownship raw ───────────────────────────────────────────────────
    ego_alt   = ego[P_ALT]
    ego_vc    = ego[P_VC]
    ego_phi   = _wrap180(ego[P_PHI])
    ego_theta = ego[P_THETA]
    ego_psi   = ego[P_PSI] % 360.0
    ego_p     = ego[P_P] * RAD_TO_DEG
    ego_q     = ego[P_Q] * RAD_TO_DEG
    ego_r     = ego[P_R] * RAD_TO_DEG

    # ── Opponent raw ──────────────────────────────────────────────────
    enm_alt   = enm[P_ALT]
    enm_vc    = enm[P_VC]
    enm_phi   = _wrap180(enm[P_PHI])
    enm_theta = enm[P_THETA]
    enm_psi   = enm[P_PSI] % 360.0
    enm_p     = enm[P_P] * RAD_TO_DEG
    enm_r     = enm[P_R] * RAD_TO_DEG

    # ── BFM 기하 (NED 기반) ───────────────────────────────────────────
    e_n, e_e, e_d = _ned(ego, center_lat, center_lon, center_alt_ft)
    o_n, o_e, o_d = _ned(enm, center_lat, center_lon, center_alt_ft)
    d_n, d_e, d_d = o_n - e_n, o_e - e_e, o_d - e_d      # ego→enm 벡터
    distance = math.sqrt(d_n**2 + d_e**2 + d_d**2)       # ft

    # ego velocity (NED, fps)
    e_vn, e_ve, e_vd = ego[P_VN], ego[P_VE], ego[P_VD]
    o_vn, o_ve, o_vd = enm[P_VN], enm[P_VE], enm[P_VD]
    ego_speed = math.sqrt(e_vn**2 + e_ve**2 + e_vd**2) + 1e-9
    enm_speed = math.sqrt(o_vn**2 + o_ve**2 + o_vd**2) + 1e-9

    # ATA (=AO): ego velocity 와 ego→enm 벡터 사이 각 (0~180, 절대)
    #   참조: liuqh16/LAG get_AO_TA_R (= upstream get_AO_TA_R 동일).
    #   head-on: ego→enm 이 ego velocity 와 정렬 → ata=0. WEZ 조건 ata<12.
    proj_ego = (d_n*e_vn + d_e*e_ve + d_d*e_vd) / (distance*ego_speed + 1e-9)
    ata = math.degrees(math.acos(max(-1.0, min(1.0, proj_ego))))

    # AA (=TA): enm velocity 와 ego→enm 벡터 사이 각 (0~180, 절대).
    #   ★ d(=ego→enm) 그대로 사용 (LAG TA 공식과 동일, 부호 negate 금지).
    #   head-on: enm velocity(적이 우리쪽) 가 d 와 반대 → aa=180.
    #   적 6시(우리가 적 꼬리): enm velocity 가 d 와 정렬 → aa=0.
    proj_enm = (d_n*o_vn + d_e*o_ve + d_d*o_vd) / (distance*enm_speed + 1e-9)
    aa = math.degrees(math.acos(max(-1.0, min(1.0, proj_enm))))

    # rel_b: 적 상대방위 (수평면, ego heading 기준), 부호 (우+/좌−)
    #   ego→enm 수평 방위각 − ego heading
    bearing_to_enm = math.degrees(math.atan2(d_e, d_n)) % 360.0  # 진북 기준
    rel_b = _wrap180(bearing_to_enm - ego_psi)

    # closure: 거리 변화율 = 상대속도의 LOS 성분, 부호 (+접근)
    #   접근 = 거리 감소 → +. (relative velocity · LOS 단위벡터)의 음수
    rel_vn, rel_ve, rel_vd = o_vn - e_vn, o_ve - e_ve, o_vd - e_vd
    closure_fps = -(rel_vn*d_n + rel_ve*d_e + rel_vd*d_d) / (distance + 1e-9)
    closure_kts = closure_fps * FT_S_TO_KNOT

    # advantage = 1 − (ata+aa)/180  [−1,+1]  (단위: 무차원)
    #   ata,aa 둘 다 [0,180]° → (ata+aa)∈[0,360] → advantage∈[−1,+1].
    #   +1: ata=0,aa=0 (적6시 nose-on)  /  0: head-on  /  −1: 우리6시 피격.
    advantage = 1.0 - (ata + aa) / 180.0
    # alt_gap = ego − enm (양수 = 우리가 위), 단위 ft
    alt_gap = ego_alt - enm_alt

    return Observation(
        # ownship
        ego_alt_ft=ego_alt, ego_vc_kts=ego_vc,
        ego_phi_deg=ego_phi, ego_theta_deg=ego_theta, ego_psi_deg=ego_psi,
        ego_p_dps=ego_p, ego_q_dps=ego_q, ego_r_dps=ego_r,
        ego_alpha_deg=ego[P_ALPHA], ego_beta_deg=ego[P_BETA],
        ego_nx_g=ego[P_NX], ego_nz_g=ego[P_NZ],
        ego_throttle=ego[P_THR], ego_health=100.0,
        # opponent
        enm_alt_ft=enm_alt, enm_vc_kts=enm_vc,
        enm_phi_deg=enm_phi, enm_theta_deg=enm_theta, enm_psi_deg=enm_psi,
        enm_p_dps=enm_p, enm_r_dps=enm_r, enm_health=100.0,
        # BFM geometry
        distance_ft=distance, rel_b_deg=rel_b,
        ata_deg=ata, aa_deg=aa, closure_kts=closure_kts,
        advantage=advantage, alt_gap_ft=alt_gap,
    )


if __name__ == "__main__":
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "control"))
    from plant import F16Plant

    print("▶ obs first-light — head-on 3000ft 시나리오")

    # ego: 북향, enm: 남향(마주봄), 3000ft 앞
    ego = F16Plant(); ego.set_ic(alt_ft=15000.0, vc_kts=350.0, psi_deg=0.0)
    ego.trim(); ego.step(5)

    enm = F16Plant(); enm.set_ic(alt_ft=15000.0, vc_kts=350.0, psi_deg=180.0)
    # enm을 ego 북쪽 3000ft에 배치
    enm["ic/lat-gc-deg"] = 3000.0 / FT_PER_DEG_LAT
    enm["ic/psi-true-deg"] = 180.0
    enm.fdm.run_ic(); enm.trim(); enm.step(5)

    obs = compute_obs(ego, enm)
    d = obs.as_dict()

    print("\n=== Layer A: Ownship ===")
    for k in ["ego_alt_ft","ego_vc_kts","ego_phi_deg","ego_psi_deg","ego_r_dps","ego_alpha_deg"]:
        print(f"  {k:16s} = {d[k]:+10.3f}")
    print("=== Layer A: Opponent (직접 관측) ===")
    for k in ["enm_alt_ft","enm_vc_kts","enm_phi_deg","enm_psi_deg","enm_r_dps"]:
        print(f"  {k:16s} = {d[k]:+10.3f}")
    print("=== Layer B: BFM 기하 ===")
    for k in ["distance_ft","rel_b_deg","ata_deg","aa_deg","closure_kts","advantage","alt_gap_ft"]:
        print(f"  {k:16s} = {d[k]:+10.3f}")

    print(f"\n총 obs 필드: {len(d)}개")
