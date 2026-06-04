"""plot_match_3d_v2_nme.py — new_match_engine 전용 3D 매치 분석 도구.

유지: 3D·circle fit·phase lock·WEZ·에너지·BFM phase (검증된 핵심)
수정: corner speed 320, 제어입력은 우리 u(aileron/elev/rud/thr) 기록
교체: RNN bin 패널 → Tactic timeline + advantage + setpoint추종 (새 엔진 의미값)

usage:
    python tools/plot_match_3d_v2_nme.py --replay <acmi> [--meta <csv>] [--out plot.png]
"""
from __future__ import annotations
import argparse
import csv
import re
import sys
from collections import Counter
from pathlib import Path

import numpy as np
import matplotlib
matplotlib.use("Agg")          # ★ 비대화형 백엔드 — 스크립트/스레드 Tk 크래시 방지 (pyplot import 전 필수)
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
HEALTH_RE = re.compile(r"Health=([\-\d\.eE]+)")
ATA_RE = re.compile(r"ATA=([\-\d\.eE]+)")
AA_RE = re.compile(r"AA=([\-\d\.eE]+)")
DIST_RE = re.compile(r"Distance=([\-\d\.eE]+)")
CR_RE = re.compile(r"ClosureRate=([\-\d\.eE]+)")
AIL_RE = re.compile(r"RollControlInput=([\-\d\.eE]+)")
ELEV_RE = re.compile(r"PitchControlInput=([\-\d\.eE]+)")
RUD_RE = re.compile(r"YawControlInput=([\-\d\.eE]+)")
THR_RE = re.compile(r"Throttle=([\-\d\.eE]+)")

CIRCLE_RESID_MAX = 0.25
CORNER_SPEED_KTS = 320.0


def _bool(v):
    return str(v).lower() in ("true", "1", "yes")


def parse_acmi(path: Path):
    """ACMI → list[(sim_time_s, {agent: {...}})].

    new_match_engine 호환:
      - write_acmi_plot() → A0100 / B0100
      - write_acmi()      → 101 / 102
      첫 번째 기체 → A0100, 두 번째 기체 → B0100 로 매핑.
    """
    ticks = []
    cur_time = 0.0
    cur_state = None
    id_map = {}          # 원본 ID → A0100/B0100
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
            raw_uid = parts[0].strip()
            # 정적 선언 줄(101,Type=...) 무시
            if "Type=" in raw_uid or "ReferenceTime=" in raw_uid:
                continue
            # ID 매핑
            if raw_uid not in id_map:
                next_label = "A0100" if len(id_map) == 0 else "B0100"
                id_map[raw_uid] = next_label
            uid = id_map[raw_uid]
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
                            (AIL_RE, "ail"), (ELEV_RE, "elev"), (RUD_RE, "rud"), (THR_RE, "thr")):
                m = rx.search(rest)
                if m:
                    entry[key] = float(m.group(1))
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
    keys = ("t", "n", "e", "u_ft", "hdg", "cas", "health", "ata", "aa",
            "dist_ft", "cr_kts", "roll_deg", "pitch_deg", "yaw_deg",
            "ail", "elev", "rud", "thr")
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
            out[uid]["health"].append(e.get("health", 100.0))
            out[uid]["ata"].append(e.get("ata", 999.0))
            out[uid]["aa"].append(e.get("aa", 999.0))
            out[uid]["dist_ft"].append(e.get("dist_ft", 0.0))
            out[uid]["cr_kts"].append(e.get("cr_kts", 0.0))
            out[uid]["roll_deg"].append(e.get("roll_deg", 0.0))
            out[uid]["pitch_deg"].append(e.get("pitch_deg", 0.0))
            out[uid]["yaw_deg"].append(e.get("yaw_deg", 0.0))
            out[uid]["ail"].append(e.get("ail", 0.0))
            out[uid]["elev"].append(e.get("elev", 0.0))
            out[uid]["rud"].append(e.get("rud", 0.0))
            out[uid]["thr"].append(e.get("thr", 0.0))
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
    """new_match_engine: InWEZ, HCA, turn_rate 등이 ACMI에 없으므로 재계산."""
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
        in_wez = (d["ata"] < 12) & (d["dist_ft"] > 500) & (d["dist_ft"] < 3000)
        out[uid] = {
            "omega": omega, "v_ms": v_ms, "R": R, "Es": Es,
            "hdg_uw": hdg_uw, "vs_fts": vs, "phases": phases,
            "in_wez": in_wez, "turn_rate_degs": omega,
        }
    if "A0100" in out and "B0100" in out:
        min_n = min(len(out["A0100"]["hdg_uw"]), len(out["B0100"]["hdg_uw"]))
        pd = out["A0100"]["hdg_uw"][:min_n] - out["B0100"]["hdg_uw"][:min_n]
        out["phase_diff"] = ((pd + 180) % 360) - 180
        hca = np.abs(((pd + 180) % 360) - 180)
        out["hca"] = hca
        out["Es_diff"] = out["A0100"]["Es"][:min_n] - out["B0100"]["Es"][:min_n]
    return out


def detect_wez_segments(ata, dist, in_wez=None):
    n = len(ata)
    if in_wez is not None and len(in_wez) == n:
        cond = in_wez
    else:
        cond = (ata < 12) & (dist > 500) & (dist < 3000)
    segs = []
    in_seg = False
    s = 0
    for i in range(n):
        if cond[i] and not in_seg:
            in_seg = True; s = i
        elif not cond[i] and in_seg:
            in_seg = False; segs.append((s, i - 1, i - s))
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


def good_circle(fit):
    return fit is not None and fit[3] <= CIRCLE_RESID_MAX


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


# ─── new_match_engine CSV 로더 ──────────────────────────────────

def load_nme_meta(csv_path: Path):
    if not csv_path.exists():
        return None
    rows = []
    with open(csv_path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        cols = reader.fieldnames or []
        for r in reader:
            rows.append(r)
    if not rows:
        return None

    def _fa(c):
        return np.array([float(r.get(c, 0)) for r in rows])

    def _fs(c):
        return [r.get(c, "") for r in rows]

    out = {"t": _fa("t")}
    out["tac1"] = _fs("tac1")
    out["tac2"] = _fs("tac2")
    for c in ("adv", "ata", "aa", "relb", "dist", "clos", "ediff",
              "ego_alt", "ego_vc", "ego_bank", "enm_bank",
              "sp_psi", "sp_h", "sp_v", "H1", "H2"):
        out[c] = _fa(c) if c in cols else None
    for c in ("u1_thr", "u1_elev", "u1_ail", "u1_rud",
              "u2_thr", "u2_elev", "u2_ail", "u2_rud"):
        out[c] = _fa(c) if c in cols else None
    return out


def _plot_rows_1_to_2(fig, gs, a, b, times, n_steps, norm, cmap_us, cmap_opp,
                       wez_segs, fit_a, fit_b, derived, pattern, scores, meta,
                       t_clip=None):
    # Row 1
    ax3d = fig.add_subplot(gs[0, 0], projection="3d")
    step = max(1, n_steps // 800)
    for i in range(0, n_steps - 1, step):
        ax3d.plot(a["e"][i:i+2], a["n"][i:i+2], a["u_ft"][i:i+2],
                  color=cmap_us(norm(times[i])), alpha=0.5, linewidth=0.6)
        ax3d.plot(b["e"][i:i+2], b["n"][i:i+2], b["u_ft"][i:i+2],
                  color=cmap_opp(norm(times[i])), alpha=0.5, linewidth=0.6)
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
    diag = (
        f"=== AUTO DIAGNOSIS (NME) ===\n"
        f"Pattern: {pattern}\n\n"
        f"ticks: {n_steps}\n"
        f"WEZ segs: {wez_count}, total: {wez_total}, max: {wez_max}, mean: {wez_mean:.1f}\n"
        f"{fit_str}{phase_str}{es_str}"
        f"corner speed: {CORNER_SPEED_KTS:.0f} kts\n"
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
    if "hca" in derived:
        hca = derived["hca"]
        t_hca = a["t"][:len(hca)]
        ax_hca.plot(t_hca, hca, "purple", alpha=0.7, label="HCA")
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
    ax_cas.axhline(CORNER_SPEED_KTS, color="green", linestyle="--", alpha=0.4,
                   label=f"corner ~{CORNER_SPEED_KTS:.0f} kts")
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


def _plot_rows_5_to_6(fig, gs, a, b, derived, meta):
    """new_match_engine 전용 하단 패널: Tactic + advantage + setpoint + u."""
    has_meta = meta is not None and meta.get("t") is not None and len(meta["t"]) > 0
    t_meta = meta["t"] if has_meta else None

    # Row 5
    ax_tac = fig.add_subplot(gs[4, 0])
    if has_meta and meta.get("tac1"):
        tac1 = meta["tac1"]
        unique = sorted(set(tac1))
        y_map = {n: i for i, n in enumerate(unique)}
        vals1 = np.array([y_map.get(n, -1) for n in tac1])
        for i in range(len(t_meta) - 1):
            ax_tac.plot(t_meta[i:i+2], vals1[i:i+2], color="navy", linewidth=2)
        ax_tac.set_yticks(range(len(unique)))
        ax_tac.set_yticklabels(unique, fontsize=6)
        ax_tac.set_xlabel("time (s)"); ax_tac.set_title("Tactic timeline (p1)")
    else:
        ax_tac.text(0.5, 0.5, "no meta CSV", transform=ax_tac.transAxes, ha="center", va="center")
        ax_tac.set_title("Tactic timeline (p1)")
    ax_tac.grid(True, alpha=0.3)

    ax_adv = fig.add_subplot(gs[4, 1])
    if has_meta and meta.get("adv") is not None:
        adv = meta["adv"]
        ax_adv.plot(t_meta, adv, "purple", label="advantage")
        ax_adv.axhline(0, color="k", alpha=0.3)
        ax_adv.fill_between(t_meta, 0, adv, where=(adv > 0), color="blue", alpha=0.15, label="us advantage")
        ax_adv.fill_between(t_meta, 0, adv, where=(adv <= 0), color="red", alpha=0.15, label="opp advantage")
        ax_adv.set_xlabel("time (s)"); ax_adv.set_ylabel("advantage")
        ax_adv.set_title("Advantage")
        ax_adv.legend(fontsize=7)
    else:
        ax_adv.text(0.5, 0.5, "no meta CSV", transform=ax_adv.transAxes, ha="center", va="center")
        ax_adv.set_title("Advantage")
    ax_adv.grid(True, alpha=0.3)

    ax_sp_hdg = fig.add_subplot(gs[4, 2])
    if has_meta and meta.get("sp_psi") is not None and "A0100" in derived:
        sp_psi = meta["sp_psi"]
        n_common = min(len(t_meta), len(a["t"]))
        ax_sp_hdg.plot(t_meta[:n_common], sp_psi[:n_common], "b--", alpha=0.7, label="sp psi")
        ax_sp_hdg.plot(a["t"][:n_common], a["hdg"][:n_common], "r-", alpha=0.6, label="actual HDG")
        ax_sp_hdg.set_xlabel("time (s)"); ax_sp_hdg.set_ylabel("deg")
        ax_sp_hdg.set_title("Setpoint tracking — heading")
        ax_sp_hdg.legend(fontsize=7)
    else:
        ax_sp_hdg.text(0.5, 0.5, "no meta CSV", transform=ax_sp_hdg.transAxes, ha="center", va="center")
        ax_sp_hdg.set_title("Setpoint tracking — heading")
    ax_sp_hdg.grid(True, alpha=0.3)

    ax_sp_alt = fig.add_subplot(gs[4, 3])
    if has_meta and meta.get("sp_h") is not None:
        sp_h = meta["sp_h"]
        n_common = min(len(t_meta), len(a["t"]))
        # ★ actual alt 는 meta 의 절대 MSL(ego_alt) 사용. a["u_ft"]는 NED 상대고도
        #   (alt0 기준 0 시작)라 절대 sp_h 와 비교 시 ~15000ft 오프셋 버그.
        if meta.get("ego_alt") is not None:
            actual_alt = meta["ego_alt"]; t_act = t_meta
        else:                                   # fallback: 상대 u_ft + 시작 MSL 복원
            actual_alt = [u + sp_h[0] for u in a["u_ft"]]; t_act = a["t"]
        m2 = min(n_common, len(actual_alt))
        ax_sp_alt.plot(t_meta[:n_common], sp_h[:n_common], "b--", alpha=0.7, label="sp alt")
        ax_sp_alt.plot(t_act[:m2], actual_alt[:m2], "r-", alpha=0.6, label="actual alt")
        ax_sp_alt.set_xlabel("time (s)"); ax_sp_alt.set_ylabel("ft MSL")
        ax_sp_alt.set_title("Setpoint tracking — altitude")
        ax_sp_alt.legend(fontsize=7)
    else:
        ax_sp_alt.text(0.5, 0.5, "no meta CSV", transform=ax_sp_alt.transAxes, ha="center", va="center")
        ax_sp_alt.set_title("Setpoint tracking — altitude")
    ax_sp_alt.grid(True, alpha=0.3)

    # Row 6
    ax_sp_vc = fig.add_subplot(gs[5, 0])
    if has_meta and meta.get("sp_v") is not None:
        sp_v = meta["sp_v"]
        n_common = min(len(t_meta), len(a["t"]))
        ax_sp_vc.plot(t_meta[:n_common], sp_v[:n_common], "b--", alpha=0.7, label="sp VC")
        ax_sp_vc.plot(a["t"][:n_common], a["cas"][:n_common], "r-", alpha=0.6, label="actual CAS")
        ax_sp_vc.set_xlabel("time (s)"); ax_sp_vc.set_ylabel("kts")
        ax_sp_vc.set_title("Setpoint tracking — speed")
        ax_sp_vc.legend(fontsize=7)
    else:
        ax_sp_vc.text(0.5, 0.5, "no meta CSV", transform=ax_sp_vc.transAxes, ha="center", va="center")
        ax_sp_vc.set_title("Setpoint tracking — speed")
    ax_sp_vc.grid(True, alpha=0.3)

    ax_u = fig.add_subplot(gs[5, 1])
    u_drawn = False
    if has_meta and meta.get("u1_ail") is not None:
        ax_u.plot(t_meta, meta["u1_ail"], "b-", alpha=0.7, label="ail")
        ax_u.plot(t_meta, meta["u1_elev"], "g-", alpha=0.6, label="elev")
        ax_u.plot(t_meta, meta["u1_rud"], "c-", alpha=0.5, label="rud")
        ax_u.plot(t_meta, meta["u1_thr"], "m-", alpha=0.5, label="thr")
        u_drawn = True
    elif len(a.get("ail", [])) > 0:
        # ACMI 기반 제어입력 폴백
        ax_u.plot(a["t"], a["ail"], "b-", alpha=0.7, label="ail")
        ax_u.plot(a["t"], a["elev"], "g-", alpha=0.6, label="elev")
        ax_u.plot(a["t"], a["rud"], "c-", alpha=0.5, label="rud")
        ax_u.plot(a["t"], a["thr"], "m-", alpha=0.5, label="thr")
        u_drawn = True
    if u_drawn:
        ax_u.set_xlabel("time (s)"); ax_u.set_ylabel("control input")
        ax_u.set_title("US control inputs (u)")
        ax_u.legend(fontsize=7)
    else:
        ax_u.text(0.5, 0.5, "no u in ACMI/meta", transform=ax_u.transAxes, ha="center", va="center")
        ax_u.set_title("US control inputs (u)")
    ax_u.grid(True, alpha=0.3)

    ax_ed2 = fig.add_subplot(gs[5, 2])
    if has_meta and meta.get("ediff") is not None:
        ed = meta["ediff"]
        ax_ed2.plot(t_meta, ed, "purple", label="energy diff")
        ax_ed2.axhline(0, color="k", alpha=0.3)
        ax_ed2.fill_between(t_meta, 0, ed, where=(ed > 0), color="blue", alpha=0.15)
        ax_ed2.fill_between(t_meta, 0, ed, where=(ed <= 0), color="red", alpha=0.15)
        ax_ed2.set_xlabel("time (s)"); ax_ed2.set_ylabel("Es diff (ft)")
        ax_ed2.set_title("Energy diff (meta)")
    else:
        ax_ed2.text(0.5, 0.5, "no meta CSV", transform=ax_ed2.transAxes, ha="center", va="center")
        ax_ed2.set_title("Energy diff (meta)")
    ax_ed2.grid(True, alpha=0.3)

    ax_hlt = fig.add_subplot(gs[5, 3])
    if has_meta and meta.get("H1") is not None:
        ax_hlt.plot(t_meta, meta["H1"], "b-", label="H1")
        ax_hlt.plot(t_meta, meta["H2"], "r-", label="H2")
        ax_hlt.set_xlabel("time (s)"); ax_hlt.set_ylabel("health")
        ax_hlt.set_title("Health timeline")
        ax_hlt.legend(fontsize=7)
    else:
        ax_hlt.plot(a["t"], a["health"], "b-", label="us")
        ax_hlt.plot(b["t"], b["health"], "r-", label="opp")
        ax_hlt.set_xlabel("time (s)"); ax_hlt.set_ylabel("health")
        ax_hlt.set_title("Health (ACMI)")
        ax_hlt.legend(fontsize=7)
    ax_hlt.grid(True, alpha=0.3)


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
        elif isinstance(v, np.ndarray):
            out[k] = v[mask[:len(v)]] if len(v) <= len(mask) else v[mask[:len(v)]]
        else:
            out[k] = v
    return out


def plot_comprehensive(traj, derived, title, out_path, meta=None, t_clip=None):
    fig = plt.figure(figsize=(24, 28))
    gs = gridspec.GridSpec(6, 4, figure=fig, hspace=0.40, wspace=0.30)

    a = traj["A0100"]
    b = traj["B0100"]
    times = a["t"]
    n_steps = len(times)
    norm = plt.Normalize(times.min(), times.max())
    cmap_us = plt.get_cmap("Blues")
    cmap_opp = plt.get_cmap("Reds")

    in_wez_a = derived.get("A0100", {}).get("in_wez")
    wez_segs = detect_wez_segments(a["ata"], a["dist_ft"], in_wez=in_wez_a)
    fit_a = fit_circle(a["n"], a["e"])
    fit_b = fit_circle(b["n"], b["e"])
    pattern, scores = classify_pattern(traj, derived)

    _plot_rows_1_to_2(fig, gs, a, b, times, n_steps, norm, cmap_us, cmap_opp,
                      wez_segs, fit_a, fit_b, derived, pattern, scores, meta,
                      t_clip=t_clip)
    _plot_rows_3_to_4(fig, gs, a, b, derived, wez_segs)
    _plot_rows_5_to_6(fig, gs, a, b, derived, meta)

    suptitle = f"NME: {title} | Pattern: {pattern}"
    if t_clip:
        suptitle += f" | clip {t_clip[0]:.1f}-{t_clip[1]:.1f}s"
    fig.suptitle(suptitle, fontsize=14, y=0.997)
    plt.savefig(out_path, dpi=90, bbox_inches="tight")
    plt.close()
    print(f"saved: {out_path}")
    print(f"  Pattern: {pattern}  scores: { {k: round(v,2) for k,v in scores.items()} }")
    print(f"  WEZ segments: {len(wez_segs)}, total dwell: {sum(d for _,_,d in wez_segs)} ticks")


def _seg_seconds(segs, dt):
    """WEZ 세그먼트(틱) → 초."""
    return [d * dt for _, _, d in segs]


def match_report(traj, derived, meta, title="match") -> str:
    """★ 표준 매치 리포트 (승/패/무 매 경기 공통). 기계가 읽고 경기간 비교 가능한 정량 텍스트.

    7층: ①결과 ②교전성 ③위치/BFM ④에너지 ⑤기동패턴 ⑥제어 ⑦판정.
    plot_match_3d_nme 가 이미 계산하는 derived/traj 재사용 — 손튜닝 metric 금지, 게임규칙 기반.
    """
    a = traj.get("A0100", {}); b = traj.get("B0100", {})
    ta = a.get("t", np.array([]))
    if len(ta) < 2:
        return f"[{title}] 데이터 부족 (ticks={len(ta)})"
    dt = float(np.median(np.diff(ta)))
    dur = float(ta[-1] - ta[0])
    L = []
    L.append(f"================ MATCH REPORT: {title} ================")

    # ── ① 결과 ──
    h1 = meta["H1"] if (meta and meta.get("H1") is not None) else a.get("health", np.array([100.0]))
    h2 = meta["H2"] if (meta and meta.get("H2") is not None) else b.get("health", np.array([100.0]))
    us_hp = float(h1[-1]); op_hp = float(h2[-1])
    dealt = 100.0 - op_hp; taken = 100.0 - us_hp
    if us_hp <= 0.0:    outcome = "LOSS"
    elif op_hp <= 0.0:  outcome = "WIN"
    elif us_hp > op_hp: outcome = "WIN(판정)"
    elif op_hp > us_hp: outcome = "LOSS(판정)"
    else:               outcome = "DRAW"
    L.append("① 결과")
    L.append(f"   outcome={outcome}  dur={dur:.0f}s  HP us={us_hp:.0f} opp={op_hp:.0f}  "
             f"dmg dealt={dealt:.0f} taken={taken:.0f}")

    # ── ② 교전성 ──
    da = a.get("dist_ft", np.array([0.0]))
    da_m = da * 0.3048
    in_wez_a = derived.get("A0100", {}).get("in_wez")
    in_wez_b = derived.get("B0100", {}).get("in_wez")
    segs_a = detect_wez_segments(a["ata"], da, in_wez=in_wez_a)
    secs_a = _seg_seconds(segs_a, dt)
    # 적 WEZ (우리가 노출된 시간) — opp 관점 ata/dist
    if "B0100" in traj and len(b.get("ata", [])):
        segs_b = detect_wez_segments(b["ata"], b["dist_ft"], in_wez=in_wez_b)
        secs_b = _seg_seconds(segs_b, dt)
    else:
        segs_b, secs_b = [], []
    close = np.mean(np.diff(da) < 0) * 100 if len(da) > 1 else 0.0
    band_close = np.mean(da_m < 1500) * 100
    band_med = np.mean((da_m >= 1500) & (da_m < 3000)) * 100
    band_far = np.mean(da_m >= 3000) * 100
    L.append("② 교전성")
    L.append(f"   WEZ(us): {len(segs_a)}회 dwell={sum(secs_a):.1f}s max={max(secs_a) if secs_a else 0:.1f}s | "
             f"WEZ(opp노출): {len(segs_b)}회 dwell={sum(secs_b):.1f}s")
    L.append(f"   거리: min={da_m.min():.0f}m mean={da_m.mean():.0f}m | "
             f"근<1.5km {band_close:.0f}% 중1.5-3 {band_med:.0f}% 원>3 {band_far:.0f}% | closing {close:.0f}%")

    # ── ③ 위치/BFM ──
    phases = derived.get("A0100", {}).get("phases", np.array([]))
    def _pct(p): return np.mean(phases == p) * 100 if len(phases) else 0.0
    adv = meta["adv"] if (meta and meta.get("adv") is not None) else None
    adv_pos = np.mean(adv > 0) * 100 if adv is not None and len(adv) else None
    # 최초 WEZ 도달 시간
    t_first = ta[segs_a[0][0]] if segs_a else None
    L.append("③ 위치/BFM")
    L.append(f"   phase: OBFM {_pct('OBFM'):.0f}% DBFM {_pct('DBFM'):.0f}% "
             f"HABFM {_pct('HABFM'):.0f}% NEUTRAL {_pct('NEUTRAL'):.0f}% | "
             f"ATĀ={np.mean(a['ata']):.0f}° AĀ={np.mean(a['aa']):.0f}°")
    L.append(f"   advantage>0 {adv_pos:.0f}%  최초WEZ도달={'%.0fs'%t_first if t_first is not None else '없음(미교전)'}"
             if adv_pos is not None else
             f"   최초WEZ도달={'%.0fs'%t_first if t_first is not None else '없음(미교전)'}")

    # ── ④ 에너지 ──
    if "A0100" in derived and "B0100" in derived:
        es_a = derived["A0100"]["Es"]; es_b = derived["B0100"]["Es"]
        esd = derived.get("Es_diff", es_a[:min(len(es_a),len(es_b))]-es_b[:min(len(es_a),len(es_b))])
        es_pos = np.mean(esd > 0) * 100 if len(esd) else 0.0
        bleed = float(es_a.max() - es_a.min())
        cas = a.get("cas", np.array([0.0]))
        corner = np.mean(np.abs(cas - CORNER_SPEED_KTS) < 30) * 100
        L.append("④ 에너지")
        L.append(f"   Es us={es_a[-1]:.0f} opp={es_b[-1]:.0f} | Es_diff>0 {es_pos:.0f}% | "
                 f"us bleed={bleed:.0f}ft | 코너±30kt 준수 {corner:.0f}%")

    # ── ⑤ 기동패턴 ──
    pattern, scores = classify_pattern(traj, derived)
    fit_a = fit_circle(a["n"], a["e"]); fit_b = fit_circle(b["n"], b["e"])
    pl = compute_phase_lock(derived.get("phase_diff"))
    ra = f"{fit_a[2]:.0f}m(r{fit_a[3]:.2f})" if fit_a else "—"
    rb = f"{fit_b[2]:.0f}m(r{fit_b[3]:.2f})" if fit_b else "—"
    L.append("⑤ 기동패턴")
    L.append(f"   pattern={pattern} | turnR us={ra} opp={rb} | "
             f"phase-lock 180°={pl['lock_frac_180']*100:.0f}% 0°={pl['lock_frac_0']*100:.0f}%"
             if pl else f"   pattern={pattern} | turnR us={ra} opp={rb}")

    # ── ⑥ 제어 (setpoint 추종) ──
    if meta and meta.get("sp_psi") is not None:
        n = min(len(meta["t"]), len(a["t"]))
        def _rms(sp, act):
            d = np.asarray(sp[:n]) - np.asarray(act[:n])
            d = (d + 180) % 360 - 180 if np.max(np.abs(d)) > 180 else d
            return float(np.sqrt(np.mean(d**2)))
        hdg_err = _rms(meta["sp_psi"], a["hdg"])
        tac1 = meta.get("tac1") or []
        tac_top = Counter(tac1).most_common(3)
        tac_str = " ".join(f"{k}:{v*dt:.0f}s" for k, v in tac_top)
        L.append("⑥ 제어")
        L.append(f"   setpoint 추종 hdg RMS={hdg_err:.1f}° | tactic 상위: {tac_str}")

    # ── ⑦ 판정 (데이터 기반 해석) ──
    verdict = []
    if t_first is None:
        verdict.append("미교전(WEZ 0회) — 닫기 실패가 1차 원인.")
    if band_far > 70:
        verdict.append(f"원거리 {band_far:.0f}% — extender 추격 실패 가능.")
    if outcome.startswith("WIN") and sum(secs_a) > 3:
        verdict.append(f"WEZ dwell {sum(secs_a):.0f}s 확보 → 격추 성립.")
    if "A0100" in derived and 'esd' in dir() and len(esd) and np.mean(esd) < -1000:
        verdict.append("평균 에너지 열세 — 다이브/과기동 bleed 의심.")
    if not verdict:
        verdict.append("특이 실패신호 없음 — 세부 패널 확인.")
    L.append("⑦ 판정: " + " ".join(verdict))
    L.append("=" * (len(title) + 40))
    return "\n".join(L)


def analyze_match_files(acmi_path, meta_path=None, out_dir=None,
                        title=None, make_plot=True):
    """★ 매 경기 1콜 — acmi(+csv) → report.txt + plot.png. 매치 저장 경로에서 호출.

    승/패/무 전부 동일하게 분석 (모든 결과가 데이터 자산). 반환: report 문자열.
    """
    acmi_path = Path(acmi_path)
    title = title or acmi_path.stem
    out_dir = Path(out_dir) if out_dir else acmi_path.parent
    meta = load_nme_meta(Path(meta_path)) if meta_path and Path(meta_path).exists() else None
    ticks = parse_acmi(acmi_path)
    traj = extract_trajectory(ticks)
    if "A0100" not in traj or len(traj["A0100"]["t"]) < 2:
        rep = f"[{title}] ACMI 파싱 실패/데이터 부족"
        (out_dir / "report.txt").write_text(rep, encoding="utf-8")
        return rep
    derived = compute_derived(traj)
    rep = match_report(traj, derived, meta, title=title)
    (out_dir / "report.txt").write_text(rep, encoding="utf-8")
    if make_plot:
        try:
            plot_comprehensive(traj, derived, title, out_dir / "plot.png", meta=meta)
        except Exception as e:
            print(f"  [plot skip] {e}")
    return rep


def _parse_windows(s, t_max):
    parts = [float(x.strip()) for x in s.split(",")]
    if len(parts) < 2:
        return [(0.0, t_max)]
    w = []
    for i in range(len(parts) - 1):
        w.append((parts[i], parts[i + 1]))
    return w


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--replay", required=True)
    ap.add_argument("--out")
    ap.add_argument("--meta", help="new_match_engine CSV (analyze_engagement.py 출력)")
    ap.add_argument("--windows", help="time windows: 0,30,60,90 → 0-30s,30-60s,60-90s PNGs")
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
        # 자동 탐색: replay 와 같은 폴더 내 engagement_headon.csv 또는 *_meta.csv
        for cand_name in ("engagement_headon.csv", replay.stem + "_meta.csv"):
            cand = replay.with_name(cand_name)
            if cand.exists():
                meta_path = cand
                break
    if meta_path is not None:
        meta = load_nme_meta(meta_path)
        print(f"  meta CSV: {meta_path} -> {'loaded' if meta else 'FAILED'}")

    print(f"parsing {replay}...")
    ticks = parse_acmi(replay)
    print(f"  {len(ticks)} ticks")
    traj_full = extract_trajectory(ticks)
    derived_full = compute_derived(traj_full)
    title = replay.stem
    t_max = float(traj_full["A0100"]["t"][-1]) if len(traj_full["A0100"]["t"]) else 0.0

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
            out = replay.with_suffix(f".win{i}_{t0c:.0f}-{t1c:.0f}s.nme.png")
            plot_comprehensive(sub_traj, sub_derived, title, out, meta=meta, t_clip=(t0c, t1c))
    else:
        out = Path(args.out) if args.out else replay.with_suffix(".nme.png")
        plot_comprehensive(traj_full, derived_full, title, out, meta=meta)


if __name__ == "__main__":
    main()
