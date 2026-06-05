"""Post-match analysis tool (2026-05-26).

목적: metadata CSV + .acmi 분석 → MPC vs hybrid 매치 동역학 *정확 진단*.

design: graph 참조 결과 — 이미 metadata_logger (tools/metadata_logger.py) 가
풍부한 step-by-step 로그 제공:
  - 기하 (distance, ata, aa, hca, rel_bearing)
  - 에너지 (Es, Ps, energy_diff, V)
  - 전술 (in_wez, energy_advantage, alt_advantage, ...)
  - 행동 (action_alt/hdg/vel, aileron/elev/rudder/throttle)
  - 결과 (health, damage_dealt, reward)
  - BT (active_node, bfm_situation)

analyze:
  1. 두 매치 CSV 비교 (hybrid vs MPC)
  2. *시점별* 차이 추적 — 언제 어디서 갈라지는가
  3. ATA/dist 분포 — WEZ entry 빈도
  4. action distribution — bin 선택 패턴
  5. damage timing — 누가 언제 hit 했나
  6. 결정적 차이 정량화 → 다음 fix 정확 도출

usage:
    python tools/analyze_match.py --hybrid logs/hybrid_meta.csv --mpc logs/mpc_meta.csv
"""

from __future__ import annotations

import argparse
import csv
from collections import Counter, defaultdict
from pathlib import Path
from typing import List, Dict


def load_csv(path: Path) -> List[Dict]:
    """metadata CSV → list of dicts."""
    rows = []
    with open(path, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            # numeric conversion
            for k, v in row.items():
                if k in ('step', 'agent_id'):
                    try: row[k] = int(v)
                    except: pass
                elif k in ('action_alt', 'action_hdg', 'action_vel'):
                    try: row[k] = int(float(v)) if v else -1
                    except: pass
                else:
                    try: row[k] = float(v)
                    except: pass
            rows.append(row)
    return rows


def split_by_agent(rows: List[Dict]) -> Dict[str, List[Dict]]:
    """rows → {agent_name: [rows]}."""
    by_agent = defaultdict(list)
    for r in rows:
        name = r.get('tree_name', str(r.get('agent_id', '?')))
        by_agent[name].append(r)
    return dict(by_agent)


def summarize_agent(rows: List[Dict], name: str) -> Dict:
    """단일 agent 의 매치 동역학 요약."""
    if not rows:
        return {}

    n = len(rows)
    # 기하 통계
    dist_vals = [r.get('distance_ft', 0) for r in rows if isinstance(r.get('distance_ft'), (int, float))]
    ata_vals = [r.get('ata_deg', 0) for r in rows if isinstance(r.get('ata_deg'), (int, float))]
    aa_vals = [r.get('aa_deg', 0) for r in rows if isinstance(r.get('aa_deg'), (int, float))]
    closure_vals = [r.get('closure_rate_kts', 0) for r in rows if isinstance(r.get('closure_rate_kts'), (int, float))]
    es_vals = [r.get('specific_energy_ft', 0) for r in rows if isinstance(r.get('specific_energy_ft'), (int, float))]
    h_vals = [r.get('ego_altitude_ft', 0) for r in rows if isinstance(r.get('ego_altitude_ft'), (int, float))]
    v_vals = [r.get('ego_vc_kts', 0) for r in rows if isinstance(r.get('ego_vc_kts'), (int, float))]

    # WEZ entries: ATA<12 AND 500<dist<3000
    wez_steps = sum(1 for r in rows
                     if r.get('ata_deg', 999) < 12.0
                     and 500 < r.get('distance_ft', 0) < 3000)
    # 피해진입 (enm in WEZ)
    threat_steps = sum(1 for r in rows
                        if r.get('aa_deg', 999) < 12.0
                        and 500 < r.get('distance_ft', 0) < 3000)
    # action bin 분포
    alt_dist = Counter(r.get('action_alt') for r in rows)
    hdg_dist = Counter(r.get('action_hdg') for r in rows)
    vel_dist = Counter(r.get('action_vel') for r in rows)
    # BT branch 분포
    bfm_dist = Counter(r.get('bfm_situation', '') for r in rows)
    node_dist = Counter(r.get('active_node', '') for r in rows)

    def stat(vals):
        if not vals: return (0, 0, 0, 0)
        sorted_v = sorted(vals)
        return (
            min(vals), max(vals),
            sum(vals)/len(vals),
            sorted_v[len(vals)//2],   # median
        )

    return {
        "name": name,
        "n_steps": n,
        "dist (min/max/mean/med)": stat(dist_vals),
        "ata  (min/max/mean/med)": stat(ata_vals),
        "aa   (min/max/mean/med)": stat(aa_vals),
        "closure (min/max/mean)":  stat(closure_vals),
        "Es   (min/max/mean)":     stat(es_vals),
        "h_ft (min/max/mean)":     stat(h_vals),
        "V_kts (min/max/mean)":    stat(v_vals),
        "WEZ steps (we attack)":   wez_steps,
        "Threat steps (we under)": threat_steps,
        "alt_bin dist":            dict(alt_dist),
        "hdg_bin dist":            dict(hdg_dist),
        "vel_bin dist":            dict(vel_dist),
        "bfm_situation dist":      dict(bfm_dist),
        "top 5 active_node":       node_dist.most_common(5),
    }


def compare_summaries(hybrid: Dict, mpc: Dict) -> None:
    """두 agent 요약 side-by-side 출력."""
    print("\n" + "=" * 84)
    print(f"{'Field':<35} {'hybrid':<22} {'MPC':<22}")
    print("=" * 84)
    keys = sorted(set(hybrid.keys()) | set(mpc.keys()))
    for k in keys:
        h_val = hybrid.get(k, "—")
        m_val = mpc.get(k, "—")

        def fmt(v):
            if isinstance(v, tuple):
                return f"({v[0]:.0f}/{v[1]:.0f}/{v[2]:.0f})" if len(v) >= 3 else str(v)
            if isinstance(v, dict):
                if len(v) <= 5:
                    return ", ".join(f"{k}:{val}" for k, val in sorted(v.items()))
                else:
                    top = sorted(v.items(), key=lambda x:-x[1])[:3]
                    return ", ".join(f"{k}:{val}" for k, val in top) + "..."
            if isinstance(v, list):
                return str(v[:3])
            return str(v)
        print(f"{k:<35} {fmt(h_val):<22} {fmt(m_val):<22}")


def find_first_divergence(rows_a: List[Dict], rows_b: List[Dict], threshold: float = 5.0) -> Dict:
    """두 매치의 *처음* 큰 차이 시점 찾기 (같은 IC 가정)."""
    diverge = {}
    for i, (r_a, r_b) in enumerate(zip(rows_a, rows_b)):
        d_dist = abs(r_a.get('distance_ft', 0) - r_b.get('distance_ft', 0))
        d_ata = abs(r_a.get('ata_deg', 0) - r_b.get('ata_deg', 0))
        d_h = abs(r_a.get('ego_altitude_ft', 0) - r_b.get('ego_altitude_ft', 0))
        if d_dist > 500 or d_ata > 20 or d_h > 500:
            diverge = {
                "step": r_a.get('step', i),
                "d_dist": d_dist,
                "d_ata": d_ata,
                "d_h": d_h,
                "a_state": f"dist={r_a.get('distance_ft'):.0f} ata={r_a.get('ata_deg'):.0f} h={r_a.get('ego_altitude_ft'):.0f}",
                "b_state": f"dist={r_b.get('distance_ft'):.0f} ata={r_b.get('ata_deg'):.0f} h={r_b.get('ego_altitude_ft'):.0f}",
                "a_action": (r_a.get('action_alt'), r_a.get('action_hdg'), r_a.get('action_vel')),
                "b_action": (r_b.get('action_alt'), r_b.get('action_hdg'), r_b.get('action_vel')),
            }
            return diverge
    return {}


def find_damage_events(rows: List[Dict]) -> List[Dict]:
    """damage 발생 step 추출."""
    events = []
    prev_dealt = 0
    for r in rows:
        dealt = r.get('ego_damage_dealt', 0)
        if dealt is None or not isinstance(dealt, (int, float)):
            continue
        if dealt > prev_dealt + 0.01:
            events.append({
                "step": r.get('step'),
                "ata": r.get('ata_deg'),
                "dist": r.get('distance_ft'),
                "alt": r.get('ego_altitude_ft'),
                "damage_increment": dealt - prev_dealt,
                "cumulative": dealt,
            })
            prev_dealt = dealt
    return events


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", type=Path, required=True, help="metadata CSV")
    ap.add_argument("--compare-to", type=Path, help="다른 CSV 와 비교")
    ap.add_argument("--us", default="pursuit_chase_v1", help="our agent name")
    args = ap.parse_args()

    rows = load_csv(args.csv)
    print(f"[loaded] {args.csv.name}: {len(rows)} rows")
    by_agent = split_by_agent(rows)
    print(f"agents: {list(by_agent.keys())}")

    our_rows = by_agent.get(args.us, rows[:len(rows)//2])

    # 1. summary
    print()
    print("=" * 84)
    print(f"SUMMARY: {args.us}")
    print("=" * 84)
    summ = summarize_agent(our_rows, args.us)
    for k, v in summ.items():
        if isinstance(v, dict):
            top = sorted(v.items(), key=lambda x:-x[1])[:8] if v else []
            print(f"  {k}:")
            for kk, vv in top:
                print(f"     {kk}: {vv}")
        elif isinstance(v, list):
            print(f"  {k}: {v[:5]}")
        else:
            print(f"  {k}: {v}")

    # 2. damage events
    print()
    print(f"DAMAGE EVENTS ({args.us} 가 적에게 가한 damage):")
    events = find_damage_events(our_rows)
    if not events:
        print("  ⚠️ NO DAMAGE EVENTS — 매치 동안 한 번도 데미지 못 가함")
    else:
        for ev in events[:20]:
            print(f"  step={ev['step']:>5}: ATA={ev['ata']:.1f}° dist={ev['dist']:.0f}ft +{ev['damage_increment']:.2f}HP (cum={ev['cumulative']:.2f})")

    # 3. comparison
    if args.compare_to:
        rows2 = load_csv(args.compare_to)
        by_agent2 = split_by_agent(rows2)
        our2 = by_agent2.get(args.us, rows2[:len(rows2)//2])
        print()
        print("=" * 84)
        print(f"COMPARISON: {args.csv.name} vs {args.compare_to.name}")
        print("=" * 84)
        summ2 = summarize_agent(our2, args.us + " (B)")
        compare_summaries(summ, summ2)

        # divergence
        div = find_first_divergence(our_rows, our2)
        if div:
            print(f"\nFIRST DIVERGENCE: step {div['step']}")
            print(f"  Δdist={div['d_dist']:.0f}ft  Δata={div['d_ata']:.0f}°  Δh={div['d_h']:.0f}ft")
            print(f"  A state: {div['a_state']}, action={div['a_action']}")
            print(f"  B state: {div['b_state']}, action={div['b_action']}")

        # B damage
        events2 = find_damage_events(our2)
        print(f"\nB damage events: {len(events2)} (vs A: {len(events)})")


if __name__ == "__main__":
    main()
