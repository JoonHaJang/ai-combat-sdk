"""BT → 제어기 → JSBSim 실제 매핑 측정 도구 (2026-06-01).

사용자 목적: BT 명령 [delta_alt, delta_hdg, delta_vel]이 실제로 JSBSim에서
어떤 물리 결과를 만드는지 empirical 측정.

측정 항목:
1. vel bin (0~4) → throttle 출력 분포 (선형인가?)
2. alt bin (0~4) → altitude 변화율, elevator 출력
3. hdg bin (0~8) → heading 변화율, aileron 출력

방법: 실제 매치에서 metadata 수집 → 각 bin 별 통계.

usage:
    python tools/verify/bt_control_mapping.py logs/metadata/*_meta.csv

결과 예시:
    vel=4 → throttle mean=0.50±0.01  ← 선형이면 throttle 높아야 함
    vel=0 → throttle mean=0.50±0.01  ← 같으면 vel→throttle 매핑 없음
"""
from __future__ import annotations
import sys, csv, glob, statistics
from collections import defaultdict
from pathlib import Path


def to_float(v, d=0.0):
    try: return float(v)
    except: return d


def analyze(paths):
    """여러 메타데이터 CSV를 합쳐서 BT bin → 물리 결과 통계."""
    # bin별 버킷
    vel_buckets  = defaultdict(lambda: {'thr': [], 'dvc': []})
    alt_buckets  = defaultdict(lambda: {'elev': [], 'dalt': []})
    hdg_buckets  = defaultdict(lambda: {'ail': [], 'dhdg': []})

    for fp in paths:
        with open(fp) as f:
            rows = list(csv.DictReader(f))
        us = [r for r in rows if r.get('tree_name') == 'pursuit_chase_btcost']
        if not us:
            continue

        prev_vc  = to_float(us[0]['ego_vc_kts'])
        prev_alt = to_float(us[0]['ego_altitude_ft'])

        for i, r in enumerate(us):
            # bin 값
            vel_bin = int(to_float(r.get('action_vel', 2)))
            alt_bin = int(to_float(r.get('action_alt', 2)))
            hdg_bin = int(to_float(r.get('action_hdg', 4)))

            # 출력 물리값
            throttle = to_float(r.get('throttle', 0.5))
            aileron  = to_float(r.get('aileron', 0.0))
            elevator = to_float(r.get('elevator', 0.0))
            vc       = to_float(r.get('ego_vc_kts', 0))
            alt      = to_float(r.get('ego_altitude_ft', 0))

            # 변화율 (다음 스텝과의 차이)
            dvc  = vc - prev_vc
            dalt = alt - prev_alt
            prev_vc = vc; prev_alt = alt

            vel_buckets[vel_bin]['thr'].append(throttle)
            vel_buckets[vel_bin]['dvc'].append(dvc)
            alt_buckets[alt_bin]['elev'].append(elevator)
            alt_buckets[alt_bin]['dalt'].append(dalt)
            hdg_buckets[hdg_bin]['ail'].append(aileron)

    # 보고
    print("\n" + "="*70)
    print("BT vel bin → throttle / vc 변화율 (선형이어야 함)")
    print("="*70)
    print(f"{'vel bin':8s} {'throttle mean':15s} {'throttle std':12s} {'dvc mean(kt/env)':18s} {'N':>6s}")
    print("-"*70)
    for v in range(5):
        b = vel_buckets[v]
        if not b['thr']:
            continue
        thr_m = statistics.mean(b['thr'])
        thr_s = statistics.stdev(b['thr']) if len(b['thr']) > 1 else 0.0
        dvc_m = statistics.mean(b['dvc'])
        n = len(b['thr'])
        flag = " ← RNN 무반응!" if v in [0,4] and abs(thr_m - 0.5) < 0.05 else ""
        print(f"  vel={v}   {thr_m:8.4f} ± {thr_s:.4f}    {dvc_m:+8.4f}         {n:6d}{flag}")

    print("\n" + "="*70)
    print("BT alt bin → elevator / altitude 변화율")
    print("="*70)
    print(f"{'alt bin':8s} {'elevator mean':15s} {'elevator std':12s} {'dalt mean(ft/env)':18s} {'N':>6s}")
    print("-"*70)
    for a in range(5):
        b = alt_buckets[a]
        if not b['elev']:
            continue
        el_m = statistics.mean(b['elev'])
        el_s = statistics.stdev(b['elev']) if len(b['elev']) > 1 else 0.0
        dalt_m = statistics.mean(b['dalt'])
        n = len(b['elev'])
        flag = " ← 비선형!" if a in [0,4] and abs(el_m) < 0.1 else ""
        print(f"  alt={a}   {el_m:+8.4f} ± {el_s:.4f}    {dalt_m:+8.2f}         {n:6d}{flag}")

    print("\n" + "="*70)
    print("BT hdg bin → aileron (선형이어야 hdg=0 → aileron -1, hdg=8 → +1)")
    print("="*70)
    print(f"{'hdg bin':8s} {'aileron mean':15s} {'aileron std':12s} {'N':>6s}")
    print("-"*70)
    for h in range(9):
        b = hdg_buckets[h]
        if not b['ail']:
            continue
        ai_m = statistics.mean(b['ail'])
        ai_s = statistics.stdev(b['ail']) if len(b['ail']) > 1 else 0.0
        n = len(b['ail'])
        print(f"  hdg={h}   {ai_m:+8.4f} ± {ai_s:.4f}                   {n:6d}")

    print("\n" + "="*70)
    print("매핑 품질 평가")
    print("="*70)
    # vel 선형성: vel=4 throttle > vel=0 throttle?
    if vel_buckets[4]['thr'] and vel_buckets[0]['thr']:
        t4 = statistics.mean(vel_buckets[4]['thr'])
        t0 = statistics.mean(vel_buckets[0]['thr'])
        diff = t4 - t0
        flag = "✅ 선형" if diff > 0.1 else "❌ 비선형 (vel→throttle 매핑 없음)"
        print(f"  vel: vel=4 throttle({t4:.3f}) - vel=0 throttle({t0:.3f}) = {diff:+.3f}  {flag}")

    if alt_buckets[4]['elev'] and alt_buckets[0]['elev']:
        e4 = statistics.mean(alt_buckets[4]['elev'])
        e0 = statistics.mean(alt_buckets[0]['elev'])
        diff = e4 - e0
        flag = "✅ 선형" if diff > 0.2 else "⚠️ 약한 선형"
        print(f"  alt: alt=4 elev({e4:.3f}) - alt=0 elev({e0:.3f}) = {diff:+.3f}  {flag}")

    if hdg_buckets[8]['ail'] and hdg_buckets[0]['ail']:
        a8 = statistics.mean(hdg_buckets[8]['ail'])
        a0 = statistics.mean(hdg_buckets[0]['ail'])
        diff = a8 - a0
        flag = "✅ 선형" if diff > 0.5 else "⚠️ 약한 선형"
        print(f"  hdg: hdg=8 ail({a8:.3f}) - hdg=0 ail({a0:.3f}) = {diff:+.3f}  {flag}")


if __name__ == "__main__":
    paths = []
    for p in sys.argv[1:]:
        paths.extend(sorted(glob.glob(p)))
    if not paths:
        # 기본: 최근 메타데이터 CSV 전체
        paths = sorted(glob.glob("logs/metadata/*.csv"))
        paths = [p for p in paths if '_result' not in p]
    if not paths:
        print("usage: python tools/verify/bt_control_mapping.py <meta_csv>")
        sys.exit(1)
    print(f"분석 파일: {len(paths)}개")
    analyze(paths)
