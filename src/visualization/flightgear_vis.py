"""
FlightGear Real-Time Visualizer

Implements FlightGear's NET_FDM binary protocol (version 24) directly via UDP.
Reads state from LAG JSBSim agents each step and streams to two FlightGear instances.

No set_output_directive needed — bypasses JSBSim's output system entirely.

Usage:
    fg = FlightGearVis()
    fg.connect()               # open UDP sockets
    # in match loop:
    fg.send_state(env)         # stream current state to FlightGear
    fg.pace(target_dt=0.2)     # real-time pacing
    fg.close()
"""

import math
import socket
import struct
import time
import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

# FlightGear NET_FDM struct format (version 24, big-endian / network byte order)
# Matches FlightGear src/Network/net_fdm.hxx
_FG_MAX_ENGINES = 4
_FG_MAX_TANKS   = 4
_FG_MAX_WHEELS  = 3

_NET_FDM_FMT = (
    '!'       # network (big-endian)
    'II'      # version, padding
    'ddd'     # longitude (rad), latitude (rad), altitude (m)
    'f'       # agl (m)
    'fff'     # phi (roll), theta (pitch), psi (yaw)  — radians
    'ff'      # alpha, beta
    'fff'     # phidot, thetadot, psidot
    'ff'      # vcas (kts), climb_rate (fps)
    'fff'     # v_north, v_east, v_down  (fps)
    'fff'     # v_body_u, v_body_v, v_body_w (fps)
    'fff'     # A_X_pilot, A_Y_pilot, A_Z_pilot (g)
    'ff'      # stall_warning, slip_deg
    'I'       # num_engines
    '4I'      # eng_state[4]
    '4f'      # rpm[4]
    '4f'      # fuel_flow[4]
    '4f'      # fuel_px[4]
    '4f'      # egt[4]
    '4f'      # cht[4]
    '4f'      # mp_osi[4]
    '4f'      # tit[4]
    '4f'      # oil_temp[4]
    '4f'      # oil_px[4]
    'I'       # num_tanks
    '4f'      # fuel_quantity[4]
    'I'       # num_wheels
    '3f'      # wow[3]
    '3f'      # gear_pos[3]
    '3f'      # gear_steer[3]
    '3f'      # gear_compression[3]
    'fff'     # cur_time, warp, visibility
    'ff'      # elevator, elevator_trim_tab
    'ff'      # left_flap, right_flap
    'ff'      # left_aileron, right_aileron
    'ff'      # rudder, nose_wheel
    'ff'      # speedbrake, spoilers
)
_NET_FDM_SIZE = struct.calcsize(_NET_FDM_FMT)


def _build_net_fdm(lat_deg: float, lon_deg: float, alt_m: float,
                   roll_rad: float, pitch_rad: float, yaw_rad: float,
                   vn_mps: float = 0.0, ve_mps: float = 0.0, vu_mps: float = 0.0,
                   sim_time: float = 0.0) -> bytes:
    """
    Pack a minimal but valid NET_FDM packet for FlightGear.

    Args:
        lat_deg, lon_deg: geodetic position in degrees
        alt_m:            altitude above MSL in meters
        roll_rad, pitch_rad, yaw_rad: body attitude in radians
        vn_mps, ve_mps, vu_mps: velocity NED (m/s); vu is up, will be negated to down
        sim_time: simulation time (seconds)
    """
    lat_rad = math.radians(lat_deg)
    lon_rad = math.radians(lon_deg)

    # Convert m/s → ft/s for v_north, v_east, v_down
    fps = 3.28084
    v_north_fps = vn_mps * fps
    v_east_fps  = ve_mps * fps
    v_down_fps  = -vu_mps * fps    # vu is "up", FG wants "down"

    vcas_kts   = math.sqrt(vn_mps**2 + ve_mps**2 + vu_mps**2) * 1.94384
    climb_fps  = vu_mps * fps

    packet = struct.pack(
        _NET_FDM_FMT,
        24, 0,                          # version=24, padding
        lon_rad, lat_rad, alt_m,        # position
        0.0,                            # agl
        roll_rad, pitch_rad, yaw_rad,   # attitude
        0.0, 0.0,                       # alpha, beta
        0.0, 0.0, 0.0,                  # phidot, thetadot, psidot
        vcas_kts, climb_fps,            # vcas, climb_rate
        v_north_fps, v_east_fps, v_down_fps,  # v_north, v_east, v_down
        0.0, 0.0, 0.0,                  # v_body_u/v/w
        0.0, 0.0, 0.0,                  # A_X/Y/Z_pilot
        0.0, 0.0,                       # stall_warning, slip_deg
        1,                              # num_engines
        1, 0, 0, 0,                     # eng_state[4]  (1=running)
        *([3000.0] + [0.0]*3),          # rpm[4]
        *([0.0]*4),                     # fuel_flow[4]
        *([0.0]*4),                     # fuel_px[4]
        *([600.0]*4),                   # egt[4]
        *([200.0]*4),                   # cht[4]
        *([0.0]*4),                     # mp_osi[4]
        *([0.0]*4),                     # tit[4]
        *([80.0]*4),                    # oil_temp[4]
        *([50.0]*4),                    # oil_px[4]
        1,                              # num_tanks
        *([0.5] + [0.0]*3),            # fuel_quantity[4]
        3,                              # num_wheels
        *([0.0]*3),                     # wow[3]
        *([0.0]*3),                     # gear_pos[3]  (gear up)
        *([0.0]*3),                     # gear_steer[3]
        *([0.0]*3),                     # gear_compression[3]
        float(sim_time), 0.0, 10000.0,  # cur_time, warp, visibility
        0.0, 0.0,                       # elevator, elevator_trim_tab
        0.0, 0.0,                       # left_flap, right_flap
        0.0, 0.0,                       # left_aileron, right_aileron
        0.0, 0.0,                       # rudder, nose_wheel
        0.0, 0.0,                       # speedbrake, spoilers
    )
    return packet


class FlightGearVis:
    """
    Streams aircraft state to two FlightGear instances via UDP NET_FDM protocol.

    FlightGear must be started with:
        fgfs --fdm=null --native-fdm=socket,in,60,,5550,udp --aircraft=f16
        fgfs --fdm=null --native-fdm=socket,in,60,,5551,udp --aircraft=f16
    """

    def __init__(
        self,
        fg1_port: int = 5550,
        fg2_port: int = 5551,
        fg_host: str = "127.0.0.1",
        tacview_host: str = "127.0.0.1",
        tacview_port: int = 42674,
    ):
        self.fg_host = fg_host
        self.fg1_port = fg1_port
        self.fg2_port = fg2_port
        self.tacview_host = tacview_host
        self.tacview_port = tacview_port

        self._sock: socket.socket | None = None
        self._tacview_sock: socket.socket | None = None
        self._last_step_time: float | None = None
        self._ego_id = None
        self._enm_id = None
        self._start_time = time.time()

    # ------------------------------------------------------------------
    # Setup
    # ------------------------------------------------------------------

    def connect(self) -> bool:
        """Open UDP socket for FlightGear streaming."""
        try:
            self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            print(f"[FlightGear] UDP ready → {self.fg_host}:{self.fg1_port} (Blue) "
                  f"and {self.fg_host}:{self.fg2_port} (Red)")
            print(f"[FlightGear] NET_FDM packet size: {_NET_FDM_SIZE} bytes")
            return True
        except Exception as e:
            logger.error("[FlightGear] socket error: %s", e)
            return False

    def setup(self, env, data_path: str = "") -> bool:
        """
        Setup called after env.reset(). Stores agent IDs and opens socket.
        data_path is ignored (kept for API compatibility).
        """
        self._ego_id = env.ego_ids[0]
        self._enm_id = env.enm_ids[0]
        return self.connect()

    # ------------------------------------------------------------------
    # Per-step streaming
    # ------------------------------------------------------------------

    def send_state(self, env, sim_time: float = 0.0):
        """
        Read current state from env agents and send NET_FDM packets to FlightGear.
        Call once per match step.
        """
        if self._sock is None:
            return

        elapsed = time.time() - self._start_time

        for agent_id, port in [(self._ego_id, self.fg1_port),
                               (self._enm_id, self.fg2_port)]:
            if agent_id is None:
                continue
            agent = env.agents.get(agent_id)
            if agent is None:
                continue
            try:
                lon, lat, alt = agent.get_geodetic()   # lon[deg], lat[deg], alt[m]
                roll, pitch, yaw = agent.get_rpy()     # radians
                vn, ve, vu = agent.get_velocity()      # m/s (north, east, up)

                pkt = _build_net_fdm(
                    lat_deg=lat, lon_deg=lon, alt_m=alt,
                    roll_rad=roll, pitch_rad=pitch, yaw_rad=yaw,
                    vn_mps=vn, ve_mps=ve, vu_mps=vu,
                    sim_time=elapsed,
                )
                self._sock.sendto(pkt, (self.fg_host, port))
            except Exception as e:
                logger.debug("[FlightGear] send error agent %s: %s", agent_id, e)

    # ------------------------------------------------------------------
    # Tacview real-time streaming (optional)
    # ------------------------------------------------------------------

    def connect_tacview(self) -> bool:
        """
        TCP server for Tacview real-time telemetry (LAG protocol).
        Tacview connects to us, we send handshake then ACMI header.
        """
        try:
            server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            server.bind(("0.0.0.0", self.tacview_port))
            server.listen(5)
            server.settimeout(30.0)
            print(f"[Tacview] Listening on port {self.tacview_port} — connect from Tacview now")
            conn, addr = server.accept()
            server.close()
            self._tacview_sock = conn

            # Tacview handshake (required before ACMI data)
            handshake = "XtraLib.Stream.0\nTacview.RealTimeTelemetry.0\nHostUsername\n\x00"
            self._tacview_sock.send(handshake.encode())
            self._tacview_sock.recv(1024)  # receive client handshake response

            # ACMI header + object definitions
            ego_id = self._ego_id or "1"
            enm_id = self._enm_id or "2"
            header = (
                "FileType=text/acmi/tacview\n"
                "FileVersion=2.1\n"
                "0,ReferenceTime=2020-04-01T00:00:00Z\n"
                "#0.00\n"
                f"{ego_id},Name=F-16C,CallSign=Blue,Coalition=Allies,Color=Blue,Type=Air+FixedWing\n"
                f"{enm_id},Name=F-16C,CallSign=Red,Coalition=Enemies,Color=Red,Type=Air+FixedWing\n"
            )
            self._tacview_sock.send(header.encode())
            print(f"[Tacview] Connected from {addr} — streaming ACMI")
            return True
        except Exception as e:
            print(f"[Tacview] Server error (continuing without): {e}")
            self._tacview_sock = None
            return False

    def stream_step(self, env, sim_time: float):
        """Send ACMI position update to Tacview."""
        if self._tacview_sock is None:
            return
        lines = [f"#{sim_time:.2f}\n"]
        for agent_id in [self._ego_id, self._enm_id]:
            if agent_id is None:
                continue
            agent = env.agents.get(agent_id)
            if agent is None:
                continue
            try:
                lon, lat, alt = agent.get_geodetic()
                roll, pitch, yaw = agent.get_rpy()
                lines.append(
                    f"{agent_id},T={lon:.6f}|{lat:.6f}|{alt:.1f}"
                    f"|{math.degrees(roll):.2f}|{math.degrees(pitch):.2f}"
                    f"|{math.degrees(yaw):.2f}\n"
                )
            except Exception as e:
                logger.debug("[Tacview] state error agent %s: %s", agent_id, e)
        try:
            self._tacview_sock.sendall("".join(lines).encode("utf-8"))
        except Exception as e:
            logger.warning("[Tacview] send error: %s", e)
            self._tacview_sock = None

    # ------------------------------------------------------------------
    # Real-time pacing
    # ------------------------------------------------------------------

    def pace(self, target_dt: float = 0.2):
        """Sleep to maintain real-time pacing. Call at end of each step."""
        now = time.perf_counter()
        if self._last_step_time is not None:
            elapsed = now - self._last_step_time
            sleep_time = target_dt - elapsed
            if sleep_time > 0.002:
                time.sleep(sleep_time)
        self._last_step_time = time.perf_counter()

    # ------------------------------------------------------------------
    # Cleanup
    # ------------------------------------------------------------------

    def close(self):
        """Release resources."""
        if self._sock is not None:
            try:
                self._sock.close()
            except Exception:
                pass
            self._sock = None
        if self._tacview_sock is not None:
            try:
                self._tacview_sock.close()
            except Exception:
                pass
            self._tacview_sock = None
        self._last_step_time = None
