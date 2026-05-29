"""R15-J v2/v3 (2026-05-29): bt_vs_bt 매치 종합 3D + 시계열 + 자동 패턴 분류 진단 도구.

v3 추가 (8 DRAW root-cause 판별 강화 — TOOL_V3_SPEC.md):
  A1: ACMI 제어입력(roll/pitch/throttle) 파싱 + 포화율 → '명령(원인)' signal.
      roll≈0=POLICY DEGENERATE vs roll 포화=PHYSICS LIMIT 자동 판별(verdict).
  A2: meta CSV 의 bin action(action_hdg/vel/alt)+active_node 오버레이.
      ⚠️ ego 운동학 컬럼은 per-agent 복사 버그로 오염 → action_* 만 화이트리스트.
  B1: circle fit 정규화 잔차 → 직선/figure-8 의 가짜 원 게이트(good_circle).
  B2: phase-lock 정량(lock_frac_0/180 + drift) → v10 진짜 평형 판별.
  B3: 분류기 단조성 체크 + 점수기반 argmax → v7 의 C 오탐 수정.
  (C 다중 run 집계 / D cutoff geometry 는 보류 — SPEC 참조)


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
# A1: 제어입력 (ACMI 에 이미 기록됨, A0100/B0100 양쪽) — "명령(원인)" signal
ROLL_RE = re.compile(r"RollControlInput=([\-\d\.eE]+)")
PITCH_RE = re.compile(r"PitchControlInput=([\-\d\.eE]+)")
YAW_RE = re.compile(r"YawControlInput=([\-\d\.eE]+)")
THR_RE = re.compile(r"Throttle=([\-\d\.eE]+)")

# A2: meta CSV 의 신뢰 가능 컬럼 (per-agent 정상). 구/신 버전 컬럼명 모두 지원.
#   ⚠️ ego_vc_kts/specific_energy_ft/ata_deg/turn_rate_degs 는 per-agent 복사
#      버그로 오염 → 절대 읽지 않음. action_*/active_node 만 화이트리스트.
_META_ACTION_COLS = {
    "alt": ("action_alt", "action_altitude"),
    "hdg": ("action_hdg", "action_heading"),
    "vel": ("action_vel", "action_velocity"),
}


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
                             (AA_RE, "aa"), (DIST_RE, "dist"), (CR_RE, "cr"),
                             (ROLL_RE, "roll"), (PITCH_RE, "pitch"),
                             (YAW_RE, "yaw"), (THR_RE, "thr")):
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
                                       "dist", "cr", "roll", "pitch",
                                       "yaw", "thr")}
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
            out[uid]["roll"].append(e.get("roll", 0.0))
            out[uid]["pitch"].append(e.get("pitch", 0.0))
            out[uid]["yaw"].append(e.get("yaw", 0.0))
            out[uid]["thr"].append(e.get("thr", 0.5))
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
        # turn radius R = V / omega (omega rad/s) — div-by-zero 안전 처리
        omega_rad = np.radians(omega)
        safe = np.abs(omega_rad) > 0.01
        R = np.where(safe, v_ms / np.where(safe, omega_rad, 1.0), np.inf)
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

    B1: (cn, ce, R, resid_norm) 반환 — resid_norm = RMS(점-원 거리)/R.
        직선/figure-8 은 lstsq 가 쓰레기 원을 뱉으므로 resid_norm 으로
        '진짜 원인지' 게이트. resid_norm 작을수록 원에 가까움.
    Returns (cn, ce, R, resid_norm) or None.
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
        # B1: 정규화 잔차 — 각 점의 중심거리와 R 의 RMS 편차 / R
        radii = np.sqrt((n_arr - cn) ** 2 + (e_arr - ce) ** 2)
        resid_norm = float(np.sqrt(np.mean((radii - R) ** 2)) / R)
        return cn, ce, R, resid_norm
    except np.linalg.LinAlgError:
        return None


# B1: 이 값보다 큰 정규화 잔차면 '원 아님'으로 간주 (직선/궤적 노이즈)
CIRCLE_RESID_MAX = 0.25


def good_circle(fit):
    """fit_circle 결과가 신뢰 가능한 원인가 (resid_norm 게이트)."""
    return fit is not None and fit[3] <= CIRCLE_RESID_MAX


def saturation_stats(arr, thr=0.9):
    """A1: 제어입력 포화율 — |input| > thr 인 tick 비율 + 평균 |input|.
    roll≈0 이면 '선회 명령 안 함'(policy degenerate),
    roll 포화면 '명령했으나 airframe/G 한계'(물리 한계) 를 가른다.
    """
    if arr is None or len(arr) == 0:
        return {"sat_frac": 0.0, "mean_abs": 0.0}
    a = np.abs(np.asarray(arr, dtype=float))
    return {"sat_frac": float(np.mean(a > thr)), "mean_abs": float(np.mean(a))}


def compute_phase_lock(phase_diff):
    """B2: phase-lock 정량화.

    lock_frac_0   : |phase_diff| < 30°    (동상 — 같은 방향 정렬)
    lock_frac_180 : ||phase_diff|-180|<30 (역상 — figure-8 거울대칭 평형)
    drift         : 50-구간 평균들의 std (정상성; 작으면 진짜 평형)
    """
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
    """A2: meta CSV 에서 per-agent 정상 컬럼만 로드 (us = A0100/A* 행).

    화이트리스트: action_alt/hdg/vel (구·신 컬럼명) + active_node.
    운동학 필드는 복사 버그로 오염되어 의도적으로 읽지 않는다.
    Returns dict{step, alt, hdg, vel, node} or None.
    """
    import csv as _csv
    p = Path(csv_path)
    if not p.exists():
        return None
    rows = []
    with open(p, newline="", encoding="utf-8-sig") as f:
        reader = _csv.DictReader(f)
        cols = reader.fieldnames or []
        # 구/신 컬럼명 해석
        resolved = {}
        for key, names in _META_ACTION_COLS.items():
            for nm in names:
                if nm in cols:
                    resolved[key] = nm
                    break
        node_col = "active_node" if "active_node" in cols else None
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
        out["node"] = [r.get(node_col, "") for r in rows] if node_col else []
    return out


def _safe_int(v):
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return -1


def dist_monotonic_frac(dist):
    """B3: 거리 단조 증가 비율 (slope 부호 일관성).
    대진폭 oscillation(v7) 을 C 로 오탐하지 않도록 — 진짜 직선 도주는
    거의 모든 tick 에서 dist 증가.
    """
    if len(dist) < 2:
        return 0.0
    d = np.diff(dist)
    return float(np.mean(d > 0))


def classify_pattern(traj, derived):
    """매치 패턴 자동 분류 (B3: 점수기반 argmax + 단조성/잔차 게이트).

    Returns (label, scores_dict). first-match return 제거 — 모든 후보를
    점수화 후 argmax. 잘못된 패턴 → 잘못된 K-hint 오염 방지.
    """
    a = traj["A0100"]
    b = traj["B0100"]
    if len(a["n"]) < 100:
        return "UNKNOWN", {}

    scores = {}
    dist = a["dist"]
    mono = dist_monotonic_frac(dist)
    late_dist = dist[100:].mean() if len(dist) > 100 else dist.mean()
    early_dist = dist[:100].mean()
    grew = late_dist / max(1.0, early_dist)

    # C_linear_extend: 단조성 높음(>0.7) AND 순증가 AND 멀어짐
    # (기존 버그: mean-ratio 만 봐서 oscillation 오탐 → 단조성 필수화)
    c_score = 0.0
    if mono > 0.7 and grew > 1.3 and late_dist > 6000:
        c_score = mono + min(1.0, (grew - 1.0))
    scores["C_linear_extend"] = c_score

    # circle 기반 패턴 — resid 게이트 통과한 fit 만 신뢰 (B1)
    fit_a = fit_circle(a["n"], a["e"])
    fit_b = fit_circle(b["n"], b["e"])
    a_ok, b_ok = good_circle(fit_a), good_circle(fit_b)
    if a_ok and b_ok:
        ca, ea, Ra, ra = fit_a
        cb, eb, Rb, rb = fit_b
        center_dist = np.sqrt((ca - cb) ** 2 + (ea - eb) ** 2)
        rr = Ra / Rb if Rb > 0 else 99
        fit_quality = 1.0 - 0.5 * (ra + rb)  # 잔차 작을수록 높음
        co_centric = center_dist < min(Ra, Rb) * 0.5
        offset = center_dist > (Ra + Rb) * 0.4
        similar_R = 0.7 < rr < 1.4
        scores["A_co_centric_scissors"] = (
            fit_quality if (co_centric and similar_R) else 0.0)
        scores["B_offset_spiral"] = fit_quality if offset else 0.0
        scores["D_inside_outside"] = (
            fit_quality if (co_centric and not similar_R) else 0.0)

    # A' figure-8: phase-lock 역상(180°) 우세 (B2) — std 보다 정밀
    pl = compute_phase_lock(derived.get("phase_diff"))
    if pl is not None:
        scores["A'_figure8_lemniscate"] = pl["lock_frac_180"]

    best = max(scores, key=scores.get) if scores else "E_undetermined"
    if not scores or scores[best] <= 0.0:
        best = "E_undetermined"
    return best, scores


def plot_comprehensive(traj, derived, title, out_path, dmg_us_to_opp=0,
                       dmg_opp_to_us=0, meta=None):
    fig = plt.figure(figsize=(20, 20))
    gs = gridspec.GridSpec(5, 4, figure=fig, hspace=0.45, wspace=0.35)

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
    # Circle fits — B1: resid 표기 + 게이트 통과 여부로 투명도 차등
    fit_a = fit_circle(a["n"], a["e"])
    fit_b = fit_circle(b["n"], b["e"])
    if fit_a:
        ca, ea, Ra, ra = fit_a
        ok = good_circle(fit_a)
        theta = np.linspace(0, 2 * np.pi, 100)
        ax_td.plot(ea + Ra * np.cos(theta), ca + Ra * np.sin(theta),
                   "b--", alpha=0.5 if ok else 0.12,
                   label=f"us fit R={Ra:.0f} resid={ra:.2f}{'' if ok else ' (X)'}")
        ax_td.scatter([ea], [ca], c="cyan", marker="x", s=80)
    if fit_b:
        cb, eb, Rb, rb = fit_b
        ok = good_circle(fit_b)
        theta = np.linspace(0, 2 * np.pi, 100)
        ax_td.plot(eb + Rb * np.cos(theta), cb + Rb * np.sin(theta),
                   "r--", alpha=0.5 if ok else 0.12,
                   label=f"opp fit R={Rb:.0f} resid={rb:.2f}{'' if ok else ' (X)'}")
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
    pattern, scores = classify_pattern(traj, derived)
    # WEZ stats
    wez_count = len(wez_segs)
    wez_total = sum(d for _, _, d in wez_segs)
    wez_max_dwell = max((d for _, _, d in wez_segs), default=0)
    wez_mean_dwell = wez_total / wez_count if wez_count > 0 else 0
    # 분류 보조 stats (B1: resid 포함)
    fit_str = ""
    if fit_a and fit_b:
        ca, ea, Ra, ra = fit_a
        cb, eb, Rb, rb = fit_b
        center_dist = np.sqrt((ca - cb) ** 2 + (ea - eb) ** 2)
        fit_str = (f"circle fit: us R={Ra:.0f}m resid={ra:.2f}{'' if good_circle(fit_a) else '(X)'}, "
                   f"opp R={Rb:.0f}m resid={rb:.2f}{'' if good_circle(fit_b) else '(X)'}, "
                   f"center_dist={center_dist:.0f}m, R_ratio={Ra/Rb:.2f}\n")
    # B2: phase-lock 정량
    phase_str = ""
    pl = compute_phase_lock(derived.get("phase_diff"))
    if pl is not None:
        pd = derived["phase_diff"]
        phase_str = (f"phase: mean={pd.mean():.0f}° std={pd.std():.0f}° | "
                     f"lock0={pl['lock_frac_0']*100:.0f}% "
                     f"lock180={pl['lock_frac_180']*100:.0f}% "
                     f"drift={pl['drift']:.0f}°\n")
    es_str = ""
    if "A0100" in derived and "B0100" in derived:
        Es_diff = derived["A0100"]["Es"][-1] - derived["B0100"]["Es"][-1]
        es_str = f"final Es advantage: {Es_diff:+.0f}m (positive=we higher Es)\n"
    # A1: 제어입력 포화 — '명령(원인)' 진단의 핵심
    sat_roll = saturation_stats(a["roll"])
    sat_pitch = saturation_stats(a["pitch"])
    ctrl_str = (f"CTRL(us): |roll| mean={sat_roll['mean_abs']:.2f} sat={sat_roll['sat_frac']*100:.0f}% | "
                f"|pitch| mean={sat_pitch['mean_abs']:.2f} sat={sat_pitch['sat_frac']*100:.0f}%\n")
    # A1 verdict: 무기동(policy degenerate) vs 포화(물리 한계)
    verdict = _root_cause_verdict(sat_roll, sat_pitch, wez_total)
    # A2: bin action 분포 (meta CSV 있을 때만)
    act_str = _action_distribution_str(meta)
    diag = (
        f"=== AUTO DIAGNOSIS ===\n"
        f"Pattern: {pattern}\n"
        f"ROOT-CAUSE VERDICT: {verdict}\n\n"
        f"=== METRICS ===\n"
        f"ticks: {n_steps}\n"
        f"dmg us→opp: {dmg_us_to_opp:.1f}, opp→us: {dmg_opp_to_us:.1f}\n"
        f"WEZ segments: {wez_count}, total dwell: {wez_total} ticks\n"
        f"  max dwell: {wez_max_dwell}, mean dwell: {wez_mean_dwell:.1f}\n"
        f"{fit_str}{phase_str}{es_str}{ctrl_str}{act_str}\n"
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

    # === Row 5: 제어입력(A1) + bin action(A2) — '명령(원인)' signal ===

    # [5,0] us 제어입력 (roll/pitch/throttle) — 무기동 vs 포화 판별
    ax_ci = fig.add_subplot(gs[4, 0])
    ax_ci.plot(a["t"], a["roll"], "b-", alpha=0.7, label="roll in")
    ax_ci.plot(a["t"], a["pitch"], "g-", alpha=0.6, label="pitch in")
    ax_ci.plot(a["t"], a["thr"], "m-", alpha=0.5, label="throttle")
    ax_ci.axhline(0.9, color="r", ls=":", alpha=0.4)
    ax_ci.axhline(-0.9, color="r", ls=":", alpha=0.4, label="±0.9 saturation")
    ax_ci.set_ylim(-1.1, 1.1)
    ax_ci.set_xlabel("time (s)")
    ax_ci.set_ylabel("control input")
    ax_ci.set_title(f"US control (roll sat={sat_roll['sat_frac']*100:.0f}%)")
    ax_ci.legend(fontsize=7)
    ax_ci.grid(True, alpha=0.3)

    # [5,1] opp 제어입력 — 적 공격성 비교
    ax_cio = fig.add_subplot(gs[4, 1])
    ax_cio.plot(b["t"], b["roll"], "r-", alpha=0.7, label="opp roll in")
    ax_cio.plot(b["t"], b["pitch"], color="orange", alpha=0.6, label="opp pitch in")
    ax_cio.axhline(0.9, color="r", ls=":", alpha=0.3)
    ax_cio.axhline(-0.9, color="r", ls=":", alpha=0.3)
    ax_cio.set_ylim(-1.1, 1.1)
    ax_cio.set_xlabel("time (s)")
    ax_cio.set_ylabel("control input")
    ax_cio.set_title("OPP control input")
    ax_cio.legend(fontsize=7)
    ax_cio.grid(True, alpha=0.3)

    # [5,2] bin action (A2) — meta CSV 있을 때
    ax_act = fig.add_subplot(gs[4, 2])
    if meta is not None:
        ax_act.step(meta["step"], meta["hdg"], "b-", where="post", alpha=0.8, label="hdg bin (0-8)")
        ax_act.step(meta["step"], meta["vel"], "m-", where="post", alpha=0.6, label="vel bin (0-4)")
        ax_act.step(meta["step"], meta["alt"], "g-", where="post", alpha=0.6, label="alt bin (0-4)")
        ax_act.axhline(4, color="gray", ls=":", alpha=0.4, label="hdg=4 (straight)")
        ax_act.set_xlabel("step")
        ax_act.set_ylabel("action bin")
        ax_act.set_title("US commanded action bins (A2)")
        ax_act.legend(fontsize=7)
    else:
        ax_act.text(0.5, 0.5, "no --meta CSV\n(bin actions unavailable)",
                    transform=ax_act.transAxes, ha="center", va="center", fontsize=11)
        ax_act.set_title("US action bins (A2 — needs --meta)")
    ax_act.grid(True, alpha=0.3)

    # [5,3] 결정 요약 텍스트 — command distribution + verdict
    ax_dec = fig.add_subplot(gs[4, 3])
    ax_dec.axis("off")
    dec_txt = (
        f"=== COMMAND-LEVEL (원인) ===\n\n"
        f"{verdict}\n\n"
        f"{_action_distribution_str(meta, full=True)}"
    )
    ax_dec.text(0, 1, dec_txt, family="monospace", fontsize=9,
                verticalalignment="top", transform=ax_dec.transAxes,
                bbox=dict(boxstyle="round,pad=0.5", fc="honeydew", alpha=0.7))

    fig.suptitle(f"R15-J v2 진단: {title} | Pattern: {pattern}", fontsize=14, y=0.997)
    plt.savefig(out_path, dpi=90, bbox_inches="tight")
    plt.close()
    print(f"saved: {out_path}")
    print(f"  Pattern: {pattern}  scores: { {k: round(v,2) for k,v in scores.items()} }")
    print(f"  VERDICT: {verdict}")
    print(f"  WEZ segments: {wez_count}, total dwell: {wez_total} ticks")


def _root_cause_verdict(sat_roll, sat_pitch, wez_total):
    """A1: 제어입력으로 'representation 한계 vs policy degenerate' 판별.

    - roll 거의 0 (mean<0.15) + WEZ 없음 → 선회 명령 자체를 안 함 = POLICY DEGENERATE
    - roll/pitch 자주 포화 (sat>30%) + WEZ 없음 → 명령했으나 못 따라감 = PHYSICS LIMIT
    - 그 외 → 혼합/추적 불안정
    """
    rm, rs = sat_roll["mean_abs"], sat_roll["sat_frac"]
    ps = sat_pitch["sat_frac"]
    if wez_total > 30:
        return "ENGAGING (WEZ 확보됨 — stalemate 아님/측정 재확인)"
    if rm < 0.15 and rs < 0.05:
        return "POLICY DEGENERATE — 선회 명령 거의 없음 (직진도주). representation 무관"
    if rs > 0.30 or ps > 0.30:
        return "PHYSICS LIMIT — 제어 포화에도 못 가림 (airframe/G/에너지 한계)"
    return "MIXED — 기동하나 추적 전환 실패 (tracking 불안정)"


def _action_distribution_str(meta, full=False):
    """A2: bin action 분포 텍스트. degenerate(직진/풀가속 우세) 자동 표기."""
    if meta is None:
        return "" if not full else "(no --meta CSV → bin actions 없음)\n"
    hdg, vel, alt = meta["hdg"], meta["vel"], meta["alt"]
    n = len(hdg)
    if n == 0:
        return ""
    hdg4 = float(np.mean(hdg == 4)) * 100
    vel4 = float(np.mean(vel == 4)) * 100
    hard_turn = float(np.mean((hdg <= 1) | (hdg >= 7))) * 100
    decel = float(np.mean(vel <= 1)) * 100
    s = (f"action: hdg=4(직진) {hdg4:.0f}% | hard-turn(0/1/7/8) {hard_turn:.0f}% | "
         f"vel=4(풀가속) {vel4:.0f}% | decel(0/1) {decel:.0f}%\n")
    if full:
        flag = ""
        if hdg4 > 70 and vel4 > 70:
            flag = ">>> DEGENERATE: 직진+풀가속 우세 (mutual extension)\n"
        elif hard_turn > 50:
            flag = ">>> 급선회 우세 — 기동 중 (추적/전환 문제)\n"
        from collections import Counter
        nodes = Counter(meta.get("node", []))
        top = ", ".join(f"{k}:{v*100//n}%" for k, v in nodes.most_common(4))
        s = s + flag + f"top nodes: {top}\n"
    return s


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
    ap.add_argument("--meta", help="A2: bin action 용 meta CSV (생략 시 동일 stem _meta.csv 자동 탐색)")
    args = ap.parse_args()

    replay = Path(args.replay)
    if not replay.exists():
        print(f"ERROR: {replay} not found")
        sys.exit(1)
    out = Path(args.out) if args.out else replay.with_suffix(".3d.v2.png")

    # A2: meta CSV 자동 탐색 (--meta 우선, 없으면 sibling *_meta.csv)
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
        print(f"  meta CSV: {meta_path} → {'loaded' if meta else 'FAILED/incompatible (ACMI-only 진행)'}")

    print(f"parsing {replay}...")
    ticks = parse_acmi(replay)
    print(f"  {len(ticks)} ticks")
    traj = extract_trajectory(ticks)
    derived = compute_derived(traj)
    title = replay.stem
    plot_comprehensive(traj, derived, title, out, args.dmg_us, args.dmg_opp, meta=meta)


if __name__ == "__main__":
    main()
