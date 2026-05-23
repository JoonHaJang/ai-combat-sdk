# pursuit_chase_v1 모델 UML — SPA Framework 정렬 (Mermaid)

> **renderer 호환성 (2026-05-17 정정)**: 본 문서의 Mermaid 는 **v9.4 ~ v11 폭넓게 호환** 되도록 정돈됨.
> - 제거됨: `classDiagram` 의 `namespace { }` (Mermaid v10+ 만 지원) → 클래스명 prefix (`SENSE_*`, `PLAN_*`) 로 대체
> - 제거됨: `sequenceDiagram` 의 `rect rgb()` (구버전 미지원) → `Note over` 만 사용
> - 유지: `flowchart` `subgraph`, `stateDiagram-v2`, `classDef` (모두 v9.4 이상 표준)
> - **VSCode**: Extension "Markdown Preview Mermaid Support" 가 *구 mermaid 6.x* 를 쓸 수 있으니 v10.x 로 업데이트 권장
> - **GitHub**: 자동 v11 — 모두 정상 렌더
>
> **구조**: 모든 diagram 이 **Sense-Plan-Act framework** 로 정렬됨. `docs/MODEL_EXPLANATION_학생용.md` 의 2-3부 와 1:1 대응.
>
> **색 코드** (전 문서 일관):
> - 🌍 **Sense** = `#E0F2FE` (파랑) — env 책임, fixed
> - 🧠 **Plan** = `#DCFCE7` (녹색) — 우리 책임, 자유 설계
> - ⚙️ **interface** = `#FEF3C7` (노랑) — game protocol, fixed
> - ✈️ **Act** = `#FCE7F3` (분홍) — env 책임, fixed
> - ❌ **Lost/Unused** = `#FECACA` (빨강)

---

## SPA 매핑 reference table

| Step | SPA | OODA 세부 | 우리 코드 | INPUT → OUTPUT | 자유도 |
|---|---|---|---|---|---|
| 1 | **SENSE** | Observe | env.observe() | world state → 28 obs | env fixed |
| 2 | **PLAN** | (Goal) | 목표 분석 (설계) | 게임 룰 → 이기는 패턴 | 우리 자유 |
| 3 | PLAN | Internal-Observe | obs_to_state_6d | 28 obs → 6D state | 우리 자유 |
| 4 | PLAN | **Orient** | dispatcher (5-layer Maslow) | 6D+28 obs → branch | 우리 자유 |
| 5 | PLAN | **Decide+Compute** | optimal_control | branch → mode-τ → ∇V → u* | 우리 자유 |
| 6 | **interface** | (Decide-out) | quantize_to_bins | u* (연속) → bin (이산) | game fixed |
| 7 | **ACT** | Act | env.step | bin → AIPILOT → JSBSim → 새 state | env fixed |

---

## 1. SPA Overview — 최상위 architecture

```mermaid
flowchart TB
    subgraph SENSE["🌍 SENSE Layer (env 책임, fixed)"]
        direction LR
        World[World State<br/>JSBSim 6-DOF 물리]
        Obs[28 obs Dict<br/>distance/ata/aa/hca/alt/V/...]
        World -->|env.observe| Obs
    end

    subgraph PLAN["🧠 PLAN Layer (우리 책임, 자유 설계)"]
        direction TB
        P2[Step 2 ─ Goal Analysis<br/>이기는 obs 패턴 정의]
        P3[Step 3 ─ Internal-Observe<br/>28 obs → 6D state]
        P4[Step 4 ─ Orient<br/>dispatcher 5-layer Maslow]
        P5[Step 5 ─ Decide+Compute<br/>BFM → ∇V → u* PMP optimal]
        P2 -.-> P3
        P3 --> P4
        P4 --> P5
    end

    subgraph INTERFACE["⚙️ Plan↔Act interface (game protocol, fixed)"]
        Q[quantize<br/>u* 연속 → alt/hdg/vel bin]
    end

    subgraph ACT["✈️ ACT Layer (env 책임, fixed)"]
        direction TB
        AIPILOT[AIPILOT — open LAG repo 사전학습 RNN<br/>baseline_model.pt 외부 자산<br/>sdk/core 둘 다 byte-identical 사본<br/>bin → aileron/elev/rudder/throttle]
        JSBSim[JSBSim 6-DOF<br/>12 ODE 풀이]
        AIPILOT --> JSBSim
    end

    SENSE -->|28 obs| PLAN
    PLAN -->|u* 연속 명령| INTERFACE
    INTERFACE -->|3 bin 정수| ACT
    ACT -.->|새 world state| SENSE

    classDef sense fill:#E0F2FE,stroke:#0369A1
    classDef plan fill:#DCFCE7,stroke:#16A34A
    classDef intf fill:#FEF3C7,stroke:#CA8A04
    classDef act fill:#FCE7F3,stroke:#BE185D
    class SENSE,World,Obs sense
    class PLAN,P2,P3,P4,P5 plan
    class INTERFACE,Q intf
    class ACT,AIPILOT,JSBSim act
```

→ **순환 구조** (Act → Sense). 매 BT tick (0.1s) 마다 1 사이클. **Plan 만 우리 책임**.

---

## 2. Class Diagram — SPA Layer 별 *Swimlane*

```mermaid
classDiagram
    class SENSE_Obs28 {
        +28 keys
        +distance/ata/aa/hca
        +ego/alt_gap/closure
        +energy_adv/Ps/Es
    }
    class PLAN_PursuitChaseOptimal {
        -obs_history: List
        -prev_branch: str
        +update() Status
        +log_tick()
    }
    class PLAN_ComputeAction {
        +compute_action(obs) action
        +obs_to_state_6d(obs) ndarray
        -MODE_TAU: dict
    }
    class PLAN_Dispatcher {
        +select_branch(obs, hist) dict
        -five_layer_priority
    }
    class PLAN_OptimalControl {
        +optimal_control(x, taus) tuple
        +grad_V_PN_corner_yoyo_ldt_T
        +B_d_matrix(x)
    }
    class PLAN_TauFunctions {
        +all_taus(obs, prev, hist) dict
    }
    class PLAN_State6D {
        +dx_dy_dh: ft
        +dpsi: rad
        +V_p_V_e: kts
    }
    class IF_Quantize {
        +quantize_to_bins(u_star) tuple
        +alt_0_4 / hdg_0_8 / vel_0_4
    }
    class ACT_AIPILOT {
        +baseline_actor_RNN
        +bin_plus_ego_to_4_stick
    }
    class ACT_JSBSim {
        +six_dof_dynamics
        +twelve_ODE
    }

    SENSE_Obs28 ..> PLAN_PursuitChaseOptimal : obs in
    PLAN_PursuitChaseOptimal --> PLAN_ComputeAction
    PLAN_ComputeAction --> PLAN_State6D : creates
    PLAN_ComputeAction --> PLAN_TauFunctions : calls
    PLAN_ComputeAction --> PLAN_Dispatcher : calls
    PLAN_ComputeAction --> PLAN_OptimalControl : calls
    PLAN_ComputeAction --> IF_Quantize : final step
    IF_Quantize ..> ACT_AIPILOT : bin out
    ACT_AIPILOT --> ACT_JSBSim
```

> **prefix 가 SPA layer 표현**: `SENSE_*` = 파랑, `PLAN_*` = 녹색, `IF_*` = 노랑, `ACT_*` = 분홍 (`namespace` 제거로 일부 renderer 에서도 호환).

→ **Plan layer 가 클래스 *대부분***. Sense/Act 각 2 클래스 (external). **우리 차별화 영역 = Plan namespace 의 6 클래스**.

---

## 3. Sequence Diagram — *SPA layer 명시* 한 BT tick

```mermaid
sequenceDiagram
    autonumber

    participant W as World+JSBSim (SENSE+ACT)
    participant BT as Plan BT Node
    participant CP as Plan compute_action
    participant BD as Plan-Orient dispatcher
    participant OC as Plan-Decide+Compute
    participant AI as Act AIPILOT

    Note over W,BT: == SENSE — env perception ==
    W->>BT: 28 obs (raw)

    Note over BT,OC: == PLAN — 4 sub-step ==
    BT->>CP: compute_action(obs)
    Note over CP: Step 3 Internal-Observe<br/>x = obs_to_state_6d(obs)
    CP->>BD: select_branch(obs, history)
    Note over BD: Step 4 Orient<br/>5-layer Maslow cascade
    BD-->>CP: branch = Theorem
    CP->>OC: optimal_control(x, taus)
    Note over OC: Step 5 Decide+Compute<br/>grad_V x 6 modes<br/>BtG = B_d.T * grad_V<br/>u* = -BtG * gain
    OC-->>CP: u* (omega, gamma_dot, a)

    Note over CP: == Step 6 Plan-Act interface ==
    CP->>CP: quantize_to_bins(u*)<br/>= (alt_bin, hdg_bin, vel_bin)
    CP-->>BT: action triplet

    Note over BT,W: == ACT — env executes ==
    BT->>AI: action (3 bins)
    Note over AI: bin + ego_obs<br/>-> AIPILOT RNN<br/>-> 4 stick command
    AI->>W: aileron/elev/rudder/throttle
    Note over W: JSBSim 6-DOF<br/>12 ODE -> new state

    W-->>BT: (next tick) new 28 obs
```

> **rect rgb() 제거**: 구 mermaid 미지원. 색대신 `==` 마커로 SPA 단계 구분. 색 시각화는 [1. SPA Overview](#1-spa-overview--최상위-architecture) flowchart 에서 제공.

→ 색깔 = SPA layer (파랑 Sense, 녹색 Plan, 노랑 interface, 분홍 Act). **각 처리 단계가 *어느 layer* 인지 시각적 명확**.

---

## 4. State Diagram — *Plan-Orient* 의 5-layer Maslow

```mermaid
stateDiagram-v2
    [*] --> Plan_Orient : 매 BT tick

    state "PLAN-ORIENT (Dispatcher)" as Plan_Orient {
        direction TB
        [*] --> L1_Safety

        state "L1: SAFETY ★★★★★" as L1_Safety {
            [*] --> HardDeck : alt<1200
            HardDeck --> [*]
            [*] --> DefensiveBreak : enm_in_wez OR<br/>(ATA>100 ∧ dist<3000)
            DefensiveBreak --> [*]
        }

        L1_Safety --> L2_Kill : Safety 비활성

        state "L2: KILL OPPORTUNITY ★★★★" as L2_Kill {
            [*] --> GunEngagement : ATA<12 ∧<br/>500<dist<3000 ∧ aligned
            GunEngagement --> [*]
        }

        L2_Kill --> L3_Sustain : Kill 비활성

        state "L3: SUSTAINABILITY ★★★" as L3_Sustain {
            [*] --> EnergyRecovery : V_p<360 OR<br/>(prev=ER ∧ V_p<400)
            EnergyRecovery --> [*]
        }

        L3_Sustain --> L4_Tactical : Sustain 비활성

        state "L4: TACTICAL ★★" as L4_Tactical {
            [*] --> LagPursuit : overshoot OR<br/>(cl>150 ∧ dist<2500)
            [*] --> OffensivePursuit : ATA<45 ∧ AA>100<br/>∧ dist<4000
            [*] --> OrbitBreak : 30<ATA<110 ∧<br/>|cl|<200 ∧ dist>2000
            [*] --> ZoomClimb : ATA<60 ∧ cl<-50<br/>∧ dist>5000 ∧ alt<18k
        }

        L4_Tactical --> L5_Default : Tactical 비활성

        state "L5: DEFAULT ★" as L5_Default {
            [*] --> Theorem : else (τ-blend full)
        }
    }

    Plan_Orient --> Plan_Compute : branch name 전달

    state "PLAN-DECIDE+COMPUTE" as Plan_Compute {
        [*] --> ModeTauLookup
        ModeTauLookup --> OptimalControl
        OptimalControl --> [*] : u*
    }

    Plan_Compute --> [*] : 다음 step (quantize)
```

→ **dispatcher 의 5 layer = Plan-Orient 내부 구조**. Maslow 시급도 우선순위. Plan-Decide+Compute 는 *별도 sub-step*.

---

## 5. Data Flow — *SPA 경계* 명시 28 obs → action

```mermaid
flowchart TB
    subgraph S["🌍 SENSE"]
        A[28 obs Dict]
    end

    subgraph P["🧠 PLAN (4 sub-steps)"]
        direction TB

        subgraph P3["Step 3 ─ Internal-Observe (6D 압축)"]
            B1[distance_ft<br/>relative_bearing_deg]
            B2[alt_gap_ft]
            B3[hca_deg]
            B4[ego_vc_kts]
            B5[ego_vc + closure_rate]
            C[x = Δx, Δy, Δh, Δψ, V_p, V_e]
            B1 --> C
            B2 --> C
            B3 --> C
            B4 --> C
            B5 --> C
        end

        subgraph P4["Step 4 ─ Orient (dispatcher)"]
            D[ata, dist, V_p, alt, closure 직접]
            E{5-layer Maslow}
            D --> E
        end

        subgraph P5["Step 5 ─ Decide+Compute (optimal_control)"]
            F[grad_V_i × 6 modes]
            G[grad = Σ τ·∇V / Στ]
            H[B_d matrix]
            I[BtG = B_d.T · grad]
            J[u* = clip-BtG·gain]
            F --> G --> H --> I --> J
        end

        C --> P5
        E --> P5
    end

    subgraph IF["⚙️ Plan↔Act interface"]
        K[quantize]
        L[alt_bin 0-4 / hdg_bin 0-8 / vel_bin 0-4]
        K --> L
    end

    subgraph ACT_L["✈️ ACT"]
        M[AIPILOT inference]
        N[JSBSim 6-DOF]
        M --> N
    end

    subgraph LOST["❌ Lost in Plan-Observe (Step 3)"]
        L1[ego_vx/vy/vz_kts]
        L2[roll/pitch_deg]
        L3[specific_energy_ft ★]
        L4[ps_fts ★]
        L5[energy_advantage ★]
        L6[ata_lead_deg ★]
    end

    A --> P3
    A --> P4
    P5 --> K
    L --> M
    N -.->|새 obs| A

    A -.->|미사용| LOST

    classDef sense fill:#E0F2FE
    classDef plan fill:#DCFCE7
    classDef intf fill:#FEF3C7
    classDef act fill:#FCE7F3
    classDef lost fill:#FECACA,stroke:#B91C1C
    class A sense
    class C,D,E,F,G,H,I,J plan
    class K,L intf
    class M,N act
    class L1,L2,L3,L4,L5,L6 lost
```

→ **빨강 = Step 3 (Plan-Internal-Observe) 에서 *버린* obs**. ★ 표시는 *MPC 도입 시 회수 권장*.

---

## 6. Adversary 도 *parallel SPA*

적의 BT 도 동일 SPA 구조. 양쪽이 *대칭 SPA pipeline*:

```mermaid
flowchart LR
    subgraph US["🟢 우리 SPA"]
        direction TB
        US_Sense[Sense: 28 obs<br/>우리 시점]
        US_Plan[Plan: compute_action<br/>BFM dispatcher + ∇V]
        US_Act[Act: bin → AIPILOT → JSBSim]
        US_Sense --> US_Plan --> US_Act
    end

    subgraph THEM["🔴 적 SPA"]
        direction TB
        THEM_Sense[Sense: 28 obs<br/>적 시점 mirror]
        THEM_Plan[Plan: Pursue.update<br/>if-else 트리 closed-form]
        THEM_Act[Act: bin → AIPILOT → JSBSim<br/>*동일 AIPILOT 공유*]
        THEM_Sense --> THEM_Plan --> THEM_Act
    end

    subgraph SHARED["🌍 공유 SENSE+ACT (env)"]
        World[World State<br/>JSBSim physics]
    end

    World --> US_Sense
    World --> THEM_Sense
    US_Act --> World
    THEM_Act --> World

    THEM_Plan -.->|core source<br/>완전 가시화| US_Plan
    oracle_note["우리는 적의 Plan 정확 함수 알고 있음<br/>= MPC adversary oracle 가능"]
    THEM_Plan -.-> oracle_note

    classDef us fill:#DCFCE7,stroke:#16A34A
    classDef them fill:#FECACA,stroke:#B91C1C
    classDef shared fill:#E0F2FE,stroke:#0369A1
    classDef notebox fill:#FEF3C7,stroke:#CA8A04
    class US_Sense,US_Plan,US_Act us
    class THEM_Sense,THEM_Plan,THEM_Act them
    class World shared
    class oracle_note notebox
```

→ ***양쪽 모두 SPA*** + **공유 Sense+Act**. 우리 white-box advantage = 적의 *Plan 함수 가시화*.

---

## 7. BFM Mode Catalog — *우리 7 vs core 30+* (학생doc 2.2 시각화)

Plan-Decide+Compute 의 **도구 카탈로그** 비교. Plan layer 의 *어느 BFM 도구가 가용*한지, *어느 것이 누락*인지 시각화.

```mermaid
flowchart TB
    subgraph CORE["📚 core BFM 카탈로그 (src/behavior_tree/nodes/actions.py 30+)"]
        direction TB

        subgraph Pursuit["Pursuit (5)"]
            P1[Pursue]
            P2[PurePursuit]
            P3["⭐ LeadPursuit"]
            P4[LagPursuit]
        end

        subgraph Turn["Turning primitive (5)"]
            T1[TurnLeft]
            T2[TurnRight]
            T3[Straight]
            T4[ClimbingTurn]
            T5[DescendingTurn]
        end

        subgraph YoYo["YoYo (2)"]
            Y1[HighYoYo]
            Y2[LowYoYo]
        end

        subgraph Defense["Defensive (4)"]
            D1[Evade]
            D2[DefensiveManeuver]
            D3[BreakTurn]
            D4[DefensiveSpiral]
        end

        subgraph Geom["Combat Geometry (2)"]
            G1[OneCircleFight]
            G2[TwoCircleFight]
        end

        subgraph Energy["Energy mgmt (5)"]
            E1["⭐ EnergyFight"]
            E2[Accelerate]
            E3[Decelerate]
            E4[AltitudeAdvantage]
            E5[MaintainAltitude]
        end

        subgraph Tactical["Tactical (3)"]
            TC1["⭐ TCFight"]
            TC2["⭐ GunAttack"]
            TC3["⭐ OvershootAvoidance"]
        end

        subgraph Aero["Aerobatic (4) — 수직 BFM 핵심"]
            A1[Loop]
            A2[ImmelmannTurn]
            A3["⭐ SplitS"]
            A4[HammerHead]
        end

        subgraph EConv["Energy conversion (2)"]
            EC1[SpiralDive]
            EC2[SpiralClimb]
        end
    end

    subgraph OURS["🟢 우리 사용 7 (pursuit_chase_v1)"]
        direction TB
        O1[PN ← PurePursuit]
        O2[Corner / 2c ← 자체 정의]
        O3[1c ← 자체 정의]
        O4[ldt ← LagPursuit]
        O5[yoyo ← HighYoYo 단축]
        O6[T capture-time ← 자체 정의]
        O7[Energy Recovery ← Corner mode]
    end

    P2 -.->|"우리 매핑"| O1
    P4 -.->|"우리 매핑"| O4
    Y1 -.->|"부분 매핑 (LowYoYo 없음)"| O5

    P3 -.->|"❌ 누락 ★★★★★"| MISSING
    E1 -.->|"❌ 누락 ★★★★"| MISSING
    A3 -.->|"❌ 누락 ★★★★"| MISSING
    A2 -.->|"❌ 누락 ★★★"| MISSING
    A4 -.->|"❌ 누락 ★★★"| MISSING
    TC2 -.->|"❌ 누락 ★★★"| MISSING
    TC3 -.->|"❌ 누락 ★★★"| MISSING
    TC1 -.->|"❌ 누락 ★★"| MISSING

    MISSING[❌ 우리 미사용 22+ BFM<br/>aggressive Nash 깸 후보]

    classDef priority fill:#FBBF24,stroke:#92400E,color:#000
    classDef used fill:#86EFAC,stroke:#15803D,color:#000
    classDef missing fill:#FCA5A5,stroke:#B91C1C,color:#000
    classDef ours fill:#DCFCE7,stroke:#16A34A
    classDef core fill:#FEE2E2,stroke:#B91C1C

    class P3,E1,A3,A2,A4,TC1,TC2,TC3 priority
    class P2,P4,Y1 used
    class MISSING missing
    class OURS,O1,O2,O3,O4,O5,O6,O7 ours
    class CORE core
```

#### 우선 도입 권고 (★ 표시)

| 우선 | BFM | 이유 | 효과 |
|---|---|---|---|
| ★★★★★ | **LeadPursuit** | Pure Pursuit → Lead 정통화 | 적 turn 예측 → ATA 빠르게 |
| ★★★★ | **EnergyFight** | Boyd EM 직접 (Ps, Es 활용) | sustained turn 우위 |
| ★★★★ | **SplitS / Immelmann** | 수직 분리 (aggressive Nash 깸 후보) | parallel chase 깸 가능 |
| ★★★ | OvershootAvoidance | 오버슈트 예방 | dist 닫고도 못 잡는 상황 회피 |
| ★★★ | GunAttack | 사격 정조준 정밀 | WEZ 내 damage 효율 ↑ |
| ★★ | HammerHead, SpiralDive/Climb | PE↔KE 변환 다양화 | 옵션 ↑ |

→ ⭐ = ★★★ 이상 우선순위. **8개 BFM 우선 도입 권장**.

---

## 8. MPC variant — Plan layer 의 *시간 horizon 확장*

```mermaid
flowchart TB
    subgraph Current["현재 Plan (myopic, H=1)"]
        direction TB
        C1[현재 obs] --> C2[dispatcher] --> C3[optimal_control] --> C4[u* 단일 step]
    end

    subgraph MPC["MPC Plan (anticipatory, H=50)"]
        direction TB
        M1[현재 obs]
        M2[forward simulate<br/>H step lookahead]
        M3[adversary oracle<br/>Pursue.update H회 호출]
        M4[augmented dynamics<br/>우리 + 적 6D 동시]
        M5[running cost<br/>D_them - D_us]
        M6[terminal cost<br/>우리 ∇V_i 재사용]
        M7[iLQR / CasADi 풀이]
        M8[u* trajectory]
        M9[u_0* 첫 step 적용]

        M1 --> M2
        M3 --> M4
        M4 --> M2
        M5 --> M7
        M6 --> M7
        M2 --> M7
        M7 --> M8 --> M9
    end

    subgraph Reuse["기존 자산 재사용 (∇V_i, B_d, damage_rate)"]
        R1[grad_V_PN/corner/yoyo/...]
        R2[B_d_matrix]
        R3[wez_damage_rate]
    end

    R1 -.-> M6
    R2 -.-> M4
    R3 -.-> M5

    Current -.-x|폐기 X| MPC
    Current -->|확장| MPC

    classDef cur fill:#FED7AA
    classDef mpc fill:#BBF7D0,stroke:#15803D
    classDef reuse fill:#E0E7FF,stroke:#4338CA
    class Current,C1,C2,C3,C4 cur
    class MPC,M1,M2,M3,M4,M5,M6,M7,M8,M9 mpc
    class Reuse,R1,R2,R3 reuse
```

→ **MPC = Plan 의 *Compute step 시간 horizon 확장***. 23 사이클 자산 (∇V_i, B_d, damage_rate) *그대로* terminal cost / linearization / running cost 로 재사용. **폐기 없음**.

---

## diagram 종류 정리 (SPA 관점)

| # | 종류 | SPA 표현 | 학생 doc 매핑 |
|---|---|---|---|
| 1 | SPA Overview (component) | 3 layer 큰 그림 | 2.1 의 7-step flow |
| 2 | Class diagram (swimlane) | Layer 별 클래스 그룹화 | 2.1 각 step 의 *코드 구현* |
| 3 | Sequence diagram (annotated) | 시간 순 + layer 색 | 2.1 의 *시간 진행* |
| 4 | State diagram (FSM) | Plan-Orient 의 5-layer Maslow | 2.3 dispatcher |
| 5 | Data flow (boundaries) | obs → action 의 SPA 경계 | 4부 의 28→6 손실 |
| 6 | Adversary (parallel SPA) | 양쪽 SPA + 공유 env | 적 white-box 의미 |
| **7** | **BFM Catalog (우리 7 vs core 30+)** | Plan-Decide+Compute 의 도구 비교 | **2.2 의 BFM gap 시각화** |
| 8 | MPC variant (proposal) | Plan-Compute 의 horizon 확장 | 미래 path |

→ **각 diagram 이 *다른 SPA 관점***. 8개 합치면 *전체 시스템* 의 *완전 표현*.

---

## 모든 prior comment 처리 확인

| user comment | 어디 반영 | 상태 |
|---|---|---|
| 1.1 단계 수치 조정 가능? | 학생doc 1.1 (env hardcoded, 양쪽 동일 명시) | ✅ |
| 2.1 abstraction gap | SPA Sense → Plan boundary 명시 (Step 1 vs 3 분리) | ✅ |
| 2.1 BFM 갑자기 점프 | 4 sub-step (Goal→Variable→Orient→Compute) 분해 | ✅ |
| 2.1 4/5/6 자세히 | Step 4-7 각 상세 설명 + 수학 의미 | ✅ |
| 2.1 bin 헷갈림 | "bin 용어 정의" 박스 + 시험점수 비유 | ✅ |
| 2.2 LeadPursuit 어디감 | core 30+ BFM vs 우리 7 비교, LeadPursuit code 전수 분석 | ✅ |
| 2.2 다른 BFM 도 | EnergyFight, SplitS, Immelmann, HammerHead 등 우선순위 표 | ✅ |
| 2.3 SPA 관점 재구성 | 5-layer Maslow + Plan-Orient 정확 위치 | ✅ |
| baseline_model.pt 정정 | AIPILOT = **open LAG repo 사전학습 RNN** (외부 자산). sdk/core byte-identical 사본만 보유, 둘 다 *load only* | ✅ |
| core 수치 정렬 | wez_damage_rate 선형, HardDeck 1000ft, 목표 table 2-tier | ✅ |
| Sense Plan Act 제대로 | OODA 통합 매핑 + Layer 책임 분리 + SPA-aligned UML 7종 | ✅ |
| **UML Mermaid + SPA** | **본 파일 (`MODEL_UML.md`) 전체 SPA-aligned Mermaid 로 재작성** | ✅ (지금) |

---

## 보는 방법

| 도구 | 설정 |
|---|---|
| **VSCode** | Extension "Markdown Preview Mermaid Support" 설치 후 `Ctrl+Shift+V` |
| **GitHub** | `.md` commit 후 자동 native 렌더링 |
| **Obsidian / Notion / Typora** | 자동 지원 |
| **PNG/SVG export** | `npm i -g @mermaid-js/mermaid-cli; mmdc -i MODEL_UML.md -o diagram.png` |

raw text 보고 있다면 → 위 도구 중 하나로 열면 mermaid 블록이 *그림* 으로 렌더링.
