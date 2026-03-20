# Dogfight 2 시각화 통합 가이드

이 문서는 AI Combat SDK에 Dogfight 2 실시간 3D 시각화를 통합하는 방법을 설명합니다.

---

## 📋 목차

1. [개요](#개요)
2. [현재 시각화 시스템](#현재-시각화-시스템)
3. [Dogfight 2란?](#dogfight-2란)
4. [통합 아키텍처](#통합-아키텍처)
5. [설치 방법](#설치-방법)
6. [통합 구현](#통합-구현)
7. [사용 방법](#사용-방법)
8. [문제 해결](#문제-해결)
9. [참고 프로젝트](#참고-프로젝트)

---

## 개요

### 현재 상태
- **AI Combat SDK**: TacView(.acmi) 리플레이 파일 생성 → 사후 분석
- **목표**: Dogfight 2 실시간 3D 시각화 추가 → 실시간 관전

### 통합 이점
- ✅ **실시간 관전**: 대전 중 실시간으로 3D 시각화
- ✅ **직관적 이해**: 전투 상황을 즉시 파악
- ✅ **디버깅 용이**: 에이전트 행동을 실시간으로 확인
- ✅ **데모/프레젠테이션**: 시각적으로 멋진 데모 가능

---

## 현재 시각화 시스템

### TacView (ACMI 리플레이)

**장점:**
- 사후 분석에 최적화
- 타임라인 제어 (일시정지, 되감기, 빨리감기)
- 상세한 데이터 분석 도구
- 무료 버전 사용 가능

**단점:**
- 실시간 시각화 불가
- 대전 종료 후에만 확인 가능
- 별도 프로그램 실행 필요

**현재 구현 위치:**
```python
# scripts/run_match.py:174
replay_path = replay_dir / f"{timestamp}_{agent1_name}_vs_{agent2_name}.acmi"

# src/match/runner_core.py
# ACMI 파일 생성 로직 (컴파일된 .pyd 내부)
```

---

## Dogfight 2란?

### 개요
- **프로젝트**: Harfang3D Dogfight Sandbox
- **GitHub**: https://github.com/harfang3d/dogfight-sandbox-hg2
- **엔진**: Harfang3D (Python 기반 3D 게임 엔진)
- **특징**: 네트워크 기반 실시간 3D 공중전 시각화

### 작동 방식
1. Dogfight 2 게임 실행 (독립 프로세스)
2. 네트워크 모드 진입 (방향키 입력)
3. IP:Port 리스닝 시작
4. Python 코드에서 TCP/UDP 소켓으로 연결
5. 실시간으로 기체 위치/자세 데이터 전송
6. Dogfight 2가 3D로 렌더링

---

## 통합 아키텍처

### 시스템 구조

```
┌─────────────────────────────────────────────────────────────┐
│                    AI Combat SDK                            │
│                                                             │
│  ┌──────────────┐      ┌──────────────┐                   │
│  │ BehaviorTree │      │ BehaviorTree │                   │
│  │   Agent 1    │      │   Agent 2    │                   │
│  └──────┬───────┘      └──────┬───────┘                   │
│         │                     │                            │
│         └──────────┬──────────┘                            │
│                    │                                       │
│         ┌──────────▼──────────┐                           │
│         │  SingleCombatEnv    │                           │
│         │     (JSBSim)        │                           │
│         └──────────┬──────────┘                           │
│                    │                                       │
│         ┌──────────▼──────────┐                           │
│         │    MatchCore        │                           │
│         │  (runner_core.py)   │                           │
│         └──────────┬──────────┘                           │
│                    │                                       │
│         ┌──────────▼──────────────────┐                   │
│         │  Visualization Manager      │ ◄── 새로 추가    │
│         │  - ACMI Writer (기존)       │                   │
│         │  - Dogfight2 Client (신규)  │                   │
│         └──────────┬──────────────────┘                   │
│                    │                                       │
└────────────────────┼───────────────────────────────────────┘
                     │
        ┌────────────┴────────────┐
        │                         │
        ▼                         ▼
┌───────────────┐         ┌──────────────────┐
│  TacView      │         │  Dogfight 2      │
│  (.acmi)      │         │  (실시간 3D)     │
│  사후 분석    │         │  네트워크 연결   │
└───────────────┘         └──────────────────┘
```

### 데이터 흐름

```python
매 스텝마다:
1. JSBSim 시뮬레이션 실행
2. 기체 상태 업데이트 (위치, 자세, 속도 등)
3. Visualization Manager로 데이터 전달
   ├─ ACMI Writer: .acmi 파일에 기록
   └─ Dogfight2 Client: 네트워크로 실시간 전송
```

---

## 설치 방법

### 1. Dogfight 2 다운로드

```bash
# 별도 디렉토리에 클론
cd c:\Users\Joon\Desktop\AI-pilot
git clone https://github.com/harfang3d/dogfight-sandbox-hg2
cd dogfight-sandbox-hg2
```

### 2. Dogfight 2 의존성 설치

```bash
pip install harfang
```

### 3. Dogfight 2 실행 테스트

```bash
python main.py
```

**네트워크 모드 진입:**
- 게임 실행 후 방향키 입력
- 화면에 표시되는 IP:Port 확인 (예: `127.0.0.1:50888`)

---

## 통합 구현

### Step 1: Dogfight 2 클라이언트 모듈 작성

**파일 위치**: `src/visualization/dogfight2_client.py`

```python
"""
Dogfight 2 실시간 시각화 클라이언트
"""
import socket
import json
import struct
from typing import Optional, Dict
import numpy as np


class Dogfight2Client:
    """Dogfight 2 네트워크 클라이언트"""
    
    def __init__(self, host: str = "127.0.0.1", port: int = 50888):
        """
        Args:
            host: Dogfight 2 서버 IP
            port: Dogfight 2 서버 포트
        """
        self.host = host
        self.port = port
        self.socket: Optional[socket.socket] = None
        self.connected = False
        
    def connect(self) -> bool:
        """Dogfight 2 서버에 연결"""
        try:
            self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.socket.settimeout(5.0)
            self.socket.connect((self.host, self.port))
            self.connected = True
            print(f"✓ Dogfight 2 연결 성공: {self.host}:{self.port}")
            return True
        except Exception as e:
            print(f"✗ Dogfight 2 연결 실패: {e}")
            self.connected = False
            return False
    
    def disconnect(self):
        """연결 종료"""
        if self.socket:
            try:
                self.socket.close()
            except:
                pass
            self.connected = False
    
    def send_state(self, aircraft_id: int, state: Dict):
        """기체 상태 전송
        
        Args:
            aircraft_id: 기체 ID (0=Agent1, 1=Agent2)
            state: 기체 상태 딕셔너리
                - position: [x, y, z] (NED 좌표계, meters)
                - attitude: [roll, pitch, yaw] (radians)
                - velocity: [vx, vy, vz] (m/s)
        """
        if not self.connected:
            return
        
        try:
            # Dogfight 2 프로토콜에 맞게 데이터 패킹
            # (실제 프로토콜은 Dogfight 2 문서 참조)
            data = {
                'id': aircraft_id,
                'pos': state['position'],
                'att': state['attitude'],
                'vel': state['velocity'],
            }
            
            # JSON 직렬화 후 전송
            message = json.dumps(data).encode('utf-8')
            length = struct.pack('!I', len(message))
            self.socket.sendall(length + message)
            
        except Exception as e:
            print(f"✗ Dogfight 2 데이터 전송 실패: {e}")
            self.connected = False
    
    def __enter__(self):
        self.connect()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.disconnect()
```

### Step 2: Visualization Manager 작성

**파일 위치**: `src/visualization/manager.py`

```python
"""
시각화 관리자 - ACMI와 Dogfight 2 통합
"""
from typing import Optional
from pathlib import Path
from .dogfight2_client import Dogfight2Client


class VisualizationManager:
    """시각화 출력 통합 관리"""
    
    def __init__(
        self,
        acmi_path: Optional[str] = None,
        enable_dogfight2: bool = False,
        dogfight2_host: str = "127.0.0.1",
        dogfight2_port: int = 50888,
    ):
        """
        Args:
            acmi_path: ACMI 파일 경로 (None이면 비활성화)
            enable_dogfight2: Dogfight 2 활성화 여부
            dogfight2_host: Dogfight 2 서버 IP
            dogfight2_port: Dogfight 2 서버 포트
        """
        self.acmi_path = acmi_path
        self.enable_dogfight2 = enable_dogfight2
        
        # ACMI Writer (기존 코드 활용)
        self.acmi_writer = None
        if acmi_path:
            # 기존 ACMI 작성 로직 초기화
            pass
        
        # Dogfight 2 Client
        self.df2_client: Optional[Dogfight2Client] = None
        if enable_dogfight2:
            self.df2_client = Dogfight2Client(dogfight2_host, dogfight2_port)
            self.df2_client.connect()
    
    def update(self, step: int, env_state: dict):
        """매 스텝마다 호출되어 시각화 데이터 업데이트
        
        Args:
            step: 현재 스텝
            env_state: 환경 상태 (JSBSim에서 추출)
        """
        # ACMI 파일 기록
        if self.acmi_writer:
            self._write_acmi(step, env_state)
        
        # Dogfight 2 실시간 전송
        if self.df2_client and self.df2_client.connected:
            self._send_to_dogfight2(step, env_state)
    
    def _write_acmi(self, step: int, env_state: dict):
        """ACMI 파일 기록 (기존 로직)"""
        # 기존 ACMI 작성 코드
        pass
    
    def _send_to_dogfight2(self, step: int, env_state: dict):
        """Dogfight 2로 실시간 전송"""
        # Agent 1 상태 전송
        state1 = {
            'position': env_state['agent1_position'],  # [x, y, z]
            'attitude': env_state['agent1_attitude'],  # [roll, pitch, yaw]
            'velocity': env_state['agent1_velocity'],  # [vx, vy, vz]
        }
        self.df2_client.send_state(0, state1)
        
        # Agent 2 상태 전송
        state2 = {
            'position': env_state['agent2_position'],
            'attitude': env_state['agent2_attitude'],
            'velocity': env_state['agent2_velocity'],
        }
        self.df2_client.send_state(1, state2)
    
    def close(self):
        """리소스 정리"""
        if self.acmi_writer:
            # ACMI 파일 닫기
            pass
        
        if self.df2_client:
            self.df2_client.disconnect()
```

### Step 3: MatchCore에 통합

**파일 수정**: `src/match/runner_core.py`

```python
# 기존 코드에 추가
from ..visualization.manager import VisualizationManager

class MatchCore:
    def __init__(
        self,
        # ... 기존 파라미터 ...
        enable_dogfight2: bool = False,
        dogfight2_host: str = "127.0.0.1",
        dogfight2_port: int = 50888,
    ):
        # ... 기존 초기화 ...
        self.enable_dogfight2 = enable_dogfight2
        self.dogfight2_host = dogfight2_host
        self.dogfight2_port = dogfight2_port
    
    def run(self, replay_path: Optional[str] = None, verbose: bool = False):
        # ... 기존 코드 ...
        
        # Visualization Manager 초기화
        viz_manager = VisualizationManager(
            acmi_path=replay_path,
            enable_dogfight2=self.enable_dogfight2,
            dogfight2_host=self.dogfight2_host,
            dogfight2_port=self.dogfight2_port,
        )
        
        # 메인 루프
        for step in range(self.max_steps):
            # ... 시뮬레이션 실행 ...
            
            # 시각화 업데이트
            env_state = self._extract_env_state(env)
            viz_manager.update(step, env_state)
            
            # ... 나머지 로직 ...
        
        # 정리
        viz_manager.close()
```

### Step 4: run_match.py에 옵션 추가

**파일 수정**: `scripts/run_match.py`

```python
def run_match(
    agent1: str,
    agent2: str,
    # ... 기존 파라미터 ...
    enable_dogfight2: bool = False,
    dogfight2_host: str = "127.0.0.1",
    dogfight2_port: int = 50888,
):
    # ... 기존 코드 ...
    
    match = BehaviorTreeMatch(
        # ... 기존 파라미터 ...
        enable_dogfight2=enable_dogfight2,
        dogfight2_host=dogfight2_host,
        dogfight2_port=dogfight2_port,
    )

# argparse에 옵션 추가
parser.add_argument('--dogfight2', action='store_true', 
                    help='Dogfight 2 실시간 시각화 활성화')
parser.add_argument('--df2-host', type=str, default='127.0.0.1',
                    help='Dogfight 2 서버 IP (기본값: 127.0.0.1)')
parser.add_argument('--df2-port', type=int, default=50888,
                    help='Dogfight 2 서버 포트 (기본값: 50888)')
```

---

## 사용 방법

### 1. Dogfight 2 실행

```bash
# 별도 터미널에서 Dogfight 2 실행
cd c:\Users\Joon\Desktop\AI-pilot\dogfight-sandbox-hg2
python main.py
```

**네트워크 모드 진입:**
- 방향키 입력하여 네트워크 모드 진입
- 화면에 표시되는 IP:Port 확인

### 2. AI Combat SDK 대전 실행 (Dogfight 2 연결)

```bash
# AI Combat SDK 터미널
cd c:\Users\Joon\Desktop\AI-pilot\AI_Pilot\ai-combat-sdk
.venv\Scripts\activate

# Dogfight 2 시각화와 함께 대전 실행
python scripts/run_match.py --agent1 eagle1 --agent2 simple --dogfight2

# 커스텀 IP:Port 지정
python scripts/run_match.py --agent1 eagle1 --agent2 simple --dogfight2 --df2-host 192.168.1.100 --df2-port 50888
```

### 3. 실시간 관전

- Dogfight 2 창에서 실시간으로 공중전 진행 상황 확인
- 카메라 조작으로 다양한 각도에서 관전 가능

### 4. 사후 분석 (TacView)

```bash
# 대전 종료 후 리플레이 파일 확인
dir replays

# TacView로 열기
# replays/*.acmi 파일을 TacView에서 열어 상세 분석
```

---

## 문제 해결

### Dogfight 2 연결 실패

**증상:**
```
✗ Dogfight 2 연결 실패: [Errno 10061] No connection could be made
```

**해결 방법:**
1. Dogfight 2가 실행 중인지 확인
2. 네트워크 모드에 진입했는지 확인
3. IP:Port가 올바른지 확인
4. 방화벽 설정 확인

### 데이터 전송 지연

**증상:**
- Dogfight 2 화면이 끊기거나 지연됨

**해결 방법:**
1. 네트워크 버퍼 크기 조정
2. 전송 빈도 조절 (매 스텝 → 2~5 스텝마다)
3. 데이터 압축 적용

### Dogfight 2 프로토콜 불일치

**증상:**
- 데이터 전송은 되지만 화면에 표시 안 됨

**해결 방법:**
1. Dogfight 2 공식 문서에서 네트워크 프로토콜 확인
2. 좌표계 변환 확인 (NED ↔ Dogfight 2 좌표계)
3. 단위 변환 확인 (meters, radians 등)

---

## 참고 프로젝트

### DBRL (Deep Reinforcement Learning for BFM)
- **GitHub**: https://github.com/mrwangyou/DBRL
- **특징**: Dogfight 2 통합 예제 포함
- **참고 파일**:
  - `envs/dogfight_client.py` - Dogfight 2 클라이언트 구현
  - `train_with_visualization.py` - 학습 중 실시간 시각화

### Dogfight Sandbox HG2
- **GitHub**: https://github.com/harfang3d/dogfight-sandbox-hg2
- **문서**: README.md의 Network Mode 섹션
- **API**: `network_protocol.md` (네트워크 프로토콜 명세)

---

## 비교: TacView vs Dogfight 2

| 특징 | TacView (.acmi) | Dogfight 2 |
|------|----------------|------------|
| **시각화 시점** | 사후 분석 | 실시간 |
| **설치** | 별도 프로그램 다운로드 | GitHub clone 필요 |
| **연결 방식** | 파일 기반 | 네트워크 소켓 |
| **타임라인 제어** | ✅ 자유롭게 제어 | ❌ 실시간만 |
| **데이터 분석** | ✅ 상세 분석 도구 | ❌ 시각화만 |
| **디버깅** | 사후 분석 | ✅ 즉시 확인 |
| **데모/발표** | 녹화 필요 | ✅ 실시간 시연 |
| **학습 곡선** | 낮음 | 중간 |
| **성능 영향** | 없음 (파일만 기록) | 약간 있음 (네트워크 전송) |

### 권장 사용 시나리오

**TacView 사용:**
- 상세한 전투 분석 필요
- 특정 시점 반복 재생
- 데이터 기반 전략 개발

**Dogfight 2 사용:**
- 실시간 디버깅
- 데모/프레젠테이션
- 학습 중 진행 상황 모니터링
- 시각적 피드백이 중요한 경우

**둘 다 사용 (권장):**
- 실시간으로 Dogfight 2로 관전
- 동시에 ACMI 파일 기록
- 대전 후 TacView로 상세 분석

---

## 다음 단계

1. **기본 통합 구현**: 위 코드를 참고하여 기본 연결 구현
2. **프로토콜 검증**: Dogfight 2 네트워크 프로토콜 확인 및 테스트
3. **성능 최적화**: 네트워크 전송 최적화
4. **UI 개선**: Dogfight 2 카메라 제어, HUD 정보 추가
5. **문서화**: 사용자 가이드 작성

---

**참고**: Dogfight 2 통합은 선택 사항입니다. TacView만으로도 충분한 분석이 가능하며, 많은 사용자들이 JSBSim + TacView 조합만 사용합니다. Dogfight 2는 실시간 시각화가 필요한 경우에만 추가하세요.

---

*Copyright © 2026 AI Combat Team. All rights reserved.*
