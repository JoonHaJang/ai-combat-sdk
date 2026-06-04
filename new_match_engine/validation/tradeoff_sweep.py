"""게인 trade-off 곡선 — LQR vs INDI 를 *공정하게* 공격성 sweep 해 Pareto 비교.

목적(사용자 ①): "양쪽 완전 최적화 후 trade-off 곡선" — 추종(정착·θss) ↔ 제어활동(u_rms·qmax)
  ↔ 강건성(모델오차 ½ 하 θss) 의 3-way 균형을 *정량화*. "INDI 가 공짜로 우월"인지, 아니면
  "같은 추종·활동 대역에서 강건성만 더 좋은지"를 데이터로 가른다.

설계:
  복합 고기동 roll60°+pull20° (내측이 가장 갈리는 시나리오) 고정.
  · LQR  공격성 = rr_scale↓ (입력페널티↓ → K_r↑ → 빠름·활동↑)
  · INDI 공격성 = K_NU↑ (+KI 비례) (PI 대역폭↑ → 빠름·활동↑)
  각 설정마다 측정:
    정상  : settle(정착s), th_ss(정상상태 θ오차°), u_rms(제어활동), q_max
    모델오차½: th_ss_ceff (강건성 = 모델 틀려도 추종 유지하는가)
  → 같은 (정상 settle / u_rms) 대역에서 두 제어기의 th_ss_ceff(강건성) 비교 = Pareto front.

실행: python tradeoff_sweep.py
"""
from __future__ import annotations
import sys, os, math
sys.path.insert(0, os.path.dirname(__file__))
import numpy as np
from aerobench_testbed import trim_level, linearize, run

THC = math.radians(20.0)
PHC = math.radians(60.0)          # 복합 고기동 (roll60 + pull20)

# 공격성 격자 — 빠를수록(낮은 rr / 높은 K_NU) 활동↑
LQR_SWEEP  = [4.0, 2.0, 1.0, 0.5, 0.25, 0.1]            # rr_scale (↓ = 공격적)
INDI_SWEEP = [8.0, 14.0, 20.0, 28.0, 40.0, 60.0]       # K_NU (↑ = 공격적)


def measure(eng, gains):
    nom  = run(eng, A, B, x0, u0, THC, PHC, ceff=1.0, gains=gains)
    ceff = run(eng, A, B, x0, u0, THC, PHC, ceff=0.5, gains=gains)
    return dict(settle=nom["settle"], th_ss=nom["th_ss"], u_rms=nom["u_rms"],
                q_max=nom["q_max"], p_max=nom["p_max"],
                th_ss_ceff=ceff["th_ss"], settle_ceff=ceff["settle"],
                loc=nom["loc"] or ceff["loc"])


if __name__ == "__main__":
    print("=" * 100)
    print("  게인 trade-off — LQR vs INDI 공정 공격성 sweep (복합 roll60+pull20, TP-1538 plant)")
    print("=" * 100)
    x0, u0 = trim_level(502.0, 15000.0)
    A, B = linearize(x0, u0)

    hdr = "%-5s %-10s | %7s %8s %8s %6s | %10s %9s | %4s"
    print(hdr % ("eng", "공격성", "정착s", "θss(정상)", "u_rms", "qmax",
                 "θss(오차½)", "정착½s", "LOC"))
    print("  (강건성 = θss(오차½): 모델 틀려도 작게 유지하는 쪽이 강건. 활동 = u_rms/qmax)")
    print("-" * 100)

    lqr_rows, indi_rows = [], []
    for rr in LQR_SWEEP:
        m = measure("lqr", {"rr_scale": rr})
        lqr_rows.append((rr, m))
        print(hdr % ("A", "rr=%.2f" % rr, "%.2f" % m["settle"], "%.3f" % m["th_ss"],
                     "%.2f" % m["u_rms"], "%.0f" % m["q_max"],
                     "%.3f" % m["th_ss_ceff"], "%.2f" % m["settle_ceff"],
                     "X" if m["loc"] else "-"))
    print("-" * 100)
    for kn in INDI_SWEEP:
        m = measure("indi", {"K_NU": kn, "KI_NU": kn * 0.5})
        indi_rows.append((kn, m))
        print(hdr % ("B", "K_NU=%.0f" % kn, "%.2f" % m["settle"], "%.3f" % m["th_ss"],
                     "%.2f" % m["u_rms"], "%.0f" % m["q_max"],
                     "%.3f" % m["th_ss_ceff"], "%.2f" % m["settle_ceff"],
                     "X" if m["loc"] else "-"))
    print("=" * 100)

    # ── 매칭 비교: 비슷한 정상 정착시간 대역에서 강건성(θss 오차½) 비교 ──
    print("\n[Pareto 해석] 같은 *제어활동(u_rms)* 대역에서 강건성 비교:")
    print("  %-22s %-22s %s" % ("LQR (활동→강건성)", "INDI (활동→강건성)", "INDI 우위"))
    # u_rms 로 정렬 후 가까운 활동끼리 매칭
    L = sorted(lqr_rows, key=lambda r: r[1]["u_rms"])
    I = sorted(indi_rows, key=lambda r: r[1]["u_rms"])
    for (rr, lm) in L:
        # 가장 가까운 u_rms 의 INDI
        j = min(I, key=lambda r: abs(r[1]["u_rms"] - lm["u_rms"]))
        im = j[1]
        adv = lm["th_ss_ceff"] / max(1e-6, im["th_ss_ceff"])
        print("  u%-6.1f θ½=%-7.3f   u%-6.1f θ½=%-7.3f   %.1f×"
              % (lm["u_rms"], lm["th_ss_ceff"], im["u_rms"], im["th_ss_ceff"], adv))

    print("\n결론 가이드:")
    print("  · 모든 활동대역에서 INDI θss(오차½) < LQR → INDI Pareto 우월(같은 활동에 더 강건).")
    print("  · 정상 θss·정착이 비슷한데 오차½서만 갈리면 → INDI 의 이득은 '강건성 특화'.")
