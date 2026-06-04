# Vendored: AeroBenchVVPython (F-16 model)

이 `aerobench/` 디렉터리는 **고AoA 검증 전용**으로 vendor된 써드파티 코드입니다.

- **출처**: Stanley Bak 외, *AeroBenchVVPython* — F-16 Maneuver Verification Benchmark.
  https://github.com/stanleybak/AeroBenchVVPython
- **라이선스**: 원 저장소 라이선스를 따름 (GPL-3.0). 본 vendoring 은 *검증/연구 목적* 이며,
  원 저작권·라이선스를 보존합니다. 배포 시 원 LICENSE 동봉 필요.
- **공력 모델**: NASA TP-1538 (Nguyen et al., 1979, *Simulator Study of Stall/Post-Stall
  Characteristics ...*) 의 고받음각/실속후 데이터 — Stevens & Lewis 룩업표 + Morelli 다항식.
- **용도**: `new_match_engine/validation/aerobench_testbed.py` 에서 고AoA INDI-vs-LQR 검증 plant.
  본 프로젝트의 **전투 엔진(JSBSim)과는 무관** — 제어기 검증 전용 testbed.

> 본 SDK 코드가 아니며, 검증 재현성을 위해 포함합니다.
