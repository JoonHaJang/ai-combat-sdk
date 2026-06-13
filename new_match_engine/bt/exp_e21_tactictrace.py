"""E21 (실험 A) — 왜 정책이 머지에서 코너+lead(ADAPTIVE/LEAD_PURSUIT)를 안 고르나.

RF action set 10개에 ADAPTIVE·LEAD_PURSUIT 포함됨(고를 수 있음). 그런데 안 고름.
→ 매 BT-tick RF 가치벡터(10 tactic 점수)를 로깅해, 머지(초반 0~40s)에서 RF가
  무엇을 더 높게 매기는지 확인. 가설: VERTICAL_PURSUIT/TWO_CIRCLE > ADAPTIVE/LEAD = myopic 라벨.

대상: 무승부 A3_LagAngler(닫기 실패 전형) + 격추 anchor_ace 대조.
usage: python exp_e21_tactictrace.py [opp] [duration_s]
"""
from __future__ import annotations
import sys, os, math, warnings
warnings.filterwarnings("ignore")

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
from tactic import Tactic, V_CORNER_KTS
from real_rollout import _es_diff
from exp_e7_champion import _train
from exp_e10_unified import DS_DA
import glob, numpy as np

ZOO = os.path.join(os.path.dirname(__file__), "..", "opponents", "zoo")
SAFE = 2500.0


def _hca(o): return abs(((o.ego_psi_deg - o.enm_psi_deg) + 180.0) % 360.0 - 180.0)


def _opp(name):
    if name.startswith("anchor_"):
        return OPPONENT_BTS[name.split("_", 1)[1]]
    fs = sorted(glob.glob(os.path.join(ZOO, name + "_*.yaml")))
    return load_bt(fs[len(fs) // 2])


class TracePolicy:
    """RF argmax + 안전상승. 매 tick 가치벡터·선택·kinematics 기록."""
    def __init__(self, rf, tac, bt_hz=10.0):
        self.rf, self.tac = rf, tac; self.t = 0.0; self.dt = 1.0 / bt_hz
        self.trace = []   # (t, dist_ft, ata, aa, vc, closure, chosen, value_vec)

    def select(self, p1, p2) -> Tactic:
        o = compute_obs(p1, p2); self.t += self.dt
        if o.ego_alt_ft < SAFE:
            return Tactic.CLIMB
        x = [[o.ata_deg, o.aa_deg, _hca(o), o.distance_ft, o.closure_kts,
              _es_diff(o), o.ego_r_dps, o.enm_r_dps]]
        v = np.asarray(self.rf.predict(x)[0], dtype=float)
        ch = int(v.argmax())
        self.trace.append((self.t, o.distance_ft, o.ata_deg, o.aa_deg,
                           o.ego_vc_kts, o.closure_kts, self.tac[ch], v.copy()))
        return Tactic[self.tac[ch]]


def main(opp_name="A3_LagAngler", dur=120.0):
    rf, tac = _train(DS_DA); tac = list(tac)
    gs = GainScheduledLQR([5000, 15000, 25000], [250, 350, 450]).build()
    cfg = AutopilotConfig(KP_PSI=0.25); cfg.MAX_PSI_RATE = math.radians(20.0)
    p1, p2 = spawn_adt_neutral(); pol = TracePolicy(rf, tac)
    m = Match(p1, p2, gs, cfg1=cfg, cfg2=AutopilotConfig(KP_PSI=0.10),
              control_hz=20, bt_hz=10, log_hz=60)
    res = m.run(tactic_fn1=lambda o: pol.select(p1, p2), tactic_fn2=_opp(opp_name), duration_s=dur)
    print(f"=== E21 tactic-trace vs {opp_name}  outcome HP {res.health1:.0f}:{res.health2:.0f} dmg={res.damage_dealt1:.0f} ===")
    print(f"action set: {tac}")
    iLEAD, iADAPT = tac.index("LEAD_PURSUIT"), tac.index("ADAPTIVE")
    iVERT = tac.index("VERTICAL_PURSUIT"); iTC = tac.index("TWO_CIRCLE")

    # ── 초반 머지 스냅샷 (t≈2,5,10,15,20,25,30,40s) ──
    print(f"\n[머지 스냅샷] 각 시점 RF 가치: chosen=선택 / 괄호=해당 tactic 점수")
    print(f"{'t':>4}{'dist':>7}{'ata':>5}{'aa':>5}{'vc':>5}{'clos':>6}  {'chosen':<16}{'LEAD':>7}{'ADAPT':>7}{'VERT':>7}{'TWOC':>7}  top3")
    want = [2, 5, 10, 15, 20, 25, 30, 40]; wi = 0
    for (t, dist, ata, aa, vc, clos, ch, v) in pol.trace:
        if wi < len(want) and t >= want[wi]:
            wi += 1
            order = np.argsort(-v)[:3]
            top3 = ", ".join(f"{tac[j]}={v[j]:.0f}" for j in order)
            print(f"{t:4.0f}{dist:7.0f}{ata:5.0f}{aa:5.0f}{vc:5.0f}{clos:6.0f}  {ch:<16}"
                  f"{v[iLEAD]:7.1f}{v[iADAPT]:7.1f}{v[iVERT]:7.1f}{v[iTC]:7.1f}  {top3}")

    # ── 전체 선택 빈도 + 머지(첫40s) 평균가치 ──
    from collections import Counter
    cnt = Counter(tr[6] for tr in pol.trace)
    print(f"\n[선택 빈도] {dict(cnt.most_common())}")
    merge = [tr[7] for tr in pol.trace if tr[0] <= 40.0]
    if merge:
        mv = np.mean(merge, axis=0)
        rank = np.argsort(-mv)
        print(f"[머지 0~40s 평균 RF 가치 순위]")
        for r in rank:
            print(f"    {tac[r]:<16}{mv[r]:7.2f}")


if __name__ == "__main__":
    a = sys.argv[1:]
    main(a[0] if a else "A3_LagAngler", float(a[1]) if len(a) > 1 else 120.0)
