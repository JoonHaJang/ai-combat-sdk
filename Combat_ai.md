# Combat AI — 아키텍처 & 도그파이트 플레이그라운드 문서

> 작성일: 2026-03-28
> 대상: ai-combat-sdk 기반 도그파이트 플레이그라운드 구축 및 JSBSim 6DOF 검증

---

## 1. 시스템 전체 아키텍처

```
┌─────────────────────────────────────────────────────────────────┐
│                        ai-combat-sdk                            │
│                                                                 │
│  scripts/run_match.py --agent1 eagle1 --agent2 simple --cesium  │
│         │                                                       │
│         ▼                                                       │
│  BehaviorTreeMatch (src/match/runner.py)                        │
│    ├─ MatchCore (.pyd — Cython 보호)                            │
│    │    ├─ BT1.tick() → action [alt_idx, hdg_idx, vel_idx]     │
│    │    ├─ BT2.tick() → action [alt_idx, hdg_idx, vel_idx]     │
│    │    └─ JSBSim env.step() → 6DOF 물리 업데이트              │
│    │                                                            │
│    └─ step_hook (매 스텝 콜백)                                  │
│         ├─ CSV 로그 기록                                        │
│         ├─ CesiumWSServer.broadcast_from_env() ──────────────┐  │
│         ├─ FlightGearVis.send_state()                        │  │
│         └─ MatchVisualizer.update() (Dogfight2)              │  │
│                                                              │  │
└──────────────────────────────────────────────────────────────┼──┘
                                                               │
                    ws://localhost:8765  ◄─────────────────────┘
                          │
                          ▼
        ┌────────────────────────────────────────┐
        │      web-flight-simulator (브라우저)    │
        │                                        │
        │  wsClient.js → WS 수신                 │
        │    └─ npcSystem.updateExternal()        │
        │         └─ _updateMeshMatrix()          │
        │              └─ Three.js 3D 렌더링      │
        │                 (roll, pitch, heading)  │
        └────────────────────────────────────────┘
```

### 핵심 데이터 흐름 요약

```
JSBSim 6DOF 물리
    └─► AircraftSimulator.get_geodetic() → (lon, lat, alt_m)
    └─► AircraftSimulator.get_rpy()      → (roll_r, pitch_r, yaw_r)
    └─► AircraftSimulator.get_velocity() → (vn, ve, vu) m/s
          │
          ▼
    _get_agent_state() → JSON dict
          │
          ▼
    CesiumWSServer.broadcast() → ws:// → 브라우저 → Three.js
```

---

## 2. 교전 규칙 (ai-combat-sdk 기준)

### 2.1 고수준 액션 공간 (5×9×5 = 225가지)

모든 BT 액션 노드는 내부적으로 아래 3개의 이산 인덱스를 환경에 전달합니다.

| 축 | 크기 | 인덱스 → 의미 |
|----|------|---------------|
| **delta_altitude** | 5 | 0=급하강, 1=하강, 2=유지, 3=상승, 4=급상승 |
| **delta_heading**  | 9 | 0=급좌(-90°) ~ 4=직진(0°) ~ 8=급우(+90°) |
| **delta_velocity** | 5 | 0=급감속, 1=감속, 2=유지, 3=가속, 4=급가속 |

### 2.2 저수준 제어 (JSBSim 입력)

고수준 액션 → JSBSim 저수준 제어 변환:

| 저수준 채널 | 범위 | 의미 |
|------------|------|------|
| `aileron`  | −1.0 ~ +1.0 | 롤 제어 |
| `elevator` | −1.0 ~ +1.0 | 피치 제어 |
| `rudder`   | −1.0 ~ +1.0 | 요 제어 |
| `throttle` | 0.0 ~ 1.0   | 추력 |

### 2.3 종료 조건 (Termination Conditions)

| 조건 | 결과 |
|------|------|
| 고도 < Hard Deck (1000 ft) | 해당 기체 즉시 패배 |
| 체력 0 (HP = 0) | 해당 기체 패배 |
| max_steps 초과 (기본 1500) | 보상 합 기준 판정 |
| 시간초과 동점 | draw |

### 2.4 보상 함수

- WEZ(무장 유효 사거리) 진입 시 포지티브 보상
- 피격 시 네거티브 보상
- Hard Deck 위반 시 대형 페널티
- 매 스텝 CSV `reward` 컬럼에 기록됨

---

## 3. BT 노드 전체 레퍼런스

### 3.1 복합 노드 (Composites)

| 노드 | 논리 | 설명 |
|------|------|------|
| `Selector` | OR | 자식 중 하나 SUCCESS → 전체 SUCCESS |
| `Sequence` | AND | 모든 자식 SUCCESS → 전체 SUCCESS |

---

### 3.2 조건 노드 (Conditions)

#### 거리 조건

| 노드 | 기본값 | 파라미터 | 설명 |
|------|--------|---------|------|
| `EnemyInRange` | `max_distance_ft=16404` | `max_distance_ft` (ft) | 적 거리 < 임계값 |
| `DistanceBelow` | `threshold_ft=9843` | `threshold_ft` (ft) | 거리 < 임계값 |
| `DistanceAbove` | `threshold_ft=6562` | `threshold_ft` (ft) | 거리 > 임계값 |

#### 고도/속도 조건

| 노드 | 기본값 | 파라미터 | 설명 |
|------|--------|---------|------|
| `AltitudeAbove` | `min_altitude_ft=9843` | `min_altitude_ft` (ft) | 고도 ≥ 지정값 |
| `AltitudeBelow` | `min_altitude_ft=3281` | `min_altitude_ft` (ft) | 고도 ≤ 지정값 |
| `BelowHardDeck` | `threshold_ft=1000` | `threshold_ft` (ft) | **Hard Deck 위반 감지 — 최상단 필수** |
| `VelocityAbove` | `min_velocity_kts=389` | `min_velocity_kts` (kts) | 속도 ≥ 지정값 |
| `VelocityBelow` | `max_velocity_kts=778` | `max_velocity_kts` (kts) | 속도 ≤ 지정값 |

> ⚠️ **Hard Deck**: 1000ft 이하 즉시 패배. BT 최상단에 `BelowHardDeck + ClimbTo` 반드시 배치.

#### BFM 상황 분류 조건

| 노드 | 분류 기준 | 설명 |
|------|----------|------|
| `IsOffensiveSituation` | ATA<45°, AA<100°, 거리 0.3~3NM + 에너지 우세 | OBFM — 공격 유리 |
| `IsDefensiveSituation` | AA>90°, ATA>60° 또는 에너지 열세+접근 중 | DBFM — 방어 필요 |
| `IsNeutralSituation` | HCA>90° 또는 원거리 또는 2-circle 선회 | HABFM — 정면/대등 |

#### 각도 조건

| 노드 | 기본값 | 파라미터 | 설명 |
|------|--------|---------|------|
| `ATAAbove` | `threshold_deg=60` | `threshold_deg` (°) | ATA > 임계값 (적이 측면/후방) |
| `ATABelow` | `threshold_deg=30` | `threshold_deg` (°) | ATA < 임계값 (적이 전방) |
| `UnderThreat` | `aa_threshold_deg=120` | `aa_threshold_deg` (°) | AA > 임계값 (위험 노출) |
| `LOSAbove` | `threshold_deg=15` | `threshold_deg` (°) | LOS 각도 > 임계값 |
| `LOSBelow` | `threshold_deg=15` | `threshold_deg` (°) | LOS 각도 < 임계값 |
| `InEnemyWEZ` | `max_distance_ft=9843`, `max_los_angle_deg=30` | 두 파라미터 | 적 WEZ 내 위치 |

> **각도 정의**
> `ATA`: 0°=적 정면, 90°=적 측면, 180°=적 후방 (내 기수 기준 적 위치)
> `AA`: 0°=내가 적 후방(안전), 180°=내가 적 정면(위험) (적 기수 기준 내 위치)

#### 에너지 조건

| 노드 | 기본값 | 파라미터 | 설명 |
|------|--------|---------|------|
| `EnergyHighPs` | `threshold_fts=0` | `threshold_fts` | Ps(비잉여동력) > 임계값 |
| `SpecificEnergyAbove` | `threshold_ft=16404` | `threshold_ft` (ft) | He = h + v²/2g ≥ 임계값 |
| `IsMerged` | `merge_threshold_ft=1640` | `merge_threshold_ft` (ft) | 근접 교전 거리 이하 |
| `IsEnergyAdvantage` | — | — | 종합 에너지 우세 |
| `IsAltAdvantage` | — | — | 고도 우세 (내 고도 > 적) |
| `IsSpdAdvantage` | — | — | 속도 우세 (내 속도 > 적) |
| `EnergyDiffAbove` | `threshold_ft=1640` | `threshold_ft` (ft) | 에너지 차이 > 임계값 |

#### 전술 상태 조건 (UE4 BT 기반)

| 노드 | 설명 |
|------|------|
| `Is39Line` | 적이 내 3-9 라인 안 (ATA < 90°) — 공격 우위 위치 |
| `IsOvershootRisk` | 오버슈트 위험 (빠른 접근 + 근거리 + 낮은 선회율) |
| `IsTargetInSight` | 적이 시야 내 (ATA < 90°) |
| `IsOneCircle` | 1-circle 선회 (HCA < 90°, 같은 방향) |
| `IsTwoCircle` | 2-circle 선회 (HCA > 90°, 반대 방향) |

#### 접근/선회율 조건

| 노드 | 기본값 | 파라미터 | 설명 |
|------|--------|---------|------|
| `ClosureRateAbove` | `threshold_kts=97.2` | `threshold_kts` | 접근 속도 > 임계값 (양수=접근 중) |
| `ClosureRateBelow` | `threshold_kts=0` | `threshold_kts` | 멀어지는 중 감지 |
| `TurnRateAbove` | `threshold_degs=5` | `threshold_degs` (°/s) | 선회율 > 임계값 |

---

### 3.3 액션 노드 (Actions)

#### 기본 기동

| 노드 | 내부 액션 (alt,hdg,vel) | 설명 |
|------|------------------------|------|
| `MaintainAltitude` | (2, 4, 2) | 모두 유지 |
| `Accelerate` | (2, 4, 4) | 급가속 |
| `Decelerate` | (2, 4, 0) | 급감속 |
| `Straight` | (2, 4, 2) | 직진 유지 |
| `TurnLeft` | (2, 2, 2) / (2, 0, 2) | 중좌회전 / `intensity="hard"` 시 급좌회전 |
| `TurnRight` | (2, 6, 2) / (2, 8, 2) | 중우회전 / `intensity="hard"` 시 급우회전 |

#### 고도 기동

| 노드 | 기본값 | 파라미터 | 설명 |
|------|--------|---------|------|
| `ClimbTo` | `target_altitude_ft=19685` | `target_altitude_ft` (ft) | 목표 고도로 상승 |
| `DescendTo` | `target_altitude_ft=13123` | `target_altitude_ft` (ft) | 목표 고도로 하강 |
| `AltitudeAdvantage` | `target_advantage_ft=1640` | `target_advantage_ft` (ft) | 적보다 지정 고도 우위 유지 |

#### 추적 기동 (OBFM)

| 노드 | 설명 |
|------|------|
| `Pursue` | 거리·고도·방위·ATA 종합 판단, 최적 기동 자동 선택 |
| `LeadPursuit` | relative_bearing + ATA 기반 선도 추적 — Gun WEZ 진입 최적화 |
| `PurePursuit` | side_flag 기반 현재 위치 직접 추적 |
| `LagPursuit` | tau_deg 기반 적 후방 추적 — 오버슈트 방지 |

**`Pursue` 주요 파라미터:**

| 파라미터 | 기본값 | 설명 |
|---------|--------|------|
| `close_range_ft` | 6562 ft | 근중거리 판정 |
| `very_close_range_ft` | 4921 ft | 근거리 판정 |
| `far_range_ft` | 13123 ft | 원거리 판정 (급가속) |
| `bearing_straight_deg` | 5° | 직진 판정 방위각 |
| `bearing_hard_deg` | 60° | 급회전 판정 방위각 |
| `ata_lost_deg` | 60° | 적 놓침 판정 ATA |

#### 방어 기동 (DBFM)

| 노드 | 설명 |
|------|------|
| `DefensiveManeuver` | AA 기반 자동 회피 — critical/danger 단계 구분 |
| `BreakTurn` | side_flag 반대 방향 급선회 + 하강 + 급가속 |
| `DefensiveSpiral` | 강선회 + 고도 조절 + 급가속 나선형 회피 |

**`DefensiveManeuver` 파라미터:**

| 파라미터 | 기본값 | 설명 |
|---------|--------|------|
| `critical_aa_threshold_deg` | 45° | 매우 위험 (이하 시 급회피) |
| `danger_aa_threshold_deg` | 90° | 위험 (이하 시 중간 회피) |
| `alt_gap_threshold_ft` | 492 ft | 고도 변경 임계값 |

#### 에너지 기동

| 노드 | 파라미터 | 설명 |
|------|---------|------|
| `ClimbingTurn` | `direction="left"/"right"/"auto"` | 상승하며 선회 (에너지 저장) |
| `DescendingTurn` | `direction="left"/"right"/"auto"` | 하강하며 선회 (속도 획득) |
| `BarrelRoll` | — | 나선형 상승↔하강 반복 회피 |
| `HighYoYo` | — | 급상승+급선회 → 하강+공격 (오버슈트 방지) |
| `LowYoYo` | — | 급하강+가속 → 상승+위치 우위 |

#### 정면 교전 기동 (HABFM)

| 노드 | 설명 |
|------|------|
| `OneCircleFight` | 적 방향 급선회 + 감속 (선회 우위 시) |
| `TwoCircleFight` | 적 반대 방향 약선회 + 급가속 (에너지 우위 시) |
| `GunAttack` | relative_bearing 기반 정밀 조준 (Gun WEZ: ±12°, 500~3000ft) |

#### UE4 BT 기반 지능형 액션

| 노드 | 설명 |
|------|------|
| `OvershootAvoidance` | 선회율<3°/s → HighYoYo, 빠른접근+근거리 → 즉시 감속+Lag |
| `EnergyFight` | 고도우세→하강공격, 속도우세→가속추격, 열세→상승회복 |
| `TCFight` | 1-circle→급선회+감속, 2-circle→에너지유지+재접근 |
| `Evade` | side_flag 반대 방향 강선회 + 가속 |

---

## 4. JSBSim 6DOF 상태 포맷

### 4.1 상태 추출 경로

```python
# src/visualization/cesium_ws_server.py — _get_agent_state()

lon, lat, alt_m  = agent.get_geodetic()   # degrees, degrees, meters
roll_r, pitch_r, yaw_r = agent.get_rpy()  # radians
vn, ve, vu = agent.get_velocity()         # m/s (North, East, Up)
speed_kts = sqrt(vn² + ve² + vu²) / 0.514444
```

### 4.2 WebSocket JSON 포맷

매 스텝 (기본 0.2초 = 5Hz) 브로드캐스트:

```json
{
  "t": 12.34,
  "blue": {
    "lon":       120.123456,
    "lat":       37.123456,
    "alt_m":     5000.0,
    "heading":   45.20,
    "pitch":     5.10,
    "roll":      15.00,
    "speed_kts": 350.5,
    "health":    85.0
  },
  "red": {
    "lon":       120.200000,
    "lat":       37.200000,
    "alt_m":     4800.0,
    "heading":   225.00,
    "pitch":     -2.50,
    "roll":      -30.00,
    "speed_kts": 320.0,
    "health":    100.0
  },
  "done":   false,
  "winner": null
}
```

### 4.3 필드 정의

| 필드 | 단위 | 설명 |
|------|------|------|
| `t` | 초 | 시뮬레이션 경과 시간 |
| `lon` | 도(°) | 경도 |
| `lat` | 도(°) | 위도 |
| `alt_m` | 미터 | WGS84 기준 고도 |
| `heading` | 도(°) | 기수 방향 (0=북, 90=동, 180=남) |
| `pitch` | 도(°) | 피치각 (양수=기수 상향) |
| `roll` | 도(°) | 롤각 (양수=우측 경사) |
| `speed_kts` | 노트 | 공간 속도 벡터 크기 |
| `health` | 0~100 | 현재 체력 |
| `done` | bool | 매치 종료 여부 |
| `winner` | null/"tree1"/"tree2"/"draw" | 승자 |

---

## 5. CSV 로그 컬럼 레퍼런스

`--log-csv` 옵션으로 생성되는 CSV 파일의 주요 컬럼:

| 컬럼 | 설명 |
|------|------|
| `step` | 스텝 번호 |
| `agent_id` | blue/red |
| `ego_altitude_ft` | 현재 고도 (ft) |
| `ego_vc_kts` | 기체 축 속도 (kts) |
| `roll_deg` | 롤각 (도) |
| `pitch_deg` | 피치각 (도) |
| `distance_ft` | 적과의 거리 (ft) |
| `ata_deg` | 각도 전방 (×180°) |
| `aa_deg` | 측방 각도 (×180°) |
| `hca_deg` | 수평 교차각 (×180°) |
| `closure_rate_kts` | 접근 속도 (kts) |
| `bfm_situation` | OBFM / DBFM / HABFM |
| `ego_health` | 자신 체력 |
| `enm_health` | 적 체력 |
| `reward` | 해당 스텝 보상 |
| `action_altitude` | 고도 액션 인덱스 (0~4) |
| `action_heading` | 방향 액션 인덱스 (0~8) |
| `action_velocity` | 속도 액션 인덱스 (0~4) |
| `aileron` | JSBSim 저수준 에일러론 |
| `elevator` | JSBSim 저수준 엘리베이터 |
| `throttle` | JSBSim 저수준 스로틀 |
| `active_node` | 마지막 SUCCESS BT 노드 |
| `active_nodes_path` | BT 실행 경로 (A>B>C) |

---

## 6. 에이전트 YAML 예시

### 6.1 simple — 입문용 (2노드)

```yaml
name: "simple"
version: "1.0.0"
description: "Hard Deck 회피 + 기본 추적만 하는 단순 전투기"

tree:
  type: Selector
  children:
    # 1. Hard Deck 회피 (필수)
    - type: Sequence
      children:
        - type: Condition
          name: BelowHardDeck
        - type: Action
          name: ClimbTo
          params:
            target_altitude_ft: 3000

    # 2. 기본 추적
    - type: Action
      name: Pursue
```

### 6.2 eagle1 — 균형 전투기 (5단계)

```yaml
name: "eagle1"
version: "1.0.0"
description: "균형잡힌 방어와 공격"

tree:
  type: Selector
  name: Eagle1_Root
  children:
    # 1. Hard Deck 위반 방지 (최우선)
    - type: Sequence
      children:
        - type: Condition
          name: BelowHardDeck
          params:
            threshold_ft: 1200
        - type: Action
          name: ClimbTo
          params:
            target_altitude_ft: 3000

    # 2. 위협 상황 대응
    - type: Sequence
      children:
        - type: Condition
          name: UnderThreat
          params:
            aa_threshold_deg: 120.0
        - type: Action
          name: DefensiveManeuver

    # 3. 고도 우위 확보
    - type: Sequence
      children:
        - type: Condition
          name: AltitudeBelow
          params:
            min_altitude_ft: 984
        - type: Action
          name: AltitudeAdvantage
          params:
            target_advantage_ft: 1312

    # 4. 근거리 공격
    - type: Sequence
      children:
        - type: Condition
          name: DistanceBelow
          params:
            threshold_ft: 8202
        - type: Action
          name: LeadPursuit

    # 5. 기본 추적
    - type: Action
      name: Pursue
```

### 6.3 BFM 풀 전술 에이전트 템플릿

```yaml
name: "bfm_full"
description: "BFM 상황 분류 기반 전술 에이전트"

tree:
  type: Selector
  children:
    # 1. Hard Deck (필수)
    - type: Sequence
      children:
        - type: Condition
          name: BelowHardDeck
        - type: Action
          name: ClimbTo
          params:
            target_altitude_ft: 3000

    # 2. 공격 유리 → 선도 추적
    - type: Sequence
      children:
        - type: Condition
          name: IsOffensiveSituation
        - type: Action
          name: LeadPursuit

    # 3. 방어 필요 → 급선회 회피
    - type: Sequence
      children:
        - type: Condition
          name: IsDefensiveSituation
        - type: Action
          name: BreakTurn

    # 4. 오버슈트 위험 → 자동 회피
    - type: Sequence
      children:
        - type: Condition
          name: IsOvershootRisk
        - type: Action
          name: OvershootAvoidance

    # 5. 에너지 우위 → 에너지 파이트
    - type: Sequence
      children:
        - type: Condition
          name: IsEnergyAdvantage
        - type: Action
          name: EnergyFight

    # 6. 기본 추적
    - type: Action
      name: Pursue
```

---

## 7. 도그파이트 플레이그라운드 실행 방법

### 7.1 CesiumJS 실시간 연동 (권장)

**이유**: JSON 포맷으로 디버깅 용이, `run_match.py --cesium` 한 줄로 전체 파이프라인 기동, 별도 앱 설치 불필요.

#### 터미널 1 — 매치 실행

```bash
cd c:\Users\USER\Desktop\ai-combat-sdk
python scripts/run_match.py --agent1 eagle1 --agent2 simple --cesium
```

#### 터미널 2 — 웹 뷰어 실행

```bash
cd c:\Users\USER\Desktop\ai-combat-sdk\web-flight-simulator
npm run dev
```

그다음 브라우저에서 `http://localhost:5173` 접속 → 게임 시작 → 두 기체가 실시간으로 움직임.

### 7.2 CSV 로그 + 시각화

```bash
# CSV 로그 저장 (logs/ 폴더 자동 생성)
python scripts/run_match.py --agent1 eagle1 --agent2 simple --log-csv --cesium

# 3라운드 연속 매치
python scripts/run_match.py --agent1 eagle1 --agent2 simple --rounds 3 --log-csv
```

### 7.3 에이전트 탐색 순서

`--agent1 <name>` 지정 시 탐색 순서:
1. `submissions/<name>/<name>.yaml`
2. `examples/<name>.yaml`
3. `examples/<name>/<name>.yaml`

### 7.4 기타 시각화 옵션

| 옵션 | 설명 |
|------|------|
| `--dogfight2` | Dogfight2 3D 시각화 (별도 앱 실행 필요) |
| `--flightgear` | FlightGear 실시간 UDP 시각화 |
| `--tacview-realtime` | Tacview 실시간 TCP 스트리밍 (포트 42674) |
| `--cesium` | CesiumJS WebSocket (포트 8765) |

---

## 8. JSBSim 6DOF 실시간 검증 체크리스트

### 8.1 기본 연결 검증

- [ ] `run_match.py --cesium` 실행 시 콘솔에 `[CesiumWS] ws://localhost:8765` 출력 확인
- [ ] 브라우저 DevTools Network 탭 → WS 프레임 수신 확인
- [ ] JSON 패킷에 `blue`, `red` 각각 `lon`, `lat`, `alt_m`, `roll`, `pitch`, `heading` 포함 확인

### 8.2 6DOF 동기화 검증

| 검증 항목 | 방법 | 기대 결과 |
|----------|------|---------|
| **Roll 동기화** | eagle1이 `BreakTurn` 실행 시 | 웹 뷰어 기체 roll 값 변화 (≤200ms) |
| **Roll 15° 테스트** | eagle1 BT에 `TurnLeft` 고정 | `roll_deg` 컬럼 −15° 전후 수렴 |
| **Pitch 동기화** | `ClimbTo` 실행 시 | `pitch` 양수로 변화 |
| **Heading 동기화** | `Pursue` 실행 시 | `heading`이 적 방향으로 수렴 |
| **Altitude 동기화** | `ClimbTo 3000` 실행 시 | `alt_m` 증가 → 약 914m 수렴 |
| **Speed 동기화** | `Accelerate` 실행 시 | `speed_kts` 증가 |

### 8.3 BT 노드 활성화 검증

```bash
# CSV 로그로 active_node 컬럼 확인
python scripts/run_match.py --agent1 eagle1 --agent2 simple --log-csv logs/

# logs/ 폴더의 CSV 파일 열어 확인
# active_node 컬럼: BelowHardDeck, ClimbTo, Pursue 등 전환 확인
```

- [ ] 초기 고도 낮을 때 → `active_node = ClimbTo` 확인
- [ ] 정상 고도 이후 → `active_node = Pursue` 전환 확인
- [ ] `bfm_situation` 컬럼이 OBFM/DBFM/HABFM으로 변화 확인

### 8.4 blue/red 독립 6DOF 검증

- [ ] `blue.roll` ≠ `red.roll` (서로 다른 기동)
- [ ] `blue.heading`과 `red.heading`이 상호 추적하며 변화
- [ ] 웹 뷰어에서 두 기체가 독립적으로 roll/pitch 표현

### 8.5 타이밍 검증

- 스텝 간격: 기본 `time_interval = 0.2s` (5Hz)
- WS 브로드캐스트: 각 스텝 후 0.2s sleep → 실시간과 동기
- 브라우저 렌더링 지연: Three.js 60fps 기준 ≤16ms
- **총 지연 허용값: ≤200ms** (물리 → JSON → WS → Three.js)

---

## 9. 핵심 파일 경로 인덱스

| 파일 | 역할 |
|------|------|
| `scripts/run_match.py` | CLI 매치 실행 진입점 |
| `src/match/runner.py` | BT 매치 오케스트레이션 + CSV/WS/FG 훅 |
| `src/match/runner_core.pyd` | 핵심 매치 로직 (Cython 보호) |
| `src/behavior_tree/*.pyd` | BT 엔진 (Cython 컴파일) |
| `src/visualization/cesium_ws_server.py` | WebSocket JSON 브로드캐스트 서버 |
| `src/visualization/match_visualizer.py` | Dogfight2 3D 시각화 클라이언트 |
| `src/visualization/flightgear_vis.py` | FlightGear UDP + Tacview TCP 스트리머 |
| `examples/simple.yaml` | 입문용 BT 에이전트 (2노드) |
| `examples/eagle1/eagle1.yaml` | 균형 BT 에이전트 (5단계) |
| `examples/aggressive.yaml` | 공격형 에이전트 |
| `examples/defensive.yaml` | 방어형 에이전트 |
| `examples/ace.yaml` / `examples/ace/ace.yaml` | 고급 에이전트 |
| `docs/NODE_REFERENCE.md` | BT 노드 전체 레퍼런스 (원본) |
| `docs/GUIDE.md` | 참가자 가이드 |
| `web-flight-simulator/src/network/wsClient.js` | WS 클라이언트 (브라우저) |
| `web-flight-simulator/src/systems/npcSystem.js` | 외부 상태 → 3D 메시 변환 |
| `web-flight-simulator/src/world/cesiumWorld.js` | CesiumJS 뷰어 초기화 |
| `LAG/envs/JSBSim/core/simulatior.py` | AircraftSimulator 6DOF 추출 |
| `Combat_ai.md` | 이 문서 |

---

## 10. Blackboard 관측값 요약

BT 조건/액션 노드에서 `observation` 딕셔너리로 접근 가능한 값:

### 자기 상태
- `ego_altitude_ft`: 현재 고도 (ft)
- `ego_vc_kts`: 기체 축 속도 (kts)
- `roll_deg`, `pitch_deg`: 자세각
- `specific_energy_ft`: 비에너지 He = h + v²/2g (ft)
- `ps_fts`: 비잉여동력 Ps (ft/s)

### 교전 기하학
- `distance_ft`: 적과의 거리 (ft)
- `ata_deg`: ATA × 180° (0=정면, 1=후방)
- `aa_deg`: AA × 180°
- `hca_deg`: HCA × 180° (수평 교차각)
- `relative_bearing_deg`: 상대 방위각 × 180°
- `closure_rate_kts`: 접근 속도 (양수=접근)
- `turn_rate_degs`: 선회율 (°/s)
- `alt_gap_ft`: 고도 차이 (ft)
- `in_39_line`: 3-9 라인 내 여부 (bool)
- `overshoot_risk`: 오버슈트 위험 (bool)
- `side_flag`: 적의 측면 방향 (−1/+1)

### 전술 분류
- `bfm_situation`: "OBFM" / "DBFM" / "HABFM"
- `tc_type`: 선회 유형 ("one_circle" / "two_circle")
- `energy_advantage`: 에너지 우세 여부 (bool)
- `alt_advantage`: 고도 우세 여부 (bool)
- `spd_advantage`: 속도 우세 여부 (bool)

### 전투 상태
- `ego_health`, `enm_health`: 체력 (0~100)
- `in_wez`: 내가 WEZ 내에 있음 (bool)
- `enm_in_wez`: 적이 WEZ 내에 있음 (bool)

---

## 11. 웹 뷰어 렌더링 아키텍처 심층 분석

> `web-flight-simulator/src/` 전체 구조 및 렌더링 파이프라인.

---

### 11.1 이중 캔버스 렌더링 구조

```
┌─────────────────────────────────────────────────────────┐
│  브라우저 뷰포트                                           │
│                                                          │
│  ┌─────────────────────────────────────────────────────┐ │
│  │  #cesiumContainer  (배경)                            │ │
│  │  Cesium.Viewer                                       │ │
│  │  ├─ 지구 구체 + 지형                                  │ │
│  │  ├─ Cesium Entity 폴리라인 (CesiumTrail)             │ │
│  │  └─ 스카이박스 + 대기                                  │ │
│  └─────────────────────────────────────────────────────┘ │
│                                                          │
│  ┌─────────────────────────────────────────────────────┐ │
│  │  #threeContainer  (오버레이, alpha: true)            │ │
│  │  THREE.WebGLRenderer — TWO-PASS RENDERING            │ │
│  │  ├─ Pass 1 (layer 0): 빈 씬, Cesium FOV 동기화       │ │
│  │  ├─ clearDepth()                                     │ │
│  │  └─ Pass 2 (layer 1, FOV=75°고정): 항공기 3D 메시    │ │
│  └─────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────┘
```

**렌더링 루프** (`main.js:1018`, `animate()`):
```js
// Pass 1 — layer 0 (Cesium와 FOV 동기화, 배경과 FOV를 맞추기 위해)
renderer.autoClear = false;
renderer.clear();
camera.fov = Cesium.Math.toDegrees(viewer.camera.frustum.fovy);
camera.layers.set(0);
renderer.render(scene, camera);

// Pass 2 — layer 1 (항공기 모델, FOV 고정 75°)
renderer.clearDepth();   // 깊이만 초기화, 색상 유지
camera.fov = 75;         // 항공기 모델 전용 고정 FOV
camera.layers.set(1);
renderer.render(scene, camera);
```

> **핵심**: Three.js `alpha: true` + `clearColor(0,0,0,0)` → 투명 오버레이.
> CesiumTrail 폴리라인은 Cesium 캔버스에 렌더링 → Three.js 투명 영역을 통해 보임.

---

### 11.2 카메라 시스템 완전 분석

#### 카메라 방향 쿼터니언 합성 (`main.js:784–810`)

```
state.heading/pitch/roll (JSBSim or 내부 물리)
        │
        ▼
planeQuat = Quaternion.fromHPR(heading, pitch, roll)
        │
        +── orbitQuat = Quaternion.fromHPR(cameraYaw, -cameraPitch, 0)
        │   (마우스 우클릭 드래그로 누적, 손 떼면 lerp→0 복귀)
        │
        ▼
finalQuat = planeQuat × orbitQuat
        │
        ▼
finalHPR = HeadingPitchRoll.fromQuaternion(finalQuat)
        │
        ├─► state.cameraRoll = toDegrees(finalHPR.roll)  ← HUD 크로스헤어용
        │
        └─► setCameraToPlane(lon, lat, alt,
                finalHPR.heading, finalHPR.pitch, finalHPR.roll,
                cameraMode === 'third')
```

#### setCameraToPlane 내부 동작 (`cesiumWorld.js:144`)

```js
// thirdPerson=true 시 (cameraMode==='third')
// 카메라를 항공기 뒤 500m + 위 80m로 오프셋
destLon  = lon - sin(heading_rad) * 500 / (111320 * cos(lat_rad))
destLat  = lat - cos(heading_rad) * 500 / 111320
destAlt  = alt + 80
destPitch = pitch - atan2(80, 500) * (180/π)   // ≈ pitch - 9.1°
//
// → 항공기 ~ 카메라 사이 500m 구간의 CesiumTrail이 시야에 들어옴
```

| 모드 | 키 | Cesium 카메라 위치 | planeModel |
|------|----|--------------------|------------|
| `third` | C | 항공기 뒤 500m + 위 80m | ✓ 표시 |
| `first` | C | 항공기 위치 그대로 | ✗ 숨김 |
| `overview` | Tab | 두 기체 중점 위 (dist×0.6) | ✗ 숨김 |

#### HUD 크로스헤어 롤 동기화

```js
// JSBSim state.roll vs 실제 카메라 roll은
// 고피치각(짐발락)에서 최대 90° 이상 차이 발생
state.cameraRoll = Cesium.Math.toDegrees(finalHPR.roll);  // 실제 카메라 롤

// hud.js
this.smoothedRoll = lerpAngle(this.smoothedRoll, state.cameraRoll ?? state.roll, lerpFactor);
```

---

### 11.3 NPC/플레이어 모델 좌표 시스템

#### 플레이어 모델 — Three.js 카메라 공간 고정

```
GLB 로드
  → Box3 계산 → mesh.position.sub(center) [원점 정렬]
  → mesh.rotation.y = π/2               [노즈 +X 방향]
  → autoScale = 4.6 / maxDim            [최대 축 = 4.6 유닛]
  → planeModel.position = (0.75, 0.8, -3.0)  [화면 우상단, 카메라 앞 3유닛]
  → layers.set(1)                        [Pass 2 전용]
```

| 변수 | 값 | 의미 |
|------|-----|------|
| `BASE_PLANE_POS` | `(0.75, 0.8, -3.0)` | 카메라 공간 고정 위치 |
| `autoScale` | `4.6 / maxDim` | 화면 크기 정규화 |
| `rotation.y` | `π/2` | GLB 노즈 정렬 |

> planeModel은 **Cesium viewMatrix 미적용** — 카메라가 이동해도 같은 화면 위치.
> NPC 모델과 달리 항상 동일한 화면 좌표에 렌더링됨.

#### NPC 모델 — Cesium 월드 공간 → Three.js 변환

```
ECEF(lon, lat, alt)
  → headingPitchRollToFixedFrame()  [Cesium ENU: X=East, Y=North, Z=Up]
  → modelMatrix (4×4)
  × viewMatrix (Cesium 카메라 역변환)
  → cameraSpaceMatrix → mesh.matrix
```

```js
// npcSystem.js:209 — Cesium HPR ↔ 항공기 관례 좌표 스왑
scratchHPR.heading = toRadians(npc.heading);
scratchHPR.pitch   = toRadians(npc.roll);    // ← roll → pitch 슬롯
scratchHPR.roll    = toRadians(npc.pitch);   // ← pitch → roll 슬롯

// 모델 로드 시 회전
model.rotation.x = Math.PI / 2;  // ENU Z-Up → Three.js Y-Up
model.rotation.y = Math.PI / 2;  // 노즈 방향 정렬
model.scale.set(1.0, 1.0, 1.0);  // GLB 원본 크기 (1 unit ≈ 1m 기준)
```

#### GLB 모델 분석 및 스케일 튜닝

| 측정값 | 계산식 | 결과 |
|--------|--------|------|
| GLB maxDim | `4.6 / autoScale` | ≈ 150.9 GLB 단위 |
| 플레이어 스케일 팩터 | `4.6 / 150.9` | ≈ 0.0305 |
| NPC 기본 스케일 | `1.0` | GLB 단위 = m 가정 |

**NPC 가시성 조정** (GLB 단위가 cm인 경우 모델이 너무 작음):
```js
// npcSystem.js:67 수정
model.scale.set(5.0, 5.0, 5.0);   // 실험적으로 조정
```

**GLB 단위 확인법**: 모델 로드 콜백에 추가:
```js
const size = box.getSize(new THREE.Vector3());
console.log('F-16 GLB size (units):', size);
// x≈15, y≈5, z≈15 → 1 unit = 1m (실제 F-16 크기)
// x≈1500 → 1 unit = 0.01m (cm 단위, scale*100 필요)
```

---

### 11.4 경로 Trail 시스템 (CesiumTrail)

**현재 구현**: `cesiumTrail.js` — Cesium 엔티티 폴리라인 (ECEF 월드 공간)

| | AircraftTrail (구버전, 미사용) | CesiumTrail (현재) |
|--|------|------|
| 렌더러 | Three.js BufferGeometry | Cesium Entity Polyline |
| 좌표계 | viewMatrix 투영 (카메라 상대) | ECEF 절대 좌표 |
| 3인칭 가시성 | 카메라 뒤쪽 trail → 불가시 | 카메라 위치 독립 |
| Tab 오버뷰 | ✓ | ✓ |

**Trail 색상**:
| 기체 | 색상 | 코드 |
|------|------|------|
| 아군 blue | 청색 | `0x4488ff` |
| 적기 red | 적색 | `0xff3333` |
| AI NPC | 회색 | `0x888888` |

**3인칭 가시 구간** (카메라 500m 오프셋 기준):
```
trail[n] ←── trail[1] ←── 항공기(P0) ←──── Cesium 카메라
  [불가시]   [500m 이내, 가시]  [카메라 전방 500m]
→ 최근 ~16 샘플(500m / 30m)이 카메라와 항공기 사이에서 보임
```

---

### 11.5 WebSocket 상태 흐름 (`main.js:631`)

```
wsClient.getWSState() → { t, blue, red, done, winner }
  │
  ├─ blue.* → state.lon/lat/alt/heading/pitch/roll
  │           physics.quaternion 동기화 (카메라 방향 계산용)
  │
  ├─ red.*  → npcSystem.updateExternal('RED_JSBSIM', lon, lat, alt, hdg, pitch, roll)
  │           npc.isExternal=true → AI 스킵, 행렬만 업데이트
  │
  └─ red.health 감소 → weaponSystem.fire() 기총 이펙트 자동 발사
```

---

### 11.6 듀얼 창 관전 모드 (`?follow=red`)

브라우저 탭 2개를 열어 아군/적기 시점을 동시에 관전:

```
탭 1: http://localhost:5173           → 아군(blue) 추적 카메라
탭 2: http://localhost:5173?follow=red → 적기(red) 추적 카메라
```

**동작** (`main.js`, `_followTarget`):
```js
const _followTarget = new URLSearchParams(window.location.search).get('follow') ?? 'blue';

// 카메라 배치:
if (_followTarget === 'red') {
    const redNpc = npcSystem.npcs.find(n => n.id === 'RED_JSBSIM');
    setCameraToPlane(redNpc.lon, redNpc.lat, redNpc.alt,
        redNpc.heading, redNpc.pitch, redNpc.roll, cameraMode === 'third');
}
// planeModel(아군 F-16)은 follow=red 창에서 자동 숨김
```

| 기능 | `follow=blue` (기본) | `follow=red` |
|------|---------------------|--------------|
| 카메라 추적 | 아군기 (`state`) | 적기 (`RED_JSBSIM` NPC) |
| planeModel | ✓ 3인칭 시 표시 | ✗ 항상 숨김 |
| Trail 표시 | 파랑/빨강 | 동일 (월드 공간 공유) |
| Tab 오버뷰 | 양측 기체 중점 | 동일 |
| C키 모드 전환 | 아군 기준 | 적기 기준 |

> **현재 한계**: `follow=red`에서 적기 3D 모델은 카메라 500m 전방의 NPC 메시로
> 렌더링됨. 플레이어 모델처럼 화면 고정 크기로 표시하려면
> `npcSystem.createNPCMesh()` → `camera-space fixed position` 방식으로 교체 필요.

---

### 11.7 시각화 검증 체크리스트

- [ ] 3인칭 모드에서 항공기 뒤 ~500m 파란/붉은 trail 확인
- [ ] Tab 오버뷰에서 양측 trail 전체 경로 확인
- [ ] 90° 뱅크 시 크로스헤어가 수직으로 회전하는지 확인
- [ ] `?follow=red` 탭 — 적기 기준 카메라 이동 확인
- [ ] `?follow=red` + Tab — 양측 기체 중점 오버뷰 정상 동작 확인
- [ ] NPC 모델 너무 작으면 `npcSystem.js` scale 조정 후 콘솔 size 출력 확인
- [ ] GLB 단위 파악: 모델 로드 시 `console.log(size)` 출력 후 실제 F-16 크기와 비교

---

## 12. 미구현 계획 및 기술 검토 사항

> 이 섹션은 구현을 결정했거나 검토 중인 항목들을 기록한다.
> 코드 변경 없이 설계 의도와 기술적 고려사항만 담는다.

---

### 12.1 `redFollowModel` — 적기 카메라 공간 고정 모델

#### 목적

`?follow=red` 창에서 적기가 `planeModel`(아군)과 동일하게
화면 우상단 고정 크기로 렌더링되도록 한다.
현재는 적기가 500m 전방의 NPC 메시로만 보인다.

#### 구현 위치

**파일**: `web-flight-simulator/src/main.js`

**Step 1 — GLB 로드 콜백에서 복제** (planeModel 설정 직후):
```js
// GLB 로드 콜백 내, planeModel 설정 직후
if (_followTarget === 'red') {
    redFollowModel = planeModel.clone();
    // 아군과 다른 화면 위치 (좌상단)
    redFollowModel.position.set(-0.75, 0.8, -3.0);
    redFollowModel.visible = false;
    redFollowModel.layers.set(1);
    redFollowModel.traverse(c => { c.layers.set(1); });

    // 적기는 붉은 계열 tint — 재질을 개별 복제해야 함
    redFollowModel.traverse(c => {
        if (c.isMesh) {
            c.material = c.material.clone();
            c.material.color.multiplyScalar(1.0);  // 기본값
            c.material.emissive = new THREE.Color(0.3, 0, 0);  // 붉은 glow
        }
    });
    scene.add(redFollowModel);
}
```

> `planeModel.clone()`은 재질 참조를 공유한다.
> color/emissive를 변경하려면 반드시 `c.material = c.material.clone()` 후 수정해야
> planeModel 재질에 영향을 주지 않는다.

**Step 2 — update() 루프에서 회전 적용** (npcSystem.update() 이후):
```js
if (redFollowModel && _followTarget === 'red') {
    const redNpc = npcSystem?.npcs.find(n => n.id === 'RED_JSBSIM');
    if (redNpc) {
        // NPC HPR → 카메라 공간 롤/피치 (planeModel과 동일 방식)
        const rollRad  = THREE.MathUtils.degToRad(redNpc.roll);
        const pitchRad = THREE.MathUtils.degToRad(redNpc.pitch) * 0.3;
        redFollowModel.quaternion.setFromEuler(
            new THREE.Euler(pitchRad, 0, -rollRad, 'YXZ')
        );
        redFollowModel.visible = (cameraMode === 'third');

        // 세계 공간 NPC 메시를 숨겨 중복 방지
        if (redNpc.mesh) redNpc.mesh.visible = false;
    }
}
```

**Step 3 — planeModel 가시성 조건 유지** (이미 적용됨):
```js
planeModel.visible = cameraMode === 'third' && _followTarget === 'blue';
```

#### 기술 고려사항

| 항목 | 내용 |
|------|------|
| `planeModel.clone()` 타이밍 | GLB 로드는 비동기 → 콜백 내부에서만 복제 가능 |
| 재질 공유 문제 | `clone()`은 재질 참조를 복사 → `material.clone()` 필수 |
| `redNpc.mesh.visible = false` | 매 프레임 강제 off — `isExternal` NPC는 매 프레임 행렬 업데이트만 하므로 safe |
| 롤/피치 스케일 | `* 0.3` 댐핑은 planeModel과 동일 → 시각적 일관성 유지 |
| 화면 위치 | `(-0.75, 0.8, -3.0)` 좌상단 — 아군 우상단과 대칭 배치 |

---

### 12.2 GLB 단위 확인 절차

실제 F-16 크기: 길이 ≈ 15m, 날개 폭 ≈ 10m, 높이 ≈ 5m

**확인 코드** (모델 로드 콜백 내 일회성 추가):
```js
// main.js — GLB 로드 콜백 내
const box = new THREE.Box3().setFromObject(model.scene);
const size = box.getSize(new THREE.Vector3());
console.log('[GLB] F-16 size:', size);
// 예상 결과별 해석:
//   x≈15, z≈10 → 1 unit = 1m → NPC scale=1.0 이 맞음
//   x≈1500      → 1 unit = 1cm → NPC scale=0.01 로 조정
//   x≈0.15      → 1 unit = 100m → NPC scale=100 로 조정
```

**npcSystem.js 스케일 조정 위치** (`npcSystem.js:67`):
```js
// GLB 단위 확인 후 적용
model.scale.set(scaleValue, scaleValue, scaleValue);
// 1 unit = 1m 인 경우: scale=1.0 (현재값, 유지)
// 1 unit = 1cm 인 경우: scale=0.01
```

---

### 12.3 3인칭 카메라 오프셋 오차 분석

**상황**: 3인칭 모드에서 Cesium 카메라가 항공기보다 500m 뒤에 위치.
NPC 모델은 `viewMatrix`(현재 카메라 기준)로 투영됨.

```
실제 NPC 위치 (월드)
         │  오차 500m (카메라 오프셋)
         ▼
NPC 화면 위치 = 실제보다 약간 앞/옆으로 치우쳐 보임
```

| NPC 거리 | 500m 오프셋 각도 오차 |
|----------|----------------------|
| 5,000m | ≈ 5.7° (sin⁻¹(500/5000)) |
| 2,000m | ≈ 14.5° |
| 10,000m | ≈ 2.9° |

> 교전 거리(2–10km)에서 허용 가능한 수준.
> BVR(장거리) 시나리오에서는 오차 무시 가능.
> WVR 근접전(< 2km) 시 NPC가 실제보다 측면으로 치우쳐 보일 수 있음.

---

### 12.4 시각화 미구현 항목

| 우선순위 | 항목 | 구현 복잡도 | 파일 |
|----------|------|------------|------|
| ★★★ | `redFollowModel` 카메라 공간 적기 모델 | 중 | `main.js` |
| ★★☆ | GLB 단위 확인 + NPC scale 조정 | 낮 | `main.js`, `npcSystem.js` |
| ★☆☆ | `redFollowModel` 붉은 tint 재질 | 낮 | `main.js` (GLB 콜백) |
| ★☆☆ | `follow=red` 탭에서 RED_JSBSIM NPC 메시 숨김 | 낮 | `main.js` (update 루프) |

---

## 13. BT 최적화 — 심층 분석 및 개선 로드맵

> 작성일: 2026-04-02
> 목적: bt_optimizer.py 기반 파이프라인의 구조적 한계 분석 및 단계별 개선 설계

---

### 13.1 현재 시스템 구조 요약

#### bt_optimizer.py 파이프라인 (3+1 스테이지)

```
Stage 1: LHS 탐색 (200개 후보, 2라운드/상대, 병렬)
    → 파라미터 상관분석 리포트
Stage 2: Top-10 정제 (각 15 이웃 perturb, 3라운드, 병렬)
Stage 3: Top-5 검증 (5라운드, 순차)
    → opt_results.json 저장
────────────────────────────────────
Stage 4 (별도): Round-Robin / Backtest / Tournament
```

#### 탐색 공간 (21개 파라미터)

| 유형 | 내용 | 개수 |
|------|------|------|
| 연속값 | 거리/각도 임계값, PD 게인 | 12 |
| 이산값 | 액션 선택, 브랜치 ON/OFF | 9 |

#### BT 템플릿 (고정 우선순위 Selector)

```
1. HardDeckAvoidance      (필수)
2. GunEngagement/PNAttack  (필수)
3. InEnemyWEZ → BreakTurn  (선택)
4. OffensivePress          (선택)
5. EmergencyDefense        (선택)
6. CloseCombat             (필수)
7. IsDefensiveSituation    (선택)
8. DefaultAction           (필수)
```

#### 스코어링 (계층적, 비중첩)

| 결과 | 점수 범위 | 계산 |
|------|-----------|------|
| WIN  | [8.0, 12.0] | 10 + hp_diff × 2 |
| DRAW | [-1.0, 3.0] | 1 + hp_diff × 2 |
| LOSS | [-7.0, -3.0] | -5 + hp_diff × 2 |

---

### 13.2 구조적 한계 분석

#### 13.2.1 전제 — 블랙박스는 제약이 아니라 물리 엔진

`.pyd` 파일(runner_core, behavior_tree)은 실제 전투기 6DOF를 반영한 시뮬레이터.
바꿀 이유도, 바꿀 필요도 없다. 핵심은:

- **커스텀 노드 확장이 가능** — PNAttack(커스텀 액션)이 이미 증명
- **LAG(CloseAirCombat)는 동일 JSBSim 환경의 RL 선행 결과물** — 참조 가능
- **제약은 물리 엔진이 아니라 BT 계층의 설계 품질**

#### 13.2.2 게임이론적 한계 — "항상 승리하는 BT"의 불가능성

"항상 승리하는 결정론적 전략"은 게임이론에서 **지배 전략(dominant strategy)**에 해당한다.
도그파이트처럼 두 에이전트가 동시에 적응하는 제로섬 게임에서는 순수 전략
내쉬 균형이 존재하지 않거나, 혼합 전략(mixed strategy) 균형에서만 최적성이 보장된다.

BT는 관측 상태에 대해 완전히 결정론적으로 반응하기 때문에, 적이 충분한 대전
데이터를 가지면 BT의 조건-액션 패턴을 역공학하여 **카운터 전략**을 설계할 수 있다.

> **참조**: DARPA AlphaDogfight Trial(2020)에서 Heron Systems의 RL 에이전트가
> 미 공군 파일럿을 5-0으로 이긴 이유는 "완벽한 전략"이 아니라
> **상대의 반응 패턴을 실시간으로 이용하는 적응성** 때문이었다.

따라서 목표는 "항상 승리하는 BT"가 아니라
**"고정 상대풀에서 최대 승점을 달성하는 BT"**로 정의해야 한다.

#### 13.2.3 BT 성능 결정 공식

```
BT 성능 = 상황 판단 정확도 × 행동 선택 품질 × 행동 실행 정밀도
          (조건 노드)         (트리 구조)        (액션 노드)
```

각 계층의 현재 한계:

**[행동 실행 정밀도]** — 이산 행동 공간의 근사 손실

현재 액션 공간 `5 × 9 × 5 = 225`개 이산 조합. JSBSim은 aileron/elevator/rudder/throttle
을 각각 [-1,1] 연속으로 제어하는데, 이를 225개로 근사하면:

- Gun WEZ ±12° 정밀 조준에 delta_heading 최소 단위(~10-15°)가 불충분
  → 0.1° 단위의 미세 기수 조정이 필요하나 구조적으로 불가
- 코너 속도(corner velocity) 유지에 필요한 aileron+throttle 동시 연속 조작이 불가
  → 실제 BFM에서 최적 선회율 달성의 핵심인데, 이산 `delta_velocity`만으로 표현 불가
- **단, PNAttack 패턴으로 우회 가능** — 노드 내부에서 연속 PD 제어 후 이산 매핑

> **참조**: Colledanchise & Ögren(2018, arXiv:1709.00084)은 BT가 Hybrid Dynamical
> System의 Switching Logic에 해당한다고 형식화하며, **연속 공간과 이산 BT 간
> 인터페이스에서 Zeno behavior(무한 전환)**가 발생할 수 있음을 경고.
> 현재 5Hz 스텝에서 BelowHardDeck 클리어 직후 즉시 Pursue로 전환되는 패턴이 이에 해당.

**[상황 판단 정확도]** — 조건 노드의 경계 불연속성 + 적 모델 부재

**(A) BFM 분류기의 경계 문제**

`IsOffensiveSituation`은 `ATA<45°, AA<100°, 거리 0.3~3NM + 에너지 우세`를 동시 요구.
ATA=44° vs ATA=46°의 전술적 우위는 거의 동일하지만, BT는 극단적으로 다른 행동
(LeadPursuit vs BreakTurn)을 취할 수 있다.

> **참조**: Millington & Funge(2009, "Artificial Intelligence for Games")가
> BT의 "dead zone" 문제로 지적한 사항.

BFM 3-way 분류(OBFM/DBFM/HABFM)가 하드 threshold 기반이므로, 상대가
`aa_threshold_deg=120` 근방에서 의도적으로 oscillation을 유발하면 BT가
DBFM ↔ HABFM 사이에서 진동하면서 실질적인 방어 기동을 수행하지 못한다.

에너지 우세 판단(`IsEnergyAdvantage`)도 `He = h + v²/2g` 단일 스칼라 비교인데,
실제 항공기 에너지 기동성은 Ps(비잉여동력)와 Em(최대 비에너지) 곡선의
2차원 관계로 판단해야 한다. 현재 Ps 노드(`EnergyHighPs`)가 존재하지만
`bfm_full` 템플릿에서 활용되지 않는다.

**(B) 적 의도 모델(enemy intent) 부재**

현재 `observation`에는 **자신과 적의 현재 상태만** 포함. 빠지는 정보:

- 적이 `LeadPursuit`인지 `BreakTurn`인지 BT는 알 수 없음
  → 기하학적 관계는 알지만, 적의 다음 행동은 예측 불가
- 역사적 교전 패턴(episode history) 없음
  → 적이 매치 중 어떤 노드를 자주 실행하는지 기억 불가
  → `active_node`가 CSV에는 기록되지만 Blackboard에는 부재 = 설계 결함

> **참조**: Shaw(1985, "Fighter Combat") — 실제 공중전에서 파일럿이
> "적의 다음 기동 의도를 읽는 것"이 승패를 결정하는 가장 중요한 요소

**[행동 선택 품질]** — BT 토폴로지 고정

- `generate_bt_yaml()`이 8개 브랜치 순서를 하드코딩
- 옵티마이저는 파라미터 튜닝 + ON/OFF만 가능, 순서 재배치·구조 변경 불가

#### 13.2.3 결정론적 시뮬레이션 — 제약이 아니라 이점

동일 BT + 동일 상대 → **매번 완전히 같은 결과** (MEMORY.md에도 기록됨).

이것은 문제가 아니다:
- **라운드 반복이 무의미** → 1라운드로 충분, 나머지 예산을 파라미터 조합 탐색에 투입
- **Fitness landscape에 노이즈 없음** → CMA-ES 등 gradient-free 최적화의 이상적 조건
- **파라미터 변경만으로도 궤적 분기** — `threat_aa_threshold`를 120→125로 바꾸면
  스텝 N에서 AA=122° 일 때 방어 발동 여부가 갈리고 이후 전체 궤적 변경

초기 조건 노이즈를 추가하면 오히려:
- heading ±3° 차이로 첫 스텝 ATABelow 통과/불통과 갈림 → 동일 BT에 WIN/LOSS 혼재
- noisy fitness → 최적화 수렴 저하
- BT 파라미터의 진짜 효과와 초기 조건 운을 분리 불가

**결론**: 결정론은 유지. 변동은 BT 파라미터 공간의 조합에서 자연 발생.

#### 13.2.4 탐색 효율

- 21차원에서 200개 LHS = 극히 희소한 탐색
- 4개 known-good 시드(v6, v72, v71, phase_a) 삽입 → 실질적으로 시드 주변 로컬 탐색
- perturb: 연속값만 실질 탐색, 이산값은 15% flip → 구조적 변화 느림
- **Stage 1에서 2라운드, Stage 2에서 3라운드는 동일 결과 반복 = 평가 예산 60%+ 낭비**

---

### 13.3 개선 로드맵

#### Phase 1: 대규모 탐색 + 메타데이터 수집

**목표**: "어떤 BT가 좋은지" 최적화 전에, "상대가 뭘 하는지" 전 영역 파악

```
다양한 BT 파라미터 조합 × 6 상대 = 대규모 매치 실행
    ↓ 매 스텝 CSV 로그 수집 (상태, 행동, 결과, active_node)
    ↓
메타데이터 분석
    ├─ 상대별 행동 패턴: "ace는 ATA<30°일 때 항상 LeadPursuit"
    ├─ 상대별 취약 구간: "aggressive는 스텝 200-400에서 고도 하락 패턴"
    ├─ WEZ 진입 선행 조건: "WEZ 진입 직전 5스텝에서 공통적으로 나타나는 상태"
    └─ 적 intent 시그니처: 적의 heading 변화율 + closure_rate 조합별 행동 분류
    ↓
적 intent 모델 (Phase 2 커스텀 노드의 재료)
```

**선행 인프라 — run_match 병렬화**:

현재: 순차 실행, 200조합 × 6상대 = 1200매치 → ~2시간+
목표: subprocess pool 또는 multiprocessing 기반 병렬화

```python
# 현재 bt_optimizer.py의 mp.Pool은 evaluate_fitness 단위 병렬
# → 1 후보 = 6 상대 순차 실행 (내부 직렬)
# 개선: 매치 단위 완전 병렬 + 라운드 1 고정
# → 동일 시간에 3배 이상의 파라미터 조합 탐색 가능
```

**탐색 전략 개선 — CMA-ES 도입**:

| 항목 | 현재 (LHS+perturb) | 개선 (CMA-ES) |
|------|---------------------|---------------|
| 방법 | 200 LHS → Top-10 × 15 perturb | 적응적 공분산 탐색 |
| 평가 횟수 | 390회 (60% 중복) | 390회 (전부 유효) |
| 라운드/상대 | 2~3 (동일 결과 반복) | 1 (결정론 활용) |
| 실질 탐색 | ~130개 유니크 파라미터 | 390개 유니크 파라미터 |
| 수렴 | 시드 주변 로컬 | 21차원 전역 적응 탐색 |

**CSV 메타데이터 수집 스키마**:

기존 `--log-csv` 컬럼에 추가로 수집이 필요한 정보:
- `enm_active_node`: 상대 BT의 현재 활성 노드 (SDK 지원 여부 확인 필요)
- `enm_heading_rate`: 적 heading 변화율 (°/s) — intent 추정의 핵심 피쳐
- `enm_altitude_rate`: 적 고도 변화율 (ft/s)
- `wez_event`: 해당 스텝에서 WEZ 진입 발생 여부 (bool)
- `n_steps_since_wez`: 마지막 WEZ 이벤트 이후 경과 스텝

---

#### Phase 2: 커스텀 노드 확장 (BT 계층 품질 향상)

Phase 1의 메타데이터 분석 결과를 기반으로, 세 계층을 각각 개선:

**[행동 실행 정밀도] — PNAttack 패턴 확장**

PNAttack이 증명한 구조: 커스텀 액션 노드 내부에서 관측값을 직접 읽고,
연속 PD 제어를 수행한 후, 최종 출력을 225개 이산 액션으로 매핑.

확장 노드:
- `PrecisionPursue`: Pursue의 구간별 이산 분류 대신 PD 컨트롤러로 연속 기수 조정
- `AdaptiveDefense`: closure_rate + turn_rate + 에너지 상태를 종합한 연속적 선회 강도 조절
- `CornerSpeedMaintain`: 현재 속도 vs 최적 선회 속도 차이에 비례한 throttle 제어

**[상황 판단 정확도] — 퍼지 조건 노드 + 적 의도 추정**

경계 불연속성 해소:
```python
class FuzzyOffensive(Condition):
    """하드 threshold 대신 연속적 점수 판단"""
    def evaluate(self, obs):
        ata_score = max(0, 1 - obs['ata_deg'] / 90)
        aa_score = max(0, 1 - obs['aa_deg'] / 180)
        dist_score = gaussian(obs['distance_ft'], mu=3000, sigma=2000)
        energy_score = 1.0 if obs['energy_advantage'] else 0.3
        composite = 0.3*ata_score + 0.3*aa_score + 0.2*dist_score + 0.2*energy_score
        return composite > self.params['threshold']
```

적 의도 추정 (Phase 1 메타데이터 기반):
```python
class EnemyPursuing(Condition):
    """적의 최근 행동에서 공격 의도 판단"""
    def evaluate(self, obs):
        # Phase 1 분석 결과: aa < 90° + closure_rate > 50kts
        # = 적이 공격 의도 (상대별 threshold는 메타데이터에서 도출)
        return (obs['aa_deg'] < 90 and obs['closure_rate_kts'] > 50)
```

**[행동 선택 품질] — 브랜치 순서 탐색**

```python
# generate_bt_yaml에 순서 파라미터 추가
# HardDeck은 항상 1번, Default는 항상 마지막
# 나머지 6개 브랜치의 순열 탐색 (720가지, CMA-ES 정수 인코딩)
"branch_order": [3, 4, 5, 2, 6, 7]  # GunEng, EnemyWEZ, OffPress, ...
```

---

#### Phase 3: LAG RL 정책 증류 (선행 결과 재활용)

LAG(CloseAirCombat)는 동일 JSBSim 환경에서 PPO 기반 RL을 수행한 선행 결과물.
RL 학습 비용(수만 에피소드, GPU 클러스터)은 LAG가 이미 지불.

```
LAG RL 정책 (학습된 신경망)
    ↓ 다양한 관측값 입력 → 행동 출력 수집
    ↓ Decision Tree로 관측→행동 매핑 근사 (해석 가능 규칙 추출)
    ↓
규칙 → 커스텀 BT 노드로 변환
    ├─ RLInspiredAttack: RL이 발견한 공격 패턴의 규칙 기반 근사
    ├─ RLInspiredDefense: RL이 발견한 회피 패턴의 규칙 기반 근사
    └─ RL이 사용한 상태 조합 → 새 퍼지 조건 노드의 가중치 초기값
    ↓
bt_optimizer로 파라미터 최적화 (Phase 1 인프라 활용)
```

장점: RL의 탐색 비용 없이 결과만 활용. GPU 불필요.
참조: `references/DBRL/` 에 LAG 코드 보존

---

### 13.4 우선순위 및 의존 관계

```
Phase 1 (인프라 + 탐색)
├─ 1-1. run_match 병렬화 ·························· 선행 인프라
├─ 1-2. bt_optimizer 라운드 1 고정 + CMA-ES 도입 ··· 탐색 효율 3배+
├─ 1-3. CSV 메타데이터 확장 수집 ·················· 분석 재료
└─ 1-4. 상대별 행동 패턴 분석 리포트 ·············· Phase 2 입력
         ↓
Phase 2 (BT 계층 품질)
├─ 2-1. 커스텀 액션 노드 확장 (PNAttack 패턴) ····· 실행 정밀도
├─ 2-2. 퍼지 조건 노드 + 적 의도 추정 ············ 판단 정확도
├─ 2-3. 브랜치 순서 탐색 파라미터 추가 ············ 구조 품질
└─ 2-4. 확장된 노드 포함 재최적화 ················· 통합 검증
         ↓
Phase 3 (RL 증류)
├─ 3-1. LAG 모델 로드 + 정책 분석 ················· 패턴 추출
├─ 3-2. Decision Tree 근사 → 규칙 추출 ············ BT 변환
└─ 3-3. RL 기반 노드 통합 + 최종 최적화 ··········· 성능 상한 확장
```

| Phase | 소요 (추정) | 핵심 산출물 |
|-------|------------|------------|
| 1 | 1-2주 | 병렬 인프라 + 상대 행동 분석 리포트 + CMA-ES 최적화 결과 |
| 2 | 2-3주 | 커스텀 노드 라이브러리 + 재최적화된 BT |
| 3 | 2-4주 | RL 증류 노드 + 최종 BT |

---

### 13.5 Phase 1 진행 기록

> 실행일: 2026-04-02

#### 13.5.1 인프라 구축 결과

**run_match.py 수정**: 반환 dict에 `tree1_health`, `tree2_health` 추가.
기존 SDK는 health 정보를 `match.health1.current_health`로만 노출하고
결과 dict에 포함하지 않았음 → 수정 완료.

**메타데이터 로거 신규**: `tools/metadata_logger.py`
- 41개 컬럼, 매 스텝 양측 에이전트 기록
- observation의 50+ 키 중 분석에 필요한 29개 필드 선별 수집
- 정규화된 각도 필드(ata_deg, aa_deg 등)를 ×180 변환하여 실제 각도로 기록

**CMA-ES 옵티마이저**: `tools/bt_optimizer_v3.py`
- 21차원 파라미터를 [0,1] 벡터로 인코딩, CMA-ES로 탐색
- 1라운드/상대 (결정론 활용), v6 시드에서 시작

#### 13.5.2 발견된 correctness 문제 및 해결

| 문제 | 원인 | 해결 |
|------|------|------|
| distance=0 기록 | `obs.get("distance")` 사용 — 실제 키는 `distance_ft` | metadata_logger에서 올바른 키 사용 |
| ata_deg 범위 0~1 | SDK가 [0,1]로 정규화 — ×180 필요 | 로거에서 ANGLE_SCALE_FIELDS 자동 변환 |
| tree1_health 미반환 | run_match 결과 dict에 health 없음 | run_match.py 수정, match 객체에서 추출 |
| save_replay 파라미터 | 현재 SDK에 존재하지 않음 | bt_optimizer_v3에서 제거 |
| BT 파라미터 이름 불일치 | `threshold` vs `threshold_ft` 등 | 실제 YAML 예시 기반으로 전부 수정 |

#### 13.5.3 observation 딕셔너리 전체 키 (50+)

SDK가 Blackboard에 제공하는 관측값 (커스텀 노드에서 접근 가능):

```
기하학: distance_ft, ata_deg*, aa_deg*, hca_deg*, relative_bearing_deg*, tau_deg*
에너지: ego_altitude_ft, ego_vc_kts, specific_energy_ft, ps_fts, energy_diff_ft
기동:   closure_rate_kts, turn_rate_degs, roll_deg, pitch_deg
전술:   in_wez, enm_in_wez, in_39_line, overshoot_risk, side_flag
분류:   bfm_situation, tc_type, energy_advantage, alt_advantage, spd_advantage
체력:   ego_health, enm_health, ego_damage_dealt, enm_damage_dealt
원시:   raw (numpy array), ego_vx/vy/vz_kts, ego_AO_rad, ego_TA_rad
(*= 정규화 [0,1], ×180 필요)
```

#### 13.5.4 핵심 발견: 커스텀 노드 확장성

**커스텀 액션 노드** — `examples/golden/nodes/custom_actions.py`에 풍부한 선행 구현:

| 노드 | 설명 | 핵심 기법 |
|------|------|----------|
| `PNPursuit` | PN 강화 추적 + 에너지 관리 | PD 컨트롤러 on tau, 거리별 속도 최적화 |
| `PNAttack` | Gun WEZ 정밀 교전 | 타이트 PD 게인, 안정적 사격 플랫폼 |
| `EnergyRecovery` | 저에너지 상태 회복 | 고도↔속도 트레이드, 완화된 추적 |
| `AdaptiveAction` | 상대 상태 인식 카운터 전략 | 6단계 상황 분류 (OFF/DEF/OVERSHOOT/1C/2C/LAG) |
| `StepLogger` | BT 내부 스텝 로거 | 항상 FAILURE → Selector 통과 (디버그용) |

`AdaptiveAction`은 Phase 2에서 구상한 "적 intent 기반 분기"를 이미 부분 구현:
- `aa < 60° + ata < 70°` → OFFENSIVE (후방 우위)
- `aa > 140°` → DEFENSIVE (적이 후방)
- `overshoot_risk` → HIGH YOYO
- `tc_type` 기반 1-circle/2-circle 분기

**관측값 키 불일치 주의**: golden 커스텀 노드는 `obs.get("distance")`,
`obs.get("ego_altitude")`, `obs.get("closure_rate")` 등 **`_ft`, `_kts` 접미사 없는
키**를 사용. 현재 SDK(Python 3.14 버전)의 실제 키는 `distance_ft`, `ego_altitude_ft`,
`closure_rate_kts`임. golden 노드는 이전 SDK 버전 기준 → 현재 SDK에서 사용 시 키 매핑 수정 필요.

**커스텀 조건 노드** — `examples/viper1/nodes/custom_conditions.py`에서 확인:
- `py_trees.behaviour.Behaviour` 상속
- Blackboard에서 `observation` 읽기
- `update()` → SUCCESS/FAILURE 반환
- 예: `HighEnergyState`, `OptimalAttackPosition`

**Phase 2의 퍼지 조건 노드, 적 intent 추정 노드가 이 방식으로 즉시 구현 가능.**

#### 13.5.5 구현 산출물

| 파일 | 역할 | 상태 |
|------|------|------|
| `scripts/run_match.py` | health 반환 추가 | 수정 완료 |
| `tools/metadata_logger.py` | Phase 1 전스텝 메타데이터 CSV 로거 (41컬럼) | 신규, 검증 완료 |
| `tools/bt_optimizer_v3.py` | CMA-ES 기반 탐색 + 올바른 파라미터 이름 | 신규, 기본 동작 확인 |

#### 13.5.6 다음 단계

Phase 1 메타데이터 수집 인프라 완료. 다음:
1. 다양한 BT 파라미터 조합(LHS 200+)으로 6상대 전 매치 실행 + CSV 수집
2. CSV 분석: 상대별 active_node 분포, BFM 전이 패턴, WEZ 진입 선행 조건
3. golden의 AdaptiveAction 분석 → Phase 2 커스텀 노드 설계 기반
4. 분석 결과 → Phase 2 커스텀 노드 설계의 입력

---

### 13.6 한계 완화 전략

13.2.2에서 분석한 게임이론적 한계(카운터 전략에 취약한 결정론적 BT)는
완전 해소가 불가능하다. 다만 다음으로 완화 가능:

| 완화 방법 | 효과 | 관련 Phase |
|-----------|------|-----------|
| 퍼지 조건 노드 | 경계값 예측을 어렵게 만듦 | Phase 2 |
| 적 intent 기반 분기 | 상대 행동에 반응적 전략 전환 | Phase 1→2 |
| 다수의 특화 BT + 메타 선택기 | 상대 유형 판별 후 대응 BT 선택 | Phase 2-3 |
| RL 증류 노드 | 학습된 비자명 패턴으로 예측 난이도 상승 | Phase 3 |
