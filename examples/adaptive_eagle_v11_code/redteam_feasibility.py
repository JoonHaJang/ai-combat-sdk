#!/usr/bin/env python3
"""
Red Team Feasibility Check — 전체 의심, 실제 메타데이터 기반
목적: HCCA v12 설계 가정이 실제 전투 데이터와 일치하는지 검증

질문 목록:
  F1. 실제 obs 분포가 모델 설계 가정과 일치하는가?
  F2. vs_defensive 0% WR의 실제 원인은 무엇인가?
  F3. 적기가 수행하는 모든 기동이 우리 모델에 반영되어 있는가?
  F4. 우리 에이전트의 실제 모드 분포가 교리상 타당한가?
  F5. 설계 파라미터(임계값)가 실제 데이터 분포와 맞는가?
  F6. Tier 1/2 신규 변수(hca_deg, tc_type, in_39_line)가 실제로 변동하는가?
  F7. 승리한 경기와 패배한 경기에서 무엇이 다른가?
"""

import csv
import json
import math
import os
import statistics
from collections import Counter, defaultdict

BASE = "/Users/joon/Desktop/KAPILOT/ai-combat-sdk/logs/metadata/v11_analysis"

# ═══════════════════════════════════════════════════════════════════════════
# 메타데이터 로드
# ═══════════════════════════════════════════════════════════════════════════
def load_match(csv_path, result_path):
    with open(result_path) as f:
        result = json.load(f)
    rows = []
    with open(csv_path, newline='') as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append(row)
    return result, rows

matches = []
for fname in sorted(os.listdir(BASE)):
    if fname.endswith("_result.json"):
        csv_name = fname.replace("_result.json", ".csv")
        rpath = os.path.join(BASE, fname)
        cpath = os.path.join(BASE, csv_name)
        if os.path.exists(cpath):
            result, rows = load_match(cpath, rpath)
            matches.append({"result": result, "rows": rows,
                            "opponent": result["tree2_agent"],
                            "won": result["winner"] == "tree1"})

print(f"로드된 경기 수: {len(matches)}")
for m in matches:
    r = m["result"]
    print(f"  vs {r['tree2_agent']:12s} | winner={r['winner']:6s} | "
          f"steps={r['total_steps']:4d} | hp: {r['tree1_hp']:.1f} vs {r['tree2_hp']:.1f}")

# 에이전트별 행 분리
def agent_rows(rows, agent_prefix="A0"):
    return [r for r in rows if r["agent_id"].startswith(agent_prefix)]

def enemy_rows(rows, enemy_prefix="B0"):
    return [r for r in rows if r["enemy_id_prefix(rows, agent_prefix)"].startswith(enemy_prefix)]

def split_rows(rows):
    our = [r for r in rows if r["tree_name"] == "adaptive_eagle_v11"]
    enm = [r for r in rows if r["tree_name"] != "adaptive_eagle_v11"]
    return our, enm

def fval(row, key, default=0.0):
    try: return float(row[key])
    except: return default

def bval(row, key):
    return row[key].strip().lower() in ("true", "1", "yes")

# ═══════════════════════════════════════════════════════════════════════════
# F1. 실제 obs 분포 vs 모델 설계 가정
# ═══════════════════════════════════════════════════════════════════════════
print("\n" + "=" * 72)
print("F1. 실제 obs 분포 vs 설계 가정")
print("=" * 72)

all_our_rows = []
for m in matches:
    our, _ = split_rows(m["rows"])
    all_our_rows.extend(our)

def stat(vals, name, unit="", design_note=""):
    if not vals: return
    mn, mx = min(vals), max(vals)
    med = statistics.median(vals)
    try: sd = statistics.stdev(vals)
    except: sd = 0
    pct5  = sorted(vals)[int(len(vals)*0.05)]
    pct95 = sorted(vals)[int(len(vals)*0.95)]
    print(f"  {name:30s}: min={mn:8.2f} med={med:8.2f} max={mx:8.2f} "
          f"p5={pct5:8.2f} p95={pct95:8.2f}  {unit}")
    if design_note:
        print(f"    {'':30s}  설계 가정: {design_note}")
    return {"min":mn,"max":mx,"med":med,"p5":pct5,"p95":pct95}

ata_vals   = [fval(r,"ata_deg") for r in all_our_rows]
aa_vals    = [fval(r,"aa_deg") for r in all_our_rows]
hca_vals   = [fval(r,"hca_deg") for r in all_our_rows]
dist_vals  = [fval(r,"distance_ft") for r in all_our_rows]
cl_vals    = [fval(r,"closure_rate_kts") for r in all_our_rows]
en_vals    = [fval(r,"energy_diff_ft") for r in all_our_rows]
spd_vals   = [fval(r,"ego_vc_kts") for r in all_our_rows]
ps_vals    = [fval(r,"ps_fts") for r in all_our_rows]
tr_vals    = [fval(r,"turn_rate_degs") for r in all_our_rows]

stat(ata_vals,  "ATA (°)",          "°",   "PoC 기준 0~180° 선형")
stat(aa_vals,   "AA (°)",           "°",   "aa_facing=1-AA/180")
stat(hca_vals,  "HCA (°)",          "°",   "hca_threat: HCA>90°에서 증가")
stat(dist_vals, "distance (ft)",    "ft",  "WEZ=914ft, stale<3000ft, far=6000ft")
stat(cl_vals,   "closure (kts)",    "kts", "pur_stale=50kts, th_rdot_scale=300")
stat(en_vals,   "energy_diff (ft)", "ft",  "erg_deficit=-2000, erg_surplus=3000")
stat(spd_vals,  "ego_spd (kts)",    "kts", "corner=300kts, spd_adv_thresh=280kts")
stat(ps_vals,   "Ps (ft/s)",        "ft/s","en_ps_scale=200")
stat(tr_vals,   "turn_rate (°/s)",  "°/s", "own_tr = ego_spd/turn_rate")

# ═══════════════════════════════════════════════════════════════════════════
# F2. vs_defensive 0% WR 원인 분석
# ═══════════════════════════════════════════════════════════════════════════
print("\n" + "=" * 72)
print("F2. vs_defensive 0% WR — 실제 데이터 원인 분석")
print("=" * 72)

def_matches = [m for m in matches if m["opponent"] == "defensive"]
win_matches = [m for m in matches if m["won"]]

for dm in def_matches:
    our, enm = split_rows(dm["rows"])
    print(f"\n  [defensive R{def_matches.index(dm)+1}] steps={dm['result']['total_steps']}")

    # 모드 분포 (active_node)
    node_cnt = Counter(r["active_node"] for r in our)
    print(f"    active_node 분포: {dict(node_cnt.most_common(8))}")

    # WEZ 진입 여부
    wez_hits    = sum(1 for r in our if bval(r, "in_wez"))
    enm_wez     = sum(1 for r in our if bval(r, "enm_in_wez"))
    in39        = sum(1 for r in our if bval(r, "in_39_line"))
    total       = len(our)
    print(f"    in_wez={wez_hits}/{total} ({100*wez_hits/total:.1f}%)"
          f"  enm_in_wez={enm_wez}/{total} ({100*enm_wez/total:.1f}%)"
          f"  in_39={in39}/{total} ({100*in39/total:.1f}%)")

    # ATA 분포
    ata_def = [fval(r,"ata_deg") for r in our]
    dist_def = [fval(r,"distance_ft") for r in our]
    cl_def  = [fval(r,"closure_rate_kts") for r in our]
    print(f"    ATA: med={statistics.median(ata_def):.1f}° "
          f"  dist: med={statistics.median(dist_def):.0f}ft "
          f"  closure: med={statistics.median(cl_def):.1f}kts")

    # bfm_situation 분포
    bfm_cnt = Counter(r["bfm_situation"] for r in our)
    print(f"    bfm_situation: {dict(bfm_cnt)}")

    # tc_type 분포
    tc_cnt = Counter(r["tc_type"] for r in our)
    print(f"    tc_type: {dict(tc_cnt)}")

    # 적기 행동 분석 (enemy)
    enm_node = Counter(r["active_node"] for r in enm)
    print(f"    [적기] active_node: {dict(enm_node.most_common(8))}")
    enm_ata = [fval(r,"ata_deg") for r in enm]
    enm_dist = [fval(r,"distance_ft") for r in enm]
    print(f"    [적기] ATA: med={statistics.median(enm_ata):.1f}°  dist: med={statistics.median(enm_dist):.0f}ft")

# ═══════════════════════════════════════════════════════════════════════════
# F3. 적기 기동 전체 분석 — 우리 모델이 반영하는가
# ═══════════════════════════════════════════════════════════════════════════
print("\n" + "=" * 72)
print("F3. 적기 기동 전체 분석 — 우리 모델이 반영하는가")
print("=" * 72)

all_enm_rows = []
for m in matches:
    _, enm = split_rows(m["rows"])
    all_enm_rows.extend(enm)

print(f"\n  전체 적기 데이터 행 수: {len(all_enm_rows)}")

# 적기 active_node 전체
enm_nodes_all = Counter(r["active_node"] for r in all_enm_rows)
print("\n  적기 active_node 전체 분포:")
for node, cnt in enm_nodes_all.most_common(15):
    print(f"    {node:40s}: {cnt:5d} ({100*cnt/len(all_enm_rows):.1f}%)")

# bfm_situation별
enm_bfm = Counter(r["bfm_situation"] for r in all_enm_rows)
print(f"\n  적기 bfm_situation: {dict(enm_bfm)}")

# tc_type별
enm_tc = Counter(r["tc_type"] for r in all_enm_rows)
print(f"  적기 tc_type: {dict(enm_tc)}")

# 적기 obs 분포 (적의 ATA, AA, HCA는 우리 관점)
enm_ata_all = [fval(r,"ata_deg")*180 for r in all_enm_rows]
enm_aa_all  = [fval(r,"aa_deg")*180 for r in all_enm_rows]
enm_hca_all = [fval(r,"hca_deg")*180 for r in all_enm_rows]
enm_cl_all  = [fval(r,"closure_rate_kts") for r in all_enm_rows]
print(f"\n  적기 관점 ATA: med={statistics.median(enm_ata_all):.1f}°  "
      f"AA: med={statistics.median(enm_aa_all):.1f}°  "
      f"HCA: med={statistics.median(enm_hca_all):.1f}°")

# 적기 기동 패턴 — ATA 변화율 (연속 스텝 간)
print("\n  적기 ATA 변화율 (적기가 ATA를 얼마나 빠르게 줄이는가):")
enm_by_match = {}
for m in matches:
    _, enm = split_rows(m["rows"])
    key = m["result"]["tree2_agent"] + "_" + str(m["result"]["total_steps"])
    if key not in enm_by_match:
        enm_by_match[key] = []
    enm_by_match[key].extend(enm)

for opp in ["defensive", "simple", "eagle1", "ace"]:
    opp_rows = [r for r in all_enm_rows
                if r["tree_name"] == opp or
                any(m["opponent"] == opp for m in matches
                    if any(x["tree_name"]==opp for x in [r]))]
    pass

# 상대별 적기 행동 비교
for opp in ["defensive", "simple", "eagle1", "ace"]:
    opp_matches = [m for m in matches if m["opponent"] == opp]
    if not opp_matches:
        continue
    opp_enm_rows = []
    for om in opp_matches:
        _, enm = split_rows(om["rows"])
        opp_enm_rows.extend(enm)
    if not opp_enm_rows:
        continue
    opp_nodes = Counter(r["active_node"] for r in opp_enm_rows)
    opp_ata = [fval(r,"ata_deg") for r in opp_enm_rows]
    opp_cl  = [fval(r,"closure_rate_kts") for r in opp_enm_rows]
    print(f"\n  [{opp:10s}] nodes: {dict(opp_nodes.most_common(5))}")
    print(f"    ATA: med={statistics.median(opp_ata):.1f}° "
          f"  closure: med={statistics.median(opp_cl):.1f}kts")

# ═══════════════════════════════════════════════════════════════════════════
# F4. 우리 에이전트 실제 모드 분포 vs 교리 기대
# ═══════════════════════════════════════════════════════════════════════════
print("\n" + "=" * 72)
print("F4. 우리 에이전트 실제 모드 분포 vs 교리 기대")
print("=" * 72)

our_nodes_all = Counter(r["active_node"] for r in all_our_rows)
total_our = len(all_our_rows)
print(f"\n  전체 에이전트 active_node ({total_our}행):")
for node, cnt in our_nodes_all.most_common(15):
    pct = 100*cnt/total_our
    concern = ""
    if "LeadPursuit" in node and pct > 60: concern = " ⚠️ 너무 높음 — ATTACK 미전환?"
    if "Defend" in node or "Break" in node: concern = " (방어)"
    if "Energy" in node: concern = " (에너지)"
    print(f"    {node:40s}: {cnt:5d} ({pct:.1f}%){concern}")

# 상대별 모드 분포
print("\n  상대별 모드 분포:")
for opp in ["defensive", "simple", "eagle1", "ace"]:
    opp_matches = [m for m in matches if m["opponent"] == opp]
    if not opp_matches: continue
    opp_our_rows = []
    for om in opp_matches:
        our, _ = split_rows(om["rows"])
        opp_our_rows.extend(our)
    if not opp_our_rows: continue
    opp_our_nodes = Counter(r["active_node"] for r in opp_our_rows)
    won = all(m["won"] for m in opp_matches)
    lost = all(not m["won"] for m in opp_matches)
    outcome = "❌LOSS" if lost else ("✅WIN" if won else "~MIX")
    print(f"\n  [{opp:10s}] {outcome}:")
    for node, cnt in opp_our_nodes.most_common(8):
        print(f"    {node:40s}: {cnt:4d} ({100*cnt/len(opp_our_rows):.1f}%)")

# ═══════════════════════════════════════════════════════════════════════════
# F5. 설계 파라미터 vs 실제 데이터 분포 정합성
# ═══════════════════════════════════════════════════════════════════════════
print("\n" + "=" * 72)
print("F5. 설계 파라미터 vs 실제 데이터 분포 — 임계값 타당성")
print("=" * 72)

def check_threshold(vals, thresh, name, direction="above", design_purpose=""):
    pct_above = 100 * sum(1 for v in vals if v > thresh) / len(vals) if vals else 0
    pct_below = 100 - pct_above
    flag = ""
    if direction == "above" and pct_above < 5:
        flag = " ⚠️ 임계값이 너무 높아 조건 거의 안 발동"
    elif direction == "below" and pct_below < 5:
        flag = " ⚠️ 임계값이 너무 낮아 조건 거의 안 발동"
    elif direction == "above" and pct_above > 95:
        flag = " ⚠️ 임계값이 너무 낮아 항상 발동"
    print(f"  {name:40s}: thresh={thresh:8.1f}  "
          f"above={pct_above:.1f}%  below={pct_below:.1f}%{flag}")
    if design_purpose:
        print(f"    {'':40s}  용도: {design_purpose}")

print("\n  [Layer 1 — τ 임계값]")
check_threshold(cl_vals,   300,   "closure vs th_rdot_scale=300",  "above", "τ_threat closure 항 스케일")
check_threshold(cl_vals,   50,    "closure vs pur_stale=50",       "below", "scissors 탐지")
check_threshold(hca_vals,  90,    "HCA vs hca_threat threshold=90","above", "head-on HCA 보강 발동")
check_threshold(dist_vals, 914,   "dist vs op_wez_max=914",        "below", "τ_opp WEZ 항 발동")
check_threshold(dist_vals, 3000,  "dist vs pur_stale_dist=3000",   "below", "stale/orbit 탐지")
check_threshold(dist_vals, 6000,  "dist vs pur_far_dist=6000",     "above", "sprint 모드")
check_threshold(dist_vals, 8000,  "dist vs dist_decay=8000",       "below", "τ_opp decay")
check_threshold(en_vals,  -2000,  "e_diff vs erg_deficit=-2000",   "below", "ENERGY 모드 트리거")
check_threshold(en_vals,   3000,  "e_diff vs erg_surplus=3000",    "above", "에너지 잉여 전환")
check_threshold(spd_vals,  280,   "ego_spd vs spd_adv_thresh=280", "above", "속도 우위 판단")
check_threshold(spd_vals,  300,   "ego_spd vs corner_speed=300",   "above", "코너속도 기준")
check_threshold(ata_vals,  20,    "ATA vs atk_wez_ata_thresh=20",  "below", "ATTACK gate 발동")

# ═══════════════════════════════════════════════════════════════════════════
# F6. Tier 1 신규 변수 실제 변동성 확인
# ═══════════════════════════════════════════════════════════════════════════
print("\n" + "=" * 72)
print("F6. Tier 1 신규 변수 실제 변동성 — 사용 가치 있는가?")
print("=" * 72)

hca_unique = len(set(f"{v:.0f}" for v in hca_vals))
tc_cnt_all = Counter(r["tc_type"] for r in all_our_rows)
in39_cnt   = Counter(r["in_39_line"] for r in all_our_rows)
overshoot_cnt = Counter(r["overshoot_risk"] for r in all_our_rows)

print(f"\n  hca_deg: 고유값 수={hca_unique}, "
      f"<90°(no effect)={100*sum(1 for v in hca_vals if v<90)/len(hca_vals):.1f}%, "
      f">=90°(active)={100*sum(1 for v in hca_vals if v>=90)/len(hca_vals):.1f}%")
if hca_unique < 5:
    print(f"  ⚠️  hca_deg 변동성 극히 낮음 — 실제로 사용 불가")

print(f"  tc_type: {dict(tc_cnt_all)}")
if len(tc_cnt_all) == 1:
    print(f"  ⚠️  tc_type 변동 없음 — 항상 {list(tc_cnt_all.keys())[0]}")

print(f"  in_39_line: {dict(in39_cnt)}")
in39_true = in39_cnt.get("True", 0)
in39_false = in39_cnt.get("False", 0)
if in39_true == 0:
    print(f"  ⚠️  in_39_line 항상 False — 이 변수가 실제로 작동하지 않음!")

print(f"  overshoot_risk: {dict(overshoot_cnt)}")

# tau_deg 분포
tau_vals = [fval(r,"tau_deg") for r in all_our_rows]
print(f"  tau_deg (lead angle): "
      f"min={min(tau_vals):.3f} med={statistics.median(tau_vals):.3f} max={max(tau_vals):.3f}")
if min(tau_vals) == max(tau_vals):
    print(f"  ⚠️  tau_deg 변동 없음!")

# ═══════════════════════════════════════════════════════════════════════════
# F7. 승리 vs 패배 경기 비교
# ═══════════════════════════════════════════════════════════════════════════
print("\n" + "=" * 72)
print("F7. 승리 vs 패배 경기 — 무엇이 다른가?")
print("=" * 72)

win_rows_all  = []
loss_rows_all = []
for m in matches:
    our, _ = split_rows(m["rows"])
    if m["won"]:
        win_rows_all.extend(our)
    elif not m["won"] and m["result"]["winner"] != "draw":
        loss_rows_all.extend(our)

def compare(win_rows, loss_rows, key, scale=1.0, label=""):
    w_vals = [fval(r,key)*scale for r in win_rows]
    l_vals = [fval(r,key)*scale for r in loss_rows]
    if not w_vals or not l_vals: return
    w_med = statistics.median(w_vals)
    l_med = statistics.median(l_vals)
    diff = w_med - l_med
    flag = " ⚠️  유의한 차이!" if abs(diff) > (w_med+l_med)/2 * 0.2 else ""
    print(f"  {label or key:35s}: WIN={w_med:8.2f}  LOSS={l_med:8.2f}  Δ={diff:+8.2f}{flag}")

if win_rows_all and loss_rows_all:
    compare(win_rows_all, loss_rows_all, "ata_deg", 1,           "ATA (°)")
    compare(win_rows_all, loss_rows_all, "aa_deg",  1,           "AA (°)")
    compare(win_rows_all, loss_rows_all, "hca_deg", 1,           "HCA (°)")
    compare(win_rows_all, loss_rows_all, "distance_ft", 1,      "distance (ft)")
    compare(win_rows_all, loss_rows_all, "closure_rate_kts", 1, "closure (kts)")
    compare(win_rows_all, loss_rows_all, "energy_diff_ft", 1,   "energy_diff (ft)")
    compare(win_rows_all, loss_rows_all, "ego_vc_kts", 1,       "ego_spd (kts)")
    compare(win_rows_all, loss_rows_all, "ps_fts", 1,           "Ps (ft/s)")

    # 노드 사용 비교
    win_nodes  = Counter(r["active_node"] for r in win_rows_all)
    loss_nodes = Counter(r["active_node"] for r in loss_rows_all)
    all_nodes  = set(win_nodes) | set(loss_nodes)
    print(f"\n  active_node 비율 비교 (WIN vs LOSS):")
    for node in sorted(all_nodes, key=lambda n: -win_nodes.get(n,0)):
        w_pct = 100*win_nodes.get(node,0)/max(len(win_rows_all),1)
        l_pct = 100*loss_nodes.get(node,0)/max(len(loss_rows_all),1)
        flag = " ⚠️" if abs(w_pct-l_pct) > 10 else ""
        print(f"    {node:40s}: WIN={w_pct:5.1f}%  LOSS={l_pct:5.1f}%{flag}")
else:
    print("  (승/패 데이터 부족)")

# ═══════════════════════════════════════════════════════════════════════════
# F8. 핵심 설계 가정 Red Team 도전
# ═══════════════════════════════════════════════════════════════════════════
print("\n" + "=" * 72)
print("F8. 핵심 설계 가정 — Red Team 도전")
print("=" * 72)

issues = []

# 가정 1: ga = σ((AA-ATA)/45)는 기하학적 우위를 잘 표현하는가?
# 실제 데이터에서 AA와 ATA의 관계
aa_minus_ata = [fval(r,"aa_deg") - fval(r,"ata_deg") for r in all_our_rows]
ga_vals_real = [1/(1+math.exp(-v/45)) for v in aa_minus_ata]
print(f"\n  [가정1] ga = σ((AA-ATA)/45)")
print(f"    실제 ga 분포: min={min(ga_vals_real):.3f} "
      f"med={statistics.median(ga_vals_real):.3f} max={max(ga_vals_real):.3f}")
pct_ga_high = 100*sum(1 for v in ga_vals_real if v > 0.7)/len(ga_vals_real)
print(f"    ga > 0.7 (공격적 위치): {pct_ga_high:.1f}%")
if pct_ga_high > 70:
    issues.append("ga가 실제로는 대부분 높음 — AA-ATA 평균적으로 양수 (우리가 대체로 유리한 위치)")

# 가정 2: enm_in_wez가 실제로 발동하는가?
enm_wez_total = sum(1 for r in all_our_rows if bval(r,"enm_in_wez"))
print(f"\n  [가정2] enm_in_wez 발동률: {enm_wez_total}/{len(all_our_rows)} ({100*enm_wez_total/len(all_our_rows):.1f}%)")
if enm_wez_total < len(all_our_rows) * 0.05:
    issues.append("enm_in_wez가 거의 발동 안 함 — ATTACK gate가 실제론 거의 안 열림!")

# 가정 3: HCA가 실제로 90° 이상 분포하는가?
hca_above90 = sum(1 for v in hca_vals if v >= 90)
print(f"\n  [가정3] HCA >= 90° (head-on 성분): {hca_above90}/{len(hca_vals)} ({100*hca_above90/len(hca_vals):.1f}%)")
if hca_above90 < len(hca_vals) * 0.1:
    issues.append("HCA가 대부분 90° 미만 — HCA head-on 보강 항이 실제로 거의 작동 안 함")

# 가정 4: tc_type이 실제로 변동하는가?
tc_2circle = sum(1 for r in all_our_rows if r["tc_type"].strip() == "2-circle")
print(f"\n  [가정4] tc_type=2-circle 비율: {tc_2circle}/{len(all_our_rows)} ({100*tc_2circle/len(all_our_rows):.1f}%)")
if tc_2circle == 0:
    issues.append("tc_type이 항상 1-circle → 2-circle lag-roll이 실제로 절대 발동 안 됨!")
elif tc_2circle == len(all_our_rows):
    issues.append("tc_type이 항상 2-circle → 1-circle 케이스 처리 없음")

# 가정 5: defensive 상대가 왜 이기는가?
def_rows_our = []
for m in [m for m in matches if m["opponent"]=="defensive"]:
    our, _ = split_rows(m["rows"])
    def_rows_our.extend(our)
if def_rows_our:
    def_enm_wez = sum(1 for r in def_rows_our if bval(r,"enm_in_wez"))
    def_in_wez  = sum(1 for r in def_rows_our if bval(r,"in_wez"))
    def_ata = [fval(r,"ata_deg") for r in def_rows_our]
    print(f"\n  [가정5] vs defensive: "
          f"enm_in_wez={def_enm_wez}/{len(def_rows_our)} ({100*def_enm_wez/len(def_rows_our):.1f}%)  "
          f"in_wez={def_in_wez}/{len(def_rows_our)} ({100*def_in_wez/len(def_rows_our):.1f}%)")
    print(f"    우리 ATA: med={statistics.median(def_ata):.1f}°")
    if def_enm_wez < 5:
        issues.append("vs defensive: enm_in_wez가 거의 0 → ATTACK gate 전혀 열리지 않음 "
                      "→ 우리 에이전트가 ATTACK으로 전환 불가")

# 가정 6: PoC에서 증명한 시나리오들이 실제로 발생하는가?
print(f"\n  [가정6] PoC 시나리오 실제 발생 여부:")
s01_real = sum(1 for r in all_our_rows
               if fval(r,"ata_deg") < 10 and fval(r,"aa_deg") < 10
               and fval(r,"closure_rate_kts") > 400)
s04_real = sum(1 for r in all_our_rows
               if r["tc_type"].strip() == "2-circle"
               and fval(r,"ata_deg") > 60 and fval(r,"distance_ft") > 3000)
s06_real = sum(1 for r in all_our_rows
               if abs(fval(r,"closure_rate_kts")) < 50
               and fval(r,"distance_ft") < 3000)

print(f"    S01 head-on (ATA<10,AA<10,closure>400): {s01_real} 행")
print(f"    S04 2-circle lag-roll (2-circle,ATA>60,dist>3000): {s04_real} 행")
print(f"    S06 scissors (|closure|<50,dist<3000): {s06_real} 행")
if s01_real == 0:
    issues.append("S01 head-on 시나리오가 실제 전투에서 발생하지 않음")
if s04_real == 0:
    issues.append("S04 2-circle lag-roll 시나리오가 실제 전투에서 발생하지 않음")

# ═══════════════════════════════════════════════════════════════════════════
# FINAL RED TEAM VERDICT
# ═══════════════════════════════════════════════════════════════════════════
print("\n" + "=" * 72)
print("RED TEAM FEASIBILITY VERDICT")
print("=" * 72)

print("\n발견된 이슈:")
if not issues:
    print("  (이슈 없음 — 모든 가정이 데이터와 일치)")
else:
    for i, issue in enumerate(issues, 1):
        print(f"  [{i}] {issue}")

print("\n" + "─" * 72)
print("결론: 위 이슈들을 기반으로 HCCA v12의 실제 전투 실효성을 판단할 것")
