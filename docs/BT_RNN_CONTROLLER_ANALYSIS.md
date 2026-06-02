# BT → RNN 제어기 분석 (2026-06-01 ~ 06-02)

> ⚠️ **읽는 순서 — §10~15 가 최신·정본** (2026-06-02, 새 엔진 v0.11 전수실측 기준).
> §1~9 는 **구엔진(v0.10)/H40b 시절 역사적 기록**으로, 일부는 새 엔진에서 무효다.
> - §요약·§4·§5·§7b 의 **"throttle 0.5 고정 / vel0~3 감속"은 구엔진 현상** — 새 엔진은
>   **§10 규칙1: 감속 자체가 없다** (vel0/1/2 전부 throttle≈0.40·335kt, vel3=0.71·377kt, vel4=0.85·398kt).
> - §2 의 "RNN 입력 12차원(BT action 포함)" → 실제는 **15차원 norm_obs**(§15.1, BT action 미포함).
> - §9 의 "85/100(H40b)" → 최신은 **§13: seed0 17/17(extender 제외)·무피탄, 단 진영 비대칭 미해결**.
> - 단위/부호/매핑 혼동 방지는 **§15(파이프라인 레퍼런스)** 가 기준이다.

## 요약 (구엔진 — 역사적)

(구엔진) BT 고수준 vel bin 이 RNN 저수준 throttle 에 반영 안 됨 — vel=4 에도 throttle 0.5 고정.
→ **새 엔진 정정(§10 규칙1): 병목이 아니라 "감속이 없는" 것** — vel0/1/2 가 모두 throttle≈0.40
으로 동일(바닥), vel3/4 만 가속. "vel=1 감속" 류 명령은 전부 placebo.

---

## 1. 제어 파이프라인 구조

```
BT Action (cost_branch_selector.py)
    ↓  [delta_alt_idx, delta_hdg_idx, delta_vel_idx]  5×9×5 discrete
singlecombat_task (norm_obs 15-dim 조립, §15.1 — BT action 미포함)
    ↓
RNN (GRU, 128-hidden, 5Hz)
    ↓  [aileron, elevator, rudder, throttle] continuous
JSBSim (6-DOF physics, 20Hz)
```

---

## 10. ★ BT 액션공간 전수 transfer-function 매핑 (2026-06-02)

> **모든 전략은 이 매핑/분해능 위에서 짠다.** 정본 데이터: `results/bt_rnn_map.csv`
> (225행 = alt5×hdg9×vel5 전수). 재측정: `python tools/verify/probe_bt_rnn_map.py`
> (env `PROBE_ACTION="alt,hdg,vel"` 로 고정액션 주입 → ACMI 위치델타로 실제 CAS/turn/climb).

### 10.1 도출된 5규칙 (steady-state)

| # | 규칙 | 함의 |
|---|---|---|
| **1** | **감속 없음** | vel 0/1/2 전부 throttle≈0.40, CAS≈335kt(동일·바닥). 가속은 vel=3(0.71,377kt)/vel=4(0.85,398kt)뿐. "vel=1 감속" 류는 전부 placebo |
| **2** | **선회율 비대칭** | 좌(hdg0-3)≈**−13°/s**, 우(hdg5-8)≈**+10°/s**. 좌선회가 빠르다. 180°선회≈14s(~70틱) |
| **3** | **hdg 분해능 포화** | hdg0≈hdg1, hdg7≈hdg8(극단 bin 중복). 미세보정 최소 단위=±1bin(22.5°) → 6° 미세 misalignment 보정 불가 |
| **4** | **선회·throttle·pitch 결합** | 강선회(hdg0,1,7,8)+vel≥3 → 자동 thr0.88+상승(에너지유지). 약선회(2,3,5,6) → thr0.40+강하(E소모). "평평한 에너지보존 선회"는 명령 불가 |
| **5** | **수직축만 비대칭 살아있음** | alt 선형: a0 −354ft/s … a2 level … a4 +325ft/s. 수평 stern-chase는 동일기체라 교착, 수직만 ±325ft/s 권한 |

### 10.2 sweet spots
- 최고속 직진 **a1 h4 v4 = 408kt** · 최대상승 **a4 h4 v2 = +325ft/s** · 최대강하 **a0 h4 v4 = −354ft/s**
- 에너지보존 강선회 **a4 h5 v2**(turn+10/climb+206) · **a2 h7 v3**(turn+10/climb+76)

---

## 11. ★ 구엔진 vs 새엔진 (왜 챔피언이 깨졌나, 2026-06-02)

구엔진(0ef1121, worktree) 동일 probe → `results/bt_rnn_map_OLDENGINE.csv`. **config·BT주기
(dt0.05/BT10Hz)·python코드 전부 동일, 오직 RNN(.pyd: task/actions/conditions)만 변경.**

| 항목 | 구엔진 | 새엔진 | 차이 |
|---|---|---|---|
| CAS vel0 | 442 | 332 | **−110kt** |
| CAS vel4 | 513 | 398 | **−115kt** (평균 −107) |
| 우선회 h6 | +13.8 | +9.2 | 비대칭 심화 |
| 상승 a4 | +406 | +325 | −81 |

→ 같은 BT 액션이 새엔진서 **평균 −107kt 느림 + 우선회 약화**. 구엔진 챔피언(빠른속도로 추격·기동)이
새엔진서 전면 무력화된 근본 원인. **속도회복은 RNN(.pyd) 안이라 BT로 불가** → per-situation
기동을 새 맵 기준 재설계(에너지비축: 추격기동 감속제거→vel3+) 필요.

---

## 12. ★ 승리 메커니즘 = 에너지유지 figure-8 (2026-06-02)

구엔진 v6 승(9.3dmg) 궤적 = **A' figure-8 lemniscate (two-circle)**: us 큰원(에너지유지) +
적 작은원(out-turn=에너지소모) + 180° phase lock + **sustained WEZ 23~39틱**. 새엔진은 −107kt로
에너지 부족 → figure-8 붕괴(phase lock 42%→14%, WEZ 0). 분석도구: `tools/plot_match_3d_v2.py`.

**해법(검증됨)**: 추격기동(gun/lead/offensive/cutoff) 감속제거→vel3 + 에너지효율(적 과선회 시
직진비축) + overshoot 적-동기 강선회 + 극심고갈 직진비축. dealt 5배, 다수 격추급(14.7), 무피탄.

---

## 13. ★★ 비결정성 = side switch (반드시 인지, 2026-06-02)

`singlecombat_env.py:61 self.np_random.shuffle(init_states)` — **매 reset마다 두 기체 spawn 위치를
셔플(진영 교환)**. 양 진영 공정평가용 의도적 설계(노이즈 아님). `config.disable_side_switch=True`로 끔.

- **함의**: upstream 기본 매치(seed 미고정)는 **매번 다른 spawn = 비결정적**. 같은 매치도 승/무 갈림.
- **검증 인프라**: `MATCH_SEED` env (우리가 추가, `src/match/runner_core.py`) → `env.seed()+reset(seed=)`
  로 deterministic. **torch/np seed 만으론 env 자체 np_random 안잡힘** — env.seed 필수.
- **진영은 2가지**(init_states 2개 shuffle): seed 0/1/2=진영A, seed 3=진영B.

### 13.1 진영 비대칭 (좌/우 선회 비대칭 — 미해결 과제)
규칙2(좌선회 −13 > 우선회 +10)로 인해 **진영에 따라 승률 갈림**:
- **진영A(seed0)**: 우리 좌선회 우세(448:202) → figure-8 성립 → **17/17 전승**
- **진영B(seed3)**: 우리 우선회 강제(221:497, RNN 약한쪽) → figure-8 실패 → **W5**

원인: 우리 선회 방향을 **rel_b(적 위치)** 로 정함 → 진영 바뀌면 선회방향 반대 → RNN 비대칭 노출.
**해결방향**: 선회를 rel_b 아닌 **d_aa(적 선회방향)** 기반 two-circle 로 → 적 선회방향은 진영무관
일관(d_aa>0 우세) → 진영 대칭. **진짜 전승 = 양 진영 robust(extender 3 제외 17/17 × 모든 spawn).**

---

## 14. 관련 메모리 / 자산
- `results/bt_rnn_map.csv`(새), `bt_rnn_map_OLDENGINE.csv`(구) — 전수 매핑
- `tools/verify/probe_bt_rnn_map.py` — 매핑 재측정 · `tools/plot_match_3d_v2.py` — 궤적 정밀분석
- worktree `c:/Users/USER/Desktop/AI-pilot/oldengine`(0ef1121 구엔진) — 비교용
- 검증: `MATCH_SEED=0 python tools/bench_zoo_precise.py` (deterministic) · multi-seed 로 robust 확인

---

## 15. ★★★ 파이프라인 데이터·단위 레퍼런스 (오해 방지 — 매번 참조)

> 모든 전략은 이 단위/부호 규약 위에서 짠다. 단계마다 단위계가 다르므로 혼동 금물.
> **코드 근거**: `singlecombat_task.py`(state_var/norm_obs/normalize_action), `behavior_tree/task.py`(get_obs).

### 15.1 4단계 데이터 흐름 + 단위계

| 단계 | 데이터 | 단위계 | 비고 |
|---|---|---|---|
| **① JSBSim raw** (state_var 16개) | lon/lat(°), alt(**m**), roll/pitch/yaw(**rad**), v_n/e/d·v_body·vc(**m/s**), accel(G) | **SI** | 원천 |
| **② RNN 입력** (norm_obs 15-dim) | alt/5000, sin/cos(roll·pitch), v_body/**340**, vc/340, Δvc/340, Δalt/1000, **AO, TA**, R/**10000**, side_flag | **정규화**(무차원) | 340m/s=음속, clip[-10,10] |
| **③ RNN 출력→제어** (normalize_action) | aileron/elev/rud = idx/20−1 → **[−1,1]**, throttle = idx/58+0.4 | 정규화 cmd | ※소스는 구버전(throttle [0.4,0.9]); **새 .pyd=[0.2,1.0]**, 실측(§10)이 기준 |
| **④ BT obs dict** (get_obs) | ego_altitude_**ft**, ego_vc_**kts**, distance_**ft**, ata/aa/hca/closure(**deg/kts**) | **imperial** | `meters_to_feet ×3.28084`, `ms_to_knots ×1.94384` |

### 15.2 BT 출력 액션 bin (③의 입력 = high-level command)
`[delta_alt_idx, delta_hdg_idx, delta_vel_idx]` 3-discrete:
- **alt**: 0=강하 / 2=level / 4=상승 (실측 ±325ft/s, §10)
- **hdg**: 0=좌 max(−13°/s) / 4=직진 / 8=우 max(+10°/s). **22.5°/bin, 좌>우 비대칭**(§10 규칙2)
- **vel**: 0~2=throttle 바닥(0.40,~335kt) / 3=0.71 / 4=0.85. **감속 불가**(§10 규칙1)

### 15.3 부호·관측 규약 (오해 多 — 엄수)
- **rel_b**(relative_bearing_deg): 적 위치 방위. **우+ / 좌−**. → 우리 선회 sign 으로 쓰임(진영 비대칭 원인 §13.1)
- **ata**(antenna train angle): 우리 nose→적, 0~180°. WEZ 조건 ata<12°
- **aa**(aspect angle): 적 tail→우리, 0~180°
- **d_aa**: 적 aspect 변화율 = **적 선회방향 proxy**(진영 무관 일관 → 진영대칭 해법, §13.1)
- **pos_adv**(positional_advantage_deg) = **aa − ata** (features.py L71)
- **omega_opp_degs**: 적 turn rate |d(aa)/dt| · **closure**: kts(+접근/−이격) · **dist**: ft

### 15.4 ★ 알려진 데이터 버그 (신뢰 금지 — 반복 오판 원인)
- **CSV angle 전부 버그**: `blackboard.observation` 이 global key → last-writer-wins → **us=opp 동일**.
  ata 만 `runner.py` 에서 debug_info(per-agent WEZ) 로 수정. **aa/hca/tau/closure/rel_b/vc CSV 는 신뢰 금지**.
- **신뢰 가능**: dmg(=100−opp_HP), in_wez, dist_ft, throttle(ll_act), action bins, ego_altitude_ft.
- 분석 지표는 **dmg/HP/dist** 직접 사용 (angle CSV 아님). 궤적은 **ACMI 물리값**(plot_match_3d_v2).

### 15.5 운영 원칙
**매 전략 사이클마다 이 §10~15 를 참조하고, 새 측정/발견 시 업데이트한다.** 특히 ①BT bin↔실측
매핑(§10) ②단위계 전환(§15.1) ③부호규약(§15.3) ④CSV 버그(§15.4) 를 혼동하면 과거처럼 오판
(ata 86 고착·over-bank·충돌 천장 등)이 반복된다. **실측(probe/plot)이 항상 소스 추정보다 우선.**

---

## 16. ★★★★ obs 방향성(부호) 분해능 — "이래서 성과가 안 났다" (2026-06-02)

> 적/우리 **선회 방향**을 obs 로 보려면 어느 키가 부호(방향)를 갖는지 알아야 한다. 소스코드 +
> 런타임 dump(`DUMP_FEAT` env, cost_branch_selector) + ACMI(GT) 3중 교차검증 결과.

### 16.1 ★ obs 각도는 대부분 절대값 (방향 정보 없음!)
소스 확정 (`combat_geometry.py`, `utils.get_AO_TA_R`):
- **turn_rate_degs** = g·tan(**abs(roll)**)/v (L223) → **절대값**. 우리 선회"율"이지 방향 아님.
- **AO/TA** = np.arccos(...) (L74,76) → **[0,π] 절대값**. 적과의 각도 크기만.
- **ata/aa/hca/tau** = arccos/정규화 → **0~180 절대값** (런타임 dump 음수 0% 확인).

### 16.2 부호(방향) 가진 obs = 단 3개
| obs 키 | 의미 | 검증(ACMI GT) |
|---|---|---|
| **roll_deg** | 우리 뱅크 = **우리 선회방향** | **부호일치 100%, 상관 +0.96** (정렬 sanity roll vs ACMI roll 100%) |
| **rel_b**(relative_bearing_deg) | 적 위치 방위(우+/좌−) | 부호 67% (정규화 [−180,180]) |
| **side_flag** | sign(cross(우리 velocity, 적방향)) = 적 좌(−)/우(+) | 부호 있음 |

### 16.3 ★ 헛걸음의 근본
- **우리 선회방향을 turn_rate(절대값, 28%)로 보려 했다** → 방향 정보가 아예 없음. **roll_deg(100%)를 써야 했다.**
- **적 선회방향을 d_aa(=절대값 aa 의 변화)로 보려 했다** → aa 가 절대값이라 부호 60%/37% = random. 불가능했던 것.
- → 과거 "충돌/천장/진영 비대칭"의 상당수가 이 **방향 feature 부재**가 원인.

### 16.4 ★ 적 선회방향 — obs 로 뽑아내는 방법 (검증됨, 90%)
적 roll/heading 은 obs 미노출이지만 **있는 obs 로 재구성 가능** (2026-06-02 검증):
```
적 상대위치 = dist_ft × [cos(heading+rel_b), sin(heading+rel_b)]   # obs: dist,heading,rel_b
적 상대velocity = d(적상대위치)/dt,   dt=0.1s/틱 (★중요: 매치 75s/750틱=0.1, 0.2아님)
적 절대velocity = vc_kts×1.688×[cos(heading),sin(heading)] + 적상대velocity   # obs: vc,heading
적 heading = atan2(적절대vy, 적절대vx) → unwrap → smooth(window 20~40틱)
적 선회방향 = d(smooth된 적heading)
```
**분해능 검증 (vs ACMI 적 course)**: raw 62% → smooth w20 **87%/상관0.67** → w40 **90%/상관0.85**.
(d_aa 60% 대비 대폭 개선). 핵심: 선회방향(저주파)은 dist/각도 obs noise 보다 느려서 smoothing 으로 분리.
- 실시간 적용: backward window(과거 20~40틱) → 2~4초 지연이나 선회방향(좌/우)엔 무방.
- 대안(최정밀): task.py(.pyd) 재빌드로 enm_vel→적 course obs 정식 노출 (지연 0).

### 16.5 즉시 적용 (진영 비대칭, §13.1)
**우리 선회방향이 roll_deg 로 100% 관측 가능**하므로, 진영 대칭은 "우리가 원하는 선회방향을
roll 로 확인하며 제어"로 접근 가능. turn_rate(절대값) 기반 판단은 전부 재검토 대상.
도구: `DUMP_FEAT=path` env (cost_branch_selector) 로 obs feature 런타임 dump → ACMI 와 분해능 비교.

### 16.6 ★ compute_features derived 정확도 — cost 가 부정확값 써온 근본 (2026-06-02)
obs 직접값뿐 아니라 **파생(derived) feature 도 재계산 필요**한 게 많다 (DUMP_FEAT+ACMI 측정):

| derived | 계산식 | 정확도 | 조치 |
|---|---|---|---|
| `omega_opp_degs` | `\|d_aa\|` | **60%** (방향+크기 부정확) | → `\|omega_opp_signed\|`(90%) 로 대체 |
| `omega_opp_signed` | 적 heading 재구성(§16.4) | **90%/상관0.85** | ✅ 채택 (선회방향) |
| `V_opp_kts` | √(vc²−2g(ediff+altgap)) | **평균오차 74kt(17%)** | energy obs 부정확/sideslip — cost 신뢰도↓ or 보정 |
| `R_opp_ft`,`R_advantage_ft` | `V_opp/omega_opp_degs` | **❌❌ 연쇄로 매우 부정확** | omega_opp_signed + V_opp 보정으로 재계산 필수 |
| `d_ata`,`d_pos`,`d_es` | 절대값 feature 의 /0.1 미분 | 부호有 but 우리+적 섞임(proxy) | 우리선회(roll) 보정 검토 |
| `turn_rate`,`R_us_ft` | abs(roll) 기반 크기 | ✅ 크기 정확 | 유지(방향엔 못씀) |
| `pos_adv` | `aa−ata` | ✅ 상대량 | 유지 |

**교훈**: cost 의 one-circle/inside 판정(`R_advantage`), 적 선회(`omega_opp`), 적 속도(`V_opp`)가 전부
부정확값 기반이었음 → cost 튜닝이 헛돌던 근본 중 하나. **새 feature 도입 시 항상 §16 방식(DUMP+ACMI)
으로 분해능부터 측정**하고, 부정확하면 재구성(§16.4) 하거나 cost 가중치를 낮춘다.
