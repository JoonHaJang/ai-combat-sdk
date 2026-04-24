"""
v11 행동 분석 — 메타데이터 CSV에서 action 명령 비교

관측값은 ego 시점만 기록되므로 (로거 제약),
action_hdg/action_vel/active_node 비교 + 관측값 추이 분석에 집중.

핵심 질문:
  1. PNLeadPursuit가 속도 명령을 어떻게 내리는가? (vel 분포)
  2. defensive 상대가 어떤 속도로 선회하는가?
  3. v11의 ATA가 개선되지 않는 구간의 특징은?
  4. 교착 구간에서 어떤 노드가 발동되고, 무슨 heading/vel을 내는가?
"""

import csv
import json
import math
import statistics
from pathlib import Path
from collections import defaultdict, Counter

META_DIR = Path(__file__).parent.parent / "logs" / "metadata" / "v11_analysis"


def load_match_split(csv_path):
    """CSV → ego(tree1)/enm(tree2) 분리."""
    ego_rows, enm_rows = [], []
    with open(csv_path, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if row.get("tree_name", "").startswith("adaptive_eagle"):
                ego_rows.append(row)
            else:
                enm_rows.append(row)
    return ego_rows, enm_rows


def sf(v, default=0.0):
    try:
        return float(v)
    except:
        return default


def analyze_match(csv_path, label=""):
    ego, enm = load_match_split(csv_path)
    if not ego or not enm:
        print(f"  [SKIP] {csv_path.name}")
        return

    # 결과
    result_path = csv_path.with_name(csv_path.stem + "_result.json")
    result = json.load(open(result_path, encoding="utf-8")) if result_path.exists() else {}
    winner = result.get("winner", "?")
    t1_hp = result.get("tree1_health", result.get("tree1_hp", 100))
    t2_hp = result.get("tree2_health", result.get("tree2_hp", 100))

    print(f"\n{'='*70}")
    print(f"  {label} | {winner} | HP {t1_hp:.0f} vs {t2_hp:.0f} | {len(ego)} ticks")
    print(f"{'='*70}")

    # ─── 1. ego/enm 속도 명령 비교 ───
    vel_map = {0: "급감속", 1: "감속", 2: "유지", 3: "가속", 4: "급가속"}
    
    print(f"\n  [1] 속도 명령 비교 (action_vel)")
    for name, rows in [("ego(v11)", ego), ("enm", enm)]:
        vel_cnt = Counter(int(r.get("action_vel", 2)) for r in rows)
        total = sum(vel_cnt.values())
        parts = []
        for v in range(5):
            c = vel_cnt.get(v, 0)
            pct = c / total * 100 if total else 0
            parts.append(f"v{v}({vel_map[v]}):{c}({pct:.0f}%)")
        print(f"      {name:10s}: {' | '.join(parts)}")

    # ─── 2. heading 명령 비교 ───
    print(f"\n  [2] 조향 명령 비교 (action_hdg)")
    for name, rows in [("ego(v11)", ego), ("enm", enm)]:
        hdg_cnt = Counter(int(r.get("action_hdg", 4)) for r in rows)
        total = sum(hdg_cnt.values())
        # 급좌(0-1), 좌(2-3), 직진(4), 우(5-6), 급우(7-8)
        hard_left = sum(hdg_cnt.get(h, 0) for h in [0, 1])
        left = sum(hdg_cnt.get(h, 0) for h in [2, 3])
        straight = hdg_cnt.get(4, 0)
        right = sum(hdg_cnt.get(h, 0) for h in [5, 6])
        hard_right = sum(hdg_cnt.get(h, 0) for h in [7, 8])
        print(f"      {name:10s}: 급좌={hard_left}({hard_left/total*100:.0f}%) "
              f"좌={left}({left/total*100:.0f}%) "
              f"직진={straight}({straight/total*100:.0f}%) "
              f"우={right}({right/total*100:.0f}%) "
              f"급우={hard_right}({hard_right/total*100:.0f}%)")

    # ─── 3. 노드별 속도 명령 ───
    print(f"\n  [3] 노드별 속도 명령 (ego)")
    node_vel = defaultdict(Counter)
    for r in ego:
        node = (r.get("active_node", "") or "").strip('"')
        vel = int(r.get("action_vel", 2))
        node_vel[node][vel] += 1
    
    for node, vc in sorted(node_vel.items(), key=lambda x: -sum(x[1].values()))[:8]:
        total = sum(vc.values())
        parts = [f"v{v}:{vc.get(v,0)}" for v in range(5)]
        avg_vel = sum(v * c for v, c in vc.items()) / total if total else 0
        print(f"      {node:25s} n={total:4d}  avg_vel={avg_vel:.1f}  {' '.join(parts)}")

    # ─── 4. 시간대별 관측값 추이 (교착 분석) ───
    print(f"\n  [4] 시간대별 추이 (200-tick 구간)")
    n = len(ego)
    chunk = 200
    for start in range(0, n, chunk):
        end = min(start + chunk, n)
        sl = ego[start:end]
        ata_avg = statistics.mean(sf(r["ata_deg"]) for r in sl)
        dist_avg = statistics.mean(sf(r["distance_ft"]) for r in sl)
        clos_avg = statistics.mean(sf(r["closure_rate_kts"]) for r in sl)
        vel_avg = statistics.mean(int(r.get("action_vel", 2)) for r in sl)
        node_top = Counter((r.get("active_node","") or "").strip('"') for r in sl).most_common(1)[0]
        print(f"      [{start:4d}-{end:4d}] ATA={ata_avg:5.1f}° dist={dist_avg:5.0f}ft "
              f"clos={clos_avg:+5.0f}kt vel_cmd={vel_avg:.1f} "
              f"top_node={node_top[0]}({node_top[1]})")

    # ─── 5. PNLeadPursuit 구간 상세 ───
    pn_rows = [r for r in ego if "PNLeadPursuit" in (r.get("active_node","") or "")]
    if pn_rows:
        print(f"\n  [5] PNLeadPursuit 활성 구간 (n={len(pn_rows)})")
        pn_ata = [sf(r["ata_deg"]) for r in pn_rows]
        pn_dist = [sf(r["distance_ft"]) for r in pn_rows]
        pn_clos = [sf(r["closure_rate_kts"]) for r in pn_rows]
        pn_vel = [int(r.get("action_vel", 2)) for r in pn_rows]
        pn_hdg = [int(r.get("action_hdg", 4)) for r in pn_rows]
        
        print(f"      ATA:  avg={statistics.mean(pn_ata):.1f}° "
              f"min={min(pn_ata):.1f}° max={max(pn_ata):.1f}°")
        print(f"      dist: avg={statistics.mean(pn_dist):.0f}ft "
              f"min={min(pn_dist):.0f}ft max={max(pn_dist):.0f}ft")
        print(f"      clos: avg={statistics.mean(pn_clos):.0f}kt")
        print(f"      vel_cmd: avg={statistics.mean(pn_vel):.1f} "
              f"분포={Counter(pn_vel).most_common()}")
        print(f"      hdg_cmd: avg={statistics.mean(pn_hdg):.1f} "
              f"분포={Counter(pn_hdg).most_common()}")
        
        # ATA 추이 (전반/후반)
        mid = len(pn_rows) // 2
        if mid > 0:
            ata1 = statistics.mean(sf(r["ata_deg"]) for r in pn_rows[:mid])
            ata2 = statistics.mean(sf(r["ata_deg"]) for r in pn_rows[mid:])
            print(f"      ATA 추이: 전반={ata1:.1f}° → 후반={ata2:.1f}° (Δ={ata2-ata1:+.1f}°)")

    # ─── 6. 교착 탐지: ATA>80° + dist>3000ft + 50tick 이상 지속 ───
    stale_count = 0
    stale_start = None
    stale_segments = []
    for i, r in enumerate(ego):
        ata = sf(r["ata_deg"])
        dist = sf(r["distance_ft"])
        if ata > 80 and dist > 3000:
            if stale_start is None:
                stale_start = i
            stale_count += 1
        else:
            if stale_count >= 50:
                stale_segments.append((stale_start, i, stale_count))
            stale_count = 0
            stale_start = None
    if stale_count >= 50:
        stale_segments.append((stale_start, len(ego), stale_count))

    print(f"\n  [6] 교착 구간 (ATA>80° & dist>3000ft, 50tick+)")
    if stale_segments:
        for s, e, cnt in stale_segments:
            sl = ego[s:e]
            nodes = Counter((r.get("active_node","") or "").strip('"') for r in sl)
            vels = Counter(int(r.get("action_vel", 2)) for r in sl)
            print(f"      [{s}-{e}] {cnt} ticks | "
                  f"nodes: {nodes.most_common(3)} | "
                  f"vel_cmds: {dict(vels)}")
    else:
        print(f"      없음")


def main():
    for opponent in ["defensive", "simple", "eagle1", "ace"]:
        csvs = sorted(META_DIR.glob(f"*_vs_{opponent}*_meta.csv"))
        if not csvs:
            continue
        print(f"\n{'#'*70}")
        print(f"  vs {opponent.upper()} ({len(csvs)} 매치)")
        print(f"{'#'*70}")
        for csv_path in csvs[:2]:  # 상대당 2매치만 (출력 축소)
            analyze_match(csv_path, label=f"vs {opponent}")


if __name__ == "__main__":
    main()
