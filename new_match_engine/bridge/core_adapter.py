"""BehaviorTreeMatch 드롭인 — legacy `src/match/runner.py` 와 동일 계약, 백엔드만 new_engine.

목적(계획서 §0): SDK 호출부(`scripts/run_match.py`·`tools/evaluate.py`·tournament)가 쓰는
  `BehaviorTreeMatch(tree1_file, tree2_file, ...).run(replay_path, verbose) -> result` 를
  *그대로* 제공하되, 내부는 .pyd core(JSBSim env + AIPILOT RNN) 대신 new_engine(자체 JSBSim +
  LQR/INDI + judge + WEZ)로 실행. 호출부는 import 한 줄만 교체.

BT(.yaml) 양쪽 = yaml_bt 해석(Tactic). 초기조건 = spawn_adt_neutral(bt_vs_bt = beam, 검증됨).
엔진 = controller("lqr"|"indi") 로 내측 제어기 선택.
"""
from __future__ import annotations
import os, sys
from datetime import datetime, timezone, timedelta

_HERE = os.path.dirname(__file__)
for _d in ("control", "engine", "bt"):
    sys.path.insert(0, os.path.join(_HERE, "..", _d))

from tactic import MATCH_DURATION_S            # noqa: E402
from scenarios import spawn_adt_neutral        # noqa: E402
from replay import write_acmi_plot, write_csv  # noqa: E402
from yaml_bt import load_bt                     # noqa: E402
from match_harness import run_engine_match      # noqa: E402  ★ 엔진 실행 단일 진실

from .result_compat import LegacyMatchResult, HealthCompat

_KST = timezone(timedelta(hours=9))
_LEGACY_ENV_HZ = 20.0    # legacy env.step 20Hz (= total_steps 의 단위). new control_hz 와 정렬.


def _spawn_for_config(config_name: str):
    """legacy config_name → new_engine 초기조건. 현재 bt_vs_bt(beam)만 (계획서 §6-D4)."""
    cn = (config_name or "").lower()
    if "bt_vs_bt" in cn or cn in ("", "default"):
        return spawn_adt_neutral()              # ★ legacy bt_vs_bt 와 동일(메모리 검증)
    raise NotImplementedError(
        f"config_name={config_name!r} 미지원 — 현재 bt_vs_bt(beam)만. "
        f"타 시나리오는 계획서 §6-D4(P4)에서 spawn 매핑 추가 예정.")


class BehaviorTreeMatch:
    """legacy `BehaviorTreeMatch` 드롭인 (new_engine 백엔드).

    legacy 와 동일 생성자 + `.run()`. 추가 인자 `controller`("lqr"|"indi") 로 엔진 선택.
    실행 후 `.health1`·`.health2`(HealthCompat)·`.task1`·`.task2` 노출(runner.py 계약).
    """

    def __init__(self, tree1_file, tree2_file,
                 config_name="1v1/NoWeapon/bt_vs_bt",
                 max_steps=0, tree1_name=None, tree2_name=None,
                 step_callback=None, log_csv=None,
                 controller="lqr"):
        self.tree1_file = tree1_file
        self.tree2_file = tree2_file
        self.config_name = config_name
        self.max_steps = max_steps
        self.tree1_name = tree1_name or os.path.splitext(os.path.basename(str(tree1_file)))[0]
        self.tree2_name = tree2_name or os.path.splitext(os.path.basename(str(tree2_file)))[0]
        self.step_callback = step_callback
        self.log_csv = log_csv
        self.controller = controller
        # 실행 후 노출 (legacy runner side-channel 호환)
        self.health1 = None
        self.health2 = None
        self.task1 = None
        self.task2 = None

    def _duration_s(self) -> float:
        if self.max_steps and self.max_steps > 0:
            return self.max_steps / _LEGACY_ENV_HZ      # legacy step(20Hz) → 초
        return MATCH_DURATION_S                          # 0 → 자동 5분

    def run(self, replay_path=None, verbose=False) -> LegacyMatchResult:
        p1, p2 = _spawn_for_config(self.config_name)
        bt1 = load_bt(self.tree1_file)
        bt2 = load_bt(self.tree2_file)

        # 양 에이전트 대칭 cfg(=default, 공정한 일반 대전). 엔진 실행은 단일 진실 run_engine_match.
        want_log = bool(replay_path or self.log_csv or self.step_callback)
        res = run_engine_match(
            p1, p2,
            tactic_fn1=lambda o: bt1(o),
            tactic_fn2=lambda o: bt2(o),
            controller=self.controller,
            log_hz=(60.0 if want_log else 0.0),
            duration_s=self._duration_s(), verbose=verbose)

        # ── replay (Tacview) ──
        if replay_path:
            try:
                os.makedirs(os.path.dirname(os.path.abspath(replay_path)), exist_ok=True)
                write_acmi_plot(res.log or [], replay_path,
                                title=f"{self.tree1_name}_vs_{self.tree2_name}")
            except Exception as e:
                print(f"[bridge] replay 저장 실패: {e}")

        # ── CSV (P2 에서 legacy 컬럼 충실화; 현재 new_engine 로그) ──
        if self.log_csv:
            try:
                write_csv(res.log or [], self.log_csv)
            except Exception as e:
                print(f"[bridge] csv 저장 실패: {e}")

        # ── side-channel (legacy runner 계약) ──
        self.health1 = HealthCompat(res.health1, res.damage_dealt1)
        self.health2 = HealthCompat(res.health2, res.damage_dealt2)

        ts = datetime.now(_KST).strftime("%Y%m%d_%H%M%S")
        return LegacyMatchResult(self.tree1_file, self.tree2_file, res,
                                 replay_file=replay_path, timestamp=ts)
