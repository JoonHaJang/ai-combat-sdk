# Patches — 가설별 변경분 보존

## 원칙

- **main (= `feat/phase1-mpc`, commit `4cdcb90` = H13)**: 절대 직접 수정 금지. baseline.
- **가설 H_N마다 git branch + .patch 둘 다**:
  - branch: `hyp/hN-<short-desc>` 에서 실험
  - patch: `patches/HN_<desc>.patch` 도 동시 저장 (cherry-pick 없이 빠른 복원)
- **5x bench 실행 동안 작업트리/git switch 금지** — bench 결과 오염 방지.
- 검증 통과한 가설만 main 으로 squash-merge.

## 가설 이력

| ID | 설명 | branch | patch | 결과 |
|---|---|---|---|---|
| H13 (main) | ACE deterministic 보존, taken 개선 | `feat/phase1-mpc` | (commit 4cdcb90) | 571/0.0/85 baseline |
| H17 | OFFP rule 3 vel=2→4 | (none) | `H17_offp_rule3_vel4.patch` | 단독 폐기 — ACE 4.82, AGG 0 |
| H18 | rule 3 lateral bias drop | (none) | (in workinprogress.patch) | 폐기 — 무의미 |
| H19 | rule 3 alt=1 dive | (none) | (in workinprogress.patch) | 421.9/6.8/76 폐기 |
| H20 | K11 트리거 closure≥-50 | (none) | (none) | t=0 sentinel 이슈로 무효 |
| H20b | K11 lock 중 closure escape | (none) | `H20b_k11_escape.patch` | 284.2/0.3/67 폐기 — v7/v8/v9/v10 손실 |
| H21 | OFFP rule 1 (one_circle) closure>-50 | (none) | `H21_one_circle_closure.patch` | bench polluted, 재검증 필요 |
