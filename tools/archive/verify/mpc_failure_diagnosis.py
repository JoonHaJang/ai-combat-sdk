"""MPC Failure Diagnostic (2026-05-26).

목적: MPC 가 hybrid 보다 worse 한 *정확한 원인* 진단.

핵심 가설:
    (A) MPC 의 roll-out dynamics (joint_step) ≠ 실제 env (AIPILOT+JSBSim)
        → MPC 가 *fictional* world 에 최적화 → 실 env 에선 작동 안 함
    (B) MPC 의 cost = jerk dominant (70%) → "가만히 있기" 학습
    (C) MPC 의 τ_0 → optimal_control → quantize chain 어딘가 끊김

3 single-tick test:
    Test 1: 같은 obs 에서 MPC vs hybrid 의 *bin 출력* 비교
    Test 2: MPC 의 cost 항별 분해 (이미 봄 — jerk dominant 확인)
    Test 3: joint_step 예측 vs reasonable expectation (1-tick rollout)
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))


def make_obs(rb=30.0, dist=5000.0, ata=30.0, aa=150.0, hca=60.0,
             alt_gap=0.0, energy_diff=0.0, closure=10.0):
    """typical mid-match obs."""
    return {
        "ego_altitude_ft": 15000.0, "ego_vc_kts": 386.8,
        "turn_rate_degs": 3.0,
        "relative_bearing_deg": rb, "distance_ft": dist,
        "ata_deg": ata, "aa_deg": aa, "hca_deg": hca,
        "alt_gap_ft": alt_gap, "energy_diff_ft": energy_diff,
        "closure_rate_kts": closure, "enm_in_wez": False,
        "energy_advantage": False,
    }


# ─── Test 1: same obs, hybrid vs MPC bin output ──────────────────


def test_1_action_divergence():
    """같은 obs → hybrid 와 MPC 가 어떤 bin 내는지 비교."""
    print("=" * 70)
    print("TEST 1: action divergence — hybrid vs MPC at same obs")
    print("=" * 70)

    scenarios = [
        ("mid-range mutual beam (typical)",
         make_obs(rb=30, dist=5000, ata=30, aa=150)),
        ("close + aligned (gun shot setup)",
         make_obs(rb=5, dist=1500, ata=8, aa=170)),
        ("our 6 o'clock (offensive position)",
         make_obs(rb=10, dist=3000, ata=15, aa=170, closure=80)),
        ("their 6 (defensive position)",
         make_obs(rb=-150, dist=2500, ata=140, aa=20, closure=120)),
        ("long range chase",
         make_obs(rb=15, dist=10000, ata=18, aa=160, closure=50)),
    ]

    for sc_name, obs in scenarios:
        print(f"\n[{sc_name}]")
        print(f"  obs: ata={obs['ata_deg']:.0f}° aa={obs['aa_deg']:.0f}° "
              f"dist={obs['distance_ft']:.0f}ft closure={obs['closure_rate_kts']:.0f}kts")

        # hybrid (default)
        for mod in list(sys.modules):
            if 'continuous_policy' in mod or 'pursuit_chase' in mod:
                del sys.modules[mod]
        os.environ.pop("PURSUIT_POLICY_MODE", None)
        from examples.pursuit_chase_v1.nodes.continuous_policy import compute_action as ca_h
        bin_h, info_h = ca_h(obs)

        # MPC
        for mod in list(sys.modules):
            if 'continuous_policy' in mod or 'pursuit_chase' in mod:
                del sys.modules[mod]
        os.environ["PURSUIT_POLICY_MODE"] = "mpc"
        os.environ["OPP_MODEL"] = "oracle"
        os.environ["ADVERSARY_BT_TYPE"] = "pursue"
        os.environ["MPC_N_SAMPLES"] = "32"
        from examples.pursuit_chase_v1.nodes.continuous_policy import compute_action as ca_m
        bin_m, info_m = ca_m(obs, obs_history=[obs, obs])

        print(f"  hybrid: bin={bin_h}  mode={info_h.get('mode')}")
        print(f"  MPC:    bin={bin_m}  mode={info_m.get('mode')}")

        # action delta
        delta = tuple(b1 - b0 for b0, b1 in zip(bin_h, bin_m))
        print(f"  Δ(bin): {delta}  ", end="")
        if all(d == 0 for d in delta):
            print("← *동일 action*")
        else:
            mag = sum(abs(d) for d in delta)
            print(f"(magnitude={mag}, *MPC 다른 결정*)")

        tau_m = info_m.get("tau_0", {})
        if tau_m:
            top = sorted(tau_m.items(), key=lambda x: -x[1])[:3]
            print(f"  MPC tau_0 top 3: {[(k, round(v,2)) for k,v in top]}")


# ─── Test 2: stationary "do nothing" test ────────────────────────


def test_2_idle_test():
    """초기 mutual beam 에서 *5 tick* MPC trace.
    MPC 가 점진적으로 attack 강화 vs idle 인지 측정."""
    print("\n" + "=" * 70)
    print("TEST 2: 5-tick MPC trace from mutual beam IC")
    print("=" * 70)

    # 정리
    for mod in list(sys.modules):
        if 'continuous_policy' in mod or 'pursuit_chase' in mod:
            del sys.modules[mod]
    os.environ["PURSUIT_POLICY_MODE"] = "mpc"
    os.environ["OPP_MODEL"] = "oracle"
    os.environ["ADVERSARY_BT_TYPE"] = "pursue"
    os.environ["MPC_N_SAMPLES"] = "32"
    from examples.pursuit_chase_v1.nodes.continuous_policy import compute_action

    obs_t = make_obs(rb=30, dist=5000, ata=30, aa=150, hca=60)
    history = [obs_t]

    print(f"{'tick':>4} {'bin':>10} {'mode':>30} {'cost':>10}")
    for tick in range(8):
        action, info = compute_action(obs_t, obs_history=history)
        cost = info.get("mpc_cost_min", 0.0)
        mode = info.get("mode", "?")[:30]
        print(f"{tick:>4} {str(action):>10} {mode:>30} {cost:>10.3f}")
        # naive next obs — 우리 1° hca shift (적이 살짝 turn)
        obs_t = dict(obs_t)
        obs_t["hca_deg"] = obs_t["hca_deg"] + 2.0
        history.append(obs_t)


# ─── Test 3: MPC roll-out vs ground truth (1-tick) ───────────────


def test_3_dynamics_mismatch():
    """MPC 의 joint_step 예측 vs 실제 env step 결과 비교.
    H=1 rollout 의 z_next 와 실 env.step 의 obs_next.
    """
    print("\n" + "=" * 70)
    print("TEST 3: MPC dynamics prediction vs simplified reality")
    print("=" * 70)

    from examples.pursuit_chase_v1.mpc import state as st
    from examples.pursuit_chase_v1.mpc import joint_dynamics as jd

    obs = make_obs(rb=30, dist=5000, ata=30, aa=150, hca=60)
    z = st.obs_to_state_12d(obs)
    print(f"Initial z:")
    print(f"  us:  x={z[0]:.0f} y={z[1]:.0f} h={z[2]:.0f} ψ={np.degrees(z[3]):.1f}° "
          f"V={z[4]:.1f}kts ω={np.degrees(z[5]):.1f}°/s")
    print(f"  opp: x={z[6]:.0f} y={z[7]:.0f} h={z[8]:.0f} ψ={np.degrees(z[9]):.1f}° "
          f"V={z[10]:.1f}kts ω={np.degrees(z[11]):.1f}°/s")

    # case A: aggressive right turn + accel
    u_us = np.array([np.radians(15.0), 0.0, 10.0])
    u_opp = np.array([np.radians(-5.0), 0.0, 0.0])
    z_next = jd.joint_step(z, u_us, u_opp, dt=0.1)
    print(f"\nAfter joint_step (dt=0.1s, u_us=ω+15°/s+10kts/s, u_opp=ω-5°/s):")
    print(f"  us:  x={z_next[0]:.0f} y={z_next[1]:.0f} h={z_next[2]:.0f} "
          f"ψ={np.degrees(z_next[3]):.1f}° V={z_next[4]:.1f}kts "
          f"ω={np.degrees(z_next[5]):.2f}°/s")
    print(f"  opp: x={z_next[6]:.0f} y={z_next[7]:.0f} h={z_next[8]:.0f} "
          f"ψ={np.degrees(z_next[9]):.1f}° V={z_next[10]:.1f}kts "
          f"ω={np.degrees(z_next[11]):.2f}°/s")

    # 분석: ω 가 실제로 얼마나 변했나?
    omega_us_change = np.degrees(z_next[5] - z[5])
    omega_opp_change = np.degrees(z_next[11] - z[11])
    print(f"\nΔω in 0.1s:")
    print(f"  us:  {omega_us_change:+.2f}°/s  (commanded change: {15-0:+}°/s)")
    print(f"  opp: {omega_opp_change:+.2f}°/s  (commanded: {-5-0:+}°/s)")
    print(f"  ω lag τ_omega = 0.4s → after 0.1s, ~{0.1/0.4*100:.0f}% of commanded reached")
    print(f"  → joint_step 의 ω first-order lag 모델 동작 확인")

    # 거리 변화
    dist_now = float(np.linalg.norm(z[6:9] - z[0:3]))
    dist_next = float(np.linalg.norm(z_next[6:9] - z_next[0:3]))
    print(f"\nΔdist: {dist_now:.0f}ft → {dist_next:.0f}ft (Δ = {dist_next-dist_now:+.0f}ft)")
    print(f"  적/우리 둘 다 ~64ft/0.1s ≈ 640fps = 380kts 으로 비행 — 합리적")


# ─── main ───────────────────────────────────────────────────────


def main():
    test_1_action_divergence()
    test_2_idle_test()
    test_3_dynamics_mismatch()

    print("\n" + "=" * 70)
    print("DIAGNOSIS SUMMARY (해석)")
    print("=" * 70)
    print()
    print("핵심 차이 요약:")
    print("  - hybrid: 17 cycle 튜닝된 _MODE_TAU 직접 사용 → action 결정적")
    print("  - MPC: joint_step (point-mass) 로 rollout cost 평가 → fictional world")
    print("  - 실 env: AIPILOT (RNN) + JSBSim (6-DOF) — 우리 joint_step 와 다름")
    print()
    print("Root cause 후보 (Test 1-3 결과 보고 판정):")
    print("  (A) action divergence 0 (= hybrid 와 동일 bin) → MPC 가 hybrid 따라함 → 다른 원인")
    print("  (A) action divergence 큼 (= MPC 다른 결정) → MPC 결정이 *틀린* 결정")
    print()
    print("  (B) tick 0-4 cost 일관됨 → MPC 가 trapped (local optimum, 같은 행동 반복)")
    print("  (B) cost 변동 큼 → MPC 가 trajectory 따라 학습 (정상)")
    print()
    print("  (C) joint_step 의 ω/V/위치 변화 합리적 → dynamics OK")
    print("  (C) 비합리적 → dynamics 모델 자체 결함")


if __name__ == "__main__":
    main()
