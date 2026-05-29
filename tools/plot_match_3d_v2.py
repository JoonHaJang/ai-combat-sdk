"""R15-J v2 (2026-05-29): bt_vs_bt 매치 종합 3D + 시계열 + 자동 패턴 분류 진단 도구.

K 가설 검증 위한 모든 derived metric 포함:
  파생 데이터:
    - closure_rate (numerical diff of dist)
    - turn_rate omega (numerical diff of HDG)
    - phase difference HDG_us - HDG_opp
    - WEZ dwell segments (ATA<12 + WEZ dist 연속 구간)
    - energy state Es = alt + V²/(2g)
    - turn radius R = V / omega (per aircraft)
    - circle fit (center + radius) for each aircraft

  자동 분류:
    - Pattern A (co-centric 2-circle): 두 원 중심 가까움 + 비슷한 R
    - Pattern A' (figure-8 lemniscate): HDG 양 aircraft 반대 부호 반복
    - Pattern B (offset spiral): circle 중심 far apart
    - Pattern C (linear extend): dist monotonic increase + HDG 두 aircraft 비슷
    - Pattern D (inside-outside): 두 R 차이 큼 + center 비슷

  14 panel layout (4 row × 4 col, with spans):
    Row 1: 3D trajectory (time gradient) | Top-down E-N (circle fits) | Pattern classification text
    Row 2: Altitude (both) | Distance + WEZ band | ATA+AA (us)
    Row 3: HDG (both) | Phase difference | CAS (both)
    Row 4: Omega (both) | Energy state | WEZ dwell histogram + 진단 텍스트

usage:
    python tools/plot_match_3d_v2.py --replay <acmi> [--out plot.png]
"""
from __future__ import annotations
import argparse
import re
import sys
from pathlib import Path

import numpy as np
import matplotlib.pyplot as plt
from matplotlib import gridspec, colors as mcolors


T_RE = re.compile(
    r"T=([\-\d\.eE]+)\|([\-\d\.eE]+)\|([\-\d\.eE]+)"
    r"(?:\|([\-\d\.eE]+)\|([\-\d\.eE]+)\|([\-\d\.eE]+))?"
)
HDG_RE = re.compile(r"HDG=([\-\d\.eE]+)")
CAS_RE = re.compile(r"CAS=([\-\d\.eE]+)")
INWEZ_RE = re.compile(r"InWEZ=(True|False)")
HEALTH_RE = re.compile(r"Health=([\-\d\.eE]+)")
ATA_RE = re.compile(r"ATA=([\-\d\.eE]+)")
AA_RE = re.compile(r"AA=([\-\d\.eE]+)")
DIST_RE = re.compile(r"Distance=([\-\d\.eE]+)")
CR_RE = re.compile(r"ClosureRate=([\-\d\.eE]+)")


def parse_acmi(path: Path):
    """ACMI → list[(sim_time_s, {agent: {...}})]."""
    ticks = []
    cur_time = 0.0
    cur_state = None
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
            if cur_state is None:
                continue
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
            for rx, key in ((HDG_RE, "hdg"), (CAS_RE, "cas"),
                             (HEALTH_RE, "health"), (ATA_RE, "ata"),
                             (AA_RE, "aa"), (DIST_RE, "dist"), (CR_RE, "cr")):
                m = rx.search(rest)
                if m:
                    entry[key] = float(m.group(1))
            m = INWEZ_RE.search(rest)
            if m:
                entry["in_wez"] = (m.group(1) == "True")
    if cur_state is not None:
        ticks.append((cur_time, cur_state))
    return ticks


def lla_to_ned(lon, lat, alt, lon0, lat0, alt0):
    R = 6378137.0
    dlat = np.radians(lat - lat0)
    dlon = np.radians(lon - lon0)
    n = dlat * R
    e = dlon * R * np.cos(np.radians(lat0))
    u = alt - alt0
    return n, e, u


def extract_trajectory(ticks):
    if not ticks:
        return {}
    a0 = ticks[0][1].get("A0100", {})
    lon0 = a0.get("lon", 120.0)
    lat0 = a0.get("lat", 60.0)
    alt0 = 0.0
    out = {}
    for uid in ("A0100", "B0100"):
        out[uid] = {k: [] for k in ("t", "n", "e", "u", "hdg", "cas",
                                       "in_wez", "health", "ata", "aa",
                                       "dist", "cr")}
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
            out[uid]["aa"].append(e.get("aa", 999.0))
            out[uid]["dist"].append(e.get("dist", 0.0))
            out[uid]["cr"].append(e.get("cr", 0.0))
    # numpy 변환
    for uid in out:
        for k in out[uid]:
            out[uid][k] = np.array(out[uid][k])
    return out


def unwrap_hdg(hdg_deg):
    """HDG 0-360 → continuous (no 0/360 jump)."""
    h = np.radians(hdg_deg)
    h_uw = np.unwrap(h)
    return np.degrees(h_uw)


def compute_derived(traj):
    """파생 metric 계산."""
    out = {}
    for uid in ("A0100", "B0100"):
        d = traj[uid]
        if len(d["t"]) < 2:
            continue
        # numerical derivatives (centered)
        dt = np.diff(d["t"], prepend=d["t"][0] - 0.05)
        dt = np.where(dt < 1e-6, 0.05, dt)
        # turn rate (omega) deg/s — use unwrap to handle 0/360 jump
        hdg_uw = unwrap_hdg(d["hdg"])
        omega = np.gradient(hdg_uw, d["t"])
        # speed in m/s (CAS kts → m/s)
        v_ms = d["cas"] * 0.5144
        # turn radius R = V / omega (omega rad/s)
        omega_rad = np.radians(omega)
        R = np.where(np.abs(omega_rad) > 0.01, v_ms / omega_rad, np.inf)
        # energy state Es = alt + V²/(2g) (m)
        Es = d["u"] + v_ms ** 2 / (2 * 9.81)
        out[uid] = {"omega": omega, "v_ms": v_ms, "R": R, "Es": Es,
                    "hdg_uw": hdg_uw}
    # phase difference (HDG_us - HDG_opp)
    if "A0100" in out and "B0100" in out:
        min_n = min(len(out["A0100"]["hdg_uw"]), len(out["B0100"]["hdg_uw"]))
        out["phase_diff"] = out["A0100"]["hdg_uw"][:min_n] - out["B0100"]["hdg_uw"][:min_n]
        out["phase_diff"] = ((out["phase_diff"] + 180) % 360) - 180  # → [-180, 180]
    return out


def detect_wez_segments(ata, dist, in_wez=None):
    """ATA<12 + 500<dist<3000 ft → WEZ dwell segments.
    Returns list of (start_idx, end_idx, duration_ticks).
    """
    n = len(ata)
    cond = (ata < 12) & (dist > 500) & (dist < 3000)
    segs = []
    in_seg = False
    s = 0
    for i in range(n):
        if cond[i] and not in_seg:
            in_seg = True
            s = i
        elif not cond[i] and in_seg:
            in_seg = False
            segs.append((s, i, i - s))
    if in_seg:
        segs.append((s, n - 1, n - 1 - s))
    return segs


def fit_circle(n_arr, e_arr):
    """간단한 algebraic circle fit (least squares).
    Returns (cn, ce, R) — center north, east, radius.
    """
    if len(n_arr) < 5:
        return None
    A = np.column_stack([2 * n_arr, 2 * e_arr, np.ones(len(n_arr))])
    b = n_arr ** 2 + e_arr ** 2
    try:
        x, *_ = np.linalg.lstsq(A, b, rcond=None)
        cn, ce = x[0], x[1]
        R = np.sqrt(x[2] + cn ** 2 + ce ** 2)
        if R > 30000 or R < 100:
            return None
        return cn, ce, R
    except np.linalg.LinAlgError:
        return None


def classify_pattern(traj, derived) -> str:
    """매치 패턴 자동 분류."""
    a = traj["A0100"]
    b = traj["B0100"]
    if len(a["n"]) < 100:
        return "UNKNOWN"
    # Linear extend: dist monotonic 증가 + HDG variance 작
    dist = a["dist"]
    if len(dist) > 100:
        late_dist = dist[100:].mean()
        early_dist = dist[:100].mean()
        if late_dist > 1.5 * early_dist and late_dist > 8000:
            return "C_linear_extend"
    # circle fit
    fit_a = fit_circle(a["n"], a["e"])
    fit_b = fit_circle(b["n"], b["e"])
    if fit_a and fit_b:
        ca, ea, Ra = fit_a
        cb, eb, Rb = fit_b
        center_dist = np.sqrt((ca - cb) ** 2 + (ea - eb) ** 2)
        radius_ratio = Ra / Rb if Rb > 0 else 99
        if center_dist < min(Ra, Rb) * 0.5 and 0.7 < radius_ratio < 1.4:
            # 비슷한 원, 가까운 중심
            return "A_co_centric_scissors"
        if center_dist > (Ra + Rb) * 0.4:
            return "B_offset_spiral"
        if center_dist < min(Ra, Rb) * 0.5 and not (0.7 < radius_ratio < 1.4):
            return "D_inside_outside"
    # figure-8 detection (phase_diff oscillation)
    if "phase_diff" in derived:
        pd = derived["phase_diff"]
        if pd.std() > 60:
            return "A'_figure8_lemniscate"
    return "E_undetermined"


def plot_comprehensive(traj, derived, title, out_path, dmg_us_to_opp=0, dmg_opp_to_us=0):
    fig = plt.figure(figsize=(20, 16))
    gs = gridspec.GridSpec(4, 4, figure=fig, hspace=0.4, wspace=0.35)

    a = traj["A0100"]
    b = traj["B0100"]
    times = a["t"]
    n_steps = len(times)

    # === Row 1: 3D + Top-down + Diagnosis ===

    # [1,1] 3D trajectory with time gradient
    ax3d = fig.add_subplot(gs[0, 0], projection="3d")
    norm = plt.Normalize(times.min(), times.max())
    cmap_us = plt.get_cmap("Blues")
    cmap_opp = plt.get_cmap("Reds")
    for i in range(0, n_steps - 1, max(1, n_steps // 200)):
        ax3d.plot(a["e"][i:i+2], a["n"][i:i+2], a["u"][i:i+2],
                  color=cmap_us(norm(times[i])), alpha=0.8, linewidth=0.8)
        ax3d.plot(b["e"][i:i+2], b["n"][i:i+2], b["u"][i:i+2],
                  color=cmap_opp(norm(times[i])), alpha=0.8, linewidth=0.8)
    ax3d.scatter([a["e"][0]], [a["n"][0]], [a["u"][0]], c="blue", s=80, marker="o")
    ax3d.scatter([b["e"][0]], [b["n"][0]], [b["u"][0]], c="red", s=80, marker="o")
    ax3d.scatter([a["e"][-1]], [a["n"][-1]], [a["u"][-1]], c="blue", s=80, marker="^")
    ax3d.scatter([b["e"][-1]], [b["n"][-1]], [b["u"][-1]], c="red", s=80, marker="^")
    ax3d.set_xlabel("E (m)")
    ax3d.set_ylabel("N (m)")
    ax3d.set_zlabel("U (m)")
    ax3d.set_title("3D trajectory (time gradient)")
    ax3d.view_init(elev=20, azim=-60)

    # [1,2] Top-down E-N with circle fits + WEZ
    ax_td = fig.add_subplot(gs[0, 1])
    # time gradient on top-down
    for i in range(0, n_steps - 1, max(1, n_steps // 200)):
        ax_td.plot(a["e"][i:i+2], a["n"][i:i+2],
                   color=cmap_us(norm(times[i])), alpha=0.6, linewidth=0.8)
        ax_td.plot(b["e"][i:i+2], b["n"][i:i+2],
                   color=cmap_opp(norm(times[i])), alpha=0.6, linewidth=0.8)
    ax_td.scatter([a["e"][0]], [a["n"][0]], c="blue", marker="o", s=50, label="us start")
    ax_td.scatter([b["e"][0]], [b["n"][0]], c="red", marker="o", s=50, label="opp start")
    # Circle fits
    fit_a = fit_circle(a["n"], a["e"])
    fit_b = fit_circle(b["n"], b["e"])
    if fit_a:
        ca, ea, Ra = fit_a
        theta = np.linspace(0, 2 * np.pi, 100)
        ax_td.plot(ea + Ra * np.cos(theta), ca + Ra * np.sin(theta),
                   "b--", alpha=0.3, label=f"us fit R={Ra:.0f}")
        ax_td.scatter([ea], [ca], c="cyan", marker="x", s=80)
    if fit_b:
        cb, eb, Rb = fit_b
        theta = np.linspace(0, 2 * np.pi, 100)
        ax_td.plot(eb + Rb * np.cos(theta), cb + Rb * np.sin(theta),
                   "r--", alpha=0.3, label=f"opp fit R={Rb:.0f}")
        ax_td.scatter([eb], [cb], c="orange", marker="x", s=80)
    # WEZ dwell markers on us
    wez_segs = detect_wez_segments(a["ata"], a["dist"])
    for s, e, dur in wez_segs:
        ax_td.scatter(a["e"][s:e+1], a["n"][s:e+1],
                      c="lime", marker="*", s=30, alpha=0.6)
    ax_td.set_xlabel("East (m)")
    ax_td.set_ylabel("North (m)")
    ax_td.set_title("Top-down + circle fits")
    ax_td.legend(fontsize=7, loc="upper right")
    ax_td.grid(True, alpha=0.3)
    ax_td.set_aspect("equal")

    # [1,3-4] Pattern classification + diagnosis text
    ax_txt = fig.add_subplot(gs[0, 2:])
    ax_txt.axis("off")
    pattern = classify_pattern(traj, derived)
    # WEZ stats
    wez_count = len(wez_segs)
    wez_total = sum(d for _, _, d in wez_segs)
    wez_max_dwell = max((d for _, _, d in wez_segs), default=0)
    wez_mean_dwell = wez_total / wez_count if wez_count > 0 else 0
    # 분류 보조 stats
    fit_str = ""
    if fit_a and fit_b:
        ca, ea, Ra = fit_a
        cb, eb, Rb = fit_b
        center_dist = np.sqrt((ca - cb) ** 2 + (ea - eb) ** 2)
        fit_str = (f"circle fit: us R={Ra:.0f}m center=({ca:.0f},{ea:.0f}), "
                   f"opp R={Rb:.0f}m center=({cb:.0f},{eb:.0f}), "
                   f"center_dist={center_dist:.0f}m, R_ratio={Ra/Rb:.2f}\n")
    phase_str = ""
    if "phase_diff" in derived:
        pd = derived["phase_diff"]
        phase_str = (f"phase diff: mean={pd.mean():.0f}°, std={pd.std():.0f}°, "
                     f"range=[{pd.min():.0f}, {pd.max():.0f}]°\n")
    es_str = ""
    if "A0100" in derived and "B0100" in derived:
        Es_diff = derived["A0100"]["Es"][-1] - derived["B0100"]["Es"][-1]
        es_str = f"final Es advantage: {Es_diff:+.0f}m (positive=we higher Es)\n"
    diag = (
        f"=== AUTO DIAGNOSIS ===\n"
        f"Pattern: {pattern}\n\n"
        f"=== METRICS ===\n"
        f"ticks: {n_steps}\n"
        f"dmg us→opp: {dmg_us_to_opp:.1f}, opp→us: {dmg_opp_to_us:.1f}\n"
        f"WEZ segments: {wez_count}, total dwell: {wez_total} ticks\n"
        f"  max dwell: {wez_max_dwell}, mean dwell: {wez_mean_dwell:.1f}\n"
        f"{fit_str}{phase_str}{es_str}\n"
        f"=== K HYPOTHESIS HINTS ===\n"
        f"{interpret_pattern(pattern, wez_segs, fit_a, fit_b, derived)}"
    )
    ax_txt.text(0, 1, diag, family="monospace", fontsize=9,
                verticalalignment="top", transform=ax_txt.transAxes,
                bbox=dict(boxstyle="round,pad=0.5", fc="lightyellow", alpha=0.6))

    # === Row 2: alt / dist / ATA+AA ===

    ax_alt = fig.add_subplot(gs[1, 0])
    ax_alt.plot(a["t"], a["u"], "b-", label="us alt")
    ax_alt.plot(b["t"], b["u"], "r-", label="opp alt")
    ax_alt.set_xlabel("time (s)")
    ax_alt.set_ylabel("altitude (m)")
    ax_alt.set_title("Altitude both aircraft")
    ax_alt.legend(fontsize=7)
    ax_alt.grid(True, alpha=0.3)

    ax_dist = fig.add_subplot(gs[1, 1])
    ax_dist.plot(a["t"], a["dist"], "k-", label="dist")
    ax_dist.axhspan(500, 3000, alpha=0.2, color="orange", label="WEZ band")
    ax_dist.axhline(914.4 / 0.3048, color="orange", linestyle="--", alpha=0.5)
    ax_dist.axhline(152.4 / 0.3048, color="red", linestyle="--", alpha=0.5)
    ax_dist.set_xlabel("time (s)")
    ax_dist.set_ylabel("distance (ft)")
    ax_dist.set_title("Distance + WEZ band")
    ax_dist.legend(fontsize=7)
    ax_dist.grid(True, alpha=0.3)

    ax_ata = fig.add_subplot(gs[1, 2])
    ax_ata.plot(a["t"], a["ata"], "b-", alpha=0.8, label="our ATA")
    ax_ata.plot(a["t"], a["aa"], "g-", alpha=0.6, label="our AA")
    ax_ata.axhline(12, color="orange", linestyle="--", alpha=0.5, label="WEZ angle 12°")
    # WEZ dwell band
    for s, e, dur in wez_segs:
        if dur > 0:
            ax_ata.axvspan(a["t"][s], a["t"][e], alpha=0.2, color="lime")
    ax_ata.set_xlabel("time (s)")
    ax_ata.set_ylabel("ATA / AA (deg)")
    ax_ata.set_ylim(0, 180)
    ax_ata.set_title("ATA + AA (us perspective)")
    ax_ata.legend(fontsize=7)
    ax_ata.grid(True, alpha=0.3)

    # Health subpanel embedded
    ax_hp = fig.add_subplot(gs[1, 3])
    ax_hp.plot(a["t"], a["health"], "b-", label="us HP")
    ax_hp.plot(b["t"], b["health"], "r-", label="opp HP")
    ax_hp.set_xlabel("time (s)")
    ax_hp.set_ylabel("HP")
    ax_hp.set_ylim(0, 105)
    ax_hp.set_title("Health both")
    ax_hp.legend(fontsize=7)
    ax_hp.grid(True, alpha=0.3)

    # === Row 3: HDG / phase / CAS / closure ===

    ax_hdg = fig.add_subplot(gs[2, 0])
    if "A0100" in derived and "B0100" in derived:
        ax_hdg.plot(a["t"], derived["A0100"]["hdg_uw"], "b-", label="us HDG (unwrapped)")
        ax_hdg.plot(b["t"], derived["B0100"]["hdg_uw"], "r-", label="opp HDG")
    ax_hdg.set_xlabel("time (s)")
    ax_hdg.set_ylabel("HDG cumulative (deg)")
    ax_hdg.set_title("Heading (unwrapped)")
    ax_hdg.legend(fontsize=7)
    ax_hdg.grid(True, alpha=0.3)

    ax_pd = fig.add_subplot(gs[2, 1])
    if "phase_diff" in derived:
        pd = derived["phase_diff"]
        t_pd = a["t"][:len(pd)]
        ax_pd.plot(t_pd, pd, "purple", label="phase diff")
        ax_pd.axhline(0, color="k", alpha=0.3)
        ax_pd.fill_between(t_pd, -30, 30, color="green", alpha=0.15, label="aligned (<30°)")
    ax_pd.set_xlabel("time (s)")
    ax_pd.set_ylabel("HDG_us - HDG_opp (deg)")
    ax_pd.set_title("Phase difference")
    ax_pd.legend(fontsize=7)
    ax_pd.grid(True, alpha=0.3)

    ax_cas = fig.add_subplot(gs[2, 2])
    ax_cas.plot(a["t"], a["cas"], "b-", label="us CAS")
    ax_cas.plot(b["t"], b["cas"], "r-", label="opp CAS")
    ax_cas.axhline(450, color="green", linestyle="--", alpha=0.4, label="corner ~450 kts")
    ax_cas.set_xlabel("time (s)")
    ax_cas.set_ylabel("CAS (kts)")
    ax_cas.set_title("Speed (CAS)")
    ax_cas.legend(fontsize=7)
    ax_cas.grid(True, alpha=0.3)

    ax_cr = fig.add_subplot(gs[2, 3])
    ax_cr.plot(a["t"], a["cr"], "k-", label="closure rate")
    ax_cr.axhline(0, color="r", alpha=0.4)
    ax_cr.set_xlabel("time (s)")
    ax_cr.set_ylabel("closure rate (kts)")
    ax_cr.set_title("Closure rate (>0 = approaching)")
    ax_cr.legend(fontsize=7)
    ax_cr.grid(True, alpha=0.3)

    # === Row 4: omega / Es / R / WEZ dwell histogram ===

    ax_om = fig.add_subplot(gs[3, 0])
    if "A0100" in derived and "B0100" in derived:
        ax_om.plot(a["t"], derived["A0100"]["omega"], "b-", alpha=0.7, label="us omega")
        ax_om.plot(b["t"], derived["B0100"]["omega"], "r-", alpha=0.7, label="opp omega")
    ax_om.set_xlabel("time (s)")
    ax_om.set_ylabel("turn rate (deg/s)")
    ax_om.set_title("Turn rate omega")
    ax_om.legend(fontsize=7)
    ax_om.grid(True, alpha=0.3)

    ax_es = fig.add_subplot(gs[3, 1])
    if "A0100" in derived and "B0100" in derived:
        ax_es.plot(a["t"], derived["A0100"]["Es"], "b-", label="us Es")
        ax_es.plot(b["t"], derived["B0100"]["Es"], "r-", label="opp Es")
    ax_es.set_xlabel("time (s)")
    ax_es.set_ylabel("Es = alt + V²/(2g) (m)")
    ax_es.set_title("Energy state")
    ax_es.legend(fontsize=7)
    ax_es.grid(True, alpha=0.3)

    ax_R = fig.add_subplot(gs[3, 2])
    if "A0100" in derived and "B0100" in derived:
        Ra = np.clip(derived["A0100"]["R"], -5000, 5000)
        Rb = np.clip(derived["B0100"]["R"], -5000, 5000)
        ax_R.plot(a["t"], Ra, "b-", alpha=0.5, label="us R")
        ax_R.plot(b["t"], Rb, "r-", alpha=0.5, label="opp R")
    ax_R.set_xlabel("time (s)")
    ax_R.set_ylabel("turn radius R (m, clipped ±5000)")
    ax_R.set_title("Turn radius R = V/omega")
    ax_R.legend(fontsize=7)
    ax_R.grid(True, alpha=0.3)

    ax_hist = fig.add_subplot(gs[3, 3])
    if wez_segs:
        durs = [d for _, _, d in wez_segs]
        ax_hist.hist(durs, bins=max(5, min(20, len(durs))),
                     color="lime", edgecolor="green", alpha=0.7)
        ax_hist.axvline(np.mean(durs), color="red", linestyle="--",
                        label=f"mean {np.mean(durs):.1f}")
        ax_hist.set_xlabel("WEZ dwell duration (ticks)")
        ax_hist.set_ylabel("count")
        ax_hist.set_title(f"WEZ dwell hist (N={len(durs)}, max={max(durs)})")
        ax_hist.legend(fontsize=7)
    else:
        ax_hist.text(0.5, 0.5, "no WEZ dwell", transform=ax_hist.transAxes,
                     ha="center", va="center", fontsize=12)
        ax_hist.set_title("WEZ dwell hist (none)")

    fig.suptitle(f"R15-J v2 진단: {title} | Pattern: {pattern}", fontsize=14, y=0.995)
    plt.savefig(out_path, dpi=90, bbox_inches="tight")
    plt.close()
    print(f"saved: {out_path}")
    print(f"  Pattern: {pattern}")
    print(f"  WEZ segments: {wez_count}, total dwell: {wez_total} ticks")


def interpret_pattern(pattern, wez_segs, fit_a, fit_b, derived):
    """패턴 별 K 가설 hint."""
    hints = []
    if pattern == "A_co_centric_scissors":
        hints.append("K1 (vertical asym) + K5 (fire dwell): WEZ window 짧음 → vertical sep")
    elif pattern == "A'_figure8_lemniscate":
        if "phase_diff" in derived and abs(derived["phase_diff"].mean()) > 90:
            hints.append("K2 (phase shift): phase 항상 반대 → turn 일시 정지로 phase 깨기")
        else:
            hints.append("K5 (fire dwell): figure-8 ATA spike 길이 늘리기")
    elif pattern == "B_offset_spiral":
        hints.append("K4 (vertical commit): offset spiral 절대 합치지 않음 → alt 분리")
    elif pattern == "C_linear_extend":
        hints.append("K3 (cut-off): 직선 도주 → 적 lead 방향 commit")
    elif pattern == "D_inside_outside":
        if fit_a and fit_b:
            hints.append("K6 (inner-lane): vel decrease → 작은 R → inside")
    if not wez_segs:
        hints.append("WEZ 0 ticks: catch 모먼트 부재 — geometry 변경 필수")
    elif max(d for _, _, d in wez_segs) < 5:
        hints.append("WEZ dwell max <5 ticks: dwell 너무 짧음 — K5 우선")
    return "\n".join(hints) if hints else "패턴 분류 미확정"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--replay", required=True)
    ap.add_argument("--out")
    ap.add_argument("--dmg-us", type=float, default=0, help="dmg us dealt to opp")
    ap.add_argument("--dmg-opp", type=float, default=0, help="dmg opp dealt to us")
    args = ap.parse_args()

    replay = Path(args.replay)
    if not replay.exists():
        print(f"ERROR: {replay} not found")
        sys.exit(1)
    out = Path(args.out) if args.out else replay.with_suffix(".3d.v2.png")

    print(f"parsing {replay}...")
    ticks = parse_acmi(replay)
    print(f"  {len(ticks)} ticks")
    traj = extract_trajectory(ticks)
    derived = compute_derived(traj)
    title = replay.stem
    plot_comprehensive(traj, derived, title, out, args.dmg_us, args.dmg_opp)


if __name__ == "__main__":
    main()
