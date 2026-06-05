"""R15-G4 (2026-05-29): sub-situation 분기 Z3 reachability + partition verification.

목적:
  1. 각 sub-situation trigger 영역이 비어있지 않은가? (reachable)
  2. 분기 우선순위가 정확한가? (disjointness 강제 후 if-then 안전 보장)
  3. bt_vs_bt 초기 상태 (dist=3300, ata=90, aa=90, pos_adv=0) 가 NeutralMerge 로 dispatch 되는가?
  4. tail_chase_us_attack/us_defend 초기 상태가 Off_TailChase / Defensive 로 dispatch 되는가?

근거:
  - cost_branch_selector.py 의 _detect_sub_situation() if-then 순서가 priority 결정.
  - Z3 LRA (linear real arithmetic) 로 조건의 SAT/UNSAT 검증.

산출: 각 property 의 PROVEN/FAIL 표시.
"""
from __future__ import annotations
import z3


def _make_vars():
    """sub-situation detector 의 입력 변수 (real-valued)."""
    return {
        "ata": z3.Real("ata"),       # |ata_deg| in [0, 180]
        "aa": z3.Real("aa"),         # |aa_deg| in [0, 180]
        "dist": z3.Real("dist"),     # ft, in [0, 30000]
        "pos_adv": z3.Real("pos_adv"),  # signed, in [-180, 180]
        "alt_gap": z3.Real("alt_gap"),  # signed ft
    }


def _physics_bounds(v):
    """관측값 물리적 bound."""
    return [
        v["ata"] >= 0, v["ata"] <= 180,
        v["aa"] >= 0, v["aa"] <= 180,
        v["dist"] >= 0, v["dist"] <= 30000,
        v["pos_adv"] >= -180, v["pos_adv"] <= 180,
        v["alt_gap"] >= -10000, v["alt_gap"] <= 10000,
    ]


def _sub_situation_conditions(v):
    """_detect_sub_situation 의 if-then 우선순위 그대로 모델링 (priority-aware)."""
    ata, aa, dist, pos_adv, alt_gap = (
        v["ata"], v["aa"], v["dist"], v["pos_adv"], v["alt_gap"]
    )
    # 1. HOM: aa > 150 AND ata < 30 AND dist > 2000
    hom_raw = z3.And(aa > 150, ata < 30, dist > 2000)
    # 2. Defensive 그룹: pos_adv < -90 AND dist < 5000
    defensive_grp = z3.And(pos_adv < -90, dist < 5000)
    # 2a. DefSpiral: defensive_grp AND dist < 2000 AND alt_gap < -500
    defspiral_raw = z3.And(defensive_grp, dist < 2000, alt_gap < -500)
    # 2b. Defensive: defensive_grp AND NOT DefSpiral
    defensive_raw = z3.And(defensive_grp, z3.Not(z3.And(dist < 2000, alt_gap < -500)))
    # 3. Offensive 그룹: pos_adv > 50 AND dist < 5000
    offensive_grp = z3.And(pos_adv > 50, dist < 5000)
    # 3a. Off_TailChase: offensive_grp AND ata < 25
    offtc_raw = z3.And(offensive_grp, ata < 25)
    # 3b. Off_Lag: offensive_grp AND 25 <= ata < 80
    offlag_raw = z3.And(offensive_grp, ata >= 25, ata < 80)
    # 4. NeutralMerge (R15-G2 NEW): |pos_adv| < 50 AND 2500 < dist < 5500
    #                                AND 60 < ata < 120 AND 60 < aa < 120
    neutralmerge_raw = z3.And(
        pos_adv > -50, pos_adv < 50,
        dist > 2500, dist < 5500,
        ata > 60, ata < 120,
        aa > 60, aa < 120,
    )
    # 5. Lufbery: 60 < aa < 120 AND 60 < ata < 120 AND dist < 4000
    lufbery_raw = z3.And(aa > 60, aa < 120, ata > 60, ata < 120, dist < 4000)

    # if-then priority 적용 (각 조건이 활성화되려면 상위 분기가 모두 비활성)
    hom = hom_raw
    defspiral = z3.And(z3.Not(hom), defspiral_raw)
    defensive = z3.And(z3.Not(hom), z3.Not(defspiral_raw), defensive_raw)
    offtc = z3.And(z3.Not(hom), z3.Not(defspiral), z3.Not(defensive), offtc_raw)
    offlag = z3.And(z3.Not(hom), z3.Not(defspiral), z3.Not(defensive),
                    z3.Not(offtc), offlag_raw)
    neutralmerge = z3.And(z3.Not(hom), z3.Not(defspiral), z3.Not(defensive),
                          z3.Not(offtc), z3.Not(offlag), neutralmerge_raw)
    lufbery = z3.And(z3.Not(hom), z3.Not(defspiral), z3.Not(defensive),
                     z3.Not(offtc), z3.Not(offlag), z3.Not(neutralmerge),
                     lufbery_raw)

    return {
        "HOM": hom,
        "DefSpiral": defspiral,
        "Defensive": defensive,
        "Off_TailChase": offtc,
        "Off_Lag": offlag,
        "NeutralMerge": neutralmerge,
        "Lufbery": lufbery,
    }


def prove_nonempty(name: str, cond, bounds, verbose=True) -> bool:
    """∃ state ∈ physics bounds: cond → 비어있지 않음."""
    s = z3.Solver()
    for b in bounds:
        s.add(b)
    s.add(cond)
    res = s.check()
    proven = (res == z3.sat)
    if verbose:
        if proven:
            m = s.model()
            print(f"  [P1-{name}] NON-EMPTY ✓  example ata={m[m.decls()[0]] if m.decls() else '?'} ...")
        else:
            print(f"  [P1-{name}] EMPTY (UNREACHABLE) ✗ — branch is dead code")
    return proven


def prove_disjoint(name_a, cond_a, name_b, cond_b, bounds, verbose=True) -> bool:
    """∄ state: cond_a ∧ cond_b (priority-aware if-then 에서 서로 배타적)."""
    s = z3.Solver()
    for b in bounds:
        s.add(b)
    s.add(z3.And(cond_a, cond_b))
    res = s.check()
    proven = (res == z3.unsat)
    if verbose:
        if proven:
            print(f"  [P2-{name_a}∩{name_b}] DISJOINT ✓")
        else:
            m = s.model()
            print(f"  [P2-{name_a}∩{name_b}] CONFLICT ✗ — overlap at: {m}")
    return proven


def check_state_dispatches_to(state: dict, target: str, conditions, verbose=True) -> bool:
    """특정 state (예: bt_vs_bt 초기) 가 target sub-situation 으로 dispatch?"""
    v = _make_vars()
    s = z3.Solver()
    for k, val in state.items():
        s.add(v[k] == val)
    cond = conditions[target]
    # rebuild conditions with our v
    actual_conds = _sub_situation_conditions(v)
    s.add(actual_conds[target])
    res = s.check()
    proven = (res == z3.sat)
    if verbose:
        if proven:
            print(f"  [P3] {state} → DISPATCH to {target} ✓")
        else:
            # 어느 sub-situation 으로 가는지 찾기
            for k, c in actual_conds.items():
                s2 = z3.Solver()
                for key, val in state.items():
                    s2.add(v[key] == val)
                s2.add(c)
                if s2.check() == z3.sat:
                    print(f"  [P3] {state} → DISPATCH to {k} (expected {target}) ✗")
                    return False
            print(f"  [P3] {state} → DISPATCH to Other (no sub-situation) (expected {target}) ✗")
    return proven


def main():
    print("=" * 70)
    print("R15-G4: Sub-situation dispatch Z3 verification")
    print("=" * 70)

    v = _make_vars()
    bounds = _physics_bounds(v)
    conds = _sub_situation_conditions(v)

    # P1: 각 sub-situation 의 trigger 영역 non-empty
    print("\n[Property 1] Non-emptiness (각 branch reachable):")
    all_p1 = True
    for name, cond in conds.items():
        if not prove_nonempty(name, cond, bounds):
            all_p1 = False

    # P2: priority-aware 분기끼리 disjoint (if-then 안전성)
    print("\n[Property 2] Disjointness (priority-aware if-then 안전):")
    names = list(conds.keys())
    all_p2 = True
    for i, a in enumerate(names):
        for b in names[i+1:]:
            if not prove_disjoint(a, conds[a], b, conds[b], bounds):
                all_p2 = False

    # P3: 시나리오 초기 state → 의도된 sub-situation 으로 dispatch
    print("\n[Property 3] Scenario initial → dispatch target:")
    # bt_vs_bt 초기: A south, B north 측면, dist 3300, perpendicular
    # ata ≈ 90, aa ≈ 90, pos_adv ≈ 0, alt_gap ≈ 0
    bt_vs_bt_init = {"ata": 90.0, "aa": 90.0, "dist": 3300.0,
                     "pos_adv": 0.0, "alt_gap": 0.0}
    check_state_dispatches_to(bt_vs_bt_init, "NeutralMerge", conds)

    # tail_chase_us_attack 초기: 우리 follower, 우리 nose 적 향함
    # ata ≈ 0, aa ≈ 180, pos_adv ≈ 180, dist ≈ 1830
    us_attack_init = {"ata": 0.0, "aa": 180.0, "dist": 1830.0,
                      "pos_adv": 180.0, "alt_gap": 0.0}
    check_state_dispatches_to(us_attack_init, "Off_TailChase", conds)

    # tail_chase_us_defend 초기: 우리 leader 적이 우리 뒤
    # 우리는 적이 우리 6시이고 우리 nose 적 반대 → ata ≈ 180, aa ≈ 0, pos_adv ≈ -180
    us_defend_init = {"ata": 180.0, "aa": 0.0, "dist": 1830.0,
                      "pos_adv": -180.0, "alt_gap": 0.0}
    check_state_dispatches_to(us_defend_init, "Defensive", conds)

    print("\n" + "=" * 70)
    print(f"P1 (non-empty): {'ALL PASS' if all_p1 else 'SOME FAIL'}")
    print(f"P2 (disjoint):  {'ALL PASS' if all_p2 else 'SOME FAIL'}")
    print("=" * 70)


if __name__ == "__main__":
    main()
