"""Compare original action_X vs SmartX action: bin output 차이 분석.

12 representative scenarios × 각 BFM pair → diff table.
사용자 명령 2026-05-27: 새 BFM 도입 시 원본 vs 새 동작 비교 필수.
"""
import sys
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# Import our cost_branch_selector (필요한 globals 초기화)
from examples.pursuit_chase_v1.nodes import cost_branch_selector as cbs


SCENARIOS = {
    "WEZ_lock":         {"ata_deg": 5,  "aa_deg": 175, "distance_ft": 1500,
                          "closure_rate_kts":  30, "energy_diff_ft":  +500,
                          "alt_gap_ft":   0,  "relative_bearing_deg":  3,
                          "ego_altitude_ft": 15000, "ego_vc_kts": 380,
                          "turn_rate_degs": 3, "overshoot_risk": False, "in_39_line": True},
    "WEZ_overshoot":    {"ata_deg": 10, "aa_deg": 170, "distance_ft": 1200,
                          "closure_rate_kts": 300, "energy_diff_ft": 1000,
                          "alt_gap_ft": -200, "relative_bearing_deg":  5,
                          "ego_altitude_ft": 15000, "ego_vc_kts": 500,
                          "turn_rate_degs": 5, "overshoot_risk": True,  "in_39_line": True},
    "tail_chase_far":   {"ata_deg": 11, "aa_deg": 169, "distance_ft": 12000,
                          "closure_rate_kts": -10, "energy_diff_ft": -3000,
                          "alt_gap_ft": -1500, "relative_bearing_deg":  4,
                          "ego_altitude_ft": 18000, "ego_vc_kts": 420,
                          "turn_rate_degs": 1, "overshoot_risk": False, "in_39_line": True},
    "parallel_stuck":   {"ata_deg": 15, "aa_deg": 165, "distance_ft": 10000,
                          "closure_rate_kts":   5, "energy_diff_ft":  -500,
                          "alt_gap_ft":  500, "relative_bearing_deg":  6,
                          "ego_altitude_ft": 16000, "ego_vc_kts": 400,
                          "turn_rate_degs": 2, "overshoot_risk": False, "in_39_line": True},
    "lufbery_neutral":  {"ata_deg": 90, "aa_deg":  90, "distance_ft":  3000,
                          "closure_rate_kts":   0, "energy_diff_ft":     0,
                          "alt_gap_ft":   0, "relative_bearing_deg": 90,
                          "ego_altitude_ft": 15000, "ego_vc_kts": 380,
                          "turn_rate_degs":12, "overshoot_risk": False, "in_39_line": False},
    "opp_threat":       {"ata_deg": 60, "aa_deg":  15, "distance_ft":  2000,
                          "closure_rate_kts": 150, "energy_diff_ft": -2000,
                          "alt_gap_ft": 800, "relative_bearing_deg": 30,
                          "ego_altitude_ft": 14000, "ego_vc_kts": 350,
                          "turn_rate_degs": 8, "overshoot_risk": False, "in_39_line": False},
    "we_offensive_6":   {"ata_deg": 30, "aa_deg": 150, "distance_ft":  4000,
                          "closure_rate_kts":  80, "energy_diff_ft":  +800,
                          "alt_gap_ft":-300, "relative_bearing_deg": 20,
                          "ego_altitude_ft": 15500, "ego_vc_kts": 420,
                          "turn_rate_degs": 4, "overshoot_risk": False, "in_39_line": True},
    "energy_deficit":   {"ata_deg": 60, "aa_deg": 120, "distance_ft":  5000,
                          "closure_rate_kts": -50, "energy_diff_ft": -3500,
                          "alt_gap_ft": 1500, "relative_bearing_deg": 40,
                          "ego_altitude_ft": 13000, "ego_vc_kts": 320,
                          "turn_rate_degs": 3, "overshoot_risk": False, "in_39_line": False},
    "alt_advantage":    {"ata_deg": 20, "aa_deg": 160, "distance_ft":  3500,
                          "closure_rate_kts":  40, "energy_diff_ft": +3500,
                          "alt_gap_ft":-3000, "relative_bearing_deg": 15,
                          "ego_altitude_ft": 22000, "ego_vc_kts": 450,
                          "turn_rate_degs": 3, "overshoot_risk": False, "in_39_line": True},
    "wide_turn":        {"ata_deg": 75, "aa_deg": 105, "distance_ft":  4500,
                          "closure_rate_kts":  20, "energy_diff_ft":   500,
                          "alt_gap_ft":  100, "relative_bearing_deg": 60,
                          "ego_altitude_ft": 15500, "ego_vc_kts": 410,
                          "turn_rate_degs": 6, "overshoot_risk": False, "in_39_line": True},
    "far_extension":    {"ata_deg": 45, "aa_deg": 135, "distance_ft": 14000,
                          "closure_rate_kts":  60, "energy_diff_ft":  +200,
                          "alt_gap_ft":  200, "relative_bearing_deg": 25,
                          "ego_altitude_ft": 16000, "ego_vc_kts": 380,
                          "turn_rate_degs": 1, "overshoot_risk": False, "in_39_line": True},
    "low_alt_danger":   {"ata_deg": 30, "aa_deg": 150, "distance_ft":  2500,
                          "closure_rate_kts":  60, "energy_diff_ft":     0,
                          "alt_gap_ft":  300, "relative_bearing_deg": 20,
                          "ego_altitude_ft":  1200, "ego_vc_kts": 350,
                          "turn_rate_degs": 5, "overshoot_risk": False, "in_39_line": True},
}


# (orig_fn, smart_fn) pairs
PAIRS = [
    ("lead",      cbs.action_lead_pursuit,      cbs.action_smart_lead),
    ("lag",       cbs.action_lag_pursuit,       cbs.action_smart_lag),
    ("highyoyo",  cbs.action_high_yoyo,         cbs.action_smart_highyoyo),
    ("lowyoyo",   cbs.action_dive_attack,       cbs.action_smart_lowyoyo),
    ("breakturn", cbs.action_break_turn,        cbs.action_smart_breakturn),
    ("offensive", cbs.action_offensive_pursuit, cbs.action_smart_purepursuit),
]


def main():
    print(f"{'='*100}")
    print(f"BFM 동작 비교 — 원본 vs Smart* — {len(SCENARIOS)} scenarios × {len(PAIRS)} pairs")
    print(f"{'='*100}\n")

    from collections import deque
    summary = {}

    for name, obs in SCENARIOS.items():
        print(f"━━━ scenario: {name} ━━━")
        print(f"  obs: ata={obs['ata_deg']} aa={obs['aa_deg']} dist={obs['distance_ft']} "
              f"cl={obs['closure_rate_kts']} ed={obs['energy_diff_ft']} ag={obs['alt_gap_ft']}")
        # 우리 obs_current global 설정 + features 계산
        cbs.obs_current = obs
        hist = deque(maxlen=5)
        hist.append(obs)
        hist.append(obs)
        f = cbs.compute_features(obs, hist)

        diff_count = {}
        for pair_name, orig_fn, smart_fn in PAIRS:
            try:
                o_bin = orig_fn(f)
            except Exception as e:
                o_bin = f"ERR({e})"
            try:
                s_bin = smart_fn(f)
            except Exception as e:
                s_bin = f"ERR({e})"
            diff = "≠" if o_bin != s_bin else "="
            print(f"  {pair_name:>10s}: orig {o_bin} | smart {s_bin}  {diff}")
            if o_bin != s_bin:
                diff_count[pair_name] = (o_bin, s_bin)
        summary[name] = diff_count
        print()

    # 종합
    print(f"\n{'='*100}")
    print("SUMMARY — pair 별 다른 scenarios 수")
    print(f"{'='*100}")
    pair_diff_counts = {p[0]: 0 for p in PAIRS}
    for name, diffs in summary.items():
        for pn in diffs:
            pair_diff_counts[pn] += 1
    for pn, cnt in pair_diff_counts.items():
        print(f"  {pn:>10s}: {cnt}/{len(SCENARIOS)} scenarios 다름")

    out = ROOT / "logs/compare_bfm_actions.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(
        {"scenarios": {n: {k: list(v) for k, v in d.items()} for n, d in summary.items()},
         "pair_diff_counts": pair_diff_counts},
        indent=2, ensure_ascii=False))
    print(f"\nSaved: {out}")


if __name__ == "__main__":
    main()
