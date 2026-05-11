"""
diagnose_offensive.py — canonical × offensive 단일 시나리오 깊이 분석.

Phase C 에서 발견된 단일 위반: canonical × offensive ρ=-28.908.
이 시나리오에서:
  - WEZ 4개 조건 (ata<12, dist>500, dist<3000 또는 aa>45+dist<4000, cl>0)
    각각이 시간 동안 어떻게 변하는지
  - 어느 조건이 가장 자주 위반되는지 (병목)
  - 우리 τ 함수가 어떤 결정을 내리는지
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np

from sim_dogfight_verify import run_scenario
from canonical_perturbation import canonical_init


def main():
    init = canonical_init()
    print("=" * 70)
    print("  Diagnose: canonical × offensive")
    print("=" * 70)

    result = run_scenario(init, "offensive", max_ticks=1500, verbose=False)
    log = result["log"]
    print(f"  Outcome:        {result['outcome']}")
    print(f"  Total ticks:    {len(log)}")
    print(f"  HP us / them:   {result['own_gun_ticks']} / {result['enemy_gun_ticks']}")
    print()

    # ─ 조건별 시계열 통계 ─────────────────────────────────────
    ata = np.array([r[1] for r in log])
    dist= np.array([r[2] for r in log])
    cl  = np.array([r[3] for r in log])
    aa  = np.array([r[11] for r in log])
    hca = np.array([r[12] for r in log])
    alt_gap = np.array([r[13] for r in log])

    print("=" * 70)
    print("  WEZ 조건별 시간 분포")
    print("=" * 70)
    print(f"  {'condition':30s}  {'min':>7s}  {'max':>7s}  {'mean':>7s}  {'%satisfy':>9s}")
    conds = [
        ("ATA < 12°",          ata < 12,   ata),
        ("dist > 500ft",       dist > 500, dist),
        ("dist < 3000ft",      dist < 3000,dist),
        ("dist < 4000 (AA>45)", (dist<4000)&(aa>45), dist),
        ("closure > 0",        cl > 0,     cl),
        ("AA > 45°",           aa > 45,    aa),
        ("HCA > 120°",         hca > 120,  hca),
    ]
    for name, mask, vals in conds:
        sat = 100 * mask.sum() / len(mask)
        print(f"  {name:30s}  {vals.min():+7.1f}  {vals.max():+7.1f}  "
              f"{vals.mean():+7.1f}  {sat:8.1f}%")

    # ─ WEZ 4개 조건 동시 만족 시간 ─────────────────────────────
    wez_basic = (ata<12) & (dist>500) & (dist<3000) & (cl>0)
    wez_ext   = (ata<12) & (dist>500) & ((dist<3000) | ((aa>45)&(dist<4000))) & (cl>0)
    print()
    print(f"  WEZ basic (dist<3000)        만족 틱: {wez_basic.sum()}/{len(log)} = {100*wez_basic.mean():.2f}%")
    print(f"  WEZ extended (AA>45→4000ft)  만족 틱: {wez_ext.sum()}/{len(log)} = {100*wez_ext.mean():.2f}%")

    # ─ 가장 근접한 시점 찾기 (ρ_capture 의 argmax) ───────────
    print()
    print("=" * 70)
    print("  가장 WEZ에 근접한 순간 (ρ_capture argmax)")
    print("=" * 70)

    # 각 시점의 ρ_AND 계산 (이전 STL 식과 동일)
    rho_ata = 12.0 - ata
    rho_d1  = dist - 500.0
    rho_d2_basic = 3000.0 - dist
    rho_d2_ext   = np.maximum(rho_d2_basic, np.minimum(aa - 45.0, 4000.0 - dist))
    rho_cl  = cl - 0.0
    rho_t   = np.minimum.reduce([rho_ata, rho_d1, rho_d2_ext, rho_cl])
    best_t = int(rho_t.argmax())
    print(f"  best tick:   {best_t} (t={best_t*0.2:.1f}s)")
    print(f"  ρ at best:   {rho_t[best_t]:+.3f}")
    print(f"    ATA = {ata[best_t]:.1f}°       (조건 ATA<12 → ρ={rho_ata[best_t]:+.1f})")
    print(f"    dist= {dist[best_t]:.0f}ft    (조건 500<dist<3000 또는 AA>45+dist<4000 → ρ={rho_d2_ext[best_t]:+.1f})")
    print(f"    AA  = {aa[best_t]:.1f}°       (extended WEZ 활성? {aa[best_t]>45})")
    print(f"    cl  = {cl[best_t]:+.0f}kts    (조건 cl>0 → ρ={rho_cl[best_t]:+.1f})")
    print(f"    HCA = {hca[best_t]:.1f}°")
    print(f"    alt_gap = {alt_gap[best_t]:+.0f}ft")

    # ─ 어느 조건이 병목? (각 조건이 ρ를 결정한 비율) ───────
    rho_stack = np.stack([rho_ata, rho_d1, rho_d2_ext, rho_cl])
    binding   = rho_stack.argmin(axis=0)   # 각 시점에서 어느 조건이 최소(병목)
    counts = np.bincount(binding, minlength=4)
    labels = ["ATA<12", "dist>500", "dist constraint", "cl>0"]
    print()
    print("  병목 조건 분포 (각 조건이 ρ_AND 결정한 비율):")
    for i, lbl in enumerate(labels):
        print(f"    {lbl:20s}  {counts[i]:5d} ticks  {100*counts[i]/len(log):5.1f}%")

    # ─ 최단 거리, 최저 ATA 추적 ────────────────────────────
    print()
    print("=" * 70)
    print("  핵심 변수 극값 추적")
    print("=" * 70)
    print(f"  최저 ATA :  {ata.min():.1f}°  @ t={ata.argmin()*0.2:.1f}s  (dist={dist[ata.argmin()]:.0f}, cl={cl[ata.argmin()]:+.0f})")
    print(f"  최단 dist:  {dist.min():.0f}ft @ t={dist.argmin()*0.2:.1f}s  (ATA={ata[dist.argmin()]:.1f}, cl={cl[dist.argmin()]:+.0f})")
    print(f"  최대 cl  :  {cl.max():+.0f}kts @ t={cl.argmax()*0.2:.1f}s  (ATA={ata[cl.argmax()]:.1f}, dist={dist[cl.argmax()]:.0f})")

    # ─ branch / mode 분포 ──────────────────────────────────
    print()
    print("=" * 70)
    print("  Branch / Mode 분포")
    print("=" * 70)
    branches = [r[4] for r in log]
    modes    = [r[5] for r in log]
    from collections import Counter
    for name, lst in [("Branch", branches), ("Mode", modes)]:
        c = Counter(lst)
        print(f"  {name}:")
        for k, v in c.most_common(5):
            print(f"    {str(k)[:50]:50s}  {v:5d}  {100*v/len(lst):5.1f}%")


if __name__ == "__main__":
    main()
