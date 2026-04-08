"""
test_intent_live.py — EIM 실시간 동작 확인 스크립트
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from collections import Counter
from src.match.runner import BehaviorTreeMatch
from src.intent import shared_state

# raw 신뢰도 전부 수집 (UNKNOWN 포함)
raw_log = []
_orig_set = shared_state.set_intent

def _patched_set(agent_id, intent, conf):
    _orig_set(agent_id, intent, conf)
    raw_log.append((agent_id[-4:], intent, round(max(conf.values()), 3)))

shared_state.set_intent = _patched_set

match = BehaviorTreeMatch(
    tree1_file="examples/eagle2/eagle2.yaml",
    tree2_file="examples/eagle1/eagle1.yaml",
    max_steps=500,
)
result = match.run(verbose=False)

print("=" * 55)
print(f"결과: {result.winner}")
print(f"Eagle2 HP: {match.health1.current_health:.1f}  |  Eagle1 HP: {match.health2.current_health:.1f}")
print(f"총 예측 건수: {len(raw_log)}")

if raw_log:
    max_confs = [x[2] for x in raw_log]
    print(f"최대 신뢰도 분포 (전체 {len(max_confs)}건):")
    buckets = [0]*10
    for c in max_confs:
        buckets[min(int(c*10), 9)] += 1
    for i, n in enumerate(buckets):
        lo = i*0.1; hi = (i+1)*0.1
        bar = "█" * (n // 3)
        print(f"  {lo:.1f}–{hi:.1f}: {n:>4}  {bar}")

    print(f"\n최고 신뢰도 예측 10건:")
    top = sorted(raw_log, key=lambda x: -x[2])[:10]
    for aid, intent, conf in top:
        print(f"  agent={aid}  intent={intent:<20}  conf={conf:.3f}")

    non_unknown = [x for x in raw_log if x[1] != "UNKNOWN"]
    if non_unknown:
        cnts = Counter(x[1] for x in non_unknown)
        print(f"\nIntent 분포 (non-UNKNOWN {len(non_unknown)}건):")
        for intent, n in cnts.most_common():
            print(f"  {intent:<22} {n:>4}")
    else:
        print("\n전체 예측이 UNKNOWN (신뢰도 < 0.35)")
