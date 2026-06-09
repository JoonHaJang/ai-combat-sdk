"""E12 — nose-chaser 에 데미지 극대화 거동 탐색 (t=0부터 적용, 적 2종).

champion 단독 dmg9 > 35s핸드오프 dmg1 → 일찍·올바른 거동이면 더 때린다. nose-chaser 는 우리를
추격하므로, 방어 reversal(break→overshoot 유도→gun)·lead·one-circle snapshot 등을 직접 비교.
오라클(이것이 nose-chaser임을 안다고 가정)로 t=0부터 각 거동 적용, 데미지 측정.

usage: python exp_e12_nosechaser.py
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
from tactic import Tactic
from real_rollout import _es_diff
from opponents import OPPONENT_BTS
from tree_policy import TreePolicy
from yaml_bt import load_bt
from replay import next_run_dir, write_acmi_plot, write_csv
import glob

RBASE = os.path.join(os.path.dirname(__file__), "..", "replays", "research_nosechaser")


class Mode:
    """t=0부터 한 거동 전략. champion 은 TreePolicy, 나머지는 obs→tactic 함수."""
    def __init__(self, mode):
        self.mode = mode; self.champ = TreePolicy() if mode == "champion" else None
        self.phase = 0

    def select(self, p1, p2):
        o = compute_obs(p1, p2)
        if o.ego_alt_ft < 2500.0: return Tactic.CLIMB
        m = self.mode
        if m == "champion":   return self.champ.select(p1, p2)
        if m == "one_circle": return Tactic.ONE_CIRCLE
        if m == "lead":       return Tactic.LEAD_PURSUIT
        if m == "gun":        return Tactic.GUN_TRACK
        if m == "scissors":   return Tactic.SCISSORS
        if m == "break_reverse":
            # 적이 우리 뒤 위협(aa 높음) → BREAK 으로 overshoot 유도. overshoot(aa 낮아짐·우리 정렬)
            #   되면 GUN_TRACK 으로 사격. (pure-pursuit 추격자 카운터)
            if o.distance_ft < 2800 and o.ata_deg < 35: return Tactic.GUN_TRACK
            if o.aa_deg > 100.0:                        return Tactic.BREAK_TURN   # 적이 뒤 → 브레이크
            return Tactic.LEAD_PURSUIT                  # overshoot 후 → 선도 추격
        if m == "rate_then_gun":
            # 선회율로 적 에너지 소진 + 에너지·각 우위 시 GUN_TRACK
            if o.distance_ft < 3000 and o.ata_deg < 30: return Tactic.GUN_TRACK
            if _es_diff(o) > 1000 and o.ata_deg < 50:   return Tactic.GUN_TRACK
            return Tactic.TWO_CIRCLE
        return Tactic.TWO_CIRCLE


def main():
    gs = GainScheduledLQR([5000, 15000, 25000], [250, 350, 450]).build()
    cfg = AutopilotConfig(KP_PSI=0.25); cfg.MAX_PSI_RATE = math.radians(20.0)
    gt = sorted(glob.glob(os.path.join(os.path.dirname(__file__), "..", "opponents", "zoo", "A2_GunTracker_*.yaml")))
    opps = {"GunTracker": load_bt(gt[len(gt)//2]), "aggressive": OPPONENT_BTS["aggressive"]}
    os.makedirs(RBASE, exist_ok=True)
    print("=== E12 nose-chaser 데미지 극대화 (t=0 적용, 300s) ===")
    print(f"  {'mode':<16}{'GunTracker':>24}{'aggressive':>24}")
    for mode in ["champion", "one_circle", "lead", "gun", "scissors", "break_reverse", "rate_then_gun"]:
        cells = []
        for on, ofn in opps.items():
            p1, p2 = spawn_adt_neutral(); pol = Mode(mode)
            m = Match(p1, p2, gs, cfg1=cfg, cfg2=AutopilotConfig(KP_PSI=0.10),
                      control_hz=20, bt_hz=10, log_hz=60)
            res = m.run(tactic_fn1=lambda o: pol.select(p1, p2), tactic_fn2=ofn, duration_s=300.0)
            mk = "W" if res.winner == "agent1" else ("L" if res.winner == "agent2" else ("w" if res.health1 > res.health2 else "d"))
            cells.append(f"{mk} dmg{res.damage_dealt1:.0f} HP{res.health1:.0f}:{res.health2:.0f}")
            rd = next_run_dir(RBASE, prefix=f"{mode}__{on}")
            write_acmi_plot(res.log, os.path.join(rd, "match.acmi"), title=f"{mode}_{on}")
            write_csv(res.log, os.path.join(rd, "match.csv"))
        print(f"  {mode:<16}{cells[0]:>24}{cells[1]:>24}", flush=True)
    print(f"\n  replay: {os.path.relpath(RBASE)}")


if __name__ == "__main__":
    main()
