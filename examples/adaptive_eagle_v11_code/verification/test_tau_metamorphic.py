"""
test_tau_metamorphic.py — τ 함수 Metamorphic Relations (Phase A 검증).

각 τ 함수가 BFM 정리(Boyd, Shaw, Pontryagin)의 entry condition과 일치하는지를
metamorphic relations(MR)로 검증. Oracle (정답) 없이도 입력↔출력 변환 관계로
정합성 확인 가능.

Reference:
    - VERIFICATION_METHODOLOGY.md §2.4
    - Chen et al (2018) "Metamorphic Testing: A Review of Challenges
      and Opportunities", ACM Computing Surveys.

실행:
    cd examples/adaptive_eagle_v11_code/verification
    python -m pytest test_tau_metamorphic.py -v

또는 standalone:
    python test_tau_metamorphic.py
"""

from __future__ import annotations

import math
import os
import sys

# parent (sim_dogfight_verify가 있는 폴더) import path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# pytest는 선택적 — 없으면 main()이 standalone 실행
try:
    import pytest
    HAS_PYTEST = True
except ImportError:
    HAS_PYTEST = False
    # pytest.mark.parametrize 호환 stub
    class _ParametrizeStub:
        def parametrize(self, names, values):
            def decorator(func):
                func._parametrize = (names, values)
                return func
            return decorator
    class _MarkStub:
        parametrize = _ParametrizeStub().parametrize
    class _PytestStub:
        mark = _MarkStub()
    pytest = _PytestStub()

from sim_dogfight_verify import tau_corner, tau_yoyo, tau_ldt


# ─── Helper — obs dict 생성기 ───────────────────────────────────────────

def make_obs(*,
             hca_deg=180.0,
             ego_vc_kts=386.8,
             turn_rate_degs=15.0,
             ata_deg=90.0,
             aa_deg=90.0,
             distance_ft=3297.6,
             closure_rate_kts=0.0,
             alt_gap_ft=0.0,
             relative_bearing_deg=90.0,
             tau_deg=0.5,
             ps_fts=0.0,
             # 사용 안 되는 필드 default
             energy_diff_ft=0.0,
             ego_altitude_ft=15000.0,
             in_wez=False,
             enm_in_wez=False,
             alt_advantage=False,
             energy_advantage=False,
             overshoot_risk=False,
             tc_type="2-circle",
             in_39_line=False,
             ata_lead_deg=0.5,
             turn_radius_ft=2000.0,
             corner_margin_kts=36.8):
    """sim_dogfight_verify.build_obs 가 만드는 dict 형식과 동일.

    각도 필드는 [0, 1] 정규화 (실제 / 180.0).
    """
    return {
        "hca_deg":         hca_deg / 180.0,
        "ego_vc_kts":      ego_vc_kts,
        "turn_rate_degs":  turn_rate_degs,
        "ata_deg":         ata_deg / 180.0,
        "aa_deg":          aa_deg / 180.0,
        "distance_ft":     distance_ft,
        "closure_rate_kts":closure_rate_kts,
        "alt_gap_ft":      alt_gap_ft,
        "relative_bearing_deg": relative_bearing_deg / 180.0,
        "tau_deg":         tau_deg,
        "ps_fts":          ps_fts,
        "energy_diff_ft":  energy_diff_ft,
        "ego_altitude_ft": ego_altitude_ft,
        "in_wez":          in_wez,
        "enm_in_wez":      enm_in_wez,
        "alt_advantage":   alt_advantage,
        "energy_advantage":energy_advantage,
        "overshoot_risk":  overshoot_risk,
        "tc_type":         tc_type,
        "in_39_line":      in_39_line,
        "ata_lead_deg":    ata_lead_deg,
        "turn_radius_ft":  turn_radius_ft,
        "corner_margin_kts": corner_margin_kts,
    }


# ════════════════════════════════════════════════════════════════════════
# τ_corner — 정리 5+6 (Boyd Ps + Shaw 2-circle)
# 발동: HCA>120 ∧ V>V_corner ∧ active turning
# ════════════════════════════════════════════════════════════════════════

class TestTauCorner:
    """정리 5+6 entry condition 검증."""

    # ── Range ─────────────────────────────────────────
    def test_range(self):
        """MR-C0: τ_corner ∈ [0, 1]."""
        for hca in [0, 50, 90, 120, 150, 180]:
            for v in [200, 350, 387, 420]:
                for tr in [0, 10, 21]:
                    obs = make_obs(hca_deg=hca, ego_vc_kts=v, turn_rate_degs=tr)
                    val = tau_corner(obs, None)
                    assert 0.0 <= val <= 1.0, f"out of range: {val}"

    # ── HCA monotonicity (정리 6) ──────────────────────
    @pytest.mark.parametrize("hca_low,hca_high", [
        (90, 120), (100, 140), (120, 160), (140, 180),
    ])
    def test_hca_monotone_increasing(self, hca_low, hca_high):
        """MR-C1: HCA ↑ → τ_corner ↑ (다른 변수 고정).

        근거: 정리 6 — HCA가 클수록 2-circle fight ⇒ ω_max 우위 가치 ↑.
        """
        common = dict(ego_vc_kts=387, turn_rate_degs=15, ata_deg=90)
        obs_lo = make_obs(hca_deg=hca_low, **common)
        obs_hi = make_obs(hca_deg=hca_high, **common)
        assert tau_corner(obs_hi, None) >= tau_corner(obs_lo, None) - 1e-9, \
            f"HCA ↑ but τ_corner ↓: {tau_corner(obs_lo, None)} → {tau_corner(obs_hi, None)}"

    # ── V monotonicity above corner ────────────────────
    @pytest.mark.parametrize("v_low,v_high", [
        (360, 380), (380, 400), (400, 420),
    ])
    def test_v_above_corner_monotone(self, v_low, v_high):
        """MR-C2: V_corner 위에서 V ↑ → τ_corner ↑.

        근거: 정리 5 — 코너 위에서 더 빠를수록 코너로 brake할 가치 ↑.
        """
        common = dict(hca_deg=180, turn_rate_degs=15)
        obs_lo = make_obs(ego_vc_kts=v_low, **common)
        obs_hi = make_obs(ego_vc_kts=v_high, **common)
        assert tau_corner(obs_hi, None) >= tau_corner(obs_lo, None) - 1e-9

    # ── V below corner → τ_corner 작음 ─────────────────
    @pytest.mark.parametrize("v", [200, 250, 300, 340])
    def test_below_corner_low_tau(self, v):
        """MR-C3: V < V_corner−15 → τ_corner < 0.5.

        근거: 코너 아래에 이미 있으면 brake할 이유 없음.
        """
        obs = make_obs(hca_deg=180, ego_vc_kts=v, turn_rate_degs=15)
        assert tau_corner(obs, None) < 0.5, \
            f"V={v}<corner이지만 τ_corner={tau_corner(obs, None):.3f}≥0.5"

    # ── 능동 turning 부재 → τ_corner 낮음 ──────────────
    def test_inactive_low_tau(self):
        """MR-C4: 양쪽 모두 직선(turn=0, hca_rate=0) → τ_corner 낮음.

        근거: 능동 선회전 아님 ⇒ corner 가치 없음.
        """
        obs_now = make_obs(hca_deg=180, ego_vc_kts=387, turn_rate_degs=0)
        obs_prev = make_obs(hca_deg=180, ego_vc_kts=387, turn_rate_degs=0)
        val = tau_corner(obs_now, obs_prev)
        assert val < 0.5, f"비능동인데 τ_corner={val:.3f}≥0.5"

    # ── 정리 6 spec 정확 — 양쪽 regime + 양쪽 turning 일 때만 ─
    # 정리 6 (Shaw) entry condition: 양쪽 능동 turning fight 시
    #   - 1-circle (HCA<90): R_min 우위
    #   - 2-circle (HCA>120): ω_max 우위
    #   - 중간 (90~120): regime 모호
    # passive 적 (직선) 시 정리 6 미적용 — 정리 1 Bernoulli 영역.

    @pytest.mark.parametrize("hca", [0, 30, 60, 75])
    def test_low_hca_active_both(self, hca):
        """MR-C5a: HCA<90 (1-circle) + 양쪽 능동 turning → τ_corner > 0.3.

        spec: 정리 6 1-circle regime entry — 양쪽이 turning 중일 때 작은 R 우세.
        obs_prev 사용해 적도 turning 중인 상태 명시 (HCA rate 가짐).
        """
        obs_prev = make_obs(hca_deg=hca + 4, ego_vc_kts=387, turn_rate_degs=15)
        obs_now  = make_obs(hca_deg=hca,     ego_vc_kts=387, turn_rate_degs=15)
        # HCA 변화 = 4°/0.2s = 20°/s. 우리 turn 15°/s 빼면 적 ω ≈ 5°/s (active)
        val = tau_corner(obs_now, obs_prev)
        assert val > 0.3, f"1-circle HCA={hca}, 양쪽 turning, τ_corner={val:.3f} < 0.3"

    @pytest.mark.parametrize("hca", [95, 105, 115])
    def test_head_on_transition_low(self, hca):
        """MR-C5b: HCA 90~120 (head-on 변이) → τ_corner 약함 (<0.5).

        regime 모호 영역. 양쪽 turning 가정해도 max(s_2c, s_1c) 둘 다 ~0.5.
        """
        obs_prev = make_obs(hca_deg=hca + 4, ego_vc_kts=387, turn_rate_degs=15)
        obs_now  = make_obs(hca_deg=hca,     ego_vc_kts=387, turn_rate_degs=15)
        val = tau_corner(obs_now, obs_prev)
        assert val < 0.5, f"transition HCA={hca}, τ_corner={val:.3f} ≥ 0.5"

    def test_passive_enemy_low(self):
        """MR-C5c: 적이 turning 안 하면 (passive) → τ_corner 낮음 (<0.3).

        spec: 정리 6 entry condition 위반. 적 직선 비행은 정리 1 (Bernoulli)
        영역. obs_prev=None → enemy_omega_est=0 → s_them 약함.
        """
        # 우리만 turning, HCA 일정 (적 turning X)
        obs_prev = make_obs(hca_deg=180, ego_vc_kts=387, turn_rate_degs=15)
        obs_now  = make_obs(hca_deg=180, ego_vc_kts=387, turn_rate_degs=15)
        val = tau_corner(obs_now, obs_prev)
        assert val < 0.3, f"적 passive, τ_corner={val:.3f} ≥ 0.3 (정리 6 spec 위반)"

    # ── Sign-symmetric in turn_rate ────────────────────
    def test_turn_rate_sign_symmetric(self):
        """MR-C6: τ_corner 는 |turn_rate|에만 의존, 부호 무관.

        근거: abs() 명시 — 좌·우 선회 차이 없어야.
        """
        obs_left  = make_obs(turn_rate_degs=+15)
        obs_right = make_obs(turn_rate_degs=-15)
        assert abs(tau_corner(obs_left, None) - tau_corner(obs_right, None)) < 1e-9


# ════════════════════════════════════════════════════════════════════════
# τ_yoyo — 정리 8 (Pontryagin 수직 BFM) + orbit-lock 확장
# 발동: (closure>0 chase) OR (HCA>120 ∧ |closure|<50 lock)
# ════════════════════════════════════════════════════════════════════════

class TestTauYoyo:
    """정리 8 + orbit-lock entry condition 검증."""

    def test_range(self):
        for cl in [-200, 0, 200]:
            for hca in [0, 90, 180]:
                for ata in [0, 90, 180]:
                    obs = make_obs(closure_rate_kts=cl, hca_deg=hca, ata_deg=ata)
                    val = tau_yoyo(obs, None)
                    assert 0.0 <= val <= 1.0

    # ── ATA gauss peak at 70° (design regression) ─────
    def test_ata_peak_around_70(self):
        """MR-Y1 [DESIGN-REGRESSION]: ATA 70° 근처에서 최대값.

        ⚠️ 이건 정리 8(Pontryagin)에서 직접 도출된 spec이 아니라 **현재 구현의
        설계 선택값** (gauss μ=70°)에 대한 회귀 테스트. 정리 8은 "medium ATA"
        라고만 명시. 최적 peak 위치는 enemy alt-track τ + 수직 dynamics에 의존.
        """
        common = dict(closure_rate_kts=80, hca_deg=180)
        peak = tau_yoyo(make_obs(ata_deg=70, **common), None)
        for off in [30, 50, 110, 150, 180]:
            other = tau_yoyo(make_obs(ata_deg=off, **common), None)
            assert peak >= other - 1e-9, \
                f"ATA=70 should peak vs {off}: {peak} vs {other}"

    # ── 정리 8 영역별 monotonicity ─────────────────────
    # τ_yoyo = max(s_chase, s_lock) · gauss(ATA)
    # 두 영역 별 monotone: chase 영역 (cl 큼) 은 cl↑→τ↑, lock 영역 (|cl| 작음)
    # 은 |cl|↑→τ↓. 두 영역 사이 (cl≈30) 는 비단조 — 정리 8 spec 의 자연스러움.

    @pytest.mark.parametrize("cl_lo,cl_hi", [(30, 80), (80, 150), (150, 250)])
    def test_chase_domain_monotone(self, cl_lo, cl_hi):
        """MR-Y2a: chase 영역 (cl>30) 에서 closure ↑ → τ_yoyo ↑."""
        common = dict(ata_deg=70)
        obs_lo = make_obs(closure_rate_kts=cl_lo, **common)
        obs_hi = make_obs(closure_rate_kts=cl_hi, **common)
        assert tau_yoyo(obs_hi, None) >= tau_yoyo(obs_lo, None) - 1e-9

    @pytest.mark.parametrize("cl_small,cl_large", [(0, 20), (10, 30), (20, 40)])
    def test_lock_domain_monotone(self, cl_small, cl_large):
        """MR-Y2b: lock 영역 (|cl|<50) 에서 |cl| ↑ → τ_yoyo ↓ (lock 약화)."""
        common = dict(ata_deg=70)
        obs_small = make_obs(closure_rate_kts=cl_small, **common)
        obs_large = make_obs(closure_rate_kts=cl_large, **common)
        v_small = tau_yoyo(obs_small, None)
        v_large = tau_yoyo(obs_large, None)
        assert v_small >= v_large - 1e-9, f"|cl|↑이면 lock↓: {v_small} >= {v_large}"

    # ── lock mode: closure 작음 + ATA 중간 → τ_yoyo 활성 (HCA 무관, 정리 8) ──
    @pytest.mark.parametrize("hca", [60, 90, 120, 180])
    def test_lock_mode_activation(self, hca):
        """MR-Y3: |closure|<50 + ATA 중간 → engagement-lock 활성 (HCA 무관).

        ⚠️ 정정 (이전 spec 결함): 이전 구현은 HCA>120 조건을 추가했으나 정리 8
        (Pontryagin 수직 BFM) 에는 HCA 조건 없음. 1-circle (HCA<90) dual-PN
        orbit 에서도 lock + ATA 중간 시 yo-yo 가치 있음.
        """
        obs = make_obs(hca_deg=hca, closure_rate_kts=0, ata_deg=80)
        val = tau_yoyo(obs, None)
        assert val >= 0.3, f"lock(HCA={hca}, cl=0, ATA=80), τ_yoyo={val:.3f}<0.3"

    # ── 비활성 — 능동 closure 음수 + HCA 작음 ───────────
    def test_diverging_low_hca_low_tau(self):
        """MR-Y4: 적이 도망 + HCA<90 → τ_yoyo 매우 낮음 (<0.1).

        Spec 강화 (이전 0.3 → 0.1): 정리 8은 closure>0 또는 orbit-lock 둘 다
        해당 안되는 경우 τ_yoyo 가 명확히 비활성이어야 함. 0.3 은 너무 느슨.
        """
        obs = make_obs(hca_deg=30, closure_rate_kts=-150, ata_deg=70)
        val = tau_yoyo(obs, None)
        assert val < 0.1, f"비활성 상황 τ_yoyo={val:.3f}≥0.1"

    # ── ATA 양 극단 (0°, 180°) → τ_yoyo 작음 ──────────
    @pytest.mark.parametrize("ata", [0, 5, 175, 180])
    def test_extreme_ata_low(self, ata):
        """MR-Y5: ATA가 0° 또는 180°면 yo-yo 적용 영역 아님."""
        obs = make_obs(ata_deg=ata, closure_rate_kts=80, hca_deg=180)
        val = tau_yoyo(obs, None)
        # gauss(ata=0, μ=70, σ=30) ≈ exp(-2.72) ≈ 0.066, gauss(180, 70, 30) ≈ 0.0096
        # max term은 chase or lock — 둘 다 약 0.7 수준 가능 → τ ≤ 0.7×0.066 = 0.046
        assert val < 0.1, f"극단 ATA={ata}인데 τ_yoyo={val:.3f}≥0.1"


# ════════════════════════════════════════════════════════════════════════
# τ_ldt — 정리 7 (Shaw Lag Displacement Turn)
# 발동: ATA ~65 ∧ dist>3000 ∧ |LOS_rate|>8
# ════════════════════════════════════════════════════════════════════════

class TestTauLdt:
    """정리 7 entry condition 검증."""

    def test_range(self):
        for ata in [0, 65, 130, 180]:
            for dist in [1000, 3000, 5000, 10000]:
                for rb in [0, 45, 90, 135]:
                    obs_now = make_obs(ata_deg=ata, distance_ft=dist, relative_bearing_deg=rb)
                    obs_prev = make_obs(ata_deg=ata, distance_ft=dist,
                                        relative_bearing_deg=rb - 5)
                    val = tau_ldt(obs_now, obs_prev)
                    assert 0.0 <= val <= 1.0

    # ── ATA peak at 65° (design regression) ────────────
    def test_ata_peak_around_65(self):
        """MR-L1 [DESIGN-REGRESSION]: ATA 65° 근처 peak.

        ⚠️ 정리 7(Shaw LDT)에서 직접 도출된 spec이 아니라 현재 구현의
        설계 선택값 (gauss μ=65°). Shaw는 "lag pursuit 영역" 만 명시.
        """
        # LOS rate를 충분히 큰 상태로 고정
        prev_rb = 70.0
        common = dict(distance_ft=4000, relative_bearing_deg=80.0)
        obs_prev = make_obs(relative_bearing_deg=prev_rb, distance_ft=4000)
        peak = tau_ldt(make_obs(ata_deg=65, **common), obs_prev)
        for off in [10, 30, 100, 130, 170]:
            other = tau_ldt(make_obs(ata_deg=off, **common), obs_prev)
            assert peak >= other - 1e-9, f"peak at 65 vs {off}: {peak} vs {other}"

    # ── MR-L2: 거리 짧으면 τ_ldt 작음 — 정리 7 (Shaw LDT) ────
    # 정리 7 spec: Phase 1→2 전환 조건은 dist·sin(ATA) ≥ R·√2.
    # 본 테스트의 케이스 (ATA=65°, R≈2100ft @ 387kts):
    #   threshold = R·√2 ≈ 2970ft
    #   - dist=500:  displacement = 500·sin(65°) = 453ft   << 2970 → 비활성
    #   - dist=1500: displacement = 1500·sin(65°) = 1359ft << 2970 → 비활성
    #   - dist=2500: displacement = 2500·sin(65°) = 2266ft < 2970  → 비활성 (still below)
    # 따라서 이 세 dist 모두에서 τ_ldt 가 <0.4 여야 정리 7 spec 일치.
    @pytest.mark.parametrize("dist", [500, 1500, 2500])
    def test_short_distance_low(self, dist):
        """MR-L2: dist·sin(ATA) < R·√2 → LDT 영역 아님 (Shaw 정리 7)."""
        obs_now = make_obs(ata_deg=65, distance_ft=dist, relative_bearing_deg=80)
        obs_prev = make_obs(ata_deg=65, distance_ft=dist, relative_bearing_deg=70)
        val = tau_ldt(obs_now, obs_prev)
        assert val < 0.4, f"dist={dist}인데 τ_ldt={val:.3f}≥0.4 (Shaw spec 위반)"

    # ── LOS rate 작으면 τ_ldt 작음 ─────────────────────
    def test_low_los_rate_low(self):
        """MR-L3: |LOS rate| ≈ 0 → τ_ldt 매우 낮음."""
        # rb_now == rb_prev → rate=0
        rb = 80.0
        obs_now = make_obs(ata_deg=65, distance_ft=5000, relative_bearing_deg=rb)
        obs_prev = make_obs(ata_deg=65, distance_ft=5000, relative_bearing_deg=rb)
        val = tau_ldt(obs_now, obs_prev)
        assert val < 0.2, f"LOS rate=0인데 τ_ldt={val:.3f}≥0.2"

    # ── 거리·LOS 둘 다 증가하면 τ_ldt 증가 ─────────────
    def test_dist_and_los_both_increase(self):
        """MR-L4: dist↑ AND LOS rate ↑ → τ_ldt ↑ (또는 같음)."""
        common_ata = dict(ata_deg=65)
        # 작은 영역: dist=2500, LOS rate=2°/s
        prev_a = make_obs(distance_ft=2500, relative_bearing_deg=78, **common_ata)
        now_a  = make_obs(distance_ft=2500, relative_bearing_deg=80, **common_ata)
        # 큰 영역: dist=5000, LOS rate=15°/s
        prev_b = make_obs(distance_ft=5000, relative_bearing_deg=65, **common_ata)
        now_b  = make_obs(distance_ft=5000, relative_bearing_deg=80, **common_ata)
        v_small = tau_ldt(now_a, prev_a)
        v_large = tau_ldt(now_b, prev_b)
        assert v_large >= v_small - 1e-9


# ════════════════════════════════════════════════════════════════════════
# Cross-τ — 함수 간 일관성
# ════════════════════════════════════════════════════════════════════════

class TestCrossTau:
    """τ 함수들 사이 정합성 검증."""

    def test_canonical_initial_state(self):
        """canonical 초기(ATA=90, HCA=180, V=386.8, cl=0, dist=3297.6) 의 τ 값.

        이 상태는 sim 시작 직후. 어떤 τ가 활성화되어야 하는지 명세적 점검:
        - τ_corner: HCA=180 매우 큼, V=386.8 코너 위, but turn_rate=0 (시작 시) → 낮음
        - τ_yoyo:   HCA=180, closure=0 → orbit-lock 활성 가능, ATA=90 (peak 70 근처)
                     → 중간 정도
        - τ_ldt:    ATA=90 (peak 65 근처지만 σ=15 narrow), but LOS rate 미정 → 보통 낮음
        """
        obs = make_obs(
            hca_deg=180, ego_vc_kts=386.8, turn_rate_degs=0,
            ata_deg=90, aa_deg=90, distance_ft=3297.6,
            closure_rate_kts=0, relative_bearing_deg=90,
            alt_gap_ft=0, ps_fts=0,
        )
        c = tau_corner(obs, None)
        y = tau_yoyo(obs, None)
        l = tau_ldt(obs, None)
        # 측정만 — 자가 점검 (assertion 안 함, regression baseline)
        print(f"\n  canonical t=0: τ_corner={c:.3f}, τ_yoyo={y:.3f}, τ_ldt={l:.3f}")
        # 발동 단조성만 점검
        assert 0 <= c <= 1
        assert 0 <= y <= 1
        assert 0 <= l <= 1

    def test_sum_bounded(self):
        """τ들 합이 무한 폭주하지 않음 (sanity)."""
        obs = make_obs(hca_deg=180, ego_vc_kts=400, turn_rate_degs=20,
                       ata_deg=70, closure_rate_kts=80, distance_ft=4000,
                       relative_bearing_deg=80)
        c = tau_corner(obs, None)
        y = tau_yoyo(obs, None)
        l = tau_ldt(obs, None)
        # 각각 [0, 1]이므로 합은 [0, 3]. 이론적 상한.
        assert 0 <= c + y + l <= 3.0


# ════════════════════════════════════════════════════════════════════════
# Boundary / smoothness
# ════════════════════════════════════════════════════════════════════════

class TestBoundaryAndSmoothness:
    """수치 안정성: 극값/경계에서 NaN, Inf 없음."""

    def test_extreme_inputs_finite(self):
        """MR-S1: 극값 입력에도 finite 결과."""
        extremes = [
            dict(hca_deg=0,   ego_vc_kts=160, turn_rate_degs=0),
            dict(hca_deg=180, ego_vc_kts=420, turn_rate_degs=21),
            dict(closure_rate_kts=-500, distance_ft=20000),
            dict(closure_rate_kts=+500, distance_ft=500),
            dict(ata_deg=0, aa_deg=180),
            dict(ata_deg=180, aa_deg=0),
            dict(alt_gap_ft=-5000, ps_fts=-300),
            dict(alt_gap_ft=+5000, ps_fts=+300),
        ]
        for extra in extremes:
            obs = make_obs(**extra)
            for fn, name in [(tau_corner, "corner"), (tau_yoyo, "yoyo"), (tau_ldt, "ldt")]:
                val = fn(obs, None)
                assert math.isfinite(val), f"{name}({extra}) = {val} (not finite)"

    def test_smoothness_hca(self):
        """MR-S2: τ_corner 가 HCA에 대해 부드럽다 — Lipschitz-like.

        ε=1° 변화에 따른 τ 변화가 0.2 이하 (sigmoid는 이론상 max gradient 0.25/scale).
        s_hca scale=20 → max d(τ)/d(hca) ≈ 0.25/20 = 0.0125 per degree.
        ε=1° 변화로 τ 변화 ≤ 0.0125. 안전 여유 두고 0.2 임계.
        """
        common = dict(ego_vc_kts=387, turn_rate_degs=15)
        for hca in [80, 100, 120, 140, 160, 180]:
            obs1 = make_obs(hca_deg=hca, **common)
            obs2 = make_obs(hca_deg=hca + 1, **common)
            d = abs(tau_corner(obs1, None) - tau_corner(obs2, None))
            assert d < 0.2, f"τ_corner non-smooth at HCA={hca}: Δ={d}"


# ════════════════════════════════════════════════════════════════════════
# Standalone 실행 — pytest 없이도 결과 보고
# ════════════════════════════════════════════════════════════════════════

def main():
    """pytest 없이 직접 실행 — 모든 테스트 cross-cut 보고."""
    import inspect
    classes = [TestTauCorner, TestTauYoyo, TestTauLdt, TestCrossTau, TestBoundaryAndSmoothness]
    total = 0; passed = 0; failed = []

    print("=" * 70)
    print("  Metamorphic Test Runner — Phase A (no pytest)")
    print("=" * 70)

    for cls in classes:
        cls_name = cls.__name__
        instance = cls()
        for name, method in inspect.getmembers(instance, predicate=inspect.ismethod):
            if not name.startswith("test_"):
                continue

            # parametrize 추출 — _parametrize 속성 또는 pytestmark
            cases = [None]   # None = parameter 없음
            params_names = None

            # pytestmark (pytest 라이브러리 있을 때)
            marks = getattr(method.__func__, "pytestmark", None) or []
            for m in marks:
                if hasattr(m, "name") and m.name == "parametrize":
                    params_names = m.args[0]
                    cases = list(m.args[1])

            # stub의 _parametrize 속성 (pytest 없을 때)
            stub_param = getattr(method.__func__, "_parametrize", None)
            if stub_param is not None:
                params_names, cases = stub_param[0], list(stub_param[1])

            for case in cases:
                total += 1
                label = f"{cls_name}.{name}"
                if case is not None:
                    label += f"[{case}]"
                try:
                    if case is None:
                        method()
                    elif isinstance(case, tuple):
                        method(*case)
                    else:
                        method(case)
                    passed += 1
                    print(f"  ✓ {label}")
                except AssertionError as e:
                    failed.append((label, str(e)))
                    print(f"  ✗ {label}: {e}")
                except Exception as e:
                    failed.append((label, f"{type(e).__name__}: {e}"))
                    print(f"  ✗ {label}: {type(e).__name__}: {e}")

    print()
    print("=" * 70)
    print(f"  Result: {passed}/{total} PASSED, {len(failed)} FAILED")
    print("=" * 70)
    if failed:
        print("\nFailed details:")
        for lbl, msg in failed:
            print(f"  {lbl}")
            print(f"    {msg}")
    return len(failed) == 0


if __name__ == "__main__":
    ok = main()
    sys.exit(0 if ok else 1)
