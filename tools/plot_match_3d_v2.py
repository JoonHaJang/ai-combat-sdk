"""R15-J v4 (2026-06-01): AI Combat SDK 종합 매치 3D + BT→RNN 파이프라인 분석 도구.

usage:
    python tools/plot_match_3d_v2.py --replay <acmi> [--meta <csv>] [--out plot.png]
"""
from __future__ import annotations
import argparse
import csv
import re
import sys
from collections import Counter
from pathlib import Path

import numpy as np
import matplotlib.pyplot as plt
from matplotlib import gridspec

# ─── 상수 ──────────────────────────────────────
G_FTS2 = 32.174
KTS_TO_FTS = 1.68781

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
ROLL_RE = re.compile(r"RollControlInput=([\-\d\.eE]+)")
PITCH_RE = re.compile(r"PitchControlInput=([\-\d\.eE]+)")
YAW_RE = re.compile(r"YawControlInput=([\-\d\.eE]+)")
THR_RE = re.compile(r"Throttle=([\-\d\.eE]+)")
HCA_RE = re.compile(r"HCA=([\-\d\.eE]+)")
TAU_RE = re.compile(r"TAU=([\-\d\.eE]+)")
ALT_GAP_RE = re.compile(r"AltGap=([\-\d\.eE]+)")
TR_RE = re.compile(r"TurnRate=([\-\d\.eE]+)")
IN39_RE = re.compile(r"In39Line=(True|False)")
OS_RE = re.compile(r"OvershootRisk=(True|False)")
EA_RE = re.compile(r"EnergyAdvantage=(True|False)")
ALT_ADV_RE = re.compile(r"AltAdvantage=(True|False)")
SPD_ADV_RE = re.compile(r"SpdAdvantage=(True|False)")
TC_RE = re.compile(r"TCType=(\S+)")
SF_RE = re.compile(r"SideFlag=([-\d\.eE]+)")

_META_ACTION_COLS = {
    "alt": ("action_alt", "action_altitude"),
    "hdg": ("action_hdg", "action_heading"),
    "vel": ("action_vel", "action_velocity"),
}


def _bool(v):
    return str(v).lower() in ("true", "1", "yes")

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
                entry["alt_m"] = float(m.group(3))
                entry["roll_deg"] = float(m.group(4)) if m.group(4) else 0.0
                entry["pitch_deg"] = float(m.group(5)) if m.group(5) else 0.0
                entry["yaw_deg"] = float(m.group(6)) if m.group(6) else 0.0
            for rx, key in ((HDG_RE, "hdg"), (CAS_RE, "cas"),
                            (HEALTH_RE, "health"), (ATA_RE, "ata"),
                            (AA_RE, "aa"), (DIST_RE, "dist_ft"), (CR_RE, "cr_kts"),
                            (ROLL_RE, "roll_in"), (PITCH_RE, "pitch_in"),
                            (YAW_RE, "yaw_in"), (THR_RE, "thr"),
                            (HCA_RE, "hca"), (TAU_RE, "tau"),
                            (ALT_GAP_RE, "alt_gap_ft"), (TR_RE, "turn_rate_degs"),
                            (SF_RE, "side_flag")):
                m = rx.search(rest)
                if m:
                    entry[key] = float(m.group(1))
            for rx, key in ((INWEZ_RE, "in_wez"), (IN39_RE, "in_39_line"),
                            (OS_RE, "overshoot_risk"), (EA_RE, "energy_advantage"),
                            (ALT_ADV_RE, "alt_advantage"), (SPD_ADV_RE, "spd_advantage")):
                m = rx.search(rest)
                if m:
                    entry[key] = _bool(m.group(1))
            m = TC_RE.search(rest)
            if m:
                entry["tc_type"] = m.group(1)
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
    alt0_m = a0.get("alt_m", 0.0)
    keys = (
        "t", "n", "e", "u_ft", "hdg", "cas", "in_wez", "health", "ata", "aa",
        "dist_ft", "cr_kts", "roll_in", "pitch_in", "yaw_in", "thr",
        "hca", "tau", "alt_gap_ft", "turn_rate_degs", "in_39_line",
        "overshoot_risk", "energy_advantage", "alt_advantage", "spd_advantage",
        "tc_type", "side_flag", "roll_deg", "pitch_deg", "yaw_deg",
    )
    out = {}
    for uid in ("A0100", "B0100"):
        out[uid] = {k: [] for k in keys}
    for t, state in ticks:
        for uid in ("A0100", "B0100"):
            e = state.get(uid)
            if not e or "lon" not in e:
                continue
            n, ee, u_m = lla_to_ned(e["lon"], e["lat"], e["alt_m"], lon0, lat0, alt0_m)
            out[uid]["t"].append(t)
            out[uid]["n"].append(n)
            out[uid]["e"].append(ee)
            out[uid]["u_ft"].append(u_m * 3.28084)
            out[uid]["hdg"].append(e.get("hdg", 0.0))
            out[uid]["cas"].append(e.get("cas", 0.0))
            out[uid]["in_wez"].append(e.get("in_wez", False))
            out[uid]["health"].append(e.get("health", 100.0))
            out[uid]["ata"].append(e.get("ata", 999.0))
            out[uid]["aa"].append(e.get("aa", 999.0))
            out[uid]["dist_ft"].append(e.get("dist_ft", 0.0))
            out[uid]["cr_kts"].append(e.get("cr_kts", 0.0))
            out[uid]["roll_in"].append(e.get("roll_in", 0.0))
            out[uid]["pitch_in"].append(e.get("pitch_in", 0.0))
            out[uid]["yaw_in"].append(e.get("yaw_in", 0.0))
            out[uid]["thr"].append(e.get("thr", 0.5))
            out[uid]["hca"].append(e.get("hca", 0.0))
            out[uid]["tau"].append(e.get("tau", 0.0))
            out[uid]["alt_gap_ft"].append(e.get("alt_gap_ft", 0.0))
            out[uid]["turn_rate_degs"].append(e.get("turn_rate_degs", 0.0))
            out[uid]["in_39_line"].append(e.get("in_39_line", False))
            out[uid]["overshoot_risk"].append(e.get("overshoot_risk", False))
            out[uid]["energy_advantage"].append(e.get("energy_advantage", False))
            out[uid]["alt_advantage"].append(e.get("alt_advantage", False))
            out[uid]["spd_advantage"].append(e.get("spd_advantage", False))
            out[uid]["tc_type"].append(e.get("tc_type", ""))
            out[uid]["side_flag"].append(e.get("side_flag", 0))
            out[uid]["roll_deg"].append(e.get("roll_deg", 0.0))
            out[uid]["pitch_deg"].append(e.get("pitch_deg", 0.0))
            out[uid]["yaw_deg"].append(e.get("yaw_deg", 0.0))
    for uid in out:
        for k in out[uid]:
            out[uid][k] = np.array(out[uid][k])
    return out

def unwrap_hdg(hdg_deg):
    return np.degrees(np.unwrap(np.radians(hdg_deg)))


def bfm_phase(ata_deg, aa_deg):
    if ata_deg < 45 and aa_deg > 135:
        return "OBFM"
    if ata_deg > 135 and aa_deg < 45:
        return "DBFM"
    if 45 <= ata_deg <= 135 and 45 <= aa_deg <= 135:
        return "HABFM"
    return "NEUTRAL"


def specific_energy_ft(alt_ft, cas_kts):
    v_fts = cas_kts * KTS_TO_FTS
    return alt_ft + (v_fts * v_fts) / (2 * G_FTS2)


def compute_derived(traj):
    out = {}
    for uid in ("A0100", "B0100"):
        d = traj[uid]
        if len(d["t"]) < 2:
            continue
        hdg_uw = unwrap_hdg(d["hdg"])
        omega = np.gradient(hdg_uw, d["t"])
        v_ms = d["cas"] * 0.5144
        omega_rad = np.radians(omega)
        safe = np.abs(omega_rad) > 0.01
        R = np.where(safe, v_ms / np.where(safe, omega_rad, 1.0), np.inf)
        Es = specific_energy_ft(d["u_ft"], d["cas"])
        vs = np.gradient(d["u_ft"], d["t"])
        phases = np.array([bfm_phase(a, b) for a, b in zip(d["ata"], d["aa"])])
        out[uid] = {
            "omega": omega, "v_ms": v_ms, "R": R, "Es": Es,
            "hdg_uw": hdg_uw, "vs_fts": vs, "phases": phases,
        }
    if "A0100" in out and "B0100" in out:
        min_n = min(len(out["A0100"]["hdg_uw"]), len(out["B0100"]["hdg_uw"]))
        pd = out["A0100"]["hdg_uw"][:min_n] - out["B0100"]["hdg_uw"][:min_n]
        out["phase_diff"] = ((pd + 180) % 360) - 180
        out["Es_diff"] = out["A0100"]["Es"][:min_n] - out["B0100"]["Es"][:min_n]
    return out

def detect_wez_segments(ata, dist, in_wez=None):
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
            segs.append((s, i - 1, i - s))
    if in_seg:
        segs.append((s, n - 1, n - s))
    return segs


def fit_circle(n_arr, e_arr):
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
        radii = np.sqrt((n_arr - cn) ** 2 + (e_arr - ce) ** 2)
        resid_norm = float(np.sqrt(np.mean((radii - R) ** 2)) / R)
        return cn, ce, R, resid_norm
    except np.linalg.LinAlgError:
        return None


CIRCLE_RESID_MAX = 0.25


def good_circle(fit):
    return fit is not None and fit[3] <= CIRCLE_RESID_MAX


def saturation_stats(arr, thr=0.9):
    if arr is None or len(arr) == 0:
        return {"sat_frac": 0.0, "mean_abs": 0.0}
    a = np.abs(np.asarray(arr, dtype=float))
    return {"sat_frac": float(np.mean(a > thr)), "mean_abs": float(np.mean(a))}


def compute_phase_lock(phase_diff):
    if phase_diff is None or len(phase_diff) == 0:
        return None
    pd = np.asarray(phase_diff, dtype=float)
    lock0 = float(np.mean(np.abs(pd) < 30))
    lock180 = float(np.mean(np.abs(np.abs(pd) - 180) < 30))
    win = max(10, len(pd) // 20)
    means = [pd[i:i + win].mean() for i in range(0, len(pd) - win, win)]
    drift = float(np.std(means)) if len(means) > 1 else 0.0
    return {"lock_frac_0": lock0, "lock_frac_180": lock180, "drift": drift}

def load_meta_actions(csv_path):
    p = Path(csv_path)
    if not p.exists():
        return None
    rows = []
    with open(p, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        cols = reader.fieldnames or []
        resolved = {}
        for key, names in _META_ACTION_COLS.items():
            for nm in names:
                if nm in cols:
                    resolved[key] = nm
                    break
        if len(resolved) < 3:
            return None
        for r in reader:
            aid = r.get("agent_id", "")
            if not aid.startswith("A"):
                continue
            rows.append(r)
        if not rows:
            return None
        out = {"step": np.arange(len(rows))}
        for key, col in resolved.items():
            out[key] = np.array([_safe_int(r.get(col)) for r in rows])
        out["node"] = [r.get("active_node", "") for r in rows]
        out["bfm"] = [r.get("bfm_situation", "") for r in rows]
        for col in ("aileron", "elevator", "rudder", "throttle", "reward"):
            if col in cols:
                try:
                    out[col] = np.array([float(r.get(col, 0)) for r in rows])
                except (TypeError, ValueError):
                    out[col] = None
            else:
                out[col] = None
    return out


def _safe_int(v):
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return -1


def dist_monotonic_frac(dist):
    if len(dist) < 2:
        return 0.0
    d = np.diff(dist)
    return float(np.mean(d > 0))


def classify_pattern(traj, derived):
    a = traj["A0100"]
    b = traj["B0100"]
    if len(a["n"]) < 100:
        return "UNKNOWN", {}
    scores = {}
    dist = a["dist_ft"]
    mono = dist_monotonic_frac(dist)
    late_dist = dist[100:].mean() if len(dist) > 100 else dist.mean()
    early_dist = dist[:100].mean()
    grew = late_dist / max(1.0, early_dist)
    c_score = 0.0
    if mono > 0.7 and grew > 1.3 and late_dist > 6000:
        c_score = mono + min(1.0, (grew - 1.0))
    scores["C_linear_extend"] = c_score
    fit_a = fit_circle(a["n"], a["e"])
    fit_b = fit_circle(b["n"], b["e"])
    a_ok, b_ok = good_circle(fit_a), good_circle(fit_b)
    if a_ok and b_ok:
        ca, ea, Ra, ra = fit_a
        cb, eb, Rb, rb = fit_b
        center_dist = np.sqrt((ca - cb) ** 2 + (ea - eb) ** 2)
        rr = Ra / Rb if Rb > 0 else 99
        fit_quality = 1.0 - 0.5 * (ra + rb)
        co_centric = center_dist < min(Ra, Rb) * 0.5
        offset = center_dist > (Ra + Rb) * 0.4
        similar_R = 0.7 < rr < 1.4
        scores["A_co_centric_scissors"] = fit_quality if (co_centric and similar_R) else 0.0
        scores["B_offset_spiral"] = fit_quality if offset else 0.0
        scores["D_inside_outside"] = fit_quality if (co_centric and not similar_R) else 0.0
    pl = compute_phase_lock(derived.get("phase_diff"))
    if pl is not None:
        scores["A'_figure8_lemniscate"] = pl["lock_frac_180"]
    best = max(scores, key=scores.get) if scores else "E_undetermined"
    if not scores or scores[best] <= 0.0:
        best = "E_undetermined"
    return best, scores

def _bfm_color(phase):
    return {"OBFM": "green", "DBFM": "red", "HABFM": "orange",
            "NEUTRAL": "gray"}.get(phase, "gray")


def _bt_rnn_verdict(traj, meta):
    if meta is None or meta.get("throttle") is None:
        return "N/A (no meta CSV)"
    vel = meta.get("vel")
    thr = meta["throttle"]
    if vel is None or len(vel) < 10:
        return "N/A (short meta)"
    vel4_idx = vel == 4
    thr_at_vel4 = thr[vel4_idx].mean() if vel4_idx.any() else None
    vel0_idx = vel == 0
    thr_at_vel0 = thr[vel0_idx].mean() if vel0_idx.any() else None
    if thr_at_vel4 is not None and thr_at_vel4 < 0.6:
        return f"THROTTLE BOTTLENECK — vel=4 but thr={thr_at_vel4:.2f}"
    if thr_at_vel0 is not None and thr_at_vel0 > 0.4:
        return f"THROTTLE BOTTLENECK — vel=0 but thr={thr_at_vel0:.2f}"
    _t4 = f"{thr_at_vel4:.2f}" if thr_at_vel4 is not None else "N/A"
    return f"BT→RNN OK (vel=4 thr={_t4})"

def _plot_rows_1_to_2(fig, gs, a, b, times, n_steps, norm, cmap_us, cmap_opp,
                       wez_segs, fit_a, fit_b, derived, pattern, scores, bt_rnn, meta,
                       t_clip=None):
    # Row 1
    ax3d = fig.add_subplot(gs[0, 0], projection="3d")
    step = max(1, n_steps // 800)
    # 전체 궤적 (연한 선)
    for i in range(0, n_steps - 1, step):
        ax3d.plot(a["e"][i:i+2], a["n"][i:i+2], a["u_ft"][i:i+2],
                  color=cmap_us(norm(times[i])), alpha=0.5, linewidth=0.6)
        ax3d.plot(b["e"][i:i+2], b["n"][i:i+2], b["u_ft"][i:i+2],
                  color=cmap_opp(norm(times[i])), alpha=0.5, linewidth=0.6)
    # WEZ 구간 강조 (굵은 선)
    for s, e, _ in wez_segs:
        ax3d.plot(a["e"][s:e+1], a["n"][s:e+1], a["u_ft"][s:e+1],
                  color="orange", alpha=0.9, linewidth=2.5, label="WEZ" if s == wez_segs[0][0] else "")
        ax3d.plot(b["e"][s:e+1], b["n"][s:e+1], b["u_ft"][s:e+1],
                  color="orange", alpha=0.9, linewidth=2.5)
    ax3d.scatter([a["e"][0]], [a["n"][0]], [a["u_ft"][0]], c="blue", s=80, marker="o")
    ax3d.scatter([b["e"][0]], [b["n"][0]], [b["u_ft"][0]], c="red", s=80, marker="o")
    ax3d.scatter([a["e"][-1]], [a["n"][-1]], [a["u_ft"][-1]], c="blue", s=80, marker="^")
    ax3d.scatter([b["e"][-1]], [b["n"][-1]], [b["u_ft"][-1]], c="red", s=80, marker="^")
    ax3d.set_xlabel("E (m)"); ax3d.set_ylabel("N (m)"); ax3d.set_zlabel("U (ft)")
    title3d = "3D trajectory (time gradient)"
    if t_clip:
        title3d += f"  clip {t_clip[0]:.1f}-{t_clip[1]:.1f}s"
    ax3d.set_title(title3d)
    ax3d.view_init(elev=20, azim=-60)

    ax_td = fig.add_subplot(gs[0, 1])
    for i in range(0, n_steps - 1, max(1, n_steps // 200)):
        ax_td.plot(a["e"][i:i+2], a["n"][i:i+2], color=cmap_us(norm(times[i])), alpha=0.6, linewidth=0.8)
        ax_td.plot(b["e"][i:i+2], b["n"][i:i+2], color=cmap_opp(norm(times[i])), alpha=0.6, linewidth=0.8)
    ax_td.scatter([a["e"][0]], [a["n"][0]], c="blue", marker="o", s=50, label="us start")
    ax_td.scatter([b["e"][0]], [b["n"][0]], c="red", marker="o", s=50, label="opp start")
    if fit_a:
        ca, ea, Ra, ra = fit_a
        theta = np.linspace(0, 2 * np.pi, 100)
        ax_td.plot(ea + Ra * np.cos(theta), ca + Ra * np.sin(theta), "b--", alpha=0.5,
                   label=f"us R={Ra:.0f} r={ra:.2f}")
    if fit_b:
        cb, eb, Rb, rb = fit_b
        theta = np.linspace(0, 2 * np.pi, 100)
        ax_td.plot(eb + Rb * np.cos(theta), cb + Rb * np.sin(theta), "r--", alpha=0.5,
                   label=f"opp R={Rb:.0f} r={rb:.2f}")
    for s, e, dur in wez_segs:
        ax_td.scatter(a["e"][s:e+1], a["n"][s:e+1], c="lime", marker="*", s=30, alpha=0.6)
    ax_td.set_xlabel("East (m)"); ax_td.set_ylabel("North (m)")
    ax_td.set_title("Top-down + circle fits")
    ax_td.legend(fontsize=7, loc="upper right")
    ax_td.grid(True, alpha=0.3); ax_td.set_aspect("equal")

    ax_bfm = fig.add_subplot(gs[0, 2])
    if "A0100" in derived:
        phases = derived["A0100"]["phases"]
        t_p = a["t"][:len(phases)]
        y = {"OBFM": 3, "DBFM": 2, "HABFM": 1, "NEUTRAL": 0}
        vals = np.array([y.get(p, 0) for p in phases])
        for i in range(len(t_p) - 1):
            ax_bfm.plot(t_p[i:i+2], vals[i:i+2], color=_bfm_color(phases[i]), linewidth=2)
        ax_bfm.set_yticks([0, 1, 2, 3])
        ax_bfm.set_yticklabels(["NEUTRAL", "HABFM", "DBFM", "OBFM"])
        ax_bfm.set_ylim(-0.5, 3.5)
    ax_bfm.set_xlabel("time (s)"); ax_bfm.set_title("BFM Phase (us)")
    ax_bfm.grid(True, alpha=0.3)

    ax_txt = fig.add_subplot(gs[0, 3])
    ax_txt.axis("off")
    wez_count = len(wez_segs)
    wez_total = sum(d for _, _, d in wez_segs)
    wez_max = max((d for _, _, d in wez_segs), default=0)
    wez_mean = wez_total / wez_count if wez_count > 0 else 0
    fit_str = ""
    if fit_a and fit_b:
        ca, ea, Ra, ra = fit_a
        cb, eb, Rb, rb = fit_b
        cd = np.sqrt((ca - cb)**2 + (ea - eb)**2)
        fit_str = f"circle: us R={Ra:.0f}m r={ra:.2f}, opp R={Rb:.0f}m r={rb:.2f}, cd={cd:.0f}m\n"
    phase_str = ""
    pl = compute_phase_lock(derived.get("phase_diff"))
    if pl is not None:
        pd = derived["phase_diff"]
        phase_str = (f"phase: mean={pd.mean():.0f} std={pd.std():.0f} | "
                     f"lock0={pl['lock_frac_0']*100:.0f}% lock180={pl['lock_frac_180']*100:.0f}%\n")
    es_str = ""
    if "A0100" in derived and "B0100" in derived:
        es_str = f"final Es adv: {derived['A0100']['Es'][-1] - derived['B0100']['Es'][-1]:+.0f} ft\n"
    sat_roll = saturation_stats(a["roll_in"])
    sat_pitch = saturation_stats(a["pitch_in"])
    ctrl_str = (f"CTRL: |roll| mean={sat_roll['mean_abs']:.2f} sat={sat_roll['sat_frac']*100:.0f}% | "
                f"|pitch| mean={sat_pitch['mean_abs']:.2f} sat={sat_pitch['sat_frac']*100:.0f}%\n")
    diag = (
        f"=== AUTO DIAGNOSIS ===\n"
        f"Pattern: {pattern}\n"
        f"BT→RNN: {bt_rnn}\n\n"
        f"ticks: {n_steps}\n"
        f"WEZ segs: {wez_count}, total: {wez_total}, max: {wez_max}, mean: {wez_mean:.1f}\n"
        f"{fit_str}{phase_str}{es_str}{ctrl_str}"
    )
    ax_txt.text(0, 1, diag, family="monospace", fontsize=9,
                verticalalignment="top", transform=ax_txt.transAxes,
                bbox=dict(boxstyle="round,pad=0.5", fc="lightyellow", alpha=0.6))

    # Row 2
    ax_alt = fig.add_subplot(gs[1, 0])
    ax_alt.plot(a["t"], a["u_ft"], "b-", label="us alt")
    ax_alt.plot(b["t"], b["u_ft"], "r-", label="opp alt")
    ax_alt.set_xlabel("time (s)"); ax_alt.set_ylabel("altitude (ft)")
    ax_alt.set_title("Altitude both aircraft")
    ax_alt.legend(fontsize=7); ax_alt.grid(True, alpha=0.3)

    ax_dist = fig.add_subplot(gs[1, 1])
    ax_dist.plot(a["t"], a["dist_ft"], "k-", label="dist")
    ax_dist.axhspan(500, 3000, alpha=0.2, color="orange", label="WEZ band")
    ax_dist.set_xlabel("time (s)"); ax_dist.set_ylabel("distance (ft)")
    ax_dist.set_title("Distance + WEZ band")
    ax_dist.legend(fontsize=7); ax_dist.grid(True, alpha=0.3)

    ax_ata = fig.add_subplot(gs[1, 2])
    ax_ata.plot(a["t"], a["ata"], "b-", alpha=0.8, label="our ATA")
    ax_ata.plot(a["t"], a["aa"], "g-", alpha=0.6, label="our AA")
    ax_ata.axhline(12, color="orange", linestyle="--", alpha=0.5, label="WEZ 12°")
    for s, e, dur in wez_segs:
        if dur > 0:
            ax_ata.axvspan(a["t"][s], a["t"][e], alpha=0.2, color="lime")
    ax_ata.set_xlabel("time (s)"); ax_ata.set_ylabel("ATA / AA (deg)")
    ax_ata.set_ylim(0, 180); ax_ata.set_title("ATA + AA (us perspective)")
    ax_ata.legend(fontsize=7); ax_ata.grid(True, alpha=0.3)

    ax_hca = fig.add_subplot(gs[1, 3])
    ax_hca.plot(a["t"], a["hca"], "purple", alpha=0.7, label="HCA")
    if "phase_diff" in derived:
        pd = derived["phase_diff"]
        t_pd = a["t"][:len(pd)]
        ax_hca.plot(t_pd, pd, "k-", alpha=0.4, label="phase diff")
        ax_hca.axhline(0, color="k", alpha=0.2)
        ax_hca.fill_between(t_pd, -30, 30, color="green", alpha=0.15, label="aligned (<30°)")
    ax_hca.set_xlabel("time (s)"); ax_hca.set_ylabel("deg")
    ax_hca.set_title("HCA + Phase diff")
    ax_hca.legend(fontsize=7); ax_hca.grid(True, alpha=0.3)

def _plot_rows_3_to_4(fig, gs, a, b, derived, wez_segs):
    # Row 3
    ax_hdg = fig.add_subplot(gs[2, 0])
    if "A0100" in derived and "B0100" in derived:
        ax_hdg.plot(a["t"], derived["A0100"]["hdg_uw"], "b-", label="us HDG (unwrapped)")
        ax_hdg.plot(b["t"], derived["B0100"]["hdg_uw"], "r-", label="opp HDG")
    ax_hdg.set_xlabel("time (s)"); ax_hdg.set_ylabel("HDG cumulative (deg)")
    ax_hdg.set_title("Heading (unwrapped)")
    ax_hdg.legend(fontsize=7); ax_hdg.grid(True, alpha=0.3)

    ax_om = fig.add_subplot(gs[2, 1])
    if "A0100" in derived and "B0100" in derived:
        ax_om.plot(a["t"], derived["A0100"]["omega"], "b-", alpha=0.7, label="us omega")
        ax_om.plot(b["t"], derived["B0100"]["omega"], "r-", alpha=0.7, label="opp omega")
    ax_om.set_xlabel("time (s)"); ax_om.set_ylabel("turn rate (deg/s)")
    ax_om.set_title("Turn rate omega")
    ax_om.legend(fontsize=7); ax_om.grid(True, alpha=0.3)

    ax_cas = fig.add_subplot(gs[2, 2])
    ax_cas.plot(a["t"], a["cas"], "b-", label="us CAS")
    ax_cas.plot(b["t"], b["cas"], "r-", label="opp CAS")
    ax_cas.axhline(450, color="green", linestyle="--", alpha=0.4, label="corner ~450 kts")
    ax_cas.set_xlabel("time (s)"); ax_cas.set_ylabel("CAS (kts)")
    ax_cas.set_title("Speed (CAS)")
    ax_cas.legend(fontsize=7); ax_cas.grid(True, alpha=0.3)

    ax_cr = fig.add_subplot(gs[2, 3])
    ax_cr.plot(a["t"], a["cr_kts"], "k-", label="closure rate")
    ax_cr.axhline(0, color="r", alpha=0.4)
    ax_cr.set_xlabel("time (s)"); ax_cr.set_ylabel("closure rate (kts)")
    ax_cr.set_title("Closure rate (>0 = approaching)")
    ax_cr.legend(fontsize=7); ax_cr.grid(True, alpha=0.3)

    # Row 4
    ax_es = fig.add_subplot(gs[3, 0])
    if "A0100" in derived and "B0100" in derived:
        ax_es.plot(a["t"], derived["A0100"]["Es"], "b-", label="us Es")
        ax_es.plot(b["t"], derived["B0100"]["Es"], "r-", label="opp Es")
    ax_es.set_xlabel("time (s)"); ax_es.set_ylabel("Es (ft)")
    ax_es.set_title("Specific Energy")
    ax_es.legend(fontsize=7); ax_es.grid(True, alpha=0.3)

    ax_ed = fig.add_subplot(gs[3, 1])
    if "Es_diff" in derived:
        ed = derived["Es_diff"]
        t_ed = a["t"][:len(ed)]
        ax_ed.plot(t_ed, ed, "purple", label="Es_us - Es_opp")
        ax_ed.axhline(0, color="k", alpha=0.3)
        ax_ed.fill_between(t_ed, 0, ed, where=(ed > 0), color="blue", alpha=0.15, label="us advantage")
        ax_ed.fill_between(t_ed, 0, ed, where=(ed <= 0), color="red", alpha=0.15, label="opp advantage")
    ax_ed.set_xlabel("time (s)"); ax_ed.set_ylabel("Es diff (ft)")
    ax_ed.set_title("Energy advantage")
    ax_ed.legend(fontsize=7); ax_ed.grid(True, alpha=0.3)

    ax_rp = fig.add_subplot(gs[3, 2])
    ax_rp.plot(a["t"], a["roll_deg"], "b-", alpha=0.7, label="us roll")
    ax_rp.plot(a["t"], a["pitch_deg"], "g-", alpha=0.6, label="us pitch")
    ax_rp.plot(b["t"], b["roll_deg"], "r-", alpha=0.5, label="opp roll")
    ax_rp.plot(b["t"], b["pitch_deg"], "orange", alpha=0.4, label="opp pitch")
    ax_rp.set_xlabel("time (s)"); ax_rp.set_ylabel("deg")
    ax_rp.set_title("Roll / Pitch")
    ax_rp.legend(fontsize=7); ax_rp.grid(True, alpha=0.3)

    ax_hist = fig.add_subplot(gs[3, 3])
    if wez_segs:
        durs = [d for _, _, d in wez_segs]
        ax_hist.hist(durs, bins=max(5, min(20, len(durs))), color="lime", edgecolor="green", alpha=0.7)
        ax_hist.axvline(np.mean(durs), color="red", linestyle="--", label=f"mean {np.mean(durs):.1f}")
        ax_hist.set_xlabel("WEZ dwell (ticks)"); ax_hist.set_ylabel("count")
        ax_hist.set_title(f"WEZ dwell hist (N={len(durs)}, max={max(durs)})")
        ax_hist.legend(fontsize=7)
    else:
        ax_hist.text(0.5, 0.5, "no WEZ dwell", transform=ax_hist.transAxes, ha="center", va="center", fontsize=12)
        ax_hist.set_title("WEZ dwell hist (none)")

def _plot_rows_5_to_6(fig, gs, a, b, meta, derived):
    # Row 5: BT→RNN pipeline analysis
    ax_vt = fig.add_subplot(gs[4, 0])
    if meta is not None and meta.get("throttle") is not None:
        steps = meta["step"]
        ax_vt.step(steps, meta["vel"], "b-", where="post", alpha=0.8, label="vel bin")
        ax2 = ax_vt.twinx()
        ax2.plot(steps, meta["throttle"], "r-", alpha=0.6, label="throttle")
        ax_vt.set_xlabel("step"); ax_vt.set_ylabel("vel bin", color="b")
        ax2.set_ylabel("throttle", color="r")
        ax_vt.set_title("vel bin vs throttle")
        ax_vt.legend(fontsize=7, loc="upper left")
        ax2.legend(fontsize=7, loc="upper right")
    else:
        ax_vt.text(0.5, 0.5, "no meta CSV", transform=ax_vt.transAxes, ha="center", va="center")
        ax_vt.set_title("vel bin vs throttle")
    ax_vt.grid(True, alpha=0.3)

    ax_ht = fig.add_subplot(gs[4, 1])
    if meta is not None and "A0100" in derived:
        steps = meta["step"]
        # 메타 step 수와 ACMI tick 수가 다를 수 있으므로 짧은 쪽에 맞춤
        n_common = min(len(steps), len(derived["A0100"]["omega"]))
        ax_ht.step(steps[:n_common], meta["hdg"][:n_common], "b-", where="post", alpha=0.8, label="hdg bin")
        ax2 = ax_ht.twinx()
        ax2.plot(a["t"][:n_common], derived["A0100"]["omega"][:n_common], "r-", alpha=0.6, label="turn rate")
        ax_ht.set_xlabel("step"); ax_ht.set_ylabel("hdg bin", color="b")
        ax2.set_ylabel("turn rate (deg/s)", color="r")
        ax_ht.set_title("hdg bin vs turn rate")
        ax_ht.legend(fontsize=7, loc="upper left")
        ax2.legend(fontsize=7, loc="upper right")
    else:
        ax_ht.text(0.5, 0.5, "no meta CSV", transform=ax_ht.transAxes, ha="center", va="center")
        ax_ht.set_title("hdg bin vs turn rate")
    ax_ht.grid(True, alpha=0.3)

    ax_av = fig.add_subplot(gs[4, 2])
    if meta is not None and "A0100" in derived:
        steps = meta["step"]
        n_common = min(len(steps), len(derived["A0100"]["vs_fts"]))
        ax_av.step(steps[:n_common], meta["alt"][:n_common], "b-", where="post", alpha=0.8, label="alt bin")
        ax2 = ax_av.twinx()
        ax2.plot(a["t"][:n_common], derived["A0100"]["vs_fts"][:n_common], "r-", alpha=0.6, label="vertical speed")
        ax_av.set_xlabel("step"); ax_av.set_ylabel("alt bin", color="b")
        ax2.set_ylabel("vs (ft/s)", color="r")
        ax_av.set_title("alt bin vs vertical speed")
        ax_av.legend(fontsize=7, loc="upper left")
        ax2.legend(fontsize=7, loc="upper right")
    else:
        ax_av.text(0.5, 0.5, "no meta CSV", transform=ax_av.transAxes, ha="center", va="center")
        ax_av.set_title("alt bin vs vertical speed")
    ax_av.grid(True, alpha=0.3)

    ax_ci = fig.add_subplot(gs[4, 3])
    ax_ci.plot(a["t"], a["roll_in"], "b-", alpha=0.7, label="roll in")
    ax_ci.plot(a["t"], a["pitch_in"], "g-", alpha=0.6, label="pitch in")
    ax_ci.plot(a["t"], a["yaw_in"], "c-", alpha=0.5, label="yaw in")
    ax_ci.plot(a["t"], a["thr"], "m-", alpha=0.5, label="throttle")
    ax_ci.axhline(0.9, color="r", ls=":", alpha=0.4)
    ax_ci.axhline(-0.9, color="r", ls=":", alpha=0.4)
    ax_ci.set_ylim(-1.1, 1.1)
    ax_ci.set_xlabel("time (s)"); ax_ci.set_ylabel("control input")
    ax_ci.set_title("US control inputs")
    ax_ci.legend(fontsize=7); ax_ci.grid(True, alpha=0.3)

    # Row 6
    ax_node = fig.add_subplot(gs[5, 0])
    if meta is not None and meta.get("node"):
        nodes = meta["node"]
        steps = meta["step"]
        unique = sorted(set(nodes))
        y_map = {n: i for i, n in enumerate(unique)}
        vals = np.array([y_map.get(n, -1) for n in nodes])
        for i in range(len(steps) - 1):
            ax_node.plot(steps[i:i+2], vals[i:i+2], color="navy", linewidth=2)
        ax_node.set_yticks(range(len(unique)))
        ax_node.set_yticklabels(unique, fontsize=6)
        ax_node.set_xlabel("step"); ax_node.set_title("Active node timeline")
    else:
        ax_node.text(0.5, 0.5, "no meta CSV", transform=ax_node.transAxes, ha="center", va="center")
        ax_node.set_title("Active node timeline")
    ax_node.grid(True, alpha=0.3)

    ax_ab = fig.add_subplot(gs[5, 1])
    if meta is not None:
        steps = meta["step"]
        ax_ab.step(steps, meta["hdg"], "b-", where="post", alpha=0.8, label="hdg bin")
        ax_ab.step(steps, meta["vel"], "m-", where="post", alpha=0.6, label="vel bin")
        ax_ab.step(steps, meta["alt"], "g-", where="post", alpha=0.6, label="alt bin")
        ax_ab.axhline(4, color="gray", ls=":", alpha=0.4)
        ax_ab.set_xlabel("step"); ax_ab.set_ylabel("action bin")
        ax_ab.set_title("US action bins")
        ax_ab.legend(fontsize=7); ax_ab.grid(True, alpha=0.3)
    else:
        ax_ab.text(0.5, 0.5, "no meta CSV", transform=ax_ab.transAxes, ha="center", va="center")
        ax_ab.set_title("US action bins")

    ax_bfm2 = fig.add_subplot(gs[5, 2])
    if meta is not None and meta.get("bfm"):
        bfm_list = meta["bfm"]
        steps = meta["step"]
        y = {"OBFM": 3, "DBFM": 2, "HABFM": 1, "NEUTRAL": 0}
        vals = np.array([y.get(p, 0) for p in bfm_list])
        for i in range(len(steps) - 1):
            ax_bfm2.plot(steps[i:i+2], vals[i:i+2], color=_bfm_color(bfm_list[i]), linewidth=2)
        ax_bfm2.set_yticks([0, 1, 2, 3])
        ax_bfm2.set_yticklabels(["NEUTRAL", "HABFM", "DBFM", "OBFM"])
        ax_bfm2.set_ylim(-0.5, 3.5)
        ax_bfm2.set_xlabel("step"); ax_bfm2.set_title("BFM situation (meta)")
    else:
        ax_bfm2.text(0.5, 0.5, "no meta CSV", transform=ax_bfm2.transAxes, ha="center", va="center")
        ax_bfm2.set_title("BFM situation (meta)")
    ax_bfm2.grid(True, alpha=0.3)

    ax_rw = fig.add_subplot(gs[5, 3])
    if meta is not None and meta.get("reward") is not None:
        steps = meta["step"]
        ax_rw.plot(steps, meta["reward"], "k-", label="reward")
        ax_rw.axhline(0, color="r", alpha=0.3)
        ax_rw.set_xlabel("step"); ax_rw.set_ylabel("reward")
        ax_rw.set_title("Reward")
        ax_rw.legend(fontsize=7)
    else:
        ax_rw.text(0.5, 0.5, "no meta CSV", transform=ax_rw.transAxes, ha="center", va="center")
        ax_rw.set_title("Reward")
    ax_rw.grid(True, alpha=0.3)

def _clip_traj(traj, t_start, t_end):
    out = {}
    for uid, d in traj.items():
        if uid in ("A0100", "B0100"):
            mask = (d["t"] >= t_start) & (d["t"] <= t_end)
            out[uid] = {k: v[mask] for k, v in d.items()}
        else:
            out[uid] = d
    return out


def _clip_derived(derived, traj_a_t, t_start, t_end):
    out = {}
    mask = (traj_a_t >= t_start) & (traj_a_t <= t_end)
    for k, v in derived.items():
        if k in ("A0100", "B0100"):
            out[k] = {kk: vv[mask] for kk, vv in v.items()}
        else:
            out[k] = v[mask] if isinstance(v, np.ndarray) and len(v) == len(mask) else v
    return out


def plot_comprehensive(traj, derived, title, out_path, dmg_us_to_opp=0,
                       dmg_opp_to_us=0, meta=None, t_clip=None):
    fig = plt.figure(figsize=(24, 28))
    gs = gridspec.GridSpec(6, 4, figure=fig, hspace=0.40, wspace=0.30)

    a = traj["A0100"]
    b = traj["B0100"]
    times = a["t"]
    n_steps = len(times)
    norm = plt.Normalize(times.min(), times.max())
    cmap_us = plt.get_cmap("Blues")
    cmap_opp = plt.get_cmap("Reds")

    wez_segs = detect_wez_segments(a["ata"], a["dist_ft"])
    fit_a = fit_circle(a["n"], a["e"])
    fit_b = fit_circle(b["n"], b["e"])
    pattern, scores = classify_pattern(traj, derived)
    bt_rnn = _bt_rnn_verdict(traj, meta)

    _plot_rows_1_to_2(fig, gs, a, b, times, n_steps, norm, cmap_us, cmap_opp,
                      wez_segs, fit_a, fit_b, derived, pattern, scores, bt_rnn, meta,
                      t_clip=t_clip)
    _plot_rows_3_to_4(fig, gs, a, b, derived, wez_segs)
    _plot_rows_5_to_6(fig, gs, a, b, meta, derived)

    suptitle = f"R15-J v4: {title} | Pattern: {pattern}"
    if t_clip:
        suptitle += f" | clip {t_clip[0]:.1f}-{t_clip[1]:.1f}s"
    fig.suptitle(suptitle, fontsize=14, y=0.997)
    plt.savefig(out_path, dpi=90, bbox_inches="tight")
    plt.close()
    print(f"saved: {out_path}")
    print(f"  Pattern: {pattern}  scores: { {k: round(v,2) for k,v in scores.items()} }")
    print(f"  BT→RNN: {bt_rnn}")
    print(f"  WEZ segments: {len(wez_segs)}, total dwell: {sum(d for _,_,d in wez_segs)} ticks")


def _parse_windows(s, t_max):
    """0,100,200,300 → [(0,100),(100,200),(200,300)]"""
    parts = [float(x.strip()) for x in s.split(",")]
    if len(parts) < 2:
        return [(0.0, t_max)]
    w = []
    for i in range(len(parts) - 1):
        a, b = parts[i], parts[i + 1]
        w.append((a, b))
    return w


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--replay", required=True)
    ap.add_argument("--out")
    ap.add_argument("--dmg-us", type=float, default=0, help="dmg us dealt to opp")
    ap.add_argument("--dmg-opp", type=float, default=0, help="dmg opp dealt to us")
    ap.add_argument("--meta", help="meta CSV (생략 시 동일 stem _meta.csv 자동 탐색)")
    ap.add_argument("--windows", help="time windows: 0,30,60,90 → 0-30s,30-60s,60-90s PNGs")
    ap.add_argument("--report", help="분석 보고서 .md 경로 (미지정 시 replay_stem.analysis.md)")
    args = ap.parse_args()

    replay = Path(args.replay)
    if not replay.exists():
        print(f"ERROR: {replay} not found")
        sys.exit(1)

    meta = None
    meta_path = None
    if args.meta:
        meta_path = Path(args.meta)
    else:
        cand = replay.with_name(replay.stem + "_meta.csv")
        if cand.exists():
            meta_path = cand
    if meta_path is not None:
        meta = load_meta_actions(meta_path)
        print(f"  meta CSV: {meta_path} → {'loaded' if meta else 'FAILED'}")

    print(f"parsing {replay}...")
    ticks = parse_acmi(replay)
    print(f"  {len(ticks)} ticks")
    traj_full = extract_trajectory(ticks)
    derived_full = compute_derived(traj_full)
    title = replay.stem
    t_max = float(traj_full["A0100"]["t"][-1]) if len(traj_full["A0100"]["t"]) else 0.0

    # 공용 분석값 (plot + report)
    wez_segs = detect_wez_segments(traj_full["A0100"]["ata"], traj_full["A0100"]["dist_ft"])
    fit_a = fit_circle(traj_full["A0100"]["n"], traj_full["A0100"]["e"])
    fit_b = fit_circle(traj_full["B0100"]["n"], traj_full["B0100"]["e"])
    pattern, scores = classify_pattern(traj_full, derived_full)
    bt_rnn = _bt_rnn_verdict(traj_full, meta)

    if args.windows:
        windows = _parse_windows(args.windows, t_max)
        valid = [(a, b) for a, b in windows if a < t_max and b > 0]
        print(f"  generating {len(valid)} window plots (clamped to t_max={t_max:.1f}s)...")
        for i, (t0, t1) in enumerate(valid, start=1):
            t0c, t1c = max(0.0, t0), min(t_max, t1)
            sub_traj = _clip_traj(traj_full, t0c, t1c)
            if len(sub_traj.get("A0100", {}).get("t", [])) == 0:
                print(f"    skip win{i}: no data in {t0c:.1f}-{t1c:.1f}s")
                continue
            sub_derived = _clip_derived(derived_full, traj_full["A0100"]["t"], t0c, t1c)
            out = replay.with_suffix(f".win{i}_{t0c:.0f}-{t1c:.0f}s.3d.v2.png")
            plot_comprehensive(sub_traj, sub_derived, title, out,
                               args.dmg_us, args.dmg_opp, meta=meta, t_clip=(t0c, t1c))
    else:
        out = Path(args.out) if args.out else replay.with_suffix(".3d.v2.png")
        plot_comprehensive(traj_full, derived_full, title, out,
                           args.dmg_us, args.dmg_opp, meta=meta)

    # 보고서 생성
    report_path = Path(args.report) if args.report else replay.with_suffix(".analysis.md")
    generate_report(traj_full, derived_full, title, report_path,
                    wez_segs, fit_a, fit_b, pattern, scores, bt_rnn, meta=meta)


def _phase_counts(phases):
    cnt = Counter(phases)
    total = sum(cnt.values())
    if total == 0:
        return {}
    return {p: f"{c} ({c/total*100:.1f}%)" for p, c in cnt.items()}


def _phase_transitions(phases):
    if len(phases) < 2:
        return 0
    return int(sum(1 for i in range(len(phases)-1) if phases[i] != phases[i+1]))


def _es_trend(Es, t):
    if len(Es) < 3:
        return {}
    thirds = len(Es) // 3
    return {
        "early": float(Es[:thirds].mean()),
        "mid": float(Es[thirds:2*thirds].mean()),
        "late": float(Es[2*thirds:].mean()),
        "overall": float(Es.mean()),
        "max": float(Es.max()),
        "min": float(Es.min()),
    }


def _wez_efficiency(wez_segs, total_ticks):
    if not wez_segs:
        return 0.0
    dwell = sum(d for _, _, d in wez_segs)
    return dwell / max(1, total_ticks)


def _compute_cmd_exec_lag(meta, derived, key, cmd_key):
    if meta is None or meta.get(cmd_key) is None or key not in derived:
        return None
    cmd = meta[cmd_key]
    actual = derived[key]
    n = min(len(cmd), len(actual))
    if n < 2:
        return None
    # simple correlation-based lag estimate
    best_lag = 0
    best_corr = -2
    for lag in range(0, min(20, n)):
        c = np.corrcoef(cmd[:n-lag], actual[lag:n])[0,1]
        if not np.isnan(c) and c > best_corr:
            best_corr = c
            best_lag = lag
    return {"lag_ticks": best_lag, "corr": float(best_corr)}


def generate_report(traj, derived, title, out_md, wez_segs, fit_a, fit_b,
                    pattern, scores, bt_rnn, meta=None):
    a = traj["A0100"]
    b = traj["B0100"]
    n_steps = len(a["t"])
    t_max = float(a["t"][-1]) if n_steps > 0 else 0.0
    lines = []
    def L(s=""): lines.append(s)

    L(f"# 매치 분석 보고서: `{title}`")
    L()
    L(f"- **생성 시각**: {__import__('datetime').datetime.now().isoformat()}")
    L(f"- **총 tick 수**: {n_steps}")
    L(f"- **시뮬레이션 시간**: {t_max:.1f}s")
    L()

    L("## 1. 교전 패턴 분석")
    L()
    L(f"- **자동 분류 패턴**: `{pattern}`")
    if scores:
        L("- **패턴 점수**:")
        for k, v in sorted(scores.items(), key=lambda x: -x[1]):
            L(f"  - {k}: `{v:.3f}`")
    if fit_a and fit_b:
        ca, ea, Ra, ra = fit_a
        cb, eb, Rb, rb = fit_b
        cd = ((ca-cb)**2 + (ea-eb)**2)**0.5
        L(f"- **원 근사**:")
        L(f"  - us: R={Ra:.0f}m, 잔차={ra:.3f}")
        L(f"  - opp: R={Rb:.0f}m, 잔차={rb:.3f}")
        L(f"  - 중심 거리: {cd:.0f}m")
    else:
        L("- **원 근사**: 실패 (데이터 부족 또는 비원형 궤적)")
    pl = compute_phase_lock(derived.get("phase_diff"))
    if pl is not None:
        L(f"- **Phase Lock**: 0°={pl['lock_frac_0']*100:.0f}%, 180°={pl['lock_frac_180']*100:.0f}%, drift={pl['drift']:.1f}°")
    L()

    L("## 2. BFM Phase 분석")
    L()
    for uid, label in (("A0100", "us"), ("B0100", "opp")):
        if uid in derived:
            ph = derived[uid]["phases"]
            L(f"- **{label}**:")
            for p, cnt_str in _phase_counts(ph).items():
                L(f"  - {p}: {cnt_str}")
            L(f"  - phase 전환 횟수: {_phase_transitions(ph)}")
    L()

    L("## 3. WEZ (Weapon Engagement Zone) 분석")
    L()
    wez_count = len(wez_segs)
    wez_total = sum(d for _, _, d in wez_segs)
    wez_max = max((d for _, _, d in wez_segs), default=0)
    wez_mean = wez_total / wez_count if wez_count else 0
    L(f"- **WEZ 세그먼트 수**: {wez_count}")
    L(f"- **총 체류 시간**: {wez_total} ticks")
    L(f"- **평균 체류**: {wez_mean:.1f} ticks")
    L(f"- **최대 체류**: {wez_max} ticks")
    L(f"- **WEZ 효율**: {_wez_efficiency(wez_segs, n_steps)*100:.2f}% (전체 시간 대비)")
    L()

    L("## 4. 에너지 분석")
    L()
    if "A0100" in derived and "B0100" in derived:
        for uid, label in (("A0100", "us"), ("B0100", "opp")):
            trend = _es_trend(derived[uid]["Es"], a["t"])
            L(f"- **{label} Specific Energy (ft)**:")
            L(f"  - early: {trend['early']:.0f}, mid: {trend['mid']:.0f}, late: {trend['late']:.0f}")
            L(f"  - min/max: {trend['min']:.0f} / {trend['max']:.0f}")
        if "Es_diff" in derived:
            ed = derived["Es_diff"]
            L(f"- **에너지 우위 변화 (us - opp)**:")
            L(f"  - 초반: {ed[0]:+.0f}ft, 중반: {ed[len(ed)//2]:+.0f}ft, 후반: {ed[-1]:+.0f}ft")
    L()

    L("## 5. BT→RNN 파이프라인 분석")
    L()
    L(f"- **판정**: {bt_rnn}")
    L()

    # 5a. ACMI 기반 추론 (meta 없어도 가능)
    L("### 5a. ACMI 기반 RNN 행동 추론")
    L()
    thr = a["thr"]
    v_ms = derived["A0100"]["v_ms"]
    if len(thr) > 1 and len(v_ms) > 1:
        thr_delta = np.abs(np.diff(thr)).mean()
        v_delta = np.abs(np.diff(v_ms)).mean()
        L(f"- throttle 변화율 (평균 |Δ|): {thr_delta:.4f} / tick")
        L(f"- 속도 변화율 (평균 |Δ|): {v_delta:.2f} m/s per tick")
        corr_tv = np.corrcoef(thr, v_ms)[0,1] if len(thr)==len(v_ms) else np.nan
        if not np.isnan(corr_tv):
            L(f"- throttle ↔ 속도 상관계수: {corr_tv:.3f}")
    # energy-throttle
    Es = derived["A0100"]["Es"]
    if len(Es) == len(thr):
        corr_et = np.corrcoef(Es, thr)[0,1]
        if not np.isnan(corr_et):
            L(f"- specific energy ↔ throttle 상관계수: {corr_et:.3f}")
    L()

    # 5b. Meta CSV 상세 분석
    L("### 5b. Meta CSV 상세 분석")
    L()
    if meta is not None:
        # velocity bin → throttle
        vel = meta.get("vel")
        hdg = meta.get("hdg")
        alt = meta.get("alt")
        thr_meta = meta.get("throttle")
        if thr_meta is not None and len(thr_meta) > 10:
            L("- **Velocity Bin → Throttle 매핑**")
            if vel is not None:
                for vbin in (0, 1, 2, 3, 4):
                    idx = vel == vbin
                    if idx.any():
                        L(f"  - vel={vbin}: 평균 throttle={thr_meta[idx].mean():.2f} (n={idx.sum()})")
            else:
                L("  - velocity bin 데이터 없음")
            L()

            # 포화 구간 분석
            sat_idx = thr_meta > 0.9
            sat_frac = sat_idx.mean()
            L(f"- **Throttle 포화**: {sat_frac*100:.1f}% (>{0.9})")
            if sat_frac > 0.05 and vel is not None:
                L(f"  - 포화 구간 평균 velocity bin: {vel[sat_idx].mean():.2f}")
            L()

            # heading bin → turn rate
            omega = derived["A0100"].get("omega")
            if hdg is not None and omega is not None and len(hdg) == len(omega):
                L("- **Heading Bin → Turn Rate 반응**")
                for hbin in (0, 1, 2, 3, 4):
                    idx = hdg == hbin
                    if idx.any():
                        L(f"  - hdg={hbin}: 평균 ω={omega[idx].mean():.2f}°/s (n={idx.sum()})")
                lag_v = _compute_cmd_exec_lag(meta, derived.get("A0100", {}), "omega", "hdg")
                if lag_v:
                    L(f"  - hdg 명령→turn rate 반응 lag: 약 {lag_v['lag_ticks']} ticks (corr={lag_v['corr']:.2f})")
                L()

            # altitude bin → vertical speed
            vs = derived["A0100"].get("vs_fts")
            if alt is not None and vs is not None and len(alt) == len(vs):
                L("- **Altitude Bin → Vertical Speed 반응**")
                for abin in (0, 1, 2, 3, 4):
                    idx = alt == abin
                    if idx.any():
                        L(f"  - alt={abin}: 평균 VS={vs[idx].mean():.1f} ft/s (n={idx.sum()})")
                L()

            # reward 분석
            reward = meta.get("reward")
            if reward is not None and len(reward) > 0:
                L("- **Reward 흐름**")
                L(f"  - 평균: {reward.mean():.3f}, max: {reward.max():.3f}, min: {reward.min():.3f}")
                # reward 변동성 (후반 vs 초반)
                n3 = len(reward)//3
                if n3 > 0:
                    early_r = reward[:n3].mean()
                    late_r = reward[-n3:].mean()
                    L(f"  - 초반 reward: {early_r:.3f}, 후반 reward: {late_r:.3f}")
                L()

            # active node 분석
            nodes = meta.get("active_nodes")
            if nodes is not None and len(nodes) > 0:
                node_counts = Counter(nodes)
                total_n = len(nodes)
                L("- **Active Node 점유율 (Top 5)**")
                for node, cnt in node_counts.most_common(5):
                    L(f"  - {node}: {cnt} ({cnt/total_n*100:.1f}%)")
                L()

            # BFM situation별 throttle
            bfm_sit = meta.get("bfm_sit")
            if bfm_sit is not None and thr_meta is not None and len(bfm_sit) == len(thr_meta):
                L("- **BFM Situation → Throttle**")
                for sit in sorted(set(bfm_sit)):
                    idx = bfm_sit == sit
                    if idx.any():
                        L(f"  - {sit}: 평균 throttle={thr_meta[idx].mean():.2f} (n={idx.sum()})")
                L()
        else:
            L("- meta CSV에 throttle 데이터 부족")
    else:
        L("- meta CSV 없음 → 5b 상세 분석 불가")
    L()

    L("## 6. 조종 입력 분석 (us)")
    L()
    for name, arr in (("roll", a["roll_in"]), ("pitch", a["pitch_in"]), ("yaw", a["yaw_in"]), ("throttle", a["thr"])):
        sat = saturation_stats(arr)
        L(f"- **{name}**: 평균절대값={sat['mean_abs']:.3f}, 포화율(>0.9)={sat['sat_frac']*100:.1f}%")
    L()

    L("## 7. 자동 진단 및 개선 방향")
    L()
    verdicts = []
    if pattern == "E_undetermined":
        verdicts.append("- 교전 패턴이 불분명 → circle fit 잔차 확인, 더 긴 교전 데이터 권장")
    if wez_count == 0:
        verdicts.append("- WEZ 진입 0회 → 상대방이 계속 거리 유지, 추격 전술 또는 속도 우위 필요")
    elif _wez_efficiency(wez_segs, n_steps) < 0.01:
        verdicts.append("- WEZ 체류 시간이 매우 짧음 → ATA 안정화 또는 선회 반경 조정 필요")
    if "A0100" in derived and "B0100" in derived:
        ed = derived.get("Es_diff")
        if ed is not None and ed[-1] < -500:
            verdicts.append(f"- 후반 에너지 열세 ({ed[-1]:+.0f} ft) → 고도/속도 보존 전술 필요")
    if bt_rnn.startswith("THROTTLE BOTTLENECK"):
        verdicts.append("- BT→RNN throttle 병목 → RNN fine-tuning 또는 direct throttle override 권장")
    sat_roll = saturation_stats(a["roll_in"])
    if sat_roll["sat_frac"] > 0.3:
        verdicts.append("- roll 입력 포화 과다 → 선회 제어 한계, 과도한 요(rate) 명령 확인")
    if not verdicts:
        verdicts.append("- 뚜렷한 이상 신호 없음. 그래프 패널 상세 확인 권장.")
    for v in verdicts:
        L(v)
    L()

    L("## 8. 참고")
    L()
    L("- 단위: 고도 ft, 거리 ft, 속도 kts, 각도 deg, 에너지 ft")
    L("- WEZ 기준: ATA < 12°, 거리 500~3000 ft")
    L("- BFM Phase: OBFM(offensive), DBFM(defensive), HABFM(horizontal), NEUTRAL")
    L()

    Path(out_md).write_text("\n".join(lines), encoding="utf-8")
    print(f"report saved: {out_md}")


if __name__ == "__main__":
    main()

