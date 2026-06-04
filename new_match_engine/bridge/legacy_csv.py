"""legacy CSV 충실 재현 — new_engine 매치로그 → SDK `runner.py` _CSV_COLUMNS 형식.

연착륙(D2): 기존 SDK CSV 소비 도구가 bridge 결과에도 그대로 동작하도록 *legacy 컬럼*으로 출력.
  · 에이전트별 1행/스텝 (legacy 와 동일: agent_id A0100/B0100).
  · ~20Hz 다운샘플 (legacy env.step rate).
  · servo_*(D2a, JSBSim fcs pos) · active_node(D2b, yaml_bt Tactic) 채움.
  · new_engine 미보유 컬럼(hca/tau/lead/tc_type 등)은 공란 — 정직(legacy 만의 기하 보조량).
"""
from __future__ import annotations
import os, sys, csv, math

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "control"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "engine"))
from judge import is_in_wez   # noqa: E402

_G = 32.174
_KT_TO_FPS = 1.68781

# legacy src/match/runner.py _CSV_COLUMNS 순서 그대로
_COLS = [
    "step", "sim_time_sec", "agent_id", "tree_name",
    "ego_altitude_ft", "ego_vc_kts", "heading_deg", "roll_deg", "pitch_deg",
    "specific_energy_ft", "ps_fts",
    "distance_ft", "ata_deg", "aa_deg", "hca_deg", "tau_deg", "alt_gap_ft",
    "closure_rate_kts", "turn_rate_degs", "in_39_line", "overshoot_risk", "tc_type",
    "ata_lead_deg", "tau_lead_deg", "side_flag", "energy_diff_ft",
    "bfm_situation",
    "ego_health", "enm_health", "ego_damage_dealt", "enm_damage_dealt",
    "in_wez", "enm_in_wez", "reward",
    "action_altitude", "action_heading", "action_velocity",
    "aileron", "elevator", "rudder", "throttle",
    "servo_aileron", "servo_elevator", "servo_rudder",
    "active_node", "active_nodes_path",
]


def _es(alt_ft, vc_kts):
    v = vc_kts * _KT_TO_FPS
    return alt_ft + v * v / (2 * _G)


def _downsample(log, hz=20.0):
    """t 기준 ~hz 로 다운샘플 (legacy env.step rate 정렬)."""
    out, nxt, dt = [], -1e9, 1.0 / hz
    for r in log:
        if r["t"] >= nxt:
            out.append(r); nxt = r["t"] + dt - 1e-9
    return out


def write_legacy_csv(log, path, tree1_name="tree1", tree2_name="tree2"):
    """new_engine 매치로그 → legacy 형식 CSV. 에이전트별 1행/스텝."""
    if not log:
        return
    rows = _downsample(log)
    os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=_COLS)
        w.writeheader()
        for step, r in enumerate(rows, 1):
            # 양 에이전트 관점 (a=공격자관점 obs). dmg_dealt ≈ 100 − 적 HP (단일 피해원 근사).
            for aid, alt, vc, psi, phi, th, ata, aa, hp, ehp, surf, srv, tac, clos, ediff in (
                ("A0100", r["alt1"], r["vc1"], r["psi1"], r["phi1"], r["theta1"],
                 r["ata12"], r["aa12"], r["H1"], r["H2"],
                 (r["thr1"], r["elev1"], r["ail1"], r["rud1"]),
                 (r.get("srv_ail1", ""), r.get("srv_elev1", ""), r.get("srv_rud1", "")),
                 r.get("tac1", ""), r.get("clos12", ""), r.get("ediff", "")),
                ("B0100", r["alt2"], r["vc2"], r["psi2"], r["phi2"], r["theta2"],
                 r["ata21"], r["aa21"], r["H2"], r["H1"],
                 (r["thr2"], r["elev2"], r["ail2"], r["rud2"]),
                 (r.get("srv_ail2", ""), r.get("srv_elev2", ""), r.get("srv_rud2", "")),
                 r.get("tac2", ""), r.get("clos12", ""), -float(r.get("ediff", 0) or 0)),
            ):
                w.writerow({
                    "step": step, "sim_time_sec": round(r["t"], 3),
                    "agent_id": aid, "tree_name": tree1_name if aid == "A0100" else tree2_name,
                    "ego_altitude_ft": alt, "ego_vc_kts": vc, "heading_deg": psi,
                    "roll_deg": phi, "pitch_deg": th,
                    "specific_energy_ft": round(_es(alt, vc), 1), "ps_fts": "",
                    "distance_ft": r["dist"], "ata_deg": ata, "aa_deg": aa,
                    "hca_deg": "", "tau_deg": "",
                    "alt_gap_ft": round(alt - (r["alt2"] if aid == "A0100" else r["alt1"]), 1),
                    "closure_rate_kts": clos, "turn_rate_degs": "",
                    "in_39_line": "", "overshoot_risk": "", "tc_type": "",
                    "ata_lead_deg": "", "tau_lead_deg": "", "side_flag": "",
                    "energy_diff_ft": round(float(ediff or 0), 1),
                    "bfm_situation": "",
                    "ego_health": hp, "enm_health": ehp,
                    "ego_damage_dealt": round(100.0 - ehp, 1),     # 근사(단일 피해원)
                    "enm_damage_dealt": round(100.0 - hp, 1),
                    "in_wez": is_in_wez(ata, r["dist"]),
                    "enm_in_wez": is_in_wez(r["ata21"] if aid == "A0100" else r["ata12"], r["dist"]),
                    "reward": 0.0,
                    "action_altitude": "", "action_heading": "", "action_velocity": "",
                    "aileron": surf[2], "elevator": surf[1], "rudder": surf[3], "throttle": surf[0],
                    "servo_aileron": srv[0], "servo_elevator": srv[1], "servo_rudder": srv[2],
                    "active_node": tac, "active_nodes_path": tac,
                })
