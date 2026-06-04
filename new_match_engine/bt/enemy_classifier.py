"""적 Tactic Classifier — obs(직접관측) → 적이 하는 Tactic 추정.

새 obs 덕분에 적 의도 100% 관측 가능 (RNN 시절 90% 재구성 → 직접):
  enm_phi (적 뱅크)    → 적 선회방향·강도
  enm_r   (적 yaw rate) → 적 선회율
  enm_vc, enm_alt 변화 → 적 가속/상승

적을 우리와 같은 13 Tactic 어휘로 분류 (대칭).
→ counter-matrix 의 입력. 추후 rollout 의 OppModel 입력.

★ 적 관점 obs 필요: compute_obs(enm, ego) = o21 (적이 공격자).
  enemy_classify(o21) = 적이 ego 에 대해 하는 tactic.
  단, 여기선 ego 관점 o12 의 enm_* 필드로 적 거동을 본다 (간편).
"""
from __future__ import annotations
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "control"))
from tactic import Tactic, WEZ_ATA_DEG, WEZ_MIN_FT, WEZ_MAX_FT

# 분류 임계값
TURN_BANK_DEG    = 15.0    # |enm_phi| > 이값 = 선회 중
HARD_BANK_DEG    = 45.0    # |enm_phi| > 이값 = 하드 선회
CLIMB_THETA_DEG  = 8.0     # 적 pitch > 이값 = 상승, < −이값 = 강하
ACCEL_VC_KTS     = 400.0   # 적 vc > 이값 = 가속/extend
DECEL_VC_KTS     = 280.0   # 적 vc < 이값 = 저속(corner/방어)


def _sign(x): return 1.0 if x >= 0.0 else -1.0


def enemy_classify(o, enm_theta_deg: float = 0.0) -> Tactic:
    """ego 관점 obs(o=o12) 의 enm_* 필드로 적 tactic 추정.

    o: engine/obs.py Observation (enm_phi_deg, enm_r_dps, enm_alt_ft, enm_vc_kts,
       그리고 우리-적 상대 ata/aa/dist/advantage).
    enm_theta_deg: 적 pitch (수직 판단용; obs에 없으면 0).

    ★ 적 관점 advantage = −o.advantage (우리가 +면 적은 −).
       적이 우리 6시면(우리 advantage 음) → 적은 공격 tactic.
    """
    enm_bank = o.enm_phi_deg          # 적 뱅크 (우+/좌−)
    enm_turn = o.enm_r_dps            # 적 선회율
    enm_adv  = -o.advantage           # 적 관점 우위 (우리 advantage 반대)
    turning  = abs(enm_bank) > TURN_BANK_DEG

    # 적이 우리를 WEZ 안에 두고 정렬? (적 공격 임박) — 적 ata 는 180−aa(우리)
    enm_ata = 180.0 - o.aa_deg        # 적 nose→우리 각도
    enm_in_wez = (enm_ata < WEZ_ATA_DEG and WEZ_MIN_FT <= o.distance_ft <= WEZ_MAX_FT)

    # ── 1. 적 공격 (적 우위) ─────────────────────────────────────────────
    if enm_in_wez:
        return Tactic.GUN_TRACK
    if enm_adv > 0.3:                  # 적이 우리 뒤 (공격)
        if turning:
            return Tactic.LAG_PURSUIT if abs(enm_bank) < HARD_BANK_DEG else Tactic.LEAD_PURSUIT
        return Tactic.PURE_PURSUIT

    # ── 2. 적 방어 (우리 우위 = 적 불리) ────────────────────────────────
    if enm_adv < -0.3:
        if abs(enm_bank) > HARD_BANK_DEG:
            return Tactic.BREAK_TURN    # 적 하드 선회 = 방어 break
        if o.enm_vc_kts > ACCEL_VC_KTS:
            return Tactic.EXTENSION     # 적 가속 이탈
        return Tactic.BREAK_TURN

    # ── 3. 중립: 선회전 / 직진 ──────────────────────────────────────────
    if turning:
        # 적 수직? (pitch 큼)
        if enm_theta_deg > CLIMB_THETA_DEG:
            return Tactic.HIGH_YOYO
        if enm_theta_deg < -CLIMB_THETA_DEG:
            return Tactic.LOW_YOYO
        # 적 선회 — corner speed(저속)면 rate fight, 아니면 angles
        if o.enm_vc_kts < DECEL_VC_KTS:
            return Tactic.TWO_CIRCLE    # 저속 하드선회 = rate fight
        return Tactic.ONE_CIRCLE
    # 적 직진
    if o.enm_vc_kts > ACCEL_VC_KTS:
        return Tactic.EXTENSION         # 가속 직진 = 이탈
    return Tactic.LEVEL_FLIGHT          # 등속 직진


def explain_enemy(o, enm_theta=0.0) -> str:
    t = enemy_classify(o, enm_theta)
    return (f"ENEMY:{t.name:18s} | enmBank={o.enm_phi_deg:+5.1f} enmR={o.enm_r_dps:+5.1f} "
            f"enmVc={o.enm_vc_kts:5.0f} enmAdv={-o.advantage:+.2f} dist={o.distance_ft:5.0f}")


if __name__ == "__main__":
    # 검증: 적을 알려진 tactic으로 돌리고 classifier가 맞추는지
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "engine"))
    from plant import F16Plant
    from lqr import GainScheduledLQR
    from autopilot import AutopilotConfig
    from obs import compute_obs, FT_PER_DEG_LAT
    from pilot import Pilot
    from collections import Counter

    print("=" * 70)
    print("  적 Tactic Classifier 검증 — 적을 알려진 tactic으로 → 맞추나?")
    print("=" * 70)
    gs = GainScheduledLQR([5000,15000,25000],[250,350,450]).build()

    def test(true_tactic, label):
        # ego(관측자) vs enm(알려진 tactic 수행)
        ego = F16Plant(); ego.set_ic(15000,350,psi_deg=0); ego.trim(); ego.step(5)
        enm = F16Plant(); enm.set_ic(15000,350,psi_deg=90)  # 적 측면
        enm["ic/long-gc-deg"]=3000/FT_PER_DEG_LAT; enm["ic/psi-true-deg"]=90
        enm.fdm.run_ic(); enm.trim(); enm.step(5)
        # 적 pilot: 알려진 tactic 수행. ego 는 직진(LEVEL).
        enm_pilot = Pilot(enm, gs, AutopilotConfig(KP_PSI=0.10), dt=0.05)
        ego_pilot = Pilot(ego, gs, AutopilotConfig(KP_PSI=0.10), dt=0.05)
        n=int(0.05/ego.dt); guesses=[]
        for t in range(200):  # 10s
            ue=ego_pilot.step(enm, tactic=Tactic.LEVEL_FLIGHT); ego.set_input(ue)
            un=enm_pilot.step(ego, tactic=true_tactic); enm.set_input(un)
            for _ in range(n): ego.step(1); enm.step(1)
            if t>40:  # 초기 transient 제외
                o12=compute_obs(ego,enm)
                enm_th = enm["attitude/theta-deg"]
                guesses.append(enemy_classify(o12, enm_th).name)
        top = Counter(guesses).most_common(2)
        print(f"  적={label:14s} → classifier 추정: {top}")

    test(Tactic.TWO_CIRCLE, "TWO_CIRCLE")
    test(Tactic.ONE_CIRCLE, "ONE_CIRCLE")
    test(Tactic.EXTENSION, "EXTENSION")
    test(Tactic.LEVEL_FLIGHT, "LEVEL_FLIGHT")
    test(Tactic.HIGH_YOYO, "HIGH_YOYO")
