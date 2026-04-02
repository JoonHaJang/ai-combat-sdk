"""
Phase 1 메타데이터 수집 로거

목적: 다양한 BT 조합 × 상대 매치에서 전 스텝의 관측/행동/결과를 기록
수집 대상: 양측 에이전트의 관측값 + 행동 + 활성 노드 + BFM 상황

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
"""

from pathlib import Path

# 수집할 observation 키 (obs 딕셔너리에서 직접 추출)
OBS_FIELDS = [
    "distance_ft", "ata_deg", "aa_deg", "hca_deg", "relative_bearing_deg",
    "ego_altitude_ft", "ego_vc_kts", "specific_energy_ft", "ps_fts",
    "energy_diff_ft", "closure_rate_kts", "turn_rate_degs",
    "in_wez", "enm_in_wez", "in_39_line", "overshoot_risk",
    "energy_advantage", "alt_advantage", "spd_advantage",
    "tc_type", "side_flag", "alt_gap_ft",
    "ego_health", "enm_health", "ego_damage_dealt", "enm_damage_dealt",
    "tau_deg", "roll_deg", "pitch_deg",
]

CSV_HEADER = (
    "step,agent_id,bfm_situation,"
    + ",".join(OBS_FIELDS)
    + ",action_alt,action_hdg,action_vel,"
    "aileron,elevator,rudder,throttle,"
    "active_node,reward\n"
)


def create_metadata_logger(log_file: str, silent: bool = True):
    """Phase 1 메타데이터 수집용 콜백 로거 생성.

    Args:
        log_file: CSV 출력 경로
        silent: True면 콘솔 출력 없음 (대량 수집 시)
    """
    Path(log_file).parent.mkdir(parents=True, exist_ok=True)
    with open(log_file, 'w', encoding='utf-8') as f:
        f.write(CSV_HEADER)

    def metadata_callback(step, agent_id, obs, action, low_level_action,
                          reward, health, active_nodes, bfm_situation):
        try:
            bfm_str = str(bfm_situation) if bfm_situation else ""

            # Active node 추출
            active_node = ""
            if active_nodes:
                success_nodes = [n for n, s in active_nodes if s == 'SUCCESS']
                active_node = success_nodes[-1] if success_nodes else ""

            # Observation 필드 추출
            # 정규화된 각도 필드는 ×180 변환 (SDK가 [0,1] 범위로 정규화)
            ANGLE_SCALE_FIELDS = {"ata_deg", "aa_deg", "hca_deg",
                                  "relative_bearing_deg", "tau_deg"}
            obs_vals = []
            for key in OBS_FIELDS:
                val = obs.get(key, "")
                if isinstance(val, bool):
                    obs_vals.append(str(val))
                elif isinstance(val, (int, float)):
                    if key in ANGLE_SCALE_FIELDS:
                        val = val * 180.0  # 정규화 → 실제 각도
                    obs_vals.append(f"{val:.6f}")
                else:
                    obs_vals.append(str(val))

            # CSV 행 작성
            with open(log_file, 'a', encoding='utf-8') as f:
                f.write(
                    f"{step},{agent_id},{bfm_str},"
                    + ",".join(obs_vals)
                    + f",{action[0]},{action[1]},{action[2]},"
                    f"{low_level_action.get('aileron',0):.4f},"
                    f"{low_level_action.get('elevator',0):.4f},"
                    f"{low_level_action.get('rudder',0):.4f},"
                    f"{low_level_action.get('throttle',0):.4f},"
                    f'"{active_node}",{reward:.6f}\n'
                )

        except Exception as e:
            if not silent:
                print(f"[metadata_logger] step={step}: {e}")

    return metadata_callback
