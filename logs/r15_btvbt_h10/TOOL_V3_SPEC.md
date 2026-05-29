# plot_match_3d_v2.py 개선 도출 + v3 구현 (TOOL_V3_SPEC)

*작성 2026-05-29 / 대상: `tools/plot_match_3d_v2.py` / 목적: 8 DRAW root-cause 판별력 강화*

---

## 0. 도출 방법론

> **진단 도구의 가치 = 경쟁하는 root-cause 가설을 *구별(discriminate)* 하는 능력.**

따라서 개선 항목을 "있으면 좋은 기능"이 아니라 **"8 DRAW의 각 가설쌍을 가르는 관찰값이 무엇이고, 도구가 그것을 surface 하는가?"** 로 역산했다. 도구가 그 관찰값을 안 보여주면 → 그게 도출된 개선이다.

### 판별 행렬 (discrimination matrix)

| draw 클러스터 | 갈라야 할 가설 H0 vs H1 | 판별 관찰값 | v2 현황 | → 개선 |
|---|---|---|---|---|
| **전체(중심)** | "representation/물리 한계" vs "policy degenerate" | *명령*(제어입력·bin) vs *달성*(운동학) | ❌ 명령 무시 | **A1, A2** |
| C-agg vs C-def | extension 무기동 vs 추적 불안정 | hdg 명령 분포 + WEZ dwell | △ dwell만 | A1/A2 |
| B (v51) | 진짜 center-분리 spiral vs 오분류된 직선/진동 | circle-fit **잔차** | ❌ 잔차 없음 | **B1** |
| v10 | 진짜 ±180° 위상고정 평형 vs 고분산 noise | phase-lock 비율 + 정상성 | ❌ std/mean만 | **B2** |
| 분류기(v7 오탐) | 단조 extend vs 대진폭 진동 | slope 부호 일관성 | ❌ 평균비, first-match | **B3** |
| 분산(v6h*) | 평균이 win vs 구조적 draw | N-run mean±std | ❌ 단일 replay | C (보류) |
| C-def 실현성 | cutoff 가능 vs 동속 가망없음 | lead bearing vs heading + 속도 | ❌ geometry 없음 | D (보류) |

### 핵심 진단 (이 도출의 근거)
- ACMI에 `RollControlInput/PitchControlInput/YawControlInput/Throttle`이 A·B 양쪽, 매 tick 기록돼 있으나 **v2는 완전히 무시**. → "명령(원인)"을 못 봄.
- meta CSV의 per-agent **운동학** 필드(`ego_vc_kts`,`specific_energy_ft`,`ata_deg`,`turn_rate_degs`)는 A→B **복사 버그로 오염**(`runner.py:388`). 단 `action_*`/`active_node`는 per-agent **정상**. → A2는 action만 화이트리스트.
- ACMI per-object(T=/HDG=/CAS=)는 genuine(교차검증: ace CAS A 427 vs B 408). → 운동학은 항상 ACMI에서.

---

## 1. 구현된 개선 (v3)

### A1 — ACMI 제어입력 + 포화율 + ROOT-CAUSE VERDICT  ✅
- **무엇**: `RollControlInput/PitchControlInput/Throttle`(A·B) 파싱 → Row5 타임라인 패널 2개 + `saturation_stats()`(|input|>0.9 비율) + `_root_cause_verdict()`.
- **왜**: 중심 질문을 직접 가르는 단일 관찰값. roll≈0 → *선회 명령 안 함*(POLICY DEGENERATE), roll 포화 → *명령했으나 못 따라감*(PHYSICS LIMIT). 데이터가 이미 파일에 있어 비용≈0.
- **어떻게**: 진단 박스에 `ROOT-CAUSE VERDICT` 자동 출력 → 8 DRAW를 '물리 한계'/'정책 결함'/'추적 불안정' 3분류.

### A2 — bin action 오버레이 + 분포 자동 판정  ✅
- **무엇**: sibling `*_meta.csv`(또는 `--meta`)에서 `action_hdg/vel/alt`+`active_node` 로드(`load_meta_actions`, 구·신 컬럼명 fallback) → Row5 step-plot + `_action_distribution_str()`.
- **왜**: 결정 레벨(어느 bin을 골랐나)을 보여줌. 운동학 오염 컬럼은 **읽지 않음**(가드).
- **검증 결과**(실측 자동 재현):
  - aggressive: `hdg=4 91% / vel=4 94%` → `>>> DEGENERATE: 직진+풀가속 우세`
  - defensive: `hard-turn 83%` → `>>> 급선회 우세 — 기동 중(추적/전환 문제)`
  - → C-agg/C-def 클러스터 분리가 손분석 없이 자동화됨.

### B1 — circle-fit 정규화 잔차 게이트  ✅
- **무엇**: `fit_circle()`이 `resid_norm = RMS(점-원거리)/R` 추가 반환. `good_circle()`(임계 0.25), top-down·진단텍스트에 resid 표기, 게이트 실패 fit은 흐리게+`(X)`.
- **왜**: 직선/figure-8도 lstsq가 가짜 원을 뱉음 → v2는 그걸 믿어 B 오판. 잔차로 "진짜 원인지" 판정.

### B2 — phase-lock 정량  ✅
- **무엇**: `compute_phase_lock()` → `lock_frac_0`(동상), `lock_frac_180`(역상=figure-8 평형), `drift`(50구간 평균 std). 진단텍스트 + 분류기에 사용.
- **왜**: std>60만으론 co-centric scissors와 못 구분. lock180 높고 drift 작으면 → 진짜 Nash 평형(v10은 draw 유지가 합리).

### B3 — 분류기 단조성 + 점수기반 argmax  ✅
- **무엇**: `classify_pattern()`이 `(label, scores)` 반환. C는 `dist_monotonic_frac>0.7` 필수. circle 패턴은 `good_circle` 게이트. figure-8은 `lock_frac_180` 점수. first-match return 제거 → argmax.
- **왜**: v2의 `late_dist>1.5*early`는 대진폭 진동(v7)을 C로 오탐(K_HYPOTHESES L156-158 자인). 잘못된 패턴 → 잘못된 K-hint 차단.

---

## 2. 보류 (필요 시 구현)

### C — 다중 run 집계 (`--replays <glob>`)
- WEZ dwell·dmg·pattern을 N개 replay에 걸쳐 mean±std 테이블. 설계문서 **P1**(v6h5a/b/e1c 5-run 재측정)에 직결. 단일 replay론 "평균이 win인가"를 원리적으로 답 못 하므로, 분산 클러스터 본격 검증 시 필수.

### D — cutoff/lead geometry 패널
- 적 상대위치+속도로 이상적 lead/collision bearing 계산, 실제 heading과 차이 + 속도패리티. C-def에서 "cutoff 가능했나 vs 동속 원천불가" 판별. K3 구현 가치 사전 판정용.

---

## 3. 사용법

```bash
# 기본 (ACMI만 — A1/B1/B2/B3 동작)
python tools/plot_match_3d_v2.py --replay <match.acmi> --out diag.png

# bin action 포함 (A2 — sibling *_meta.csv 자동 탐색, 또는 명시)
python tools/plot_match_3d_v2.py --replay <match.acmi> --meta <match_meta.csv>
```

출력 진단 박스 핵심 필드:
- `ROOT-CAUSE VERDICT`: POLICY DEGENERATE / PHYSICS LIMIT / MIXED / ENGAGING
- `CTRL(us)`: roll·pitch 평균크기 + 포화%
- `action`: hdg=4%/hard-turn%/vel=4%/decel% (+ DEGENERATE 플래그)
- `circle fit ... resid`: 원 신뢰도
- `phase: lock0%/lock180%/drift`

### 8 DRAW 적용 워크플로
각 draw opp의 H10-config ACMI(+meta CSV)를 생성 후:
```bash
for opp in defensive aggressive ace v6h5a v6h5b v6h_e1c v10 v51; do
  python tools/plot_match_3d_v2.py --replay <$opp>.acmi --meta <$opp>_meta.csv \
      --out logs/r15_btvbt_h10/diag_$opp.png
done
```
VERDICT 한 줄로 클러스터 즉시 분류 → 설계문서(K_STALEMATE_DESIGN.md) 가설 확정.

---

## 4. 검증 상태
- syntax OK, ACMI-only 실행 OK(ace), --meta 실행 OK(전체 5행 렌더).
- A2 자동판정이 손분석 결과(aggressive hdg=4 91%, defensive hard-turn 83%) 재현 확인.
- 제약: H10-config ACMI 미보유(보유: replays_h1/replays_v51) → 8 DRAW 본 진단은 해당 config 매치 재생성 후(엔진 필요). 도구는 준비 완료.
