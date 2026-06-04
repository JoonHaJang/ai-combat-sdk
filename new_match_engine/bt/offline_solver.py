"""오프라인 Solver — 알려진 툴(sklearn DecisionTree) 기반 투명 정책 도출.

★ 사용자 지침: 온라인 rollout(constant_action 예측 약함) 폐기 + 알려진 방법론 활용.
파이프라인 (offline imitation/policy-distillation, 모두 known tools):
  ① 상태 샘플: 다양 spawn×적 매치 중 상태 스냅샷(capture_state) + feature 수집
  ② label: 각 상태서 후보 tactic 을 ★실제 적 BT 상대 forward-sim(H초)★ → best tactic
     (오프라인이라 constant_action 불필요 — 진짜 적 거동으로 정확 평가)
  ③ 정책 학습: sklearn DecisionTreeClassifier(feature→best tactic) — 완전 투명(rule)
  ④ export: 트리 규칙 출력 + situation_policy 저장 → 가벼운 dispatch 배포
"""
from __future__ import annotations
import sys, os, math
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "control"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "engine"))

import numpy as np
from lqr import GainScheduledLQR
from autopilot import AutopilotConfig
from plant import F16Plant
from pilot import Pilot
from match import Match
from scenarios import SITUATIONS
from obs import compute_obs
from tactic import Tactic, WEZ_ATA_DEG, WEZ_MIN_FT, WEZ_MAX_FT
from opponents import OPPONENT_BTS
from real_rollout import _wez_margin, _es_diff
from judge import wez_damage          # ★ 진짜 게임 규칙 (ata<12, 500~3000ft, 25HP/s)

from sklearn.ensemble import RandomForestRegressor
from sklearn.model_selection import cross_val_score

# feature (상황 기술 — 적 무관 relational/물리)
FEATS = ["ata", "aa", "hca", "dist", "closure", "es_diff", "ego_omega", "opp_omega"]
# 후보 tactic (물리 적합) — ★ ADAPTIVE(τ-블렌딩)·VERTICAL_PURSUIT(고도추종) 추가:
#   새 권역을 RF 가 데이터로 학습 → evasive/merge 전환을 손코딩 dispatch 대신 정책이 도출.
CANDS = [Tactic.PURE_PURSUIT, Tactic.LEAD_PURSUIT, Tactic.LAG_PURSUIT, Tactic.GUN_TRACK,
         Tactic.ONE_CIRCLE, Tactic.TWO_CIRCLE, Tactic.HIGH_YOYO, Tactic.BREAK_TURN,
         Tactic.ADAPTIVE, Tactic.VERTICAL_PURSUIT]

_AGGR = AutopilotConfig(KP_PSI=0.25); _AGGR.MAX_PSI_RATE = math.radians(20.0)


def _hca(o):
    return abs(((o.ego_psi_deg - o.enm_psi_deg) + 180.0) % 360.0 - 180.0)


def _phi(o12, o21):
    """potential Φ = 위치우위(wez_margin 차) + 에너지우위. shaping 용 (Ng 정리: 최적정책 불변).
    ★ 에너지 항 추가 — head-on 등서 다이브로 에너지 까먹는 것 억제 (위치만 보상하던 약점)."""
    pos = _wez_margin(o12) - _wez_margin(o21)
    energy = 0.3 * math.tanh(_es_diff(o12) / 4000.0)       # Es차 → [-0.3,+0.3]
    return pos + energy

def _feat(o12):
    return [o12.ata_deg, o12.aa_deg, _hca(o12), o12.distance_ft, o12.closure_kts,
            _es_diff(o12), o12.ego_r_dps, o12.enm_r_dps]


class _Sim:
    """forward-sim 평가기 — ★ fitted-Q 라벨 (myopia 해결).

    Q(S,T) = "S에서 T를 짧게(commit_s) 한 뒤, 그다음은 base 정책으로 끝까지" 의 진짜 데미지 차.
      · 단일 tactic을 H초 강제하면 setup 전술(circle/yoyo)이 60초 안에 빛 못 봐 과소평가됨(myopia).
      · T를 잠깐만 commit하고 이후 base 정책으로 이어가면 → T가 만든 이득을 base가 capitalize →
        setup 전술이 제값 받음. = 강화학습 n-step + bootstrap (fitted-Q / policy iteration).
    점수 = Σ(가한 − 받은) wez_damage (진짜 게임 규칙). base=None이면 PURE_PURSUIT fallback.
    """
    def __init__(self, gs, H=60.0, commit_s=4.0, base=None):
        self.gs = gs; self.H = H; self.commit_s = commit_s; self.base = base; self.chz = 20.0
        self._us = F16Plant(); self._us.set_ic(15000.0, 350.0); self._us.trim(); self._us.step(2)
        self._op = F16Plant(); self._op.set_ic(15000.0, 350.0); self._op.trim(); self._op.step(2)
        self._pu = Pilot(self._us, gs, _AGGR, 1/self.chz)
        self._po = Pilot(self._op, gs, AutopilotConfig(KP_PSI=0.10), 1/self.chz)

    def eval(self, snap_us, snap_op, tac, opp_fn):
        """T를 H초 강제 vs 실제 적BT → ★진짜 데미지 차 + potential-based shaping.

        점수 = (가한−받은 데미지) + SHAPE_K·(Φ_끝 − Φ_시작),  Φ=wez_margin(우리)−wez_margin(적).
          · 진짜 데미지가 목적 (그대로). shaping은 위치개선의 dense gradient.
          · Ng et al.(1999): potential 차는 최적정책 불변 → 편향 없이 sparse 신호 해결.
          · setup 전술(각도 개선)이 Φ↑로 즉시 credit → myopia 동시 해결.
        """
        self._us.restore_state(snap_us); self._op.restore_state(snap_op)
        cdt = 1/self.chz; n_ctrl = max(1, int(round(cdt/self._us.dt))); nt = int(self.H/cdt)
        o0 = compute_obs(self._us, self._op); o0r = compute_obs(self._op, self._us)
        phi_start = _phi(o0, o0r)
        dealt = taken = 0.0
        o12 = o0; o21 = o0r
        for k in range(nt):
            o12 = compute_obs(self._us, self._op); o21 = compute_obs(self._op, self._us)
            mytac = Tactic.CLIMB if o12.ego_alt_ft < 2500.0 else tac
            u1 = self._pu.step(self._op, tactic=mytac)
            u2 = self._po.step(self._us, tactic=opp_fn(o21))   # ★ 실제 적 BT
            self._us.set_input(u1); self._op.set_input(u2)
            dealt += wez_damage(o12.ata_deg, o12.distance_ft, cdt)
            taken += wez_damage(o21.ata_deg, o21.distance_ft, cdt)
            for _ in range(n_ctrl): self._us.step(1); self._op.step(1)
            if dealt >= 100.0 or taken >= 100.0:
                break               # 격추 결정 — 조기 종료
        oN = compute_obs(self._us, self._op); oNr = compute_obs(self._op, self._us)
        phi_end = _phi(oN, oNr)
        SHAPE_K = 20.0              # 위치/에너지 개선 1.0 ≈ 데미지 20 (HP 스케일 맞춤)
        return (dealt - taken) + SHAPE_K * (phi_end - phi_start)


def collect(gs, n_sample_per=25, match_s=90.0):
    """다양 spawn×적 매치 → 상태 샘플 + feature + ★8 tactic 점수 전부★(value 회귀용).

    ③→④ 연결: argmax 1개가 아니라 모든 tactic 의 forward-sim 점수를 보존.
    """
    sim = _Sim(gs, H=60.0)                       # ★ 진짜 데미지 라벨 (사격 일어날 만큼 길게)
    X, Y, meta = [], [], []                      # Y = [n_states × n_tactics] 데미지차 행렬
    for spawn_name, spawn_fn in SITUATIONS.items():
        for opp_name, opp_fn in OPPONENT_BTS.items():
            p1, p2 = spawn_fn()
            cdt = 0.05; nt = int(match_s/cdt); n_ctrl = 6
            from pilot import Pilot as _P
            pu = _P(p1, gs, _AGGR, 1/20.0); po = _P(p2, gs, AutopilotConfig(KP_PSI=0.10), 1/20.0)
            sample_iv = max(1, nt // n_sample_per)
            cur = Tactic.PURE_PURSUIT
            for k in range(nt):
                o12 = compute_obs(p1, p2); o21 = compute_obs(p2, p1)
                if k % sample_iv == 0 and o12.ego_alt_ft > 2500 and o12.distance_ft < 25000:
                    snap_us, snap_op = p1.capture_state(), p2.capture_state()
                    scores = [sim.eval(snap_us, snap_op, t, opp_fn) for t in CANDS]
                    X.append(_feat(o12)); Y.append(scores)   # ★ 점수 전부 보존
                    meta.append((spawn_name, opp_name))
                    p1.restore_state(snap_us); p2.restore_state(snap_op)
                    cur = CANDS[int(np.argmax(scores))]
                u1 = pu.step(p2, tactic=(Tactic.CLIMB if o12.ego_alt_ft<2500 else cur))
                u2 = po.step(p1, tactic=opp_fn(o21))
                p1.set_input(u1); p2.set_input(u2)
                for _ in range(n_ctrl): p1.step(1); p2.step(1)
                if compute_obs(p1,p2).ego_health<=0 or compute_obs(p2,p1).ego_health<=0: break
            print(f"  {spawn_name:<13} vs {opp_name:<11}: 샘플 누적 {len(X)}")
    return np.array(X, float), np.array(Y, float), meta


def solve():
    gs = GainScheduledLQR([5000, 15000, 25000], [250, 350, 450]).build()
    print("=== 오프라인 Solver — value 회귀 (③모든 점수 → ④회귀 → argmax) ===")
    X, Y, meta = collect(gs)
    import collections
    argmax_t = [CANDS[i].name for i in np.argmax(Y, axis=1)]
    print(f"\n총 {len(X)} 상태 × {len(CANDS)} tactic 점수. argmax 분포:")
    for t, c in collections.Counter(argmax_t).most_common():
        print(f"  {t:<14} {c}")

    # ④ value 회귀 (multi-output) — feature → tactic별 점수 (③ 모든 점수 사용)
    reg = RandomForestRegressor(n_estimators=120, max_depth=8, min_samples_leaf=8,
                                random_state=0, n_jobs=-1)
    # CV: 회귀 R² (점수 예측 정확도)
    cv = cross_val_score(reg, X, Y, cv=5, scoring="r2")
    reg.fit(X, Y)
    print(f"\nValue 회귀 (RandomForest): CV R²={cv.mean():.2f}±{cv.std():.2f}")
    print("feature 중요도:", {f: round(i, 2) for f, i in zip(FEATS, reg.feature_importances_)})
    # 배포 정책 = argmax 예측점수 — 학습데이터 일치도(greedy accuracy)
    pred_t = [CANDS[i].name for i in np.argmax(reg.predict(X), axis=1)]
    acc = np.mean([a == b for a, b in zip(pred_t, argmax_t)])
    print(f"greedy 정책 일치도 (예측 argmax = sim argmax): {acc:.2f}")

    import pickle
    out = os.path.join(os.path.dirname(__file__), "policy_value.pkl")
    with open(out, "wb") as f:
        pickle.dump({"reg": reg, "feats": FEATS, "tactics": [t.name for t in CANDS]}, f)
    print(f"정책 저장: {os.path.relpath(out)}")
    return reg


if __name__ == "__main__":
    solve()
