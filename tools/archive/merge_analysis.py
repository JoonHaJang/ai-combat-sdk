"""R15-K 머지 phase 분석 — 첫 8초가 사망진단서인지 검증.

각 stalemate 매치의 첫 8초 (160 ticks @ 20Hz) 에서:
  - ATA 진화 (누가 먼저 정렬?)
  - closure peak 시점/값
  - HDG rate — 누가 먼저 회전 시작 (lead turn 흔적)
  - min dist 시점 — 머지 중심점
  - 그 순간의 energy_diff, alt_gap
"""
import re
from pathlib import Path
import numpy as np
import matplotlib.pyplot as plt

T_RE = re.compile(r"T=([\-\d\.eE]+)\|([\-\d\.eE]+)\|([\-\d\.eE]+)")
HDG_RE = re.compile(r"HDG=([\-\d\.eE]+)")
CAS_RE = re.compile(r"CAS=([\-\d\.eE]+)")
ATA_RE = re.compile(r"ATA=([\-\d\.eE]+)")
AA_RE = re.compile(r"AA=([\-\d\.eE]+)")
DIST_RE = re.compile(r"Distance=([\-\d\.eE]+)")
CR_RE = re.compile(r"ClosureRate=([\-\d\.eE]+)")


def parse(path):
    """Per-tick per-object ACMI extraction."""
    ticks = {}  # time → {uid: dict}
    cur_time = 0.0
    with open(path, 'r', encoding='utf-8-sig') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            if line.startswith('#'):
                try: cur_time = float(line[1:])
                except: pass
                continue
            if not (line.startswith('A0100') or line.startswith('B0100')):
                continue
            uid = line[:5]
            d = ticks.setdefault(cur_time, {}).setdefault(uid, {})
            for rx, key in ((HDG_RE, "hdg"), (CAS_RE, "cas"),
                             (ATA_RE, "ata"), (AA_RE, "aa"),
                             (DIST_RE, "dist"), (CR_RE, "cr")):
                m = rx.search(line)
                if m:
                    d[key] = float(m.group(1))
            m = T_RE.search(line)
            if m:
                d["lon"] = float(m.group(1))
                d["lat"] = float(m.group(2))
                d["alt"] = float(m.group(3))
    return sorted(ticks.items())


def extract_arrays(ticks, window_s=8.0):
    """첫 window_s 초 만 추출. arrays of t, dist, cr, ata_a, ata_b, hdg_a, hdg_b, cas_a, cas_b, alt_a, alt_b."""
    out = {k: [] for k in ("t", "dist", "cr",
                            "ata_a", "ata_b", "hdg_a", "hdg_b",
                            "cas_a", "cas_b", "alt_a", "alt_b")}
    for t, state in ticks:
        if t > window_s:
            break
        a = state.get("A0100", {})
        b = state.get("B0100", {})
        out["t"].append(t)
        out["dist"].append(a.get("dist", 0))
        out["cr"].append(a.get("cr", 0))
        out["ata_a"].append(a.get("ata", 999))
        out["ata_b"].append(b.get("ata", 999))
        out["hdg_a"].append(a.get("hdg", 0))
        out["hdg_b"].append(b.get("hdg", 0))
        out["cas_a"].append(a.get("cas", 0))
        out["cas_b"].append(b.get("cas", 0))
        out["alt_a"].append(a.get("alt", 0))
        out["alt_b"].append(b.get("alt", 0))
    for k in out:
        out[k] = np.array(out[k])
    return out


def hdg_rate(hdg_arr, t_arr):
    """unwrap + gradient → deg/s."""
    if len(hdg_arr) < 2:
        return np.array([0.0])
    h_uw = np.degrees(np.unwrap(np.radians(hdg_arr)))
    return np.gradient(h_uw, t_arr)


def analyze(label, path):
    ticks = parse(path)
    if not ticks:
        return None
    d = extract_arrays(ticks, window_s=8.0)
    if len(d["t"]) < 5:
        return None

    # turn rate
    omega_a = hdg_rate(d["hdg_a"], d["t"])
    omega_b = hdg_rate(d["hdg_b"], d["t"])

    # 첫 회전 시작 시점 (|omega| > 10 deg/s 처음 도달)
    a_turn_start = next((i for i, w in enumerate(omega_a) if abs(w) > 10), len(omega_a))
    b_turn_start = next((i for i, w in enumerate(omega_b) if abs(w) > 10), len(omega_b))

    # 초기 0 값 제외 (ACMI 첫 ticks 에 T= 안 적힐 수 있음)
    valid_dist = (d["dist"] > 100)
    if not np.any(valid_dist):
        return None
    cr_valid = d["cr"][valid_dist]
    dist_valid = d["dist"][valid_dist]
    t_valid = d["t"][valid_dist]
    ata_a_valid = d["ata_a"][valid_dist]
    ata_b_valid = d["ata_b"][valid_dist]
    alt_a_valid = d["alt_a"][valid_dist]
    alt_b_valid = d["alt_b"][valid_dist]
    cas_a_valid = d["cas_a"][valid_dist]
    cas_b_valid = d["cas_b"][valid_dist]

    # closure peak (max approach rate, >0 가장 큰)
    cr_peak_idx = np.argmax(cr_valid)
    cr_peak = cr_valid[cr_peak_idx]
    cr_peak_t = t_valid[cr_peak_idx]

    # min dist
    min_dist_idx = np.argmin(dist_valid)
    min_dist = dist_valid[min_dist_idx]
    min_dist_t = t_valid[min_dist_idx]

    # 그 순간의 ATA
    ata_a_at_min = ata_a_valid[min_dist_idx]
    ata_b_at_min = ata_b_valid[min_dist_idx]

    # ATA 첫 12° 도달 (만약 일어났다면)
    ata_a_lock = next((i for i, a in enumerate(ata_a_valid) if a < 12), -1)
    ata_b_lock = next((i for i, a in enumerate(ata_b_valid) if a < 12), -1)

    # 8초 시점 (끝) 의 정렬 상태
    end_ata_a = d["ata_a"][-1]
    end_ata_b = d["ata_b"][-1]
    end_dist = d["dist"][-1]

    # alt diff / cas diff at min dist
    alt_diff = alt_a_valid[min_dist_idx] - alt_b_valid[min_dist_idx]
    cas_diff = cas_a_valid[min_dist_idx] - cas_b_valid[min_dist_idx]

    return {
        "label": label,
        "n_ticks": len(d["t"]),
        "a_turn_start_t": d["t"][a_turn_start] if a_turn_start < len(d["t"]) else 99,
        "b_turn_start_t": d["t"][b_turn_start] if b_turn_start < len(d["t"]) else 99,
        "cr_peak": cr_peak,
        "cr_peak_t": cr_peak_t,
        "min_dist": min_dist,
        "min_dist_t": min_dist_t,
        "ata_a_at_min": ata_a_at_min,
        "ata_b_at_min": ata_b_at_min,
        "ata_a_lock_t": t_valid[ata_a_lock] if ata_a_lock >= 0 else -1,
        "ata_b_lock_t": t_valid[ata_b_lock] if ata_b_lock >= 0 else -1,
        "end_ata_a": end_ata_a,
        "end_ata_b": end_ata_b,
        "end_dist": end_dist,
        "alt_diff_at_min": alt_diff,
        "cas_diff_at_min": cas_diff,
        "arrays": d,
        "omega_a": omega_a,
        "omega_b": omega_b,
    }


def plot_merge(results, out_path):
    fig, axs = plt.subplots(5, len(results), figsize=(4*len(results), 14),
                              sharex=True)
    if len(results) == 1:
        axs = axs[:, None]
    for col, r in enumerate(results):
        if r is None:
            continue
        d = r["arrays"]
        t = d["t"]
        title = f"{r['label']}\nmin_dist {r['min_dist']:.0f}ft @t={r['min_dist_t']:.1f}s"

        ax = axs[0, col]
        ax.plot(t, d["dist"], 'k-')
        ax.axvline(r["min_dist_t"], color='red', alpha=0.4, linestyle='--')
        ax.set_ylabel("dist (ft)" if col == 0 else "")
        ax.set_title(title, fontsize=10)
        ax.grid(True, alpha=0.3)

        ax = axs[1, col]
        ax.plot(t, d["cr"], 'g-')
        ax.axhline(0, color='k', alpha=0.3)
        ax.set_ylabel("closure (kts)" if col == 0 else "")
        ax.grid(True, alpha=0.3)

        ax = axs[2, col]
        ax.plot(t, d["ata_a"], 'b-', label='us ATA')
        ax.plot(t, d["ata_b"], 'r-', label='opp ATA')
        ax.axhline(12, color='orange', alpha=0.4, linestyle='--')
        ax.set_ylabel("ATA (deg)" if col == 0 else "")
        ax.legend(fontsize=8)
        ax.grid(True, alpha=0.3)

        ax = axs[3, col]
        ax.plot(t, r["omega_a"], 'b-', label='us omega')
        ax.plot(t, r["omega_b"], 'r-', label='opp omega')
        ax.axhline(0, color='k', alpha=0.3)
        ax.axhline(10, color='orange', alpha=0.3, linestyle=':')
        ax.axhline(-10, color='orange', alpha=0.3, linestyle=':')
        ax.axvline(r["a_turn_start_t"], color='blue', alpha=0.4, linestyle='--')
        ax.axvline(r["b_turn_start_t"], color='red', alpha=0.4, linestyle='--')
        ax.set_ylabel("omega (deg/s)" if col == 0 else "")
        ax.legend(fontsize=8)
        ax.grid(True, alpha=0.3)

        ax = axs[4, col]
        ax.plot(t, d["cas_a"], 'b-', label='us CAS')
        ax.plot(t, d["cas_b"], 'r-', label='opp CAS')
        ax.set_ylabel("CAS (kts)" if col == 0 else "")
        ax.set_xlabel("time (s)")
        ax.legend(fontsize=8)
        ax.grid(True, alpha=0.3)

    plt.tight_layout()
    plt.savefig(out_path, dpi=100, bbox_inches="tight")
    plt.close()
    print(f"saved: {out_path}")


def main():
    OPPS = [
        ("defensive (C)", "replays/20260530_010912_pursuit_chase_btcost_vs_defensive.acmi"),
        ("aggressive (C)", "replays/20260530_010922_pursuit_chase_btcost_vs_aggressive.acmi"),
        ("ace (D)", "replays/20260530_010932_pursuit_chase_btcost_vs_ace.acmi"),
        ("v10 (A')", "replays/20260530_010941_pursuit_chase_btcost_vs_adaptive_eagle_v10.acmi"),
        ("v51 (B)", "replays/20260530_010951_pursuit_chase_btcost_vs_adaptive_eagle_v51.acmi"),
    ]

    results = []
    for label, path in OPPS:
        r = analyze(label, path)
        if r:
            results.append(r)

    # 종합 표
    print("\n=== 머지 phase (첫 8초) 분석 ===\n")
    print(f"{'OPP':<18} {'우리 회전 시작':>14} {'적 회전 시작':>13} {'먼저 회전':>10}  "
          f"{'closure peak':>13} {'@t(s)':>8}  {'min_dist (ft)':>14} {'@t(s)':>7}  "
          f"{'우리 ATA@min':>13} {'적 ATA@min':>11}  {'alt diff (m)':>13} {'cas diff':>10}")
    print("-" * 200)
    for r in results:
        winner = "우리" if r['a_turn_start_t'] < r['b_turn_start_t'] else \
                 "적" if r['b_turn_start_t'] < r['a_turn_start_t'] else "동시"
        print(f"{r['label']:<18} {r['a_turn_start_t']:>13.2f}s {r['b_turn_start_t']:>12.2f}s {winner:>10}  "
              f"{r['cr_peak']:>10.0f} kts {r['cr_peak_t']:>7.2f}s  "
              f"{r['min_dist']:>13.0f}ft {r['min_dist_t']:>6.2f}s  "
              f"{r['ata_a_at_min']:>11.1f}° {r['ata_b_at_min']:>9.1f}°  "
              f"{r['alt_diff_at_min']:>+11.0f}m {r['cas_diff_at_min']:>+8.1f}")

    print(f"\n8초 후 상태:")
    print(f"{'OPP':<18} {'8s dist':>10} {'우리 ATA':>10} {'적 ATA':>9}  {'우리 ATA<12 시점':>16} {'적 ATA<12 시점':>16}")
    print("-" * 90)
    for r in results:
        lock_a = f"{r['ata_a_lock_t']:.2f}s" if r['ata_a_lock_t'] >= 0 else "안 됨"
        lock_b = f"{r['ata_b_lock_t']:.2f}s" if r['ata_b_lock_t'] >= 0 else "안 됨"
        print(f"{r['label']:<18} {r['end_dist']:>9.0f}ft {r['end_ata_a']:>9.1f}° {r['end_ata_b']:>8.1f}°  "
              f"{lock_a:>16} {lock_b:>16}")

    # plot
    plot_merge(results, "logs/r15_K_v3/merge_phase.png")


if __name__ == "__main__":
    main()
