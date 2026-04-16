"""
bt_templates.py — BT YAML dict 생성 템플릿 함수 모음

`bt_optimizer_v3.py` 에서 추출됨 (2026-04-16 정리).
`generate_agents.py` 및 기타 툴이 공유하는 BT 구조 빌더.

Usage:
    from tools.bt_templates import generate_bt_yaml
    bt = generate_bt_yaml(params_dict)
"""


def generate_bt_yaml(params):
    """Convert parameter dict -> BT YAML dict.

    alpha1 계열 BT의 공통 템플릿. 21개 파라미터를 받아 YAML dict 반환.
    파라미터 키는 generate_agents.py의 AGENT_PROFILES 참조.

    구조 (선택적 분기는 params["include_*"] 플래그로):
      1. HardDeckAvoidance (필수)
      2. GunEngagement (필수)
      3. ThreatResponse (optional)
      4. OffensivePress (optional)
      5. EmergencyDefense (optional)
      6. CloseCombat (필수)
      7. DefensiveEvasion (optional)
      8. Default (Parallel with altitude or single action)
    """
    children = []

    # 1. Hard Deck Avoidance (always)
    children.append({
        "type": "Sequence", "name": "HardDeckAvoidance",
        "children": [
            {"type": "Condition", "name": "BelowHardDeck",
             "params": {"threshold_ft": int(params["hard_deck_threshold"])}},
            {"type": "Action", "name": "ClimbTo",
             "params": {"target_altitude_ft": int(params["climb_target"])}},
        ]
    })

    # 2. Gun WEZ Engagement (always)
    children.append({
        "type": "Sequence", "name": "GunEngagement",
        "children": [
            {"type": "Condition", "name": "DistanceBelow", "params": {"threshold_ft": 914}},
            {"type": "Condition", "name": "DistanceAbove", "params": {"threshold_ft": 152}},
            {"type": "Condition", "name": "ATABelow",
             "params": {"threshold_deg": round(float(params["wez_ata_threshold"]), 1)}},
            {"type": "Action", "name": "GunAttack"},
        ]
    })

    # 3. InEnemyWEZ → BreakTurn (optional)
    if params.get("include_enemy_wez", False):
        children.append({
            "type": "Sequence", "name": "ThreatResponse",
            "children": [
                {"type": "Condition", "name": "InEnemyWEZ",
                 "params": {
                     "max_distance_ft": round(float(params["enemy_wez_distance"]), 0),
                     "max_los_angle_deg": round(float(params["enemy_wez_los"]), 1),
                 }},
                {"type": "Action", "name": "BreakTurn"},
            ]
        })

    # 4. OffensivePress (optional)
    if params.get("include_offensive_press", False):
        children.append({
            "type": "Sequence", "name": "OffensivePress",
            "children": [
                {"type": "Condition", "name": "DistanceBelow",
                 "params": {"threshold_ft": int(params["offensive_press_distance"])}},
                {"type": "Condition", "name": "IsOffensiveSituation"},
                {"type": "Action", "name": params.get("offensive_press_action", "LeadPursuit")},
            ]
        })

    # 5. Emergency Defense (optional)
    if params.get("include_emergency_defense", False):
        children.append({
            "type": "Sequence", "name": "EmergencyDefense",
            "children": [
                {"type": "Condition", "name": "UnderThreat",
                 "params": {"aa_threshold_deg": float(params["threat_aa_threshold"])}},
                {"type": "Condition", "name": "DistanceBelow",
                 "params": {"threshold_ft": int(params["threat_distance"])}},
                {"type": "Action", "name": params["defense_action"]},
            ]
        })

    # 6. Close Combat (always)
    children.append({
        "type": "Sequence", "name": "CloseCombat",
        "children": [
            {"type": "Condition", "name": "DistanceBelow",
             "params": {"threshold_ft": int(params["close_combat_distance"])}},
            {"type": "Action", "name": params["close_action"]},
        ]
    })

    # 7. IsDefensiveSituation (optional)
    if params.get("include_is_defensive", False):
        children.append({
            "type": "Sequence", "name": "DefensiveEvasion",
            "children": [
                {"type": "Condition", "name": "IsDefensiveSituation"},
                {"type": "Action", "name": params.get("is_defensive_action", "BarrelRoll")},
            ]
        })

    # 8. Default action
    if params.get("include_altitude_far", False):
        children.append({
            "type": "Parallel", "name": "FarPursuitWithAltitude",
            "policy": "SuccessOnOne",
            "children": [
                {"type": "Action", "name": params["default_action"]},
                {"type": "Action", "name": "AltitudeAdvantage",
                 "params": {"target_advantage_ft": int(params["altitude_advantage_target"])}},
            ]
        })
    else:
        children.append({"type": "Action", "name": params["default_action"]})

    return {
        "name": "alpha1", "version": "opt_v3",
        "description": "Parameter-driven BT (alpha1 template)",
        "tree": {"type": "Selector", "children": children}
    }
