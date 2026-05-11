"""
Verification framework for sim_dogfight_verify.py BFM-τ control.

Modules:
    canonical_perturbation — P(x_0; δ) sampler (모든 검증의 기반)
    test_tau_metamorphic    — Phase A: τ 함수 metamorphic relations (pytest)
    statistical_mc          — Phase B: Wilson CI + Wald SPRT for WIN rate

See ../VERIFICATION_METHODOLOGY.md for academic context and roadmap.
"""
