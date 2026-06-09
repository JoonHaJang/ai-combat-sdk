"""E10 — 단일 BT (8/8 win 목표): dagger 연속정책 + 막힘-nose-chaser fallback.

설계(U.13): 하나의 BT/정책으로 적 정체 모르고 8/8(win). 구조:
  1. [BelowHardDeck] → CLIMB (안전)
  2. [Stuck-NoseChaser 감지] → TWO_CIRCLE latch (선회율 압박, HP/하드덱 승)
       감지 = 누적 t>STUCK_S 인데 WEZ 0회 + 적 nose-on(aa낮음) + 압박(closure↑·근거리)
       (죽일 수 있는 6적은 그 전에 WEZ/격추 → 미발동. nose-chaser만 발동)
  3. else → dagger 연속 가치 argmax (6적 격추 모드)

usage: python exp_e10_unified.py [duration_s] [stuck_s]
"""
from __future__ import annotations
import sys, os, math
import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "control"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "engine"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "tools"))

from lqr import GainScheduledLQR
from autopilot import AutopilotConfig
from match import Match
from scenarios import spawn_adt_neutral
from obs import compute_obs
from tactic import Tactic, WEZ_ATA_DEG, WEZ_MIN_FT, WEZ_MAX_FT
from real_rollout import _es_diff
from exp_e6_winrate import _opps
from exp_e7_champion import _train
from replay import next_run_dir, write_acmi_plot, write_csv
from plot_match_3d_nme import analyze_match_files

DS_DA = os.path.join(os.path.dirname(__file__), "..", "results_research_dagger.npz")
RBASE = os.path.join(os.path.dirname(__file__), "..", "replays", "research_unified")
STUCK_S = 60.0       # 이 시간 지나도 WEZ 0 + 압박이면 nose-chaser fallback


def _hca(o): return abs(((o.ego_psi_deg - o.enm_psi_deg) + 180.0) % 360.0 - 180.0)
def _in_wez(o): return o.ata_deg < WEZ_ATA_DEG and WEZ_MIN_FT <= o.distance_ft <= WEZ_MAX_FT


class UnifiedPolicy:
    """단일 BT: 연속 가치 + 막힘-nose-chaser fallback."""
    def __init__(self, rf, tac, bt_hz=10.0, stuck_s=STUCK_S):
        self.rf, self.tac = rf, tac
        self.t = 0.0; self.dt = 1.0 / bt_hz
        self.wez_ever = False; self.latch = False; self.stuck_s = stuck_s

    def select(self, p1, p2) -> Tactic:
        o = compute_obs(p1, p2); self.t += self.dt
        if o.ego_alt_ft < 2500.0:
            return Tactic.CLIMB
        if _in_wez(o):
            self.wez_ever = True
        # ── 막힘-nose-chaser 감지 (관측 기반, 정체 무관) ──
        if (not self.latch and self.t > self.stuck_s and not self.wez_ever
                and o.closure_kts > 15.0 and o.aa_deg < 70.0 and o.distance_ft < 7000.0):
            self.latch = True
        if self.latch:
            return Tactic.TWO_CIRCLE          # 선회율 압박 commit
        x = [[o.ata_deg, o.aa_deg, _hca(o), o.distance_ft, o.closure_kts,
              _es_diff(o), o.ego_r_dps, o.enm_r_dps]]
        return Tactic[self.tac[int(self.rf.predict(x)[0].argmax())]]


def main(dur=300.0, stuck_s=STUCK_S):
    rf, tac = _train(DS_DA)
    gs = GainScheduledLQR([5000, 15000, 25000], [250, 350, 450]).build()
    cfg = AutopilotConfig(KP_PSI=0.25); cfg.MAX_PSI_RATE = math.radians(20.0)
    opps = _opps(); os.makedirs(RBASE, exist_ok=True)
    print(f"=== E10 단일 BT (dagger + nose-chaser fallback, stuck>{stuck_s:.0f}s) 적 {len(opps)} {dur:.0f}s ===\n")
    wins = real = kills = 0; cells = []
    for opp_name, opp_fn in opps.items():
        p1, p2 = spawn_adt_neutral(); pol = UnifiedPolicy(rf, tac, bt_hz=10.0, stuck_s=stuck_s)
        m = Match(p1, p2, gs, cfg1=cfg, cfg2=AutopilotConfig(KP_PSI=0.10),
                  control_hz=20, bt_hz=10, log_hz=60)
        res = m.run(tactic_fn1=lambda o: pol.select(p1, p2), tactic_fn2=opp_fn, duration_s=dur)
        win = (res.winner == "agent1") or (res.winner == "draw" and res.health1 > res.health2)
        wins += int(win); kills += int(res.health2 <= 0)
        real += int(res.health2 <= 0 or res.damage_dealt1 >= 40)
        mk = "W" if res.winner == "agent1" else ("L" if res.winner == "agent2"
             else ("w" if res.health1 > res.health2 else "d"))
        cells.append(f"{opp_name.split('_')[-1][:4]}:{mk}({res.damage_dealt1:.0f}/{res.health2:.0f})")
        rd = next_run_dir(RBASE, prefix=f"unified__{opp_name}")
        acmi = os.path.join(rd, "match.acmi"); csvp = os.path.join(rd, "match.csv")
        write_acmi_plot(res.log, acmi, title=f"unified_{opp_name}"); write_csv(res.log, csvp)
        try: analyze_match_files(acmi, meta_path=csvp, out_dir=rd, title=f"unified_{opp_name}", make_plot=True)
        except Exception: pass
        print(f"  {opp_name:<18} {mk} dmg={res.damage_dealt1:.0f} HP {res.health1:.0f}:{res.health2:.0f} "
              f"latch={pol.latch}", flush=True)
    print(f"\n  단일 BT: 판정 {wins}/8, 실력 {real}/8, 격추 {kills}  | {' '.join(cells)}")
    print(f"  (판정승=HP차/하드덱 포함). replay: {os.path.relpath(RBASE)}")


if __name__ == "__main__":
    a = sys.argv[1:]
    main(float(a[0]) if a else 300.0, float(a[1]) if len(a) > 1 else STUCK_S)
