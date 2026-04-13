"""
find_rigid_behavior.py — ACMI에서 "관측 변화 vs 행동 고정" 구간 탐지.

목적: 기동이 관측값 변화에 반응하지 않는 구간을 자동 식별.
     이 구간은 "피드백이 빠진" 부분 → 개선 포인트.

방법:
  1. ACMI를 파싱 (ACMIParser 재사용)
  2. 각 tick의 (관측, action)을 추출
  3. 슬라이딩 윈도우로 다음 조건을 감지:
     - 거리가 연속으로 벌어지는데 선회/속도가 변화 없음
     - ATA가 증가하는데 선회 방향/강도가 동일
     - 에너지 차이가 크게 변하는데 고도/속도 불변
     - WEZ 진입 직전인데 감속 없음
  4. 발견된 각 구간에 "어떻게 했어야 했는지" 설명 출력

사용:
    python tools/find_rigid_behavior.py replays_v51/ace/adaptive_eagle_vs_ace.acmi
"""

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from tools.analyze_acmi import ACMIParser


def find_rigid_intervals(parser):
    """rigid-behavior 구간을 탐지."""
    frames = parser.frames
    n = len(frames)
    if n < 20:
        return []

    findings = []

    # Helper: frame에서 관측값 뽑기
    def get(f, key, default=0):
        return f["ego"].get(key, default)

    # 1. 거리 벌어짐 + 선회 변화 없음
    window = 20  # 4초 (0.2s × 20 tick)
    i = window
    while i < n - window:
        past = frames[i - window]["ego"]
        now = frames[i]["ego"]
        # 거리 크게 증가 (> 500ft)
        dist_delta = now["dist"] - past["dist"]
        if dist_delta > 500:
            # 같은 구간 ATA는?
            ata_now = now["ata"]
            # action node 동일?
            if past["active_node"] == now["active_node"] and now["active_node"]:
                findings.append({
                    "type": "DIST_WIDENING_RIGID",
                    "tick": i,
                    "t_s": now.get("t", i * 0.2),
                    "node": now["active_node"],
                    "dist_change": round(dist_delta),
                    "ata": round(ata_now, 1),
                    "closure": round(now["closure"], 1),
                    "advice": "거리 벌어짐 + 같은 행동 지속 → 타이트 턴 또는 가속 필요",
                })
                i += window  # skip ahead
        i += 1

    # 2. ATA 증가 지속 (포인팅 실패 연속)
    i = window
    while i < n - window:
        atas = [frames[j]["ego"]["ata"] for j in range(i - window, i + 1)]
        # 단조 증가 체크 (10° 이상)
        if atas[-1] - atas[0] > 10 and all(
                atas[j] >= atas[j-1] - 1 for j in range(1, len(atas))):
            now = frames[i]["ego"]
            findings.append({
                "type": "ATA_GROWING_RIGID",
                "tick": i,
                "t_s": now.get("t", i * 0.2),
                "node": now["active_node"],
                "ata_start": round(atas[0], 1),
                "ata_end": round(atas[-1], 1),
                "advice": "ATA 연속 증가 → 타이트 턴으로 각도 회수 필요",
            })
            i += window
        i += 1

    # 3. WEZ 임박인데 감속 없음 (closure 과다)
    for i in range(1, n):
        now = frames[i]["ego"]
        if (now["dist"] < 1200 and now["dist"] > 152
                and abs(now["ata"]) < 20 and now["closure"] > 250):
            prev = frames[i - 1]["ego"]
            # closure 변화 없으면 브레이크 안 함
            if abs(now["closure"] - prev["closure"]) < 10:
                findings.append({
                    "type": "WEZ_OVERSHOOT_RISK",
                    "tick": i,
                    "t_s": now.get("t", i * 0.2),
                    "node": now["active_node"],
                    "dist": round(now["dist"]),
                    "ata": round(now["ata"], 1),
                    "closure": round(now["closure"], 1),
                    "advice": "WEZ 직전 + closure 과다 → 감속 브레이크 필요 (lag pursuit)",
                })

    # 4. HighYoYo 판정: climb 계속 + dist 벌어짐
    # (active_node가 포함 "YoYo"인 경우)
    i = window
    while i < n - window:
        now = frames[i]["ego"]
        if now["active_node"] and "YoYo" in now["active_node"]:
            past = frames[i - window]["ego"]
            if now["dist"] - past["dist"] > 800:
                findings.append({
                    "type": "YOYO_WIDENING",
                    "tick": i,
                    "t_s": now.get("t", i * 0.2),
                    "node": now["active_node"],
                    "dist_gain": round(now["dist"] - past["dist"]),
                    "advice": "Yo-Yo 중 거리 벌어짐 → 반경이 과대, 즉시 DIVE 또는 lead 전환",
                })
                i += window
        i += 1

    # 5. 동일 action 연속 (> 50 tick = 10초) + closure 음수
    i = 0
    streak_node = None
    streak_start = 0
    while i < n:
        node = frames[i]["ego"]["active_node"]
        if node == streak_node:
            streak_len = i - streak_start
            if streak_len == 50:  # 10초 연속
                mid = frames[(streak_start + i) // 2]["ego"]
                if mid["closure"] < 0:  # 이 기간 동안 벌어지는 중
                    findings.append({
                        "type": "SAME_ACTION_LONG_STREAK",
                        "tick": i,
                        "t_s": mid.get("t", i * 0.2),
                        "node": node,
                        "streak_len": streak_len,
                        "avg_closure": round(mid["closure"], 1),
                        "advice": f"{streak_len} tick 연속 동일 action + closure 음수 → 전략 전환 필요",
                    })
        else:
            streak_node = node
            streak_start = i
        i += 1

    return findings


def print_findings(path, findings):
    print(f"\n{'='*70}")
    print(f"  Rigid Behavior Detection: {Path(path).name}")
    print('='*70)

    if not findings:
        print("  No rigid behavior detected.")
        return

    by_type = {}
    for f in findings:
        by_type.setdefault(f["type"], []).append(f)

    for typ, items in by_type.items():
        print(f"\n  [{typ}]  {len(items)}건")
        # Show top 3
        for f in items[:3]:
            print(f"    @ t={f['t_s']:.1f}s  node={f['node']}")
            print(f"      {f['advice']}")
            detail = {k: v for k, v in f.items()
                      if k not in ("type", "tick", "t_s", "node", "advice")}
            if detail:
                print(f"      {detail}")
        if len(items) > 3:
            print(f"    ... 및 {len(items) - 3}건 더")
    print()


def main():
    ap = argparse.ArgumentParser(description="ACMI rigid behavior detector")
    ap.add_argument("path", help="ACMI 파일 또는 디렉토리")
    args = ap.parse_args()

    p = Path(args.path)
    if p.is_file():
        paths = [p]
    elif p.is_dir():
        paths = sorted(p.rglob("*.acmi"))
    else:
        print(f"ERROR: {p} not found")
        return 1

    for path in paths:
        try:
            parser = ACMIParser(path)
            findings = find_rigid_intervals(parser)
            print_findings(path, findings)
        except Exception as e:
            print(f"ERROR {path}: {e}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
