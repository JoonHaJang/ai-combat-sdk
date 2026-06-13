"""E24 (#2a) — lead-turn 머지 dispatch를 정책에 넣고 *전체 매치 승패*로 평가.

검증(exp_relabel): per-state 라벨은 on-policy 편향으로 LEAD_TURN을 못 배움. LEAD_TURN 가치는
policy-level(머지서 쓰고 전환) → 재학습 말고 dispatch로 넣고 full-match로 평가.
정책: 머지조건(closing·mid-range·미정렬) → LEAD_TURN, else RF argmax(+안전상승). 재학습 0 = 8/8 위험 0.
비교: base(RF) vs merge-dispatch — 무승부(A3/D2) 닫히나 + 격추 회귀 없나.
usage: python exp_e24_mergedispatch.py [duration_s]
"""
from __future__ import annotations
import sys, os, math, csv, warnings
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

RBASE = os.path.join(os.path.dirname(__file__), "..", "replays", "research_mergedispatch")
SAFE = 2500.0


def _hca(o): return abs(((o.ego_psi_deg - o.enm_psi_deg) + 180.0) % 360.0 - 180.0)


class Pol:
    """mode='base' → 순수 RF argmax. mode='merge' → 전환국면이면 LEAD_TURN, else RF."""
    def __init__(self, rf, tac, mode="base"):
        self.rf, self.tac, self.mode = rf, tac, mode
        self.fire = 0; self.tot = 0

    def _merge(self, o):
        # ★ 전환국면 = 미정렬(nose-on 아님) + 교전사거리(WEZ 밖~원). closure 부호 무관.
        #   (이전 버그: closure>60 요구 → 머지초반은 음수라 한번도 발동 안 함.)
        #   정렬(ata<35)되면 RF(pursuit/gun)가 받아 격추 마무리.
        return (o.ata_deg > 35.0 and 2500.0 < o.distance_ft < 12000.0)

    def select(self, p1, p2) -> Tactic:
        o = compute_obs(p1, p2); self.tot += 1
        if o.ego_alt_ft < SAFE:
            return Tactic.CLIMB
        if self.mode == "merge" and self._merge(o):
            self.fire += 1
            return Tactic.LEAD_TURN
        x = [[o.ata_deg, o.aa_deg, _hca(o), o.distance_ft, o.closure_kts,
              _es_diff(o), o.ego_r_dps, o.enm_r_dps]]
        return Tactic[self.tac[int(self.rf.predict(x)[0].argmax())]]


def main(dur=220.0, controller="lqr"):
    rf, tac = _train(DS_DA)
    gs = GainScheduledLQR([5000, 15000, 25000], [250, 350, 450]).build()
    cfg = AutopilotConfig(KP_PSI=0.25); cfg.MAX_PSI_RATE = math.radians(20.0)
    os.makedirs(RBASE, exist_ok=True)
    print(f"[controller={controller}]")
    # 무승부(검증대상) + 격추(회귀검증) + nose-chaser(회귀검증) 혼합
    opps = ["A3_LagAngler", "D2_LastDitch",          # 무승부 → 닫히나
            "anchor_ace", "B2_Extender", "C2_OneCircleRad",  # 격추 → 회귀 없나
            "anchor_aggressive", "A1_PurePursuer"]   # nose-chaser/판정 → 회귀 없나
    print(f"=== E24 머지 dispatch(LEAD_TURN) vs base {dur:.0f}s ===")
    print(f"{'opp':<16}{'mode':<8}{'결과':<6}{'dmg':>5}{'HP us:opp':>11}{'maxD(m)':>9}{'코너%':>7}")
    wins = {"base": [0, 0], "merge": [0, 0]}   # [win, kill]
    for opp_name in opps:
        for mode in ["base", "merge"]:
            p1, p2 = spawn_adt_neutral(); pol = Pol(rf, tac, mode=mode)
            m = Match(p1, p2, gs, cfg1=cfg, cfg2=AutopilotConfig(KP_PSI=0.10),
                      control_hz=20, bt_hz=10, log_hz=60,
                      controller1=controller, controller2="lqr")
            res = m.run(tactic_fn1=lambda o: pol.select(p1, p2), tactic_fn2=_opp(opp_name), duration_s=dur)
            win = (res.winner == "agent1") or (res.winner == "draw" and res.health1 > res.health2)
            kill = res.health2 <= 0
            wins[mode][0] += int(win); wins[mode][1] += int(kill)
            mk = "격추" if kill else ("패" if res.health1 < res.health2
                 else ("판정" if res.health1 > res.health2 else "무"))
            rd = next_run_dir(RBASE, prefix=f"{opp_name}__{mode}")
            acmi = os.path.join(rd, "match.acmi"); csvp = os.path.join(rd, "match.csv")
            write_acmi_plot(res.log, acmi, title=f"{opp_name}_{mode}"); write_csv(res.log, csvp)
            try: analyze_match_files(acmi, meta_path=csvp, out_dir=rd, title=f"{opp_name}_{mode}", make_plot=False)
            except Exception: pass
            maxd, meand, corner = _metrics(csvp)
            fire = f"{100*pol.fire/max(1,pol.tot):.0f}%" if mode == "merge" else "-"
            print(f"{opp_name:<16}{mode:<8}{mk:<6}{res.damage_dealt1:>5.0f}"
                  f"{res.health1:>5.0f}:{res.health2:<5.0f}{maxd:>9.0f}{corner*100:>6.0f}%{fire:>7}", flush=True)
        print(flush=True)
    n = len(opps)
    print(f"합계 (n={n}):  base 승{wins['base'][0]} 격추{wins['base'][1]}  |  "
          f"merge 승{wins['merge'][0]} 격추{wins['merge'][1]}", flush=True)
    print(f"replay: {os.path.relpath(RBASE)}", flush=True)


if __name__ == "__main__":
    a = sys.argv[1:]
    main(float(a[0]) if a else 220.0, a[1] if len(a) > 1 else "lqr")
