"""Tactic Selector — cost_branch_selector doctrine → Tactic enum (새 obs 기반).

cost_branch_selector.py 의 3-layer 우선순위 dispatch 를 새 엔진의 13 Tactic 으로 이식.
단 RNN 재구성값(omega_opp_signed 90%) 대신 **직접관측**(enm_phi/enm_r 100%) 사용.

우선순위 (cost_branch Framework B/C 순서):
  1. 안전 (Hard Deck)        ← ego_alt < 2500ft
  2. WEZ 진입 (공격 gun)      ← in_wez AND ata<12
  3. 방어 (적이 우리 6시)     ← aa<30 근접 위협
  4. 공격 포지션              ← advantage>0 (overshoot/lead/lag/pursuit)
  5. 중립 선회               ← one/two-circle (직접 bank 부호)
  6. 에너지 관리             ← yoyo (deficit/excess)
  7. 기본                    ← pure pursuit

단위·부호: [[new-match-engine-math-units]] 준수. obs = engine/obs.py Observation.
참조: cost_branch_selector.py doctrine (HOM/Defensive/Off_Lag/Lufbery/circle-fight 등).
"""
from __future__ import annotations
import sys, os, math
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "control"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "engine"))

from tactic import (
    Tactic, HARD_DECK_FT, WEZ_MIN_FT, WEZ_MAX_FT, WEZ_ATA_DEG,
)

# ── 임계값 (cost_branch_selector doctrine 에서 이식) ──────────────────────
HARD_DECK_BUFFER_FT = 1500.0   # F2: ego_alt < HARD_DECK + 1500 = 2500ft
DEF_AA_THRESH       = 40.0     # 적이 우리 6시: aa < 40° (적 nose 우리 향함)
DEF_CLOSURE_THRESH  = 80.0     # 방어 위협: closure > 80kts
DEF_DIST_THRESH     = 4000.0   # 방어 위협 거리
OVERSHOOT_CLOSURE   = 150.0    # overshoot: closure > 150kts (cost_branch 120~280)
GUN_ENTRY_ATA       = 20.0     # GUN_TRACK 진입 ata
ENERGY_DEFICIT_FT   = -600.0   # 에너지 결핍 (LOW_YOYO/EXTENSION)
ENERGY_EXCESS_KTS   = 420.0    # 에너지 과잉 (HIGH_YOYO)
EXTENSION_VC_KTS    = 250.0    # 에너지 고갈 이탈
CIRCLE_BANK_DEG     = 5.0      # 선회 판정 최소 bank (deadband=히스테리시스)
G_FT_S2             = 32.17404856
KT_FPS              = 1.6878098524


def _sign(x: float) -> float:
    return 1.0 if x >= 0.0 else -1.0


def _specific_energy_ft(alt_ft: float, vc_kts: float) -> float:
    """He = h + V²/2g (ft). V: kts→fps."""
    v_fps = vc_kts * KT_FPS
    return alt_ft + v_fps * v_fps / (2.0 * G_FT_S2)


def select_tactic(obs) -> Tactic:
    """Observation → Tactic. 우선순위 dispatch (첫 매치 win).

    obs: engine/obs.py Observation (필드 직접 접근).
    """
    o = obs
    # 파생값 (직접관측 기반)
    energy_diff = (_specific_energy_ft(o.ego_alt_ft, o.ego_vc_kts)
                   - _specific_energy_ft(o.enm_alt_ft, o.enm_vc_kts))   # +우리 우세
    in_wez = (o.ata_deg < WEZ_ATA_DEG
              and WEZ_MIN_FT <= o.distance_ft <= WEZ_MAX_FT)
    # 선회 방향 (직접 bank, 100%) — deadband 로 chatter 방지
    ego_turn = _sign(o.ego_phi_deg) if abs(o.ego_phi_deg) > CIRCLE_BANK_DEG else 0.0
    enm_turn = _sign(o.enm_phi_deg) if abs(o.enm_phi_deg) > CIRCLE_BANK_DEG else 0.0

    # ★ 공격/방어는 advantage([−1,+1])로 판별 (aa 부호 관례 함정 회피).
    #   advantage = 1−(ata+aa)/180.  +공격(적6시 nose-on) / −방어(우리6시 피격).
    #   ata: 우리 nose→적 (0=정렬). aa: 우리가 적 어디(0=적꼬리).

    # ── 1. 안전: Hard Deck (최우선) ──────────────────────────────────────
    if o.ego_alt_ft < HARD_DECK_FT + HARD_DECK_BUFFER_FT:
        return Tactic.HIGH_YOYO   # 상승 (고도 회복)

    # ── 2. WEZ 진입: 공격 gun (우리 nose 정렬 + 사거리) ─────────────────
    if in_wez:
        return Tactic.GUN_TRACK

    # ── 3. 방어: 적이 우리 6시 (advantage 음 = 불리) ───────────────────
    #   advantage<−0.3 = ata,aa 둘 다 큼 = 적이 우리 뒤+nose 우리향함.
    if o.advantage < -0.3:
        # 적이 접근 중(closure>0) + 근접 → 즉시 위협
        if o.closure_kts > DEF_CLOSURE_THRESH and o.distance_ft < DEF_DIST_THRESH:
            return Tactic.BREAK_TURN
        # 저에너지 → 이탈 회복
        if o.ego_vc_kts < EXTENSION_VC_KTS or energy_diff < ENERGY_DEFICIT_FT:
            return Tactic.EXTENSION
        return Tactic.BREAK_TURN

    # ── 4. 공격 포지션 (advantage > 0.3 = 우위) ────────────────────────
    if o.advantage > 0.3:
        # 4a. overshoot 임박 (근접 고속접근, 아직 미정렬) → lift-vector 이탈
        if o.closure_kts > OVERSHOOT_CLOSURE and o.distance_ft < 2000.0 and o.ata_deg > 20.0:
            return Tactic.LAG_DISPLACEMENT_ROLL
        # 4b. 근접+정렬 → 정밀 추적 (WEZ 직전)
        if o.ata_deg < GUN_ENTRY_ATA and o.distance_ft < WEZ_MAX_FT:
            return Tactic.GUN_TRACK
        # 4c. 강한 우위 → lag (선회전 유지·에너지 보존)
        if o.advantage > 0.6 and o.distance_ft < 5000.0:
            return Tactic.LAG_PURSUIT
        # 4d. 근접 → lead (조준 앞당김)
        if o.distance_ft < 6000.0 and o.ata_deg < 45.0:
            return Tactic.LEAD_PURSUIT
        # 4e. 원거리 → pure pursuit (직접 추격)
        return Tactic.PURE_PURSUIT

    # ── 5. 중립 (|advantage| ≤ 0.3): 선회전 / 추격 ─────────────────────
    #   ★ 적이 선회 중일 때만 circle fight. 직진 적은 추격(가속)해야 잡음.
    if enm_turn != 0.0:                        # 적이 선회 중 → 선회전
        if ego_turn != 0.0 and ego_turn != enm_turn:
            return Tactic.ONE_CIRCLE          # 반대 선회 = nose-to-nose
        return Tactic.TWO_CIRCLE              # 같은 선회 = nose-to-tail (out-rate)
    # 적 직진(enm_turn=0): merge 접근 중이면 일단 circle, 아니면 pursuit(가속)
    if o.closure_kts > 100.0 and o.distance_ft < 4000.0:
        return Tactic.ONE_CIRCLE              # 정면 고속 접근 = merge
    return Tactic.PURE_PURSUIT               # 직진 적 추격 (sprint 가속)

    # ── 6. 에너지 관리 (중립인데 에너지 불균형) ─────────────────────────
    if energy_diff < ENERGY_DEFICIT_FT or o.ego_vc_kts < EXTENSION_VC_KTS:
        return Tactic.LOW_YOYO                 # 결핍 → 강하 가속
    if o.ego_vc_kts > ENERGY_EXCESS_KTS:
        return Tactic.HIGH_YOYO                # 과잉 → 상승 감속

    # ── 7. 기본 ──────────────────────────────────────────────────────────
    return Tactic.PURE_PURSUIT


def explain(obs) -> str:
    """선택 근거 디버그 문자열."""
    t = select_tactic(obs)
    o = obs
    ediff = (_specific_energy_ft(o.ego_alt_ft, o.ego_vc_kts)
             - _specific_energy_ft(o.enm_alt_ft, o.enm_vc_kts))
    return (f"{t.name:18s} | adv={o.advantage:+.2f} ata={o.ata_deg:5.1f} aa={o.aa_deg:5.1f} "
            f"dist={o.distance_ft:5.0f} clos={o.closure_kts:+5.0f} "
            f"egoBank={o.ego_phi_deg:+5.1f} enmBank={o.enm_phi_deg:+5.1f} eDiff={ediff:+5.0f}")


if __name__ == "__main__":
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "engine"))
    from plant import F16Plant
    from obs import compute_obs, FT_PER_DEG_LAT

    print("=" * 70)
    print("  Tactic Selector — cost_branch doctrine 검증 (대표 상황)")
    print("=" * 70)

    def scen(name, ego_psi, enm_psi, north, east=0.0, ego_alt=15000, enm_alt=15000,
             ego_v=350, enm_v=350, ego_roll=0.0, enm_roll=0.0):
        e = F16Plant(); e.set_ic(ego_alt, ego_v, psi_deg=ego_psi); e.trim(); e.step(5)
        if abs(ego_roll) > 0.1:
            u=e.get_input(); u[2]=0.3*_sign(ego_roll); e.set_input(u)
            for _ in range(40): e.step(1)
        n = F16Plant(); n.set_ic(enm_alt, enm_v, psi_deg=enm_psi)
        n["ic/lat-gc-deg"]=north/FT_PER_DEG_LAT; n["ic/long-gc-deg"]=east/FT_PER_DEG_LAT
        n["ic/psi-true-deg"]=enm_psi; n.fdm.run_ic(); n.trim(); n.step(5)
        if abs(enm_roll) > 0.1:
            u=n.get_input(); u[2]=0.3*_sign(enm_roll); n.set_input(u)
            for _ in range(40): n.step(1)
        o = compute_obs(e, n)
        print(f"  {name:24s} → {explain(o)}")

    scen("적 6시 추격(공격)",      0,   0,  2000)            # 적 앞, 같은방향
    scen("적 정면 head-on",         0, 180,  3000)            # 마주봄
    scen("적이 우리 6시(방어)",     0, 180, -2500)            # 적 뒤에서 우리향함
    scen("WEZ 내 정렬",             0,   0,  1500)            # 근접 nose-on
    scen("저고도(hard deck)",       0,   0,  2000, ego_alt=2200)
    scen("저에너지",                0,   0,  3000, ego_v=240)
