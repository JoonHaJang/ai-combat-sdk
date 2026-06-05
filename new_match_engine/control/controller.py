"""제어기 옵션 — "엔진 갈아끼우기". 내측 제어기 2종을 동일 인터페이스로 추상화·선택·교체.

  ┌── 옵션 A = "lqr"  : Autopilot (Gain-scheduled LQR cascade)
  │     · 최적(CARE)·증명적 안정(Lyapunov). 정상~중간 기동. (docs LQR Report §1–14)
  └── 옵션 B = "indi" : INDIController (Incremental Nonlinear Dynamic Inversion)
        · 센서기반 증분·모델경량·외란 강건. 고기동/불확실성. (docs INDI thesis, LQR Report §15.5)

둘 다 **동일 인터페이스** — step(sp:Setpoint) -> u[thr,elev,ail,rud], reset().
이름/옵션으로 생성하고 런타임에 번갈아 교체 가능 (Pilot.set_controller, Match controller1/2).

새 제어기 추가: 같은 인터페이스 구현 후 _REGISTRY 에 한 줄 등록 → 전체에서 선택 가능.
"""
from __future__ import annotations
from typing import Protocol, runtime_checkable
import numpy as np
from guidance import Setpoint


@runtime_checkable
class Controller(Protocol):
    """교체 가능한 내측 제어기 계약. Autopilot·INDIController 가 이를 만족."""
    def step(self, sp: Setpoint) -> np.ndarray: ...
    def reset(self) -> None: ...


# ── 옵션 레지스트리 (A/B). 정규명 → (옵션문자, 표시명, 지연 팩토리) ──
def _make_lqr(plant, lqr, config, dt, indi_config):
    from autopilot import Autopilot
    return Autopilot(plant, lqr, config, dt)


def _make_indi(plant, lqr, config, dt, indi_config):
    from indi import INDIController
    return INDIController(plant, lqr, config, dt, indi_config)


_REGISTRY = {
    "lqr":  ("A", "Gain-scheduled LQR cascade",         _make_lqr),
    "indi": ("B", "Incremental Nonlinear Dyn. Inversion", _make_indi),
}
# 별칭: A/B, 대소문자, 동의어 → 정규명
_ALIAS = {"a": "lqr", "lqr": "lqr", "autopilot": "lqr",
          "b": "indi", "indi": "indi"}

CONTROLLER_OPTIONS = {k: v[0] for k, v in _REGISTRY.items()}   # {"lqr":"A","indi":"B"}


def resolve(name: str) -> str:
    """'A'/'B'/'lqr'/'indi'(대소문자 무관) → 정규명('lqr'|'indi')."""
    key = _ALIAS.get(str(name).strip().lower())
    if key is None:
        raise ValueError(f"unknown controller option: {name!r} "
                         f"(A=lqr | B=indi, or names {list(_REGISTRY)})")
    return key


def make_controller(name, plant, lqr, config=None, dt: float = 0.1,
                    indi_config=None) -> Controller:
    """옵션(A/B/이름) → 제어기 인스턴스 생성."""
    _, _, factory = _REGISTRY[resolve(name)]
    return factory(plant, lqr, config, dt, indi_config)


def list_options() -> str:
    return " | ".join(f"{v[0]}={k} ({v[1]})" for k, v in _REGISTRY.items())
