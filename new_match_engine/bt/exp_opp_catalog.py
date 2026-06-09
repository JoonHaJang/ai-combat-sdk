"""적 BT 도감 생성 — 각 archetype 이 상황(거리·자세·에너지)에 따라 어떤 tactic 으로 비행하는지.

합성 obs 로 상황을 만들어 각 archetype 대표의 tactic 응답을 표로. gen_opponent_zoo 의 BT 구조와
짝지어 "어떤 BT·어떻게 비행·상황별 변화"를 문서화.
"""
from __future__ import annotations
import sys, os, glob

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "control"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "engine"))
from yaml_bt import load_bt
import exp_opp_audit as au  # SimObs

ZOO = os.path.join(os.path.dirname(__file__), "..", "opponents", "zoo")

# 상황 정의 (이름, ata, aa, dist, ego_alt, closure, hca)
SITS = [
    ("정면머지",   5,  175, 6000, 15000,  120, 175),
    ("중립빔",     90,  90, 4000, 15000,   30,  90),
    ("우리가공격", 20,  40, 3000, 15000,   60,  30),   # 우리 적 뒤
    ("우리가방어", 150, 20, 2500, 15000,   50, 160),   # 적이 우리 뒤
    ("원거리",     30,  30,13000, 15000,   10,  20),
    ("저고도",     30,  90, 4000,  1500,   30,  90),
    ("에너지열세", 60,  60, 5000,  4000,   40,  60),
]


def _archetypes():
    by = {}
    for f in sorted(glob.glob(os.path.join(ZOO, "*.yaml"))):
        a = os.path.basename(f).rsplit("_", 1)[0]
        by.setdefault(a, []).append(f)
    return {a: fs[len(fs)//2] for a, fs in by.items()}


def main():
    arch = _archetypes()
    print(f"적 archetype {len(arch)}종 상황별 tactic:\n")
    hdr = "archetype          " + "".join(f"{s[0]:<10}" for s in SITS)
    print(hdr)
    for a, f in arch.items():
        fn = load_bt(f)
        cells = []
        for (_n, ata, aa, dist, alt, clo, hca) in SITS:
            o = au.SimObs(ata, aa, dist, alt, clo, hca)
            cells.append(fn(o).name[:9])
        print(f"{a:<19}" + "".join(f"{c:<10}" for c in cells))


if __name__ == "__main__":
    main()
