"""통합 매치 러너 — 원본 run_match.py 와 동일 조건(5분, ADT neutral spawn).

experiment.py / rollout_selector.py 공용. 매치 → event log 출력 → replay 저장.

usage (코드):
    from run_nme import run_match
    res = run_match(tactic_fn1, tactic_fn2, label="myexp", duration_s=300.0)
"""
from __future__ import annotations
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "control"))

from lqr import GainScheduledLQR
from autopilot import AutopilotConfig
from tactic import MATCH_DURATION_S
from match import Match
from scenarios import spawn_adt_neutral
from replay import next_run_dir, write_acmi_plot, write_csv

_GS = None
def _gs():
    global _GS
    if _GS is None:
        _GS = GainScheduledLQR([5000, 15000, 25000], [250, 350, 450]).build()
    return _GS

# event 종류별 표시 아이콘
_ICON = {"TACTIC1": "🔵", "TACTIC2": "🔴", "WEZ1": "🎯", "WEZ2": "⚠️ ",
         "HP1": "💥", "HP2": "💢", "HDECK1": "⬇️ ", "HDECK2": "⬇️ ", "RESULT": "🏁"}


def print_events(events, hide_tactic=False):
    """event log 정렬 출력 (원본 run_match.py 스타일 정보 표시)."""
    if not events:
        print("  (event 없음)"); return
    print(f"\n  ── EVENT LOG ({len(events)} events) ──────────────────────")
    for t, kind, msg in events:
        if hide_tactic and kind.startswith("TACTIC"):
            continue
        icon = _ICON.get(kind, "  ")
        print(f"  [{t:6.1f}s] {icon} {msg}")


def run_match(tactic_fn1, tactic_fn2, label="match",
              duration_s: float = MATCH_DURATION_S,
              control_hz=20.0, bt_hz=10.0, log_hz=60.0,
              save_replay=True, show_events=True, hide_tactic=False):
    """원본 동일조건 매치 1회. → MatchResult.

    duration_s 기본 = MATCH_DURATION_S(300s, 5분). spawn = ADT neutral(원본).
    """
    p1, p2 = spawn_adt_neutral()
    m = Match(p1, p2, _gs(),
              cfg1=AutopilotConfig(KP_PSI=0.10), cfg2=AutopilotConfig(KP_PSI=0.10),
              control_hz=control_hz, bt_hz=bt_hz, log_hz=log_hz)
    res = m.run(tactic_fn1=tactic_fn1, tactic_fn2=tactic_fn2, duration_s=duration_s)

    print(f"\n  결과: winner={res.winner}  ({res.condition.value})  t={res.time_s:.1f}s")
    print(f"        H1={res.health1:.0f}  H2={res.health2:.0f}  "
          f"A1피해={res.damage_dealt1:.0f}  A2피해={res.damage_dealt2:.0f}")
    if show_events:
        print_events(res.events, hide_tactic=hide_tactic)

    if save_replay and res.log:
        rd = next_run_dir(os.path.join(os.path.dirname(__file__), "..", "replays"), prefix=label)
        acmi = os.path.join(rd, "match.acmi"); csv = os.path.join(rd, "match.csv")
        write_acmi_plot(res.log, acmi, title=label)
        write_csv(res.log, csv)
        # event log 도 파일로
        with open(os.path.join(rd, "events.log"), "w", encoding="utf-8") as f:
            for t, kind, msg in (res.events or []):
                f.write(f"[{t:7.2f}s] {kind:8s} {msg}\n")
        print(f"\n  replay: {os.path.relpath(rd)}/  (match.acmi, match.csv, events.log)")
        print(f"  plot:   python tools/plot_match_3d_nme.py "
              f"--replay {os.path.relpath(acmi)} --meta {os.path.relpath(csv)}")
    return res
