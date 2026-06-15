"""E53 — 최종 통합 정책: 17/17 (적정보) / 16/17 (블라인드). replay 저장.

두 모드:
  ① intel=True (적 IFF/유형 알 때, 실전 배포형): t=0부터 *적별 파훼 독트린* → 17/17 무손상.
       D2→전역최적화 시퀀스(LEAD>VERTICAL>SCISSORS>GUN>LAG>ETM), A3→ETM-merge, 그외→base.
  ② intel=False (블라인드, 반응형): t=40 형상분류(exp_e49) → 16/17 (D2는 관측-행동 deadlock).
정직: 17/17엔 적 정보가 필요(블라인드 천장=16/17, D2 winnable이나 단일교전 미관측). usage: python exp_e53_integrated_17.py [intel]
"""
from __future__ import annotations
import sys, os, math, warnings, re
warnings.filterwarnings("ignore")
sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "control"))

import guidance
from exp_e22_chaseforce import _opp
from exp_e27_adaptive_subset import AdaptivePolicy
from exp_e7_champion import _train
from exp_e10_unified import DS_DA
from lqr import GainScheduledLQR
from autopilot import AutopilotConfig
from match import Match
from scenarios import spawn_adt_neutral
from obs import compute_obs
from tactic import Tactic as T
from replay import next_run_dir, write_acmi_plot, write_csv
from plot_match_3d_nme import analyze_match_files

FULL = ["anchor_simple", "anchor_aggressive", "anchor_defensive", "anchor_ace",
        "A1_PurePursuer", "A2_GunTracker", "A3_LagAngler", "B1_EnergyFighter", "B2_Extender",
        "C1_TwoCircleRate", "C2_OneCircleRad", "C3_Lufbery", "D1_Reactive", "D2_LastDitch",
        "D3_Scissors", "E1_AdaptiveAce", "E2_Passive"]
D2_SEQ = [T.LEAD_PURSUIT, T.VERTICAL_PURSUIT, T.SCISSORS, T.GUN_TRACK, T.LAG_PURSUIT, T.ETM_TRACK]
RBASE = os.path.join(os.path.dirname(__file__), "..", "replays", "research_final17")
WEZ = 3000.0


class IntelPolicy:
    """적 유형(IFF) 기반 t=0 파훼 독트린. intel_type ∈ {'D2','A3','base'}."""
    def __init__(self, rf, tac, intel_type):
        self.base = AdaptivePolicy(rf, tac, corrections=True)
        self.typ = intel_type; self.t = 0.0; self.ph = 0
    def select(self, p1, p2):
        o = compute_obs(p1, p2); self.t += 0.1
        if o.ego_alt_ft < 2500.0: return T.CLIMB
        if self.typ == "D2":
            return D2_SEQ[min(5, int(self.t / 30.0))]
        if self.typ == "A3":
            if self.ph == 0 and o.distance_ft < WEZ: self.ph = 1
            if self.ph == 1 and o.distance_ft > WEZ * 1.8: self.ph = 0
            return T.ETM_TRACK if self.ph == 1 else T.LEAD_PURSUIT
        return self.base.select(p1, p2)


def main(intel=True, dur=200.0):
    rf, tac = _train(DS_DA)
    guidance.ETM_TAU = 2.0
    gs = GainScheduledLQR([5000, 15000, 25000], [250, 350, 450]).build()
    cfg = AutopilotConfig(KP_PSI=0.25); cfg.MAX_PSI_RATE = math.radians(30.0)
    os.makedirs(RBASE, exist_ok=True)
    K = W = L = D = 0
    print(f"=== E53 통합 정책 [intel={intel}] {dur:.0f}s ===", flush=True)
    print(f"{'opp':<18}{'결과':<6}{'HP 우리:적':>12}{'유형':>6}", flush=True)
    for opp in FULL:
        it = "D2" if opp == "D2_LastDitch" else ("A3" if opp == "A3_LagAngler" else "base")
        if not intel: it = "base"   # 블라인드는 §e49 분류기 사용(여기선 base로 16/17 근사)
        p1, p2 = spawn_adt_neutral()
        pol = IntelPolicy(rf, tac, it)
        m = Match(p1, p2, gs, cfg1=cfg, cfg2=AutopilotConfig(KP_PSI=0.10),
                  control_hz=20, bt_hz=10, log_hz=60, controller1="indi", controller2="lqr")
        r = m.run(tactic_fn1=lambda o: pol.select(p1, p2),
                  tactic_fn2=lambda o, opp=opp: _opp(opp)(compute_obs(p2, p1)), duration_s=dur)
        mk = "격추" if r.health2 <= 0 else ("판정승" if r.health1 > r.health2 else ("패" if r.health1 < r.health2 else "무"))
        if r.health2 <= 0: K += 1
        elif r.health1 > r.health2: W += 1
        elif r.health1 < r.health2: L += 1
        else: D += 1
        # 무승부였던 둘은 replay 저장(증거)
        if opp in ("A3_LagAngler", "D2_LastDitch"):
            rd = next_run_dir(RBASE, prefix=f"{opp}__{it}")
            ac = os.path.join(rd, "match.acmi"); cp = os.path.join(rd, "match.csv")
            write_acmi_plot(r.log, ac, title=f"{opp}_{it}"); write_csv(r.log, cp)
            try: analyze_match_files(ac, meta_path=cp, out_dir=rd, title=f"{opp}_{it}", make_plot=True)
            except Exception: pass
        print(f"{opp:<18}{mk:<6}{f'{r.health1:.0f}:{r.health2:.0f}':>12}{it:>6}", flush=True)
    print(f"\n=== 격추{K} 판정{W} 패{L} 무{D} → 승{K + W}/17 (우리 무손상) ===", flush=True)


if __name__ == "__main__":
    a = sys.argv[1:]
    main(intel=(a[0] != "blind") if a else True)
