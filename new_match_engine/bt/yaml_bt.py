"""Generic .yaml BT 인터프리터 — legacy BT(795 opponent_pool + 174 archetype + ...)를
새 엔진에서 그대로 실행. 손 포팅 없이 ~970 적 자동 해금 → MC rollout coverage 확보.

★ 사용자 비전: new_engine 코드로 legacy 대체 + .yaml 호환.
구조: py_trees Selector/Sequence/Condition/Action 트리 → obs 기반 평가 → Tactic.
어휘: 조건 ~26종(거의 obs 직접), 액션 ~40종(내 Tactic 매핑). 미지원은 근사/PURE_PURSUIT.

usage:
    from yaml_bt import load_bt
    opp_fn = load_bt("examples/opponent_pool/L1_pure_barrelroll_fast.yaml")
    tactic = opp_fn(obs)   # obs = compute_obs(opp, us)
"""
from __future__ import annotations
import sys, os, math
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "control"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "engine"))
import yaml
from tactic import Tactic
from situation import Geom, is_offensive, is_defensive, is_neutral, _es_ft

_G_FT_S2 = 32.174       # 협조선회 turn-rate 계산용
_KT_TO_FPS = 1.68781

# ── Action 이름 → Tactic 매핑 (legacy 어휘 → 우리 Tactic) ───────────────────
_ACTION = {
    "ClimbTo": Tactic.CLIMB, "DescendTo": Tactic.LOW_YOYO,
    "GunAttack": Tactic.GUN_TRACK,
    "Pursue": Tactic.PURE_PURSUIT, "PurePursuit": Tactic.PURE_PURSUIT,
    "LagPursuit": Tactic.LAG_PURSUIT, "LeadPursuit": Tactic.LEAD_PURSUIT,
    "BreakTurn": Tactic.BREAK_TURN, "DefensiveManeuver": Tactic.BREAK_TURN,
    "DefensiveSpiral": Tactic.BREAK_TURN, "Evade": Tactic.BREAK_TURN,
    "SliceTurn": Tactic.BREAK_TURN, "DescendingTurn": Tactic.LOW_YOYO,
    "HighYoYo": Tactic.HIGH_YOYO, "LowYoYo": Tactic.LOW_YOYO,
    "ClimbingTurn": Tactic.HIGH_YOYO, "ReengageClimb": Tactic.HIGH_YOYO,
    "AltitudeAdvantage": Tactic.HIGH_YOYO, "EnergyFight": Tactic.HIGH_YOYO,
    "SpiralClimb": Tactic.HIGH_YOYO, "Loop": Tactic.HIGH_YOYO,
    "ImmelmannTurn": Tactic.HIGH_YOYO, "HammerHead": Tactic.HIGH_YOYO,
    "OneCircleFight": Tactic.ONE_CIRCLE, "TwoCircleFight": Tactic.TWO_CIRCLE,
    "TCFight": Tactic.TWO_CIRCLE, "TurnLeft": Tactic.ONE_CIRCLE,
    "TurnRight": Tactic.ONE_CIRCLE, "BarrelRoll": Tactic.LAG_DISPLACEMENT_ROLL,
    "ScissorsAccel": Tactic.SCISSORS,
    "Straight": Tactic.LEVEL_FLIGHT, "MaintainAltitude": Tactic.LEVEL_FLIGHT,
    "Accelerate": Tactic.EXTENSION, "Decelerate": Tactic.LAG_PURSUIT,
    "SplitS": Tactic.LOW_YOYO, "SpiralDive": Tactic.LOW_YOYO,
    "OvershootAvoidance": Tactic.HIGH_YOYO,   # 오버슈트 회피 = 수직 yoyo 로 closure 제거
}


def _cond(name: str, params: dict, o) -> bool:
    """Condition 이름 + params → obs 평가 (legacy 어휘)."""
    p = params or {}
    g = None
    def G():
        nonlocal g
        if g is None: g = Geom(o)
        return g
    if name == "BelowHardDeck":   return o.ego_alt_ft < p.get("threshold_ft", 1000.0)
    if name == "DistanceBelow":   return o.distance_ft < p.get("threshold_ft", 3000.0)
    if name == "DistanceAbove":   return o.distance_ft > p.get("threshold_ft", 3000.0)
    if name == "ATABelow":        return o.ata_deg < p.get("threshold_deg", 30.0)
    if name == "ATAAbove":        return o.ata_deg > p.get("threshold_deg", 30.0)
    if name in ("EnemyInRange",): return o.distance_ft < p.get("max_distance_ft", 6562.0)
    if name == "AltitudeBelow":   return o.ego_alt_ft < p.get("min_altitude_ft", 5000.0)
    if name == "AltitudeAbove":   return o.ego_alt_ft > p.get("max_altitude_ft", 20000.0)
    if name == "UnderThreat":     return o.aa_deg > p.get("aa_threshold_deg", 120.0)
    if name == "VelocityBelow":   return o.ego_vc_kts < p.get("threshold_kts", 250.0)
    if name == "ClosureRateAbove":return o.closure_kts > p.get("threshold_kts", 30.0)
    if name == "InEnemyWEZ":      return o.aa_deg > 150.0 and o.distance_ft < 3000.0
    if name == "IsOffensiveSituation": return is_offensive(G())
    if name == "IsDefensiveSituation": return is_defensive(G())
    if name == "IsNeutralSituation":   return is_neutral(G())
    if name == "IsEnergyAdvantage":
        return _es_ft(o.ego_alt_ft, o.ego_vc_kts) > _es_ft(o.enm_alt_ft, o.enm_vc_kts) + 200.0
    if name == "SpecificEnergyAbove":
        return _es_ft(o.ego_alt_ft, o.ego_vc_kts) > p.get("threshold_ft", 18000.0)
    if name in ("IsAltAdvantage",):    return o.alt_gap_ft > 200.0
    if name == "IsMerged":             return o.distance_ft < 2000.0
    if name == "IsOvershootRisk":      return o.closure_kts > 80.0 and o.distance_ft < 3000.0
    if name == "IsNearOffensive":      return o.advantage > 0.1
    if name == "IsDisengaging":        return o.closure_kts < -50.0
    if name == "IsOneCircle":          return G().hca < 60.0
    if name == "IsTwoCircle":          return G().hca > 120.0
    if name == "IsScissors":           return 60 < o.aa_deg < 120 and o.distance_ft < 3000.0
    if name == "EnergyHighPs":         return o.ego_vc_kts > 350.0
    # ── bt-editor 정합 추가 (2026-06-05): 편집기 어휘 100% 커버 ──
    if name == "ClosureRateBelow": return o.closure_kts < p.get("threshold_kts", 0.0)
    if name == "VelocityAbove":    return o.ego_vc_kts > p.get("min_velocity_kts", 389.0)
    if name == "EnergyDiffAbove":
        return (_es_ft(o.ego_alt_ft, o.ego_vc_kts) - _es_ft(o.enm_alt_ft, o.enm_vc_kts)
                > p.get("threshold_ft", 1640.0))
    if name == "Is39Line":         return G().in_39                 # 적 후방반구(aa<90)
    if name == "IsSpdAdvantage":   return o.ego_vc_kts > o.enm_vc_kts + 10.0
    if name == "IsTargetInSight":  return o.ata_deg < 45.0          # 전방 시계 내
    if name == "LOSAbove":         return abs(o.rel_b_deg) > p.get("threshold_deg", 15.0)
    if name == "LOSBelow":         return abs(o.rel_b_deg) < p.get("threshold_deg", 15.0)
    if name == "TurnRateAbove":
        v_fps = max(o.ego_vc_kts * _KT_TO_FPS, 1.0)
        tr = abs(math.degrees(_G_FT_S2 * math.tan(math.radians(o.ego_phi_deg)) / v_fps))
        return tr > p.get("threshold_degs", 5.0)
    return False    # 미지원 조건 → 통과 안 함 (다음 branch 로)


def _walk(node, o):
    """py_trees 트리 walk → (Tactic|None, [성공경로 노드명]).

    ★ D2b 연착륙: legacy active_node/active_nodes_path 재현을 위해 성공 branch 의 노드명
      경로를 함께 반환. 실패(None) branch 는 경로 미오염.
    """
    t = node.get("type")
    nm = node.get("name", "")
    if t == "Selector":
        for c in node.get("children", []):
            r, path = _walk(c, o)
            if r is not None:
                return r, ([nm] + path if nm else path)   # 첫 성공 branch
        return None, []
    if t == "Sequence":
        action, subpath = None, []
        for c in node.get("children", []):
            ct = c.get("type")
            if ct == "Condition":
                if not _cond(c.get("name"), c.get("params"), o):
                    return None, []          # 조건 실패 → sequence 실패
            elif ct == "Action":
                action = _ACTION.get(c.get("name"), Tactic.PURE_PURSUIT)
                subpath = [c.get("name", "")]
            elif ct in ("Selector", "Sequence", "Parallel"):
                r, p = _walk(c, o)
                if r is None:
                    return None, []
                action, subpath = r, p
        if action is None:
            return None, []
        return action, ([nm] + subpath if nm else subpath)
    if t == "Parallel":
        for c in node.get("children", []):   # SuccessOnOne 근사 — 첫 액션
            r, p = _walk(c, o)
            if r is not None:
                return r, ([nm] + p if nm else p)
        return None, []
    if t == "Action":
        return _ACTION.get(node.get("name"), Tactic.PURE_PURSUIT), [node.get("name", "")]
    if t == "Condition":
        return (Tactic.LEVEL_FLIGHT, [nm]) if _cond(node.get("name"), node.get("params"), o) else (None, [])
    return None, []


def load_bt(yaml_path: str):
    """yaml BT 파일 → opp_fn(obs) → Tactic. (obs = compute_obs(opp, us)).

    opp_fn 은 호출마다 `last_node`(선택된 말단 Action명)·`last_path`(성공경로 ">" 연결)를
    갱신 — legacy active_node/active_nodes_path 충실 재현(D2b).
    """
    with open(yaml_path, "r", encoding="utf-8") as f:
        spec = yaml.safe_load(f)
    tree = spec["tree"]

    def opp_fn(o):
        tac, path = _walk(tree, o)
        if tac is None:
            tac, path = Tactic.PURE_PURSUIT, ["<default>"]    # 기본값
        path = [p for p in path if p]
        opp_fn.last_node = path[-1] if path else ""
        opp_fn.last_path = ">".join(path)
        return tac

    opp_fn.bt_name = spec.get("name", os.path.basename(yaml_path))
    opp_fn.last_node = ""
    opp_fn.last_path = ""
    return opp_fn


if __name__ == "__main__":
    # sanity — 몇 개 로드 + 상황별 출력
    from scenarios import SITUATIONS
    from obs import compute_obs
    PROOT = os.path.join(os.path.dirname(__file__), "..", "..")
    tests = [
        "examples/opponent_pool/L1_pure_barrelroll_fast.yaml",
        "examples/opponent_pool/L2_DefensiveSituation_BreakTurn_Pursue.yaml",
        "examples/ace.yaml",
    ]
    print("yaml BT 인터프리터 sanity — 상황별 tactic:")
    print(f"{'bt':<45}" + "".join(f"{s:>13}" for s in SITUATIONS))
    for rel in tests:
        fn = load_bt(os.path.join(PROOT, rel))
        cells = []
        for s, sp in SITUATIONS.items():
            p1, p2 = sp(); o21 = compute_obs(p2, p1)
            cells.append(fn(o21).name)
        print(f"{fn.bt_name:<45}" + "".join(f"{c:>13}" for c in cells))
