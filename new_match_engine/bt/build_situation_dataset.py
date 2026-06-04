"""상황 데이터셋 생성 — 다양 spawn × 적 × full match, 매 tick 물리 feature 로깅.

★ 목적: 손으로 정한 상황(CHASE/CIRCLE/DEFENSIVE)이 데이터에서 자연 클러스터로
  나오는지 + 몇 개가 맞는지 클러스터링으로 검증 (측정 먼저). on-to-on·chased 등 포함.

feature (상황 기술자 — 적 무관 relational/물리):
  ata, aa, hca, dist, closure, es_diff, ego_omega(선회율), opp_omega, alt_gap,
  our_wez_margin, opp_wez_margin, advantage.
출력: results_situation_dataset.csv (+ spawn/opp/tactic/situation/outcome 메타)
"""
from __future__ import annotations
import sys, os, math
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "control"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "engine"))

from lqr import GainScheduledLQR
from autopilot import AutopilotConfig
from match import Match
from scenarios import SITUATIONS          # neutral_beam, offensive, defensive, headon
from obs import compute_obs
from tactic import Tactic, WEZ_ATA_DEG, WEZ_MIN_FT, WEZ_MAX_FT
from real_rollout import RealRollout, _wez_margin, _es_diff
from opponents import OPPONENT_BTS

_G = 32.174; _KT = 1.68781


def _hca(o):
    return abs(((o.ego_psi_deg - o.enm_psi_deg) + 180.0) % 360.0 - 180.0)


def _feat_row(o12, o21):
    """매 tick 상황 기술 feature (적 무관)."""
    return {
        "ata": o12.ata_deg, "aa": o12.aa_deg, "hca": _hca(o12),
        "dist": o12.distance_ft, "closure": o12.closure_kts,
        "es_diff": _es_diff(o12), "alt_gap": o12.alt_gap_ft,
        "ego_omega": o12.ego_r_dps, "opp_omega": o12.enm_r_dps,
        "our_wez": _wez_margin(o12), "opp_wez": _wez_margin(o21),
        "advantage": o12.advantage,
    }


def build(duration_s=120.0, sample_every=10):
    gs = GainScheduledLQR([5000, 15000, 25000], [250, 350, 450]).build()
    cfg = AutopilotConfig(KP_PSI=0.25); cfg.MAX_PSI_RATE = math.radians(20.0)
    rows = []
    for spawn_name, spawn_fn in SITUATIONS.items():
        for opp_name, opp_fn in OPPONENT_BTS.items():
            rr = RealRollout(gs, cfg=cfg, horizon_s=8.0, recompute_every=10)
            p1, p2 = spawn_fn()
            tick = [0]
            def sel(o):
                t = rr.select(p1, p2)
                if tick[0] % sample_every == 0:
                    o12 = compute_obs(p1, p2); o21 = compute_obs(p2, p1)
                    r = _feat_row(o12, o21)
                    r.update(spawn=spawn_name, opp=opp_name,
                             situation=rr.last_situation, tactic=t.name, t=tick[0]*0.1)
                    rows.append(r)
                tick[0] += 1
                return t
            m = Match(p1, p2, gs, cfg1=cfg, cfg2=AutopilotConfig(KP_PSI=0.10),
                      control_hz=20, bt_hz=10, log_hz=0)
            res = m.run(tactic_fn1=sel, tactic_fn2=opp_fn, duration_s=duration_s)
            outcome = "win" if (res.winner == "agent1" or
                                (res.winner == "draw" and res.health1 > res.health2)) else \
                      ("loss" if res.winner == "agent2" else "draw")
            for r in rows:
                if r.get("spawn") == spawn_name and r.get("opp") == opp_name and "outcome" not in r:
                    r["outcome"] = outcome
            print(f"  {spawn_name:<13} vs {opp_name:<11}: {res.winner} dmg={res.damage_dealt1:.0f}")
    # CSV
    out = os.path.join(os.path.dirname(__file__), "..", "results_situation_dataset.csv")
    cols = ["spawn", "opp", "t", "situation", "tactic", "outcome",
            "ata", "aa", "hca", "dist", "closure", "es_diff", "alt_gap",
            "ego_omega", "opp_omega", "our_wez", "opp_wez", "advantage"]
    with open(out, "w", encoding="utf-8") as f:
        f.write(",".join(cols) + "\n")
        for r in rows:
            f.write(",".join(f"{r[c]:.4f}" if isinstance(r.get(c), float) else str(r.get(c, ""))
                             for c in cols) + "\n")
    print(f"\n데이터셋: {os.path.relpath(out)}  ({len(rows)} rows, {len(SITUATIONS)}spawn×{len(OPPONENT_BTS)}opp)")
    return out


if __name__ == "__main__":
    print("=== 상황 데이터셋 생성 (다양 spawn × 적) ===")
    build()
