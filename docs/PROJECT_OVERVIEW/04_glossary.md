# 04. 용어집 — 자주 막히는 단어 정리

> **이 문서의 용도**: 다른 문서 읽다가 막히는 단어 빠르게 찾아보기.
> 정확한 수학 정의는 [BFM_MATHEMATICAL_FOUNDATIONS.md](../../examples/adaptive_eagle_v11_code/BFM_MATHEMATICAL_FOUNDATIONS.md), 코드 정의는 [CURRENT_STATE_AND_DESIGN.md](../../examples/adaptive_eagle_v11_code/CURRENT_STATE_AND_DESIGN.md) 참조.

---

## 기하·관측 용어

### ATA (Antenna Train Angle, 안테나 트레인 각)
- **내 기수와 적까지 시선(LOS) 사이 각도.**
- ATA = 0° → 적이 정확히 내 코앞.
- ATA = 12° 미만 + 사거리 + 양수 closure → **사격 가능 (WEZ 진입)**.
- ATA = 90° → 적이 내 옆 (빔).
- ATA = 180° → 적이 내 뒤.

```
        적
         ★
        /
      / ATA
    /
   ►━━━━━━  (내 기수)
```

### AA (Aspect Angle, 어스펙트 앵글)
- **적의 기수와 (적→나 시선) 사이 각도.** ATA의 적 입장 버전.
- AA = 0° → 적이 나를 정조준 (위험!).
- AA = 180° → 내가 적 6시 (적 꼬리).
- AA > 45° → 적이 나를 사격 못 함 (각도 컷).

### HCA (Heading Cross Angle, 헤딩 교차각)
- **두 비행기 헤딩(진행 방향)이 이루는 각.**
- HCA = 0° → 같은 방향 (1-circle 가능).
- HCA = 180° → 정반대 (head-on, 빔 패스, 2-circle).
- HCA = 90° → 직각.

### closure (closure rate, 거리 변화율)
- **두 비행기 사이 거리가 변하는 속도 (kts 단위).**
- closure > 0 → 거리 줄어들고 있음 (수렴).
- closure < 0 → 거리 늘어남 (이탈).
- 사격(WEZ) 가능하려면 closure > 0 필수.

### LOS (Line Of Sight, 시선)
- **나에서 적까지 그은 직선 벡터.**
- LOS rate = 그 직선이 회전하는 속도 (°/s). 적이 옆으로 빠를수록 LOS rate 큼.

### relative_bearing (상대 방위)
- **내 기수 기준으로 적이 어느 방향에 있나 (°).**
- 0° = 정면, 90° = 우측 빔, 180° = 후방, -90° = 좌측 빔.

### tau_deg (관측값 이름)
- 코드의 28-피처 중 하나. PN(비례 항법)의 lead 각도 정보.
- **그리스 문자 τ 와 헷갈림 주의** — 이 obs 이름은 단지 "τ_deg"라는 변수일 뿐, 본 문서의 τ 함수와는 다름.

---

## τ (그리스 문자 타우) — 0~1 가중치

본 프로젝트 최근 작업의 핵심.

### τ란?
- **0~1 사이 점수.** "이 BFM 정리를 지금 얼마나 강하게 쓸까?"
- τ=0 → 안 씀.
- τ=0.7 → 70% 강도로 적용.
- τ=1.0 → 완전 적용.

### τ 함수 3종 (현재 구현)

| 이름 | 의미 | 구체 |
|------|------|------|
| `τ_corner` | "지금 코너속도(350kts)로 감속해야 하나?" | 정리 5+6 (Boyd Ps + Shaw 2-circle) |
| `τ_yoyo` | "지금 위로 climb → dive 해야 하나?" | 정리 8 (Pontryagin 수직 BFM) |
| `τ_ldt` | "지금 옆으로 우회 후 진입해야 하나?" | 정리 7 (Shaw Lag Displacement Turn) |

### 합성 — τ-blending
```
명령 = (1 - τ) × 기본_PN_명령  +  τ × 그_정리의_명령
```
τ가 변하면 명령도 부드럽게 변함 → 적응형.

---

## canonical (캐노니컬)

### 단어 뜻
- 영어로 "표준의 / 정해진 형식의".

### 본 프로젝트에서
- **실제 JSBSim 매치가 매번 똑같이 시작하는 정확한 초기 조건.**

| 항목 | 값 |
|------|-----|
| ATA | 90° |
| 거리 | 3,297.6 ft |
| 두 비행기 속도 | 386.8 kts (둘 다) |
| 고도 | 15,000 ft |
| HCA | 180° (정반대 헤딩) |
| closure | 0 (거리 변화 없음) |

→ 두 비행기가 **양 옆에서 정반대 방향으로 빔 패스 시작**하는 모양.

### 시뮬에서의 시나리오 변형
- `canonical` = 위 조건 그대로
- `canonical_close` = 거리만 2,000ft (변형)
- `canonical_far` = 거리만 7,000ft (변형)
- `canonical_e_deficit` = 에너지 결핍 (e_diff=-3000ft)
- `canonical_enm_fast` = 적이 처음부터 MAX_SPD 420kts
- `canonical_alt_low` = 고도 8,000ft

---

## BFM (Basic Fighter Maneuvers, 기본 공중기동)

- 1930년대부터 축적된 **공중전 표준 기동 라이브러리**.
- 각 기동마다 **수학적 정리** 가 있음 (어떤 조건에서 어떻게 움직이면 유리한가).

### 본 프로젝트에서 인용한 정리 (총 8개)

| 번호 | 정리 | 출전 |
|------|------|------|
| 1 | Bernoulli 추격 곡선 (1732) | Pure pursuit 해석 해 |
| 2 | Bryson-Ho PN 최적성 (1969) | "Applied Optimal Control" |
| 3 | Isaacs Homicidal Chauffeur (1965) | Differential Games |
| 4 | Isaacs Game of Two Cars | Differential Games |
| 5 | Boyd Energy-Maneuverability (1964) | E-M 이론, doghouse plot |
| 6 | Shaw 1-circle vs 2-circle (1985) | "Fighter Combat" |
| 7 | Shaw Lag Displacement Turn | "Fighter Combat" |
| 8 | Pontryagin yo-yo 수직 최적 (수치 해) | 최적 제어 |

자세한 출전·증명은 [BFM_MATHEMATICAL_FOUNDATIONS.md](../../examples/adaptive_eagle_v11_code/BFM_MATHEMATICAL_FOUNDATIONS.md).

---

## 사격·교전 용어

### WEZ (Weapon Engagement Zone, 무장 교전 구역)
- **데미지 들어가는 조건의 영역.**
- 본 프로젝트: ATA<12° AND 500<거리<3000ft AND closure>0.

### Gun WEZ
- 기관총 사격 가능 영역. 위 WEZ와 동의어 (이 프로젝트 무기는 기관총만).

### Hard Deck (하드 덱)
- **추락 임계 고도.** 1,200ft 이하 = 즉시 패배.
- BT 최상단에는 항상 `BelowHardDeck` 검사 + `ClimbTo` 액션.

### HP (Hit Points)
- 체력. 100에서 시작, 0이면 격추.
- 매 틱 WEZ 안에 있으면 ~5 HP 감소 (거리·각도 가중치 적용).

---

## 속도·에너지 용어

### corner speed (코너 속도, V_corner)
- **F-16에서 최대 순간 선회율(ω_max=21°/s)이 나오는 속도.**
- 약 350 KIAS (corner speed at sea level).
- 이 속도 위로 가면 ω 떨어짐, 아래로 가면 G 한계 못 채움.
- **본 프로젝트 핵심**: 코너에 머물면 ω 우위 → 정리 5+6 활용 가능.

### Ps (Specific Excess Power, 비여분동력)
- **단위 무게당 가용 동력.** Ps = (T-D)·V/W (추력-항력)·속도/무게.
- Ps > 0 → 가속 또는 상승 가능. Ps < 0 → 에너지 손실 중.
- Boyd E-M 이론의 핵심 변수.

### specific_energy (비에너지)
- **고도 + 속도에너지의 단위 무게당 합.** E_s = h + v²/(2g).
- 두 비행기의 specific_energy 차 = energy_diff_ft (28-피처).

---

## 선회 기하 용어

### 1-circle fight (1-서클)
- **두 비행기가 같은 원 안쪽으로 같이 도는** 선회전.
- HCA가 작을 때 (양쪽 같은 방향 선회 가능).
- **승자: 더 작은 turn radius 가진 자** (=저속 또는 작은 wing loading).

### 2-circle fight (2-서클)
- **두 비행기가 각자 다른 원에서 반대 방향으로 도는** 선회전.
- HCA가 클 때 (정면 빔 패스 후).
- **승자: 더 큰 ω(=선회율) 가진 자** (=코너 속도 안착자).

### turn radius (선회 반경, R)
- 비행기가 그리는 원의 반경. R = V / ω.
- F-16 350kts에서 약 1,650ft.

### turn rate (선회율, ω)
- 헤딩이 회전하는 속도 (°/s). F-16 9G 순간선회 시 350kts에서 21°/s.

### lead pursuit / pure pursuit / lag pursuit
- **lead**: 적의 미래 위치를 향해 미리 조준. 사격 시 필요.
- **pure**: 현재 적 위치를 향해 직접 조준. 단순 추격.
- **lag**: 적 뒤쪽(후미)을 향해 조준. 가속·displacement 누적용.

---

## 코드·도구 용어

### BT (Behavior Tree, 행동 트리)
- 위에서 아래로 평가해서 액션 선택하는 의사결정 구조.
- YAML 파일로 정의 (`adaptive_eagle_v11_code.yaml` 같은).

### HCCA (Hierarchical Continuous Control Architecture, 위계적 연속 제어)
- 본 프로젝트의 5-layer 연속 제어 아키텍처. (현재 작업과는 별개로 존재)
- 위치: `examples/adaptive_eagle_v11_code/nodes/`.

### EIM (Enemy Intent Model, 적 의도 모델)
- 적이 GUN_RUN / CLOSING / EXTENDING / CLIMBING / DIVING / ORBITING 중 어느 의도인지 분류.
- 28-피처 obs를 입력으로 받음.

### JSBSim
- 외부 비행 물리 시뮬레이터. 실제 토너먼트 본 매치 환경.

### sim_dogfight_verify
- 우리가 만든 가벼운 검증 시뮬레이터 (3D 점질량). 빠르게 실험 가능.
- 91% WIN 결과는 여기서 측정 (JSBSim 통합 검증은 별개).

---

## 적 정책 5종

검증 시뮬에서 우리 AI가 상대하는 5가지 적 패턴 (`enemy_policy()` 함수):

| 정책 | 행동 |
|------|------|
| `passive` | 직선 등속 비행 (가만히) |
| `orbiting` | 일정 방향으로 -13°/s 선회 (교착 유발) |
| `defensive` | 위협 시에만 break turn + 수직 회피 |
| `offensive` | PN 추격(N=3) + +2kts/s 가속 + alt 추종 |
| `evading` | 우리가 가까우면 90° break + push-over |

---

## "정리 N" 표현

본 프로젝트 문서에서 "정리 5", "정리 8" 같은 표현은
[BFM_MATHEMATICAL_FOUNDATIONS.md](../../examples/adaptive_eagle_v11_code/BFM_MATHEMATICAL_FOUNDATIONS.md) 의 §N (해당 절)을 가리킵니다.

빠른 매핑:
- 정리 1 = §2 = Bernoulli pursuit
- 정리 2 = §3 = Bryson-Ho PN
- 정리 3 = §4 = Homicidal Chauffeur
- 정리 4 = §5 = Game of Two Cars
- 정리 5 = §6 = Boyd Energy-Maneuverability
- 정리 6 = §7 = Shaw 1/2-circle
- 정리 7 = §8 = Shaw Lag Displacement Turn
- 정리 8 = §9 = Pontryagin yo-yo
