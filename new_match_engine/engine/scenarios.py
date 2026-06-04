"""교전 초기 spawn — 원본 bt_vs_bt config 정확 복제.

★ 모든 실험·매치는 이 spawn 사용 (원본과 동일해야 비교 가능).
출처: src/simulation/envs/JSBSim/configs/1v1/NoWeapon/bt_vs_bt.yaml (ADT Neutral start)

  A0100(Blue/us):  lon 119.991(서/9시), lat 60, alt 15000ft, psi 180(남향), u 600fps
  B0100(Red/opp):  lon 120.009(동/3시), lat 60, alt 15000ft, psi 0(북향),  u 600fps
  → 동서 ~3000ft 떨어져, 서로 90° beam, anti-parallel = 의도된 중립.

★ 속도는 ic_u_fps=600 (body-x, ~355kts TAS). vc-kts 아님 — 원본과 동일하게 u-fps 사용.
"""
from __future__ import annotations
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "control"))
from plant import F16Plant

# 원본 config 정확값
LAT0      = 60.0
LON_WEST  = 119.991   # A0100 (us) — 9시
LON_EAST  = 120.009   # B0100 (opp) — 3시
ALT_FT    = 15000.0
U_FPS     = 600.0     # body-x 속도 (~355 kts TAS)
PSI_US    = 180.0     # 남향
PSI_OPP   = 0.0       # 북향


def _spawn_one(lat, lon, psi, alt=ALT_FT, u_fps=U_FPS):
    p = F16Plant()
    f = p.fdm
    f["ic/lat-gc-deg"]   = lat
    f["ic/long-gc-deg"]  = lon
    f["ic/h-sl-ft"]      = alt
    f["ic/psi-true-deg"] = psi
    f["ic/u-fps"]        = u_fps     # ★ 원본과 동일 (vc 아님)
    f.run_ic()
    p.start_engines()                # 엔진 시동 (무동력 버그 방지)
    p.trim()
    p.step(5)
    return p


def spawn_adt_neutral():
    """원본 ADT Neutral start → (p1=us, p2=opp).

    90° beam, 3000ft, anti-parallel. 의도된 중립 시작.
    """
    p1 = _spawn_one(LAT0, LON_WEST, PSI_US)   # us, 서, 남향
    p2 = _spawn_one(LAT0, LON_EAST, PSI_OPP)  # opp, 동, 북향
    return p1, p2


# ── canonical BFM 상황 spawn (데이터 누적용 — 단순→복합) ────────────────────
#   FT_PER_DEG_LAT 로 거리(ft)→위도(deg) 변환. lat↑=북, lon↑=동.
from obs import FT_PER_DEG_LAT as _FPDL

def _lat_off(ft):  return ft / _FPDL
def _lon_off(ft):  return ft / (_FPDL * 0.5)   # lat60 cos≈0.5 보정 (경도거리)


def spawn_offensive(range_ft: float = 3000.0):
    """OFFENSIVE: 우리가 적 6시 뒤 range_ft, 둘 다 북향 → 우리 공격우위.

    us 뒤(남), opp 앞(북), 같은 방향(0°). advantage>0 기대.
    """
    p1 = _spawn_one(LAT0, 120.0, 0.0)                       # us, 북향
    p2 = _spawn_one(LAT0 + _lat_off(range_ft), 120.0, 0.0)  # opp, range_ft 앞(북), 북향
    return p1, p2


def spawn_defensive(range_ft: float = 3000.0):
    """DEFENSIVE: 적이 우리 6시 뒤 → 우리 피격위협. spawn_offensive 의 역."""
    p1 = _spawn_one(LAT0 + _lat_off(range_ft), 120.0, 0.0)  # us, 앞(북), 북향
    p2 = _spawn_one(LAT0, 120.0, 0.0)                       # opp, 뒤(남), 북향
    return p1, p2


def spawn_headon(range_ft: float = 6000.0):
    """NEUTRAL head-on: 정면 접근. us 남쪽 북향, opp 북쪽 남향 → merge."""
    p1 = _spawn_one(LAT0, 120.0, 0.0)                        # us, 남, 북향
    p2 = _spawn_one(LAT0 + _lat_off(range_ft), 120.0, 180.0) # opp, 북, 남향(마주봄)
    return p1, p2


# 상황 레지스트리 (matrix 실험용)
SITUATIONS = {
    "neutral_beam": spawn_adt_neutral,   # 원본 90° beam
    "offensive":    spawn_offensive,     # 적 6시 (우위)
    "defensive":    spawn_defensive,     # 우리 6시 피격 (열위)
    "headon":       spawn_headon,        # 정면 merge
}

import math as _math
_LON0 = 120.0


def spawn_param(range_ft=5000.0, los_deg=0.0, hca_deg=0.0,
                us_alt=15000.0, us_u=600.0, opp_alt=15000.0, opp_u=600.0):
    """파라미터화 spawn — BFM 상태공간 임의 기하 생성. us heading=북(0).

    range_ft: 거리. los_deg: 적 위치 방위(0=앞/북, 90=우, 180=뒤). hca_deg: 적 heading
      (=HCA, us 북향 기준; 0=정렬추격, 90=교차, 180=정면). us/opp alt·u: 에너지 변형.
    """
    us = _spawn_one(LAT0, _LON0, 0.0, us_alt, us_u)        # 우리 북향
    dlat = range_ft * _math.cos(_math.radians(los_deg)) / _FPDL
    dlon = range_ft * _math.sin(_math.radians(los_deg)) / (_FPDL * 0.5)  # cos(lat60)≈0.5
    opp = _spawn_one(LAT0 + dlat, _LON0 + dlon, hca_deg, opp_alt, opp_u)
    return us, opp


def diverse_spawns():
    """거리×방위×HCA×에너지 격자 → 다양 spawn dict (상태공간 체계 커버). ~108종."""
    out = {}
    for rng in (2500.0, 5000.0, 9000.0, 15000.0):
        for los in (0.0, 90.0, 180.0):                    # 적 앞/옆/뒤
            for hca in (0.0, 90.0, 180.0):                # 적 정렬/교차/정면
                for ealt, eu in ((15000.0, 600.0), (20000.0, 600.0), (11000.0, 720.0)):
                    nm = f"r{int(rng)}_los{int(los)}_hca{int(hca)}_a{int(ealt)}"
                    out[nm] = (lambda r=rng, l=los, h=hca, ea=ealt, eu_=eu:
                               spawn_param(r, l, h, opp_alt=ea, opp_u=eu_))
    return out


# 7-D 교전 파라미터 범위 (실제 1:1 dogfight 분해능 — 고르게 채움)
_SPAWN_RANGES = [
    (1500.0, 18000.0),   # range_ft  거리
    (0.0, 360.0),        # los_deg   적 위치 방위 (전방위)
    (0.0, 360.0),        # hca_deg   적 heading (전방위)
    (8000.0, 24000.0),   # us_alt
    (8000.0, 24000.0),   # opp_alt
    (470.0, 760.0),      # us_u  (fps, 에너지)
    (470.0, 760.0),      # opp_u
]

def diverse_spawns_sampled(n=64, seed=0):
    """★ Latin Hypercube(scipy) 로 7-D 교전공간 고르게 dense sampling → n 다양 spawn.
    격자보다 균일 커버. n↑ = 분해능↑ (실제 dogfight 상황 더 촘촘히)."""
    from scipy.stats import qmc
    u = qmc.LatinHypercube(d=len(_SPAWN_RANGES), seed=seed).random(n)
    out = {}
    for i, row in enumerate(u):
        v = [lo + (hi - lo) * x for x, (lo, hi) in zip(row, _SPAWN_RANGES)]
        rng, los, hca, ua, oa, uu, ou = v
        out[f"s{i:03d}"] = (lambda r=rng, l=los, h=hca, ua_=ua, oa_=oa, uu_=uu, ou_=ou:
                            spawn_param(r, l, h, ua_, uu_, oa_, ou_))
    return out


if __name__ == "__main__":
    # spawn 기하 검증 — 90° beam, 3000ft, 중립인가?
    from obs import compute_obs
    print("=" * 60)
    print("  ADT Neutral spawn 기하 검증 (원본 bt_vs_bt)")
    print("=" * 60)
    p1, p2 = spawn_adt_neutral()
    o12 = compute_obs(p1, p2)
    o21 = compute_obs(p2, p1)
    print(f"  거리        = {o12.distance_ft:.0f} ft   (기대 ~3000)")
    print(f"  us rel_b    = {o12.rel_b_deg:+.1f}°    (적 방위; beam이면 ±90)")
    print(f"  us ata      = {o12.ata_deg:.1f}°     (us nose→적)")
    print(f"  us aa       = {o12.aa_deg:.1f}°     (적 aspect)")
    print(f"  advantage   = {o12.advantage:+.2f}     (중립이면 ~0)")
    print(f"  us psi      = {o12.ego_psi_deg:.0f}°  (남향=180)")
    print(f"  opp psi     = {o21.ego_psi_deg:.0f}°  (북향=0)")
    print(f"  us vc       = {o12.ego_vc_kts:.0f} kts (u600fps 환산)")
    print(f"  us alt      = {o12.ego_alt_ft:.0f} ft")
