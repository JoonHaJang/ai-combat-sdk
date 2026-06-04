"""트리 정책 배포 — offline_solver 가 학습한 DecisionTree 로 가벼운 dispatch.

★ 온라인 rollout 없음 (예측 불필요). classify(feature) → tactic, 매 tick μs.
  사용자 비전: 오프라인 solver 로 도출 → 가벼운 정책 배포.
"""
from __future__ import annotations
import sys, os, math, pickle
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "control"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "engine"))

import numpy as np
from obs import compute_obs
from tactic import Tactic
from real_rollout import _es_diff

_PKL = os.path.join(os.path.dirname(__file__), "policy_value.pkl")


def _hca(o):
    return abs(((o.ego_psi_deg - o.enm_psi_deg) + 180.0) % 360.0 - 180.0)


class TreePolicy:
    """학습된 value 회귀 정책 — feature→tactic별 점수 예측 → argmax (Safety 우선)."""
    def __init__(self, safe_deck_ft=2500.0):
        with open(_PKL, "rb") as f:
            d = pickle.load(f)
        self.reg = d["reg"]; self.feats = d["feats"]; self.tactics = d["tactics"]
        self.safe_deck_ft = safe_deck_ft
        self._engaged = False        # ★ head-on ADAPTIVE commit (spawn 기반 상황 latch)
        self._tick = 0

    def select(self, p1, p2) -> Tactic:
        o = compute_obs(p1, p2)
        if o.ego_alt_ft < self.safe_deck_ft:
            return Tactic.CLIMB
        # ★ 상황 독립 디스패치 (사용자 지침: 상황별 복합·독립 접근):
        #   spawn 이 정면(head-on)인 매치만 ADAPTIVE τ-블렌딩(v11) commit. 그 외는 RF 정책.
        #   ★ spawn 구분: head-on=t0부터 ata~0·aa~180 / neutral=ata~90 / off=aa낮음 / def=ata높음.
        #     첫 5s(spawn 반영 구간)에 head-on 감지 → 그 매치 latch (연속 commit=4/4, 스위칭=1/4).
        #     중반 transient merge 는 latch 안 함 → neutral 추격 무회귀.
        self._tick += 1
        if (self._tick < 50 and o.ata_deg < 40.0 and o.aa_deg > 130.0
                and o.distance_ft < 9000.0):
            self._engaged = True
        if self._engaged:
            return Tactic.ADAPTIVE
        # ★ evasive-extend 디스패치 (상황 독립): 적을 겨누는데 멀고 안 닫힘(extend) →
        #   VERTICAL_PURSUIT (적 고도 추종, zoom 따라붙음). 계측: 수평 pursuit 는 수직으로 놓침.
        #   sim/agg(다가옴, closure>0)은 미발동 → 무회귀. defensive(ata 높음)도 미발동.
        if o.distance_ft > 4500.0 and o.ata_deg < 50.0 and o.closure_kts < 30.0:
            return Tactic.VERTICAL_PURSUIT
        # ★ 근접 finish 디스패치 (상황 독립): WEZ 사거리 근처 + 대충 정렬 → GUN_TRACK.
        #   계측: 근접서 사거리엔 들어가나 overshoot 로 ata 안 맞아 WEZ 0(각+거리 동시 실패).
        #   GUN_TRACK = 연속 정밀 lead(적 선회 예측)로 ata<12 락 시도 → WEZ 사거리 유지.
        if o.distance_ft < 2800.0 and o.ata_deg < 45.0:
            return Tactic.GUN_TRACK
        x = [[o.ata_deg, o.aa_deg, _hca(o), o.distance_ft, o.closure_kts,
              _es_diff(o), o.ego_r_dps, o.enm_r_dps]]
        scores = self.reg.predict(x)[0]           # tactic별 예측 점수
        return Tactic[self.tactics[int(scores.argmax())]]


if __name__ == "__main__":
    from lqr import GainScheduledLQR
    from autopilot import AutopilotConfig
    from match import Match
    from scenarios import spawn_adt_neutral, SITUATIONS
    from opponents import OPPONENT_BTS
    from replay import next_run_dir, write_acmi_plot, write_csv
    # ★ 매 경기 표준 분석 (승/패/무 전부 데이터 자산) — report.txt + plot.png
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "tools"))
    from plot_match_3d_nme import analyze_match_files
    gs = GainScheduledLQR([5000, 15000, 25000], [250, 350, 450]).build()
    cfg = AutopilotConfig(KP_PSI=0.25); cfg.MAX_PSI_RATE = math.radians(20.0)
    pol = TreePolicy()
    rbase = os.path.join(os.path.dirname(__file__), "..", "replays")
    print("=== 트리 정책 (오프라인 도출, 온라인 rollout 없음) vs 적 BT ===")
    for spawn_name, spawn_fn in SITUATIONS.items():
        W = 0
        line = f"  [{spawn_name:<13}] "
        for opp_name, opp_fn in OPPONENT_BTS.items():
            p1, p2 = spawn_fn()
            pol = TreePolicy()        # ★ 경기마다 새로 (dwell state 리셋 — 교전 commit 누수 방지)
            m = Match(p1, p2, gs, cfg1=cfg, cfg2=AutopilotConfig(KP_PSI=0.10),
                      control_hz=20, bt_hz=10, log_hz=60)        # ★ replay 저장
            res = m.run(tactic_fn1=lambda o: pol.select(p1, p2), tactic_fn2=opp_fn, duration_s=300.0)
            win = (res.winner == "agent1") or (res.winner == "draw" and res.health1 > res.health2)
            if win: W += 1
            mk = "W" if res.winner == "agent1" else ("L" if res.winner == "agent2" else ("w" if res.health1 > res.health2 else "d"))
            line += f"{opp_name[:3]}:{mk}({res.damage_dealt1:.0f}) "
            # ★ replay 저장 (spawn_opp 별 폴더): acmi + csv + events
            rd = next_run_dir(rbase, prefix=f"pol_{spawn_name}_{opp_name}")
            acmi = os.path.join(rd, "match.acmi"); csvp = os.path.join(rd, "match.csv")
            write_acmi_plot(res.log, acmi, title=f"{spawn_name}_{opp_name}")
            write_csv(res.log, csvp)
            with open(os.path.join(rd, "events.log"), "w", encoding="utf-8") as f:
                for t, k, msg in (res.events or []):
                    f.write(f"[{t:7.2f}s] {k:8s} {msg}\n")
            # ★ 매 경기 표준 분석 (report.txt + plot.png) — 7층 정량 리포트
            try:
                analyze_match_files(acmi, meta_path=csvp, out_dir=rd,
                                    title=f"{spawn_name}_{opp_name}", make_plot=True)
            except Exception as e:
                print(f"    [analyze skip {spawn_name}_{opp_name}] {e}")
        print(line + f" → {W}/4")
    print(f"\nreplay: {os.path.relpath(rbase)}/pol_*  (각 매치 acmi+csv+events+report+plot)")
