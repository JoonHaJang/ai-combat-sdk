"""
Phase 1 메타데이터 수집 로거

목적: 다양한 BT 조합 × 상대 매치에서 전 스텝의 관측/행동/결과를 기록하고,
      매치 종료 후 승패 결과를 사이드카 JSON으로 저장하여 Phase 2 분석에 연결.

CSV 컬럼:
  - 기본: step, agent_id, bfm_situation
  - 기하학: distance_ft, ata_deg, aa_deg, hca_deg, relative_bearing_deg
  - 에너지: ego_altitude_ft, ego_vc_kts, specific_energy_ft, ps_fts,
            energy_diff_ft, closure_rate_kts, turn_rate_degs
  - 전술 상태: in_wez, enm_in_wez, in_39_line, overshoot_risk,
               energy_advantage, alt_advantage, spd_advantage, tc_type, side_flag
  - 체력: ego_health, enm_health, ego_damage_dealt, enm_damage_dealt
  - 행동: action_alt, action_hdg, action_vel, aileron, elevator, rudder, throttle
  - BT: active_node, reward

사이드카 JSON (_result.json):
  - winner, tree1_agent, tree2_agent, tree1_hp, tree2_hp, total_steps, csv_path
"""

import json
from pathlib import Path

# 수집할 observation 키 (obs 딕셔너리에서 직접 추출)
OBS_FIELDS = [
    "distance_ft", "ata_deg", "aa_deg", "hca_deg", "relative_bearing_deg",
    "ego_altitude_ft", "ego_vc_kts", "specific_energy_ft", "ps_fts",
    "energy_diff_ft", "closure_rate_kts", "turn_rate_degs",
    "in_wez", "enm_in_wez", "in_39_line", "overshoot_risk",
    "energy_advantage", "alt_advantage", "spd_advantage",
    "tc_type", "side_flag", "alt_gap_ft",
    # BUG-6 수정: ego_health/enm_health는 obs에서 읽으면 안됨.
    # obs는 양쪽 에이전트가 동일 값을 공유 (BFM 엔진 고정 관점).
    # runner.py가 전달하는 health dict(agent-specific)에서 별도 추출.
    # "ego_health", "enm_health", "ego_damage_dealt", "enm_damage_dealt",
    "tau_deg", "roll_deg", "pitch_deg",
]

# health dict에서 별도 추출할 필드 (runner.py step_callback의 health 파라미터)
HEALTH_FIELDS = ["ego_health", "enm_health", "ego_damage_dealt", "enm_damage_dealt"]

# [0,1] 정규화 → 실제 각도(°) 변환이 필요한 필드
ANGLE_SCALE_FIELDS = {"ata_deg", "aa_deg", "hca_deg", "relative_bearing_deg", "tau_deg"}

CSV_HEADER = (
    "step,agent_id,tree_name,bfm_situation,"
    + ",".join(OBS_FIELDS + HEALTH_FIELDS)
    + ",action_alt,action_hdg,action_vel,"
    "aileron,elevator,rudder,throttle,"
    "active_node,reward\n"
)


def create_metadata_logger(log_file: str, agent1_name: str = "", agent2_name: str = "",
                            silent: bool = True):
    """Phase 1 메타데이터 수집용 콜백 로거 생성.

    Returns:
        (step_callback, finalize) 튜플
        - step_callback: runner.py step_callback 인터페이스 호환
        - finalize(winner, tree1_hp, tree2_hp, total_steps):
            매치 종료 후 호출 → 사이드카 JSON 저장
    """
    log_path = Path(log_file)
    log_path.parent.mkdir(parents=True, exist_ok=True)

    with open(log_path, 'w', encoding='utf-8') as f:
        f.write(CSV_HEADER)

    # 스텝 카운터 + agent_id → tree_name 매핑
    state = {"steps_written": 0, "id_map": {}}

    def step_callback(step, agent_id, obs, action, low_level_action,
                      reward, health, active_nodes, bfm_situation):
        try:
            # agent_id → tree_name 매핑 (A* = tree1, B* = tree2)
            if agent_id not in state["id_map"]:
                agent_id_str = str(agent_id)
                if agent_id_str.startswith("A"):
                    state["id_map"][agent_id] = agent1_name
                elif agent_id_str.startswith("B"):
                    state["id_map"][agent_id] = agent2_name
                else:
                    # fallback: 처음 본 ID = tree1, 두 번째 = tree2
                    assigned = list(state["id_map"].values())
                    if agent1_name not in assigned:
                        state["id_map"][agent_id] = agent1_name
                    else:
                        state["id_map"][agent_id] = agent2_name
            tree_name = state["id_map"].get(agent_id, "")

            # bfm_situation 정규화: "BFMSituation.HABFM" → "HABFM"
            bfm_raw = str(bfm_situation) if bfm_situation else ""
            bfm_str = bfm_raw.split(".")[-1] if "." in bfm_raw else bfm_raw

            # 마지막 SUCCESS 노드 추출
            active_node = ""
            if active_nodes:
                success_nodes = [n for n, s in active_nodes if s == 'SUCCESS']
                active_node = success_nodes[-1] if success_nodes else ""

            # OBS 필드 직렬화
            obs_vals = []
            for key in OBS_FIELDS:
                val = obs.get(key, "")
                if isinstance(val, bool):
                    obs_vals.append(str(val))
                elif isinstance(val, (int, float)):
                    if key in ANGLE_SCALE_FIELDS:
                        val = val * 180.0  # [0,1] → 실제 도(°)
                    obs_vals.append(f"{val:.6f}")
                else:
                    obs_vals.append(str(val))

            # BUG-6 수정: health 필드는 runner의 agent-specific health dict에서 추출
            h_dict = health if isinstance(health, dict) else {}
            for key in HEALTH_FIELDS:
                if key == "ego_health":
                    val = h_dict.get("ego", obs.get("ego_health", ""))
                elif key == "enm_health":
                    val = h_dict.get("enm", obs.get("enm_health", ""))
                elif key == "ego_damage_dealt":
                    val = h_dict.get("ego_damage_dealt", obs.get("ego_damage_dealt", ""))
                elif key == "enm_damage_dealt":
                    val = h_dict.get("enm_damage_dealt", obs.get("enm_damage_dealt", ""))
                else:
                    val = obs.get(key, "")
                if isinstance(val, (int, float)):
                    obs_vals.append(f"{val:.6f}")
                else:
                    obs_vals.append(str(val))

            with open(log_path, 'a', encoding='utf-8') as f:
                f.write(
                    f"{step},{agent_id},{tree_name},{bfm_str},"
                    + ",".join(obs_vals)
                    + f",{action[0]},{action[1]},{action[2]},"
                    f"{low_level_action.get('aileron', 0):.4f},"
                    f"{low_level_action.get('elevator', 0):.4f},"
                    f"{low_level_action.get('rudder', 0):.4f},"
                    f"{low_level_action.get('throttle', 0):.4f},"
                    f'"{active_node}",{reward:.6f}\n'
                )
            state["steps_written"] += 1

        except Exception as e:
            if not silent:
                print(f"[metadata_logger] step={step}: {e}")

    def finalize(winner: str, tree1_hp: float = 100.0, tree2_hp: float = 100.0,
                 total_steps: int = 0):
        """매치 종료 후 결과를 사이드카 JSON으로 저장.

        파일명: <csv_stem>_result.json
        Phase 2 분석 시 CSV와 이 JSON을 파일명 prefix로 조인.
        """
        result = {
            "winner": winner,
            "tree1_agent": agent1_name,
            "tree2_agent": agent2_name,
            "tree1_hp": round(tree1_hp, 2),
            "tree2_hp": round(tree2_hp, 2),
            "total_steps": total_steps,
            "steps_recorded": state["steps_written"],
            "csv_path": str(log_path),
        }
        result_path = log_path.with_name(log_path.stem + "_result.json")
        with open(result_path, 'w', encoding='utf-8') as f:
            json.dump(result, f, indent=2, ensure_ascii=False)
        if not silent:
            print(f"[metadata_logger] result → {result_path.name}")

    return step_callback, finalize
