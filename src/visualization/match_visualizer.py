"""
Match Visualizer - Custom Physics (JSBSim 정확 미러링)

custom physics로 JSBSim 위치/자세를 DF2에 정확히 전달.
시각 보정: thrust(엔진 불꽃) + pitch/roll/yaw(조종면 애니메이션)
DF2 전체 상태 로그.
"""
import math
import time
from typing import Optional

from .dogfight2_client import Dogfight2Client, get_local_ip
from src.simulation.envs.JSBSim.core.catalog import JsbsimCatalog as _prp


def _rpy_to_matrix_3x4(roll, pitch, yaw, x, y, z):
    """RPY (radians) + position -> Harfang column-major 3x4 matrix
    NEU -> Harfang: [N,E,U] -> [X=N, Y=U, Z=E]"""
    cr, sr = math.cos(roll), math.sin(roll)
    cp, sp = math.cos(pitch), math.sin(pitch)
    cy, sy = math.cos(yaw), math.sin(yaw)
    r00 = cy * cp
    r01 = cy * sp * sr - sy * cr
    r02 = cy * sp * cr + sy * sr
    r10 = sy * cp
    r11 = sy * sp * sr + cy * cr
    r12 = sy * sp * cr - cy * sr
    r20 = -sp
    r21 = cp * sr
    r22 = cp * cr
    return [r00,r20,r10, r01,r21,r11, r02,r22,r12, x,y,z]


class MatchVisualizer:

    def __init__(self, host=None, port=50888):
        if host is None:
            host = get_local_ip()
        self.client = Dogfight2Client(host, port)
        self.connected = False
        self._plane_map = {}
        self._plane_roles = {}
        self._initialized = False
        self._step_count = 0
        self._log_file = None
        self._df2_center = [0, 4572, 0]
        self._jsb_center = [0, 0, 4572]
        self._origins_set = False
        self._targets = {}       # {plane_id: {pos, rpy}}
        self._prev_targets = {}  # 이전 스텝 (보간용)

    def connect(self):
        if not self.client.connect():
            return False
        self.connected = True
        time.sleep(2)
        self.client.disable_log()
        self.client.set_client_update_mode(True)
        self.client.set_renderless_mode(False)
        return True

    def _spawn_in_air(self, plane1, plane2):
        c = self.client
        print(f"[MatchViz] Stabilizing...")
        for _ in range(30):
            c.update_scene()
            time.sleep(1/60)

        for pid in [plane1, plane2]:
            st = c.get_plane_state(pid)
            if st:
                print(f"[MatchViz] {pid}: alt={st.get('altitude',0):.0f}m "
                      f"spd={st.get('linear_speed',0):.0f}m/s "
                      f"hdg={st.get('heading',0):.0f}")

        # DF2 중심점 (ally_1 위치)
        s1 = c.get_plane_state(plane1)
        if s1:
            p = s1["position"]
            self._df2_center = [p[0], p[1], p[2]]

        # 타겟 설정
        c.set_target_id(plane1, plane2)
        c.set_target_id(plane2, plane1)

        # custom physics 전환
        c.set_machine_custom_physics_mode(plane1, True)
        c.set_machine_custom_physics_mode(plane2, True)

        # 현재 위치 유지
        for pid in [plane1, plane2]:
            st = c.get_plane_state(pid)
            if st:
                p = st["position"]
                c.update_machine_kinetics(pid, [1,0,0,0,1,0,0,0,1,p[0],p[1],p[2]], [0,0,0])
        c.update_scene()

        print(f"[MatchViz] Custom physics ON. DF2 center: "
              f"[{self._df2_center[0]:.0f},{self._df2_center[1]:.0f},{self._df2_center[2]:.0f}]")

    def initialize_planes(self, ego_id, enm_id):
        if not self.connected:
            return False

        planes = self.client.get_planes_list()
        if not planes or len(planes) < 2:
            print(f"[MatchViz] Not enough planes: {planes}")
            self.connected = False
            return False

        ally = [p for p in planes if 'ally' in p.lower()]
        enemy = [p for p in planes if 'ennemy' in p.lower() or 'enemy' in p.lower()]
        ego_plane = ally[0] if ally else planes[0]
        enm_plane = enemy[0] if enemy else planes[1]

        self._plane_map[ego_id] = ego_plane
        self._plane_map[enm_id] = enm_plane
        self._plane_roles[ego_plane] = "ALLY"
        self._plane_roles[enm_plane] = "ENEMY"

        for p in planes:
            self.client.reset_machine(p)

        self._spawn_in_air(ego_plane, enm_plane)

        # 로그 파일 (DF2 전체 상태)
        try:
            import os
            os.makedirs("logs", exist_ok=True)
            self._log_file = open("logs/df2_tracking.log", "w")
            self._log_file.write(
                "step,plane,role,"
                "jsb_n,jsb_e,jsb_u,jsb_roll,jsb_pitch,jsb_yaw,jsb_speed,"
                "hg_x,hg_y,hg_z,"
                "df2_alt,df2_hdg,df2_pitch,df2_roll,"
                "df2_linear_spd,df2_horiz_spd,df2_vert_spd,"
                "df2_thrust,df2_health,df2_crashed,df2_wreck,"
                "df2_tgt_dist,df2_tgt_locked,df2_tgt_angle\n")
        except Exception:
            self._log_file = None

        self._initialized = True
        print(f"[MatchViz] {ego_id}->{ego_plane}(ALLY), {enm_id}->{enm_plane}(ENEMY)")
        return True

    def update(self, env, step, max_steps, health1, health2,
               tree1_name="Blue", tree2_name="Red", debug_info=None):
        if not self._initialized:
            return

        c = self.client

        # 첫 스텝: JSBSim 중간점
        if not self._origins_set:
            positions = []
            for aid in self._plane_map:
                agent = env.agents.get(aid)
                if agent:
                    positions.append(agent.get_position())
            if len(positions) >= 2:
                self._jsb_center = [
                    (positions[0][0]+positions[1][0])/2,
                    (positions[0][1]+positions[1][1])/2,
                    (positions[0][2]+positions[1][2])/2,
                ]
            self._origins_set = True
            print(f"[MatchViz] JSBSim center: [{self._jsb_center[0]:.0f},"
                  f"{self._jsb_center[1]:.0f},{self._jsb_center[2]:.0f}]")

        # 재연결 시 custom physics 복원
        if c._reconnected:
            c._reconnected = False
            c.set_client_update_mode(True)
            c.set_renderless_mode(False)
            for pid in self._plane_map.values():
                c.set_machine_custom_physics_mode(pid, True)

        for agent_id, plane_id in self._plane_map.items():
            agent = env.agents.get(agent_id)
            if agent is None:
                continue

            # JSBSim 상태
            pos = agent.get_position()   # [N, E, U]
            vel = agent.get_velocity()   # [Vn, Ve, Vu]
            rpy = agent.get_rpy()        # [roll, pitch, yaw]
            jsb_speed = math.sqrt(vel[0]**2 + vel[1]**2 + vel[2]**2)

            # JSBSim → DF2 좌표 (NEU → HG: X=N, Y=U, Z=E)
            dn = pos[0] - self._jsb_center[0]
            de = pos[1] - self._jsb_center[1]
            du = pos[2] - self._jsb_center[2]
            hg_x = self._df2_center[0] + dn
            hg_y = self._df2_center[1] + du
            hg_z = self._df2_center[2] + de
            if hg_y < 50:
                hg_y = 50

            # 현재 목표 위치/자세 저장 (보간용)
            self._targets[plane_id] = {
                'pos': [hg_x, hg_y, hg_z],
                'rpy': [rpy[0], rpy[1], rpy[2]],
            }

            # 시각 보정: 엔진 불꽃 + 조종면 애니메이션
            try:
                throttle = float(agent.get_property_value(_prp.fcs_throttle_cmd_norm))
                aileron = float(agent.get_property_value(_prp.fcs_aileron_cmd_norm))
                elevator = float(agent.get_property_value(_prp.fcs_elevator_cmd_norm))
                rudder = float(agent.get_property_value(_prp.fcs_rudder_cmd_norm))
            except Exception:
                throttle, aileron, elevator, rudder = 0.8, 0, 0, 0

            c.set_plane_thrust(plane_id, throttle)

            # DF2 전체 상태 조회
            state = c.get_plane_state(plane_id)
            if state:
                df2_alt = state.get("altitude", 0)
                df2_hdg = state.get("heading", 0)
                df2_pitch = state.get("pitch_attitude", 0)
                df2_roll = state.get("roll_attitude", 0)
                df2_lspd = state.get("linear_speed", 0)
                df2_hspd = state.get("horizontal_speed", 0)
                df2_vspd = state.get("vertical_speed", 0)
                df2_thrust = state.get("thrust_level", 0)
                df2_health = state.get("health_level", 1)
                df2_crashed = state.get("crashed", False)
                df2_wreck = state.get("wreck", False)
                df2_tgt_angle = state.get("target_angle", 0)
                df2_tgt_locked = state.get("target_locked", False)
                df2_tgt_oor = state.get("target_out_of_range", False)
            else:
                df2_alt=df2_hdg=df2_pitch=df2_roll=0
                df2_lspd=df2_hspd=df2_vspd=df2_thrust=0
                df2_health=1;df2_crashed=df2_wreck=False
                df2_tgt_angle=0;df2_tgt_locked=False;df2_tgt_oor=False

            role = self._plane_roles.get(plane_id, "?")

            # 콘솔 로그
            if self._step_count < 3 or self._step_count % 100 == 0:
                print(f"[CP] step={self._step_count} {plane_id}({role}): "
                      f"JSB[r={math.degrees(rpy[0]):.0f} p={math.degrees(rpy[1]):.0f} "
                      f"alt={pos[2]:.0f} spd={jsb_speed:.0f}] "
                      f"DF2[r={df2_roll:.0f} p={df2_pitch:.0f} "
                      f"alt={df2_alt:.0f} spd={df2_lspd:.0f}]")

            # CSV 로그
            if self._log_file:
                self._log_file.write(
                    f"{self._step_count},{plane_id},{role},"
                    f"{pos[0]:.1f},{pos[1]:.1f},{pos[2]:.1f},"
                    f"{math.degrees(rpy[0]):.1f},{math.degrees(rpy[1]):.1f},{math.degrees(rpy[2]):.1f},"
                    f"{jsb_speed:.1f},"
                    f"{hg_x:.1f},{hg_y:.1f},{hg_z:.1f},"
                    f"{df2_alt:.1f},{df2_hdg:.1f},{df2_pitch:.1f},{df2_roll:.1f},"
                    f"{df2_lspd:.1f},{df2_hspd:.1f},{df2_vspd:.1f},"
                    f"{df2_thrust:.3f},{df2_health:.3f},{df2_crashed},{df2_wreck},"
                    f"{df2_tgt_angle:.1f},{df2_tgt_locked},{df2_tgt_oor}\n")

        # 기총 효과
        if debug_info:
            plane_list = list(self._plane_map.values())
            if len(plane_list) >= 2:
                if debug_info.get('in_wez1', False):
                    c.activate_machine_gun(plane_list[0])
                else:
                    c.deactivate_machine_gun(plane_list[0])
                if debug_info.get('in_wez2', False):
                    c.activate_machine_gun(plane_list[1])
                else:
                    c.deactivate_machine_gun(plane_list[1])

        # HUD
        c._send_command("DISPLAY_2DTEXT", {
            "position": [0.01, 0.02],
            "text": f"AI Combat 1v1 | Step {step}/{max_steps}",
            "size": 0.025,
            "color": [1.0, 0.9, 0.3, 1.0],
        })
        c._send_command("DISPLAY_2DTEXT", {
            "position": [0.01, 0.06],
            "text": f"[ALLY] {tree1_name}: {health1:.0f} HP",
            "size": 0.022,
            "color": [0.25, 1.0, 0.25, 1.0],
        })
        c._send_command("DISPLAY_2DTEXT", {
            "position": [0.01, 0.10],
            "text": f"[ENEMY] {tree2_name}: {health2:.0f} HP",
            "size": 0.022,
            "color": [1.0, 0.5, 0.5, 1.0],
        })

        # 보간 렌더링: JSBSim 0.2초를 12프레임(60fps)으로 부드럽게
        SUB_FRAMES = 12
        for f in range(SUB_FRAMES):
            t = (f + 1) / SUB_FRAMES  # 0.08 ~ 1.0

            for plane_id in self._plane_map.values():
                prev = self._prev_targets.get(plane_id)
                curr = self._targets.get(plane_id)
                if not prev or not curr:
                    if curr:
                        m = _rpy_to_matrix_3x4(*curr['rpy'], *curr['pos'])
                        c.update_machine_kinetics(plane_id, m, [0,0,0])
                    continue

                # 위치 선형 보간
                px = prev['pos'][0] + (curr['pos'][0] - prev['pos'][0]) * t
                py = prev['pos'][1] + (curr['pos'][1] - prev['pos'][1]) * t
                pz = prev['pos'][2] + (curr['pos'][2] - prev['pos'][2]) * t

                # 자세 선형 보간 (작은 각도에서 충분)
                rx = prev['rpy'][0] + (curr['rpy'][0] - prev['rpy'][0]) * t
                ry = prev['rpy'][1] + (curr['rpy'][1] - prev['rpy'][1]) * t
                rz = prev['rpy'][2] + (curr['rpy'][2] - prev['rpy'][2]) * t

                m = _rpy_to_matrix_3x4(rx, ry, rz, px, py, pz)
                c.update_machine_kinetics(plane_id, m, [0,0,0])

            c.update_scene()
            time.sleep(1/60)

        # 이전 값 저장
        for pid in self._plane_map.values():
            if pid in self._targets:
                self._prev_targets[pid] = self._targets[pid].copy()

        self._step_count += 1

    def update_from_env(self, env):
        self.update(env, self._step_count, 0, 100, 100)

    def display_hud_info(self, *args, **kwargs):
        pass

    def close(self):
        if self._log_file:
            self._log_file.flush()
            self._log_file.close()
            print(f"[MatchViz] Log: logs/df2_tracking.log")
        if self._initialized:
            for pid in self._plane_map.values():
                try:
                    self.client.set_machine_custom_physics_mode(pid, False)
                except Exception:
                    pass
        if self.connected:
            self.client.disconnect()
            self.connected = False
