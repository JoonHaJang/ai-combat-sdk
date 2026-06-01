"""BT → JSBSim 직접 물리 매핑 측정 (2026-06-01).

metadata의 aileron/throttle은 fallback(0.5/0.0) — 실제 값 아님.
물리 결과(dvc, dalt, dhdg)로 간접 측정.

측정: BT bin → N 스텝 후 실제 물리 변화량 통계.
    vel bin → dvc(kt/env_step), vc trajectory
    alt bin → dalt(ft/env_step), alt trajectory
    hdg bin → d_rel_bearing (deg/step) → heading 변화 proxy

usage:
    python tools/verify/bt_mapping_direct.py logs/mapping_test/*.csv
"""
from __future__ import annotations
import sys, csv, glob, statistics
from collections import defaultdict


def analyze(paths):
    by_vel_dvc  = defaultdict(list)   # vel bin → dvc
    by_vel_vc   = defaultdict(list)   # vel bin → vc 절대
    by_alt_dalt = defaultdict(list)   # alt bin → dalt
    by_alt_alt  = defaultdict(list)   # alt bin → alt 절대
    by_hdg_drb  = defaultdict(list)   # hdg bin → d_rel_bearing
    by_hdg_tr   = defaultdict(list)   # hdg bin → turn_rate

    for fp in paths:
        with open(fp) as f:
            rows = list(csv.DictReader(f))
        us = [r for r in rows if 'pursuit' in str(r.get('tree_name', '')).lower()]
        if len(us) < 2:
            continue

        # 컬럼명 호환: 구버전(action_vel) / upstream v0.11(action_velocity)
        c0 = us[0]
        VEL = 'action_velocity' if 'action_velocity' in c0 else 'action_vel'
        ALT = 'action_altitude' if 'action_altitude' in c0 else 'action_alt'
        HDG = 'action_heading' if 'action_heading' in c0 else 'action_hdg'

        for i in range(1, len(us)):
            r0, r1 = us[i-1], us[i]
            try:
                vel = int(float(r0.get(VEL, 2)))
                alt = int(float(r0.get(ALT, 2)))
                hdg = int(float(r0.get(HDG, 4)))

                vc0 = float(r0['ego_vc_kts']); vc1 = float(r1['ego_vc_kts'])
                a0  = float(r0['ego_altitude_ft']); a1 = float(r1['ego_altitude_ft'])
                # relative_bearing_deg 없으면(upstream CSV) turn_rate 만 사용.
                rb0 = float(r0.get('relative_bearing_deg', 0)) / 180.0
                rb1 = float(r1.get('relative_bearing_deg', 0)) / 180.0
                tr  = float(r1.get('turn_rate_degs', 0))

                dvc = vc1 - vc0
                dalt = a1 - a0
                drb = rb1 - rb0   # 적 relative bearing 변화 (heading 변화 proxy)

                by_vel_dvc[vel].append(dvc)
                by_vel_vc[vel].append(vc1)
                by_alt_dalt[alt].append(dalt)
                by_alt_alt[alt].append(a1)
                by_hdg_drb[hdg].append(drb)
                by_hdg_tr[hdg].append(tr)
            except (KeyError, ValueError):
                continue

    def mean_std(lst):
        if not lst: return 0.0, 0.0, 0
        m = statistics.mean(lst)
        s = statistics.stdev(lst) if len(lst) > 1 else 0.0
        return m, s, len(lst)

    print("\n" + "="*75)
    print("vel bin → 속도 변화율 (dvc, kt/env_step) + 평균 vc")
    print("  * 선형이면: vel=4 dvc > vel=3 > vel=2 > vel=1 > vel=0")
    print("="*75)
    print(f"  {'vel':4} | {'dvc mean':10} | {'dvc std':8} | {'vc mean':8} | {'n':>6}")
    print("  " + "-"*55)
    prev_dvc = None
    for v in range(5):
        m, s, n = mean_std(by_vel_dvc[v])
        vm, _, _ = mean_std(by_vel_vc[v])
        mono = ""
        if prev_dvc is not None:
            mono = "✓" if m > prev_dvc else "✗"
        prev_dvc = m
        print(f"  vel={v} | {m:+8.4f}   | {s:6.4f}   | {vm:6.1f}   | {n:6d}  {mono}")

    print("\n" + "="*75)
    print("alt bin → 고도 변화율 (dalt, ft/env_step) + 평균 alt")
    print("  * 선형이면: alt=4 dalt > alt=3 > alt=2 > alt=1 > alt=0")
    print("="*75)
    print(f"  {'alt':4} | {'dalt mean':10} | {'dalt std':8} | {'alt mean':8} | {'n':>6}")
    print("  " + "-"*55)
    prev_dalt = None
    for a in range(5):
        m, s, n = mean_std(by_alt_dalt[a])
        am, _, _ = mean_std(by_alt_alt[a])
        mono = ""
        if prev_dalt is not None:
            mono = "✓" if m > prev_dalt else "✗"
        prev_dalt = m
        print(f"  alt={a} | {m:+8.2f}   | {s:6.2f}   | {am:6.1f}   | {n:6d}  {mono}")

    print("\n" + "="*75)
    print("hdg bin → rel_bearing 변화율 + turn_rate")
    print("  * 선형이면: hdg=8 turn > hdg=4(직진) > hdg=0 turn (반대)")
    print("="*75)
    print(f"  {'hdg':4} | {'drb mean':10} | {'drb std':8} | {'tr mean':8} | {'n':>6}")
    print("  " + "-"*55)
    for h in range(9):
        m, s, n = mean_std(by_hdg_drb[h])
        tr_m, _, _ = mean_std(by_hdg_tr[h])
        print(f"  hdg={h} | {m:+8.4f}   | {s:6.4f}   | {tr_m:+6.2f}   | {n:6d}")

    print("\n" + "="*75)
    print("SUMMARY: BT → JSBSim 매핑 품질")
    print("="*75)
    for label, buckets in [("vel→dvc", by_vel_dvc), ("alt→dalt", by_alt_dalt)]:
        vals = [statistics.mean(v) for k, v in sorted(buckets.items()) if v]
        if len(vals) >= 2:
            mono = all(vals[i] <= vals[i+1] for i in range(len(vals)-1))
            print(f"  {label}: {'단조증가 ✅ 선형' if mono else '단조 불만족 ❌ 비선형'} | values: {[f'{v:+.3f}' for v in vals]}")


if __name__ == "__main__":
    paths = []
    for p in sys.argv[1:]:
        paths.extend(sorted(glob.glob(p)))
    if not paths:
        paths = [p for p in sorted(glob.glob("logs/**/*.csv", recursive=True))
                 if '_result' not in p and 'metadata' in p][:10]
    print(f"분석 파일: {len(paths)}개")
    analyze(paths)
