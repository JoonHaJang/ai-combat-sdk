"""
Phase 1 메타데이터 분석기

목적: CSV 메타데이터를 정량적으로 분석하여 Phase 2 커스텀 노드 설계의
      객관적 근거를 생성. 주관적 해석 배제, 공식 기반 평가.

분석 모듈:
  [1] State-Action Effectiveness (SAE)
      - 각 (BFM상태, Action) 조합에 대해 N스텝 후 상태 개선도 측정
      - 개선도 = Δ(ATA감소) + Δ(거리접근) + Δ(HP차이) — 정량 공식

  [2] Transition Induction Rate (TIR)
      - 각 Action이 유리한 BFM 전이(→OBFM)를 유도하는 확률

  [3] WEZ Precursor Pattern (WPP)
      - WEZ 진입 직전 K스텝의 상태-행동 시퀀스 추출

  [4] Win Contribution Score (WCS)
      - 승리 매치 vs 패배 매치에서의 Action 사용률 차이

  [5] Enemy Intent Profile (EIP) ← Phase 1 핵심 목표
      - 상대별 (상태 → 행동) 조건부 확률
      - "ace는 ATA<30°일 때 78%로 LeadPursuit"
      - Phase 2 조건 노드 `EnemyPursuing` 등의 threshold 근거

  [6] Enemy Vulnerability Window (EVW)
      - 상대별 시간대별 취약 구간 (고도 하락, 에너지 열세 패턴)
      - "aggressive는 스텝 200-400에서 고도가 낮아지는 경향"

출력:
  logs/analysis/state_action_effectiveness.json
  logs/analysis/transition_rates.json
  logs/analysis/wez_precursors.json
  logs/analysis/win_contribution.json
  logs/analysis/enemy_intent_profiles.json
  logs/analysis/enemy_vulnerability.json
  logs/analysis/summary_report.txt

Usage:
  python tools/analyze_metadata.py
  python tools/analyze_metadata.py --meta-dir logs/metadata --lookahead 10
"""

import sys
import csv
import json
import argparse
from pathlib import Path
from collections import defaultdict, Counter
from datetime import datetime

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# ============================================================
# Constants
# ============================================================

BFM_STATES = ["OBFM", "DBFM", "HABFM", "UNKNOWN"]

# UNKNOWN 하위 분류 (Phase 1 분석 결과 기반)
def classify_unknown_sub(ata_deg, closure_kts):
    """UNKNOWN BFM을 3개 하위 상태로 세분화."""
    if ata_deg < 45:
        return "UNK_NEAR_OFF"     # 공격 직전
    elif ata_deg < 70 and closure_kts < 0:
        return "UNK_SCISSORS"     # 선회 교착
    else:
        return "UNK_DISENGAGING"  # 이탈 중

# BFM 우선순위 (높을수록 공격적으로 유리)
BFM_RANK = {"OBFM": 3, "UNKNOWN": 1, "HABFM": 0, "DBFM": -2,
            "UNK_NEAR_OFF": 2, "UNK_SCISSORS": 1, "UNK_DISENGAGING": 0}


# ============================================================
# Data Loading
# ============================================================

def load_metadata(meta_dir, max_files=None):
    """CSV + result JSON을 로드하여 매치별 데이터 구조로 반환."""
    meta_path = Path(meta_dir)
    csv_files = sorted(meta_path.glob("*_meta.csv"))
    if max_files:
        csv_files = csv_files[:max_files]

    # result JSON → 매치 결과 매핑 (csv stem → winner)
    match_results = {}
    for jp in meta_path.glob("*_result.json"):
        try:
            with open(jp, encoding='utf-8') as f:
                d = json.load(f)
            csv_stem = jp.stem.replace("_result", "")
            match_results[csv_stem] = d
        except Exception:
            pass

    matches = []
    for csv_path in csv_files:
        try:
            rows = list(csv.DictReader(open(csv_path, encoding='utf-8')))
            stem = csv_path.stem
            result = match_results.get(stem, {})
            matches.append({
                "file": csv_path.name,
                "rows": rows,
                "winner": result.get("winner", "unknown"),
                "tree1_agent": result.get("tree1_agent", ""),
                "tree2_agent": result.get("tree2_agent", ""),
                "tree1_hp": result.get("tree1_hp", 100),
                "tree2_hp": result.get("tree2_hp", 100),
            })
        except Exception:
            pass

    return matches


def safe_float(val, default=0.0):
    try:
        return float(val)
    except (ValueError, TypeError):
        return default


# ============================================================
# [1] State-Action Effectiveness (SAE)
# ============================================================

def compute_sae(matches, lookahead=10):
    """
    각 (BFM상태, Action) 조합의 효과성을 측정.

    효과성 공식 (N스텝 후 상태 변화):
      SAE = w1 * Δ(ATA감소율) + w2 * Δ(거리접근율) + w3 * Δ(HP차이)

    where:
      Δ(ATA감소율) = (ata_now - ata_future) / 180  → [-1, 1], 양수=개선
      Δ(거리접근율) = (dist_now - dist_future) / dist_now  → [-1, 1], 양수=접근
      Δ(HP차이) = (hp_diff_future - hp_diff_now) / 100  → [-1, 1], 양수=유리

    가중치: w1=0.4 (조준 개선), w2=0.3 (거리 단축), w3=0.3 (체력 우위)
    """
    W_ATA = 0.4
    W_DIST = 0.3
    W_HP = 0.3

    # (bfm_state, action) → [sae_scores]
    sae_table = defaultdict(list)

    for match in matches:
        rows = match["rows"]
        # agent별로 분리
        agents = defaultdict(list)
        for row in rows:
            agents[row.get("agent_id", "")].append(row)

        for agent_id, agent_rows in agents.items():
            for i in range(len(agent_rows) - lookahead):
                now = agent_rows[i]
                future = agent_rows[i + lookahead]

                bfm = now.get("bfm_situation", "")
                if bfm not in BFM_STATES:
                    continue

                action = now.get("active_node", "").strip('"')
                if not action:
                    continue

                # UNKNOWN 세분화
                if bfm == "UNKNOWN":
                    ata_now = safe_float(now.get("ata_deg"))
                    closure_now = safe_float(now.get("closure_rate_kts"))
                    bfm = classify_unknown_sub(ata_now, closure_now)

                # 현재 상태
                ata_now = safe_float(now.get("ata_deg"), 90)
                dist_now = safe_float(now.get("distance_ft"), 5000)
                hp_now = safe_float(now.get("ego_health"), 100)
                enm_hp_now = safe_float(now.get("enm_health"), 100)

                # N스텝 후 상태
                ata_fut = safe_float(future.get("ata_deg"), 90)
                dist_fut = safe_float(future.get("distance_ft"), 5000)
                hp_fut = safe_float(future.get("ego_health"), 100)
                enm_hp_fut = safe_float(future.get("enm_health"), 100)

                # SAE 계산
                delta_ata = (ata_now - ata_fut) / 180.0  # ATA 감소 = 양수 = 개선
                delta_dist = (dist_now - dist_fut) / max(dist_now, 1.0)  # 거리 감소 = 양수
                delta_hp = ((hp_fut - enm_hp_fut) - (hp_now - enm_hp_now)) / 100.0

                sae = W_ATA * delta_ata + W_DIST * delta_dist + W_HP * delta_hp
                sae_table[(bfm, action)].append(sae)

    # 집계: 평균 + 신뢰 구간
    results = {}
    for (bfm, action), scores in sae_table.items():
        n = len(scores)
        if n < 20:  # 최소 샘플 수
            continue
        mean = sum(scores) / n
        sorted_s = sorted(scores)
        p25 = sorted_s[n // 4]
        p75 = sorted_s[3 * n // 4]
        results[f"{bfm}|{action}"] = {
            "bfm": bfm, "action": action,
            "mean_sae": round(mean, 4),
            "p25": round(p25, 4), "p75": round(p75, 4),
            "n": n,
        }

    return results


# ============================================================
# [2] Transition Induction Rate (TIR)
# ============================================================

def compute_tir(matches, lookahead=10):
    """
    각 (BFM상태, Action) → N스텝 후 BFM 전이 확률.

    유리한 전이: → OBFM (공격 우위 확보)
    불리한 전이: → DBFM (방어 전환)

    TIR_favorable = P(future_bfm == OBFM | current_bfm, action)
    TIR_unfavorable = P(future_bfm == DBFM | current_bfm, action)
    """
    # (bfm, action) → {future_bfm: count}
    trans_table = defaultdict(Counter)

    for match in matches:
        rows = match["rows"]
        agents = defaultdict(list)
        for row in rows:
            agents[row.get("agent_id", "")].append(row)

        for agent_id, agent_rows in agents.items():
            for i in range(len(agent_rows) - lookahead):
                now = agent_rows[i]
                future = agent_rows[i + lookahead]

                bfm_now = now.get("bfm_situation", "")
                bfm_fut = future.get("bfm_situation", "")
                action = now.get("active_node", "").strip('"')

                if bfm_now not in BFM_STATES or not action:
                    continue

                if bfm_now == "UNKNOWN":
                    ata = safe_float(now.get("ata_deg"))
                    closure = safe_float(now.get("closure_rate_kts"))
                    bfm_now = classify_unknown_sub(ata, closure)

                trans_table[(bfm_now, action)][bfm_fut] += 1

    results = {}
    for (bfm, action), counter in trans_table.items():
        total = sum(counter.values())
        if total < 20:
            continue
        results[f"{bfm}|{action}"] = {
            "bfm": bfm, "action": action,
            "n": total,
            "tir_obfm": round(counter.get("OBFM", 0) / total, 4),
            "tir_dbfm": round(counter.get("DBFM", 0) / total, 4),
            "tir_habfm": round(counter.get("HABFM", 0) / total, 4),
            "tir_unknown": round(counter.get("UNKNOWN", 0) / total, 4),
            "tir_favorable": round(counter.get("OBFM", 0) / total, 4),
            "tir_unfavorable": round(counter.get("DBFM", 0) / total, 4),
        }

    return results


# ============================================================
# [3] WEZ Precursor Pattern (WPP)
# ============================================================

def compute_wpp(matches, lookback=10):
    """
    WEZ 진입 직전 K스텝의 공통 상태-행동 패턴 추출.

    WEZ 이벤트: in_wez == True 또는 enm_in_wez == True
    각 이벤트 직전 K스텝의:
      - BFM 시퀀스
      - Action 시퀀스
      - ATA/거리/closure 평균
    """
    precursors = {"in_wez": [], "enm_in_wez": []}

    for match in matches:
        rows = match["rows"]
        agents = defaultdict(list)
        for row in rows:
            agents[row.get("agent_id", "")].append(row)

        for agent_id, agent_rows in agents.items():
            for i in range(lookback, len(agent_rows)):
                row = agent_rows[i]

                for wez_field in ["in_wez", "enm_in_wez"]:
                    val = row.get(wez_field, "").strip()
                    prev_val = agent_rows[i-1].get(wez_field, "").strip() if i > 0 else "False"

                    # WEZ 진입 순간만 (False → True)
                    if val == "True" and prev_val != "True":
                        window = agent_rows[max(0, i - lookback):i]
                        if len(window) < lookback // 2:
                            continue

                        actions = [r.get("active_node", "").strip('"') for r in window]
                        bfms = [r.get("bfm_situation", "") for r in window]
                        avg_ata = sum(safe_float(r.get("ata_deg")) for r in window) / len(window)
                        avg_dist = sum(safe_float(r.get("distance_ft")) for r in window) / len(window)
                        avg_closure = sum(safe_float(r.get("closure_rate_kts")) for r in window) / len(window)

                        precursors[wez_field].append({
                            "actions": actions,
                            "bfms": bfms,
                            "avg_ata": round(avg_ata, 1),
                            "avg_dist": round(avg_dist, 0),
                            "avg_closure": round(avg_closure, 1),
                        })

    # 집계: 가장 빈번한 action 패턴
    summary = {}
    for wez_field, events in precursors.items():
        if not events:
            summary[wez_field] = {"count": 0}
            continue

        action_freq = Counter()
        bfm_freq = Counter()
        ata_vals, dist_vals, closure_vals = [], [], []

        for ev in events:
            for a in ev["actions"]:
                if a:
                    action_freq[a] += 1
            for b in ev["bfms"]:
                if b:
                    bfm_freq[b] += 1
            ata_vals.append(ev["avg_ata"])
            dist_vals.append(ev["avg_dist"])
            closure_vals.append(ev["avg_closure"])

        summary[wez_field] = {
            "count": len(events),
            "top_actions": dict(action_freq.most_common(5)),
            "top_bfms": dict(bfm_freq.most_common(5)),
            "avg_ata": round(sum(ata_vals) / len(ata_vals), 1) if ata_vals else 0,
            "avg_dist": round(sum(dist_vals) / len(dist_vals), 0) if dist_vals else 0,
            "avg_closure": round(sum(closure_vals) / len(closure_vals), 1) if closure_vals else 0,
        }

    return summary


# ============================================================
# [4] Win Contribution Score (WCS)
# ============================================================

def compute_wcs(matches):
    """
    승리 매치 vs 패배 매치에서 각 Action의 사용률 차이.

    WCS(action) = P(action | win) - P(action | loss)
    양수 = 승리와 양의 상관, 음수 = 패배와 양의 상관
    """
    win_actions = Counter()
    loss_actions = Counter()
    draw_actions = Counter()
    win_total = loss_total = draw_total = 0

    for match in matches:
        winner = match.get("winner", "")
        for row in match["rows"]:
            agent_id = row.get("agent_id", "")
            action = row.get("active_node", "").strip('"')
            if not action:
                continue

            # tree1 관점: tree1이면 agent A*, tree2이면 agent B*
            is_tree1 = str(agent_id).startswith("A")

            if (winner == "tree1" and is_tree1) or (winner == "tree2" and not is_tree1):
                win_actions[action] += 1
                win_total += 1
            elif winner == "draw":
                draw_actions[action] += 1
                draw_total += 1
            else:
                loss_actions[action] += 1
                loss_total += 1

    results = {}
    all_actions = set(win_actions) | set(loss_actions) | set(draw_actions)
    for action in all_actions:
        p_win = win_actions[action] / max(win_total, 1)
        p_loss = loss_actions[action] / max(loss_total, 1)
        wcs = p_win - p_loss
        results[action] = {
            "action": action,
            "wcs": round(wcs, 4),
            "p_win": round(p_win, 4),
            "p_loss": round(p_loss, 4),
            "p_draw": round(draw_actions[action] / max(draw_total, 1), 4),
            "n_win": win_actions[action],
            "n_loss": loss_actions[action],
        }

    return results


# ============================================================
# [5] Enemy Intent Profile (EIP) — Phase 1 핵심 목표
# ============================================================

def compute_eip(matches):
    """
    전체 적 풀의 (관측 상태 조합 → 행동) 조건부 확률.

    상대 불문 — 모든 적(B*)의 행동을 상태 조합별로 집계.
    "ATA<30° + dist<2000ft + OBFM 상태에서, 적은 78%로 LeadPursuit을 선택"
    → Phase 2 조건 노드의 threshold 및 적 intent 추정 근거.

    상태 축 (적 관점 관측값):
      - ata_bin: <30, 30-60, 60-90, >90
      - dist_bin: <2000, 2000-5000, >5000
      - bfm: OBFM, DBFM, HABFM, UNKNOWN
      - closure_bin: approaching(>0), separating(<=0)
      - energy_adv: True/False

    출력:
      "global": { "bfm|ata_bin|dist_bin" → {action: prob, ...}, ... }
      "marginal_ata": { "ata<30" → {action: prob}, ... }
      "marginal_bfm": { "OBFM" → {action: prob}, ... }
      "joint_bfm_ata": { "OBFM|ata<30" → {action: prob}, ... }
      "joint_full": { "OBFM|ata<30|dist<2k|approaching" → {action: prob}, ... }
    """
    # 여러 집계 레벨
    marginal_ata = defaultdict(Counter)
    marginal_bfm = defaultdict(Counter)
    marginal_dist = defaultdict(Counter)
    joint_bfm_ata = defaultdict(Counter)
    joint_bfm_ata_dist = defaultdict(Counter)
    joint_full = defaultdict(Counter)
    total_actions = Counter()

    for match in matches:
        for row in match["rows"]:
            agent_id = row.get("agent_id", "")
            # 적의 행동만 수집 (B* = tree2, A* 매치에서는 B가 상대)
            # 양방향 매치이므로 A가 상대인 경우도 있음 — 모든 rows 사용
            action = row.get("active_node", "").strip('"')
            if not action:
                continue

            # 관측값 추출 (이미 ×180 변환된 경우와 아닌 경우 모두 처리)
            ata_raw = safe_float(row.get("ata_deg"), 0.5)
            ata = ata_raw * 180.0 if ata_raw <= 1.0 else ata_raw
            dist = safe_float(row.get("distance_ft"), 5000)
            bfm = row.get("bfm_situation", "UNKNOWN")
            closure = safe_float(row.get("closure_rate_kts"), 0)
            energy_adv = row.get("energy_advantage", "").strip().lower() == "true"

            # 구간화
            if ata < 30:
                ata_bin = "ata<30"
            elif ata < 60:
                ata_bin = "ata30-60"
            elif ata < 90:
                ata_bin = "ata60-90"
            else:
                ata_bin = "ata>90"

            if dist < 2000:
                dist_bin = "dist<2k"
            elif dist < 5000:
                dist_bin = "dist2k-5k"
            else:
                dist_bin = "dist>5k"

            closure_bin = "approaching" if closure > 0 else "separating"

            # 모든 레벨 집계
            total_actions[action] += 1
            marginal_ata[ata_bin][action] += 1
            marginal_bfm[bfm][action] += 1
            marginal_dist[dist_bin][action] += 1
            joint_bfm_ata[f"{bfm}|{ata_bin}"][action] += 1
            joint_bfm_ata_dist[f"{bfm}|{ata_bin}|{dist_bin}"][action] += 1
            joint_full[f"{bfm}|{ata_bin}|{dist_bin}|{closure_bin}"][action] += 1

    def _to_probs(counter_dict, min_n=30):
        result = {}
        for key, counts in counter_dict.items():
            total = sum(counts.values())
            if total < min_n:
                continue
            probs = {a: round(c / total, 3) for a, c in counts.most_common(5)}
            result[key] = {"probs": probs, "n": total}
        return result

    return {
        "total_rows": sum(total_actions.values()),
        "total_actions": {a: c for a, c in total_actions.most_common()},
        "marginal_ata": _to_probs(marginal_ata),
        "marginal_bfm": _to_probs(marginal_bfm),
        "marginal_dist": _to_probs(marginal_dist),
        "joint_bfm_ata": _to_probs(joint_bfm_ata),
        "joint_bfm_ata_dist": _to_probs(joint_bfm_ata_dist, min_n=20),
        "joint_full": _to_probs(joint_full, min_n=20),
    }


# ============================================================
# [6] Enemy Vulnerability Window (EVW)
# ============================================================

def compute_evw(matches, window_size=100):
    """
    상대별 시간대별 취약 구간 분석.

    매치를 window_size 스텝 구간으로 나누어:
      - 적의 평균 고도, 속도, 에너지, HP 변화 추적
      - 구간별 적의 WEZ 노출(enm_in_wez) 빈도
      - 구간별 적 HP 감소율

    출력: 상대별 "시간 구간 → 취약도 지표"
    """
    # opponent_name → { window_idx → [metrics] }
    vuln_data = defaultdict(lambda: defaultdict(list))

    for match in matches:
        rows = match["rows"]
        tree2_name = match.get("tree2_agent", "")

        # 우리(A*) 관점에서 적의 취약성 측정
        our_rows = [r for r in rows if str(r.get("agent_id", "")).startswith("A")]

        for row in our_rows:
            step = int(row.get("step", 0))
            window_idx = step // window_size

            opp_name = tree2_name or match.get("tree2_agent", "unknown")
            enm_hp = safe_float(row.get("enm_health"), 100)
            ego_hp = safe_float(row.get("ego_health"), 100)
            dist = safe_float(row.get("distance_ft"), 5000)
            enm_in_wez = row.get("enm_in_wez", "").strip().lower() == "true"
            in_wez = row.get("in_wez", "").strip().lower() == "true"
            closure = safe_float(row.get("closure_rate_kts"), 0)

            vuln_data[opp_name][window_idx].append({
                "enm_hp": enm_hp,
                "ego_hp": ego_hp,
                "dist": dist,
                "enm_in_wez": enm_in_wez,
                "in_wez": in_wez,
                "closure": closure,
            })

    # 집계
    results = {}
    for opp_name, windows in vuln_data.items():
        opp_result = {}
        for widx in sorted(windows.keys()):
            entries = windows[widx]
            n = len(entries)
            if n < 20:
                continue

            avg_enm_hp = sum(e["enm_hp"] for e in entries) / n
            avg_ego_hp = sum(e["ego_hp"] for e in entries) / n
            avg_dist = sum(e["dist"] for e in entries) / n
            wez_rate = sum(1 for e in entries if e["in_wez"]) / n
            enm_wez_rate = sum(1 for e in entries if e["enm_in_wez"]) / n
            avg_closure = sum(e["closure"] for e in entries) / n

            # 취약도 = 우리가 WEZ 진입한 비율 + 적 HP 감소율
            hp_adv = avg_ego_hp - avg_enm_hp
            vulnerability = wez_rate * 100 + max(0, hp_adv) * 0.5

            step_range = f"{widx * window_size}-{(widx + 1) * window_size}"
            opp_result[step_range] = {
                "avg_enm_hp": round(avg_enm_hp, 1),
                "avg_ego_hp": round(avg_ego_hp, 1),
                "hp_advantage": round(hp_adv, 1),
                "avg_dist": round(avg_dist, 0),
                "in_wez_rate": round(wez_rate, 4),
                "enm_in_wez_rate": round(enm_wez_rate, 4),
                "avg_closure": round(avg_closure, 1),
                "vulnerability_score": round(vulnerability, 2),
                "n": n,
            }
        if opp_result:
            results[opp_name] = opp_result

    return results


# ============================================================
# Report Generation
# ============================================================

def generate_report(sae, tir, wpp, wcs, eip, evw, output_dir):
    """분석 결과를 텍스트 리포트로 출력."""
    lines = []
    def out(s=""):
        print(s)
        lines.append(s)

    out(f"\n{'='*70}")
    out(f"  Phase 1 메타데이터 분석 리포트")
    out(f"  생성: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    out(f"{'='*70}")

    # [1] SAE — BFM별 최고/최저 액션
    out(f"\n{'─'*70}")
    out(f"  [1] State-Action Effectiveness (SAE)")
    out(f"      공식: SAE = 0.4×Δ(ATA↓) + 0.3×Δ(거리↓) + 0.3×Δ(HP차이↑)")
    out(f"      lookahead 후 상태 개선도. 양수=좋음, 음수=나쁨")
    out(f"{'─'*70}")

    for bfm in list(BFM_RANK.keys()):
        entries = [(k, v) for k, v in sae.items() if v["bfm"] == bfm]
        if not entries:
            continue
        entries.sort(key=lambda x: x[1]["mean_sae"], reverse=True)
        out(f"\n  [{bfm}]")
        out(f"    {'Action':<25s} {'SAE':>8s} {'p25':>8s} {'p75':>8s} {'N':>6s}")
        for _, v in entries[:8]:
            bar_len = int(max(0, (v["mean_sae"] + 0.1) * 30))
            bar = "█" * bar_len
            out(f"    {v['action']:<25s} {v['mean_sae']:>8.4f} {v['p25']:>8.4f} {v['p75']:>8.4f} {v['n']:>6d}  {bar}")

    # [2] TIR — UNKNOWN에서의 전이
    out(f"\n{'─'*70}")
    out(f"  [2] Transition Induction Rate (TIR)")
    out(f"      각 Action이 유리한 전이(→OBFM)를 유도하는 확률")
    out(f"{'─'*70}")

    for bfm_prefix in ["UNK_NEAR_OFF", "UNK_SCISSORS", "UNK_DISENGAGING", "UNKNOWN"]:
        entries = [(k, v) for k, v in tir.items() if v["bfm"] == bfm_prefix]
        if not entries:
            continue
        entries.sort(key=lambda x: x[1]["tir_favorable"], reverse=True)
        out(f"\n  [{bfm_prefix}] → 전이 확률")
        out(f"    {'Action':<25s} {'→OBFM':>7s} {'→DBFM':>7s} {'→HABFM':>7s} {'→UNK':>7s} {'N':>6s}")
        for _, v in entries[:8]:
            out(f"    {v['action']:<25s} {v['tir_obfm']:>7.1%} {v['tir_dbfm']:>7.1%} "
                f"{v['tir_habfm']:>7.1%} {v['tir_unknown']:>7.1%} {v['n']:>6d}")

    # [3] WPP — WEZ 진입 선행 패턴
    out(f"\n{'─'*70}")
    out(f"  [3] WEZ Precursor Pattern (WPP)")
    out(f"      WEZ 진입 직전 10스텝의 공통 패턴")
    out(f"{'─'*70}")

    for wez_field in ["in_wez", "enm_in_wez"]:
        data = wpp.get(wez_field, {})
        out(f"\n  [{wez_field}] 이벤트 수: {data.get('count', 0)}")
        if data.get("count", 0) > 0:
            out(f"    평균 상태: ATA={data['avg_ata']}° dist={data['avg_dist']}ft closure={data['avg_closure']}kts")
            out(f"    선행 Action: {data.get('top_actions', {})}")
            out(f"    선행 BFM: {data.get('top_bfms', {})}")

    # [4] WCS — 승패 기여도
    out(f"\n{'─'*70}")
    out(f"  [4] Win Contribution Score (WCS)")
    out(f"      WCS = P(action|win) - P(action|loss)")
    out(f"      양수=승리 기여, 음수=패배 상관")
    out(f"{'─'*70}")

    wcs_sorted = sorted(wcs.values(), key=lambda x: x["wcs"], reverse=True)
    out(f"\n    {'Action':<25s} {'WCS':>8s} {'P(win)':>8s} {'P(loss)':>8s} {'N_win':>7s} {'N_loss':>7s}")
    for v in wcs_sorted:
        marker = "★" if abs(v["wcs"]) > 0.03 else " "
        out(f"    {v['action']:<25s} {v['wcs']:>+8.4f} {v['p_win']:>8.4f} {v['p_loss']:>8.4f} "
            f"{v['n_win']:>7d} {v['n_loss']:>7d}  {marker}")

    # Phase 2 권고
    # [5] EIP — 확률 기반 적 intent 프로파일 (상대 불문)
    out(f"\n{'─'*70}")
    out(f"  [5] Enemy Intent Profile (EIP) — 상태 조합별 행동 확률")
    out(f"      전체 적 풀 통합 (상대 불문). Phase 2 조건 노드 threshold 근거.")
    out(f"      총 rows: {eip.get('total_rows', 0):,}")
    out(f"{'─'*70}")

    # marginal ATA
    out(f"\n  ── ATA 구간별 행동 확률 (적 intent 핵심) ──")
    out(f"    {'ATA 구간':<12s} {'N':>7s}  Top-3 행동")
    for key in ["ata<30", "ata30-60", "ata60-90", "ata>90"]:
        entry = eip.get("marginal_ata", {}).get(key)
        if entry:
            top3 = ", ".join(f"{a} {p:.0%}" for a, p in list(entry["probs"].items())[:3])
            out(f"    {key:<12s} {entry['n']:>7,}  {top3}")

    # marginal BFM
    out(f"\n  ── BFM별 행동 확률 ──")
    out(f"    {'BFM':<12s} {'N':>7s}  Top-3 행동")
    for key in ["OBFM", "DBFM", "HABFM", "UNKNOWN"]:
        entry = eip.get("marginal_bfm", {}).get(key)
        if entry:
            top3 = ", ".join(f"{a} {p:.0%}" for a, p in list(entry["probs"].items())[:3])
            out(f"    {key:<12s} {entry['n']:>7,}  {top3}")

    # joint BFM × ATA (핵심 — 가장 실용적인 세분화)
    out(f"\n  ── BFM × ATA 교차 확률 (Phase 2 조건 노드 설계 입력) ──")
    out(f"    {'BFM|ATA':<25s} {'N':>6s}  Top Action (확률)")
    joint = eip.get("joint_bfm_ata", {})
    for key in sorted(joint.keys()):
        entry = joint[key]
        top = list(entry["probs"].items())[0] if entry["probs"] else ("?", 0)
        second = list(entry["probs"].items())[1] if len(entry["probs"]) > 1 else ("", 0)
        out(f"    {key:<25s} {entry['n']:>6,}  {top[0]} ({top[1]:.0%})"
            f"{'  ' + second[0] + ' (' + f'{second[1]:.0%}' + ')' if second[0] else ''}")

    # [6] EVW — 상대별 취약 구간
    out(f"\n{'─'*70}")
    out(f"  [6] Enemy Vulnerability Window (EVW)")
    out(f"      상대별 시간대별 취약도 (in_wez 비율 + HP 우위)")
    out(f"{'─'*70}")

    for opp_name in sorted(evw.keys()):
        opp_data = evw[opp_name]
        if not opp_data:
            continue
        # 취약도 최고 구간 찾기
        best_window = max(opp_data.items(), key=lambda x: x[1]["vulnerability_score"])
        out(f"\n  [{opp_name}]")
        out(f"    {'구간':>12s}  {'enm_HP':>7s} {'ego_HP':>7s} {'HP우위':>6s} "
            f"{'WEZ%':>6s} {'eWEZ%':>6s} {'취약도':>6s}")
        for window, data in sorted(opp_data.items(), key=lambda x: x[0]):
            marker = " ◀ peak" if window == best_window[0] else ""
            out(f"    {window:>12s}  {data['avg_enm_hp']:>7.1f} {data['avg_ego_hp']:>7.1f} "
                f"{data['hp_advantage']:>+6.1f} "
                f"{data['in_wez_rate']:>6.2%} {data['enm_in_wez_rate']:>6.2%} "
                f"{data['vulnerability_score']:>6.1f}{marker}")

    out(f"\n{'='*70}")
    out(f"  [Phase 2 권고사항 — 데이터 기반]")
    out(f"{'='*70}")

    # UNKNOWN에서 OBFM 전이율이 가장 높은 액션
    unk_entries = [(k, v) for k, v in tir.items()
                   if v["bfm"].startswith("UNK") and v["n"] >= 50]
    if unk_entries:
        best_unk = max(unk_entries, key=lambda x: x[1]["tir_favorable"])
        out(f"\n  UNKNOWN→OBFM 최고 전이 유도 액션: {best_unk[1]['action']}")
        out(f"    상태: {best_unk[1]['bfm']}, 전이율: {best_unk[1]['tir_favorable']:.1%}, N={best_unk[1]['n']}")

    # 승리 기여도 최고/최저 액션
    if wcs_sorted:
        out(f"\n  승리 기여 최고: {wcs_sorted[0]['action']} (WCS={wcs_sorted[0]['wcs']:+.4f})")
        out(f"  패배 상관 최고: {wcs_sorted[-1]['action']} (WCS={wcs_sorted[-1]['wcs']:+.4f})")

    out(f"\n{'='*70}\n")

    # 파일 저장
    report_path = Path(output_dir) / "summary_report.txt"
    with open(report_path, 'w', encoding='utf-8') as f:
        f.write("\n".join(lines))
    print(f"  리포트 저장: {report_path}")


# ============================================================
# Main
# ============================================================

def main():
    parser = argparse.ArgumentParser(description="Phase 1 메타데이터 분석기")
    parser.add_argument("--meta-dir", type=str, default="logs/metadata")
    parser.add_argument("--output-dir", type=str, default="logs/analysis")
    parser.add_argument("--lookahead", type=int, default=10,
                        help="SAE/TIR 측정 시 미래 스텝 수 (기본: 10)")
    parser.add_argument("--lookback", type=int, default=10,
                        help="WPP 선행 패턴 윈도우 (기본: 10)")
    parser.add_argument("--max-files", type=int, default=None,
                        help="분석할 최대 CSV 수 (테스트용)")
    args = parser.parse_args()

    output_dir = PROJECT_ROOT / args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)

    print(f"\n  메타데이터 로드 중: {args.meta_dir}")
    matches = load_metadata(PROJECT_ROOT / args.meta_dir, max_files=args.max_files)
    total_rows = sum(len(m["rows"]) for m in matches)
    print(f"  로드 완료: {len(matches)} 매치, {total_rows:,} rows")

    print(f"\n  [1/4] State-Action Effectiveness 계산...")
    sae = compute_sae(matches, lookahead=args.lookahead)
    with open(output_dir / "state_action_effectiveness.json", 'w') as f:
        json.dump(sae, f, indent=2, ensure_ascii=False)
    print(f"    {len(sae)} state-action 조합")

    print(f"  [2/4] Transition Induction Rate 계산...")
    tir = compute_tir(matches, lookahead=args.lookahead)
    with open(output_dir / "transition_rates.json", 'w') as f:
        json.dump(tir, f, indent=2, ensure_ascii=False)
    print(f"    {len(tir)} state-action 조합")

    print(f"  [3/4] WEZ Precursor Pattern 추출...")
    wpp = compute_wpp(matches, lookback=args.lookback)
    with open(output_dir / "wez_precursors.json", 'w') as f:
        json.dump(wpp, f, indent=2, ensure_ascii=False)
    print(f"    in_wez: {wpp.get('in_wez', {}).get('count', 0)} 이벤트")
    print(f"    enm_in_wez: {wpp.get('enm_in_wez', {}).get('count', 0)} 이벤트")

    print(f"  [4/6] Win Contribution Score 계산...")
    wcs = compute_wcs(matches)
    with open(output_dir / "win_contribution.json", 'w') as f:
        json.dump(wcs, f, indent=2, ensure_ascii=False)
    print(f"    {len(wcs)} 액션")

    print(f"  [5/6] Enemy Intent Profile 생성...")
    eip = compute_eip(matches)
    with open(output_dir / "enemy_intent_profiles.json", 'w') as f:
        json.dump(eip, f, indent=2, ensure_ascii=False)
    joint_count = len(eip.get("joint_bfm_ata", {}))
    print(f"    {eip.get('total_rows', 0):,} rows, {joint_count} BFM×ATA 조합")

    print(f"  [6/6] Enemy Vulnerability Window 계산...")
    evw = compute_evw(matches, window_size=100)
    with open(output_dir / "enemy_vulnerability.json", 'w') as f:
        json.dump(evw, f, indent=2, ensure_ascii=False)
    print(f"    {len(evw)} 상대 프로파일")

    print(f"\n  리포트 생성...")
    generate_report(sae, tir, wpp, wcs, eip, evw, str(output_dir))


if __name__ == "__main__":
    main()
