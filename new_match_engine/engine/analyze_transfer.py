"""BT → 엔진 → JSBSim 전달함수(transfer function) 측정.

목적: BT 고수준 명령이 실제 JSBSim 결과로 이어지는지 실측.
      특히 RNN §10 문제(감속불가·좌우비대칭)를 새 엔진이 고쳤는지 검증.

측정 항목:
  A. 좌/우 선회율 대칭     — RNN: 좌−13/우+10 비대칭. 새 엔진: 대칭이어야.
  B. 가속/감속 능력        — RNN: throttle 바닥, 감속불가. 새 엔진: 감속 가능해야.
  C. 상승/강하율           — setpoint Δh → 실제 climb rate.
  D. 선형성                — heading 명령 크기 → 응답 비례.

방법: setpoint 직접 명령 → 정상상태 응답 측정 (§10 probe 와 동일 철학).
단위: 선회율 °/s, 속도 kts, 고도율 ft/s.
"""
from __future__ import annotations
import sys, os, math
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "control"))
import numpy as np

from plant import F16Plant
from lqr import GainScheduledLQR
from autopilot import Autopilot, AutopilotConfig, RAD_TO_DEG, FT_S_TO_KNOT, _iPSI, _iH, _iV
from guidance import Setpoint

CTRL_HZ = 20.0
CDT = 1.0 / CTRL_HZ


def _new(gs, cfg=None):
    p = F16Plant(); p.set_ic(15000.0, 350.0, psi_deg=90.0); p.trim(); p.step(5)
    ap = Autopilot(p, gs, cfg or AutopilotConfig(KP_PSI=0.08), dt=CDT)
    return p, ap


def _run(p, ap, sp, secs):
    """sp 명령으로 secs초 비행, (heading열, alt열, vc열) 반환."""
    n = max(1, int(round(CDT / p.dt)))
    psis, alts, vcs = [], [], []
    for _ in range(int(secs / CDT)):
        u = ap.step(sp); p.set_input(u)
        for _ in range(n): p.step(1)
        x = p.get_state()
        psis.append(x[_iPSI] * RAD_TO_DEG % 360.0)
        alts.append(x[_iH])
        vcs.append(x[_iV] * FT_S_TO_KNOT)   # TAS kts (rate 측정용)
    return np.array(psis), np.array(alts), np.array(vcs)


def _turn_rate(psis):
    """unwrap heading → 정상상태 선회율(°/s) 중앙값."""
    u = np.degrees(np.unwrap(np.radians(psis)))
    rate = np.diff(u) / CDT
    # 정상상태 구간 (초반 banking 제외): 2~8초 구간
    i0, i1 = int(2.0/CDT), int(8.0/CDT)
    seg = rate[i0:i1]
    return np.median(seg) if len(seg) else 0.0


if __name__ == "__main__":
    print("=" * 66)
    print("  BT → 엔진 → JSBSim 전달함수 측정 (RNN §10 비교)")
    print("=" * 66)
    gs = GainScheduledLQR([5000,15000,25000],[250,350,450]).build()

    # ── A. 좌/우 선회율 대칭 ─────────────────────────────────────────────
    print("\n[A] 좌/우 선회율 대칭 (RNN: 좌−13/우+10 비대칭)")
    p, ap = _new(gs); psi0 = p.get_state()[_iPSI]*RAD_TO_DEG%360.0
    # 우선회: heading +150° 명령 (saturating)
    psis_r,_,_ = _run(p, ap, Setpoint((psi0+150)%360, 15000.0, 350.0), 10.0)
    rate_r = _turn_rate(psis_r)
    p, ap = _new(gs); psi0 = p.get_state()[_iPSI]*RAD_TO_DEG%360.0
    psis_l,_,_ = _run(p, ap, Setpoint((psi0-150)%360, 15000.0, 350.0), 10.0)
    rate_l = _turn_rate(psis_l)
    asym = abs(abs(rate_r) - abs(rate_l)) / max(abs(rate_r), abs(rate_l), 1e-9) * 100
    print(f"  우선회율 = {rate_r:+.2f} °/s")
    print(f"  좌선회율 = {rate_l:+.2f} °/s")
    print(f"  비대칭도 = {asym:.1f}%   {'✅ 대칭' if asym < 10 else '❌ 비대칭'} "
          f"(RNN 은 ~30% 비대칭)")

    # ── B. 가속/감속 능력 ────────────────────────────────────────────────
    print("\n[B] 가속/감속 능력 (RNN: throttle 바닥, 감속불가)")
    print(f"  {'명령 v*':>10} {'30s후 vc':>10} {'변화':>8}")
    for v_star in [250.0, 300.0, 350.0, 400.0, 420.0]:
        p, ap = _new(gs)
        _,_,vcs = _run(p, ap, Setpoint(90.0, 15000.0, v_star), 30.0)
        vc_final = vcs[-1]
        vc0 = vcs[0]
        print(f"  {v_star:>9.0f}k {vc_final:>9.1f}k {vc_final-vc0:>+7.1f}k")
    print("  → v* 낮추면 vc 감소 = 감속 가능 (RNN 불가능했던 것)")

    # ── C. 상승/강하율 ───────────────────────────────────────────────────
    print("\n[C] 상승/강하율 (setpoint Δh → climb rate)")
    print(f"  {'명령 Δh':>10} {'climb rate':>12}")
    for dh in [+3000.0, +1500.0, -1500.0, -3000.0]:
        p, ap = _new(gs)
        _,alts,_ = _run(p, ap, Setpoint(90.0, 15000.0+dh, 350.0), 10.0)
        # 초반 2~6초 평균 상승률
        i0,i1 = int(2.0/CDT), int(6.0/CDT)
        rate = (alts[i1]-alts[i0])/((i1-i0)*CDT)
        print(f"  {dh:>+9.0f}ft {rate:>+9.1f} ft/s")
    print("  → Δh 부호대로 상승/강하 (수직 기동 가능)")

    # ── D. 선형성 (heading 명령 → 정착 시간) ────────────────────────────
    print("\n[D] heading 명령 크기 → 응답 (선형성)")
    print(f"  {'명령 Δψ':>10} {'10s후 오차':>12}")
    for dpsi in [10.0, 30.0, 60.0, 90.0]:
        p, ap = _new(gs); psi0 = p.get_state()[_iPSI]*RAD_TO_DEG%360.0
        psis,_,_ = _run(p, ap, Setpoint((psi0+dpsi)%360, 15000.0, 350.0), 10.0)
        # 최종 heading 오차
        err = ((psis[-1] - (psi0+dpsi)%360 + 180) % 360) - 180
        print(f"  {dpsi:>+9.0f}° {err:>+9.1f}°")
    print("  → 작은 명령 빨리 정착, 큰 명령은 선회율 한계(±MAX_PSI_RATE)로 시간↑")
