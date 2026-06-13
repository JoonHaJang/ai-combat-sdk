"""E27 (Step B v2) — ADAPTIVE = base ⊇ subset. base를 부분집합으로 포함 + 무승부 상황만 보정.

방법론(docs/NEW_ENGINE_ADAPTIVE_METHODOLOGY.md §0): ADAPTIVE(obs)=base_vp + Σ w_s·Δ_s,
base-승리 상황에선 w_s=0 → ADAPTIVE≡base(부분집합). 무승부 상황(circle/extend)만 보정 발동.
게이트=관측-차 sigmoid(절대값 0). 보정=lead-collision cutoff(LEAD_TURN).

가정: base+게이트보정 → ace/B2/C2 격추 *보존*(부분집합 검증) + A3/D2 무승부 개선.
controller=indi(C3 튜닝). usage: python exp_e27_adaptive_subset.py [dur] [controller]
"""
from __future__ import annotations
import sys, os, math, warnings
warnings.filterwarnings("ignore")
sys.path.insert(0, os.path.dirname(__file__))

from exp_e22_chaseforce import _opp, _metrics
from lqr import GainScheduledLQR
from autopilot import AutopilotConfig
from match import Match
from scenarios import spawn_adt_neutral
from obs import compute_obs
from tactic import Tactic
from real_rollout import _es_diff
from replay import next_run_dir, write_acmi_plot, write_csv
from plot_match_3d_nme import analyze_match_files
from exp_e7_champion import _train
from exp_e10_unified import DS_DA

RBASE = os.path.join(os.path.dirname(__file__), "..", "replays", "research_subset")
SAFE = 2500.0
OPPS = ["anchor_ace", "B2_Extender", "C2_OneCircleRad", "A3_LagAngler", "D2_LastDitch"]


def _sig(x): return 1.0 / (1.0 + math.exp(-max(-30.0, min(30.0, x))))
def _hca(o): return abs(((o.ego_psi_deg - o.enm_psi_deg) + 180.0) % 360.0 - 180.0)


class AdaptivePolicy:
    """base(RF argmax+안전) + 무승부 상황 게이트 보정. corrections=False면 순수 base(부분집합 검증)."""
    def __init__(self, rf, tac, corrections=True, thr=0.6):
        self.rf, self.tac, self.corrections, self.thr = rf, tac, corrections, thr
        self.fire_circ = self.fire_ext = self.tot = 0

    def _base(self, o):
        x = [[o.ata_deg, o.aa_deg, _hca(o), o.distance_ft, o.closure_kts,
              _es_diff(o), o.ego_r_dps, o.enm_r_dps]]
        return Tactic[self.tac[int(self.rf.predict(x)[0].argmax())]]

    def select(self, p1, p2) -> Tactic:
        o = compute_obs(p1, p2); self.tot += 1
        if o.ego_alt_ft < SAFE:
            return Tactic.CLIMB
        base_t = self._base(o)
        if not self.corrections:
            return base_t
        # ── 관측-차 상황 게이트 (절대값 0) ──
        hca, ata, clos = _hca(o), o.ata_deg, o.closure_kts
        # ★ loop N+1 fix: rate 게이트는 HCA(교차)만 — ata 요구 제거(각 잡혀도 보정 유지→gun 종결 도달).
        #   HCA가 base-승리(저HCA 정렬추격) vs rate fight(고HCA 교차) 구분 → 부분집합 보존.
        w_circ = _sig((hca - 90.0)/30.0)                               # 2-circle rate (c3)
        w_ext  = _sig((-clos - 25.0)/30.0) * _sig((ata - 30.0)/20.0)    # extend (c2/c4)
        # ── 무승부 상황 dominant 시 보정, 아니면 base 보존 ──
        # ★ loop N+1: rate 보정 단계화 — 각 미정렬(ata↑)=LEAD_TURN(cutoff로 거리·각 닫기),
        #   각 잡힘(ata↓)=GUN_TRACK(정밀 lead로 ata<12° 종결). BFM 정석(cutoff→gun).
        # ★ loop N+3: closure suppressor 가설 실패(역효과·draw전환 상실) → 제거, N+2 복원.
        #   D3·ace 회귀의 surgical fix는 *recent-WEZ* 판별자 필요(미래 루프). 현재 N+2가 최선(15/7/2).
        if w_circ > self.thr and w_circ >= w_ext:
            self.fire_circ += 1
            return Tactic.GUN_TRACK if o.ata_deg < 30.0 else Tactic.LEAD_TURN
        if w_ext > self.thr:
            self.fire_ext += 1
            return Tactic.GUN_TRACK if o.ata_deg < 30.0 else Tactic.LEAD_TURN
        return base_t   # ★ base-승리 상황 = base 그대로 (부분집합)


def main(dur=220.0, controller="indi"):
    rf, tac = _train(DS_DA)
    gs = GainScheduledLQR([5000, 15000, 25000], [250, 350, 450]).build()
    cfg = AutopilotConfig(KP_PSI=0.25); cfg.MAX_PSI_RATE = math.radians(20.0)
    os.makedirs(RBASE, exist_ok=True)
    print(f"=== E27 ADAPTIVE=base⊇subset [controller={controller}] {dur:.0f}s ===")
    print(f"{'opp':<16}{'mode':<10}{'결과':<6}{'dmg':>5}{'HP us:opp':>11}{'maxD(m)':>9}{'보정%':>8}")
    for opp_name in OPPS:
        for mode in ["base", "ADAPTIVE"]:
            p1, p2 = spawn_adt_neutral()
            pol = AdaptivePolicy(rf, tac, corrections=(mode == "ADAPTIVE"))
            m = Match(p1, p2, gs, cfg1=cfg, cfg2=AutopilotConfig(KP_PSI=0.10),
                      control_hz=20, bt_hz=10, log_hz=60,
                      controller1=controller, controller2="lqr")
            res = m.run(tactic_fn1=lambda o: pol.select(p1, p2), tactic_fn2=_opp(opp_name), duration_s=dur)
            mk = "격추" if res.health2 <= 0 else ("패" if res.health1 < res.health2
                 else ("판정" if res.health1 > res.health2 else "무"))
            rd = next_run_dir(RBASE, prefix=f"{opp_name}__{mode}")
            acmi = os.path.join(rd, "match.acmi"); csvp = os.path.join(rd, "match.csv")
            write_acmi_plot(res.log, acmi, title=f"{opp_name}_{mode}"); write_csv(res.log, csvp)
            try: analyze_match_files(acmi, meta_path=csvp, out_dir=rd, title=f"{opp_name}_{mode}", make_plot=False)
            except Exception: pass
            maxd, _, _ = _metrics(csvp)
            fpct = f"{100*(pol.fire_circ+pol.fire_ext)/max(1,pol.tot):.0f}%" if mode == "ADAPTIVE" else "-"
            print(f"{opp_name:<16}{mode:<10}{mk:<6}{res.damage_dealt1:>5.0f}"
                  f"{res.health1:>5.0f}:{res.health2:<5.0f}{maxd:>9.0f}{fpct:>8}", flush=True)
        print(flush=True)
    print(f"replay: {os.path.relpath(RBASE)}", flush=True)


if __name__ == "__main__":
    a = sys.argv[1:]
    main(float(a[0]) if a else 220.0, a[1] if len(a) > 1 else "indi")
