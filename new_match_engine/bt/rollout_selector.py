"""Rollout Tactic Selector — 후보 tactic을 kinematic 시뮬 → 최적 선택.

새 엔진 superpower(예측-시뮬-선택). full JSBSim 포크는 느려서(plant생성~1s)
**kinematic 대리모델**로 빠르게 rollout (측정 transfer function 기반).

모델 (2D 수평, 측정값 사용):
  psi_dot = clamp(KP·wrap(psi*−psi), ±MAX_PSI_RATE=16°/s)   ← autopilot 일치
  v       → v* 로 가속/감속 (감속 가능 — 새 엔진)
  n,e     = ∫v·(cos psi, sin psi)
  적: 현재 선회율(enm_r) 외삽 = mode-persistence OppModel (라벨 불필요)

평가: horizon 동안 ∫(advantage + WEZ보너스) → 최고 tactic 선택.
→ "어느 tactic이 실제로 advantage/WEZ로 이어지나" 시뮬로 결정 (휴리스틱 아님).
"""
from __future__ import annotations
import sys, os, math
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "control"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "engine"))

from tactic import (Tactic, V_CORNER_KTS, V_MAX_KTS, WEZ_ATA_DEG, WEZ_MIN_FT, WEZ_MAX_FT)
from guidance import GuidanceLayer, Obs

KT_FPS = 1.6878098524
MAX_PSI_RATE = math.radians(16.0)   # autopilot 일치
KP_PSI = 0.10
ACCEL_KT_S = 8.0                    # 가속/감속률 (kts/s, 측정 근사)

# 후보 tactic (전수 13개는 과함 — 핵심 기동만)
CANDIDATES = [
    Tactic.PURE_PURSUIT, Tactic.LEAD_PURSUIT, Tactic.LAG_PURSUIT,
    Tactic.GUN_TRACK, Tactic.ONE_CIRCLE, Tactic.TWO_CIRCLE,
    Tactic.LAG_DISPLACEMENT_ROLL, Tactic.HIGH_YOYO, Tactic.LOW_YOYO,
    Tactic.BREAK_TURN, Tactic.EXTENSION,
]


def _wrap_pi(a): return (a + math.pi) % (2*math.pi) - math.pi


class _KState:
    """kinematic 2D 상태 (수평면). psi: rad, 0=north(+n). v: fps."""
    __slots__ = ("n", "e", "psi", "v")
    def __init__(self, n, e, psi, v):
        self.n=n; self.e=e; self.psi=psi; self.v=v


def _geom(us: _KState, op: _KState):
    """us·op → (dist_ft, ata_deg, aa_deg, rel_b_deg)."""
    dn, de = op.n - us.n, op.e - us.e
    dist = math.hypot(dn, de) + 1e-6
    # us velocity dir = psi (0=north). ata = angle(us_vel, los)
    los = math.atan2(de, dn)                    # bearing to enemy (0=north)
    ata = abs(math.degrees(_wrap_pi(los - us.psi)))
    # aa = angle(op_vel, los_from_us)  (op velocity vs ego→enm)
    aa = abs(math.degrees(_wrap_pi(los - op.psi)))   # op nose vs our position dir... 근사
    # 정확히는 aa = angle(op_vel, ego→enm). op_vel dir=op.psi. ego→enm dir=los. 일치식.
    rel_b = math.degrees(_wrap_pi(los - us.psi))
    return dist, ata, min(aa,180.0), rel_b


def _step(s: _KState, psi_star_rad, v_star_fps, dt):
    """kinematic 1-step."""
    err = _wrap_pi(psi_star_rad - s.psi)
    psi_rate = max(-MAX_PSI_RATE, min(MAX_PSI_RATE, KP_PSI * err / dt * 0.0 + _sat_rate(err)))
    s.psi = (s.psi + psi_rate * dt) % (2*math.pi)
    dv = max(-ACCEL_KT_S*KT_FPS*dt, min(ACCEL_KT_S*KT_FPS*dt, v_star_fps - s.v))
    s.v += dv
    s.n += s.v * math.cos(s.psi) * dt
    s.e += s.v * math.sin(s.psi) * dt


def _sat_rate(err_rad):
    """헤딩 오차 → 선회율 (P + 포화). autopilot 협조선회 근사."""
    rate = 0.7 * err_rad           # P 게인 (빠른 수렴)
    return max(-MAX_PSI_RATE, min(MAX_PSI_RATE, rate))


WEZ_MID_FT = 0.5 * (WEZ_MIN_FT + WEZ_MAX_FT)   # ~1750ft, WEZ 중심


def _shaped_score(dist, ata, aa):
    """BFM-correct step reward — long-game 승리 방향으로 shaping (P3 대응).

    승리 = 적 6시(aa↓) + nose-on(ata↓) + WEZ 거리. 순간 advantage만으론 blind.
    """
    adv = 1.0 - (ata + aa)/180.0                 # 각도 우위 [-1,+1]
    # 거리 closure: WEZ band 밖이면 다가갈수록 +, band 안이면 만점
    if dist > WEZ_MAX_FT:
        range_r = -(dist - WEZ_MAX_FT) / 8000.0  # 멀수록 penalty (다가가면↑)
    elif dist < WEZ_MIN_FT:
        range_r = -(WEZ_MIN_FT - dist) / 2000.0  # 너무 가까우면 약penalty(overshoot)
    else:
        range_r = 0.3                            # WEZ band = 보너스
    wez = 5.0 if (ata < WEZ_ATA_DEG and WEZ_MIN_FT <= dist <= WEZ_MAX_FT) else 0.0
    return adv + range_r + wez


def rollout_select(obs, horizon_s: float = 12.0, dt: float = 0.3) -> Tactic:
    """obs → 후보 tactic rollout → 최고 score tactic.

    obs: engine/obs.py Observation.
    horizon 12s: beam(90°)서 반전+추격 closure 가 보이는 길이 (P6 대응).
      6s 면 반전만 하다 끝 → EXTENSION 이 단기 각도로 이김(=도망). 12s 면 분리 dr러남.
      직진 적은 enm_r=0 외삽 완벽 → 긴 horizon 정확. 선회 적도 mode-persistence 가정.
    """
    gl = GuidanceLayer()
    # 현재 kinematic 상태 (us 기준 상대 — us at origin)
    us0 = _KState(0.0, 0.0, math.radians(obs.ego_psi_deg), obs.ego_vc_kts * KT_FPS)
    # 적 위치: dist·bearing (bearing = ego_psi + rel_b)
    br = math.radians(obs.ego_psi_deg + obs.rel_b_deg)
    op0 = _KState(obs.distance_ft*math.cos(br), obs.distance_ft*math.sin(br),
                  math.radians(obs.enm_psi_deg), obs.enm_vc_kts * KT_FPS)
    enm_r_rad = math.radians(obs.enm_r_dps)     # 적 선회율 외삽

    n_steps = int(horizon_s / dt)
    best_t, best_score = Tactic.PURE_PURSUIT, -1e9
    for tac in CANDIDATES:
        us = _KState(us0.n, us0.e, us0.psi, us0.v)
        op = _KState(op0.n, op0.e, op0.psi, op0.v)
        score = 0.0
        for k in range(n_steps):
            # us: guidance setpoint (현재 obs 기준 — 근사, 매 step 재계산은 비용↑)
            dist, ata, aa, rel_b = _geom(us, op)
            # 간이 obs 로 guidance 호출 (핵심 필드만)
            sp = _guidance_sp(gl, tac, obs, dist, ata, aa, rel_b)
            _step(us, math.radians(sp[0]), sp[1]*KT_FPS, dt)
            # 적: 선회율 외삽 (mode-persistence)
            op.psi = (op.psi + enm_r_rad * dt) % (2*math.pi)
            op.n += op.v*math.cos(op.psi)*dt; op.e += op.v*math.sin(op.psi)*dt
            # score: BFM-shaped (terminal 가중 — 후반 step일수록↑)
            w = 1.0 + 2.0 * (k / n_steps)        # terminal emphasis
            score += w * _shaped_score(dist, ata, aa)
        if score > best_score:
            best_score, best_t = score, tac
    return best_t


def _guidance_sp(gl, tac, obs, dist, ata, aa, rel_b):
    """예측 geometry 로 guidance setpoint (psi*, v*) 근사 계산."""
    # obs 복제 후 geometry 갱신 (간이)
    o = Obs(
        heading_deg=obs.ego_psi_deg, ego_altitude_ft=obs.ego_alt_ft, ego_vc_kts=obs.ego_vc_kts,
        ata_deg=ata, aa_deg=aa, rel_b=rel_b, closure_kts=0.0, distance_ft=dist,
        roll_deg=obs.ego_phi_deg, omega_opp_signed=obs.enm_r_dps,
        enm_altitude_ft=obs.enm_alt_ft, advantage=1.0-(ata+aa)/180.0, tau_s=dist/600.0,
    )
    sp = gl.compute(tac, o)
    return sp.psi_star_deg, sp.v_star_kts


if __name__ == "__main__":
    from run_nme import run_match           # 통합 러너 (300s, event log, replay)

    print("=" * 64)
    print("  Rollout selector 검증 — vs 직진 적, vs TWO_CIRCLE 적 (원본 동일조건)")
    print("=" * 64)
    for label, t2 in (("rollout_vs_straight", lambda o: Tactic.LEVEL_FLIGHT),
                      ("rollout_vs_twocircle", lambda o: Tactic.TWO_CIRCLE)):
        print(f"\n### {label} ###")
        run_match(lambda o: rollout_select(o), t2, label=label, hide_tactic=True)
