# validation — 제어기 검증 (Joonha Jang © 2026, All Rights Reserved)

new_match_engine 제어기(LQR/INDI)의 검증 스크립트. **이 디렉터리의 `.py` 는 저작권자의 코드**
(상위 `../LICENSE` 적용).

| 파일 | 내용 | 외부 의존성 |
|---|---|---|
| `formal_verify.py` | Z3 형식 검증 — 명령한계(LRA) + LQR Lyapunov ROA(NRA) | aerobench, z3-solver |
| `aerobench_testbed.py` | TP-1538 고AoA INDI-vs-LQR 검증 | aerobench |
| `tradeoff_sweep.py` | 게인 trade-off Pareto 곡선 | aerobench |

## 외부 의존성: AeroBenchVVPython (aerobench)

세 스크립트는 고받음각 plant 로 **AeroBenchVVPython**(NASA TP-1538 F-16 모델)을 사용한다.
이 라이브러리는 **GPL-3.0**(stanleybak)이라 *본 배포에는 미포함* — 저작권 보호를 위해 별도 설치한다.

```bash
# aerobench 를 이 디렉터리에 두면 import 됨 (validation/aerobench/)
git clone https://github.com/stanleybak/AeroBenchVVPython
cp -r AeroBenchVVPython/code/aerobench validation/aerobench
```

설치 후:
```bash
python new_match_engine/validation/formal_verify.py    # Z3 형식 검증 (PROVEN)
python new_match_engine/validation/aerobench_testbed.py # INDI vs LQR 고AoA
python new_match_engine/validation/tradeoff_sweep.py    # 게인 Pareto
```

> aerobench 미설치 시 위 스크립트는 ImportError. 엔진 본체(control/engine/bt/bridge)와
> `formal_verify` 의 Z3 부분 결론은 별도 — 자세한 결과는 `../../docs/NEW_ENGINE_INDI_VALIDATION_REPORT.md`.
