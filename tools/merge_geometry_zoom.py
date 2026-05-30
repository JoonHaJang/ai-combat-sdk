"""R15-K (b): 5 매치 별 closure peak / 재조우 시점 기하 *확대* 분석.

각 매치 별 큰 그림 (한 매치 = 한 figure):
  panel 1: 전체 dist/closure 시계열 (마커: peak, re-encounter)
  panel 2: 전체 lead-turn miss 시계열
  panel 3: peak/re-encounter ±3초 zoom — top-down geometry
            (우리 위치/heading, 적 위치/heading, 적 미래 2s 점, ideal LOS)
  panel 4: 동일 시간대 ATA, dist, closure 확대
  panel 5: K10 머지 결정기가 *그 시점에* 활성화될 조건 (closure +30 이상, dist 2-5km, etc.)
"""
import re
from pathlib import Path
import numpy as np
import matplotlib.pyplot as plt
from matplotlib.patches import FancyArrowPatch

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


def lla_to_ne(lon, lat, lon0=120.0, lat0=60.0):
    n = (lat - lat0) * 111000
    e = (lon - lon0) * 111000 * np.cos(np.radians(lat0))
    return n, e


def extract(ticks, t_max=75.0):
    rows = []
    for t, st in ticks:
        if t > t_max: break
        a = st.get("A0100", {})
        b = st.get("B0100", {})
        if "lon" not in a or "lon" not in b: continue
        an, ae = lla_to_ne(a["lon"], a["lat"])
        bn, be = lla_to_ne(b["lon"], b["lat"])
        rows.append({
            "t": t, "dist": a.get("dist", 0), "cr": a.get("cr", 0),
            "a_n": an, "a_e": ae, "a_hdg": a.get("hdg", 0), "a_cas": a.get("cas", 0),
            "a_ata": a.get("ata", 999),
            "b_n": bn, "b_e": be, "b_hdg": b.get("hdg", 0), "b_cas": b.get("cas", 0),
        })
    return rows


def find_events(rows):
    """closure peak (양수 max) + 재조우 (8초 후 +30 첫 도달) 시점 idx."""
    cr = np.array([r["cr"] for r in rows])
    t = np.array([r["t"] for r in rows])

    peak_idx = None
    if np.any(cr > 0):
        cr_pos = cr.copy()
        cr_pos[cr <= 0] = -np.inf
        peak_idx = int(np.argmax(cr_pos))

    reenc_idx = None
    for i in range(int(8 / 0.05), len(cr)):
        if cr[i] > 30:
            reenc_idx = i
            break

    return peak_idx, reenc_idx


def plot_match(label, rows, peak_idx, reenc_idx, out_path):
    t = np.array([r["t"] for r in rows])
    dist = np.array([r["dist"] for r in rows])
    cr = np.array([r["cr"] for r in rows])
    a_n = np.array([r["a_n"] for r in rows])
    a_e = np.array([r["a_e"] for r in rows])
    a_hdg = np.array([r["a_hdg"] for r in rows])
    a_cas = np.array([r["a_cas"] for r in rows])
    a_ata = np.array([r["a_ata"] for r in rows])
    b_n = np.array([r["b_n"] for r in rows])
    b_e = np.array([r["b_e"] for r in rows])
    b_hdg = np.array([r["b_hdg"] for r in rows])
    b_cas = np.array([r["b_cas"] for r in rows])

    # lead-turn miss
    LOOKAHEAD_S = 2.0
    KTS_TO_MS = 0.5144
    b_hdg_r = np.radians(b_hdg)
    b_fut_n = b_n + np.cos(b_hdg_r) * b_cas * KTS_TO_MS * LOOKAHEAD_S
    b_fut_e = b_e + np.sin(b_hdg_r) * b_cas * KTS_TO_MS * LOOKAHEAD_S
    los_n = b_fut_n - a_n; los_e = b_fut_e - a_e
    ideal_hdg = np.degrees(np.arctan2(los_e, los_n)) % 360
    miss = ((ideal_hdg - a_hdg + 540) % 360) - 180

    fig = plt.figure(figsize=(18, 10))
    gs = fig.add_gridspec(3, 4)

    # Row 1: full timeline
    ax1 = fig.add_subplot(gs[0, :2])
    ax1.plot(t, cr, 'g-', linewidth=0.7, label='closure')
    ax1.axhline(0, color='k', alpha=0.3)
    ax1.axhline(30, color='b', alpha=0.3, linestyle=':')
    if peak_idx is not None:
        ax1.axvline(t[peak_idx], color='red', linestyle='--', alpha=0.6,
                    label=f'peak +{cr[peak_idx]:.0f}kts @{t[peak_idx]:.1f}s')
        ax1.scatter([t[peak_idx]], [cr[peak_idx]], c='red', s=80, zorder=5)
    if reenc_idx is not None:
        ax1.axvline(t[reenc_idx], color='blue', linestyle=':', alpha=0.6,
                    label=f're-encounter @{t[reenc_idx]:.1f}s')
    ax1.set_xlabel('time (s)'); ax1.set_ylabel('closure (kts)')
    ax1.set_title(f'{label}: full closure timeline')
    ax1.legend(fontsize=9)
    ax1.grid(True, alpha=0.3)

    ax2 = fig.add_subplot(gs[0, 2:])
    ax2.plot(t, miss, 'b-', linewidth=0.7, label='lead-turn miss')
    ax2.axhline(0, color='k', alpha=0.3)
    ax2.axhline(45, color='orange', alpha=0.3, linestyle=':')
    ax2.axhline(-45, color='orange', alpha=0.3, linestyle=':')
    if peak_idx is not None:
        ax2.axvline(t[peak_idx], color='red', linestyle='--', alpha=0.6)
    if reenc_idx is not None:
        ax2.axvline(t[reenc_idx], color='blue', linestyle=':', alpha=0.6)
    ax2.set_xlabel('time (s)'); ax2.set_ylabel('miss (deg)')
    ax2.set_title(f'{label}: full lead-turn miss timeline')
    ax2.set_ylim(-180, 180)
    ax2.grid(True, alpha=0.3)

    # Row 2: zoom around peak (or re-encounter)
    event_idx = peak_idx if peak_idx is not None else reenc_idx
    event_t = t[event_idx] if event_idx is not None else 4.0
    zoom_start = max(0, event_idx - int(3/0.05)) if event_idx else 0
    zoom_end = min(len(rows), event_idx + int(3/0.05)) if event_idx else int(6/0.05)

    # top-down zoom geometry — peak ±3초
    ax3 = fig.add_subplot(gs[1:, :2])
    a_n_z = a_n[zoom_start:zoom_end]; a_e_z = a_e[zoom_start:zoom_end]
    b_n_z = b_n[zoom_start:zoom_end]; b_e_z = b_e[zoom_start:zoom_end]
    t_z = t[zoom_start:zoom_end]
    # gradient color by time
    cmap_us = plt.get_cmap('Blues')
    cmap_op = plt.get_cmap('Reds')
    norm = plt.Normalize(t_z[0] if len(t_z) else 0, t_z[-1] if len(t_z) else 1)
    for i in range(0, len(a_n_z) - 1, max(1, len(a_n_z)//100)):
        ax3.plot(a_e_z[i:i+2], a_n_z[i:i+2], color=cmap_us(norm(t_z[i])), linewidth=1.2)
        ax3.plot(b_e_z[i:i+2], b_n_z[i:i+2], color=cmap_op(norm(t_z[i])), linewidth=1.2)
    # at event_idx, draw vectors
    if event_idx is not None and zoom_start <= event_idx < zoom_end:
        i = event_idx
        # velocity vectors (small)
        scale = 80
        ax3.arrow(a_e[i], a_n[i],
                   np.sin(np.radians(a_hdg[i])) * scale,
                   np.cos(np.radians(a_hdg[i])) * scale,
                   color='blue', width=15, head_width=80, alpha=0.7,
                   label=f'us hdg={a_hdg[i]:.0f}°')
        ax3.arrow(b_e[i], b_n[i],
                   np.sin(np.radians(b_hdg[i])) * scale,
                   np.cos(np.radians(b_hdg[i])) * scale,
                   color='red', width=15, head_width=80, alpha=0.7,
                   label=f'opp hdg={b_hdg[i]:.0f}°')
        # 적 미래 2s 위치
        ax3.scatter([b_fut_e[i]], [b_fut_n[i]], c='red', marker='*', s=300,
                    edgecolors='black', label=f'opp 2s 후 점')
        # ideal LOS line (우리 → 적 미래)
        ax3.plot([a_e[i], b_fut_e[i]], [a_n[i], b_fut_n[i]],
                  'g--', alpha=0.5, label=f'ideal hdg={ideal_hdg[i]:.0f}°, miss={miss[i]:+.0f}°')
        ax3.scatter([a_e[i]], [a_n[i]], c='blue', marker='o', s=100, zorder=5)
        ax3.scatter([b_e[i]], [b_n[i]], c='red', marker='o', s=100, zorder=5)
    ax3.set_xlabel('East (m)'); ax3.set_ylabel('North (m)')
    ax3.set_title(f'{label}: top-down geometry @ event t={event_t:.1f}s ±3s')
    ax3.legend(fontsize=8, loc='upper right')
    ax3.grid(True, alpha=0.3)
    ax3.set_aspect('equal')

    # zoom timeseries
    ax4 = fig.add_subplot(gs[1, 2:])
    ax4.plot(t_z, cr[zoom_start:zoom_end], 'g-', linewidth=1.5)
    ax4.axhline(0, color='k', alpha=0.3)
    if event_idx is not None: ax4.axvline(event_t, color='red', linestyle='--', alpha=0.5)
    ax4.set_ylabel('closure (kts)'); ax4.set_title(f'closure zoom (event ±3s)')
    ax4.grid(True, alpha=0.3)

    ax5 = fig.add_subplot(gs[2, 2:])
    ax5.plot(t_z, a_ata[zoom_start:zoom_end], 'b-', linewidth=1.5, label='our ATA')
    ax5.plot(t_z, miss[zoom_start:zoom_end], 'purple', linewidth=1.0, label='lead miss')
    ax5.axhline(12, color='orange', linestyle=':', alpha=0.5)
    ax5.axhline(0, color='k', alpha=0.3)
    if event_idx is not None: ax5.axvline(event_t, color='red', linestyle='--', alpha=0.5)
    ax5.set_ylabel('deg'); ax5.set_xlabel('time (s)')
    ax5.set_title('ATA + lead-turn miss zoom')
    ax5.legend(fontsize=8)
    ax5.grid(True, alpha=0.3)

    plt.tight_layout()
    plt.savefig(out_path, dpi=100, bbox_inches='tight')
    plt.close()
    print(f"saved: {out_path}")

    # 결정기 활성 시점 검출 + 출력
    print(f"\n[{label}] 머지 결정기 K10 활성화 후보 시점:")
    print(f"  closure>30 + 2000<dist<5000ft + miss>30° 조건 만족 모든 시점:")
    triggers = 0
    last_t = -10
    for i in range(len(rows)):
        if cr[i] > 30 and 2000 < dist[i] < 5000 and abs(miss[i]) > 30 and (t[i] - last_t) > 0.5:
            triggers += 1
            if triggers <= 5:  # 처음 5개만
                print(f"    t={t[i]:.2f}s  dist={dist[i]:.0f}ft  closure=+{cr[i]:.0f}kts  miss={miss[i]:+.1f}°  ata={a_ata[i]:.0f}°")
            last_t = t[i]
    print(f"  → 총 {triggers}회 활성화 윈도우 있음 (0.5s 이상 간격)")


def main():
    OPPS = [
        ("defensive", "replays/20260530_010912_pursuit_chase_btcost_vs_defensive.acmi"),
        ("aggressive", "replays/20260530_010922_pursuit_chase_btcost_vs_aggressive.acmi"),
        ("ace", "replays/20260530_010932_pursuit_chase_btcost_vs_ace.acmi"),
        ("v10", "replays/20260530_010941_pursuit_chase_btcost_vs_adaptive_eagle_v10.acmi"),
        ("v51", "replays/20260530_010951_pursuit_chase_btcost_vs_adaptive_eagle_v51.acmi"),
    ]

    for label, path in OPPS:
        ticks = parse(path)
        rows = extract(ticks)
        peak_idx, reenc_idx = find_events(rows)
        plot_match(label, rows, peak_idx, reenc_idx, f"logs/r15_K_v3/zoom_{label}.png")
        print()


if __name__ == "__main__":
    main()
