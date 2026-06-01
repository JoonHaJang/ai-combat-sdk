"""H22 prototype: 적 분류 + K22 RUNNER zoom climb (2026-05-31).

bench 진행 중이라 main file 안 건드림. bench 결과 받은 후 cost_branch_selector.py 에 patch 적용.

설계 (보강된 H22):
1. _KState 에 opp_omega_window, opp_vc_window, opp_alt_window 추가
2. opp obs 가져와서 window update — obs["aa_deg"] 변화율 = opp omega proxy
3. classify_opp(state, f) — t=30 시점 분류 cached
4. _k_apply_dispatch 안에 K22 (RUNNER zoom climb) 추가
5. enabled_ks 기본값에 "K22" 포함
6. RUNNER 분류 시 cost_extension weight 강화 (-4.28 → -10.0 boost)
   현재 cost_extension base = -1.3 ~ -4.3 → OffensivePursuit(-10~-100) 보다 높은 cost.
   RUNNER 분류 확정 시 weight × 2.5 → Extension 선호도 ↑.

분류 기준 (baseline 4-target 데이터):
| OPP | opp_omega mean | closure D-phase | classification |
|---|---|---|---|
| AGG | 1.1°/s | -95 | RUNNER |
| DEF | 2.4°/s | -17 | RUNNER |
| ACE | 2.0°/s | +47 (다가옴) | DEFAULT (이미 WIN) |
| v51 | 2.7°/s | +4 | LUFBERY (orbit pattern) |
| v6-v11 | 5-7°/s | -43~-71 | TURNER |

분류 함수:
    if opp_omega < 3°/s AND closure_phaseB < -200: RUNNER
    elif dist oscillation > 5000ft + opp_omega 3-5°/s: LUFBERY
    elif opp_omega > 5°/s: TURNER
    else: DEFAULT

K22 RUNNER 대응:
- Phase 1 climb (50t): alt=4 vel=4 + mild turn → PE 형성 (~5000ft 상승)
- Phase 2 dive (30t): alt=0 vel=4 + lead turn → PE→KE 환산 + closure
- 단 1회 (per match)

ACE/v51 격파 보존: 분류가 DEFAULT/LUFBERY 면 K22 skip → 기존 logic 유지.
"""

# ─────────────────────────────────────────────────────────────────
# 1. _KState 확장 — opp 관측 window + K22 state + 분류 cache
# ─────────────────────────────────────────────────────────────────

# 추가할 필드:
#   self.opp_aa_window = []     # opp aa (우리 입장 적의 aa) — opp omega proxy 추출용
#   self.opp_vc_window = []     # opp vc kts
#   self.opp_alt_window = []    # opp altitude
#   self.k22_phase = "off"      # "off" / "climb" / "dive"
#   self.k22_phase_tick = 0
#   self.k22_triggered_once = False
#   self._opp_class = "UNKNOWN" # 분류 cache


# ─────────────────────────────────────────────────────────────────
# 2. _k_update_windows 확장
# ─────────────────────────────────────────────────────────────────

def _k_update_windows_addition(state, obs, f):
    """추가될 부분 (기존 함수 끝에)."""
    # opp aa: 우리 입장 적의 aa. 적의 omega 추정 = d(aa)/dt × 10Hz
    opp_aa = float(f.get("aa", 0.0))   # 또는 obs.get("aa_deg", 0.0)
    opp_alt = float(f.get("ego_alt", 15000.0)) + float(obs.get("alt_gap_ft", 0.0))
    # opp_vc 는 직접 obs 에 없음. closure 와 우리 vc 로 proxy
    # opp_vc = us_vc + closure  (closure positive = 다가옴 = 우리 vc 보다 옵 빠름?)
    # 더 정확: aa 와 dist 시계열로 계산. proxy 로 일단 us_vc - closure
    us_vc = float(obs.get("ego_vc_kts", 400.0))
    closure = float(f.get("closure_kts", 0.0))
    opp_vc = us_vc - closure   # closure > 0 다가옴 → us_vc > opp_vc 가정 X. proxy 한계.

    state.opp_aa_window.append(opp_aa)
    state.opp_vc_window.append(opp_vc)
    state.opp_alt_window.append(opp_alt)
    for arr in (state.opp_aa_window, state.opp_vc_window, state.opp_alt_window):
        if len(arr) > 50:
            arr.pop(0)


# ─────────────────────────────────────────────────────────────────
# 3. classify_opp — t=30 분류
# ─────────────────────────────────────────────────────────────────

def classify_opp(state):
    """spawn 0~30t opp 관측 → CLASS_{RUNNER, LUFBERY, TURNER, DEFAULT}.

    UNKNOWN 반환 (t<30 까지) → 기존 K-rule 발화.
    """
    if state.no_dmg_ticks < 30:
        return "UNKNOWN"
    if getattr(state, "_opp_class", "UNKNOWN") != "UNKNOWN":
        return state._opp_class

    # 30 tick spawn 측정
    if len(state.opp_aa_window) < 30:
        state._opp_class = "DEFAULT"
        return "DEFAULT"

    opp_aa = state.opp_aa_window[:30]
    opp_omega = [abs(opp_aa[i] - opp_aa[i-1]) * 10.0  # rad → deg/s @10Hz
                 for i in range(1, len(opp_aa))]
    mean_omega = sum(opp_omega) / len(opp_omega) if opp_omega else 0.0

    cl_in = state.closure_window[:30] if len(state.closure_window) >= 30 else []
    mean_closure = sum(cl_in) / len(cl_in) if cl_in else 0.0

    di_in = state.dist_window[:30] if len(state.dist_window) >= 30 else []
    dist_growth = (di_in[-1] - di_in[0]) if len(di_in) >= 2 else 0.0
    dist_range = (max(di_in) - min(di_in)) if di_in else 0.0

    # 분류
    if mean_omega < 3.0 and dist_growth > 1000 and mean_closure < -100:
        # RUNNER: 적 안 회전 + 거리 증가 + 도주
        state._opp_class = "RUNNER"
    elif 3.0 <= mean_omega <= 6.0 and dist_range > 3000:
        # LUFBERY: 적 적당 회전 + 거리 oscillation
        state._opp_class = "LUFBERY"
    elif mean_omega > 6.0:
        # TURNER: 적 강 회전
        state._opp_class = "TURNER"
    else:
        state._opp_class = "DEFAULT"
    return state._opp_class


# ─────────────────────────────────────────────────────────────────
# 4. K22 RUNNER zoom climb dispatch
# ─────────────────────────────────────────────────────────────────

def _k22_dispatch(state, f, obs, rel_b, dist, ata, ego_alt, enabled_ks):
    """RUNNER 적 전용 zoom climb → dive 추격.

    Phase 1 climb (50t): alt=4 vel=4 mild turn → PE 형성
    Phase 2 dive (30t):  alt=0 vel=4 lead turn → KE 환산 + closure
    단 1회 (per match)
    """
    if "K22" not in enabled_ks:
        return None, None
    opp_class = classify_opp(state)
    if opp_class != "RUNNER":
        return None, None

    if state.k22_phase == "climb":
        state.k22_phase_tick += 1
        if state.k22_phase_tick >= 50 or ego_alt > 20000 or ata < 30:
            state.k22_phase = "dive"
            state.k22_phase_tick = 0
        else:
            # mild turn (lead 만큼) + max throttle + max climb
            hdg = max(0, min(8, 4 + int(round(np.clip(rel_b / 22.5, -2, 2)))))
            return (4, hdg, 4), "K22_ZOOM_CLIMB"

    if state.k22_phase == "dive":
        state.k22_phase_tick += 1
        if state.k22_phase_tick >= 30 or dist < 3500:
            state.k22_phase = "off"
            state.k22_phase_tick = 0
        else:
            hdg = max(0, min(8, 4 + int(round(np.clip(rel_b / 22.5, -4, 4)))))
            return (0, hdg, 4), "K22_DIVE_ATTACK"

    if not state.k22_triggered_once:
        state.k22_phase = "climb"
        state.k22_phase_tick = 0
        state.k22_triggered_once = True
        hdg = max(0, min(8, 4 + int(round(np.clip(rel_b / 22.5, -2, 2)))))
        return (4, hdg, 4), "K22_ZOOM_CLIMB"

    return None, None


# ─────────────────────────────────────────────────────────────────
# 5. 통합 위치
# ─────────────────────────────────────────────────────────────────
# - _k_apply_dispatch 안에 K22 분기 추가 — K11 직전 (spawn 단계 우선순위)
# - enabled_ks 기본값에 "K22" 추가 → "K2,K8,K10,K11,K12,K22"
# - _KState __init__ 에 K22 / opp window 필드 추가
# - _k_update_windows 에 opp obs update 추가
