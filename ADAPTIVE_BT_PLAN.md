# Adaptive Combat BT — 설계 계획서 v2.1

> 최초 작성: 2026-04-05
> 최종 갱신: 2026-04-08 (Phase 2 완료 + Phase 3a 진행 중)
> 목표: **"어떤 상대든 적응적으로 대응하여 항상 이기는 AI Pilot"**

---

## 0. 요약 (현재 상태 스냅샷)

| 항목 | v4.6 (이전) | v5.1 (현재) | 목표 |
|---|---|---|---|
| vs eagle1 승률 (10R) | ~38% | **60%** | 65%+ |
| EIM 작동 여부 | 미작동 (BUG 3건) | **작동** (BUG-4,5 수정) | 정상 |
| 테스트 자동화 | 없음 | **5/5 PASS** | CI 수준 |
| 패배 원인 분류 | 없음 | **자동** (timeout/hp/harddeck) | 자동 |
| Dead code | 8개 클래스 | **0개** | 0개 |

---

## 1. 완료된 작업

### Phase 1: 측정 기반 구축 ✅

#### 1a. 통합 평가 함수 (`tools/evaluate.py`) ✅

```bash
python tools/evaluate.py adaptive_eagle --rounds 50 --opponents eagle1 ace
```

- N라운드 × M상대 자동 실행
- Wilson 95% 신뢰구간 (소표본 안정)
- 상대별 승률 매트릭스
- 패배 원인 자동 분류: {hard_deck, hp_diff, timeout}
- JSON 저장 (`--save`)

#### 1b. 자동 검증 테스트 (`tools/test_suite.py`) ✅

```bash
python tools/test_suite.py adaptive_eagle
```

5개 테스트:
| 테스트 | 검증 대상 |
|---|---|
| name_collision | 커스텀 노드명이 pyd 빌트인과 충돌하지 않음 |
| yaml_init_match | YAML params ↔ __init__ 파라미터 일치 |
| init_imports | YAML 참조 노드가 __init__.py에 import됨 |
| dead_code | import 되었으나 YAML 미사용 클래스 없음 |
| tree_structure | 루트 Selector + 첫 브랜치 HardDeck 확인 |

**실증: BUG-4(IsCircularOrbit 이름 충돌)를 자동 탐지 성공**

### Phase 2: 버그 수정 ✅

| # | 수정 내용 | 검증 |
|---|---|---|
| 2a | `IsCircularOrbit` → `CustomOrbitDetector` (BUG-4) | test_suite name_collision PASS |
| 2b | `tracker1.update(obs2)` → `tracker1.update(obs1)` (BUG-5) | eagle1에 2전 2승 (이전 0-2) |
| 2c | mid-match `update_online()` 비활성화 (드리프트) | 10R 안정 (이전 38%→80% 변동) |
| 2d | 8개 미사용 클래스 제거 (371줄 → 131줄) | test_suite dead_code PASS |

### Phase 3a: 커스텀 노드 (진행 중)

#### 구현 완료

| 노드 | 역할 | 상태 |
|---|---|---|
| `SmartGunAttack` | PD 제어(kp=1.2, kd=0.5) + 거리별 속도 적응 | **YAML 적용 중** |
| `SmartLeadPursuit` | 에너지 인식 vel/alt 적응 | 구현 완료, YAML에서 **미사용** |

#### 실험 결과

| 버전 | 구성 | vs eagle1 10R |
|---|---|---|
| v4.6 (이전) | 빌트인 + EIM 미작동 | 38% |
| v5.0 (Phase 2 완료) | 빌트인 + EIM 작동 | 50% |
| v5.0-smart | SmartLeadPursuit(전체 교체) | **30%** ← heading 열등 |
| **v5.1 (현재)** | **빌트인 LeadPursuit + SmartGunAttack** | **60%** |

**교훈: 빌트인 LeadPursuit의 heading 추적은 내부 PN 로직이 정교하여 커스텀보다 우수. heading은 빌트인에 맡기고, WEZ 내 정밀 제어(SmartGunAttack)만 커스텀이 가치.**

---

## 2. 현재 아키텍처 (v5.1)

```
adaptive_eagle v5.1 — 7-branch Selector
│
├─ 1. HardDeckAvoidance: BelowHardDeck(1200ft) → ClimbTo(3000ft)
├─ 2. GunEngagement: dist<914 + dist>152 + ATA<15° → SmartGunAttack(PD)
├─ 3. IntentAdaptiveEscape: EIM(NEUTRAL_CIRCLE) + CustomOrbitDetector → HeadOnBreak
├─ 4. CircularOrbitBreak: CustomOrbitDetector → Accelerate
├─ 5. CloseCombat: dist<3000 → LeadPursuit (빌트인)
├─ 6. DefensiveEscape: IsDefensiveGeometry(AO>90°,TA<70°) → ExtensionBreak
└─ 7. Default: LeadPursuit (빌트인)
```

---

## 3. 다음 단계

### Phase 3b: Optimizer 적용 (다음 우선순위)

**목표: 40차원 파라미터를 자동 탐색하여 승률 65%+ 달성**

```python
# tools/adaptive_optimizer.py (구현 예정)
SEARCH_SPACE = {
    # 조건 파라미터
    "orbit_ata_min": (20, 50),
    "orbit_ata_max": (70, 120),
    "orbit_closure_max": (100, 400),
    "defense_ao_min": (70, 120),
    "defense_ta_max": (50, 90),
    "close_combat_dist": (2000, 5000),
    "gun_ata_max": (5, 20),
    "gun_dist_max": (600, 1500),
    "eim_confidence": (0.2, 0.5),
    "harddeck_threshold": (1000, 1500),
    # 행동 파라미터
    "gun_kp": (0.5, 2.0),
    "gun_kd": (0.1, 1.0),
    "headon_gain": (0.5, 1.5),
    # 구조 파라미터
    "enable_eim_branch": [True, False],
    "enable_orbit_branch": [True, False],
}
# 평가: evaluate() 사용 → 50라운드 × 6 opponents
```

### Phase 3c: Ablation 실험

```
실험 1: EIM ON vs OFF → 적응형 가치 검증
실험 2: SmartGunAttack vs 빌트인 GunAttack → PD 제어 가치
실험 3: ExtensionBreak ON vs OFF → 방어 기동 기여도
실험 4: ATA 15° vs 8° vs 12° → WEZ 진입 임계값 최적화
```

### Phase 3d: 추가 커스텀 노드 후보

| 노드 | 교체 대상 | 가치 판단 기준 |
|---|---|---|
| SmartBreakTurn | BreakTurn | 저고도 Hard Deck 보호 (현재 미사용) |
| AdaptiveDefense | DefensiveManeuver | 에너지+closure 인식 방어 |
| EnergyPursuit | Pursue | 원거리 에너지 빌드 (vel=4+alt 적응) |

**주의: SmartLeadPursuit 실패 교훈 — heading은 빌트인이 우수, vel/alt 적응만 가치**

### Phase 4: 적응형 고도화 (EIM 정상 작동 확인 후)

| 작업 | 전제 조건 |
|---|---|
| 4a. EIM 학습 데이터 보강 (GUN_ATTACK 3.7K → 200K) | Phase 3 완료 |
| 4b. 상대별 최적 전략 매핑 자동화 | optimizer + evaluate 완성 |
| 4c. 매치 중 상대 유형 인식 → 전략 전환 | EIM 정확도 85%+ |

---

## 4. 검증 기준

| 지표 | v4.6 | v5.1 (현재) | Phase 3 목표 | 최종 |
|---|---|---|---|---|
| vs eagle1 (10R) | 38% | **60%** | 65%+ | 75%+ |
| vs 6 opponents 평균 | 미측정 | 미측정 | 55%+ | 65%+ |
| 최악 상대 승률 | 미측정 | 미측정 | 35%+ | 50%+ |
| WEZ 진입 횟수/match | ~0 | TBD | 3+ | 5+ |
| test_suite | 없음 | **5/5 PASS** | 5/5 | 5/5 |

---

## 5. 커스텀 노드 작성 규칙

### 필수 체크리스트

| # | 항목 | 확인 방법 |
|---|---|---|
| 1 | **이름 충돌 없는가** | `python tools/test_suite.py <agent>` |
| 2 | **각도 ×180 했는가** | ata_deg, aa_deg, hca_deg, tau_deg, relative_bearing_deg |
| 3 | **YAML params ↔ __init__ 일치** | test_suite yaml_init_match |
| 4 | **__init__.py에 import** | test_suite init_imports |
| 5 | **heading은 빌트인 우선** | SmartLeadPursuit 실패 교훈: 커스텀 heading < 빌트인 PN |
| 6 | **커스텀 가치 = vel/alt 적응 + PD 제어** | heading 이외에서 차별화 |

### 관측값 단위

| 키 | 범위 | 변환 |
|---|---|---|
| ata_deg, aa_deg, hca_deg | 0~1 | ×180 → 도 |
| tau_deg | -1~1 | ×180 → 도 |
| relative_bearing_deg | -1~1 | ×180 → 도 |
| distance_ft, closure_rate_kts, ego_altitude_ft | raw | 변환 불필요 |

---

## 6. 제어 루프 요약 (참조)

```
관측 (0.2초/tick) → BT 결정 (3-tuple) → JSBSim 물리 (12 substep @ 60Hz)
                                          ↓
액션: [alt_idx(0-4), hdg_idx(0-8), vel_idx(0-4)] = 225 조합
                                          ↓
제약: 22.5° 조향 단위, 0.2초 반응 지연, 적 기동 미예측
```

**핵심 한계: 접근(closing)은 쉬우나 WEZ 유지(staying)가 어려움.**
→ PD 제어(SmartGunAttack)로 WEZ 내 정밀 추적이 가장 가치 있는 커스텀화.

---

## 7. 파일 구조 (현재)

```
examples/adaptive_eagle/
├── adaptive_eagle.yaml         # v5.1
└── nodes/
    ├── __init__.py              # HeadOnBreak, ExtensionBreak, SmartLeadPursuit,
    │                            # SmartGunAttack, IsDefensiveGeometry,
    │                            # CustomOrbitDetector, EnemyIntentIs
    ├── custom_actions.py        # HeadOnBreak, ExtensionBreak,
    │                            # SmartLeadPursuit (미사용), SmartGunAttack
    └── custom_conditions.py     # IsDefensiveGeometry, CustomOrbitDetector, EnemyIntentIs

tools/
├── evaluate.py                  # Phase 1a: 통합 평가 (승률+CI+원인)
├── test_suite.py                # Phase 1b: 자동 검증 (5개 테스트)
├── test_agent.py                # 기본 매치 테스트
├── bt_optimizer_v3.py           # CMA-ES optimizer (alpha1용)
├── collect_phase1.py            # 대규모 메타데이터 수집
└── metadata_logger.py           # per-step CSV 로깅

src/match/
├── runner.py                    # BUG-1,5 수정, 드리프트 비활성화 적용
└── runner_core.py               # MatchCore (변경 없음)
```

---

## 부록 A: 버전 이력

| 버전 | 주요 변경 | vs eagle1 | 교훈 |
|---|---|---|---|
| v3.x | 순수 기하학 BT | ~50% | EIM 없어도 50% 가능 |
| v4.0-v4.3 | EIM 연결 시도 | 불안정 | 통합 테스트 없이 연결하면 버그 |
| v4.4 | RLInspiredAttack | **0%** | 좌우 반전 → 회귀 테스트 필요 |
| v4.5 | LeadPursuit 복귀 | 57% | 단순한 것이 안정적 |
| v4.6 | EIM NEUTRAL_CIRCLE | 38-80% | 온라인 드리프트 불안정 |
| v5.0 | BUG-4,5 수정 | 50% | 측정 기반 검증의 힘 |
| v5.0-smart | SmartLeadPursuit | 30% | heading은 빌트인이 우수 |
| **v5.1** | **빌트인 LP + SmartGunAttack** | **60%** | **heading 빌트인 + WEZ PD 커스텀** |

## 부록 B: 인프라 요구사항

- **Python 3.14** 필수 (upstream v0.5.5.9 pyd가 cp314)
- `PYTHONIOENCODING=utf-8` (Windows cp949 대응)
- upstream remote: `https://github.com/rokafa-daslab/ai-combat-sdk`
