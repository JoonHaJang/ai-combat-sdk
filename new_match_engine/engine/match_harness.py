"""단일 진실 — new_engine 매치 실행 하네스. 모든 진입점이 *이걸* 호출.

목적(2026-06-05): `scripts/run_match.py`(bridge 백엔드)와
`new_match_engine/bt/run_match.py`(canonical 평가)가 **동일한 엔진 역학**
(LQR 격자·제어 rate·autopilot cfg 기본값·Match 조립)을 쓰도록 중복 제거 → drift 방지.

호출자는 (이미 spawn 된) p1,p2 + 양측 tactic_fn 만 준다. 누가 플레이하는지(TreePolicy vs
yaml_bt), cfg 비대칭(적 핸디캡), 엔진(lqr/indi), 출력물(acmi/csv/report)은 *호출자 선택* —
하지만 그 아래 엔진 실행은 이 함수 하나로 통일된다.
"""
from __future__ import annotations
import os, sys, math

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "control"))
from lqr import GainScheduledLQR        # noqa: E402
from autopilot import AutopilotConfig   # noqa: E402
from tactic import MATCH_DURATION_S     # noqa: E402
from match import Match                 # noqa: E402

# ── 단일 진실 상수 (scripts·canonical 공통) ──
LQR_ALTS = [5000.0, 15000.0, 25000.0]   # gain-schedule 고도 격자 (ft)
LQR_VCS  = [250.0, 350.0, 450.0]        # gain-schedule 속도 격자 (kts)
CONTROL_HZ = 20.0
BT_HZ      = 10.0
LOG_HZ     = 60.0

_GS_CACHE = None


def get_shared_lqr() -> GainScheduledLQR:
    """프로세스당 1회 빌드되는 공유 gain-scheduled LQR (격자 = 단일 진실)."""
    global _GS_CACHE
    if _GS_CACHE is None:
        _GS_CACHE = GainScheduledLQR(LQR_ALTS, LQR_VCS).build()
    return _GS_CACHE


def default_autopilot_cfg() -> AutopilotConfig:
    """기본 autopilot cfg — BFM 하드선회 (KP_PSI=0.25, MAX_PSI_RATE=20°). 단일 진실."""
    cfg = AutopilotConfig(KP_PSI=0.25)
    cfg.MAX_PSI_RATE = math.radians(20.0)
    return cfg


def run_engine_match(p1, p2, tactic_fn1, tactic_fn2, *,
                     controller: str = "lqr", controller2: str | None = None,
                     cfg1: AutopilotConfig | None = None,
                     cfg2: AutopilotConfig | None = None,
                     control_hz: float = CONTROL_HZ, bt_hz: float = BT_HZ,
                     log_hz: float = LOG_HZ,
                     duration_s: float = MATCH_DURATION_S, verbose: bool = False):
    """new_engine 매치 1회 실행 → MatchResult. **엔진 역학 단일 진실**.

    p1,p2        : 이미 spawn 된 F16Plant (호출자가 spawn_adt_neutral 등으로 준비)
    tactic_fn1/2 : (Observation)->Tactic  (TreePolicy.select 또는 yaml_bt load_bt 결과)
    controller   : "lqr"|"indi" (양측 동일; controller2 로 비대칭 가능)
    cfg1/cfg2    : autopilot cfg (None→default_autopilot_cfg). canonical 은 cfg2 핸디캡 주입.
    """
    gs = get_shared_lqr()
    m = Match(p1, p2, gs,
              cfg1=cfg1 or default_autopilot_cfg(),
              cfg2=cfg2 or default_autopilot_cfg(),
              control_hz=control_hz, bt_hz=bt_hz, log_hz=log_hz,
              controller1=controller, controller2=controller2 or controller)
    return m.run(tactic_fn1=tactic_fn1, tactic_fn2=tactic_fn2,
                 duration_s=duration_s, verbose=verbose)
