"""
GAP-3: _wilson_ci 수학 정확도 단위 테스트.
시뮬레이션 없음 — 순수 수학 함수 검증.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from tools.evaluate import _wilson_ci


class TestWilsonCI:
    def test_zero_total_returns_zeros(self):
        lo, hi = _wilson_ci(0, 0)
        assert lo == 0.0 and hi == 0.0

    def test_perfect_win_rate(self):
        lo, hi = _wilson_ci(100, 100)
        assert lo > 0.9, f"Expected lo > 0.9, got {lo}"
        assert hi == 1.0

    def test_zero_win_rate(self):
        lo, hi = _wilson_ci(0, 100)
        assert lo == 0.0
        assert hi < 0.05, f"Expected hi < 0.05, got {hi}"

    def test_50_percent(self):
        lo, hi = _wilson_ci(50, 100)
        # 50% with n=100: CI should be roughly [0.40, 0.60]
        assert 0.38 < lo < 0.45
        assert 0.55 < hi < 0.62

    def test_ci_is_ordered(self):
        for wins, total in [(10, 40), (1, 695), (22, 40), (17, 40)]:
            lo, hi = _wilson_ci(wins, total)
            assert lo <= hi, f"lo={lo} > hi={hi} for wins={wins}, total={total}"

    def test_wilson_bounds_in_0_1(self):
        for wins, total in [(0, 1), (1, 1), (500, 1000), (6950, 6950)]:
            lo, hi = _wilson_ci(wins, total)
            assert 0.0 <= lo <= 1.0
            assert 0.0 <= hi <= 1.0

    def test_cycle1_baseline(self):
        # Cycle 1 전체 검증: WR=54.17%, n=6950
        wins = round(0.5417 * 6950)
        lo, hi = _wilson_ci(wins, 6950)
        # 기존 계산값 [0.5300, 0.5534] 와 일치 여부
        assert abs(lo - 0.5300) < 0.005, f"lo={lo} vs expected ~0.5300"
        assert abs(hi - 0.5534) < 0.005, f"hi={hi} vs expected ~0.5534"

    def test_small_sample_conservative(self):
        # 소표본 (n=40, cycle eval sample): CI가 충분히 넓어야 함
        lo, hi = _wilson_ci(22, 40)
        assert hi - lo > 0.20, f"CI too narrow for n=40: [{lo}, {hi}]"

    def test_symmetry(self):
        # p=0.3이면 reverse도 동일 폭
        lo1, hi1 = _wilson_ci(30, 100)
        lo2, hi2 = _wilson_ci(70, 100)
        assert abs((hi1 - lo1) - (hi2 - lo2)) < 0.01
