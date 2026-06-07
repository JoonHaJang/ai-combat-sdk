"""R2 — 설계된 적 풀 생성기 (1:1 dogfight 문제 커버).

3장 BFM 교리 근거 13 archetype × 파라미터 변주 → .yaml BT suite.
yaml_bt 인터프리터로 실행, bt-editor 편집 가능. 어휘 35조건/37액션 사용.

생성 규칙:
  - 각 archetype 은 우선순위 Selector. 첫 가지는 항상 안전(BelowHardDeck→ClimbTo).
  - 변주는 archetype 이 실제 읽는 파라미터 축의 곱. 결과 트리 문자열로 dedup → 진짜 distinct.
  - archetype 당 최대 12변주.

출력: new_match_engine/opponents/zoo/{archetype}_{i:02d}.yaml
"""
from __future__ import annotations
import os, itertools, yaml

OUT = os.path.join(os.path.dirname(__file__), "..", "opponents", "zoo")


# ── 노드 헬퍼 ──────────────────────────────────────────────────────────────
def C(name, **p):  return {"type": "Condition", "name": name, "params": p}
def A(name, **p):  return {"type": "Action", "name": name, "params": p}
def Seq(*ch):      return {"type": "Sequence", "children": [c for c in ch if c]}
def Sel(*ch):      return {"type": "Selector", "children": [c for c in ch if c]}

def SAFETY():      return Seq(C("BelowHardDeck", threshold_ft=1200.0), A("ClimbTo"))
def GUN(ata, rng): return Seq(C("DistanceBelow", threshold_ft=rng),
                              C("ATABelow", threshold_deg=ata), A("GunAttack"))
def BREAK(aa):     return Seq(C("UnderThreat", aa_threshold_deg=aa), A("BreakTurn"))


# ── archetype 트리 빌더 (params dict → tree) ──────────────────────────────
def a1_pure(p):
    gun = GUN(p["gun_ata"], p["gun_range"]) if p["gun_range"] > 0 else None
    return Sel(SAFETY(), gun, A("Pursue"))

def a2_guntracker(p):
    return Sel(SAFETY(), GUN(p["gun_ata"], p["gun_range"]),
               Seq(C("ATABelow", threshold_deg=p["lead_ata"]), A("LeadPursuit")),
               A("Pursue"))

def a3_lag(p):
    # 원거리=lag(통제구역 유지), 근거리=pure(파고들기) → commit 이 진짜 분기
    return Sel(SAFETY(), GUN(p["gun_ata"], p["gun_range"]),
               Seq(C("DistanceAbove", threshold_ft=p["commit"]), A("LagPursuit")),
               A("Pursue"))

def b1_energy(p):
    return Sel(SAFETY(), BREAK(p["def_aa"]),
               Seq(C("AltitudeBelow", min_altitude_ft=p["climb_alt"]), A("ClimbingTurn")),
               Seq(C("IsEnergyAdvantage"), A("HighYoYo")),
               GUN(p["gun_ata"], 3000.0),
               A("HighYoYo"))

def b2_extend(p):
    return Sel(SAFETY(), BREAK(p["def_aa"]),
               Seq(C("DistanceAbove", threshold_ft=p["commit"]), A("Accelerate")),
               Seq(C("IsDisengaging"), A("Accelerate")),
               A("Straight"))

def c1_tworate(p):
    return Sel(SAFETY(), BREAK(p["def_aa"]),
               Seq(C("IsMerged"), A("TwoCircleFight")),
               Seq(C("DistanceBelow", threshold_ft=p["commit"]), A("TCFight")),
               A("TwoCircleFight"))

def c2_oneradius(p):
    return Sel(SAFETY(), BREAK(p["def_aa"]),
               Seq(C("IsMerged"), A("OneCircleFight")),
               Seq(C("DistanceBelow", threshold_ft=p["commit"]), A("OneCircleFight")),
               A("OneCircleFight"))

def c3_lufbery(p):
    return Sel(SAFETY(), BREAK(p["def_aa"]),
               GUN(p["gun_ata"], 3000.0),
               A("Loop"))

def d1_reactive(p):
    return Sel(SAFETY(), BREAK(p["def_aa"]),
               GUN(p["gun_ata"], p["gun_range"]),
               A("Pursue"))

def d2_lastditch(p):
    return Sel(SAFETY(), Seq(C("InEnemyWEZ"), A("BreakTurn")),
               Seq(C("UnderThreat", aa_threshold_deg=p["def_aa"]), A("SpiralDive")),
               GUN(p["gun_ata"], 3000.0),
               A("Pursue"))

def d3_scissors(p):
    return Sel(SAFETY(), Seq(C("IsScissors"), A("ScissorsAccel")),
               Seq(C("IsMerged"), A("ScissorsAccel")),
               BREAK(p["def_aa"]),
               A("Pursue"))

def e1_ace(p):
    return Sel(SAFETY(), GUN(p["gun_ata"], p["gun_range"]),
               BREAK(p["def_aa"]),
               Seq(C("IsDefensiveSituation"), A("HighYoYo")),
               Seq(C("IsOffensiveSituation"),
                   C("DistanceBelow", threshold_ft=p["commit"]), A("LeadPursuit")),
               Seq(C("IsOffensiveSituation"), A("LagPursuit")),
               Seq(C("IsMerged"), A("OneCircleFight")),
               Seq(C("AltitudeBelow", min_altitude_ft=p.get("climb_alt", 11000.0)), A("ClimbingTurn")),
               A("Pursue"))

def e2_passive(p):
    act = p["act"]
    return Sel(SAFETY(), A(act))


# ── archetype → (빌더, 변주 축) ──────────────────────────────────────────
ARCH = {
    "A1_PurePursuer":   (a1_pure,     {"gun_range": [0, 1500, 2500, 3500], "gun_ata": [12, 18, 25]}),
    "A2_GunTracker":    (a2_guntracker, {"gun_ata": [10, 15, 20], "gun_range": [2000, 3000, 4500], "lead_ata": [40, 60]}),
    "A3_LagAngler":     (a3_lag,      {"gun_ata": [12, 18], "gun_range": [1500, 2500], "commit": [4000, 6500, 9000]}),
    "B1_EnergyFighter": (b1_energy,   {"def_aa": [110, 130], "climb_alt": [8000, 14000], "gun_ata": [12, 18, 25]}),
    "B2_Extender":      (b2_extend,   {"def_aa": [110, 130, 150], "commit": [4000, 6500, 9000]}),
    "C1_TwoCircleRate": (c1_tworate,  {"def_aa": [110, 130], "commit": [3000, 5000, 7000]}),
    "C2_OneCircleRad":  (c2_oneradius, {"def_aa": [110, 130], "commit": [3000, 5000, 7000]}),
    "C3_Lufbery":       (c3_lufbery,  {"def_aa": [110, 130, 150], "gun_ata": [12, 18, 25]}),
    "D1_Reactive":      (d1_reactive, {"def_aa": [100, 120, 140], "gun_ata": [12, 18], "gun_range": [2500, 3500]}),
    "D2_LastDitch":     (d2_lastditch, {"def_aa": [110, 130, 150], "gun_ata": [12, 18]}),
    "D3_Scissors":      (d3_scissors, {"def_aa": [110, 130, 150]}),
    "E1_AdaptiveAce":   (e1_ace,      {"gun_ata": [12, 15, 18], "gun_range": [2500, 3500], "def_aa": [110, 130], "commit": [5000, 8000]}),
    "E2_Passive":       (e2_passive,  {"act": ["Straight", "MaintainAltitude"]}),
}

MAX_VARIANTS = 12


def _variants(axes):
    keys = list(axes)
    return [dict(zip(keys, combo)) for combo in itertools.product(*(axes[k] for k in keys))]


def main():
    os.makedirs(OUT, exist_ok=True)
    # 기존 zoo 비우기 (재현)
    for f in os.listdir(OUT):
        if f.endswith(".yaml"):
            os.remove(os.path.join(OUT, f))

    total = 0
    summary = []
    for arch, (build, axes) in ARCH.items():
        seen, kept = set(), 0
        for i, p in enumerate(_variants(axes)):
            tree = build(p)
            key = yaml.safe_dump(tree, sort_keys=True)
            if key in seen:
                continue
            seen.add(key)
            name = f"{arch}_{kept:02d}"
            spec = {"name": name, "archetype": arch, "params": p, "tree": tree}
            with open(os.path.join(OUT, name + ".yaml"), "w", encoding="utf-8") as fh:
                yaml.safe_dump(spec, fh, sort_keys=False, allow_unicode=True)
            kept += 1
            total += 1
            if kept >= MAX_VARIANTS:
                break
        summary.append((arch, kept))

    print(f"=== 설계 적 풀 생성 완료 → {os.path.relpath(OUT)} ===")
    for arch, k in summary:
        print(f"  {arch:<18} {k} 변주")
    print(f"  총 {total}개 (+ 앵커 9: opponents/*.yaml)")


if __name__ == "__main__":
    main()
