# 0. 현재 프로젝트 현황 요약

---

## 0-1. ai-combat-sdk — BT 에이전트 매치 실행기

**함수적 표현:**
```
f(agent1_yaml, agent2_yaml, config)
  → [JSBSim 물리 × N steps + BT 트리 평가 + WEZ 피해 계산]
  → winner, health, damage, replay.acmi, logs/*.csv
```

| 입력 | 처리 | 출력 |
|------|------|------|
| BT YAML 2개 (eagle1, ace 등) | JSBSim 1v1 물리 (60Hz × 12 substep/step) | MatchResult (winner, health, steps) |
| match_config.yaml | BT 트리 평가 (conditions/actions) | logs/*.csv (93컬럼 텔레메트리) |
| CLI flags | WEZ 총기 피해 계산 (.pyd) | replays/*.acmi (Tacview 재생) |
| (선택) --tacview-realtime | Tacview TCP ACMI 스트리밍 (포트 42674) | Tacview 실시간 전술 뷰 |

**파일 구성 및 관계:**
```
scripts/run_match.py              ← CLI 진입점
  └─ src/match/runner.py          ← BehaviorTreeMatch (CSV + 시각화 래퍼)
       └─ src/match/runner_core.py    ← MatchCore (주 루프)
            ├─ JSBSim SingleCombatEnv     (물리 시뮬)
            ├─ BehaviorTreeTask x2 .pyd   (트리 실행)
            ├─ HealthGauge x2 .pyd        (체력 관리)
            └─ wez_engine.pyd             (총기 피해)
  └─ src/visualization/
       ├─ flightgear_vis.py       ← FlightGear UDP + Tacview TCP 서버
       └─ match_visualizer.py     ← Dogfight2 클라이언트 (레거시)
  └─ examples/eagle1/eagle1.yaml  ← BT 트리 정의 예시
```

---

## 0-2. LAG — JSBSim RL 훈련 환경 (참조용)

**함수적 표현:**
```
f(scenario_yaml, ppo_config)
  → [JSBSim 물리 × PPO 학습 루프 (GRU Actor-Critic + GAE)]
  → trained_policy.pt, tacview_replay.acmi, episode_rewards
```

| 입력 | 처리 | 출력 |
|------|------|------|
| 시나리오 YAML (1v1/NoWeapon 등) | JSBSim FDM 60Hz × 12 substep | 학습된 PPO 정책 (.pt) |
| 관측 15차원 벡터 (정규화) | GRU+MLP Actor-Critic 네트워크 | ACMI 재생 파일 |
| 이산 행동 4차원 (aileron×41 등) | GAE + PPO 클리핑 손실 | 에피소드 보상 로그 |
| (선택) selfplay 설정 | 자기대전 / baseline 대전 | ELO 레이팅 |

**파일 구성 및 관계:**
```
LAG/scripts/train/train_jsbsim.py     ← 학습 진입점
  └─ LAG/runner/jsbsim_runner.py      ← 수집/계산/학습 루프
       └─ LAG/envs/JSBSim/envs/
            ├─ env_base.py            ← Gymnasium 환경 기반
            └─ singlecombat_env.py    ← 1v1 전투 환경
       └─ LAG/envs/JSBSim/core/
            ├─ simulatior.py          ← AircraftSimulator (jsbsim_exec 래퍼)
            └─ render_tacview.py      ← ACMI 출력
       └─ LAG/envs/JSBSim/tasks/
            └─ singlecombat_task.py   ← 관측/행동/보상 정의
       └─ LAG/algorithms/ppo/
            ├─ ppo_policy.py          ← Actor+Critic 네트워크
            ├─ ppo_trainer.py         ← PPO 손실 계산
            └─ utils/buffer.py        ← GAE 리플레이 버퍼
```

---

## 0-3. 두 프로젝트의 관계

```
LAG                                   ai-combat-sdk
──────────────────────────────────────────────────────────
JSBSim 환경 (SingleCombatEnv)   ──→   동일 환경 사용 (내부 .pyd)
PPO 정책으로 학습                ──→   학습된 정책을 BT로 대체
자체 Tacview ACMI 스트리밍       ──→   동일 프로토콜 채용 (포트 42674)
훈련/평가 파이프라인              ──→   대회/매치 실행 파이프라인
```

**핵심 차이**: LAG은 RL **훈련**이 목적, ai-combat-sdk는 BT 에이전트 **경쟁 매치**가 목적.
JSBSim 물리 엔진과 Tacview ACMI 프로토콜은 공유.

**다음 목표**: 두 프로젝트의 시뮬레이션 루프 → **CesiumJS 브라우저 뷰어**로 실시간 시각화.

---

# 현재 구현 현황 및 남은 TODO

## 완료된 작업 ✅

| 파일 | 내용 |
|------|------|
| `src/visualization/cesium_ws_server.py` | JSBSim → WebSocket 브로드캐스트 서버 (asyncio 백그라운드 스레드) |
| `src/match/runner.py` | `--cesium` 플래그, step_hook에서 broadcast_from_env 호출, pacing sleep 추가 |
| `scripts/run_match.py` | `--cesium`, `--cesium-port`, `--serve-static`, `--static-port` CLI 인수 |
| `web-flight-simulator/src/network/wsClient.js` | WS 싱글톤 클라이언트 (자동 재연결) |
| `web-flight-simulator/src/main.js` | WS 연결 시 JSBSim 외부 제어 모드 if/else 분기 |
| `web-flight-simulator/src/systems/npcSystem.js` | `updateExternal()`, `_updateMeshMatrix()` 추가 |
| `requirements.txt` | `websockets>=12.0` 추가 |
| `web-flight-simulator/DEPLOY.md` | 개발/배포 실행 가이드 |

**실행 명령:**
```bash
# Terminal 1
cd ai-combat-sdk
python scripts/run_match.py --agent1 eagle1 --agent2 simple_fighter --cesium

# Terminal 2
cd web-flight-simulator
npm run dev
# → http://localhost:5173 열고 Start 클릭
```

---

## Clone 후 초기 세팅 (신규 환경)

```bash
git clone https://github.com/JoonHaJang/ai-combat-sdk.git
cd ai-combat-sdk

# Python 의존성
pip install -r requirements.txt

# Node.js 의존성
cd web-flight-simulator
npm install

# Cesium ion 토큰 설정 (필수)
# https://ion.cesium.com → Access Tokens → Default Token 복사
echo "VITE_CESIUM_TOKEN=여기에_토큰_붙여넣기" > .env
```

### Cesium ion 토큰 위치

| 항목 | 경로 |
|------|------|
| 토큰 파일 | `web-flight-simulator/.env` |
| 변수명 | `VITE_CESIUM_TOKEN=eyJh...` |
| GitHub 제외 | `.gitignore`에 등록 — 자동으로 push 안 됨 (보안) |
| 발급 URL | https://ion.cesium.com/tokens |

> `.env` 파일은 clone 후 수동으로 생성해야 합니다. 없으면 Cesium 지형/위성이 로드되지 않습니다.

---

## 남은 TODO (우선순위 순)

### 🔴 P0 — 전투기 모델 미표시 버그 수정 (핵심 크래시 버그)

**파일:** `web-flight-simulator/src/main.js`

**문제:** `update(dt)` 함수에서 `input`, `physicsResult`, `prevSpeed`가 `else` 블록 안에 `const`로 선언되어, WS 연결 시 블록 밖에서 ReferenceError 발생 → 렌더 루프 크래시 → 기체 모델 미표시

**수정:**
1. `update(dt)` 첫 줄에 `let` 선언 3개를 if/else 밖으로 이동:
   ```js
   let prevSpeed = state.speed;
   let physicsResult = { isBoosting: false, boostDuration: 1, boostTimeRemaining: 0, boostRotations: 0 };
   let input = { isDragging: false, roll: 0, pitch: 0, yaw: 0, cameraPitch: 0, cameraYaw: 0 };
   ```
2. WS if 블록 상단에 `input = controller.update();` 추가 (카메라 오빗 유지)
3. else 블록에서 `const input/physicsResult/prevSpeed` → `input/physicsResult/prevSpeed` (재선언 제거)

---

### 🔴 P0 — 자동 스폰 (Start 클릭 시 맵 선택 스킵)

**파일:** `web-flight-simulator/src/main.js`

**수정:**
1. 모듈 초기화 시점에 `connectWSClient('ws://localhost:8765')` 선호출 (WS 미리 연결)
2. `startBtn.onclick` 핸들러에서 WS 연결 확인 후 자동 스폰:
   ```js
   const wsState = getWSState();
   if (isWSConnected() && wsState && wsState.blue) {
       state.lon = wsState.blue.lon; state.lat = wsState.blue.lat;
       state.alt = wsState.blue.alt_m; state.heading = wsState.blue.heading;
       document.getElementById('confirmSpawnBtn').click();
   } else {
       enterSpawnPicking(false);
   }
   ```

---

### 🟡 P1 — NPC AI 대화창 및 랜덤 NPC 스폰 억제

**파일:** `web-flight-simulator/src/main.js`

`confirmSpawnBtn.onclick` 내 두 곳 수정:
```js
// NPC 랜덤 스폰 억제 (Red 기체는 JSBSim이 제어)
if (npcSystem && !isWSConnected()) {
    npcSystem.spawnNPC(state.lon, state.lat, state.alt);
}

// Tutorial dialogue 억제
if (dialogueSystem && !isWSConnected()) {
    dialogueSystem.start();
}
```

---

### 🟢 P2 — 향후 기능

| 기능 | 내용 |
|------|------|
| 다중 기체 지원 | 2v2 매치 시 4대 동시 표시 |
| 미사일 이벤트 시각화 | WEZ 발사/명중 파티클 효과 |
| 매치 종료 오버레이 | `done: true` 수신 시 승자 화면 표시 |
| ACMI 재생 모드 | 매치 후 `.acmi` 파일 브라우저 재생 |
| F-16 GLB 교체 | 현재 F-15 → F-16 모델로 교체 (Sketchfab/Blender) |

---

# JSBSim × Cesium JS 전투 시각화 — 프로젝트 조사 및 구현 계획

> 목적: Tacview 대체 / 경량 브라우저 기반 전투 시뮬 시각화
> cannibal_pipeline.py (BT 에이전트) + JSBSim 물리 → Cesium JS 시각화

---

## 1. 참조 프로젝트 목록

### 1-1. `dimartarmizi/web-flight-simulator` ★ 가장 중요
GitHub: https://github.com/dimartarmizi/web-flight-simulator
데모: https://flight.tarmizi.id

#### 핵심 구조
Three.js (로컬 좌표계, 기체 GLB 모델, 파티클)
  + CesiumJS (WGS84 지구, 지형 스트리밍, 위성영상)
  + Vite (번들러)

#### 참조할 점
| 항목 | 내용 |
|---|---|
| 하이브리드 렌더링 | CesiumJS 지형 + Three.js 기체 분리 구조 — 성능/정밀도 균형 |
| GLB 모델 사용 | Sketchfab F-15 low-poly GLB → F-16 GLB도 동일 방식 적용 가능 |
| 전술 HUD 완성 | 피치 래더, 헤딩 테이프, 고도/속도, 무장 상태, 미니맵 코드 있음 |
| 무기 시스템 | AIM-9 락온, M61 기관포, 플레어 카운터메저 구현 완료 |
| 파티클 효과 | 애프터버너 화염, 폭발 Three.js 구현 |
| 오디오 | GPWS "PULL UP", RWR 경보음, 엔진 루프 |
| 설치 간단 | npm install → npm run dev |

#### 준비할 것
- [ ] Node.js 18+ 설치
- [ ] Cesium ion 계정(무료) + Access Token
- [ ] F-16 GLB 모델 (Sketchfab 또는 Blender 익스포트)

#### 구현 필요한 부분
- [ ] 내장 물리 → JSBSim WebSocket 수신으로 교체
- [ ] 단일 기체 → 다중 기체 (아군/적기)
- [ ] NPC AI(미개발) → cannibal_pipeline BT 에이전트 연결
- [ ] ACMI 녹화/재생 기능 추가

---

### 1-2. `dpculp/qtjsbsim` ★ JSBSim-Cesium 연동 레퍼런스
GitHub: https://github.com/dpculp/qtjsbsim
라이선스: GPLv3

#### 핵심 구조
Qt5 입력 → UDP → JSBSim FDM → UDP → CesiumJS Viewer

#### 참조할 점
| 항목 | 내용 |
|---|---|
| JSBSim ↔ Cesium 연동 완성 | UDP 소켓으로 위치/자세 실시간 전송 — 검증된 구조 |
| JSBSim pause/resume | 시뮬 제어 참조 가능 |
| ILS / Flight Path Marker | 항법 HUD 요소 코드 |

#### 구현 필요한 부분
- [ ] Qt 의존성 제거 → Python FastAPI + WebSocket으로 경량화
- [ ] 단순 OTW → 전술 HUD + 다중 기체 확장

---

### 1-3. `Aterfax/Node.js-DCS-WebGCI` ★ ACMI→Cesium 레퍼런스
GitHub: https://github.com/Aterfax/Node.js-DCS-WebGCI

#### 핵심 구조
Tacview ACMI 출력 → Node.js 파싱 → CesiumJS 실시간 표시

#### 참조할 점
- Tacview 없이 브라우저에서 ACMI 재생 완성 구조
- servers.json으로 다중 서버 정의, delay 변수로 타이밍 제어

#### 구현 필요한 부분
- [ ] cannibal_pipeline → ACMI 출력 모듈 추가
- [ ] JSBSim용 ACMI 변환기 작성

---

### 1-4. `pyacmi` — Python ACMI 파서
GitHub: https://github.com/wangtong2015/pyacmi
설치: pip install pyacmi

- ACMI 2.2 완전 파싱 (위치/속도/자세/이벤트)
- cannibal_pipeline과 같은 Python — 연동 단순

#### 구현 필요한 부분
- [ ] JSBSim 출력 → ACMI 2.2 직렬화 함수 작성

---

### 1-5. Cesium 공식 Flight Tracker 튜토리얼
URL: https://cesium.com/learn/cesiumjs-learn/cesiumjs-flight-tracker/

- SampledPositionProperty: 타임스탬프 기반 보간 → 부드러운 이동
- 타임라인 스크럽 UI 내장
- Cesium ion 무료 지형 스트리밍

---

## 2. GLB 모델 소스

| 소스 | URL | 비고 |
|---|---|---|
| Sketchfab | https://sketchfab.com | "F-16 glb free", CC 라이선스 필터 |
| NASA 3D Resources | https://nasa3d.arc.nasa.gov | 공공도메인 |
| Blender → GLB | 기존 F-16 .blend 파일 | 최고품질 ★ 권장 |

### Blender → GLB 익스포트
File → Export → glTF 2.0 (.glb)
  ✅ Format: GLB
  ✅ Apply Modifiers
  ✅ Include Textures / Normals
  ✅ Draco 압축
  ✅ Forward: -Y / Up: Z  ← Three.js 좌표계

---

## 3. 목표 아키텍처
```
cannibal_pipeline.py (JSBSim + BT 에이전트)
    ↓ WebSocket JSON 30Hz
Python FastAPI 서버 (ACMI 기록 + 브로드캐스트)
    ↓ ws://localhost:8000/ws
브라우저 뷰어 (web-flight-simulator 기반)
  ├── CesiumJS: 한반도 위성지형 + WGS84
  ├── Three.js: F-16 GLB + 파티클
  ├── 전술 HUD: 속도/고도/G/AOA/교전거리
  └── 시점: F1 Chase / F2 Cockpit / F3 Padlock / F4 탑뷰 / F5 자유
    ↓ (임무 종료 후)
ACMI 재생기: pyacmi → SampledPositionProperty → 타임라인 스크럽
```

---

## 4. 구현 로드맵

| Phase | 내용 | 기간 |
|---|---|---|
| 1 | web-flight-simulator 클론 + F-16 GLB + Cesium 토큰 | 1~2일 |
| 2 | Python FastAPI WebSocket + JSBSim 물리 루프 연결 | 2~3일 |
| 3 | 다중 기체 + BT 에이전트 + 궤적 LineString + 시점 전환 | 3~5일 |
| 4 | 전술 HUD + 레이더 반경 + 미사일 이벤트 시각화 | 3~4일 |
| 5 | ACMI 녹화/재생 + 타임라인 스크럽 UI | 2~3일 |

---

## 5. 설치 체크리스트
```bash
# Python
pip install jsbsim fastapi uvicorn websockets pyacmi

# Node.js
git clone https://github.com/dimartarmizi/web-flight-simulator.git
cd web-flight-simulator
npm install
echo "VITE_CESIUM_TOKEN=your_token" > .env
npm run dev
```

---

## 6. 핵심 판단

| 항목 | 결론 |
|---|---|
| Tacview 대체? | 재생/궤적 ✅, 전술 수치 HUD는 직접 구현 |
| GPU 필요? | WebGL 수준 — 내장 그래픽으로 동작 |
| GLB 품질? | Sketchfab 무료도 충분, Blender 변환 시 최상 |
| 개발 기간? | Phase 1~2: 1주, 전체: 3~4주 |
| 핵심 참조 | web-flight-simulator (렌더링) + QtJSBSim (연동) |