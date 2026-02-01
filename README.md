# AI Combat Platform

![Version](https://img.shields.io/badge/version-v0.1-blue)

AI 공중전 챌린지 플랫폼 - 행동트리 또는 고수준 정책으로 공중전 AI 개발

> **참고 논문**: "공대공 전투 모의를 위한 규칙기반 AI 교전 모델 개발"
> 
> 항공 교범에 기반한 BFM(Basic Fighter Maneuver) 전술을 구현하는 체계적인 AI 개발 환경을 제공합니다.

## 🚀 빠른 시작

### ⚡ 한 줄 설치 (Windows PowerShell)
```powershell
python -m venv .venv; .venv\Scripts\activate; pip install -r requirements.txt
```

### 1. 환경 설정

```bash
# 1. 가상환경 생성
python -m venv .venv

# 2. 가상환경 활성화
# Windows
.venv\Scripts\activate
# Linux/Mac
source .venv/bin/activate

# 3. 의존성 설치
pip install -r requirements.txt

# 4. 설치 확인
python -c "import jsbsim; print('✅ JSBSim 설치 완료')"
python -c "import py_trees; print('✅ py_trees 설치 완료')"
```

### ⚠️ 중요: 가상 환경 활성화 규칙

**AI Combat Platform 코드를 실행하려면 항상 가상 환경이 활성화되어야 합니다.**

```bash
# 새 터미널을 열 때마다 실행
# Windows
.venv\Scripts\activate
# Linux/Mac  
source .venv/bin/activate
```

**활성화 확인:**
```bash
# 프롬프트에 (.venv)가 표시되어야 함
# Windows 예시
(.venv) C:\Users\user\ai-combat>
# Linux/Mac 예시
(.venv) user@hostname:~/ai-combat$ 
```

### 🔧 PowerShell 사용자 참고

Windows PowerShell에서 여러 명령을 연속 실행할 경우:
```bash
# PowerShell에서는 && 대신 ; 사용
.venv\Scripts\activate; python scripts/run_match.py tactical
```

### 2. 기능 테스트

```bash
# 단위 테스트 실행 (CombatGeometry)
python -m pytest test/test_combat_geometry.py -v

# 전술 테스트 실행 (tactical_fighter vs 베이스라인)
python scripts/run_match.py tactical

# 챌린지 매치 실행
python scripts/run_match.py challenge --agent1 sample_behavior_tree --agent2 aggressive_fighter
```

## 📋 챌린지 레벨별 참가 방법

### 🎯 Level 1: 행동트리 챌린지 (입문자용)

**특징**: YAML 파일로 전술 로직 작성, 1-2시간 내 개발 가능, 해석 용이

#### 📝 파일 명명 규칙

**파일명과 name 속성은 반드시 일치해야 합니다.**

```
{agent_name}.yaml
```

**요구사항:**
- ✅ 소문자 사용
- ✅ 언더스코어(`_`) 사용 가능
- ❌ 공백 사용 금지
- ❌ 특수문자 사용 금지 (언더스코어 제외)
- ✅ 짧고 명확하게 (권장: 15자 이내)

**예시:**
```
✅ simple.yaml          # name: "simple"
✅ viper1.yaml          # name: "viper1"
✅ my_agent.yaml        # name: "my_agent"

❌ Simple Fighter.yaml  # 공백 포함
❌ ace-fighter.yaml     # 하이픈 사용
❌ Ace.yaml             # 대문자 사용
```

#### 파일 구조
```
submissions/
  viper1/
    viper1.yaml         # 행동트리 정의 (파일명 = name 속성)
    nodes/              # 커스텀 노드 (선택)
      custom_actions.py
      custom_conditions.py
    README.md           # 전략 설명 (선택)

examples/
  simple.yaml           # name: "simple"
  ace.yaml              # name: "ace"
```

#### 행동트리 기본 구조
```yaml
name: "viper1"          # 파일명과 정확히 일치 (공백 없음)
description: "전투 전략 설명"

tree:
  type: Selector        # 자식 노드 중 하나 성공 시 성공
  children:
    - type: Sequence    # 모든 자식 성공 시 성공
      children:
        - type: Condition  # 조건 확인
          name: DistanceBelow
          params:
            threshold: 2000
        - type: Action      # 액션 실행
          name: LeadPursuit
    
    - type: Action
      name: Pursue
```

#### 사용 가능한 노드

**Condition 노드 (조건 확인)**:

*기본 조건:*
- `EnemyInRange(max_distance)`: 적이 거리 내에 있는지
- `AltitudeAbove(threshold)`: 고도가 기준값 이상인지
- `AltitudeBelow(threshold)`: 고도가 기준값 이하인지
- `DistanceBelow(threshold)`: 거리가 기준값 이하인지
- `BelowHardDeck(threshold)`: Hard Deck 이하인지
- `UnderThreat(aa_threshold)`: 위협 상황 (AA 기반)

*BFM 상황 분류 (논문 기반):*
- `IsOffensiveSituation`: OBFM 상황 (공격 유리)
- `IsDefensiveSituation`: DBFM 상황 (방어 필요)
- `IsNeutralSituation`: HABFM 상황 (정면/고측면)

**Action 노드 (액션 실행)**:

*기본 기동:*
- `Pursue`: 기본 추적
- `Evade`: 회피 기동
- `ClimbTo(target_altitude)`: 목표 고도로 상승
- `DescendTo(target_altitude)`: 목표 고도로 하강
- `Accelerate`: 가속
- `Decelerate`: 감속
- `TurnLeft(intensity)`: 좌회전
- `TurnRight(intensity)`: 우회전
- `Straight`: 직진
- `ClimbingTurn(direction)`: 상승 선회
- `DescendingTurn(direction)`: 하강 선회
- `BarrelRoll`: 배럴 롤 (나선형 회피)

*OBFM 전용 (공격 상황):*
- `LeadPursuit`: TAU 기반 선도 추적
- `PurePursuit`: 순수 추적 (적 현재 위치)
- `LagPursuit`: 지연 추적 (에너지 관리)
- `HighYoYo`: 고고도 요요 (에너지 변환)
- `AltitudeAdvantage(target_advantage)`: 고도 우위 확보

*DBFM 전용 (방어 상황):*
- `DefensiveManeuver`: AA 기반 방어 기동
- `BreakTurn`: 급선회 회피
- `DefensiveSpiral`: 방어 나선

*HABFM 전용 (정면/고측면 상황):*
- `OneCircleFight`: 1서클 전투 (작은 선회 반경)
- `TwoCircleFight`: 2서클 전투 (큰 선회 반경)

### 🚀 Level 2: 고수준 정책 챌린지 (중급자용)

**특징**: Python 클래스로 동적 전술 구현, 상태 기반 의사결정 가능, 복잡한 로직 구현

#### 파일 구조
```
submissions/
  my_policy/
    policy.py           # 정책 클래스
    requirements.txt    # 추가 의존성 (필요시)
    README.md           # 전략 설명 (선택)
```

#### 정책 인터페이스
```python
class MyPolicy:
    def __init__(self):
        """초기화"""
        pass
    
    def reset(self):
        """에피소드 시작 시 호출"""
        pass
    
    def get_action(self, obs: dict) -> list:
        """액션 선택
        
        Args:
            obs: 관측 정보 딕셔너리
        
        Returns:
            [delta_altitude_idx, delta_heading_idx, delta_velocity_idx]
            - delta_altitude_idx: 0=급하강, 1=하강, 2=유지, 3=상승, 4=급상승
            - delta_heading_idx: 0=급좌회전, 1=강좌회전, 2=약좌회전, 3=직진, 4=약우회전, 5=강우회전, 6=급우회전
            - delta_velocity_idx: 0=급감속, 1=감속, 2=유지, 3=가속, 4=급가속
        """
        raise NotImplementedError
```

#### 관측 정보
```python
observation = {
    "distance": float,        # 적과의 거리 (m)
    "altitude": float,        # 현재 고도 (m)
    "ego_vc": float,          # 현재 속도 (m/s)
    "ata_deg": float,         # ATA (0~1, 정규화, 0°=정면조준)
    "aa_deg": float,          # AA (0~1, 정규화, 목표물 꼬리에서 공격자까지 측정한 각도, 0°=적의 후방, 180°=정면위협)
    "hca_deg": float,         # HCA (0~1, 정규화)
    "tau_deg": float,         # TAU (-1~1, 정규화)
    "alt_gap": float,         # 고도 차이 (m, 양수=적이 위)
    "side_flag": int,         # -1=왼쪽, 0=정면, 1=오른쪽
}
```

## 🎯 실행 방법

### ⚠️ 실행 전 확인: 가상 환경 활성화

**모든 코드 실행 전에 가상 환경이 활성화되었는지 확인하세요:**
```bash
# Windows
.venv\Scripts\activate
# Linux/Mac
source .venv/bin/activate
# 프롬프트에 (.venv) 표시 확인
```

### 매치 실행

```bash
# 기본 실행 (에이전트 이름만 입력)
python scripts/run_match.py --agent1 viper1 --agent2 ace

# 다중 라운드
python scripts/run_match.py --agent1 viper1 --agent2 ace --rounds 3

# 파일 탐색 순서:
# 1. submissions/{name}/{name}.yaml
# 2. examples/{name}.yaml
# 3. 직접 경로
```

**예시:**
```bash
# Submissions vs Examples
python scripts/run_match.py --agent1 viper1 --agent2 ace

# Examples 간 대결
python scripts/run_match.py --agent1 simple --agent2 aggressive

# 커스텀 노드 포함 에이전트
python scripts/run_match.py --agent1 viper1 --agent2 eagle1
```

**출력 예시:**
```
매치 완료:
  승자: viper1
  스텝: 1500
  viper1 보상: 3.15
  ace 보상: -9.91
  리플레이: 20260131_162100_viper1_vs_ace.acmi
```

### ACMI 파일 저장 (Tacview 분석용)
```bash
# 모든 매치는 자동으로 ACMI 파일 저장
# 리플레이 파일 위치: replays/match_name.acmi

# 예시: tactical_vs_aggressive.acmi
python scripts/run_match.py tactical

# Tacview로 열기
# replays/tactical_vs_aggressive.acmi
```

## 📊 전투 기하학 및 BFM 시스템

### 🎯 CombatGeometry 핵심 파라미터

**3D 벡터 기반 공중전 기하학 계산**

- **ATA (Antenna Train Angle)**: 내가 적을 조준하는 각도 (0°=정면조준, 180°=후방)
- **AA (Aspect Angle)**: 목표물 꼬리에서 공격자까지 측정한 각도 (0°=적의 후방, 180°=정면위협)
- **HCA (Heading Crossing Angle)**: 두 기체의 진행 방향 각도 (0°=동일 방향, 180°=정면 대치)
- **TAU**: 롤 각도를 고려한 목표 위치 각도
- **alt_gap**: 고도 차이 (양수=적이 위, 음수=적이 아래)
- **closure_rate**: 접근 속도 (양수=접근 중, 음수=멀어짐)

### 🔄 BFM 상황 자동 분류 시스템

항공 교범 기준으로 전투 상황을 자동 분류하여 적절한 전술을 선택합니다:

| 상황 | 조건 (교범 기준) | 전술 목표 | 주요 기동 |
|------|----------------|----------|----------|
| **OBFM** (공격) | ATA<30°, AA<60°, 고도우위(>600ft) | WEZ 진입 및 격추 | Lead/Pure/Lag Pursuit, HighYoYo |
| **DBFM** (방어) | AA>120°, ATA>90°, 고도열세(>600ft) | 위협 회피 및 역전 | BreakTurn, DefensiveSpiral |
| **HABFM** (정면) | HCA<90°, 동일 고도(±600ft) | 선회 우위 확보 | OneCircle, TwoCircle Fight |

### 📐 전술적 의미 및 임계값

- **ATA < 30°**: 유효 사격 각도 (WEZ 진입 가능)
- **AA < 45°**: 적의 후방 점유 (공격 유리)
- **AA > 135°**: 정면 위협 상황 (방어 필요)
- **TAU ≈ 0°**: Lead Pursuit 기회
- **alt_gap > 600ft**: 고도 우위 (에너지 우위)
- **거리 0.5-2 NM**: 효과적 교전 거리

## 🏆 베이스라인 에이전트

### 1. aggressive_fighter.yaml
- **전략**: 적극적 추적과 공격
- **특징**: Lead Pursuit, 고도 우위 확보, 근거리 교전 특화
- **상성**: 방어적 에이전트에 강함
- **주요 전술**: 거리 구간별 공격, 급상승/급하강 적극 활용

### 2. defensive_fighter.yaml
- **전략**: 방어 기동 우선
- **특징**: Hard Deck 회피, DefensiveManeuver, 위협 감지
- **상성**: 공격적 에이전트에 강함
- **주요 전술**: AA 기반 방어, BreakTurn, DefensiveSpiral

### 3. defensive_evader.yaml
- **전략**: 회피 중심
- **특징**: 고도 유지, 기본 추적, 균형 잡힌 기동
- **상성**: 균형 잡힌 성능, 만능형
- **주요 전술**: 안정적인 거리 유지, 점진적 접근

## 📈 평가 시스템

### 🏁 승패 조건
- **시간 초과** (300 steps, 60초): 누적 보상 비교
- **Hard Deck 위반** (고도 < 1200ft): 즉시 패배
- **충돌**: 양측 패배
- **미사일 발사**: 향후 구현 예정

### 🎯 보상 구성
```python
reward = (
    angle_reward +      # ATA, AA 기반 각도 우위 보상
    altitude_reward +   # 고도 우위 보상 (에너지 우위)
    distance_reward +   # 적절한 거리 유지 보상
    missile_reward      # 미사일 발사 기회 보상 (향후)
)
```

### 📊 평가 지표
- **각도 우위**: ATA, AA 기반 조준 상태
- **에너지 우위**: 고도 및 속도 우위
- **위치 우위**: 적의 후방 점유향

## 🛠️ 개발 가이드

### 🌳 행동트리 개발 팁
1. **안전 우선**: Hard Deck 회피를 최상위에 배치 (`BelowHardDeck` + `ClimbTo`)
2. **단순하게 시작**: 기본 `Pursue`부터 시작하여 점진적 개선
3. **거리 구간화**: 근/중/원거리별 전술 분리
4. **BFM 기반**: OBFM/DBFM/HABFM 상황에 맞는 전술 선택
5. **다양한 테스트**: 여러 상대 에이전트로 성능 검증

### 🐍 고수준 정책 개발 팁
1. **상태 관리**: 상태 기반 전술 구현 및 상태 전환 로직
2. **안전장치**: Hard Deck, 위협 상황 처리 우선
3. **파라미터 튜닝**: 임계값 실험 및 최적화
4. **로깅**: 상태 전환 및 의사결정 로그 추가
5. **모듈화**: 전술별 함수 분리 및 재사용성 확보

## ❓ 자주 묻는 질문 (FAQ)

**Q: 어떤 실행 모드를 사용해야 하나요?**
A: 
- `tactical`: 개발 중인 에이전트 테스트용 (베이스라인과 다중 대전)
- `challenge`: 챌린지 제출물 공식 테스트용
- `match`: 빠른 1:1 대전용

**Q: 에이전트 파일을 찾지 못해요.**
A: 경로 우선순위를 확인하세요:
1. `submissions/my_agent/agent.yaml` (제출 폴더)
2. `examples/my_agent.yaml` (예제 폴더)
3. 직접 경로: `path/to/agent.yaml`

**Q: 행동트리와 정책 중 어떤 것을 선택해야 하나요?**
A: 
- **행동트리**: 빠른 프로토타이핑, 해석 가능성, 입문자에게 적합
- **정책**: 복잡한 로직, 동적 상태 관리, 중급자 이상에 적합

**Q: 코드 실행 시 ModuleNotFoundError가 발생해요.**
A: 가상 환경 활성화를 확인하세요. 새 터미널마다 다시 실행해야 합니다:
- Windows: `.venv\Scripts\activate`
- Linux/Mac: `source .venv/bin/activate`
- PowerShell: `.venv\Scripts\activate; python your_script.py`


**Q: 매치가 Hard Deck 위반으로 끝나요.**
A: 고도 관리 로직을 확인하세요. `BelowHardDeck` 조건과 `ClimbTo` 액션으로 Hard Deck 회피를 최우선으로 구현해야 합니다.

**Q: BFM 상황 분류가 정확하지 않아요.**
A: CombatGeometry 파라미터를 확인하고, 교범 기준 임계값(ATA, AA, 고도 차이)을 조정해보세요.

**Q: ACMI 리플레이 파일이 열리지 않아요.**
A: Tacview와 같은 ACMI 뷰어를 설치하고, `replays/` 폴더에서 파일을 열어보세요.

## 📁 프로젝트 아키텍처

```
ai-combat/
├── src/
│   ├── behavior_tree/          # 행동트리 시스템
│   │   ├── nodes/             # 행동/조건 노드 구현
│   │   ├── task.py           # 시뮬레이션 통합 태스크
│   │   └── loader.py         # YAML 행동트리 로더
│   ├── control/               # 제어 시스템
│   │   ├── combat_geometry.py # 3D 전투 기하학 계산
│   │   ├── bfm_classifier.py # BFM 상황 자동 분류
│   │   ├── pid_controller.py # PID 제어기
│   │   └── health_manager.py # 건강 상태 관리
│   ├── simulation/            # 시뮬레이션 환경
│   │   ├── algorithms/        # 강화학습 알고리즘
│   │   └── envs/             # JSBSim 환경
│   └── api/                   # REST API 인터페이스
├── examples/                  # 예제 행동트리
├── submissions/               # 제출 템플릿 및 결과
├── scripts/                   # 실행 스크립트
│   └── run_match.py          # 통합 매치 실행기
├── test/                      # 단위/통합 테스트
├── docs/                      # 상세 기술 문서
└── replays/                   # ACMI 리플레이 파일 (Tacview)
```

## 🔗 기술 스택

### 🎮 시뮬레이션 환경
- **JSBSim 1.2.3**: 고정도 항공기 시뮬레이션 ✅ 설치 확인 완료
- **JSBSim 환경**: 항공기 시뮬레이션 환경 ✅ 통합 완료

### 🧠 AI 및 알고리즘
- **행동트리**: py_trees 2.4.0 ✅ 설치 확인 완료 (계층적 의사결정)
- **강화학습**: PPO/MAPPO (다중 에이전트 지원)
- **기하학 계산**: ai-pilot-project 기반 3D 벡터 연산

### 🛠️ 개발 환경
- **언어**: Python 3.10+ (3.12 권장)
- **웹 프레임워크**: FastAPI (API 서버)
- **데이터베이스**: SQLAlchemy + aiosqlite
- **시각화**: Matplotlib, Tacview (ACMI)

### 📦 주요 의존성
- **수치 계산**: NumPy, PyTorch
- **환경**: Gymnasium, Gym
- **지리 정보**: pymap3d, geographiclib
- **테스트**: pytest, pytest-asyncio

## � SDK 배포 (개발자용)

### Cython 컴파일

```bash
# 전체 재컴파일
python setup.py build_ext --inplace

# 컴파일 후 .pyd 파일이 src/ 폴더에 생성됨
```

### SDK 빌드 및 배포

```bash
# SDK 빌드 (비공개 → 공개 저장소)
python scripts/build_sdk.py --output ../ai-combat-sdk

# 빌드 과정:
# 1. Cython 컴파일 (.py → .pyd)
# 2. SDK 문서/예제/스크립트 복사
# 3. JSBSim 리소스 복사
# 4. import 경로 패치
# 5. 소스 코드 보호 (핵심 모듈은 .pyd만 복사)
```

### 공개 저장소 배포

```bash
cd ../ai-combat-sdk

# 변경 사항 확인
git status

# 커밋 및 푸시
git add .
git commit -m "feat: SDK 업데이트 - Cython 컴파일 버전"
git push origin main
```

### 빌드 설정

- **제외 패턴**: `src/build_config.py`에서 관리
- **Cython 옵션**: `setup.py`에서 설정
- **공개 저장소**: https://github.com/songhyonkim/ai-combat-sdk

### 소스 코드 보호 정책

**참가자용 파일 (Python 소스 유지)**:
```python
KEEP_SOURCE_PATTERNS = [
    "scripts\\",           # 실행 스크립트 (run_match.py, run_challenge.py 등)
    "scripts/",
    "sdk\\tools\\",        # SDK 도구 (validate_agent.py, test_agent.py)
    "sdk/tools/",
    "examples\\",          # 예제 에이전트
    "examples/",
    "submissions\\",       # 참가자 제출 디렉토리
    "submissions/",
    "custom_nodes\\",      # 커스텀 노드 예제
    "custom_nodes/",
]
```

**핵심 모듈 (Cython 컴파일, .pyd만 복사)**:
- `src/` - 핵심 라이브러리 (behavior_tree, control, simulation 등)
- JSBSim 관련 모듈
- 알고리즘 및 환경 모듈

**보호 목적**: 지적 재산 보호 및 역공학 방지

**설정 파일**: `src/build_config.py`에서 `KEEP_SOURCE_PATTERNS` 관리

## �📞 지원 및 커뮤니티

- **GitHub Issues**: 버그 리포트 및 기능 요청
- **Discord**: 실시간 개발 커뮤니티 및 토론
- **문서**: `docs/` 폴더 상세 기술 문서
- **예제**: `examples/` 폴더 참고 구현

---

**🛩️ 하늘을 지배할 당신의 전투기 AI를 개발하세요!** ✨

> "공중전은 과학이자 예술이다. AI로 그 정수를 마스터하라."
