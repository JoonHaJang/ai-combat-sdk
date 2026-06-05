"""R15-J (2026-05-29 사용자 제안): 3D 매치 궤도 시각화 — 정체 원인 직접 관찰.

ACMI 리플레이 파일 파싱 → matplotlib 3D plot:
  - 아군 (Blue, A0100) / 적군 (Red, B0100) 궤적
  - 속도 벡터 (heading 방향 × 속도)
  - 시간 마커 (10초 간격)
  - WEZ 위치 (양측 정렬 + 거리 적정 순간)
  - 정렬 LOS 라인 (특정 tick 의 LOS 시각)

usage:
    python tools/plot_match_3d.py --replay <replay.acmi> [--out plot.png] [--key-ticks N]
"""
from __future__ import annotations
import argparse
import re
import sys
from pathlib import Path

import numpy as np
import matplotlib.pyplot as plt
from mpl_toolkits.mplot3d import Axes3D  # noqa: F401
from matplotlib.lines import Line2D


T_RE = re.compile(
    r"T=([\-\d\.eE]+)\|([\-\d\.eE]+)\|([\-\d\.eE]+)"
    r"(?:\|([\-\d\.eE]+)\|([\-\d\.eE]+)\|([\-\d\.eE]+))?"
)
HDG_RE = re.compile(r"HDG=([\-\d\.eE]+)")
CAS_RE = re.compile(r"CAS=([\-\d\.eE]+)")
INWEZ_RE = re.compile(r"InWEZ=(True|False)")
HEALTH_RE = re.compile(r"Health=([\-\d\.eE]+)")
ATA_RE = re.compile(r"ATA=([\-\d\.eE]+)")
DIST_RE = re.compile(r"Distance=([\-\d\.eE]+)")


def parse_acmi(path: Path):
    """ACMI → per-tick per-agent state dict."""
    ticks = []  # list of (sim_time_s, {agent: {lon, lat, alt, hdg, cas, ...}})
    cur_time = 0.0
    cur_state = None
    agents = {}
    with open(path, "r", encoding="utf-8-sig") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            if line.startswith("#"):
                if cur_state is not None:
                    ticks.append((cur_time, cur_state))
                try:
                    cur_time = float(line[1:])
                except ValueError:
                    pass
                cur_state = {}
                continue
            # 기록 시작 전 헤더
            if cur_state is None:
                continue
            # uid,T=...,...
            parts = line.split(",", 1)
            uid = parts[0].strip()
            if uid not in ("A0100", "B0100"):
                continue
            rest = parts[1] if len(parts) > 1 else ""
            entry = cur_state.setdefault(uid, {})
            m = T_RE.search(rest)
            if m:
                entry["lon"] = float(m.group(1))
                entry["lat"] = float(m.group(2))
                entry["alt"] = float(m.group(3))
                if m.group(4) is not None:
                    entry["roll"] = float(m.group(4))
                    entry["pitch"] = float(m.group(5))
                    entry["yaw"] = float(m.group(6))
            m = HDG_RE.search(rest)
            if m:
                entry["hdg"] = float(m.group(1))
            m = CAS_RE.search(rest)
            if m:
                entry["cas"] = float(m.group(1))
            m = INWEZ_RE.search(rest)
            if m:
                entry["in_wez"] = (m.group(1) == "True")
            m = HEALTH_RE.search(rest)
            if m:
                entry["health"] = float(m.group(1))
            m = ATA_RE.search(rest)
            if m:
                entry["ata"] = float(m.group(1))
            m = DIST_RE.search(rest)
            if m:
                entry["dist"] = float(m.group(1))
    if cur_state is not None:
        ticks.append((cur_time, cur_state))
    return ticks


def lla_to_ned(lon, lat, alt, lon0, lat0, alt0):
    """Quick LLA → local NED (approx, flat-earth)."""
    R = 6378137.0
    dlat = np.radians(lat - lat0)
    dlon = np.radians(lon - lon0)
    n = dlat * R
    e = dlon * R * np.cos(np.radians(lat0))
    u = alt - alt0
    return n, e, u


def extract_trajectory(ticks):
    """Per-agent: arrays of positions, headings, speeds, times."""
    if not ticks:
        return {}
    # Reference at first tick
    a0 = ticks[0][1].get("A0100", {})
    lon0 = a0.get("lon", 120.0)
    lat0 = a0.get("lat", 60.0)
    alt0 = 0.0
    out = {"A0100": {"t": [], "n": [], "e": [], "u": [], "hdg": [], "cas": [],
                    "in_wez": [], "health": [], "ata": [], "dist": []},
           "B0100": {"t": [], "n": [], "e": [], "u": [], "hdg": [], "cas": [],
                    "in_wez": [], "health": [], "ata": [], "dist": []}}
    for t, state in ticks:
        for uid in ("A0100", "B0100"):
            e = state.get(uid)
            if not e or "lon" not in e:
                continue
            n, ee, u = lla_to_ned(e["lon"], e["lat"], e["alt"], lon0, lat0, alt0)
            out[uid]["t"].append(t)
            out[uid]["n"].append(n)
            out[uid]["e"].append(ee)
            out[uid]["u"].append(u)
            out[uid]["hdg"].append(e.get("hdg", 0.0))
            out[uid]["cas"].append(e.get("cas", 0.0))
            out[uid]["in_wez"].append(e.get("in_wez", False))
            out[uid]["health"].append(e.get("health", 100.0))
            out[uid]["ata"].append(e.get("ata", 999.0))
            out[uid]["dist"].append(e.get("dist", 0.0))
    return out


def plot_3d(traj, title: str, out: Path, key_tick_step=50):
    fig = plt.figure(figsize=(15, 10))
    ax = fig.add_subplot(2, 2, 1, projection="3d")

    a = traj["A0100"]
    b = traj["B0100"]
    if not a["n"] or not b["n"]:
        print("ERROR: missing trajectory data")
        return

    # 궤적
    ax.plot(a["e"], a["n"], a["u"], "b-", linewidth=1.0, alpha=0.7, label="us (A0100)")
    ax.plot(b["e"], b["n"], b["u"], "r-", linewidth=1.0, alpha=0.7, label="opp (B0100)")
    # 시작 / 끝 마커
    ax.scatter([a["e"][0]], [a["n"][0]], [a["u"][0]], c="blue", marker="o", s=80, label="us start")
    ax.scatter([b["e"][0]], [b["n"][0]], [b["u"][0]], c="red", marker="o", s=80, label="opp start")
    ax.scatter([a["e"][-1]], [a["n"][-1]], [a["u"][-1]], c="blue", marker="^", s=80, label="us end")
    ax.scatter([b["e"][-1]], [b["n"][-1]], [b["u"][-1]], c="red", marker="^", s=80, label="opp end")

    # 속도 벡터 (heading 방향 × CAS)
    n_steps = len(a["n"])
    for i in range(0, n_steps, key_tick_step):
        for src, color in ((a, "blue"), (b, "red")):
            if i >= len(src["n"]):
                continue
            hdg_rad = np.radians(src["hdg"][i])
            v_scale = src["cas"][i] * 1.0  # kts → m approx scale
            # NED: N=+x (north), E=+y, U=+z. heading=yaw (deg from N, +cw).
            vn = v_scale * np.cos(hdg_rad)
            ve = v_scale * np.sin(hdg_rad)
            ax.quiver(src["e"][i], src["n"][i], src["u"][i],
                      ve, vn, 0, color=color, alpha=0.4, length=1.0,
                      arrow_length_ratio=0.3, linewidth=0.8)

    # WEZ 모먼트 (양쪽 in_wez 사용)
    wez_indices_us = [i for i in range(n_steps)
                       if i < len(a["in_wez"]) and a["in_wez"][i]]
    if wez_indices_us:
        ax.scatter([a["e"][i] for i in wez_indices_us],
                   [a["n"][i] for i in wez_indices_us],
                   [a["u"][i] for i in wez_indices_us],
                   c="lime", marker="*", s=100, label="us in WEZ")

    ax.set_xlabel("East (m)")
    ax.set_ylabel("North (m)")
    ax.set_zlabel("Up (m)")
    ax.set_title(f"3D trajectory: {title}")
    ax.legend(loc="upper right", fontsize=7)
    ax.view_init(elev=20, azim=-60)

    # Top-down (East-North)
    ax2 = fig.add_subplot(2, 2, 2)
    ax2.plot(a["e"], a["n"], "b-", alpha=0.7, label="us")
    ax2.plot(b["e"], b["n"], "r-", alpha=0.7, label="opp")
    ax2.scatter([a["e"][0]], [a["n"][0]], c="blue", marker="o", s=50)
    ax2.scatter([b["e"][0]], [b["n"][0]], c="red", marker="o", s=50)
    ax2.scatter([a["e"][-1]], [a["n"][-1]], c="blue", marker="^", s=50)
    ax2.scatter([b["e"][-1]], [b["n"][-1]], c="red", marker="^", s=50)
    if wez_indices_us:
        ax2.scatter([a["e"][i] for i in wez_indices_us],
                    [a["n"][i] for i in wez_indices_us],
                    c="lime", marker="*", s=50, label="WEZ")
    ax2.set_xlabel("East (m)")
    ax2.set_ylabel("North (m)")
    ax2.set_title("Top-down (E-N)")
    ax2.legend(fontsize=7)
    ax2.grid(True, alpha=0.3)
    ax2.set_aspect("equal")

    # 시간 대 dist
    ax3 = fig.add_subplot(2, 2, 3)
    ax3.plot(a["t"], a["dist"], "k-", alpha=0.6, label="distance")
    ax3.axhline(y=914.4 / 0.3048, color="orange", linestyle="--", alpha=0.5, label="WEZ outer (3000ft)")
    ax3.axhline(y=152.4 / 0.3048, color="red", linestyle="--", alpha=0.5, label="WEZ inner (500ft)")
    ax3.set_xlabel("time (s)")
    ax3.set_ylabel("distance (ft)")
    ax3.set_title("Distance over time")
    ax3.legend(fontsize=7)
    ax3.grid(True, alpha=0.3)

    # ATA + Health
    ax4 = fig.add_subplot(2, 2, 4)
    ax4.plot(a["t"], a["ata"], "b-", alpha=0.7, label="our ATA (°)")
    ax4.axhline(y=12, color="orange", linestyle="--", alpha=0.5, label="WEZ angle (12°)")
    ax4.set_xlabel("time (s)")
    ax4.set_ylabel("ATA (deg)")
    ax4.set_title("ATA / Health")
    ax4.set_ylim(0, 180)
    ax4.legend(loc="upper left", fontsize=7)
    ax4.grid(True, alpha=0.3)
    ax4b = ax4.twinx()
    ax4b.plot(a["t"], a["health"], "b:", alpha=0.6, label="us HP")
    ax4b.plot(b["t"], b["health"], "r:", alpha=0.6, label="opp HP")
    ax4b.set_ylabel("HP")
    ax4b.set_ylim(0, 105)
    ax4b.legend(loc="upper right", fontsize=7)

    plt.tight_layout()
    plt.savefig(out, dpi=100, bbox_inches="tight")
    plt.close()
    print(f"saved: {out}")
    # 추가 통계 print
    print(f"  ticks: {n_steps}")
    print(f"  WEZ ticks (우리): {len(wez_indices_us)}")
    print(f"  final HP us={a['health'][-1]:.1f} opp={b['health'][-1]:.1f}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--replay", required=True, help=".acmi replay path")
    ap.add_argument("--out", help="output PNG path (default: same dir as replay)")
    ap.add_argument("--key-ticks", type=int, default=80,
                    help="velocity vector every N ticks")
    args = ap.parse_args()

    replay = Path(args.replay)
    if not replay.exists():
        print(f"ERROR: {replay} not found")
        sys.exit(1)

    out = Path(args.out) if args.out else replay.with_suffix(".3d.png")

    print(f"parsing {replay}...")
    ticks = parse_acmi(replay)
    print(f"  parsed {len(ticks)} ticks")
    traj = extract_trajectory(ticks)
    if not traj or not traj["A0100"]["n"]:
        print("ERROR: empty trajectory")
        sys.exit(1)

    title = replay.stem
    plot_3d(traj, title, out, key_tick_step=args.key_ticks)


if __name__ == "__main__":
    main()
