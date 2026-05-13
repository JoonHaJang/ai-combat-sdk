#!/usr/bin/env python3
"""
sim_dogfight_verify.py — 1:1 도그파이트 3D 시뮬레이션 검증

목적:
  적의 기동 행동(5종)을 설계하고, 우리 BT + HCCA v12를 주입하여
  각 전황 조합에서 실제로 어떻게 동작하는지 시뮬레이션한다.

구성:
  [물리] 3D 점질량 키네마틱 모델 (위치 x/y/z, 헤딩, 비행경로각 γ, 속도)
  [기하] ATA, AA, dist, closure, HCA, tc_type — 3D 벡터 내적으로 계산
  [적]   5개 적 정책 (Passive, Orbiting, Defensive, Offensive, Evading)
  [아군] BT 브랜치 선택 + HCCA 모드 선택 → 헤딩/피치/속도 명령
  [판정] 승리: ATA<12°, 500<dist<3000, closure>0 / 패배: 역전 조건

초기 배치 35종 × 적 정책 5종 = 175 시나리오
"""

import sys, os, math, types

# ── py_trees mock ──────────────────────────────────────────────────
class _FakeBehav:
    def __init__(self, name): self.name = name
    def attach_blackboard_client(self):
        class _C:
            def register_key(self, **_): pass
        return _C()

_pt = types.ModuleType("py_trees")
_pt.behaviour = types.ModuleType("py_trees.behaviour")
_pt.behaviour.Behaviour = _FakeBehav
_pt.common = types.ModuleType("py_trees.common")
_pt.common.Access = types.SimpleNamespace(READ="R", WRITE="W")
_pt.Status = types.SimpleNamespace(SUCCESS="S", FAILURE="F", RUNNING="R")
sys.modules["py_trees"] = _pt
sys.modules["py_trees.behaviour"] = _pt.behaviour
sys.modules["py_trees.common"] = _pt.common

_HERE = os.path.dirname(__file__)
sys.path.insert(0, os.path.join(_HERE, "nodes"))
from custom_actions import ContinuousMasterController as CMC, _sigmoid as _sig

# ══════════════════════════════════════════════════════════════════════
# 상수 및 설정
# ══════════════════════════════════════════════════════════════════════
KTS_TO_FPS = 1.6878
DT = 0.2            # 틱당 시간 (s)

# ── JSBSim 실제 매치 초기 조건 (모든 실전 매치의 표준 시작점) ──────────────────
# 출처: logs/metadata/v11_analysis/*.json 실측 — 모든 매치 ATA=90°에서 시작
CANONICAL_SPD  = 386.8   # kts  — JSBSim 초기 속도
CANONICAL_ALT  = 15000.0 # ft   — JSBSim 초기 고도
CANONICAL_DIST = 3297.6  # ft   — JSBSim 초기 거리 (ATA=90° 기준)
# ── F-16 전투 선회 성능 테이블 (8000ft 기준) ─────────────────────────────────
# 출처: JSBSim 실측 + F-16 Flight Manual / NASA TP-1538 보정
# JSBSim 저G 실측(~3G):  300kts→10.4°/s  ← 기준점
# 실전 순간 선회율(~9G):  300kts≈18°/s, 350kts≈21°/s (코너속도 피크), 420kts≈16°/s
# 3D 시뮬레이션: 수평/수직 선회율 모두 이 테이블에서 파생 (수직 ≈ 수평 × 0.7)
_JSB_SPD = [0,   160,  200,  250,  300,  350,  400,  420,  500]
_JSB_TR  = [6.0, 9.0, 12.0, 15.0, 18.0, 21.0, 18.5, 16.0, 14.0]  # °/s
_JSB_R   = [1600,1700,1600,1700,1800,1650,2100,2500,2800]           # ft (V/ω 역산)

def max_turn_rate(speed_kts):
    """JSBSim F-16 실측 선회율 (°/s) — 선형 보간."""
    spd = max(_JSB_SPD[0], min(_JSB_SPD[-1], speed_kts))
    for i in range(len(_JSB_SPD)-1):
        if _JSB_SPD[i] <= spd <= _JSB_SPD[i+1]:
            t = (spd - _JSB_SPD[i]) / (_JSB_SPD[i+1] - _JSB_SPD[i])
            return _JSB_TR[i] + t * (_JSB_TR[i+1] - _JSB_TR[i])
    return _JSB_TR[-1]

def turn_radius_ft(speed_kts, tr_degs=None):
    """JSBSim F-16 실측 선회 반경 (ft) — 선형 보간."""
    spd = max(_JSB_SPD[0], min(_JSB_SPD[-1], speed_kts))
    for i in range(len(_JSB_SPD)-1):
        if _JSB_SPD[i] <= spd <= _JSB_SPD[i+1]:
            t = (spd - _JSB_SPD[i]) / (_JSB_SPD[i+1] - _JSB_SPD[i])
            return _JSB_R[i] + t * (_JSB_R[i+1] - _JSB_R[i])
    return _JSB_R[-1]

MAX_SPD  = 420.0    # 최대 속도 kts (F-16 실용 상한)
MIN_SPD  = 160.0    # 최소 속도 kts (실속 전)
CORNER_SPD = 350.0  # 코너 속도 kts (최대 선회율 발생)
MAX_TR   = 21.0     # 최대 명령 선회율 (°/s) — 코너속도 피크

# 승리 집합 V
V_ATA_MAX  = 12.0   # °
V_DIST_MIN = 500.0  # ft
V_DIST_MAX = 3000.0 # ft
V_CL_MIN   = 0.0    # kts

# ══════════════════════════════════════════════════════════════════════
# 물리 모델 — 3D 점질량 항공기 (위치 x/y/z, 헤딩, 비행경로각 γ, 속도)
# ══════════════════════════════════════════════════════════════════════
class Aircraft:
    def __init__(self, x, y, z, hdg, gamma, speed):
        self.x     = float(x)      # ft  East
        self.y     = float(y)      # ft  North
        self.z     = float(z)      # ft  Altitude (고도)
        self.hdg   = float(hdg)    # deg 수평 방위 (0=북, 90=동)
        self.gamma = float(gamma)  # deg 비행경로각 (+= 상승, -= 강하)
        self.speed = float(speed)  # kts

    def vel(self):
        """3D 속도 벡터 (ft/s): (East, North, Up)."""
        v    = self.speed * KTS_TO_FPS
        cg   = math.cos(math.radians(self.gamma))
        sg   = math.sin(math.radians(self.gamma))
        return (v * cg * math.sin(math.radians(self.hdg)),
                v * cg * math.cos(math.radians(self.hdg)),
                v * sg)

    def step(self, d_hdg_rate, d_gamma_rate, d_speed):
        """
        d_hdg_rate  : 수평 선회율 °/s (+ = 우선회)
        d_gamma_rate: 피치율 °/s (+ = 상승)
        d_speed     : 가속도 kts/s
        """
        tr_max  = max_turn_rate(self.speed)
        ptr_max = tr_max * 0.7          # 수직 피치율은 수평의 70%
        d_hdg_rate   = max(-tr_max,  min(tr_max,  d_hdg_rate))
        d_gamma_rate = max(-ptr_max, min(ptr_max, d_gamma_rate))
        self.hdg   = (self.hdg + d_hdg_rate   * DT) % 360.0
        self.gamma = max(-80.0, min(80.0, self.gamma + d_gamma_rate * DT))
        self.speed = max(MIN_SPD, min(MAX_SPD, self.speed + d_speed * DT))
        vx, vy, vz = self.vel()
        self.x += vx * DT
        self.y += vy * DT
        self.z  = max(500.0, self.z + vz * DT)   # 지면 충돌 방지 500ft 하한

    @property
    def tr(self):
        """현재 속도에서의 최대 수평 선회율 (°/s)."""
        return max_turn_rate(self.speed)

    @property
    def radius(self):
        """현재 속도/선회율 기반 최소 선회 반경 (ft)."""
        return turn_radius_ft(self.speed, self.tr)


def ang_diff(a, b):
    """부호 있는 각도 차 a-b ∈ (-180, 180]."""
    d = (a - b) % 360.0
    return d if d <= 180.0 else d - 360.0


def compute_geo(own, enemy):
    """3D 기하 관측값 계산: ATA, AA, dist, closure, HCA, tc_type, alt_gap."""
    dx = enemy.x - own.x
    dy = enemy.y - own.y
    dz = enemy.z - own.z
    dist = math.sqrt(dx*dx + dy*dy + dz*dz) + 1e-3

    # LOS 단위 벡터 (3D)
    lx, ly, lz = dx/dist, dy/dist, dz/dist

    # 아군 속도 단위 벡터 (3D)
    ovx, ovy, ovz = own.vel()
    ov_mag = math.sqrt(ovx*ovx + ovy*ovy + ovz*ovz) + 1e-10
    ouvx, ouvy, ouvz = ovx/ov_mag, ovy/ov_mag, ovz/ov_mag

    # 적 속도 단위 벡터 (3D)
    evx, evy, evz = enemy.vel()
    ev_mag = math.sqrt(evx*evx + evy*evy + evz*evz) + 1e-10
    euvx, euvy, euvz = evx/ev_mag, evy/ev_mag, evz/ev_mag

    # ATA: 내 속도벡터와 LOS 사이 각도 (내 기수 기준 적 방위)
    dot_o = max(-1.0, min(1.0, ouvx*lx + ouvy*ly + ouvz*lz))
    ata = math.degrees(math.acos(dot_o))

    # AA: 적 속도벡터와 역-LOS 사이 각도 (적 기수 기준 나의 방위)
    dot_e = max(-1.0, min(1.0, -(euvx*lx + euvy*ly + euvz*lz)))
    aa = math.degrees(math.acos(dot_e))

    # Closure: 상대속도의 LOS 성분 (kts, 양수 = 거리 감소)
    closure = ((ovx-evx)*lx + (ovy-evy)*ly + (ovz-evz)*lz) / KTS_TO_FPS

    # HCA: 두 속도벡터 사이 각도 (0~180°)
    dot_vv = max(-1.0, min(1.0, ouvx*euvx + ouvy*euvy + ouvz*euvz))
    hca = math.degrees(math.acos(dot_vv))

    # 수평 방위각 (헤딩 명령 계산용 — 수평 성분만)
    bear = math.degrees(math.atan2(dx, dy)) % 360.0

    # tc_type: ATA+AA > 180 → 2-circle
    tc_type = "2-circle" if (ata + aa) > 180.0 else "1-circle"

    # alt_gap: 아군 고도 - 적 고도 (양수 = 우리가 위)
    alt_gap = own.z - enemy.z

    # 고도 기반 상승각 (수직 PN용)
    horiz_dist = math.sqrt(dx*dx + dy*dy) + 1e-3
    elev_to_enemy = math.degrees(math.atan2(dz, horiz_dist))

    return {
        "ata": ata, "aa": aa, "dist": dist, "closure": closure,
        "hca": hca, "tc_type": tc_type, "bear": bear,
        "alt_gap": alt_gap, "own_alt": own.z, "enemy_alt": enemy.z,
        "elev": elev_to_enemy,
    }


def is_victory(geo):
    """승리 집합 V: ATA<12°, 500<dist<3000(일반) or <4000(꼬리-AA>45°), closure>0.
    AA>45° 꼬리 추격: 적 사격 불가 + 정렬 우수 → 사거리 연장(4000ft) 합당.
    """
    dist_max = 4000.0 if geo["aa"] > 45.0 else V_DIST_MAX
    return (geo["ata"] < V_ATA_MAX
            and V_DIST_MIN < geo["dist"] < dist_max
            and geo["closure"] > V_CL_MIN)


def is_enemy_win(geo):
    """적 승리: AA<12°, 500<dist<3000, closure>0 (적이 우리 뒤를 잡음)."""
    return (geo["aa"] < V_ATA_MAX
            and V_DIST_MIN < geo["dist"] < V_DIST_MAX
            and geo["closure"] > V_CL_MIN)


# ══════════════════════════════════════════════════════════════════════
# 적 정책 (Adversary Policies) — 4종
# ══════════════════════════════════════════════════════════════════════

def enemy_policy(policy, enemy, own, geo, tick):
    """
    Returns (d_hdg °/s, d_gamma °/s, d_speed kts/s).

    Passive   : 직선 수평 비행
    Orbiting  : 일정 선회율 유지 (교착 유발)
    Defensive : 위협 시 break turn + 수직 회피
    Offensive : 3D PN 추격 (수평 + 수직)
    Evading   : 90° break + push-over
    """
    dx = own.x - enemy.x
    dy = own.y - enemy.y
    dz = own.z - enemy.z
    bear_to_own = math.degrees(math.atan2(dx, dy)) % 360.0
    horiz_d = math.sqrt(dx*dx + dy*dy) + 1e-3
    elev_to_own = math.degrees(math.atan2(dz, horiz_d))

    if policy == "passive":
        # 수평 직선, gamma를 0으로 서서히 복귀
        d_gamma = max(-2.0, min(2.0, -enemy.gamma / (DT * 5)))
        return 0.0, d_gamma, 0.0

    elif policy == "orbiting":
        return -13.0, 0.0, 0.0

    elif policy == "defensive":
        if geo["aa"] < 60.0:
            err = ang_diff(bear_to_own + 90.0, enemy.hdg)
            d_hdg = max(-MAX_TR, min(MAX_TR, err / (DT * 4)))
            # 수직 회피: 적보다 위면 push-over, 아래면 pull-up
            d_gamma = -MAX_TR * 0.4 if geo["alt_gap"] < 0 else MAX_TR * 0.4
            return d_hdg, d_gamma, -5.0
        d_gamma = max(-2.0, min(2.0, -enemy.gamma / (DT * 5)))
        return 0.0, d_gamma, 0.0

    elif policy == "offensive":
        # 3D PN 추격: 수평 lead + 수직 고도 추종
        err = ang_diff(bear_to_own, enemy.hdg)
        ata_own = abs(ang_diff(bear_to_own, enemy.hdg))
        lead = 3.0 * ata_own * 0.08
        target = (bear_to_own + lead * (1 if err > 0 else -1)) % 360
        err2 = ang_diff(target, enemy.hdg)
        d_hdg = max(-MAX_TR, min(MAX_TR, err2 / (DT * 2)))
        # 수직: 우리 고도로 수렴
        d_gamma = max(-MAX_TR*0.5, min(MAX_TR*0.5, (elev_to_own - enemy.gamma) / (DT * 4.0)))
        return d_hdg, d_gamma, 2.0

    elif policy == "evading":
        if geo["aa"] < 45.0:
            err = ang_diff(bear_to_own + 90.0, enemy.hdg)
            d_hdg = max(-MAX_TR, min(MAX_TR, err / (DT * 2)))
            # push-over로 고도 이탈 → 3D 회피
            d_gamma = -MAX_TR * 0.5
            return d_hdg, d_gamma, -3.0
        d_gamma = max(-2.0, min(2.0, -enemy.gamma / (DT * 5)))
        return 0.0, d_gamma, 0.0

    return 0.0, 0.0, 0.0


# ══════════════════════════════════════════════════════════════════════
# BT 브랜치 선택 모델 (proof_of_win bt_branch 기반)
# ══════════════════════════════════════════════════════════════════════

def select_bt_branch(geo, avg_cl, own_spd=300.0, alt=8000.0, own_gamma=0.0):
    """YAML 우선순위 트리: 발동 브랜치 반환."""
    ata, aa, dist, cl, hca = geo["ata"], geo["aa"], geo["dist"], geo["closure"], geo["hca"]

    if alt < 1200.0:
        return "HardDeckAvoidance"
    # GunEngagement: ATA<12° + 사거리 내
    # HCA gate 확장: 후방(HCA<30°) OR 정면(HCA>150°) OR 빔/플랭크(AA>45°, 적이 못 쏨)
    # AA>45° 꼬리 추격 시 사거리 연장 4000ft: 적 사격 불가 + 기수정렬 완벽
    dist_gun_max = 4000.0 if aa > 45.0 else 3000.0
    if ata < 12.0 and 500 < dist < dist_gun_max and (hca < 30.0 or hca > 150.0 or aa > 45.0):
        return "GunEngagement"
    if ata < 45.0 and aa > 100.0 and dist < 4000.0:
        return "OffensivePursuit"
    # ── 안전 분기 외에는 모두 TheoremAdaptive(τ-blended 연속 제어)로 일임 ──
    # 28-피처 obs 직접 입력 → τ_corner/τ_yoyo/τ_ldt → 제어 합성
    return "TheoremAdaptive"

# 브랜치가 HCCA(PNLeadPursuit)를 사용하는지 여부
# OffensivePursuit 제거: branch_cmd의 N=4+sprint 코드가 실제로 실행되어야 함 (GAP-D1)
_HCCA_BRANCHES = {
    "CloseCombat", "CounterOrbiting",
    "TacticalLookup", "LeadPursuit", "StaleChaseBreak",
}


# ══════════════════════════════════════════════════════════════════════
# 헤딩 명령 생성 — BT 브랜치 or HCCA 모드 → (d_hdg_rate, d_speed)
# ══════════════════════════════════════════════════════════════════════

def pn_cmd(own, geo, N=3.0):
    """3D PN 유도: 수평 lead pursuit + 수직 고도 수렴 → (d_hdg, d_gamma, d_speed)."""
    bear = geo["bear"]
    ata  = geo["ata"]
    # 수평: lead angle
    side = 1.0 if ang_diff(bear, own.hdg) > 0 else -1.0
    lead = N * ata * 0.06
    desired = (bear + side * lead) % 360.0
    err = ang_diff(desired, own.hdg)
    d_hdg = max(-MAX_TR, min(MAX_TR, err / (DT * 2.5)))
    # 수직: 적 고도로 수렴 (elev_to_enemy → gamma 추종)
    elev = geo.get("elev", 0.0)
    d_gamma = max(-MAX_TR*0.5, min(MAX_TR*0.5, (elev - own.gamma) / (DT * 4.0)))
    return d_hdg, d_gamma, 0.0


def _orbit_intercept_cmd(own, enemy, geo, gun_range=2000.0):
    """
    3D 궤도 인터셉트: 적의 예측 궤도 뒤 gun_range 위치에 dive 합류.

    교리:
      Phase 1 (alt_gap < CLIMB_THRESH): 수직 상승으로 고도 우위 확보 + 코너속도 유지
      Phase 2 (alt_gap >= CLIMB_THRESH): 적 예측 위치(T초 후) gun_range 뒤를 향해 Dive

    근거: 2-circle scissors는 2D 평면에서 안정적 orbit를 형성 → 수직 이탈(3D)만이
          대칭을 깨고 close pass를 만들어 사격 기회 창출.
    """
    CLIMB_THRESH = 1500.0  # ft: Phase 1→2 전환 고도 차
    T_pred       = 5.0     # sec: 적 미래 위치 예측 시간

    alt_gap = geo.get("alt_gap", 0.0)
    bear    = geo["bear"]

    ata_now = geo.get("ata", 90.0)
    cl_now  = geo.get("closure", 0.0)

    # ── Z5 역전 모드: ATA>140° + 이탈(cl<0) ──
    # 이탈 중 상승은 의미 없음 — 직선 최고속으로 반전해 head-on 거리 최소화
    if ata_now > 140.0 and cl_now < 0:
        err = ang_diff(bear, own.hdg)
        d_hdg = max(-MAX_TR, min(MAX_TR, err / (DT * 1.0)))
        # 수평 유지 (상승/하강 없음 → 속도 손실 방지)
        d_gamma = max(-MAX_TR * 0.4, min(MAX_TR * 0.4, (0.0 - own.gamma) / (DT * 2.0)))
        return d_hdg, d_gamma, 20.0  # 최대 가속

    # ── Phase 판정: alt_gap OR gamma 기반 ──
    # 1500ft 고도 우위 → dive (전통 기준)
    # OR gamma > 25° (충분히 nose-up 상태) → dive 전환
    #   근거: offensive enemy가 alt 추종 시 alt_gap≈0 유지 → 순수 alt 기준 불작동
    #         gamma>25°이면 충분히 상승했으므로 이 시점에 push-over → 속도 환원 + 각도 변환
    phase = "dive" if (alt_gap >= CLIMB_THRESH or own.gamma >= 25.0) else "climb"

    if phase == "climb":
        # 수평: 적 방향 유지 (이탈 방지)
        err   = ang_diff(bear, own.hdg)
        d_hdg = max(-MAX_TR, min(MAX_TR, err / (DT * 2.5)))
        # 수직: 최대 pull-up
        d_gamma = MAX_TR * 0.65
        # 속도: 코너속도로
        accel = 10.0 if own.speed < CORNER_SPD else 0.0
        return d_hdg, d_gamma, accel

    else:  # dive
        # 적 미래 위치: 현재 속도벡터로 T_pred초 선형 예측
        evx, evy, evz = enemy.vel()
        ev_spd = math.sqrt(evx*evx + evy*evy + evz*evz) + 1e-10
        # 예측 위치
        fx = enemy.x + evx * T_pred
        fy = enemy.y + evy * T_pred
        fz = enemy.z + evz * T_pred
        # 인터셉트 포인트: 예측 위치에서 gun_range 뒤 (적 속도 반대방향)
        fx -= (evx / ev_spd) * gun_range
        fy -= (evy / ev_spd) * gun_range
        fz -= (evz / ev_spd) * gun_range
        # 인터셉트 포인트 방향
        ddx, ddy, ddz = fx - own.x, fy - own.y, fz - own.z
        tgt_bear  = math.degrees(math.atan2(ddx, ddy)) % 360.0
        horiz_d   = math.sqrt(ddx*ddx + ddy*ddy) + 1e-3
        tgt_elev  = math.degrees(math.atan2(ddz, horiz_d))
        err = ang_diff(tgt_bear, own.hdg)
        d_hdg = max(-MAX_TR, min(MAX_TR, err / (DT * 2.0)))
        # 수직: dive 각도 추종 (하강)
        d_gamma = max(-MAX_TR * 0.65, min(MAX_TR * 0.3,
                      (tgt_elev - own.gamma) / (DT * 2.0)))
        # 속도: dive 중 코너속도 유지 (가속하면 pull-out 반경 커짐)
        accel = 0.0
        return d_hdg, d_gamma, accel


# ══════════════════════════════════════════════════════════════════════
# τ 함수 (BFM 정리 5/6/7/8 → 28-피처 obs 직접 매핑)
#
# 모든 τ ∈ [0, 1]. 입력은 28-피처 obs dict (선택적으로 obs_prev). 추정기 없음.
# 적 정책 변화 → obs 변화 → τ 변화 → 제어 자동 적응.
# ══════════════════════════════════════════════════════════════════════

def _gauss(x, mu, sigma):
    return math.exp(-((x - mu) ** 2) / (2.0 * sigma * sigma))


def tau_corner(obs, obs_prev):
    """
    정리 5 (Boyd Ps) + 정리 6 (Shaw 1-circle + 2-circle) → τ_corner ∈ [0, 1]

    정리 6 (Shaw) 정확 인코딩 — 양쪽 fight regime 모두에서 코너 가치 있음:
      - 2-circle (HCA>120°): ω_max 우위 → 코너에서 ω=21°/s 최대
      - 1-circle (HCA<90°):  R_min 우위 → 코너에서 R=V/ω=1611ft 최소
      - 중간 (90<HCA<120):   head-on 변이 영역, regime 모호 → τ 약함

    중요한 spec 추가: 정리 6 entry condition 은 **양쪽 능동 turning fight** 일 때만.
    적이 직선 (passive) 인데 우리만 turn 시 정리 6 적용 영역 아님 (정리 1 Bernoulli).
    적 ω 추정: HCA 변화율 - 우리 turn rate 잔여 (obs 직접, 추정기 없음).

    추정 없음 — turn_rate_degs와 hca의 시간차분으로 직접 측정.
    """
    hca = obs["hca_deg"] * 180.0
    vc  = obs["ego_vc_kts"]
    our_omega = abs(obs["turn_rate_degs"])
    hca_prev = obs_prev["hca_deg"] * 180.0 if obs_prev else hca
    hca_rate = abs(hca - hca_prev) / DT
    # 적 ω 추정 (보수적): HCA 변화율 중 우리 turn 으로 설명 안 되는 잔여
    # 이는 estimator 가 아니라 obs 직접 차분 — Kalman 등 모델 가정 X
    enemy_omega_est = max(0.0, hca_rate - our_omega)

    # 정리 6: 양쪽 regime 모두에서 코너 가치
    s_2circle = _sig((hca - 120.0) / 20.0)
    s_1circle = _sig((90.0 - hca) / 20.0)
    s_regime  = max(s_2circle, s_1circle)

    s_v       = _sig((vc - 355.0) / 8.0)             # 코너속도 sharp transition

    # 능동 fight: 우리 AND 적 둘 다 turning (정리 6 entry condition 의 핵심)
    s_us      = _sig((our_omega       - 5.0) / 5.0)
    s_them    = _sig((enemy_omega_est - 3.0) / 3.0)
    s_active  = s_us * s_them

    return s_regime * s_v * s_active


def tau_yoyo(obs, obs_prev):
    """
    정리 8 (Pontryagin 수직 BFM 최적 제어) → τ_yoyo ∈ [0, 1]

    정리 8 정확 spec:
      (a) chase yo-yo: closure>0 + ATA 중간 — 능동 추격 timing exploit
      (b) orbit break: |closure| 작음 + ATA 중간 — engagement 락 → 수직 이탈

    ⚠️ 이전 구현은 lock 조건에 HCA>120 추가 — 정리 8 에 없는 군더더기.
    정리 8 (Pontryagin 수직 평면 최적 제어) 은 closure / ATA / Ps 만 의존.
    HCA 조건 제거 — 1-circle dual-PN orbit (HCA<120) 에서도 yo-yo 가치 있음.
    """
    cl  = obs["closure_rate_kts"]
    ata = obs["ata_deg"] * 180.0

    # 두 모드: chase OR engagement-lock (둘 다 ATA 중간 영역에서 의미)
    s_chase = _sig((cl - 30.0) / 50.0)             # closure>0 능동 추격
    s_lock  = _sig((50.0 - abs(cl)) / 30.0)        # |cl| 작음 = 락 상태
    s_engagement = max(s_chase, s_lock)

    s_ata = _gauss(ata, mu=70.0, sigma=30.0)       # 40~100° 영역
    return s_engagement * s_ata


def tau_ldt(obs, obs_prev):
    """
    정리 7 (Shaw LDT) → τ_ldt ∈ [0, 1]
    Shaw Phase 1→2 전환 조건의 정확한 형식:
        dist · sin(ATA) ≥ R_us · √2

    이전 구현은 dist threshold(3000ft)만 사용 — 정리 7의 spec 미충족.
    수정: displacement 계산을 정확히 sin(ATA)와 R(V)에 의존하게.
    """
    ata = obs["ata_deg"] * 180.0
    dist = obs["distance_ft"]
    R = obs.get("turn_radius_ft", 2100.0)  # 28-피처에 이미 노출됨, fallback 2100
    rb  = obs["relative_bearing_deg"] * 180.0
    rb_prev = obs_prev["relative_bearing_deg"] * 180.0 if obs_prev else rb
    los_rate = abs(ang_diff(rb, rb_prev)) / DT   # °/s, LOS rate

    s_ata = _gauss(ata, mu=65.0, sigma=15.0)
    # Shaw 정리 7 정확 form: displacement vs R·√2
    displacement = dist * math.sin(math.radians(ata))
    threshold = R * math.sqrt(2)
    s_disp = _sig((displacement - threshold) / 500.0)
    s_los  = _sig((los_rate - 8.0) / 5.0)        # 강한 LOS rate 시에만
    return s_ata * s_disp * s_los


# ══════════════════════════════════════════════════════════════════════
# adaptive_command — τ-blended 연속 제어 합성기
#
# 28-피처 obs 직접 입력 → τ 3종 → baseline PN과 정리별 명령 연속 blending.
# 이산 분기 없음. 적 정책 변화에 즉시 적응.
# ══════════════════════════════════════════════════════════════════════

def adaptive_command(obs, obs_prev, own, geo, enemy=None):
    """obs 직접 → (d_hdg, d_gamma, d_speed, τ_dict)."""
    τc = tau_corner(obs, obs_prev)
    τy = tau_yoyo(obs, obs_prev)
    τl = tau_ldt(obs, obs_prev)

    # ── baseline: 3D PN (정리 2 등가) ────────────────────────────
    d_hdg_pn, d_gamma_pn, _ = pn_cmd(own, geo, N=3.0)
    # baseline 속도: ATA<90°(우리 전방에 적) → 추격 가속, ATA>120°(적 후방) → 역전 위해 감속
    # 정리 1 (Bernoulli): 동속 직선 추격은 점근적 → 우리가 더 빨라야 capture 가능
    ata = obs["ata_deg"] * 180.0
    if ata < 90.0 and own.speed < MAX_SPD:
        d_speed_pn = 15.0
    elif ata > 120.0 and own.speed > CORNER_SPD:
        d_speed_pn = -10.0
    else:
        d_speed_pn = 0.0

    # ── 정리 5+6 명령: 코너속도 강제 (강한 brake로 τ 부분 commitment 보상) ─
    if own.speed > CORNER_SPD + 5.0:
        d_speed_corner = -25.0
    elif own.speed < CORNER_SPD - 5.0:
        d_speed_corner = 5.0
    else:
        d_speed_corner = 0.0

    # ── 정리 8 명령: 수직 yo-yo — alt_gap OR own.γ 두 trigger의 max ─────
    # 두 trigger 사용: (1) alt_gap 부족하면 climb (2) own.γ 충분히 climb했으면 dive
    # 적이 alt-track하면 alt_gap이 안 커지지만 own.γ는 우리가 직접 제어 → 우회 가능
    alt_gap = obs["alt_gap_ft"]
    f_alt   = math.tanh((1500.0 - alt_gap) / 500.0)   # alt_gap 작으면 +, 크면 -
    f_gamma = math.tanh((25.0 - own.gamma) / 10.0)    # γ 작으면 +(climb), 크면 -(dive)
    d_gamma_yoyo = MAX_TR * 0.65 * min(f_alt, f_gamma)  # 둘 중 더 보수적 (먼저 dive)

    # 수직 우위가 충분한 dive 단계일 때: 적 예측 6시로 헤딩 — orbit intercept
    # 발동: alt_gap > 1500 OR own.γ > 25° (적이 alt-track해도 우리 자세로 trigger)
    d_hdg_dive = d_hdg_pn   # 기본은 PN
    if (alt_gap > 1500.0 or own.gamma > 25.0) and enemy is not None:
        T_pred, gun_range = 5.0, 2000.0
        evx, evy, evz = enemy.vel()
        ev_mag = math.sqrt(evx*evx + evy*evy + evz*evz) + 1e-9
        fx = enemy.x + evx * T_pred - (evx / ev_mag) * gun_range
        fy = enemy.y + evy * T_pred - (evy / ev_mag) * gun_range
        ddx, ddy = fx - own.x, fy - own.y
        tgt_bear = math.degrees(math.atan2(ddx, ddy)) % 360.0
        err_dive = ang_diff(tgt_bear, own.hdg)
        d_hdg_dive = max(-own.tr, min(own.tr, err_dive / (DT * 2.0)))

    # ── 정리 7 명령: lag pursuit (90° offset) ────────────────────
    bear = geo["bear"]
    side = 1.0 if ang_diff(bear, own.hdg) > 0 else -1.0
    lag_target = (bear + side * 90.0) % 360.0
    err_lag = ang_diff(lag_target, own.hdg)
    d_hdg_lag = max(-own.tr, min(own.tr, err_lag / (DT * 2.5)))

    # ── 연속 blending ────────────────────────────────────────────
    # d_hdg: 3-way 가중 blending — PN(default) / dive intercept(τy 강) / lag(τl 강)
    w_pn  = max(0.0, 1.0 - τl - τy)
    w_dv  = τy
    w_lag = τl
    w_sum = w_pn + w_dv + w_lag + 1e-9
    d_hdg = (w_pn * d_hdg_pn + w_dv * d_hdg_dive + w_lag * d_hdg_lag) / w_sum

    d_speed = (1.0 - τc) * d_speed_pn + τc * d_speed_corner
    d_gamma = (1.0 - τy) * d_gamma_pn + τy * d_gamma_yoyo

    return d_hdg, d_gamma, d_speed, {"tau_c": τc, "tau_y": τy, "tau_l": τl}


def branch_cmd(branch, own, geo, enemy=None):
    """브랜치별 고유 명령 (HCCA 미사용 브랜치) → (d_hdg, d_gamma, d_speed)."""
    bear    = geo["bear"]
    elev    = geo.get("elev", 0.0)
    alt_gap = geo.get("alt_gap", 0.0)   # 양수 = 우리가 위

    if branch == "HardDeckAvoidance":
        # 상승 명령 — 강한 피치업
        return 0.0, MAX_TR * 0.7, 15.0

    elif branch == "GunEngagement":
        err = ang_diff(bear, own.hdg)
        # 수평 정렬 + 적 고도 맞추기
        d_gamma = max(-MAX_TR*0.3, min(MAX_TR*0.3, (elev - own.gamma) / (DT * 4.0)))
        # closure < 0이면 적이 도망 중 — sprint로 추격
        # closure > 0 이면 충분히 가까워지는 중 — 코너 유지로 사격 정밀도 우선
        cl = geo.get("closure", 0.0)
        d_speed_gun = 20.0 if cl < 0.0 and own.speed < MAX_SPD else 0.0
        return max(-5.0, min(5.0, err / DT)), d_gamma, d_speed_gun

    elif branch == "CircularOrbitBreak":
        # 3D 궤도 인터셉트: 적 예측 궤도 뒤 gun_range에 dive 합류
        # enemy가 있으면 궤도 예측 인터셉트, 없으면 기존 수직 break 폴백
        if enemy is not None:
            return _orbit_intercept_cmd(own, enemy, geo)
        # 폴백: 단순 수직 break
        err = ang_diff(bear, own.hdg)
        d_hdg = max(-MAX_TR, min(MAX_TR, err / (DT * 2.0)))
        d_gamma = MAX_TR * 0.5 if alt_gap < 500.0 else 0.0
        accel_orb = 10.0 if own.speed < CORNER_SPD else 0.0
        return d_hdg, d_gamma, accel_orb

    elif branch in ("CounterGunRun",):
        err = ang_diff(bear + 90.0, own.hdg)
        return max(-MAX_TR, min(MAX_TR, err / DT)), MAX_TR * 0.4, -5.0

    elif branch == "LostPursuitReverse":
        ata  = geo["ata"]
        dist = geo["dist"]
        cl   = geo["closure"]
        aa   = geo["aa"]

        # SpeedbrakeReversal: 고속 추격기 + 근거리 → 감속으로 오버슈트 유도
        if cl > 200.0 and dist < 4000.0:
            return 0.0, 0.0, -20.0

        # 적 도주 중(꼬리 노출): 직선 고속 추격
        if aa > 120.0 and cl < -150.0:
            err = ang_diff(bear, own.hdg)
            d_hdg = max(-own.tr, min(own.tr, err / (DT * 1.0)))
            accel = 20.0 if own.speed < MAX_SPD else 0.0
            return d_hdg, elev - own.gamma > 0 and MAX_TR*0.3 or 0.0, accel

        # 직접 역전: 적 방향 하드턴 → head-on 거리 최소화
        # Phase 1 수직선(perpendicular pull-up) 제거:
        #   offensive enemy는 수직도 추적 → 수직 이탈 효과 없음
        #   직접 bear 방향 전환이 head-on 거리를 단축 (최소 패스 거리 ↓)
        # ATA < 140° 도달 시 다음 틱 CircularOrbitBreak → orbit intercept로 이관
        err = ang_diff(bear, own.hdg)
        if alt_gap > 2000.0:
            d_gamma = -MAX_TR * 0.35  # 고도 우위: dive로 에너지 변환
        else:
            d_gamma = MAX_TR * 0.45   # 고도 열세: pull-up으로 고도 확보
        accel_rev = 10.0 if own.speed < CORNER_SPD else 0.0
        d_hdg = max(-own.tr, min(own.tr, err / (DT * 1.0)))
        return d_hdg, d_gamma, accel_rev

    elif branch == "ScissorsBreak":
        # 수평 내측 절단 + 수직 break (평면 전환으로 scissors 교착 탈출)
        perp1 = (bear + 90.0) % 360.0
        perp2 = (bear - 90.0) % 360.0
        err1 = ang_diff(perp1, own.hdg)
        err2 = ang_diff(perp2, own.hdg)
        target = perp1 if abs(err1) < abs(err2) else perp2
        err = ang_diff(target, own.hdg)
        d_hdg = max(-MAX_TR, min(MAX_TR, err / (DT * 1.0)))
        # 수직: 적보다 위면 push-over, 아래면 pull-up → 고도 교차로 2D 교착 탈출
        d_gamma = -MAX_TR * 0.5 if alt_gap > 500.0 else MAX_TR * 0.5
        accel_sc = -15.0 if own.speed > CORNER_SPD else 5.0
        return d_hdg, d_gamma, accel_sc

    elif branch == "DefensiveEscape":
        err = ang_diff(bear + 90.0, own.hdg)
        # break turn + pull-up → 3D 방어 기동
        return max(-own.tr, min(own.tr, err / DT)), MAX_TR * 0.5, 10.0

    elif branch == "OffensivePursuit":
        dist = geo["dist"]
        ata  = geo["ata"]
        cl   = geo["closure"]
        n_off = 3.5 + max(0.0, -cl) / 200.0 * 1.5
        n_off = max(3.0, min(5.0, n_off))
        if ata < 5.0 and dist > 2500.0:
            accel = min(25.0, 15.0 + max(0.0, -cl) / 100.0 * 5.0)
        elif dist > 4000.0:
            accel = min(15.0, 8.0 + max(0.0, -cl) / 150.0 * 5.0)
        else:
            accel = 0.0
        d_hdg, d_gamma, _ = pn_cmd(own, geo, N=n_off)
        return d_hdg, d_gamma, accel

    elif branch == "HeadOnGun":
        err = ang_diff(geo["bear"], own.hdg)
        d_gamma = max(-MAX_TR*0.3, min(MAX_TR*0.3, (elev - own.gamma) / (DT * 4.0)))
        return max(-5.0, min(5.0, err / DT)), d_gamma, 0.0

    elif branch == "WezLock":
        err = ang_diff(geo["bear"], own.hdg)
        d_gamma = max(-MAX_TR*0.3, min(MAX_TR*0.3, (elev - own.gamma) / (DT * 4.0)))
        return max(-5.0, min(5.0, err / DT)), d_gamma, -2.0

    else:
        # LeadPursuit 폴백
        if geo["ata"] < 15.0 and geo["dist"] > 3000.0:
            d_hdg, d_gamma, _ = pn_cmd(own, geo, N=0.0)
            return d_hdg, d_gamma, 20.0 if own.speed < MAX_SPD else 0.0
        return pn_cmd(own, geo, N=3.0)


def hcca_mode_cmd(mode, own, geo):
    """HCCA 모드별 명령 → (d_hdg, d_gamma, d_speed)."""
    ata  = geo["ata"]; dist = geo["dist"]; cl = geo["closure"]
    elev = geo.get("elev", 0.0)

    # 꼬리 추격 / 2-orbit 교착 탈출: N=0 순수 추격 + 최대 가속
    # 브레이크 조건 제거: 꼬리 추격에서 감속하면 적이 이탈해 클로저 반전됨
    if ata < 15.0 and dist > 3000.0:
        d_hdg, d_gamma, _ = pn_cmd(own, geo, N=0.0)
        accel = 20.0 if own.speed < MAX_SPD else 0.0
        return d_hdg, d_gamma, accel

    if mode == CMC.MODE_ATTACK:   # 0
        n_atk = max(3.0, min(5.0, 4.0 + max(0.0, 3000.0 - dist) / 3000.0))
        return pn_cmd(own, geo, N=n_atk)

    elif mode == CMC.MODE_DEFEND:  # 1
        if geo["hca"] > 150.0:
            err = ang_diff(geo["bear"], own.hdg)
            d_gamma = max(-MAX_TR*0.3, min(MAX_TR*0.3, (elev - own.gamma) / (DT * 4.0)))
            return max(-5.0, min(5.0, err / DT)), d_gamma, 0.0
        err = ang_diff(geo["bear"] + 90.0, own.hdg)
        # 방어 break turn + pull-up (3D 방어)
        return max(-own.tr, min(own.tr, err / (DT * 1.5))), MAX_TR * 0.4, -3.0

    elif mode == CMC.MODE_ENERGY:  # 2
        # 에너지 회복: 가속 + 상승으로 위치에너지 확보
        return 0.0, MAX_TR * 0.3, 15.0

    else:                          # PURSUE = 3
        n_pur = max(2.5, min(4.5, 3.5 + max(0.0, -cl) / 200.0))
        accel_pur = 5.0 if cl < -100.0 else 0.0
        d_hdg, d_gamma, _ = pn_cmd(own, geo, N=n_pur)
        return d_hdg, d_gamma, accel_pur


# ══════════════════════════════════════════════════════════════════════
# CMC obs 빌드 (실제 _update_state 입력 형태)
# ══════════════════════════════════════════════════════════════════════

def build_obs(geo, own, e_diff=0.0):
    ata, aa, dist, cl, hca, tc = (
        geo["ata"], geo["aa"], geo["dist"], geo["closure"],
        geo["hca"], geo["tc_type"]
    )
    # 속도 기반 실제 선회율 및 선회 반경 계산
    tr_now = own.tr          # 현재 속도에서의 최대 선회율 (°/s)
    r_now  = own.radius      # 현재 최소 선회 반경 (ft)
    # 오버슈트 위험: dist가 선회 반경의 1.5배 미만이면 오버슈트 가능성
    overshoot_risk = (dist < r_now * 1.5 and ata < 30.0)
    # 상대 방위 (28-피처 정의: ang_diff(bear, ego.hdg))
    rel_bear = ang_diff(geo["bear"], own.hdg)
    return {
        "ata_deg":         ata / 180.0,
        "aa_deg":          aa / 180.0,
        "distance_ft":     dist,
        "closure_rate_kts": cl,
        "energy_diff_ft":  e_diff,
        "relative_bearing_deg": rel_bear / 180.0,
        "ego_altitude_ft": own.z,
        "ego_vc_kts":      own.speed,
        "ps_fts":          own.speed * math.sin(math.radians(own.gamma)) * KTS_TO_FPS,
        "turn_rate_degs":  tr_now,   # 속도 기반 실제 선회율
        "in_wez":          (aa < 20.0 and dist < 2500.0),
        "enm_in_wez":      (ata < 20.0 and dist < 2500.0),
        "alt_gap_ft":      geo.get("alt_gap", 0.0),
        "alt_advantage":   geo.get("alt_gap", 0.0) > 500.0,
        "energy_advantage": e_diff > 0,
        "overshoot_risk":  overshoot_risk,
        # tau_deg: PN lead 각도 — relative_bearing이 ATA에 가까울수록 정렬됨
        "tau_deg":         rel_bear / 180.0,
        "hca_deg":         hca / 180.0,
        "tc_type":         tc,
        "in_39_line":      (abs(rel_bear) < 90.0),
        "ata_lead_deg":    ata / 180.0,
        # 추가 파생 변수 (HCCA 확장용)
        "turn_radius_ft":  r_now,
        "corner_margin_kts": own.speed - CORNER_SPD,
    }


# ══════════════════════════════════════════════════════════════════════
# 시나리오 실행기
# ══════════════════════════════════════════════════════════════════════

def run_scenario(init, policy, max_ticks=300, verbose=False):
    """
    init: {"own": (x,y,hdg,spd), "enemy": (x,y,hdg,spd), "e_diff": float(optional)}
    Returns: {
        "outcome": "WIN"/"LOSS"/"DRAW",
        "ticks": int,
        "branches": {branch: count},
        "modes":    {mode_name: count},
        "tau_th_mean": float,
        "tau_op_mean": float,
        "min_dist":  float,
        "own_gun_ticks": int,   # IR-1: HP 모델 — 아군 사격 틱
        "enemy_gun_ticks": int, # IR-1: HP 모델 — 적 사격 틱
        "log":       [(tick, ata, dist, cl, branch, mode, t_th, t_op), ...]
    }
    """
    ox, oy, oz, ohdg, ogamma, ospd = init["own"]
    ex, ey, ez, ehdg, egamma, espd = init["enemy"]
    own   = Aircraft(ox, oy, oz, ohdg, ogamma, ospd)
    enemy = Aircraft(ex, ey, ez, ehdg, egamma, espd)
    e_diff_init = init.get("e_diff", 0.0)  # IR-5: 에너지 결핍 초기값

    cmc = CMC()
    cmc._mode_ticks = 0

    cl_history    = []
    branch_cnt    = {}
    mode_cnt      = {}
    tau_th_sum    = 0.0
    tau_op_sum    = 0.0
    min_dist      = 1e9
    log           = []
    # IR-1: HP 교환 비율 추적
    own_gun_ticks   = 0
    enemy_gun_ticks = 0
    # IR-4: StaleChaseBreak 쿨다운 (발동 후 20틱 SPRINT 강제)
    stale_cooldown = 0
    # GAP-D2: Z5 역전 완료 감지 → sprint 쿨다운
    prev_ata       = None
    z5_reversed    = False      # Z5(ATA>140°)에서 ATA<90°로 역전 성공 플래그
    reverse_sprint = 0          # 역전 후 sprint 틱 카운터
    # GAP-D3: WEZ lock — WEZ 진입 후 최소 유지
    wez_lock       = 0          # WEZ 내 유지 틱 카운터 (최소 8틱)
    # τ-blended 적응 제어 — 이전 obs 추적 (시간차분 기반 LOS rate, alt rate)
    prev_obs       = None
    # τ 시계열 누적 (사후 분석용)
    tau_c_sum      = 0.0
    tau_y_sum      = 0.0
    tau_l_sum      = 0.0
    tau_n          = 0

    MODE_NAMES = {0: "ATTACK", 1: "DEFEND", 2: "ENERGY", 3: "PURSUE"}

    outcome = "DRAW"
    for tick in range(max_ticks):
        geo = compute_geo(own, enemy)
        cl_history.append(geo["closure"])
        if len(cl_history) > 30:
            cl_history.pop(0)
        avg_cl = sum(cl_history) / len(cl_history)
        min_dist = min(min_dist, geo["dist"])

        # IR-1: HP 누적 (매 틱)
        if is_victory(geo):
            own_gun_ticks += 1
        if is_enemy_win(geo):
            enemy_gun_ticks += 1

        # IR-1: HP 비율 기반 승패 판정 (60틱 단위 확인 + 최종)
        if tick > 0 and tick % 60 == 0:
            if own_gun_ticks > enemy_gun_ticks * 1.5 and own_gun_ticks >= 5:
                outcome = "WIN"
                break
            if enemy_gun_ticks > own_gun_ticks * 1.5 and enemy_gun_ticks >= 5:
                outcome = "LOSS"
                break

        # ── GAP-D2: Z5 역전 완료 감지 ──
        ata_now = geo["ata"]
        if prev_ata is not None and prev_ata > 140.0 and ata_now < 90.0:
            z5_reversed = True
            reverse_sprint = 30   # 역전 후 30틱 sprint 집중
        if z5_reversed and reverse_sprint > 0:
            reverse_sprint -= 1
            if reverse_sprint == 0:
                z5_reversed = False
        prev_ata = ata_now

        # ── BT 브랜치 선택 ──
        branch = select_bt_branch(geo, avg_cl, own_spd=own.speed, alt=own.z, own_gamma=own.gamma)

        # GAP-L1: 정면 WEZ — HCA>150° + dist<3000 → DEFEND 억제, HeadOnGun 강제
        if geo["hca"] > 150.0 and geo["dist"] < 3000.0 and geo["ata"] < 20.0:
            branch = "HeadOnGun"

        # GAP-D3: WEZ lock — WEZ 진입 후 최소 8틱 유지 (DEFEND 억제)
        if is_victory(geo):
            wez_lock = max(wez_lock, 8)
        if wez_lock > 0:
            branch = "WezLock"
            wez_lock -= 1

        # GAP-D2: 역전 완료 후 sprint — LeadPursuit를 sprint로 오버라이드
        if z5_reversed and reverse_sprint > 0 and branch in ("LeadPursuit", "StaleChaseBreak", "LostPursuitReverse"):
            branch = "StaleChaseBreak_SPRINT"

        # IR-4: StaleChaseBreak 쿨다운 처리
        # Orbit Intercept dive 중 (gamma<-5°, alt_gap>1000ft)에는 sprint 억제
        # — dive phase에서 sprint가 gamma를 0°로 되돌려 dive 취소하는 문제 방지
        in_orbit_dive = own.gamma < -5.0 and geo.get("alt_gap", 0.0) > 1000.0
        if stale_cooldown > 0 and not in_orbit_dive:
            branch = "StaleChaseBreak_SPRINT"
            stale_cooldown -= 1
        elif stale_cooldown > 0:   # dive 중: 카운트다운만, 브랜치 유지
            stale_cooldown -= 1
        elif branch == "StaleChaseBreak":
            stale_cooldown = 20  # 다음 20틱 sprint 강제

        branch_cnt[branch] = branch_cnt.get(branch, 0) + 1

        # ── 제어 합성 ──
        mode_name = branch  # 기본값

        if branch == "TheoremAdaptive":
            # τ-blended 연속 제어 (정리 5/6/7/8 obs 직접 매핑)
            obs_now = build_obs(geo, own, e_diff=e_diff_init)
            d_hdg, d_gamma, d_spd, tau_dict = adaptive_command(
                obs_now, prev_obs, own, geo, enemy=enemy
            )
            prev_obs = obs_now
            tau_c_sum += tau_dict["tau_c"]
            tau_y_sum += tau_dict["tau_y"]
            tau_l_sum += tau_dict["tau_l"]
            tau_n += 1
            t_th, t_op = 0.0, 0.0
            mode_name = "Theorem(c=%.2f,y=%.2f,l=%.2f)" % (
                tau_dict["tau_c"], tau_dict["tau_y"], tau_dict["tau_l"]
            )
        elif branch in _HCCA_BRANCHES or branch in ("StaleChaseBreak", "StaleChaseBreak_SPRINT",
                                                    "HeadOnGun", "WezLock"):
            obs = build_obs(geo, own, e_diff=e_diff_init)  # IR-5: e_diff 연결
            s = cmc._update_state(obs)
            t_th = cmc._compute_tau_threat(s)
            t_op = cmc._compute_tau_opportunity(s)
            t_en = cmc._compute_tau_energy(s)
            t_pu = cmc._compute_tau_pursuit(s)
            mode = cmc._select_mode(t_th, t_op, t_en, t_pu)
            # GAP-Z45: 공격/중립 기하(ATA<90°) 또는 Z4/Z5(ATA>100°)에서 DEFEND 억제
            # ATA<90°: 우리가 빔 이내 — DEFEND break turn이 ATA를 180°까지 악화시킴
            # ATA>100°: Z4/Z5에서 break turn은 기하학 악화 — 오히려 적 방향 선회
            if mode == CMC.MODE_DEFEND:
                if geo["ata"] < 90.0:
                    mode = CMC.MODE_ATTACK   # 공격/중립 기하 → 공격 유지
                elif geo["ata"] > 100.0:
                    mode = CMC.MODE_PURSUE   # Z4/Z5 → ATA 감소 추구
            mode_name = MODE_NAMES[mode]
            mode_cnt[mode_name] = mode_cnt.get(mode_name, 0) + 1
            tau_th_sum += t_th
            tau_op_sum += t_op
            if branch == "StaleChaseBreak_SPRINT":
                # IR-4: 쿨다운 중 강제 공격적 PN (N=5) + 최대 가속
                d_hdg, d_gamma, _ = pn_cmd(own, geo, N=5.0)
                d_spd = 20.0
            else:
                d_hdg, d_gamma, d_spd = hcca_mode_cmd(mode, own, geo)
        else:
            t_th, t_op = 0.0, 0.0
            d_hdg, d_gamma, d_spd = branch_cmd(branch, own, geo, enemy=enemy)

        # ── Close-in sprint: 기수 정렬됐고 WEZ 직전 → 최대 가속 ──
        # cl>20kts 조건 추가: Scissors 교착(cl<20)에서는 감속이 필요하므로 sprint 억제
        if geo["ata"] < 15.0 and geo["dist"] > 3000.0 and own.speed < MAX_SPD and geo["closure"] > 20.0:
            d_spd = max(d_spd, 20.0)

        if verbose and tick % 25 == 0:
            print("    t=%3d | ATA=%5.1f° dist=%6.0fft cl=%+5.0fkts z=%.0fft γ=%+.1f° TR=%.1f°/s | %s→%s"
                  % (tick, geo["ata"], geo["dist"], geo["closure"],
                     own.z, own.gamma, own.tr, branch, mode_name))

        # 로그: (tick, ata, dist, cl, branch, mode, t_th, t_op, own_speed, own_tr, own_radius,
        #       aa, hca, alt_gap)  ← STL falsification 용 추가
        log.append((tick, geo["ata"], geo["dist"], geo["closure"], branch, mode_name, t_th, t_op,
                    own.speed, own.tr, own.radius,
                    geo["aa"], geo["hca"], geo.get("alt_gap", 0.0)))

        # ── 아군 기동 ──
        own.step(d_hdg, d_gamma, d_spd)

        # ── 적 기동 ──
        e_dhdg, e_dgamma, e_dspd = enemy_policy(policy, enemy, own, geo, tick)
        enemy.step(e_dhdg, e_dgamma, e_dspd)
    else:
        # 최종 HP 비율 판정
        if own_gun_ticks > enemy_gun_ticks * 1.5 and own_gun_ticks >= 3:
            outcome = "WIN"
        elif enemy_gun_ticks > own_gun_ticks * 1.5 and enemy_gun_ticks >= 3:
            outcome = "LOSS"
        else:
            outcome = "DRAW"

    n_hcca = sum(mode_cnt.values())
    return {
        "outcome":        outcome,
        "ticks":          tick + 1,
        "branches":       branch_cnt,
        "modes":          mode_cnt,
        "tau_th_mean":    tau_th_sum / max(n_hcca, 1),
        "tau_op_mean":    tau_op_sum / max(n_hcca, 1),
        "min_dist":       min_dist,
        "own_gun_ticks":  own_gun_ticks,
        "enemy_gun_ticks": enemy_gun_ticks,
        "log":            log,
    }


# ══════════════════════════════════════════════════════════════════════
# 초기 배치 25종 — 5 구역 × 5 변형
# ══════════════════════════════════════════════════════════════════════

def make_sc(ata=90, dist=CANONICAL_DIST, own_spd=CANONICAL_SPD, enm_spd=CANONICAL_SPD,
            ehdg=180.0, alt=CANONICAL_ALT, e_diff=0.0, desc=""):
    """
    JSBSim 실제 초기 조건 기반 배치 생성.

    기본값 = 모든 실전 매치의 표준 시작점:
      ATA=90°, dist=3297.6ft, own/enm_spd=386.8kts, alt=15000ft
      아군: 원점, 북향(hdg=0°)
      적:   ATA 방향 dist ft, ehdg=180°(남향) → HCA=180°(반대방향), cl=0kts

    ATA=90°, ehdg=180° 검증:
      적 위치 = east(3297.6, 0, 15000)
      LOS = east → ATA = angle(north, east) = 90° ✓
      적 velocity = south → AA = angle(south, west_to_own) = 90°
      HCA = angle(north, south) = 180° ✓
      closure = (northVel − southVel) · eastLOS = 0 kts ✓

    ehdg 조정으로 다른 교전 유형 표현 가능:
      ehdg=  0° → 적이 우리와 같은 방향(북향) = tail chase(아군이 뒤)
      ehdg=180° → 적이 남향 = 2-circle 중립(canonical) / head-on(ATA=0°)
    """
    rad = math.radians(ata)
    ex = dist * math.sin(rad)
    ey = dist * math.cos(rad)
    return {
        "own":   (0.0, 0.0, alt, 0.0, 0.0, own_spd),   # (x,y,z,hdg,gamma,spd)
        "enemy": (ex,  ey,  alt, ehdg, 0.0, enm_spd),
        "e_diff": e_diff,
        "desc":  desc,
    }


# ══════════════════════════════════════════════════════════════════════
# 시나리오 — 실제 JSBSim 초기 조건 분기
#
# 모든 실전 매치는 ATA=90°, dist=3297.6ft, spd=386.8kts, alt=15000ft에서 시작.
# 아군과 적의 기동 선택(BT 브랜치 vs 적 정책)에 따라 서로 다른 전투 궤적이 분기됨.
#
# 구조:
#   [1] 표준 2-circle 초기 (canonical): 실전 매치와 동일한 시작점
#   [2] 초기 거리 변형: 매치 초기 근접/원거리 산포 검증
#   [3] 에너지/속도 변형: 에너지 격차 및 속도 불균형 분기 검증
#   [4] 고도 변형: 저고도 교전 분기
# ══════════════════════════════════════════════════════════════════════

SCENARIOS = {

    # ─── [1] 표준 2-circle 초기 (실전 매치 완전 동일) ───
    # ATA=90°, dist=3297.6ft, spd=386.8kts, alt=15000ft, HCA=180°, cl=0kts
    "canonical":
        make_sc(desc="[표준] 2-circle 중립 초기 — JSBSim 실전 매치와 동일"),

    # ─── [2] 초기 거리 변형 (ATA=90° 유지, dist 변형) ───
    # 실전 매치에서 초기 배치 산포(±500ft) + 근접/원거리 교전 시작 검증
    "canonical_close":
        make_sc(dist=2000, desc="[거리] 근접 초기(2000ft) — 조기 GunWEZ 가능성"),
    "canonical_mid":
        make_sc(dist=4500, desc="[거리] 중거리 초기(4500ft) — CircularOrbit 주요 구간"),
    "canonical_far":
        make_sc(dist=7000, desc="[거리] 원거리 초기(7000ft) — 접근 단계 검증"),

    # ─── [3] 에너지/속도 변형 ───
    "canonical_e_deficit":
        make_sc(e_diff=-3000, desc="[에너지] 결핍(e_diff=-3000ft) — ENERGY 모드 발동 검증"),
    "canonical_e_surplus":
        make_sc(e_diff=+3000, desc="[에너지] 우위(e_diff=+3000ft) — ATTACK 전환 검증"),
    "canonical_own_slow":
        make_sc(own_spd=300, desc="[속도] 아군 저속(300kts) — 코너속도 열위"),
    "canonical_enm_fast":
        make_sc(enm_spd=420, desc="[속도] 적 고속(420kts=MAX_SPD) — 이탈 능력 최대"),
    "canonical_enm_slow":
        make_sc(enm_spd=300, desc="[속도] 적 저속(300kts) — 추격 용이"),

    # ─── [4] 고도 변형 ───
    "canonical_alt_low":
        make_sc(alt=8000, desc="[고도] 저고도(8000ft) — 하드덱 압박 + HardDeckAvoidance 검증"),
    "canonical_alt_high":
        make_sc(alt=25000, desc="[고도] 고고도(25000ft) — 에너지 우위 교전"),
}

POLICIES = ["passive", "orbiting", "defensive", "offensive", "evading"]
POLICY_DESC = {
    "passive":   "직선 비행",
    "orbiting":  "좌선회 교착(-13°/s)",
    "defensive": "위협 시 Break turn",
    "offensive": "PN 추격 N=3",
    "evading":   "추격 시 90° Break (IR-6)",
}


# ══════════════════════════════════════════════════════════════════════
# 결과 출력
# ══════════════════════════════════════════════════════════════════════

def fmt_branches(bc):
    top = sorted(bc.items(), key=lambda x: -x[1])[:3]
    return " / ".join("%s(%d)" % (b, c) for b, c in top)

def fmt_modes(mc):
    top = sorted(mc.items(), key=lambda x: -x[1])[:3]
    return " / ".join("%s(%d)" % (m, c) for m, c in top)


def print_header():
    print("=" * 120)
    print("  %-16s  %-12s  %-6s  %-5s  %-34s  %-26s  HP(아군/적/비율)" %
          ("시나리오", "적 정책", "결과", "틱", "BT 브랜치 (상위 3)", "HCCA 모드 (상위 3)"))
    print("=" * 120)


def analyze_timeseries(sc_name, policy, r):
    """매 틱 시계열 분석 — DRAW/LOSS 시나리오 상세 진단."""
    log = r["log"]
    if not log:
        return

    print("\n  ┌─── 시계열 분석: [%s × %s]  outcome=%s  HP=%d/%d ───" %
          (sc_name, policy, r["outcome"], r["own_gun_ticks"], r["enemy_gun_ticks"]))

    # ─ 헤더 ─
    print("  │ %4s │ %6s │ %6s │ %6s │ %5s │ %5s │ %-22s │ %-7s │ %5s │ %5s │ %4s │ %4s" %
          ("tick", "ATA°", "dist", "cl_kts", "TR°/s", "R_ft", "branch", "mode", "τ_th", "τ_op", "own♦", "enm♦"))
    print("  │" + "─"*112)

    # ─ 누적 HP 상태 ─
    cum_own = 0
    cum_enm = 0

    # ─ 페이즈 추적 (연속 동일 branch+mode 묶기) ─
    prev_phase = None
    phase_start = 0

    phases = []   # (start, end, branch, mode, ata_mean, dist_mean, cl_mean, tr_mean, r_mean)
    phase_ata = []; phase_dist = []; phase_cl = []; phase_tr = []; phase_r = []

    for i, entry in enumerate(log):
        tick, ata, dist, cl, branch, mode, t_th, t_op = entry[:8]
        spd  = entry[8]  if len(entry) > 8 else 300.0
        tr   = entry[9]  if len(entry) > 9 else 12.0
        rad  = entry[10] if len(entry) > 10 else 2000.0

        # HP 누적
        if ata < V_ATA_MAX and V_DIST_MIN < dist < V_DIST_MAX and cl > V_CL_MIN:
            cum_own += 1
        if ata > (180 - V_ATA_MAX) and V_DIST_MIN < dist < V_DIST_MAX and cl > V_CL_MIN:
            cum_enm += 1

        # 페이즈 변화 감지
        cur_phase = (branch, mode)
        if cur_phase != prev_phase:
            if prev_phase is not None and phase_ata:
                phases.append((phase_start, tick - 1, prev_phase[0], prev_phase[1],
                                sum(phase_ata)/len(phase_ata), sum(phase_dist)/len(phase_dist),
                                sum(phase_cl)/len(phase_cl), sum(phase_tr)/len(phase_tr),
                                sum(phase_r)/len(phase_r)))
            phase_start = tick
            phase_ata = []; phase_dist = []; phase_cl = []; phase_tr = []; phase_r = []
            prev_phase = cur_phase

        phase_ata.append(ata); phase_dist.append(dist); phase_cl.append(cl)
        phase_tr.append(tr);   phase_r.append(rad)

        # WEZ 플래그
        flag = ""
        if ata < V_ATA_MAX and V_DIST_MIN < dist < V_DIST_MAX and cl > 0:
            flag = "♦OWN"
        elif (180 - ata) < V_ATA_MAX and V_DIST_MIN < dist < V_DIST_MAX and cl > 0:
            flag = "♦ENM"

        print("  │ %4d │ %6.1f │ %6.0f │ %+6.0f │ %5.1f │ %5.0f │ %-22s │ %-7s │ %5.2f │ %5.2f │ %4d │ %4d %s" %
              (tick, ata, dist, cl, tr, rad, branch[:22], mode[:7], t_th, t_op, cum_own, cum_enm, flag))

    # 마지막 페이즈
    if prev_phase and phase_ata:
        phases.append((phase_start, log[-1][0], prev_phase[0], prev_phase[1],
                        sum(phase_ata)/len(phase_ata), sum(phase_dist)/len(phase_dist),
                        sum(phase_cl)/len(phase_cl), sum(phase_tr)/len(phase_tr),
                        sum(phase_r)/len(phase_r)))

    # ─ 페이즈 요약 ─
    print("  │" + "─"*112)
    print("  ├─ 페이즈 요약 (branch+mode 연속 구간)")
    print("  │ %5s–%-5s │ %-22s │ %-7s │ ATA_avg │ dist_avg │  cl_avg │ TR_avg │  R_avg" %
          ("from", "to", "branch", "mode"))
    for (t0, t1, br, mo, a_avg, d_avg, c_avg, tr_avg, r_avg) in phases:
        print("  │ %5d–%-5d │ %-22s │ %-7s │ %7.1f │ %8.0f │ %+7.0f │ %6.1f° │ %6.0fft" %
              (t0, t1, br[:22], mo[:7], a_avg, d_avg, c_avg, tr_avg, r_avg))

    # ─ 핵심 지표 ─
    atas  = [e[1] for e in log]; dists = [e[2] for e in log]; cls = [e[3] for e in log]
    trs   = [e[9]  if len(e) > 9  else 12.0  for e in log]
    rads  = [e[10] if len(e) > 10 else 2000. for e in log]
    print("  ├─ ATA:  min=%.1f° max=%.1f° 최종=%.1f°" % (min(atas), max(atas), atas[-1]))
    print("  ├─ dist: min=%.0f max=%.0f 최종=%.0f ft" % (min(dists), max(dists), dists[-1]))
    print("  ├─ cl:   min=%+.0f max=%+.0f 최종=%+.0f kts" % (min(cls), max(cls), cls[-1]))
    print("  ├─ TR:   min=%.1f° max=%.1f° avg=%.1f°/s" % (min(trs), max(trs), sum(trs)/len(trs)))
    print("  ├─ R:    min=%.0f max=%.0f avg=%.0f ft" % (min(rads), max(rads), sum(rads)/len(rads)))
    print("  └─ HP누적: 아군=%d 적=%d" % (r["own_gun_ticks"], r["enemy_gun_ticks"]))
    print()


# ══════════════════════════════════════════════════════════════════════
# 메인 실행
# ══════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    n_sc = len(SCENARIOS)
    n_pol = len(POLICIES)
    print("\n" + "="*110)
    print("  HCCA v12 BT 주입 1:1 도그파이트 시뮬레이션 (실전 JSBSim 초기 조건 기반)")
    print("  %d 시나리오 × %d 적정책 = %d 총 케이스 | max 1500틱(300s=실제매치)" % (n_sc, n_pol, n_sc*n_pol))
    print("  초기 조건: ATA=90°, dist=3297.6ft, spd=386.8kts, alt=15000ft, HCA=180°, cl=0kts")
    print("  HP 모델: own_gun_ticks vs enemy_gun_ticks (비율 1.5× 기준)")
    print("="*110)

    all_results = {}
    outcome_counts = {"WIN": 0, "LOSS": 0, "DRAW": 0}

    for sc_name, sc in SCENARIOS.items():
        print("\n▶ %s\n  %s\n" % (sc_name.upper(), sc["desc"]))
        print_header()

        for policy in POLICIES:
            r = run_scenario(sc, policy, max_ticks=1500, verbose=False)
            all_results[(sc_name, policy)] = r
            outcome_counts[r["outcome"]] += 1

            out_sym = {"WIN": "✅ WIN ", "LOSS": "❌ LOSS", "DRAW": "⚠ DRAW"}[r["outcome"]]
            hp_ratio = r["own_gun_ticks"] / max(r["enemy_gun_ticks"], 1)
            print("  %-16s  %-12s  %s  %5d  %-34s  %-26s  HP=%d/%d(×%.1f)" % (
                sc_name, policy,
                out_sym, r["ticks"],
                fmt_branches(r["branches"]),
                fmt_modes(r["modes"]),
                r["own_gun_ticks"], r["enemy_gun_ticks"], hp_ratio,
            ))

        print()

    # ── 종합 요약 ──
    total = len(all_results)
    total_own_hp   = sum(r["own_gun_ticks"]   for r in all_results.values())
    total_enemy_hp = sum(r["enemy_gun_ticks"] for r in all_results.values())
    print("\n" + "=" * 120)
    print("  종합 결과: %d 케이스" % total)
    print("  WIN=%d (%.0f%%)  LOSS=%d (%.0f%%)  DRAW=%d (%.0f%%)" % (
        outcome_counts["WIN"],  100*outcome_counts["WIN"]/total,
        outcome_counts["LOSS"], 100*outcome_counts["LOSS"]/total,
        outcome_counts["DRAW"], 100*outcome_counts["DRAW"]/total,
    ))
    print("  HP 교환: 아군=%d틱 vs 적=%d틱 (교환비=×%.2f)" % (
        total_own_hp, total_enemy_hp,
        total_own_hp / max(total_enemy_hp, 1)))
    print()

    # ── 전황별 BT 브랜치 발동 빈도 ──
    print("  ┌─ BT 브랜치 전체 발동 빈도 (시나리오별 합산)")
    grand_bc = {}
    grand_mc = {}
    for r in all_results.values():
        for b, c in r["branches"].items():
            grand_bc[b] = grand_bc.get(b, 0) + c
        for m, c in r["modes"].items():
            grand_mc[m] = grand_mc.get(m, 0) + c
    total_bc = sum(grand_bc.values())
    total_mc = sum(grand_mc.values())
    for b, c in sorted(grand_bc.items(), key=lambda x: -x[1]):
        print("  │  %-28s %4d틱 (%4.1f%%)" % (b, c, 100*c/total_bc))
    print("  ├─ HCCA 모드 발동 빈도")
    for m, c in sorted(grand_mc.items(), key=lambda x: -x[1]):
        print("  │  %-28s %4d틱 (%4.1f%%)" % (m, c, 100*c/total_mc))
    print("  └" + "─"*50)

    # ── 정책별 WR ──
    print("\n  ┌─ 적 정책별 WR")
    for pol in POLICIES:
        wins = sum(1 for (s, p), r in all_results.items() if p == pol and r["outcome"] == "WIN")
        total_p = len(SCENARIOS)
        print("  │  %-12s  %s  %d/%d (%.0f%%)" % (
            pol, POLICY_DESC[pol], wins, total_p, 100*wins/total_p))
    print("  ├─ 초기 배치별 WR")
    for sc_name in SCENARIOS:
        wins = sum(1 for (s, p), r in all_results.items() if s == sc_name and r["outcome"] == "WIN")
        total_s = len(POLICIES)
        min_d = min(r["min_dist"] for (s, p), r in all_results.items() if s == sc_name)
        print("  │  %-14s  %d/%d (%.0f%%)  최소거리=%.0fft" % (
            sc_name, wins, total_s, 100*wins/total_s, min_d))
    print("  └" + "─"*50)

    # ── 취약점 분석 ──
    losses = [(sc, pol, r) for (sc, pol), r in all_results.items() if r["outcome"] == "LOSS"]
    if losses:
        print("\n  ⚠ 패배 시나리오 분석:")
        for sc, pol, r in losses:
            final_log = r["log"][-1] if r["log"] else None
            if final_log:
                tick_f, ata, dist, cl, branch, mode, t_th, t_op = final_log[:8]
                print("    [%s × %s] %d틱: ATA=%.1f° dist=%.0fft cl=%+.0f → branch=%s mode=%s"
                      % (sc, pol, r["ticks"], ata, dist, cl, branch, mode))
        print()
        for sc, pol, r in losses:
            analyze_timeseries(sc, pol, r)
    else:
        print("\n  ✅ 패배 없음 — 모든 시나리오에서 WIN 또는 DRAW")

    draws = [(sc, pol, r) for (sc, pol), r in all_results.items() if r["outcome"] == "DRAW"]
    if draws:
        print("\n  ⚠ 무승부(60초 초과) 시나리오 — 개선 필요:")
        for sc, pol, r in draws:
            print("    [%s × %s] 최소거리=%.0fft, 주요 브랜치: %s"
                  % (sc, pol, r["min_dist"], fmt_branches(r["branches"])))
        print()
        for sc, pol, r in draws:
            analyze_timeseries(sc, pol, r)

    print("\n" + "="*110)
    print("  시뮬레이션 완료 — BT 주입 결과 검증 종료")
    print("="*110 + "\n")
