"""R15-K 머지 결정기 설계용 정량 분석.

목표:
1. **lead-turn miss**: 매 tick 우리 hdg vs 적 미래(2초후) 위치로의 ideal hdg 차이.
   pure pursuit 의 본질적 lag 정량화.
2. **결정 모먼트**: closure 가 +(접근) → -(분리) 로 뒤집히는 시점 = 머지 정점.
3. **재조우 윈도우**: 정상상태 진입 후에도 closure +30 이상 모먼트 있나.
"""
import re
from pathlib import Path
import numpy as np
import matplotlib.pyplot as plt

T_RE = re.compile(r"T=([\-\d\.eE]+)\|([\-\d\.eE]+)\|([\-\d\.eE]+)")
HDG_RE = re.compile(r"HDG=([\-\d\.eE]+)")
CAS_RE = re.compile(r"CAS=([\-\d\.eE]+)")
ATA_RE = re.compile(r"ATA=([\-\d\.eE]+)")
DIST_RE = re.compile(r"Distance=([\-\d\.eE]+)")
CR_RE = re.compile(r"ClosureRate=([\-\d\.eE]+)")


def parse(path):
    ticks = []
    cur_time = 0.0
    cur_state = None
    with open(path, 'r', encoding='utf-8-sig') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            if line.startswith('#'):
                if cur_state is not None:
                    ticks.append((cur_time, cur_state))
                try: cur_time = float(line[1:])
                except: pass
                cur_state = {}
                continue
            if cur_state is None or not (line.startswith('A0100') or line.startswith('B0100')):
                continue
            uid = line[:5]
            d = cur_state.setdefault(uid, {})
            for rx, key in ((HDG_RE, "hdg"), (CAS_RE, "cas"),
                             (ATA_RE, "ata"), (DIST_RE, "dist"), (CR_RE, "cr")):
                m = rx.search(line)
                if m:
                    d[key] = float(m.group(1))
            m = T_RE.search(line)
            if m:
                d["lon"] = float(m.group(1))
                d["lat"] = float(m.group(2))
                d["alt"] = float(m.group(3))
    if cur_state is not None:
        ticks.append((cur_time, cur_state))
    return ticks


def to_local_ne(lon, lat, lon0=120.0, lat0=60.0):
    """Quick local NE projection (m)."""
    n = (lat - lat0) * 111000
    e = (lon - lon0) * 111000 * np.cos(np.radians(lat0))
    return n, e


def analyze(label, path, window_full_s=75.0):
    ticks = parse(path)
    if not ticks:
        return None

    # arrays
    t_arr, dist_arr, cr_arr = [], [], []
    a_n, a_e, a_hdg, a_cas, a_ata = [], [], [], [], []
    b_n, b_e, b_hdg, b_cas = [], [], [], []
    for t, state in ticks:
        if t > window_full_s: break
        a = state.get("A0100", {})
        b = state.get("B0100", {})
        if "lon" not in a or "lon" not in b:
            continue
        t_arr.append(t)
        dist_arr.append(a.get("dist", 0))
        cr_arr.append(a.get("cr", 0))
        an, ae = to_local_ne(a["lon"], a["lat"])
        bn, be = to_local_ne(b["lon"], b["lat"])
        a_n.append(an); a_e.append(ae)
        b_n.append(bn); b_e.append(be)
        a_hdg.append(a.get("hdg", 0)); a_cas.append(a.get("cas", 0))
        a_ata.append(a.get("ata", 999))
        b_hdg.append(b.get("hdg", 0)); b_cas.append(b.get("cas", 0))

    if len(t_arr) < 10:
        return None

    t_arr = np.array(t_arr); dist = np.array(dist_arr); cr = np.array(cr_arr)
    a_n = np.array(a_n); a_e = np.array(a_e); a_hdg = np.array(a_hdg); a_cas = np.array(a_cas)
    a_ata = np.array(a_ata); b_n = np.array(b_n); b_e = np.array(b_e); b_hdg = np.array(b_hdg)
    b_cas = np.array(b_cas)

    # === 1. lead-turn miss 계산 ===
    # 적의 미래 위치 (2초 후) — 적 현 위치 + 적 hdg × 적 CAS × 2초
    LOOKAHEAD_S = 2.0
    KTS_TO_MS = 0.5144
    LOOKAHEAD_M_PER_KTS = LOOKAHEAD_S * KTS_TO_MS  # kts → m for 2s
    # 적 hdg → unit vector (N from north, +clockwise)
    b_hdg_rad = np.radians(b_hdg)
    b_future_n = b_n + np.cos(b_hdg_rad) * b_cas * LOOKAHEAD_M_PER_KTS
    b_future_e = b_e + np.sin(b_hdg_rad) * b_cas * LOOKAHEAD_M_PER_KTS
    # 우리 → 적 미래 위치 벡터
    los_future_n = b_future_n - a_n
    los_future_e = b_future_e - a_e
    # 그 방향의 ideal hdg
    ideal_hdg = np.degrees(np.arctan2(los_future_e, los_future_n)) % 360
    # 현 우리 hdg 와 차이 (signed)
    miss = ((ideal_hdg - a_hdg + 540) % 360) - 180  # -180~180

    # === 2. 결정 모먼트 = closure 첫 양수 → 첫 음수 전환 시점 ===
    decision_idx = None
    for i in range(1, len(cr)):
        if cr[i-1] > 5 and cr[i] < -5:  # 양에서 음으로 뒤집
            decision_idx = i
            break
    decision_t = t_arr[decision_idx] if decision_idx else -1
    decision_dist = dist[decision_idx] if decision_idx else -1
    decision_miss = miss[decision_idx] if decision_idx else 999

    # === 3. 첫 closure peak (양수 최대) — 이게 머지 정점 ===
    cr_pos = cr.copy()
    cr_pos[cr < 0] = -np.inf
    if np.any(np.isfinite(cr_pos)):
        peak_pos_idx = np.argmax(cr_pos)
        cr_peak_pos = cr[peak_pos_idx]
        cr_peak_pos_t = t_arr[peak_pos_idx]
        miss_at_peak = miss[peak_pos_idx]
        dist_at_peak = dist[peak_pos_idx]
    else:
        cr_peak_pos = -999; cr_peak_pos_t = -1
        miss_at_peak = 999; dist_at_peak = -1

    # === 4. 재조우 시점 (8초 후 closure +30 이상 처음 도달) ===
    reencounter_idx = None
    for i in range(int(8 / 0.05), len(t_arr)):
        if cr[i] > 30:
            reencounter_idx = i
            break
    reencounter_t = t_arr[reencounter_idx] if reencounter_idx else -1
    reencounter_dist = dist[reencounter_idx] if reencounter_idx else -1
    reencounter_miss = miss[reencounter_idx] if reencounter_idx else 999

    # === 5. ATA 평균 miss (첫 8초) — pure pursuit lag 가시화 ===
    n8 = int(8 / 0.05)
    miss_8s = miss[:n8]
    avg_abs_miss_8s = np.mean(np.abs(miss_8s))

    return {
        "label": label,
        "t": t_arr,
        "dist": dist,
        "cr": cr,
        "miss": miss,
        "decision_t": decision_t,
        "decision_dist": decision_dist,
        "decision_miss": decision_miss,
        "cr_peak_pos": cr_peak_pos,
        "cr_peak_pos_t": cr_peak_pos_t,
        "miss_at_peak": miss_at_peak,
        "dist_at_peak": dist_at_peak,
        "reencounter_t": reencounter_t,
        "reencounter_dist": reencounter_dist,
        "reencounter_miss": reencounter_miss,
        "avg_abs_miss_8s": avg_abs_miss_8s,
    }


def main():
    OPPS = [
        ("defensive", "replays/20260530_010912_pursuit_chase_btcost_vs_defensive.acmi"),
        ("aggressive", "replays/20260530_010922_pursuit_chase_btcost_vs_aggressive.acmi"),
        ("ace", "replays/20260530_010932_pursuit_chase_btcost_vs_ace.acmi"),
        ("v10", "replays/20260530_010941_pursuit_chase_btcost_vs_adaptive_eagle_v10.acmi"),
        ("v51", "replays/20260530_010951_pursuit_chase_btcost_vs_adaptive_eagle_v51.acmi"),
    ]

    results = []
    for label, path in OPPS:
        r = analyze(label, path)
        if r:
            results.append(r)

    print("\n=== 1. 머지 정점 (closure peak 양수) ===\n")
    print(f"{'OPP':<14} {'peak closure':>14} {'@t(s)':>8} {'dist@peak':>11} {'lead-turn miss@peak (deg)':>26}")
    print("-" * 80)
    for r in results:
        print(f"{r['label']:<14} {r['cr_peak_pos']:>11.0f} kts {r['cr_peak_pos_t']:>7.2f}s "
              f"{r['dist_at_peak']:>9.0f}ft {r['miss_at_peak']:>+22.1f}°")

    print("\n=== 2. 결정 모먼트 (closure +→- 전환) — 머지 끝 ===\n")
    print(f"{'OPP':<14} {'@t(s)':>8} {'dist (ft)':>10} {'lead-turn miss (deg)':>22}")
    print("-" * 60)
    for r in results:
        if r['decision_t'] >= 0:
            print(f"{r['label']:<14} {r['decision_t']:>7.2f}s {r['decision_dist']:>8.0f}ft "
                  f"{r['decision_miss']:>+18.1f}°")
        else:
            print(f"{r['label']:<14} {'없음':>8}")

    print("\n=== 3. 첫 8초 평균 |lead-turn miss| — pure pursuit lag ===\n")
    print(f"{'OPP':<14} {'평균 |miss|':>14}")
    for r in results:
        print(f"{r['label']:<14} {r['avg_abs_miss_8s']:>12.1f}°")

    print("\n=== 4. 8초 후 재조우 (closure +30 이상) ===\n")
    print(f"{'OPP':<14} {'@t(s)':>8} {'dist (ft)':>10} {'lead-turn miss (deg)':>22}")
    print("-" * 60)
    for r in results:
        if r['reencounter_t'] >= 0:
            print(f"{r['label']:<14} {r['reencounter_t']:>7.2f}s {r['reencounter_dist']:>8.0f}ft "
                  f"{r['reencounter_miss']:>+18.1f}°")
        else:
            print(f"{r['label']:<14} {'없음 (8초 후 다시 안 만남)':>30}")

    # === plot: 각 매치 별 closure / lead-turn miss / dist 시계열 ===
    fig, axs = plt.subplots(3, len(results), figsize=(4*len(results), 9), sharex=True)
    for col, r in enumerate(results):
        ax = axs[0, col]
        ax.plot(r['t'], r['cr'], 'g-', linewidth=0.8)
        ax.axhline(0, color='k', alpha=0.4)
        ax.axhline(30, color='blue', alpha=0.3, linestyle='--', label='재조우 임계')
        if r['cr_peak_pos_t'] >= 0:
            ax.axvline(r['cr_peak_pos_t'], color='red', alpha=0.5, linestyle=':')
        if r['decision_t'] >= 0:
            ax.axvline(r['decision_t'], color='purple', alpha=0.5, linestyle='--', label='결정')
        if r['reencounter_t'] >= 0:
            ax.axvline(r['reencounter_t'], color='blue', alpha=0.5, linestyle=':', label='재조우')
        ax.set_title(f"{r['label']}: 첫 머지 +{r['cr_peak_pos']:.0f}kts @{r['cr_peak_pos_t']:.1f}s")
        ax.set_ylabel("closure (kts)" if col == 0 else "")
        ax.legend(fontsize=7, loc='lower right')
        ax.grid(True, alpha=0.3)

        ax = axs[1, col]
        ax.plot(r['t'], r['miss'], 'b-', linewidth=0.8)
        ax.axhline(0, color='k', alpha=0.4)
        ax.axhline(45, color='orange', alpha=0.3, linestyle=':')
        ax.axhline(-45, color='orange', alpha=0.3, linestyle=':')
        ax.set_ylabel("lead-turn miss (deg)\n(우리 hdg - 적 2s 후 위치 hdg)" if col == 0 else "")
        ax.set_ylim(-180, 180)
        ax.grid(True, alpha=0.3)

        ax = axs[2, col]
        ax.plot(r['t'], r['dist'], 'k-', linewidth=0.8)
        ax.axhspan(500, 3000, alpha=0.15, color='orange')
        ax.set_ylabel("dist (ft)" if col == 0 else "")
        ax.set_xlabel("time (s)")
        ax.grid(True, alpha=0.3)

    plt.tight_layout()
    plt.savefig('logs/r15_K_v3/merge_decision.png', dpi=100, bbox_inches='tight')
    plt.close()
    print(f"\nsaved: logs/r15_K_v3/merge_decision.png")


if __name__ == "__main__":
    main()
