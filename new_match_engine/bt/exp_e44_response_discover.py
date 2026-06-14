"""E44 — *반응 발견*: A3·D2를 격추하는 *기동이 존재하는가* 전수 탐색 (탐지 무시, forced).

사용자: 교착 단정 금지 → response 소진. E38은 close→align만. 여기선 ①전 단일 tactic ②cutoff 2-phase
(LEAD_TURN/TIGHT_TURN/SCISSORS = 원을 *가로질러 가로채기*, 꼬리추격 아님). D2=2nm 원 → inside-cut 정석.
이기는 기동 찾으면 → 그게 response. replay 생략(스캔), 확정시 재현. usage: python exp_e44_response_discover.py [opp] [dur]
"""
from __future__ import annotations
import sys, os, math, warnings
warnings.filterwarnings("ignore")
sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "control"))

from exp_e22_chaseforce import _opp
from exp_e38_twophase_discover import make_policy
from lqr import GainScheduledLQR
from autopilot import AutopilotConfig
from match import Match
from scenarios import spawn_adt_neutral
from obs import compute_obs
from tactic import Tactic
from replay import next_run_dir, write_acmi_plot, write_csv
from plot_match_3d_nme import analyze_match_files

T = Tactic
SINGLES = [T.LEAD_TURN, T.TIGHT_TURN, T.SCISSORS, T.LEAD_PURSUIT, T.PURE_PURSUIT,
           T.GUN_TRACK, T.LAG_DISPLACEMENT_ROLL, T.HIGH_YOYO, T.LOW_YOYO, T.EXTENSION]
# cutoff/inside-cut 2-phase (close→align): 원을 가로질러 잡기
TWOPHASE = [("TIGHT→GUN", T.TIGHT_TURN, T.GUN_TRACK),
            ("LEADTURN→GUN", T.LEAD_TURN, T.GUN_TRACK),
            ("TIGHT→LEAD", T.TIGHT_TURN, T.LEAD_PURSUIT),
            ("SCISSORS→GUN", T.SCISSORS, T.GUN_TRACK),
            ("EXT→LEADTURN", T.EXTENSION, T.LEAD_TURN),
            ("LEADTURN→TIGHT", T.LEAD_TURN, T.TIGHT_TURN)]
RBASE = os.path.join(os.path.dirname(__file__), "..", "replays", "research_resp")


def _run(build, opp_name, gs, cfg, dur):
    p1, p2 = spawn_adt_neutral()
    fn = build(p1, p2)                         # 정책 매치당 1회 생성(상태 보존)
    m = Match(p1, p2, gs, cfg1=cfg, cfg2=AutopilotConfig(KP_PSI=0.10),
              control_hz=20, bt_hz=10, log_hz=60, controller1="indi", controller2="lqr")
    res = m.run(tactic_fn1=lambda o: fn(o),
                tactic_fn2=lambda o: _opp(opp_name)(compute_obs(p2, p1)), duration_s=dur)
    mk = "격추" if res.health2 <= 0 else ("판정" if res.health1 > res.health2 else "무")
    return mk, res.damage_dealt1, res.health2


def main(opp_name="D2_LastDitch", dur=200.0):
    gs = GainScheduledLQR([5000, 15000, 25000], [250, 350, 450]).build()
    cfg = AutopilotConfig(KP_PSI=0.25); cfg.MAX_PSI_RATE = math.radians(20.0)
    print(f"=== E44 반응 발견 vs {opp_name} {dur:.0f}s (격추 찾기) ===", flush=True)
    best = ("?", -1)
    print("[단일 tactic 강제]", flush=True)
    for t in SINGLES:
        build = lambda p1, p2, t=t: (lambda o: (Tactic.CLIMB if compute_obs(p1, p2).ego_alt_ft < 2500 else t))
        mk, d, h2 = _run(build, opp_name, gs, cfg, dur)
        print(f"  {t.name:<22}{mk:<6} dmg={d:.0f} oppHP={h2:.0f}", flush=True)
        if d > best[1]: best = (t.name, d)
    print("[cutoff 2-phase]", flush=True)
    for label, ct, at in TWOPHASE:
        build = lambda p1, p2, ct=ct, at=at: make_policy(p1, p2, ct, at)
        mk, d, h2 = _run(build, opp_name, gs, cfg, dur)
        print(f"  {label:<22}{mk:<6} dmg={d:.0f} oppHP={h2:.0f}", flush=True)
        if d > best[1]: best = (label, d)
    print(f"\n★ 최선: {best[0]}  dmg={best[1]:.0f}", flush=True)


if __name__ == "__main__":
    a = sys.argv[1:]
    main(a[0] if a else "D2_LastDitch", float(a[1]) if len(a) > 1 else 200.0)
