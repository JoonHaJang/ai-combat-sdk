"""Feature-orthogonal 상황 분류 + BT zoo 매치 시계열 측정 (2026-06-01).

사용자 통찰: 진짜 mode 분리 + DEFENSIVE 차원 포함 (적이 우리 뒤).

목적:
1. classify_situation(obs, f, state) 정의 — 명확한 임계값, overlap 없음
2. BT zoo 매치 metadata 시계열 → 상황 분포 측정
3. AGG/ACE 분포 비교 → 진짜 분리 시그널 식별

상황 16개 (5 카테고리):
  OFFENSIVE: O1_TRACKING / O2_CHASE / O3_CUTOFF / O4_TAIL_CHASE
  DEFENSIVE: D1_BOGEY_6 / D2_GUNS_DEFENSE / D3_OVERSHOOT_BAIT / D4_BUGOUT
  NEUTRAL:   N1_HEADON / N2_ONE_CIRCLE / N3_TWO_CIRCLE / N4_LUFBERY / N5_SCISSORS
  MERGE:     M1_SPAWN_HEADON
  FIRE:      F1_WEZ_ENTRY / F2_HARD_DECK

usage:
    python tools/situation_lookup.py logs/h13_baseline_3d/*.csv
"""
from __future__ import annotations
import sys, csv, glob
from collections import Counter
from pathlib import Path


HARD_DECK_FT = 1000.0


def deg(v):
    try: return float(v) / 180.0
    except: return 0.0


def to_float(v, default=0.0):
    try: return float(v)
    except: return default


def classify_situation(obs_row, prev_aa=None, spawn_tick=999):
    """Feature-orthogonal 상황 분류 — 16 명확한 상황 중 1개.

    Args:
        obs_row: metadata CSV row (us 측)
        prev_aa: 1초 전 aa (omega 계산용)
        spawn_tick: spawn 후 경과 tick

    Returns:
        situation 명 (str)
    """
    ata = deg(obs_row.get("ata_deg", 0))
    aa = deg(obs_row.get("aa_deg", 0))
    dist = to_float(obs_row.get("distance_ft", 0))
    closure = to_float(obs_row.get("closure_rate_kts", 0))
    in_wez = obs_row.get("in_wez", "False") in ("True", "1", "1.000000")
    enm_in_wez = obs_row.get("enm_in_wez", "False") in ("True", "1", "1.000000")
    ego_alt = to_float(obs_row.get("ego_altitude_ft", 0))
    alt_gap = to_float(obs_row.get("alt_gap_ft", 0))
    side_flag = to_float(obs_row.get("side_flag", 0))

    # F2: Hard Deck (최우선 안전)
    if ego_alt < HARD_DECK_FT + 1500:
        return "F2_HARD_DECK"

    # F1: WEZ entry (우리 fire 준비)
    if in_wez and ata < 12:
        return "F1_WEZ_ENTRY"

    # D2: GUNS_DEFENSE (적이 우리 사정거리 안)
    if enm_in_wez:
        return "D2_GUNS_DEFENSE"

    # M1: SPAWN_HEADON (spawn 직후 90° crossing)
    if spawn_tick < 20 and 60 <= ata <= 120 and dist < 5000:
        return "M1_SPAWN_HEADON"

    # DEFENSIVE — 적 nose 우리 향 (aa < 30)
    if aa < 30:
        if closure > 200 and dist < 4000:
            return "D3_OVERSHOOT_BAIT"
        if dist > 4000 and alt_gap > 1000:
            return "D4_BUGOUT"
        if ata > 120 and dist < 5000:
            return "D1_BOGEY_6"
        return "D1_BOGEY_6"   # default 적 nose 우리 향

    # OFFENSIVE — aa > 120 (적 등이 우리 향, 우리 후방)
    if aa > 120:
        if dist < 500:
            return "O4_TAIL_CHASE"
        if 500 <= dist <= 3000 and ata < 30:
            return "O1_TRACKING"
        if dist > 3000 and closure < -50:
            return "O2_CHASE"   # ⭐ 핵심
        if 3000 <= dist <= 6000 and -50 <= closure <= 50:
            return "O4_TAIL_CHASE"
        return "O3_CUTOFF"

    # CUTOFF — 적 측면, lead pursuit 시도
    if 30 <= ata <= 60 and dist > 3000:
        return "O3_CUTOFF"

    # NEUTRAL HEADON — 양쪽 마주봐서
    if 60 <= ata <= 120 and 60 <= aa <= 120 and closure > 100:
        return "N1_HEADON"

    # NEUTRAL TURN FIGHT
    if 30 <= ata <= 90 and dist < 5000:
        return "N2_ONE_CIRCLE"   # placeholder (omega 부호 필요)

    if 90 <= ata <= 150 and dist < 6000:
        return "N4_LUFBERY"

    return "OTHER"


def analyze(path, opp_name=None):
    with open(path) as f:
        rows = list(csv.DictReader(f))
    us = [r for r in rows if r["tree_name"] == "pursuit_chase_btcost"]
    name = opp_name or Path(path).stem.split("_vs_")[-1].replace("_meta", "")

    sit_seq = []
    for i, r in enumerate(us):
        sit = classify_situation(r, spawn_tick=i // 2)
        sit_seq.append(sit)

    counts = Counter(sit_seq)
    total = len(sit_seq)
    print(f"\n=== {name} ({total} env steps) ===")
    print("CATEGORY  | situation         | count   pct")
    print("-" * 55)
    cat_order = ["F", "D", "M", "O", "N", "OTHER"]
    grouped = {}
    for s, c in counts.items():
        cat = s[0] if s[0] in cat_order else "OTHER"
        grouped.setdefault(cat, []).append((s, c))
    for cat in cat_order:
        if cat not in grouped: continue
        for s, c in sorted(grouped[cat], key=lambda x: -x[1]):
            print(f"  {cat:7s} | {s:18s} | {c:5d}   {100*c/total:5.1f}%")


if __name__ == "__main__":
    paths = []
    for p in sys.argv[1:]:
        paths.extend(sorted(glob.glob(p)))
    if not paths:
        print("usage: python situation_lookup.py <meta_csv> [...]")
        sys.exit(1)
    for p in paths:
        analyze(p)
