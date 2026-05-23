"""RT-1.3 — BT API hdg-bin sign stub (RED TEAM F4 closure).

목적: BT action 의 hdg bin (0..8, 4=straight) 이 물리적으로 좌/우 어느 방향
선회인지 *경험적으로* 확정. 핵심 SDK 는 컴파일된 .pyd 라 bin→제어 매핑을
소스에서 읽을 수 없음 → fixed-command stub 으로 측정.

FixedHdg 노드: 매 tick `set_action(alt_bin, hdg_bin, vel_bin)` 고정 출력.
부수적으로 obs 를 tick 별 CSV 로깅 (HDG_STUB_LOG 환경변수).

검증: ACMI replay 의 `HDG=` (절대 방위) 변화로 ground-truth 좌/우 판정.
  HDG 증가(시계방향) = RIGHT, HDG 감소(반시계) = LEFT.
"""

from __future__ import annotations

import os
from pathlib import Path

import py_trees

_LOG_PATH = os.environ.get("HDG_STUB_LOG", "")
_LOG_FILE = None
_TICK = 0


def _log_open():
    global _LOG_FILE
    if not _LOG_PATH or _LOG_FILE is not None:
        return _LOG_FILE
    p = Path(_LOG_PATH)
    p.parent.mkdir(parents=True, exist_ok=True)
    _LOG_FILE = open(p, "w", encoding="utf-8")
    _LOG_FILE.write(
        "tick,cmd_alt,cmd_hdg,cmd_vel,"
        "relative_bearing_deg,side_flag,ata_deg,aa_deg,hca_deg,"
        "roll_deg,pitch_deg,turn_rate_degs,distance_ft,ego_altitude_ft\n"
    )
    return _LOG_FILE


class FixedHdg(py_trees.behaviour.Behaviour):
    """매 tick 고정 (alt, hdg, vel) bin 출력 + obs 로깅.

    Params (yaml):
        hdg_bin: 고정 출력할 heading bin (0..8). default 8.
        alt_bin: default 2 (hold).
        vel_bin: default 2 (hold).
    """

    def __init__(self, name: str = "FixedHdg",
                 hdg_bin: int = 8, alt_bin: int = 2, vel_bin: int = 2):
        super().__init__(name)
        self.hdg_bin = int(hdg_bin)
        self.alt_bin = int(alt_bin)
        self.vel_bin = int(vel_bin)
        self.blackboard = self.attach_blackboard_client()
        self.blackboard.register_key(key="observation", access=py_trees.common.Access.READ)
        self.blackboard.register_key(key="action", access=py_trees.common.Access.WRITE)

    def update(self) -> py_trees.common.Status:
        global _TICK
        obs = self.blackboard.observation
        f = _log_open()
        if f is not None and obs is not None:
            def g(k):
                v = obs.get(k, "")
                return v
            if _TICK == 0:
                f.write(f"# obs keys: {sorted(obs.keys())}\n")
            f.write(
                f"{_TICK},{self.alt_bin},{self.hdg_bin},{self.vel_bin},"
                f"{g('relative_bearing_deg')},{g('side_flag')},{g('ata_deg')},"
                f"{g('aa_deg')},{g('hca_deg')},{g('roll_deg')},{g('pitch_deg')},"
                f"{g('turn_rate_degs')},{g('distance_ft')},{g('ego_altitude_ft')}\n"
            )
            f.flush()
            _TICK += 1

        self.blackboard.action = [self.alt_bin, self.hdg_bin, self.vel_bin]
        return py_trees.common.Status.SUCCESS
