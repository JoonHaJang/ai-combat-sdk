"""Dynamics 가정 (small-γ) 실측 검증.

목적: §0.5 C2 의 "small-γ 가정 (~14% 오차)" 이 실 매치 데이터에서
       얼마나 빈번/큰가를 정량 측정.

측정:
  1. γ (flight path angle) 분포 — γ = asin(v_z / |v|)
  2. pitch_deg 분포 — body axis angle
  3. cos γ 실측 vs cos γ ≈ 1 가정 오차 (%)
  4. sin γ 실측 vs sin γ ≈ γ (rad) 가정 오차 (%)
  5. Δψ 분포 — state 비선형성의 source
  6. 각 액션별 γ 발생 빈도

데이터 소스:
  logs/profiling/*.csv — 31 액션 × 3 trial = ~93 매치, 각 200 ticks
                       --log-csv (50 cols, vx/vy/vz 포함)

실행:
  python tools/analyze_dynamics_assumptions.py
"""

from __future__ import annotations

import sys
import os
from pathlib import Path

os.environ.setdefault("PYTHONIOENCODING", "utf-8")
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, ValueError):
    pass

import numpy as np
import pandas as pd
import re

PROJECT_ROOT = Path(__file__).parent.parent
PROFILING_DIR = PROJECT_ROOT / "logs" / "profiling"


def gamma_from_velocity(vx, vy, vz):
    """flight path angle γ = asin(v_z / |v|) [degrees]."""
    v_mag = np.sqrt(vx ** 2 + vy ** 2 + vz ** 2)
    v_mag = np.where(v_mag < 1e-6, 1e-6, v_mag)
    sin_gamma = np.clip(vz / v_mag, -1.0, 1.0)
    return np.degrees(np.arcsin(sin_gamma))


def extract_action_name(csv_path):
    """파일명에서 액션 이름 추출."""
    m = re.search(r"profile_(\w+)_vs_", csv_path.name)
    return m.group(1) if m else "unknown"


def main():
    print("=" * 80)
    print("  Dynamics 가정 실측 검증 — small-γ approximation error")
    print("=" * 80)

    csv_files = sorted(PROFILING_DIR.glob("*_profile_*.csv"))
    print(f"\n로드 CSV: {len(csv_files)} 파일")

    # 전체 데이터 누적
    all_gamma = []
    all_dpsi = []
    all_pitch = []
    all_vmag = []
    per_action = {}

    for csv_path in csv_files:
        action = extract_action_name(csv_path)
        try:
            df = pd.read_csv(csv_path)
        except Exception:
            continue

        # 우리 측만
        tree_name = f"profile_{action}"
        df_us = df[df["tree_name"] == tree_name]
        if len(df_us) < 5:
            continue

        # γ 계산
        if all(c in df_us.columns for c in ["ego_vx_kts", "ego_vy_kts", "ego_vz_kts"]):
            gamma = gamma_from_velocity(df_us["ego_vx_kts"].values,
                                        df_us["ego_vy_kts"].values,
                                        df_us["ego_vz_kts"].values)
            all_gamma.extend(gamma)
            per_action.setdefault(action, []).extend(gamma)

        # 추가 지표
        if "pitch_deg" in df_us.columns:
            all_pitch.extend(df_us["pitch_deg"].values)
        if "hca_deg" in df_us.columns:
            # hca_deg 는 (raw) × 180 스케일됨 (CSV 버그) — / 180 으로 정상화
            hca_raw = df_us["hca_deg"].values
            hca_normalized = hca_raw / 180.0   # 이제 정확한 도 값
            all_dpsi.extend(hca_normalized)
        if all(c in df_us.columns for c in ["ego_vx_kts", "ego_vy_kts", "ego_vz_kts"]):
            vmag = np.sqrt(df_us["ego_vx_kts"].values**2 +
                           df_us["ego_vy_kts"].values**2 +
                           df_us["ego_vz_kts"].values**2)
            all_vmag.extend(vmag)

    all_gamma = np.array(all_gamma)
    all_pitch = np.array(all_pitch)
    all_dpsi = np.array(all_dpsi)
    all_vmag = np.array(all_vmag)

    n_total = len(all_gamma)
    print(f"  총 데이터 포인트: {n_total:,} tick (≈ {n_total/5:.0f} 초 비행)")

    if n_total == 0:
        print("❌ 데이터 없음 — profiling 매치 먼저 실행 필요")
        return

    # ─── 1. γ 분포 ──────────────────────────────────────
    print(f"\n{'='*80}")
    print(f"  [1] γ (flight path angle) 분포 — velocity vector 기반")
    print(f"{'='*80}")
    print(f"  min                : {all_gamma.min():7.2f} °")
    print(f"  max                : {all_gamma.max():7.2f} °")
    print(f"  mean (signed)      : {all_gamma.mean():7.2f} °")
    print(f"  mean |γ|           : {np.abs(all_gamma).mean():7.2f} °")
    print(f"  median |γ|         : {np.median(np.abs(all_gamma)):7.2f} °")
    print(f"  95-percentile |γ|  : {np.percentile(np.abs(all_gamma), 95):7.2f} °")
    print(f"  99-percentile |γ|  : {np.percentile(np.abs(all_gamma), 99):7.2f} °")
    print(f"  std                : {all_gamma.std():7.2f} °")

    # γ 범위별 빈도
    print(f"\n  |γ| 범위별 빈도:")
    bins = [0, 5, 10, 15, 20, 25, 30, 45, 60, 90]
    abs_gamma = np.abs(all_gamma)
    for lo, hi in zip(bins[:-1], bins[1:]):
        n = ((abs_gamma >= lo) & (abs_gamma < hi)).sum()
        pct = 100 * n / n_total
        bar = "█" * int(pct / 2)
        print(f"    [{lo:2d}, {hi:2d})°: {n:6,} ({pct:5.1f}%) {bar}")

    # ─── 2. small-γ 가정 오차 (cos γ ≈ 1) ────────────────
    print(f"\n{'='*80}")
    print(f"  [2] cos γ ≈ 1 가정 오차 (small-γ assumption error)")
    print(f"{'='*80}")
    cos_actual = np.cos(np.radians(all_gamma))
    cos_assumed = 1.0
    cos_error_pct = (cos_assumed - cos_actual) / cos_actual * 100  # 가정이 얼마나 과대평가
    cos_error_abs = np.abs(cos_error_pct)

    print(f"  cos γ 실측 평균    : {cos_actual.mean():.4f}")
    print(f"  cos γ 가정 (≡ 1)   : 1.0000")
    print(f"  Relative error mean: {cos_error_abs.mean():.2f} %")
    print(f"  Relative error 95%ile: {np.percentile(cos_error_abs, 95):.2f} %")
    print(f"  Relative error max : {cos_error_abs.max():.2f} %")

    print(f"\n  오차 분포:")
    err_bins = [0, 1, 2, 5, 10, 14, 20, 50]
    for lo, hi in zip(err_bins[:-1], err_bins[1:]):
        n = ((cos_error_abs >= lo) & (cos_error_abs < hi)).sum()
        pct = 100 * n / n_total
        bar = "█" * int(pct / 2)
        print(f"    [{lo:2d}%, {hi:2d}%): {n:6,} ({pct:5.1f}%) {bar}")

    # ─── 3. small-γ 가정 오차 (sin γ ≈ γ_rad) ──────────
    print(f"\n{'='*80}")
    print(f"  [3] sin γ ≈ γ (rad) 가정 오차")
    print(f"{'='*80}")
    gamma_rad = np.radians(all_gamma)
    sin_actual = np.sin(gamma_rad)
    sin_assumed = gamma_rad
    # 분모 0 방지
    safe_sin = np.where(np.abs(sin_actual) < 1e-9, 1e-9, sin_actual)
    sin_error_pct = (sin_assumed - sin_actual) / np.abs(safe_sin) * 100
    sin_error_abs = np.abs(sin_error_pct)
    # γ=0 인 곳 제외 (분모 작아 무의미)
    mask = np.abs(all_gamma) > 1.0
    print(f"  유효 데이터 (|γ|>1°): {mask.sum():,} / {n_total:,} ({100*mask.sum()/n_total:.1f}%)")
    if mask.sum() > 0:
        print(f"  Relative error mean : {sin_error_abs[mask].mean():.2f} %")
        print(f"  Relative error 95%ile: {np.percentile(sin_error_abs[mask], 95):.2f} %")
        print(f"  Relative error max  : {sin_error_abs[mask].max():.2f} %")

    # ─── 4. Δψ (heading 차) 분포 ───────────────────────
    print(f"\n{'='*80}")
    print(f"  [4] HCA (≈ Δψ) 분포 — state 비선형성의 source")
    print(f"{'='*80}")
    if len(all_dpsi) > 0:
        print(f"  HCA min/max     : {all_dpsi.min():.1f}°  /  {all_dpsi.max():.1f}°")
        print(f"  HCA mean        : {all_dpsi.mean():.1f}°")
        print(f"  HCA median      : {np.median(all_dpsi):.1f}°")
        print(f"\n  HCA 범위별 빈도:")
        dpsi_bins = [0, 30, 60, 90, 120, 150, 180]
        for lo, hi in zip(dpsi_bins[:-1], dpsi_bins[1:]):
            n = ((all_dpsi >= lo) & (all_dpsi < hi)).sum()
            pct = 100 * n / len(all_dpsi)
            bar = "█" * int(pct / 2)
            print(f"    [{lo:3d}, {hi:3d})°: {n:6,} ({pct:5.1f}%) {bar}")

    # ─── 5. 액션별 γ 통계 ───────────────────────────────
    print(f"\n{'='*80}")
    print(f"  [5] 액션별 |γ| 통계 (Top 10 큰 γ 발생 액션)")
    print(f"{'='*80}")
    action_stats = []
    for action, gammas in per_action.items():
        ga = np.abs(np.array(gammas))
        action_stats.append((action, ga.mean(), ga.max(), np.percentile(ga, 95), len(ga)))
    action_stats.sort(key=lambda x: -x[2])  # max desc
    print(f"  {'Action':<22} {'|γ| mean':>10} {'|γ| max':>10} {'|γ| 95%':>10} {'N ticks':>10}")
    print(f"  {'-'*22} {'-'*10} {'-'*10} {'-'*10} {'-'*10}")
    for action, m, mx, p95, n in action_stats[:10]:
        print(f"  {action:<22} {m:>10.2f}° {mx:>10.2f}° {p95:>10.2f}° {n:>10,}")

    # ─── 6. small-γ 가정의 실측 평균 오차 (full 측정) ────
    print(f"\n{'='*80}")
    print(f"  [6] 종합 — small-γ 가정의 실측 평균 오차")
    print(f"{'='*80}")
    # 이론값 (sin/cos 계산)
    err_at_gamma = {}
    for g_deg in [0, 5, 10, 15, 20, 25, 30, 45]:
        cos_err = (1 - np.cos(np.radians(g_deg))) * 100  # %
        if g_deg > 0:
            sin_err = (np.radians(g_deg) - np.sin(np.radians(g_deg))) / np.sin(np.radians(g_deg)) * 100
        else:
            sin_err = 0
        err_at_gamma[g_deg] = (cos_err, sin_err)
    print(f"  이론적 오차 (γ 값 기준):")
    print(f"  {'γ [°]':<8} {'cos 오차 (%)':<15} {'sin 오차 (%)':<15}")
    for g, (ce, se) in err_at_gamma.items():
        print(f"  {g:<8} {ce:<15.3f} {se:<15.3f}")

    print(f"\n  본 데이터에서 실측:")
    print(f"  cos γ 평균 오차     : {cos_error_abs.mean():.3f}%")
    print(f"  sin γ 평균 오차 (|γ|>1°): {sin_error_abs[mask].mean() if mask.sum() else 0:.3f}%")
    print(f"  → §0.5 C2 가정의 실 매치 평균 오차 = {cos_error_abs.mean():.3f}% (cos)")
    print(f"  → '~14% 오차' 는 max γ=30° 의 worst case — 실 매치에서는 훨씬 작음")


if __name__ == "__main__":
    main()
