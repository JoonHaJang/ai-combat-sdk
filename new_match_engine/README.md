# new_match_engine — 투명 제어 엔진 (legacy core 드롭인)

> **한 줄**: 기존 매치 엔진의 블랙박스 저수준 제어(AIPILOT RNN)를 **투명·결정론·인용 가능한
> 제어기(gain-scheduled LQR / INDI)**로 대체하는 자급식 엔진. **BT(`.yaml`) 인터페이스는 그대로**,
> 매치 백엔드만 교체한다.

기존 SDK 흐름(`scripts/run_match.py`)에 **`--backend` 플래그 한 개**로 끼워 쓴다:

```bash
python scripts/run_match.py --agent1 aggressive --agent2 ace --backend lqr     # 투명 LQR
python scripts/run_match.py --agent1 aggressive --agent2 ace --backend indi    # INDI
python scripts/run_match.py --agent1 aggressive --agent2 ace --backend legacy  # 원본(기본)
```

---

## 1. 프로젝트 구조

```
new_match_engine/
├── control/                 # 비행 제어 (자급식, JSBSim 만 의존)
│   ├── tactic.py            # Tactic enum + 상수·단위 (단일 진실)
│   ├── guidance.py          # Tactic + obs → Setpoint(ψ*,h*,V*)
│   ├── plant.py             # JSBSim F-16 6-DOF 래퍼 (root 경로 자동탐색)
│   ├── linearize.py         # 운영점 유한차분 (A,B)
│   ├── lqr.py               # CARE → 게인 K, gain-scheduled 3×3
│   ├── indi.py              # 증분 비선형 동적 역변환 (옵션 B)
│   ├── autopilot.py         # 외측 PI/P + 내측 LQR (단위변환 전담)
│   └── controller.py        # 엔진 레지스트리 A=lqr / B=indi
├── engine/                  # 매치 루프·심판·관측
│   ├── obs.py               # compute_obs → Observation(기하)
│   ├── judge.py             # WEZ 데미지 + 승패 (원본 100% 복제)
│   ├── match.py             # 매치 루프 (multi-rate)
│   ├── match_harness.py     # ★ 엔진 실행 단일 진실 run_engine_match
│   ├── pilot.py             # obs→tactic→guidance→autopilot→u 체인
│   ├── replay.py            # ACMI(Tacview) + CSV 기록
│   └── scenarios.py         # spawn_adt_neutral(beam) 등 초기조건
├── bt/                      # 전술 결정
│   ├── tree_policy.py       # 상황 독립 dispatch (우리 정책)
│   ├── yaml_bt.py           # legacy .yaml BT 해석 → Tactic
│   ├── situation.py         # 상황 분류(offensive/defensive/neutral)
│   └── run_match.py         # canonical 평가 진입점
├── bridge/                  # ★ legacy core 드롭인
│   ├── core_adapter.py      # legacy BehaviorTreeMatch 와 동일 계약
│   ├── result_compat.py     # 결과 형태 변환(tree1/tree2/draw)
│   ├── legacy_csv.py        # legacy 46컬럼 CSV 재현
│   ├── run_legacy.py        # CLI: 두 .yaml 을 new_engine 으로 1경기
│   └── verify_swap.py       # 교환 검증(3 백엔드 패리티)
├── validation/              # 제어기 검증 (연구용)
│   ├── aerobench_testbed.py # TP-1538 고AoA INDI-vs-LQR
│   ├── tradeoff_sweep.py    # 게인 Pareto 곡선
│   └── formal_verify.py     # Z3 형식 검증(명령한계·ROA)
├── README.md  ·  TACTIC_SPEC.md  ·  BT_ENGINE_TUTORIAL.md
```

**의존성**: `jsbsim`(pip), `numpy`, `scipy`, `pyyaml` (+ INDI 검증에 `z3-solver`). F-16 비행데이터는
`external_repo/AIP_knowledge_Base/JSBSim` 를 자동으로 찾는다(sdk/core 양쪽 경로 robust).

---

## 2. run_match.py 참조

`scripts/run_match.py` 는 **백엔드 선택 외에는 기존과 동일**하다.

| 인자 | 뜻 |
|---|---|
| `--agent1`, `--agent2` | BT(`.yaml`) 이름 (examples/ 또는 submissions/) 또는 경로 |
| `--backend legacy\|lqr\|indi` | 매치 백엔드. 기본 `legacy`(원본 .pyd/RNN) |
| `--scenario bt_vs_bt` | 초기조건(현재 new_engine 백엔드는 bt_vs_bt=beam 지원) |
| `--max-steps N` | 0=자동(5분=6000 step @20Hz) |
| `--rounds`, `--log-csv`, `--quiet` | 기존과 동일 |

내부 분기(발췌):

```python
def _make_match_cls(backend):
    if backend == "legacy":
        from src.match.runner import BehaviorTreeMatch        # 원본 core
        return BehaviorTreeMatch, {}
    if backend in ("lqr", "indi"):
        from new_match_engine.bridge import BehaviorTreeMatch  # 드롭인
        return BehaviorTreeMatch, {"controller": backend}
```

`bridge.BehaviorTreeMatch` 는 원본 `src/match/runner.py` 의 `BehaviorTreeMatch` 와 **동일한
생성자·`.run()`·결과 계약**(winner∈{tree1,tree2,draw}, `.steps`/`.health1`/`.health2`, replay, CSV).
즉 호출부 무수정.

다른 진입점:
```bash
python -m new_match_engine.bridge.run_legacy aggressive ace --controller indi --replay
python new_match_engine/bt/run_match.py ace        # canonical (우리 TreePolicy vs .yaml)
```

---

## 3. 제어 알고리즘 교체법

저수준 제어기는 **옵션 A(LQR) / 옵션 B(INDI)** 로 런타임 교체된다. 외측 루프(자세 목표 산출)는 동일,
**내측 루프만** 갈아끼운다(공정 비교).

**(a) CLI 한 인자** — 가장 쉬움:
```bash
--backend lqr     # 옵션 A: gain-scheduled LQR
--backend indi    # 옵션 B: INDI (증분 비선형 동적 역변환)
```

**(b) 코드에서** — `controller` 인자:
```python
from new_match_engine.bridge import BehaviorTreeMatch
m = BehaviorTreeMatch("aggressive.yaml", "ace.yaml", controller="indi")
res = m.run(replay_path="x.acmi")
```

**(c) 런타임 교체** — Pilot:
```python
pilot.set_controller("indi")   # 또는 "lqr"
```

**(d) 새 제어기 추가** — `control/controller.py` 레지스트리에 등록:
```python
_REGISTRY = {
    "lqr":  ("A", "gain-scheduled LQR", _make_lqr),
    "indi": ("B", "INDI",               _make_indi),
    # "mpc": ("C", ...) ← 여기에 추가하면 --backend mpc 로 사용 가능
}
```
제어기는 `step(setpoint) -> u[thr,elev,ail,rud]` 프로토콜만 만족하면 된다(`controller.py`의 Controller).

**언제 무엇을**: 단순 기동은 LQR·INDI 모두 정상상태 <0.1°(동등). **복합 고기동 + 모델 불확실성**에선
INDI가 ~4× 정밀·~7× 빠른 정착(`validation/`의 TP-1538 검증). 자세한 비교는
[INDI 검증 리포트](../docs/book/08_indi.md).

---

## 4. 검증 (교환이 제대로 됐는지)

```bash
# 교환 검증 — legacy·LQR·INDI 3 백엔드가 동일 .yaml·동일 인터페이스로 동작 (3/3 PASS)
python -m new_match_engine.bridge.verify_swap

# 제어기 형식 검증 — Z3 로 명령한계·LQR ROA 기계증명
python new_match_engine/validation/formal_verify.py

# 게인 trade-off Pareto
python new_match_engine/validation/tradeoff_sweep.py
```

`verify_swap` 가 확인하는 것:
1. **API 패리티** — legacy 생성자/`.run()` 인자가 bridge 에 모두 존재(드롭인 가능).
2. **side-by-side** — 같은 `.yaml` 쌍을 legacy(원본)·new(LQR)·new(INDI)로 실행, *동일 인터페이스*로
   결과 반환. (winner/HP 값은 RNN≠LQR 이라 다를 수 있음 — 인터페이스 동일성이 핵심.)
3. **드롭인 소비자** — `scripts/run_match.py` 의 결과 접근 패턴이 그대로 동작.

> 참고: 약한 `.yaml` 둘이 붙으면 **원본 엔진도 0-0 무승부** — bridge 0-0 은 결함이 아니라 충실 재현.

---

## 5. 동작 원리 (4계층 요약)

```
[1] 상황판단 dispatch  (TreePolicy / yaml_bt)  → Tactic
[2] 유도 guidance      (전술 → 목표)            → Setpoint(ψ*,h*,V*)
[3] 자동조종 + LQR/INDI (목표 → 조종면)          → u=[thr,elev,ail,rud]
[4] 물리 JSBSim F-16    (6-DOF 한 스텝)
          ↑ WEZ(ATA<12°,500–3000ft)·judge(HardDeck<1000ft) 로 승패
```

자세한 설명:
- [학생용 입문서](../docs/book/02_big_picture.md) — 전체 그림·직관
- [아키텍처 다이어그램](../docs/book/13_architecture.md) — 모듈·흐름 Mermaid
- [LQR 제어 리포트](../docs/book/06_lqr.md) — 이론·증명
- [INDI 검증](../docs/book/08_indi.md) · [core 교체 계획](../docs/book/14_engine_replacement.md)

---

## 6. 라이선스 / 출처

- **new_match_engine 코드·문서**: Copyright (c) 2026 **Joonha Jang. All Rights Reserved** (`LICENSE`).
  서면 허가 없이 사용·복제·수정·배포 금지(열람 가능). 문의 cyber040946@gmail.com.
- `jsbsim_data/`: JSBSim F-16 데이터 (LGPL-2.1, `jsbsim_data/COPYING` 동봉).
- `validation/aerobench/`(외부 의존성, **본 배포 미포함**): AeroBenchVVPython (GPL-3.0, stanleybak)
  — 설치법은 `validation/README.md`.
