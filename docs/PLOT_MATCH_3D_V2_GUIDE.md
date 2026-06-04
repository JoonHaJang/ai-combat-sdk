# plot_match_3d_v2.py 사용법 및 기능 가이드 (v4)

> AI Combat SDK 전용 종합 매치 3D 시각화 + BT→RNN 파이프라인 진단 도구

---

## 1. 개요

`plot_match_3d_v2.py`는 ACMI 리플레이 파일과 `metadata_logger.py`가 출력한 메타 CSV를 동시에 해석해, **한 장의 PNG**에 전투 매치의 물리·기하·에너지·제어·BFM 상황을 6×4(총 24칸) 종합 대시보드로 출력합니다.

graphify 결과(프로젝트 구조, BT→RNN 병목, BFM phase 체계)를 반영하여 현재 프로젝트에 최적화되어 있습니다.

---

## 2. 전제조건

- Python 3.9+
- numpy
- matplotlib

```bash
pip install numpy matplotlib
```

---

## 3. 기본 사용법

```bash
python tools/plot_match_3d_v2.py --replay <acmi 파일> [--meta <csv 파일>] [--out <png 경로>]
```

| 옵션 | 설명 | 기본값 |
|---|---|---|
| `--replay` | **필수.** ACMI(`.txt.acmi`) 리플레이 파일 경로 | — |
| `--meta` | 선택. `metadata_logger.py`가 생성한 per-agent CSV (`*_meta.csv`) | 동일 파일명 + `_meta.csv` 자동 탐색 |
| `--out` | 선택. 출력 PNG 경로 | `<replay>.3d.v2.png` |
| `--dmg-us` | 선택. us → opp 누적 데미지 (진단 텍스트용) | `0` |
| `--dmg-opp` | 선택. opp → us 누적 데미지 | `0` |

### 예시

```bash
# ACMI만으로 실행 (메타 CSV 자동 탐색 시도)
python tools/plot_match_3d_v2.py --replay replays/match_001.txt.acmi

# 메타 CSV 직접 지정
python tools/plot_match_3d_v2.py --replay replays/match_001.txt.acmi --meta logs/match_001_meta.csv --out out/match_001_diag.png
```

---

## 4. 입력 데이터

### 4.1 ACMI 파일 (`--replay`)
- `T=lon|lat|alt|roll|pitch|yaw` 파싱
- 프로젝트 표준 확장 필드:
  - `HDG`, `CAS`, `ATA`, `AA`, `Distance`, `ClosureRate`
  - `HCA`, `TAU`, `AltGap`, `TurnRate`
  - `In39Line`, `OvershootRisk`, `EnergyAdvantage`, `AltAdvantage`, `SpdAdvantage`
  - `TCType`, `SideFlag`
  - 제어 입력: `RollControlInput`, `PitchControlInput`, `YawControlInput`, `Throttle`

### 4.2 메타 CSV (`--meta`)
- `metadata_logger.py` 출력 형식 완전 호환
- us 행만 필터링 (`agent_id`가 `A`로 시작)
- 활용 컬럼:
  - `action_alt` / `action_altitude`
  - `action_hdg` / `action_heading`
  - `action_vel` / `action_velocity`
  - `active_node`, `bfm_situation`
  - `aileron`, `elevator`, `rudder`, `throttle`, `reward`

> 주의: `ego_vc_kts`, `specific_energy_ft`, `ata_deg` 등 운동학 필드는 per-agent 복사 버그로 오염될 수 있으므로 **절대 사용하지 않습니다.** ACMI의 물리 값을 신뢰합니다.

---

## 5. 패널 구성 (6×4 대시보드)

| 행 | 열 1 | 열 2 | 열 3 | 열 4 |
|---|---|---|---|---|
| **Row 1** | 3D 궤적 (시간 그라데이션) | Top-down + 원 적합 + WEZ | **BFM Phase 타임라인** | Pattern + 종합 진단 텍스트 |
| **Row 2** | 고도 (ft) | 거리 + WEZ 밴드 (ft) | ATA + AA | HCA + 위상 차 |
| **Row 3** | HDG (언랩) | 선회율 (deg/s) | CAS (kts) | Closure rate (kts) |
| **Row 4** | 비해면 에너지 Es (ft) | 에너지 우위 차 | 롤/피치 각도 (deg) | WEZ 체류 히스토그램 |
| **Row 5** | **vel bin vs throttle** | **hdg bin vs turn rate** | **alt bin vs 수직 속도** | 제어 입력 (ail/elev/rud/thr) |
| **Row 6** | Active node 타임라인 | Action bin 분포 | BFM situation 분포 | Reward 추이 + Verdict |

---

## 6. 핵심 분석 기능

### 6.1 BT→RNN 파이프라인 병목 분석

`BT_RNN_CONTROLLER_ANALYSIS.md`의 진단 로직을 시각화에 직접 반영합니다.

- **Row 5, Col 1** (`vel bin vs throttle`):
  - BT `vel=4`(풀가속) 구간에서 실제 throttle 평균이 `0.6` 미만이면 **THROTTLE BOTTLENECK**으로 판정.
  - `vel=0`(감속) 구간에서 throttle 평균이 `0.4` 초과면 동일하게 병목.
- **Row 5, Col 2** (`hdg bin vs turn_rate`):
  - BT `hdg bin`이 급선회(0,1,7,8)일 때 실제 선회율(turn rate)이 미미하면 RNN 저수준 추종 실패 시각화.
- **Row 5, Col 3** (`alt bin vs vertical speed`):
  - 고도 bin과 실제 수직 속도(`vs_fts`) 비교.

### 6.2 BFM Phase 타임라인 (Row 1, Col 3)

- `analyze_acmi.py`와 동일한 규약:
  - `OBFM` (offensive): ATA < 45° && AA > 135°
  - `DBFM` (defensive): ATA > 135° && AA < 45°
  - `HABFM` (high aspect): 45° ≤ ATA,AA ≤ 135°
  - `NEUTRAL`: 그 외
- 시간축 위에 색상 띠로 표현되어 전투 흐름을 한눈에 파악.

### 6.3 에너지 메트릭 (Row 4)

- **비해면 에너지** `Es = alt + v²/(2g)` (단위: ft)
  - `G_FTS2 = 32.174`, `KTS_TO_FTS = 1.68781` 사용.
- **에너지 우위 차** (`Es_diff = Es_us - Es_opp`):
  - 양수면 우리가 에너지 우위.
  - 0 근방 교차(crossover) 구간 강조.

### 6.4 자동 패턴 분류

- **A** co-centric scissors: 중심 근접 + 유사 R
- **A'** figure-8 (lemniscate): 180° phase lock 우세
- **B** offset spiral: 중심 멀리 떨어진 원
- **C** linear extend: 단조 증가 + 거리 확대 (oscillation 오탐 방지)
- **D** inside-outside: 동심원 + R 차이 큼
- **E** undetermined

점수 기반 `argmax`로 단일 패턴 결정. 단조성 게이트(`mono > 0.7`)로 가짜 C 오탐 차단.

### 6.5 Root-Cause Verdict

- **POLICY DEGENERATE**: roll 평균 < 0.15 && WEZ 없음 → 선회 명령 자체 부재
- **PHYSICS LIMIT**: roll/pitch 포화 > 30% && WEZ 없음 → 명령했으나 기체 한계
- **BT→RNN BOTTLENECK**: vel bin과 throttle 응답 불일치
- **MIXED / ENGAGING**: 그 외 상황

---

## 7. 프로젝트 표준 단위

| 물리량 | 단위 | 비고 |
|---|---|---|
| 거리 (n/e) | m | LLA → NED 변환 |
| 고도 (u) | ft | ACMI alt(m) × 3.28084 |
| 거리 (dist) | ft | ACMI Distance 그대로 |
| 속도 (CAS) | kts | ACMI CAS 그대로 |
| 선회율 | deg/s | numerical gradient |
| 에너지 (Es) | ft | `alt + v²/(2g)` |
| 제어 입력 | 정규화 [-1,1] | ACMI ControlInput 그대로 |
| Throttle | [0,1] | ACMI Throttle 그대로 |

---

## 8. 출력 파일

- **포맷**: PNG
- **해상도**: `dpi=90` (기본), `bbox_inches="tight"`
- **크기**: `figsize=(24, 28)` 인치 (충분한 세부 정보용)

---

## 9. 로컬 실행 체크리스트

```bash
# 1. 의존성 확인
python -c "import numpy, matplotlib; print('OK')"

# 2. ACMI 파일 확인
head -n 5 replays/match_001.txt.acmi

# 3. 메타 CSV 확인 (선택)
head -n 2 logs/match_001_meta.csv

# 4. 실행
python tools/plot_match_3d_v2.py --replay replays/match_001.txt.acmi

# 5. 출력 확인
ls -lh replays/match_001.3d.v2.png
```

---

## 10. 알려진 제한 및 팁

1. **ACMI 파일 내용**: `A0100`, `B0100` UID가 포함되어야 양측 궤적이 모두 그려집니다.
2. **메타 CSV 자동 탐색**: `--meta`를 생략하면 `<replay_stem>_meta.csv`를 같은 디렉터리에서 찾습니다. 없으면 ACMI만으로 진행.
3. **시간 동기화**: ACMI `T=` 타임스탬프와 메타 CSV `step`은 별도 축으로 표시됩니다. 메타 step은 보통 1step ≈ 0.05s 가정이나 정확한 동기화를 위해서는 양쪽에 동일한 시간 축이 필요합니다.
4. **파일 크기**: 긴 매치(수만 틱)는 PNG 생성에 수 초 ~ 수십 초 소요될 수 있습니다.
5. **메모리**: 매우 긴 ACMI는 numpy 배열로 메모리에 적재되므로 RAM 여유가 필요합니다.

---

## 11. 관련 문서

- `docs/BT_RNN_CONTROLLER_ANALYSIS.md` — BT→RNN 병목 분석 원문
- `tools/analyze_acmi.py` — 텍스트 기반 ACMI 분석
- `tools/metadata_logger.py` — 메타 CSV 생성 모듈
- `scripts/run_match.py` — 매치 실행 + ACMI/CSV 출력
