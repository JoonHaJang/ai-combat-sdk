"""Phase 1 MPC framework — design ref: docs/PHASE1_MPC_DESIGN.md.

architecture:
    interfaces.py    — abstract Protocols (AdversaryModel, MPCSolver, ...)
    state.py         — 12D joint state z + feature derivation
    features.py      — 3-layer feature extraction (relational + dynamic + semantic)
    joint_dynamics.py — joint 6D ODE rollout
    adversary/       — oracle (Phase 1), ensemble/learned (later phases)
    solvers/         — mppi (Phase 1 primary), ilqr (graduation)
    tau_param/       — piecewise_constant 3-segment (Phase 1)
    costs.py         — fully relational cost (no absolute thresholds)

design 원칙 (사용자 통찰 2026-05-18):
    1. cost = relational only (절대 threshold = 적 BT 함정)
    2. event = obs 차이의 변화 (semantic 함수가 의미 추출)
    3. dispatcher = safety + context only (behavior 는 MPPI cost)
"""
