"""
JSBSim Bridge for Dogfight2 (Option B)

Wraps jsbsim.FGFDMExec and owns:
  1. JSBSim FDM lifecycle (init, step, query)
  2. Coordinate transform: JSBSim geodetic -> Harfang/DF2 local flat-earth
  3. Control mapping: DF2 normalized inputs -> JSBSim fcs/ properties
  4. Output: Harfang column-major 3x4 matrix + v_move vector per frame

No harfang dependency — can be unit-tested in isolation.
"""

import math
import os


class JSBSimBridge:
    """
    JSBSim FDM wrapper for Dogfight2 physics replacement.

    Usage:
        bridge = JSBSimBridge("f16", "/path/to/jsbsim/data",
                              origin_lat=60.0, origin_lon=120.0,
                              df2_origin=[0.0, 4572.0, -503.0])
        bridge.reset(lat=60.0, lon=119.99546, alt_m=4572.0,
                     heading_deg=180.0, speed_mps=244.0)
        aircraft.attach_jsbsim(bridge)

        # Each DF2 frame:
        mat12, v3 = bridge.step(dts)
    """

    def __init__(self, model_name: str, data_path: str,
                 origin_lat: float = 60.0, origin_lon: float = 120.0,
                 origin_alt_m: float = 0.0, df2_origin: list = None):
        """
        Args:
            model_name: JSBSim aircraft model name (e.g. 'f16', 'f4n')
            data_path:  Absolute path to JSBSim data directory
                        (must contain aircraft/, engines/, systems/)
            origin_lat: Geodetic latitude of DF2 world origin [deg]
            origin_lon: Geodetic longitude of DF2 world origin [deg]
            origin_alt_m: Altitude of DF2 world origin [m]
            df2_origin: [x, y, z] Harfang position of the world origin
        """
        if df2_origin is None:
            df2_origin = [0.0, 0.0, 0.0]

        self.model_name = model_name
        self.data_path = os.path.abspath(data_path)
        self.origin_lat = origin_lat
        self.origin_lon = origin_lon
        self.origin_alt_m = origin_alt_m
        self.df2_origin = list(df2_origin)

        self._dt = 1.0 / 60.0  # JSBSim integration timestep (60 Hz, matches sim_freq in env configs)
        self._initialized = False
        self._paused = True      # Pause physics until client connects
        self._controls_dirty = False  # Only step when client sends new controls
        self._pending_step_count = 0  # Queue multiple steps per DF2 frame
        self._client_sim_dt = 0.2  # agent_interaction_steps(12) × dt(1/60) = 0.2s per client step
        self._step_count = 0     # Frame counter for periodic logging
        self._last_valid_matrix = [1,0,0, 0,1,0, 0,0,1,
                                   df2_origin[0], df2_origin[1], df2_origin[2]]
        self._last_v_move = [0.0, 0.0, 0.0]

        # Controls applied on next step() call
        self._pending_controls = {
            "aileron":  0.0,
            "elevator": 0.0,
            "rudder":   0.0,
            "throttle": 0.8 * 0.9,  # stored in JSBSim range [0, 0.9]
        }

        # Validate data path
        if not os.path.isdir(os.path.join(self.data_path, "aircraft")):
            raise FileNotFoundError(
                f"[JSBSimBridge] JSBSim data path invalid: {self.data_path}\n"
                f"Expected 'aircraft/' subdirectory to exist there."
            )

        try:
            import jsbsim
            self.fdm = jsbsim.FGFDMExec(self.data_path)
            self.fdm.set_debug_level(0)
            self._jsbsim_available = True
        except ImportError:
            print("[JSBSimBridge] WARNING: jsbsim package not available. "
                  "Bridge will be inactive (no-op).")
            self.fdm = None
            self._jsbsim_available = False

    def reset(self, lat: float, lon: float, alt_m: float,
              heading_deg: float, speed_mps: float):
        """
        Load JSBSim model and set initial conditions.
        Runs a 3-second warm-up to numerically stabilize the FDM.

        Args:
            lat:         Starting geodetic latitude [deg]
            lon:         Starting geodetic longitude [deg]
            alt_m:       Starting altitude MSL [m]
            heading_deg: Starting heading (0=North, 90=East) [deg]
            speed_mps:   Starting calibrated airspeed [m/s]
        """
        if not self._jsbsim_available:
            self._initialized = True
            return

        self.fdm.load_model(self.model_name)
        self.fdm.set_dt(self._dt)

        # Initial conditions
        self.fdm['ic/lat-geod-deg'] = lat
        self.fdm['ic/long-gc-deg']  = lon
        self.fdm['ic/h-sl-ft']      = alt_m * 3.28084
        self.fdm['ic/psi-true-deg'] = heading_deg
        self.fdm['ic/vc-kts']       = speed_mps * 1.94384  # m/s -> knots

        self.fdm.run_ic()

        # 3-second warm-up: let JSBSim settle from initial conditions
        # Without this, the aircraft lurches violently in the first frames
        for _ in range(180):  # 180 * (1/60s) = 3s
            self.fdm['fcs/throttle-cmd-norm'] = 0.8 * 0.9
            self.fdm.run()

        self._initialized = True
        print(f"[JSBSimBridge] {self.model_name} initialized: "
              f"lat={lat:.4f} lon={lon:.4f} alt={alt_m:.0f}m "
              f"hdg={heading_deg:.0f}° spd={speed_mps:.0f}m/s")

    def set_controls(self, aileron: float, elevator: float,
                     rudder: float, throttle: float):
        """
        Queue control inputs to be applied on the next step().

        Args:
            aileron:  [-1, 1] roll control (positive = right bank)
            elevator: [-1, 1] pitch control (positive = nose up)
            rudder:   [-1, 1] yaw control (positive = nose right)
            throttle: [0, 1]  throttle in DF2 range; auto-converted to [0, 0.9]
        """
        self._pending_controls['aileron']  = max(-1.0, min(1.0, float(aileron)))
        self._pending_controls['elevator'] = max(-1.0, min(1.0, float(elevator)))
        self._pending_controls['rudder']   = max(-1.0, min(1.0, float(rudder)))
        # DF2 throttle [0,1] -> JSBSim [0,0.9]
        self._pending_controls['throttle'] = max(0.0, min(0.9, float(throttle) * 0.9))

    def step(self, dt: float):
        """
        Advance simulation by dt seconds and return new kinematic state.

        Args:
            dt: Elapsed time since last call [s] (typically 1/60 for 60fps DF2)

        Returns:
            (matrix_12, v_move_3):
                matrix_12 -- Harfang column-major 3x4 flat list [12 floats]
                v_move_3  -- Velocity in Harfang coords [vn, vu, ve] m/s
        """
        if not self._jsbsim_available or not self._initialized:
            return self._last_valid_matrix, [0.0, 0.0, 0.0]

        # Pause physics until client connects (prevent pre-connection crash)
        if self._paused:
            return self._last_valid_matrix, [0.0, 0.0, 0.0]

        # Only step when client sends new controls (A-plan: client-synchronized)
        if not self._controls_dirty:
            return self._last_valid_matrix, self._last_v_move

        self._controls_dirty = False

        # Atomically copy controls (GIL-safe shallow copy)
        controls = dict(self._pending_controls)

        # Apply controls to JSBSim
        self.fdm['fcs/aileron-cmd-norm']  = controls['aileron']
        self.fdm['fcs/elevator-cmd-norm'] = controls['elevator']
        self.fdm['fcs/rudder-cmd-norm']   = controls['rudder']
        self.fdm['fcs/throttle-cmd-norm'] = controls['throttle']

        # Use client simulation dt (0.2s = 12 substeps at 120Hz)
        # This matches agent_interaction_steps=12 in the env config
        client_dt = self._client_sim_dt if self._client_sim_dt > 0 else dt
        n_substeps = max(1, round(client_dt / self._dt)) if client_dt > 0 else 1
        for _ in range(n_substeps):
            if not self.fdm.run():
                print("[JSBSimBridge] WARNING: fdm.run() returned False")
                break

        # Read state
        try:
            lat   = self.fdm['position/lat-geod-deg']
            lon   = self.fdm['position/long-gc-deg']
            alt_m = self.fdm['position/h-sl-ft'] / 3.28084
            roll  = self.fdm['attitude/roll-rad']
            pitch = self.fdm['attitude/pitch-rad']
            yaw   = self.fdm['attitude/heading-true-rad']
            vn    = self.fdm['velocities/v-north-fps'] * 0.3048
            ve    = self.fdm['velocities/v-east-fps']  * 0.3048
            vu    = -self.fdm['velocities/v-down-fps'] * 0.3048  # NED down -> NEU up
        except Exception as e:
            print(f"[JSBSimBridge] State read error: {e}")
            return self._last_valid_matrix, [0.0, 0.0, 0.0]

        # NaN guard on raw JSBSim reads — catch divergence early
        raw_vals = [lat, lon, alt_m, roll, pitch, yaw, vn, ve, vu]
        if any(math.isnan(v) for v in raw_vals):
            print(f"[JSBSimBridge] WARNING: NaN in JSBSim state reads: "
                  f"lat={lat} lon={lon} alt={alt_m} roll={roll} pitch={pitch} yaw={yaw}")
            return self._last_valid_matrix, [0.0, 0.0, 0.0]

        # Convert to Harfang space
        hg_x, hg_y, hg_z = self._lla_to_hg(lat, lon, alt_m)
        matrix_12 = self._rpy_to_matrix_12(roll, pitch, yaw, hg_x, hg_y, hg_z)
        v_move = [vn, vu, ve]  # Harfang: X=North, Y=Up, Z=East

        self._last_valid_matrix = matrix_12
        self._last_v_move = v_move
        self._step_count += 1
        # Periodic logging: every 120 frames (~2 seconds at 60fps)
        if self._step_count % 120 == 1:
            spd = math.sqrt(vn*vn + ve*ve + vu*vu)
            ctrl = self._pending_controls
            print(f"[JSBSim] frame={self._step_count} "
                  f"pos=({hg_x:.1f},{hg_y:.1f},{hg_z:.1f}) "
                  f"alt={alt_m:.1f}m spd={spd:.1f}m/s "
                  f"rpy=({math.degrees(roll):.1f},{math.degrees(pitch):.1f},{math.degrees(yaw):.1f}) "
                  f"ctrl(a={ctrl['aileron']:.2f},e={ctrl['elevator']:.2f},"
                  f"r={ctrl['rudder']:.2f},t={ctrl['throttle']:.2f})")
        return matrix_12, v_move

    def destroy(self):
        """Explicitly release the FDM before Python shutdown to avoid segfault."""
        if self.fdm is not None:
            self._initialized = False
            try:
                self.fdm = None  # release reference; FGFDMExec destructor runs now
            except Exception:
                pass

    def get_thrust_level(self) -> float:
        """
        Returns actual throttle position rescaled to DF2 range [0, 1].
        Accounts for engine spool-up lag (actual position != command).
        """
        if not self._jsbsim_available or not self._initialized:
            return 0.8
        try:
            raw = self.fdm['fcs/throttle-pos-norm']  # JSBSim range [0, ~0.9]
            return min(1.0, raw / 0.9)
        except Exception:
            return 0.8

    def get_post_combustion_active(self) -> bool:
        """
        Returns True when throttle is near maximum (afterburner zone).
        Threshold 0.88 in JSBSim range ~ 0.978 in DF2 range.
        """
        if not self._jsbsim_available or not self._initialized:
            return False
        try:
            return self.fdm['fcs/throttle-pos-norm'] >= 0.88
        except Exception:
            return False

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _lla_to_hg(self, lat: float, lon: float, alt_m: float):
        """
        Flat-earth LLA -> Harfang local XYZ.
        Identical to LLA2NEU in simulatior.py so both JSBSim instances
        produce the same Harfang positions for the same geodetic input.

        Harfang axes: X=North, Y=Up, Z=East
        """
        R = 6371000.0
        pi = math.pi
        lat0 = self.origin_lat
        lon0 = self.origin_lon
        dn = (lat - lat0) * pi / 180.0 * R
        de = (lon - lon0) * pi / 180.0 * math.cos(lat0 * pi / 180.0) * R
        du = alt_m - self.origin_alt_m
        hg_x = self.df2_origin[0] + dn
        hg_y = self.df2_origin[1] + du
        hg_z = self.df2_origin[2] + de
        return hg_x, hg_y, hg_z

    def _rpy_to_matrix_12(self, roll: float, pitch: float, yaw: float,
                           x: float, y: float, z: float) -> list:
        """
        RPY (radians) + position -> Harfang column-major 3x4 flat list.
        NEU -> Harfang axis permutation (X=North, Y=Up, Z=East) is baked in.

        This is a direct copy of _rpy_to_matrix_3x4 in match_visualizer.py
        (lines 16-31) which is proven correct by the existing visualizer.
        """
        cr, sr = math.cos(roll),  math.sin(roll)
        cp, sp = math.cos(pitch), math.sin(pitch)
        cy, sy = math.cos(yaw),   math.sin(yaw)

        r00 = cy * cp
        r01 = cy * sp * sr - sy * cr
        r02 = cy * sp * cr + sy * sr
        r10 = sy * cp
        r11 = sy * sp * sr + cy * cr
        r12 = sy * sp * cr - cy * sr
        r20 = -sp
        r21 = cp * sr
        r22 = cp * cr

        # Harfang column-major: [col0(r00,r20,r10), col1(r01,r21,r11),
        #                         col2(r02,r22,r12), translation(x,y,z)]
        return [r00, r20, r10,
                r01, r21, r11,
                r02, r22, r12,
                x,   y,   z]


# ------------------------------------------------------------------
# Standalone test
# ------------------------------------------------------------------
if __name__ == "__main__":
    import sys
    import os

    # Resolve JSBSim data path relative to this file
    here = os.path.dirname(os.path.abspath(__file__))
    data_path = os.path.abspath(
        os.path.join(here, "..", "..", "src", "simulation", "envs", "JSBSim", "data")
    )

    print(f"Testing JSBSimBridge with data_path={data_path}")

    bridge = JSBSimBridge(
        model_name="f16",
        data_path=data_path,
        origin_lat=60.0,
        origin_lon=120.0,
        df2_origin=[0.0, 4572.0, -503.0]
    )

    bridge.reset(lat=60.0, lon=120.0 - 503.0/111000.0,
                 alt_m=4572.0, heading_deg=180.0, speed_mps=244.0)

    print("Running 10 steps...")
    for i in range(10):
        mat12, v3 = bridge.step(1.0/60.0)
        print(f"  step {i}: pos=({mat12[9]:.1f},{mat12[10]:.1f},{mat12[11]:.1f}) "
              f"vel=({v3[0]:.1f},{v3[1]:.1f},{v3[2]:.1f}) "
              f"thrust={bridge.get_thrust_level():.2f} "
              f"pc={bridge.get_post_combustion_active()}")

    print("JSBSimBridge test OK")
