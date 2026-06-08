"""E6 (레드팀 갭2) — 배포 win-rate: 라벨 regret 이 실제 매치 성능으로 이어지나.

E3 는 라벨 regret 만 쟀다. 실제 배포 성능(win-rate, 마진)은 매치로만 안다. 또한 BT 진화 질문
(손-규칙 4개가 실제로 도움되나)을 직접 시험한다.

비교 정책 (같은 clean 데이터로 학습):
  - 연속RF:    feature→RF.predict→argmax (+ 안전 상승만)
  - 하이브리드RF: 연속RF + tree_policy 손-규칙 4개(head-on/evasive/근접/안전)
  - 연속XGB:   feature→XGBoost→argmax (+ 안전 상승만)
대상 적: 대표 8종(강·다양). canonical neutral 200s. replay(.acmi)+report+plot 전부 저장.

usage: python exp_e6_winrate.py [duration_s]
출력: new_match_engine/replays/research_winrate/<policy>__<opp>_*/{acmi,csv,report,plot}
"""
from __future__ import annotations
import sys, os, glob, math
import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "control"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "engine"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "tools"))

from lqr import GainScheduledLQR
from autopilot import AutopilotConfig
from match import Match
from scenarios import spawn_adt_neutral
from opponents import OPPONENT_BTS
from yaml_bt import load_bt
from obs import compute_obs
from tactic import Tactic
from offline_solver import _feat
from real_rollout import _es_diff
from replay import next_run_dir, write_acmi_plot, write_csv
from plot_match_3d_nme import analyze_match_files
from sklearn.ensemble import RandomForestRegressor
import xgboost as xgb

ZOO = os.path.join(os.path.dirname(__file__), "..", "opponents", "zoo")
RBASE = os.path.join(os.path.dirname(__file__), "..", "replays", "research_winrate")
DS = os.path.join(os.path.dirname(__file__), "..", "results_research_dataset.npz")
SAFE = 2500.0


def _hca(o): return abs(((o.ego_psi_deg - o.enm_psi_deg) + 180.0) % 360.0 - 180.0)


class ContPolicy:
    """순수 연속: argmax + 안전 상승만 (손-규칙 없음)."""
    def __init__(self, model, tactics): self.m = model; self.tac = tactics
    def select(self, p1, p2):
        o = compute_obs(p1, p2)
        if o.ego_alt_ft < SAFE: return Tactic.CLIMB
        x = [[o.ata_deg, o.aa_deg, _hca(o), o.distance_ft, o.closure_kts,
              _es_diff(o), o.ego_r_dps, o.enm_r_dps]]
        return Tactic[self.tac[int(np.asarray(self.m.predict(x))[0].argmax())]]


class HybridPolicy:
    """연속 + tree_policy 손-규칙 4개."""
    def __init__(self, model, tactics): self.m = model; self.tac = tactics; self._eng = False; self._t = 0
    def select(self, p1, p2):
        o = compute_obs(p1, p2); self._t += 1
        if o.ego_alt_ft < SAFE: return Tactic.CLIMB
        if self._t < 50 and o.ata_deg < 40 and o.aa_deg > 130 and o.distance_ft < 9000: self._eng = True
        if self._eng: return Tactic.ADAPTIVE
        if o.distance_ft > 4500 and o.ata_deg < 50 and o.closure_kts < 30: return Tactic.VERTICAL_PURSUIT
        if o.distance_ft < 2800 and o.ata_deg < 45: return Tactic.GUN_TRACK
        x = [[o.ata_deg, o.aa_deg, _hca(o), o.distance_ft, o.closure_kts,
              _es_diff(o), o.ego_r_dps, o.enm_r_dps]]
        return Tactic[self.tac[int(np.asarray(self.m.predict(x))[0].argmax())]]


def _opps():
    reps = {}
    want = ["A2_GunTracker", "B1_EnergyFighter", "C1_TwoCircleRate", "D3_Scissors", "E1_AdaptiveAce"]
    for arch in want:
        fs = sorted(glob.glob(os.path.join(ZOO, arch + "_*.yaml")))
        if fs: reps[arch] = load_bt(fs[len(fs)//2])
    for n in ["aggressive", "defensive", "ace"]:
        reps["anchor_" + n] = OPPONENT_BTS[n]
    return reps


def _run(pol_factory, pol_name, opps, gs, cfg, dur):
    W = wins = 0; rows = []
    for opp_name, opp_fn in opps.items():
        p1, p2 = spawn_adt_neutral()
        pol = pol_factory()
        m = Match(p1, p2, gs, cfg1=cfg, cfg2=AutopilotConfig(KP_PSI=0.10),
                  control_hz=20, bt_hz=10, log_hz=60)
        res = m.run(tactic_fn1=lambda o: pol.select(p1, p2), tactic_fn2=opp_fn, duration_s=dur)
        win = (res.winner == "agent1") or (res.winner == "draw" and res.health1 > res.health2)
        wins += int(win)
        mk = "W" if res.winner == "agent1" else ("L" if res.winner == "agent2" else ("w" if res.health1 > res.health2 else ("d" if res.health1 == res.health2 else "l")))
        rd = next_run_dir(RBASE, prefix=f"{pol_name}__{opp_name}")
        acmi = os.path.join(rd, "match.acmi"); csvp = os.path.join(rd, "match.csv")
        write_acmi_plot(res.log, acmi, title=f"{pol_name}_{opp_name}"); write_csv(res.log, csvp)
        try: analyze_match_files(acmi, meta_path=csvp, out_dir=rd, title=f"{pol_name}_{opp_name}", make_plot=True)
        except Exception as e: print(f"   [plot skip] {repr(e)[:50]}")
        rows.append((opp_name, mk, res.damage_dealt1, res.health1, res.health2))
    return wins, rows


def main(dur=200.0):
    d = np.load(DS, allow_pickle=True)
    X, Y, tac = d["X"], d["Y"], list(d["tactics"])
    rf = RandomForestRegressor(n_estimators=150, max_depth=10, min_samples_leaf=6, n_jobs=-1, random_state=0).fit(X, Y)
    xg = xgb.XGBRegressor(n_estimators=300, max_depth=5, learning_rate=0.05, subsample=0.8,
                          colsample_bytree=0.8, n_jobs=-1, random_state=0,
                          multi_strategy="multi_output_tree").fit(X, Y)
    gs = GainScheduledLQR([5000, 15000, 25000], [250, 350, 450]).build()
    cfg = AutopilotConfig(KP_PSI=0.25); cfg.MAX_PSI_RATE = math.radians(20.0)
    opps = _opps(); os.makedirs(RBASE, exist_ok=True)
    print(f"=== E6 배포 win-rate (적 {len(opps)}종, neutral {dur:.0f}s, replay 저장) ===\n")
    policies = [
        ("contRF",   lambda: ContPolicy(rf, tac)),
        ("hybridRF", lambda: HybridPolicy(rf, tac)),
        ("contXGB",  lambda: ContPolicy(xg, tac)),
    ]
    print(f"  {'정책':<10}{'판정승':>7}{'실력승':>7}{'격추':>6}  매치별(적:판정(데미지))")
    for pname, fac in policies:
        wins, rows = _run(fac, pname, opps, gs, cfg, dur)
        kills = sum(1 for o, mk, dm, h1, h2 in rows if h2 <= 0)
        real = sum(1 for o, mk, dm, h1, h2 in rows if h2 <= 0 or dm >= 40)  # 격추+결정타
        line = " ".join(f"{o.split('_')[-1][:4]}:{mk}({dm:.0f})" for o, mk, dm, h1, h2 in rows)
        print(f"  {pname:<10}{wins:>5}/8{real:>5}/8{kills:>6}  {line}", flush=True)
    print(f"\n  실력승 = 격추(적 HP=0) + 결정타(데미지≥40). 판정승은 하드덱 자멸·HP 타이브레이크 포함(부풀림).")
    print(f"  replay: {os.path.relpath(RBASE)}/<policy>__<opp>_*  (acmi+csv+report+plot, HIT·하드덱 이벤트 포함)")


if __name__ == "__main__":
    main(float(sys.argv[1]) if len(sys.argv) > 1 else 200.0)
