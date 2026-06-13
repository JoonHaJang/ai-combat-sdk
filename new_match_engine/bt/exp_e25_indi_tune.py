"""E25 — INDI 게인 튜닝 sweep. 기본 INDI가 LQR 격추를 잃음(WEZ sustained 추종 부족).

핵심 게인(뱅크 K_PHI/K_P, 피치 K_THETA/K_Q)을 올려 자세 수렴↑ → 격추 회복되나.
대상: 격추적 ace/B2/C2(회복 목표) + 무승부 A3. base RF 정책, controller=indi.
판정: dmg=100=격추. config별 dmg 합이 LQR(3격추=300) 회복하면 INDI 공정 튜닝됨.
usage: python exp_e25_indi_tune.py [duration_s]
"""
from __future__ import annotations
import sys, os, math, warnings
warnings.filterwarnings("ignore")
sys.path.insert(0, os.path.dirname(__file__))

from exp_e24_mergedispatch import Pol, _opp
from lqr import GainScheduledLQR
from autopilot import AutopilotConfig
from match import Match
from scenarios import spawn_adt_neutral
from exp_e7_champion import _train
from exp_e10_unified import DS_DA

# 게인 config (env override). C0=기본(현재값).
CONFIGS = {
    "C0_base":     {},
    "C1_bank":     {"INDI_K_PHI": "5", "INDI_K_P": "12"},
    "C2_bank+":    {"INDI_K_PHI": "7", "INDI_K_P": "14"},
    "C3_all":      {"INDI_K_PHI": "5", "INDI_K_P": "12", "INDI_K_THETA": "3", "INDI_K_Q": "9"},
}
OPPS = ["anchor_ace", "B2_Extender", "C2_OneCircleRad", "A3_LagAngler"]  # 3격추 + 1무승부


def main(dur=200.0):
    rf, tac = _train(DS_DA)
    gs = GainScheduledLQR([5000, 15000, 25000], [250, 350, 450]).build()
    cfg = AutopilotConfig(KP_PSI=0.25); cfg.MAX_PSI_RATE = math.radians(20.0)
    print(f"=== E25 INDI 게인 튜닝 (base 정책, controller=indi) {dur:.0f}s ===")
    print("기준: LQR base = ace격추 B2격추 C2격추 A3무 (dmg 100/100/100/0)\n")
    print(f"{'config':<12}" + "".join(f"{o.split('_')[-1][:5]:>8}" for o in OPPS) + f"{'dmg합':>8}{'격추':>5}")
    for cname, env in CONFIGS.items():
        for k in ("INDI_K_PHI", "INDI_K_P", "INDI_K_THETA", "INDI_K_Q"):
            os.environ.pop(k, None)
        for k, v in env.items():
            os.environ[k] = v
        cells = []; dsum = 0; kills = 0
        for opp_name in OPPS:
            p1, p2 = spawn_adt_neutral(); pol = Pol(rf, tac, mode="base")
            m = Match(p1, p2, gs, cfg1=cfg, cfg2=AutopilotConfig(KP_PSI=0.10),
                      control_hz=20, bt_hz=10, log_hz=60,
                      controller1="indi", controller2="lqr")
            res = m.run(tactic_fn1=lambda o: pol.select(p1, p2), tactic_fn2=_opp(opp_name), duration_s=dur)
            d = res.damage_dealt1; dsum += d; kills += int(res.health2 <= 0)
            mk = "K" if res.health2 <= 0 else ("." if d < 5 else "~")
            cells.append(f"{d:.0f}{mk}")
        print(f"{cname:<12}" + "".join(f"{c:>8}" for c in cells) + f"{dsum:>8.0f}{kills:>5}", flush=True)
    print("\n(K=격추 ~=부분WEZ .=미교전. dmg합 300·격추3 = LQR 회복)")


if __name__ == "__main__":
    a = sys.argv[1:]
    main(float(a[0]) if a else 200.0)
