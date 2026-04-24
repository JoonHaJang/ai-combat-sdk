"""
v11 vs defensive/simple 선회 반경 분석

핵심 가설: PNLeadPursuit가 속도를 과도하게 유지 → 선회 반경이 커져 뒤를 잡지 못함.

분석 항목:
  1. ego vs enm 속도 비교 (ego_vc_kts)
  2. ego vs enm 선회율 비교 (turn_rate_degs)
  3. 파생 선회 반경: R = V_fps / ω_rad  (ft)
  4. 속도 명령 분포 (action_velocity)
  5. 활성 노드 분포 (active_node)
  6. ATA/거리 추이 (교착 탐지)
"""

import csv
import json
import math
import statistics
from pathlib import Path
from collections import defaultdict, Counter

KTS_TO_FPS = 1.6878
META_DIR = Path(__file__).parent.parent / "logs" / "metadata" / "v11_analysis"


def load_match(csv_path):
    """CSV → ego/enm 분리 로드."""
    rows_by_agent = defaultdict(list)
    first_agent = None
    with open(csv_path, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            aid = row.get("agent_id", "")
            if first_agent is None:
                first_agent = aid
            rows_by_agent[aid].append(row)
    
    agents = list(rows_by_agent.keys())
    if len(agents) < 2:
        return None, None
    ego_rows = rows_by_agent[first_agent]
    enm_rows = rows_by_agent[[a for a in agents if a != first_agent][0]]
    return ego_rows, enm_rows


def safe_float(v, default=0.0):
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def compute_turn_radius(v_kts, omega_dps):
    """선회 반경 계산: R = V / ω (ft)."""
    v_fps = v_kts * KTS_TO_FPS
    omega_rps = abs(omega_dps) * math.pi / 180
    if omega_rps < 0.01:  # 거의 직선
        return 99999.0
    return v_fps / omega_rps


def analyze_match(csv_path, label=""):
    ego_rows, enm_rows = load_match(csv_path)
    if not ego_rows or not enm_rows:
        print(f"  [SKIP] {csv_path.name}: 데이터 부족")
        return None

    n = min(len(ego_rows), len(enm_rows))
    
    ego_speeds = []
    enm_speeds = []
    ego_turn_rates = []
    enm_turn_rates = []
    ego_radii = []
    enm_radii = []
    ego_atas = []
    ego_dists = []
    vel_cmds = Counter()
    node_cmds = Counter()
    
    # 데미지 이벤트 탐지
    ego_hp_prev = 100.0
    enm_hp_prev = 100.0
    ego_hit_steps = []
    enm_hit_steps = []
    
    for i in range(n):
        er = ego_rows[i]
        nr = enm_rows[i]
        step = int(er.get("step", i))
        
        ev = safe_float(er.get("ego_vc_kts"), 350)
        nv = safe_float(nr.get("ego_vc_kts"), 350)
        etr = safe_float(er.get("turn_rate_degs"), 0)
        ntr = safe_float(nr.get("turn_rate_degs"), 0)
        
        ego_speeds.append(ev)
        enm_speeds.append(nv)
        ego_turn_rates.append(abs(etr))
        enm_turn_rates.append(abs(ntr))
        
        ego_radii.append(compute_turn_radius(ev, etr))
        enm_radii.append(compute_turn_radius(nv, ntr))
        
        ata = safe_float(er.get("ata_deg"), 90)
        if ata < 2:  # normalized 0-1
            ata *= 180
        ego_atas.append(ata)
        ego_dists.append(safe_float(er.get("distance_ft"), 5000))
        
        vel_cmd = er.get("action_velocity", "")
        if vel_cmd:
            vel_cmds[vel_cmd] += 1
        
        node = (er.get("active_node", "") or "").strip('"')
        if node:
            node_cmds[node] += 1
        
        # HP 추적
        ego_hp = safe_float(er.get("ego_health"), 100)
        enm_hp = safe_float(er.get("enm_health"), 100)
        if ego_hp < ego_hp_prev - 0.5:
            ego_hit_steps.append(step)
        if enm_hp < enm_hp_prev - 0.5:
            enm_hit_steps.append(step)
        ego_hp_prev = ego_hp
        enm_hp_prev = enm_hp
    
    # 선회 중인 구간만 필터 (turn_rate > 3 deg/s)
    turning_mask = [abs(ego_turn_rates[i]) > 3 or abs(enm_turn_rates[i]) > 3 
                    for i in range(n)]
    n_turning = sum(turning_mask)
    
    ego_turn_radii_filt = [ego_radii[i] for i in range(n) if turning_mask[i] and ego_radii[i] < 50000]
    enm_turn_radii_filt = [enm_radii[i] for i in range(n) if turning_mask[i] and enm_radii[i] < 50000]
    ego_speed_turning = [ego_speeds[i] for i in range(n) if turning_mask[i]]
    enm_speed_turning = [enm_speeds[i] for i in range(n) if turning_mask[i]]
    ego_tr_turning = [ego_turn_rates[i] for i in range(n) if turning_mask[i]]
    enm_tr_turning = [enm_turn_rates[i] for i in range(n) if turning_mask[i]]
    
    # ATA 교착 분석: 마지막 50% 구간에서 ATA 평균
    mid = n // 2
    ata_first_half = statistics.mean(ego_atas[:mid]) if mid > 0 else 0
    ata_second_half = statistics.mean(ego_atas[mid:]) if mid < n else 0
    
    # 결과 JSON 로드
    result_path = csv_path.with_name(csv_path.stem + "_result.json")
    result = {}
    if result_path.exists():
        with open(result_path, encoding="utf-8") as f:
            result = json.load(f)
    
    winner = result.get("winner", "?")
    t1_hp = result.get("tree1_health", result.get("tree1_hp", 100))
    t2_hp = result.get("tree2_health", result.get("tree2_hp", 100))
    
    print(f"\n{'='*65}")
    print(f"  {label} | {csv_path.name}")
    print(f"  결과: {winner} | HP: {t1_hp:.0f} vs {t2_hp:.0f} | {n} ticks")
    print(f"{'='*65}")
    
    print(f"\n  [1] 속도 비교 (선회 중, n={n_turning} ticks)")
    if ego_speed_turning:
        print(f"      ego 평균: {statistics.mean(ego_speed_turning):.0f} kts")
        print(f"      enm 평균: {statistics.mean(enm_speed_turning):.0f} kts")
        print(f"      차이:     {statistics.mean(ego_speed_turning) - statistics.mean(enm_speed_turning):+.0f} kts")
    
    print(f"\n  [2] 선회율 비교 (선회 중)")
    if ego_tr_turning:
        print(f"      ego 평균: {statistics.mean(ego_tr_turning):.1f} °/s")
        print(f"      enm 평균: {statistics.mean(enm_tr_turning):.1f} °/s")
        print(f"      차이:     {statistics.mean(ego_tr_turning) - statistics.mean(enm_tr_turning):+.1f} °/s")
    
    print(f"\n  [3] 선회 반경 비교 (핵심!)")
    if ego_turn_radii_filt:
        er_mean = statistics.mean(ego_turn_radii_filt)
        nr_mean = statistics.mean(enm_turn_radii_filt)
        print(f"      ego 평균: {er_mean:.0f} ft")
        print(f"      enm 평균: {nr_mean:.0f} ft")
        print(f"      비율:     ego/enm = {er_mean/max(nr_mean,1):.2f}x")
        if er_mean > nr_mean * 1.1:
            print(f"      ⚠️ ego 선회 반경이 {(er_mean/max(nr_mean,1)-1)*100:.0f}% 더 큼 → 뒤를 잡기 어려움")
    
    print(f"\n  [4] 속도 명령 분포 (action_velocity)")
    total_cmds = sum(vel_cmds.values())
    for vc, cnt in sorted(vel_cmds.items(), key=lambda x: -x[1]):
        pct = cnt / total_cmds * 100 if total_cmds else 0
        label_map = {"0": "급감속", "1": "감속", "2": "유지", "3": "가속", "4": "급가속"}
        print(f"      vel={vc} ({label_map.get(str(vc), '?')}): {cnt:4d} ({pct:5.1f}%)")
    
    print(f"\n  [5] 활성 노드 분포")
    total_nodes = sum(node_cmds.values())
    for nd, cnt in sorted(node_cmds.items(), key=lambda x: -x[1])[:8]:
        pct = cnt / total_nodes * 100 if total_nodes else 0
        print(f"      {nd:25s}: {cnt:4d} ({pct:5.1f}%)")
    
    print(f"\n  [6] ATA 교착 분석")
    print(f"      전반 ATA 평균: {ata_first_half:.1f}°")
    print(f"      후반 ATA 평균: {ata_second_half:.1f}°")
    if ata_second_half > ata_first_half + 5:
        print(f"      ⚠️ ATA 악화 ({ata_second_half - ata_first_half:+.1f}°) → 교착 심화")
    elif ata_second_half < ata_first_half - 10:
        print(f"      ✅ ATA 개선 ({ata_second_half - ata_first_half:+.1f}°)")
    else:
        print(f"      ─ ATA 변화 미미 → 교착 지속")
    
    print(f"\n  [7] 데미지 이벤트")
    print(f"      ego 피격: {len(ego_hit_steps)}회 (steps: {ego_hit_steps[:5]})")
    print(f"      enm 피격: {len(enm_hit_steps)}회 (steps: {enm_hit_steps[:5]})")
    
    return {
        "ego_speed_mean": statistics.mean(ego_speed_turning) if ego_speed_turning else 0,
        "enm_speed_mean": statistics.mean(enm_speed_turning) if enm_speed_turning else 0,
        "ego_radius_mean": statistics.mean(ego_turn_radii_filt) if ego_turn_radii_filt else 0,
        "enm_radius_mean": statistics.mean(enm_turn_radii_filt) if enm_turn_radii_filt else 0,
        "ego_tr_mean": statistics.mean(ego_tr_turning) if ego_tr_turning else 0,
        "enm_tr_mean": statistics.mean(enm_tr_turning) if enm_tr_turning else 0,
        "ata_first": ata_first_half,
        "ata_second": ata_second_half,
        "vel_cmds": dict(vel_cmds),
        "winner": winner,
    }


def main():
    print("\n" + "=" * 65)
    print("  v11 선회 반경 분석 — defensive & simple")
    print("=" * 65)
    
    all_results = {"defensive": [], "simple": [], "eagle1": [], "ace": []}
    
    for opponent in ["defensive", "simple", "eagle1", "ace"]:
        csvs = sorted(META_DIR.glob(f"*_vs_{opponent}*_meta.csv"))
        if not csvs:
            continue
        print(f"\n\n{'#'*65}")
        print(f"  vs {opponent.upper()} ({len(csvs)} 매치)")
        print(f"{'#'*65}")
        
        for csv_path in csvs:
            r = analyze_match(csv_path, label=f"vs {opponent}")
            if r:
                all_results[opponent].append(r)
    
    # 종합 비교
    print(f"\n\n{'='*65}")
    print(f"  종합 비교 (상대별 평균)")
    print(f"{'='*65}")
    print(f"\n  {'상대':12s} {'ego속도':>8s} {'enm속도':>8s} {'ego반경':>8s} {'enm반경':>8s} {'반경비':>6s} {'ATA후반':>8s}")
    print(f"  {'-'*62}")
    
    for opp, results in all_results.items():
        if not results:
            continue
        es = statistics.mean([r["ego_speed_mean"] for r in results])
        ns = statistics.mean([r["enm_speed_mean"] for r in results])
        er = statistics.mean([r["ego_radius_mean"] for r in results])
        nr = statistics.mean([r["enm_radius_mean"] for r in results])
        ata2 = statistics.mean([r["ata_second"] for r in results])
        ratio = er / max(nr, 1)
        print(f"  {opp:12s} {es:7.0f}kt {ns:7.0f}kt {er:7.0f}ft {nr:7.0f}ft {ratio:5.2f}x {ata2:7.1f}°")
    
    print()


if __name__ == "__main__":
    main()
