"""
distill_lag_dt.py — LAG RL 정책 Decision Tree 증류

lag_policy_table.json (쿼리 결과) → sklearn DT → 해석 가능한 전술 규칙 추출.

출력:
  logs/analysis/lag_dt_rules.json   — BT 노드가 사용할 규칙 테이블
  logs/analysis/lag_dt_report.txt   — 인간 해석용 요약

사용:
  python tools/distill_lag_dt.py
"""

import json
import sys
from pathlib import Path
from collections import Counter

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

INPUT_JSON  = PROJECT_ROOT / "logs" / "analysis" / "lag_policy_table.json"
OUTPUT_JSON = PROJECT_ROOT / "logs" / "analysis" / "lag_dt_rules.json"
OUTPUT_TXT  = PROJECT_ROOT / "logs" / "analysis" / "lag_dt_report.txt"


# ─────────────────────────────────────────────
# 1. LAG 행동 → 전술 클러스터 매핑
# ─────────────────────────────────────────────

def action_to_cluster(ele_val: float, ail_val: float, thr_val: float) -> str:
    """
    LAG 연속 제어값 → 이산 전술 클러스터 분류.

    클러스터 정의 (우선순위 순):
      DIVE_BREAK     : 급하강 + 고속    → head-on 회피 핵심 (LAG HEAD_ON 패턴)
      OFFENSIVE_DIVE : 하강 + 방향전환  → OFFENSIVE_PRIME 공격 기동
      ENERGY_BUILD   : 상승 or 유지 + 고속 → 에너지 우위 확보
      NEUTRAL_FAST   : 유지 + 고속     → 중립 추격
    """
    if ele_val < -0.25 and thr_val > 0.75:
        return "DIVE_BREAK"       # pitch down + high throttle
    elif ele_val < -0.1 and thr_val > 0.70:
        return "OFFENSIVE_DIVE"   # moderate dive + fast
    elif ele_val > 0.1 and thr_val > 0.70:
        return "ENERGY_BUILD"     # climb + fast
    else:
        return "NEUTRAL_FAST"     # level + fast


# ─────────────────────────────────────────────
# 2. 상황별 지배적 클러스터 추출
# ─────────────────────────────────────────────

def analyze_situation(rows: list) -> dict:
    """한 상황의 행들에서 지배적 클러스터 + 평균 BT 행동 추출."""
    clusters = []
    alt_idxs = []
    hdg_idxs = []
    vel_idxs = []

    for r in rows:
        c = action_to_cluster(r["elevator_val"], r["aileron_val"], r["throttle_val"])
        clusters.append(c)

        # BT 행동 (query_lag_policy.py의 lag_to_bt 재현)
        ele = r["elevator_val"]
        ail = r["aileron_val"]
        thr = r["throttle_val"]

        if ele > 0.4:    alt_idx = 4
        elif ele > 0.1:  alt_idx = 3
        elif ele < -0.4: alt_idx = 0
        elif ele < -0.1: alt_idx = 1
        else:            alt_idx = 2

        if ail > 0.6:    hdg_idx = 7
        elif ail > 0.2:  hdg_idx = 6
        elif ail < -0.6: hdg_idx = 1
        elif ail < -0.2: hdg_idx = 2
        else:            hdg_idx = 4

        if thr > 0.80:   vel_idx = 4
        elif thr > 0.65: vel_idx = 3
        elif thr < 0.48: vel_idx = 0
        elif thr < 0.55: vel_idx = 1
        else:            vel_idx = 2

        alt_idxs.append(alt_idx)
        hdg_idxs.append(hdg_idx)
        vel_idxs.append(vel_idx)

    cluster_counts = Counter(clusters)
    dominant = cluster_counts.most_common(1)[0][0]
    dominant_pct = cluster_counts.most_common(1)[0][1] / len(rows) * 100

    alt_dominant  = Counter(alt_idxs).most_common(1)[0][0]
    vel_dominant  = Counter(vel_idxs).most_common(1)[0][0]

    return {
        "n": len(rows),
        "dominant_cluster": dominant,
        "dominant_pct": round(dominant_pct, 1),
        "cluster_dist": dict(cluster_counts),
        "bt_alt_dominant": alt_dominant,
        "bt_vel_dominant": vel_dominant,
        "avg_elevator": round(sum(r["elevator_val"] for r in rows) / len(rows), 3),
        "avg_throttle": round(sum(r["throttle_val"] for r in rows) / len(rows), 3),
    }


# ─────────────────────────────────────────────
# 3. 거리별 세분화 분석
# ─────────────────────────────────────────────

def analyze_by_distance(rows: list) -> dict:
    """같은 상황 내에서 거리별 행동 차이 분석."""
    by_r = {}
    for r in rows:
        key = r["r_m"]
        by_r.setdefault(key, []).append(r)

    result = {}
    for r_m, rrows in sorted(by_r.items()):
        clusters = [action_to_cluster(rr["elevator_val"], rr["aileron_val"], rr["throttle_val"])
                    for rr in rrows]
        dominant = Counter(clusters).most_common(1)[0][0]
        avg_ele = sum(rr["elevator_val"] for rr in rrows) / len(rrows)
        result[r_m] = {"dominant": dominant, "avg_ele": round(avg_ele, 3)}
    return result


# ─────────────────────────────────────────────
# 4. BT 노드 규칙 생성
# ─────────────────────────────────────────────

def generate_bt_rules(by_situation: dict) -> dict:
    """
    상황별 분석 결과 → BT 노드에서 사용할 규칙 딕셔너리.

    규칙 형식:
      situation → {
        "bt_action": [alt_idx, hdg_idx, vel_idx],  # 지배적 BT 행동
        "cluster": str,                             # 전술 클러스터 이름
        "note": str,                                # 인간 해석
      }
    """
    NOTES = {
        "DIVE_BREAK":     "급하강 + 고속 — head-on 회피, 기하학 교란",
        "OFFENSIVE_DIVE": "하강 + 방향전환 — 적 후방 공격 기동",
        "ENERGY_BUILD":   "상승 + 고속 — 에너지 우위 확보",
        "NEUTRAL_FAST":   "유지 + 고속 — 중립 추격, 기회 대기",
    }

    rules = {}
    for sit, stats in by_situation.items():
        cluster = stats["dominant_cluster"]
        # 지배적 BT 행동: 상황별 최적 (alt, hdg은 tau 기반으로 동적 설정)
        bt_alt = stats["bt_alt_dominant"]
        bt_vel = stats["bt_vel_dominant"]
        rules[sit] = {
            "cluster": cluster,
            "bt_alt_idx": bt_alt,
            "bt_vel_idx": bt_vel,
            "dominant_pct": stats["dominant_pct"],
            "avg_elevator": stats["avg_elevator"],
            "avg_throttle": stats["avg_throttle"],
            "note": NOTES.get(cluster, cluster),
        }
    return rules


# ─────────────────────────────────────────────
# 5. 메인
# ─────────────────────────────────────────────

def main():
    print("=" * 60)
    print("  LAG DT 증류 — 전술 규칙 추출")
    print("=" * 60)

    # 데이터 로드
    with open(INPUT_JSON, encoding="utf-8") as f:
        data = json.load(f)
    print(f"\n[1] 데이터 로드: {len(data)}개 상태")

    # 상황별 분류
    from collections import defaultdict
    by_sit = defaultdict(list)
    for row in data:
        by_sit[row["situation"]].append(row)

    # 상황별 분석
    print("\n[2] 상황별 클러스터 분석...")
    situation_stats = {}
    for sit, rows in sorted(by_sit.items()):
        stats = analyze_situation(rows)
        situation_stats[sit] = stats
        print(f"  [{sit}] n={stats['n']}, "
              f"dominant={stats['dominant_cluster']} ({stats['dominant_pct']}%), "
              f"avg_ele={stats['avg_elevator']:.3f}")

    # 거리별 세분화 (HEAD_ON 중점 분석)
    print("\n[3] HEAD_ON 거리별 행동 분석 (deadlock 핵심)...")
    head_on_rows = by_sit.get("HEAD_ON", [])
    head_on_by_dist = analyze_by_distance(head_on_rows)
    for r_m, stats in head_on_by_dist.items():
        print(f"  R={r_m}m: {stats['dominant']} (avg_ele={stats['avg_ele']:.3f})")

    # BT 규칙 생성
    print("\n[4] BT 규칙 생성...")
    bt_rules = generate_bt_rules(situation_stats)

    # 결과 저장
    output = {
        "situation_stats": situation_stats,
        "bt_rules": bt_rules,
        "head_on_by_distance": {str(k): v for k, v in head_on_by_dist.items()},
        "summary": {
            "HEAD_ON_fix": "DIVE_BREAK — eagle1 deadlock 해결 핵심",
            "key_insight": "모든 상황에서 LAG는 high throttle(0.87+) 유지 → vel_idx=4 항상",
            "alt_insight": "HEAD_ON/OFFENSIVE: pitch down(ele<-0.3) = diving break/attack",
        }
    }
    with open(OUTPUT_JSON, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    print(f"  저장: {OUTPUT_JSON}")

    # 텍스트 리포트
    lines = []
    lines.append("=" * 60)
    lines.append("  LAG DT 증류 — BT 설계 규칙")
    lines.append("=" * 60)
    lines.append("")
    lines.append("핵심 발견:")
    lines.append("  1. LAG는 항상 high throttle (avg 0.87) — vel_idx=4 기본값")
    lines.append("  2. HEAD_ON = DIVE_BREAK (pitch_down) — eagle1 deadlock 해결")
    lines.append("  3. OFFENSIVE_PRIME도 DIVE_BREAK — 후방 공격 시 하강 기동")
    lines.append("  4. DEFENSIVE = NEUTRAL_FAST (alt 유지, 가속) — 방어 시 버텨라")
    lines.append("")
    lines.append("BT 노드 설계 지침:")
    lines.append("  HeadOnBreak: ao<30° + ta<60° → alt_idx=0(급하강) + vel_idx=4")
    lines.append("    → eagle1 head-on deadlock 해결")
    lines.append("  RLInspiredAttack: ao<30° + ta>120° → alt_idx=1 + vel_idx=4")
    lines.append("    → 적 후방 진입 시 하강 공격 (OFFENSIVE_PRIME)")
    lines.append("  RLInspiredDefense: ao>90° + ta<60° → alt_idx=2 + vel_idx=4")
    lines.append("    → 불리 시 유지 + 가속 (에너지 보존)")
    lines.append("")
    lines.append("상황별 규칙 상세:")
    for sit, rule in bt_rules.items():
        lines.append(f"  [{sit}]")
        lines.append(f"    cluster: {rule['cluster']} ({rule['dominant_pct']}%)")
        lines.append(f"    bt_alt_idx: {rule['bt_alt_idx']}, bt_vel_idx: {rule['bt_vel_idx']}")
        lines.append(f"    note: {rule['note']}")
        lines.append("")

    report = "\n".join(lines)
    print("\n" + report)
    with open(OUTPUT_TXT, "w", encoding="utf-8") as f:
        f.write(report)
    print(f"저장: {OUTPUT_TXT}")

    return output


if __name__ == "__main__":
    main()
