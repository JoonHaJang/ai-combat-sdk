"""Pursuit_Chase_BT basis 모듈.

HJI 수치해 산출을 위한 dynamics, solver, sanity check 함수 집합.

Modules:
  dynamics_f16_6d.py  — F-16 점-질량 6D dynamics (numpy 기반, JAX 포팅 가능)
  hji_solve.py        — Hamilton-Jacobi-Isaacs 수치 PDE solver (예정)
  buzikov_galyaev.py  — 3D 등속 동등 스펙 해석해 (sanity check, 예정)
"""

from .dynamics_f16_6d import (
    F16Envelope,
    canonical_initial_state,
    dynamics,
    omega_max_at,
    State6D,
    Control,
)

__all__ = [
    "F16Envelope",
    "canonical_initial_state",
    "dynamics",
    "omega_max_at",
    "State6D",
    "Control",
]
