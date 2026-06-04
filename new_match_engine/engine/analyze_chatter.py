"""Tactic chatter 분석 — 실측으로 dwell 필요성·값 결정.

시나리오: 적이 weave(좌우 교대 선회) → enm_r_dps 부호가 0 근처서 진동
          → suggest_tactic 의 ONE/TWO_CIRCLE 등 경계 전술이 떨리는지 측정.

측정: BT 10Hz 로 tactic 선택, 전환 횟수·최장 유지구간 집계.
비교: dwell 없음 vs dwell 0.3s vs 0.5s.
"""
from __future__ import annotations
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "control"))
import numpy as np

from plant import F16Plant
from lqr import GainScheduledLQR
from autopilot import Autopilot, AutopilotConfig
from guidance import GuidanceLayer, Obs, suggest_tactic
from tactic import Tactic
from obs import compute_obs, FT_PER_DEG_LAT


def run_scenario(dwell_s: float, gs, duration_s=20.0,
                 control_hz=20.0, bt_hz=10.0):
    """dwell_s 적용 시 tactic 전환 통계 반환."""
    # ego: 북향, 적: 정면 2500ft 근접 (중립 merge, 경계 상황)
    ego = F16Plant(); ego.set_ic(15000.0, 350.0, psi_deg=0.0); ego.trim(); ego.step(5)
    enm = F16Plant(); enm.set_ic(15000.0, 350.0, psi_deg=180.0)
    enm["ic/lat-gc-deg"] = 2500.0 / FT_PER_DEG_LAT
    enm["ic/psi-true-deg"] = 180.0
    enm.fdm.run_ic(); enm.trim(); enm.step(5)

    ap = Autopilot(ego, gs, AutopilotConfig(KP_PSI=0.08), dt=1.0/control_hz)
    gl = GuidanceLayer()

    dt_phys = ego.dt
    cdt = 1.0/control_hz
    n_sub = max(1, int(round(cdt/dt_phys)))
    bt_every = max(1, int(round(control_hz/bt_hz)))   # BT는 control 몇 틱마다
    max_ticks = int(round(duration_s/cdt))

    cur_tactic = Tactic.LEVEL_FLIGHT
    time_in_tactic = 0.0
    tactics_log = []      # 매 control tick 현재 tactic
    switches = 0

    # 적 weave: 2s 주기로 aileron 부호 교대
    import math
    for tick in range(max_ticks):
        t = tick * cdt
        o12 = compute_obs(ego, enm)

        # BT 결정 (bt_every 틱마다) + dwell 적용
        if tick % bt_every == 0:
            proposed = suggest_tactic(Obs.from_observation(o12))
            if proposed != cur_tactic and time_in_tactic >= dwell_s:
                cur_tactic = proposed
                time_in_tactic = 0.0
                switches += 1
            # else: dwell 미충족 → 현 tactic 유지
        time_in_tactic += cdt
        tactics_log.append(cur_tactic)

        # 제어
        sp = gl.compute(cur_tactic, o12)
        u = ap.step(sp)
        ego.set_input(u)

        # 적 weave 입력 (좌우 교대 ±0.25 aileron, 주기 2s)
        enm_u = enm.get_input()
        enm_u[2] = 0.25 * math.sin(2*math.pi*t/2.0)   # aileron weave
        enm.set_input(enm_u)

        for _ in range(n_sub):
            ego.step(1); enm.step(1)

    # 통계
    # 최장 유지 구간 (control tick 단위)
    runs = []
    cnt = 1
    for i in range(1, len(tactics_log)):
        if tactics_log[i] == tactics_log[i-1]:
            cnt += 1
        else:
            runs.append(cnt); cnt = 1
    runs.append(cnt)
    longest = max(runs) * cdt
    shortest = min(runs) * cdt
    n_distinct = len(set(tactics_log))

    return {
        "switches": switches,
        "switch_rate_hz": switches / duration_s,
        "longest_hold_s": longest,
        "shortest_hold_s": shortest,
        "n_distinct_tactics": n_distinct,
    }


if __name__ == "__main__":
    print("="*64)
    print("  Tactic chatter 분석 — 적 weave 중립 merge, 20s")
    print("="*64)
    gs = GainScheduledLQR([5000,15000,25000],[250,350,450]).build()

    print(f"\n[1] dwell sweep (BT 10Hz 고정)")
    print(f"{'dwell':>8} {'전환수':>7} {'전환율(Hz)':>11} {'최장유지(s)':>11} {'최단유지(s)':>11}")
    print("-"*54)
    for dwell in [0.0, 0.3, 0.5]:
        r = run_scenario(dwell, gs, bt_hz=10.0)
        print(f"{dwell:>7.1f}s {r['switches']:>7d} {r['switch_rate_hz']:>11.2f} "
              f"{r['longest_hold_s']:>11.2f} {r['shortest_hold_s']:>11.2f}")

    print(f"\n[2] BT hz sweep (dwell 0.3s 고정) — BT 빠르게 하면 이득?")
    print(f"{'bt_hz':>8} {'전환수':>7} {'전환율(Hz)':>11} {'최단유지(s)':>11} {'BT호출수':>9} {'BT시간(ms)':>10}")
    print("-"*64)
    import time as _time
    for bt_hz in [10.0, 20.0, 40.0]:
        r = run_scenario(0.3, gs, bt_hz=bt_hz)
        # BT 호출 비용 측정 (suggest_tactic 1만회)
        from guidance import Obs as _Obs, suggest_tactic as _st
        _o = compute_obs(
            *(lambda: (lambda e,n: (e,n))(
                (lambda p: (p.set_ic(15000,350),p.trim(),p.step(5),p)[-1])(F16Plant()),
                (lambda p: (p.set_ic(15000,350),p.trim(),p.step(5),p)[-1])(F16Plant())
            ))()
        )
        _go = _Obs.from_observation(_o)
        t0=_time.perf_counter()
        for _ in range(10000): _st(_go)
        bt_call_us = (_time.perf_counter()-t0)/10000*1e6
        n_bt_calls = int(20.0 * bt_hz)   # 20s × bt_hz
        bt_total_ms = n_bt_calls * bt_call_us / 1000
        print(f"{bt_hz:>7.0f}Hz {r['switches']:>7d} {r['switch_rate_hz']:>11.2f} "
              f"{r['shortest_hold_s']:>11.2f} {n_bt_calls:>9d} {bt_total_ms:>10.3f}")

    print("\n해석 기준:")
    print("  반응지연 = 1/bt_hz: 10Hz=100ms, 20Hz=50ms, 40Hz=25ms")
    print("  BFM 기동은 초 단위 → 100ms 지연 = 350kts에서 ~59ft 이동 (1000~3000ft 교전서 미미)")
    print("  BT hz↑ → 전환수 비슷/증가(이득無) + 연산 2~4배 (실제 cost_branch_selector는 더 무거움)")
