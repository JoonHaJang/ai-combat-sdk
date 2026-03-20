"""
Dogfight 2 Client for AI Combat SDK
실시간 3D 시각화를 위한 Dogfight 2 네트워크 클라이언트

Protocol: dogfight-sandbox-hg2 network API
- JSON over TCP with 4-byte big-endian length header
- Port: 50888 (default)
- Host: Dogfight 2 server listens on the machine's network IP (socket.gethostbyname),
        NOT 127.0.0.1. Use get_local_ip() to auto-detect.
"""
import json
import socket
from typing import Optional, Dict, List
from .socket_lib import SocketConnection


def get_local_ip() -> str:
    """Dogfight 2 서버가 바인딩하는 IP 자동 감지 (socket.gethostbyname과 동일)"""
    return socket.gethostbyname(socket.gethostname())

# 응답을 반환하는 명령어 목록
COMMANDS_WITH_RESPONSE = {
    "GET_RUNNING", "GET_TIMESTEP", "GET_PLANESLIST", "GET_PLANE_STATE",
    "GET_PLANE_THRUST", "GET_HEALTH", "GET_TARGETS_LIST", "GET_TARGET_IDX",
    "GET_MACHINE_MISSILES_LIST", "GET_MISSILESDEVICE_SLOTS_STATE",
    "GET_MACHINE_GUN_STATE", "GET_MOBILE_PARTS_LIST",
    "GET_MACHINE_CUSTOM_PHYSICS_MODE",
    "GET_MISSILESLIST", "GET_MISSILE_STATE", "GET_MISSILE_TARGETS_LIST",
    "GET_MISSILE_LAUNCHERS_LIST", "GET_MISSILE_LAUNCHER_STATE",
    "IS_AUTOPILOT_ACTIVATED", "IS_IA_ACTIVATED", "IS_USER_CONTROL_ACTIVATED",
    "COMPUTE_NEXT_TIMESTEP_PHYSICS",
}


class Dogfight2Client:
    """Dogfight 2 네트워크 클라이언트

    dogfight-sandbox-hg2의 network_server.py와 통신하는 클라이언트.
    원본 dogfight_client.py / socket_lib.py 프로토콜과 동일.
    """

    def __init__(self, host: str = None, port: int = 50888):
        if host is None:
            host = get_local_ip()
        self.host = host
        self.port = port
        self.socket = SocketConnection()
        self.connected = False
        self.plane_ids = {}  # {agent_name: plane_id}
        self._error_count = 0
        self._reconnected = False

    def connect(self) -> bool:
        """Dogfight 2 서버에 연결"""
        try:
            success = self.socket.connect(self.host, self.port)
            if success:
                self.connected = True
                print(f"[Dogfight2] Connected: {self.host}:{self.port}")
                return True
            else:
                print(f"[Dogfight2] Connection failed: {self.socket.logger}")
                return False
        except Exception as e:
            print(f"[Dogfight2] Connection error: {e}")
            self.connected = False
            return False

    def disconnect(self):
        """연결 종료"""
        if self.socket:
            self.socket.close()
            self.connected = False
            print("[Dogfight2] Disconnected")

    def _send_command(self, command: str, args: Dict = None) -> Optional[Dict]:
        """명령어 전송 및 응답 수신"""
        if not self.connected:
            return None

        try:
            message = {"command": command, "args": args or {}}
            json_str = json.dumps(message)
            self.socket.send_message(json_str.encode('utf-8'))

            # 응답이 필요한 명령어인 경우
            if command in COMMANDS_WITH_RESPONSE:
                answer = self.socket.get_answer()
                if answer:
                    return json.loads(answer.decode('utf-8'))

            return None
        except (ConnectionResetError, BrokenPipeError, ConnectionAbortedError, OSError) as e:
            self._error_count += 1
            if self._error_count <= 3:
                print(f"[Dogfight2] Connection error ({command}): {e} - reconnecting...")
            # 재연결 시도
            try:
                self.socket.close()
                import time
                time.sleep(1)
                if self.socket.connect(self.host, self.port):
                    if self._error_count <= 3:
                        print(f"[Dogfight2] Reconnected!")
                    self._reconnected = True  # 재연결 플래그
                    return None
            except Exception:
                pass
            self.connected = False
            return None
        except Exception as e:
            self._error_count += 1
            if self._error_count <= 3:
                print(f"[Dogfight2] Command skip ({command}): {e}")
            return None

    # ========== Global Commands ==========

    def disable_log(self):
        self._send_command("DISABLE_LOG")

    def enable_log(self):
        self._send_command("ENABLE_LOG")

    def get_running(self) -> Optional[Dict]:
        return self._send_command("GET_RUNNING")

    def set_renderless_mode(self, flag: bool):
        self._send_command("SET_RENDERLESS_MODE", {"flag": flag})

    def set_client_update_mode(self, flag: bool):
        self._send_command("SET_CLIENT_UPDATE_MODE", {"flag": flag})

    def get_timestep(self) -> Optional[Dict]:
        return self._send_command("GET_TIMESTEP")

    def set_timestep(self, timestep: float):
        self._send_command("SET_TIMESTEP", {"timestep": timestep})

    def update_scene(self):
        self._send_command("UPDATE_SCENE")

    def display_2d_text(self, position: List[float], text: str, size: float, color: List[float]):
        self._send_command("DISPLAY_2DTEXT", {
            "position": position, "text": text, "size": size, "color": color
        })

    # ========== Aircraft Commands ==========

    def get_planes_list(self) -> List[str]:
        result = self._send_command("GET_PLANESLIST")
        return result if result else []

    def get_plane_state(self, plane_id: str) -> Optional[Dict]:
        return self._send_command("GET_PLANE_STATE", {"plane_id": plane_id})

    def get_plane_thrust(self, plane_id: str) -> Optional[Dict]:
        return self._send_command("GET_PLANE_THRUST", {"plane_id": plane_id})

    def set_plane_thrust(self, plane_id: str, level: float):
        self._send_command("SET_PLANE_THRUST", {"plane_id": plane_id, "thrust_level": level})

    def set_plane_pitch(self, plane_id: str, level: float):
        self._send_command("SET_PLANE_PITCH", {"plane_id": plane_id, "pitch_level": level})

    def set_plane_roll(self, plane_id: str, level: float):
        self._send_command("SET_PLANE_ROLL", {"plane_id": plane_id, "roll_level": level})

    def set_plane_yaw(self, plane_id: str, level: float):
        self._send_command("SET_PLANE_YAW", {"plane_id": plane_id, "yaw_level": level})

    def set_plane_brake(self, plane_id: str, level: float):
        self._send_command("SET_PLANE_BRAKE", {"plane_id": plane_id, "brake_level": level})

    def set_plane_flaps(self, plane_id: str, level: float):
        self._send_command("SET_PLANE_FLAPS", {"plane_id": plane_id, "flaps_level": level})

    def set_plane_linear_speed(self, plane_id: str, speed: float):
        self._send_command("SET_PLANE_LINEAR_SPEED", {"plane_id": plane_id, "linear_speed": speed})

    def stabilize_plane(self, plane_id: str):
        self._send_command("STABILIZE_PLANE", {"plane_id": plane_id})

    def deploy_gear(self, plane_id: str):
        self._send_command("DEPLOY_GEAR", {"plane_id": plane_id})

    def retract_gear(self, plane_id: str):
        self._send_command("RETRACT_GEAR", {"plane_id": plane_id})

    def activate_post_combustion(self, plane_id: str):
        self._send_command("ACTIVATE_PC", {"plane_id": plane_id})

    def deactivate_post_combustion(self, plane_id: str):
        self._send_command("DEACTIVATE_PC", {"plane_id": plane_id})

    def set_plane_autopilot_heading(self, plane_id: str, heading: float):
        self._send_command("SET_PLANE_AUTOPILOT_HEADING", {"plane_id": plane_id, "ap_heading": heading})

    def set_plane_autopilot_speed(self, plane_id: str, speed: float):
        self._send_command("SET_PLANE_AUTOPILOT_SPEED", {"plane_id": plane_id, "ap_speed": speed})

    def set_plane_autopilot_altitude(self, plane_id: str, altitude: float):
        self._send_command("SET_PLANE_AUTOPILOT_ALTITUDE", {"plane_id": plane_id, "ap_altitude": altitude})

    def activate_easy_steering(self, plane_id: str):
        self._send_command("ACTIVATE_EASY_STEERING", {"plane_id": plane_id})

    def deactivate_easy_steering(self, plane_id: str):
        self._send_command("DEACTIVATE_EASY_STEERING", {"plane_id": plane_id})

    def record_plane_start_state(self, plane_id: str):
        self._send_command("RECORD_PLANE_START_STATE", {"plane_id": plane_id})

    # ========== Machine Commands ==========

    def reset_machine(self, machine_id: str):
        self._send_command("RESET_MACHINE", {"machine_id": machine_id})

    def reset_machine_matrix(self, machine_id: str, position: List[float], rotation: List[float]):
        self._send_command("RESET_MACHINE_MATRIX", {
            "machine_id": machine_id, "position": position, "rotation": rotation
        })

    def get_health(self, machine_id: str) -> Optional[Dict]:
        return self._send_command("GET_HEALTH", {"machine_id": machine_id})

    def set_health(self, machine_id: str, level: float):
        self._send_command("SET_HEALTH", {"machine_id": machine_id, "health_level": level})

    def set_machine_custom_physics_mode(self, machine_id: str, flag: bool):
        self._send_command("SET_MACHINE_CUSTOM_PHYSICS_MODE", {
            "machine_id": machine_id, "flag": flag
        })

    def get_machine_custom_physics_mode(self, machine_id: str) -> Optional[Dict]:
        return self._send_command("GET_MACHINE_CUSTOM_PHYSICS_MODE", {"machine_id": machine_id})

    def update_machine_kinetics(self, machine_id: str, matrix_3_4: List[float], speed_vector: List[float]):
        self._send_command("UPDATE_MACHINE_KINETICS", {
            "machine_id": machine_id, "matrix": matrix_3_4, "v_move": speed_vector
        })

    def get_targets_list(self, machine_id: str) -> Optional[Dict]:
        return self._send_command("GET_TARGETS_LIST", {"machine_id": machine_id})

    def set_target_id(self, machine_id: str, target_id):
        self._send_command("SET_TARGET_ID", {"machine_id": machine_id, "target_id": target_id})

    def activate_IA(self, machine_id: str):
        self._send_command("ACTIVATE_IA", {"machine_id": machine_id})

    def deactivate_IA(self, machine_id: str):
        self._send_command("DEACTIVATE_IA", {"machine_id": machine_id})

    def activate_autopilot(self, machine_id: str):
        self._send_command("ACTIVATE_AUTOPILOT", {"machine_id": machine_id})

    def deactivate_autopilot(self, machine_id: str):
        self._send_command("DEACTIVATE_AUTOPILOT", {"machine_id": machine_id})

    # ========== Machine Gun Commands ==========

    def activate_machine_gun(self, machine_id: str):
        self._send_command("ACTIVATE_MACHINE_GUN", {"machine_id": machine_id})

    def deactivate_machine_gun(self, machine_id: str):
        self._send_command("DEACTIVATE_MACHINE_GUN", {"machine_id": machine_id})

    # ========== Missile Commands ==========

    def get_machine_missiles_list(self, machine_id: str):
        return self._send_command("GET_MACHINE_MISSILES_LIST", {"machine_id": machine_id})

    def fire_missile(self, machine_id: str, slot_id: int):
        self._send_command("FIRE_MISSILE", {"machine_id": machine_id, "slot_id": slot_id})

    def rearm_machine(self, machine_id: str):
        self._send_command("REARM_MACHINE", {"machine_id": machine_id})

    # ========== Helper Methods ==========

    def setup_for_visualization(self):
        """시각화를 위한 초기 설정 (connect 후 호출)"""
        self.disable_log()
        self.set_client_update_mode(True)
        self.set_renderless_mode(False)

    def initialize_planes(self, num_planes: int = 2) -> bool:
        """비행기 초기화 및 에이전트 매핑"""
        try:
            planes = self.get_planes_list()
            if not planes or len(planes) < num_planes:
                print(f"[Dogfight2] Not enough planes: {len(planes) if planes else 0}/{num_planes}")
                return False

            print(f"[Dogfight2] Available planes: {planes}")

            for i in range(num_planes):
                plane_id = planes[i]
                self.reset_machine(plane_id)
                self.set_plane_thrust(plane_id, 1.0)
                self.retract_gear(plane_id)
                agent_name = f"agent{i+1}"
                self.plane_ids[agent_name] = plane_id

            print(f"[Dogfight2] Initialized {num_planes} planes: {self.plane_ids}")
            return True
        except Exception as e:
            print(f"[Dogfight2] Plane init failed: {e}")
            return False

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.disconnect()
