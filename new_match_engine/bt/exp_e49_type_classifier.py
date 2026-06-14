"""E49 — 적-유형 classifier 통합: t=50 형상분류 → 유형별 독트린. A3 승리 ∧ 15 보존 (16/17 목표).

E48 분리 확정: A3=reopen<3000(tight standoff lagger), D2=aa_min>30 ∧ rmin>3000(wide-orbit evader),
승자15=둘다 미해당. → base로 50s 관측·분류·래치. A3형→forced merge(LEAD_TURN→GUN, 판정),
D2형→best-effort, else→base 유지(승자 보존). 형상 classifier=사용자 가설 실현. usage: python exp_e49_type_classifier.py [dur]
"""
from __future__ import annotations
import sys, os, math, warnings
warnings.filterwarnings("ignore")
sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "control"))

from exp_e22_chaseforce import _opp
from exp_e27_adaptive_subset import AdaptivePolicy
from lqr import GainScheduledLQR
from autopilot import AutopilotConfig
from match import Match
from scenarios import spawn_adt_neutral
from obs import compute_obs
from tactic import Tactic
from exp_e7_champion import _train
from exp_e10_unified import DS_DA

T = Tactic
FULL = ["anchor_simple", "anchor_aggressive", "anchor_defensive", "anchor_ace",
        "A1_PurePursuer", "A2_GunTracker", "A3_LagAngler", "B1_EnergyFighter", "B2_Extender",
        "C1_TwoCircleRate", "C2_OneCircleRad", "C3_Lufbery", "D1_Reactive", "D2_LastDitch",
        "D3_Scissors", "E1_AdaptiveAce", "E2_Passive"]
DRAWS = {"A3_LagAngler", "D2_LastDitch"}
WEZ = 3000.0
T_CLASS = float(os.environ.get("NME_TCLASS", "50.0"))


class TypeClassifierPolicy:
    """base 50s 관측 → 궤적-형상 분류(A3형/D2형/일반) → 유형별 독트린 래치."""
    def __init__(self, rf, tac, gated=True):
        self.base = AdaptivePolicy(rf, tac, corrections=True)
        self.gated = gated
        self.t = 0.0; self.rmin = 9e9; self.aa_min = 999.0
        self.typ = None; self.ph = 0       # typ: None/'A3'/'D2'/'base'
        self.t_det = 0.0                   # D2 시퀀스 시작시각(조기탐지)

    def select(self, p1, p2) -> Tactic:
        o = compute_obs(p1, p2); self.t += 0.1
        if o.ego_alt_ft < 2500: return Tactic.CLIMB
        if self.t <= T_CLASS:
            self.rmin = min(self.rmin, o.distance_ft)
            self.aa_min = min(self.aa_min, o.aa_deg)
        if not self.gated:
            return self.base.select(p1, p2)
        # ── t=T_CLASS 형상 분류(한 번, 래치). D2 먼저(aa_min↑ wide-orbit), 그다음 A3(tight standoff) ──
        #   조기탐지는 불가(t<40엔 D2 시그니처가 모든 미진입 적과 겹침=관측-행동 deadlock).
        if self.typ is None and self.t > T_CLASS:
            reopen = o.distance_ft - self.rmin
            if self.aa_min > 30.0 and self.rmin > 3000.0:    # D2형: wide-orbit, 꼬리 못잡음
                self.typ = "D2"; self.t_det = self.t
            elif reopen < 3000.0:                            # A3형: tight standoff
                self.typ = "A3"
            else:
                self.typ = "base"
        # ── 유형별 독트린 ──
        if self.typ == "A3":                                 # A3형: forced merge + ETM 예측조준(판정승)
            if self.ph == 0 and o.distance_ft < WEZ: self.ph = 1
            if self.ph == 1 and o.distance_ft > WEZ * 1.8: self.ph = 0
            return T.ETM_TRACK if self.ph == 1 else T.LEAD_PURSUIT
        if self.typ == "D2":                                 # D2형: 전역최적화 발견 시퀀스(판정승 100:94)
            #   LEAD→VERTICAL→SCISSORS→GUN→LAG→ETM. *조기탐지(t_det) 기준* — 머지기하 보존 위해 일찍 시작.
            seq = [T.LEAD_PURSUIT, T.VERTICAL_PURSUIT, T.SCISSORS, T.GUN_TRACK, T.LAG_PURSUIT, T.ETM_TRACK]
            return seq[min(5, int((self.t - self.t_det) / 28.0))]
        return self.base.select(p1, p2)                      # 일반=base(승자 보존)


def main(dur=200.0):
    rf, tac = _train(DS_DA)
    gs = GainScheduledLQR([5000, 15000, 25000], [250, 350, 450]).build()
    cfg = AutopilotConfig(KP_PSI=0.25); cfg.MAX_PSI_RATE = math.radians(20.0)
    print(f"=== E49 유형 classifier {dur:.0f}s (16/17 목표) ===", flush=True)
    print(f"{'opp':<18}{'base':<8}{'CLF':<8}{'유형':<6}{'변화'}", flush=True)
    nb = ng = 0
    for opp in FULL:
        # base
        p1, p2 = spawn_adt_neutral(); pb = TypeClassifierPolicy(rf, tac, gated=False)
        mb = Match(p1, p2, gs, cfg1=cfg, cfg2=AutopilotConfig(KP_PSI=0.10), control_hz=20, bt_hz=10, log_hz=60, controller1="indi", controller2="lqr")
        rb = mb.run(tactic_fn1=lambda o: pb.select(p1, p2), tactic_fn2=lambda o, opp=opp: _opp(opp)(compute_obs(p2, p1)), duration_s=dur)
        bmk = "격" if rb.health2 <= 0 else ("승" if rb.health1 > rb.health2 else ("패" if rb.health1 < rb.health2 else "무"))
        # classifier
        p1, p2 = spawn_adt_neutral(); pc = TypeClassifierPolicy(rf, tac, gated=True)
        mc = Match(p1, p2, gs, cfg1=cfg, cfg2=AutopilotConfig(KP_PSI=0.10), control_hz=20, bt_hz=10, log_hz=60, controller1="indi", controller2="lqr")
        rc = mc.run(tactic_fn1=lambda o: pc.select(p1, p2), tactic_fn2=lambda o, opp=opp: _opp(opp)(compute_obs(p2, p1)), duration_s=dur)
        cmk = "격" if rc.health2 <= 0 else ("승" if rc.health1 > rc.health2 else ("패" if rc.health1 < rc.health2 else "무"))
        if opp in DRAWS:                                      # 무승부형 classifier 매치 replay 저장(규율)
            try:
                from replay import next_run_dir, write_acmi_plot, write_csv
                from plot_match_3d_nme import analyze_match_files
                rd = next_run_dir(os.path.join(os.path.dirname(__file__), "..", "replays", "research_etm"), prefix=f"{opp}_CLF")
                ac = os.path.join(rd, "match.acmi"); cp = os.path.join(rd, "match.csv")
                write_acmi_plot(rc.log, ac, title=f"{opp}_CLF"); write_csv(rc.log, cp)
                analyze_match_files(ac, meta_path=cp, out_dir=rd, title=f"{opp}_CLF", make_plot=True)
            except Exception as e: print("  replay err", e)
        if bmk in "격승": nb += 1
        if cmk in "격승": ng += 1
        chg = "  ←개선" if (bmk == "무" and cmk in "격승") else ("  ←회귀!" if (bmk in "격승" and cmk in "무패") else "")
        print(f"{opp:<18}{bmk+f'({rb.damage_dealt1:.0f})':<8}{cmk+f'({rc.damage_dealt1:.0f})':<8}{(pc.typ or '-'):<6}{chg}", flush=True)
    print(f"\nbase 승{nb}/17  →  classifier 승{ng}/17", flush=True)


if __name__ == "__main__":
    main(float(sys.argv[1]) if len(sys.argv) > 1 else 200.0)
