"""논문 그림 생성 — docs/figures/ 에 fig1~fig8 PNG. 실데이터(궤적·D2시퀀스·결과)+스키매틱(구조·기하·ETM·deadlock).

usage: python tools/make_paper_figures.py
"""
from __future__ import annotations
import sys, os, math, warnings
warnings.filterwarnings("ignore")
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch, Wedge, Circle, Arc
import numpy as np

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIG = os.path.join(HERE, "docs", "figures")
os.makedirs(FIG, exist_ok=True)
NME = os.path.join(HERE, "new_match_engine")
for p in ("bt", "control", "engine"):
    sys.path.insert(0, os.path.join(NME, p))
sys.path.insert(0, os.path.join(HERE, "tools"))

plt.rcParams.update({"font.size": 11, "axes.grid": True, "grid.alpha": 0.3,
                     "figure.dpi": 120, "savefig.bbox": "tight"})
BLUE, RED, GREEN, ORANGE, PURPLE = "#2b6cb0", "#c53030", "#2f855a", "#dd6b20", "#6b46c1"


# ─────────────────────────────────────────────────────────────────────────────
def fig1_architecture():
    """Fig 1 — 4계층 정책 아키텍처 블록다이어그램."""
    fig, ax = plt.subplots(figsize=(11, 4.2)); ax.axis("off"); ax.grid(False)
    ax.set_xlim(0, 11); ax.set_ylim(0, 4.2)
    boxes = [
        (0.2, "관측 obs\n(상대기하·에너지)", "#e2e8f0"),
        (2.1, "① 상황분류\n궤적 형상\n(reopen·aa_min·rmin)", "#bee3f8"),
        (4.2, "② 독트린\nBFM tactic\n(pursuit/circle/ETM…)", "#c6f6d5"),
        (6.4, "③ guidance\nsetpoint\n(ψ*, h*, V*)", "#fefcbf"),
        (8.5, "④ autopilot\nLQR / INDI", "#fed7d7"),
    ]
    for x, t, c in boxes:
        ax.add_patch(FancyBboxPatch((x, 1.5), 1.7, 1.4, boxstyle="round,pad=0.05",
                                    fc=c, ec="#444", lw=1.3))
        ax.text(x + 0.85, 2.2, t, ha="center", va="center", fontsize=9.5)
    for x in (1.9, 4.0, 6.2, 8.3):
        ax.add_patch(FancyArrowPatch((x, 2.2), (x + 0.2, 2.2), arrowstyle="-|>", mutation_scale=16, color="#444"))
    # physics + judge
    ax.add_patch(FancyBboxPatch((8.5, 0.1), 2.3, 1.0, boxstyle="round,pad=0.05", fc="#e9d8fd", ec="#444", lw=1.3))
    ax.text(9.65, 0.6, "JSBSim 물리 120Hz\n→ judge(WEZ: ATA<12° &\n500–3000ft → DAMAGE)", ha="center", va="center", fontsize=8.5)
    ax.add_patch(FancyArrowPatch((9.6, 1.5), (9.6, 1.15), arrowstyle="-|>", mutation_scale=16, color="#444"))
    ax.add_patch(FancyArrowPatch((8.5, 0.6), (0.6, 0.6), arrowstyle="-|>", mutation_scale=16, color=BLUE, ls="--"))
    ax.text(4.5, 0.35, "feedback (다음 obs)", color=BLUE, fontsize=8.5, ha="center")
    ax.set_title("Fig 1.  설명가능 BT 정책의 4계층 구조", fontsize=12, loc="left")
    fig.savefig(os.path.join(FIG, "fig1_architecture.png")); plt.close(fig)


def fig2_wez_geometry():
    """Fig 2 — 교전 기하: ATA, AA, LOS, WEZ cone."""
    fig, ax = plt.subplots(figsize=(7.2, 5.2)); ax.set_aspect("equal")
    ax.set_xlim(-1, 9); ax.set_ylim(-1, 7)
    # ego at origin heading up-right
    ego = np.array([1.0, 1.0]); enm = np.array([6.0, 5.0])
    ehead = np.array([0.85, 0.53]); ehead /= np.linalg.norm(ehead)        # ego velocity
    thead = np.array([-0.2, 0.98]); thead /= np.linalg.norm(thead)        # enm velocity
    los = enm - ego; losn = los / np.linalg.norm(los)
    ax.plot([ego[0], ego[0] + 2.2*ehead[0]], [ego[1], ego[1] + 2.2*ehead[1]], color=BLUE, lw=2)
    ax.annotate("우리 속도벡터", ego + 2.3*ehead, color=BLUE, fontsize=9)
    ax.plot([enm[0], enm[0] + 2.0*thead[0]], [enm[1], enm[1] + 2.0*thead[1]], color=RED, lw=2)
    ax.annotate("적 속도벡터", enm + 2.0*thead + np.array([-1.4, 0.1]), color=RED, fontsize=9)
    ax.plot([ego[0], enm[0]], [ego[1], enm[1]], color="#444", ls="--", lw=1.3)
    ax.annotate("LOS (시선)", (ego+enm)/2 + np.array([0.1, -0.5]), fontsize=9, color="#444")
    # WEZ cone from ego (±12° around velocity)
    a0 = math.degrees(math.atan2(ehead[1], ehead[0]))
    ax.add_patch(Wedge(ego, 7.5, a0-12, a0+12, fc=GREEN, alpha=0.15))
    ax.add_patch(Wedge(ego, 0.6, a0-12, a0+12, fc=GREEN, alpha=0.0, ec=GREEN))
    ax.annotate("WEZ cone\nATA<12°", ego + 4.5*ehead + np.array([-0.2, 1.0]), color=GREEN, fontsize=9)
    # ATA angle arc
    ax.add_patch(Arc(ego, 2.0, 2.0, angle=0, theta1=a0, theta2=math.degrees(math.atan2(losn[1], losn[0])), color=BLUE))
    ax.text(ego[0]+1.2, ego[1]+0.9, "ATA", color=BLUE, fontsize=10)
    # AA at enm (angle off enm tail to LOS)
    ta = math.degrees(math.atan2(-thead[1], -thead[0]))
    la = math.degrees(math.atan2(-losn[1], -losn[0]))
    ax.add_patch(Arc(enm, 1.6, 1.6, angle=0, theta1=min(ta, la), theta2=max(ta, la), color=RED))
    ax.text(enm[0]-1.6, enm[1]-0.3, "AA", color=RED, fontsize=10)
    ax.plot(*ego, "^", color=BLUE, ms=13); ax.plot(*enm, "^", color=RED, ms=13)
    ax.text(ego[0]-0.1, ego[1]-0.5, "우리(ego)", color=BLUE, fontsize=9, ha="center")
    ax.text(enm[0]+0.1, enm[1]+0.5, "적(enm)", color=RED, fontsize=9, ha="center")
    ax.set_title("Fig 2.  교전 기하 — ATA(antenna train), AA(aspect), LOS, WEZ", fontsize=11.5, loc="left")
    ax.set_xticks([]); ax.set_yticks([]); ax.grid(False)
    fig.savefig(os.path.join(FIG, "fig2_wez_geometry.png")); plt.close(fig)


def fig5_etm_concept():
    """Fig 5 — ETM: 현재위치 조준(lag) vs 예측 호 조준(앞지름)."""
    fig, ax = plt.subplots(figsize=(7.2, 4.6)); ax.set_aspect("equal")
    ego = np.array([0.0, 0.0])
    th = np.linspace(-0.3, 1.5, 60); R = 3.0
    cx, cy = 2.0, 3.2
    arc = np.stack([cx + R*np.cos(th + 3.6), cy + R*np.sin(th + 3.6)], 1)
    ax.plot(arc[:, 0], arc[:, 1], color=RED, lw=2, label="적 등선회 호(예측)")
    now = arc[15]; fut = arc[40]
    ax.plot(*now, "o", color=RED, ms=10); ax.annotate("적 현재", now+np.array([0.1, -0.4]), color=RED, fontsize=9)
    ax.plot(*fut, "o", color=ORANGE, ms=10); ax.annotate("적 τ초 뒤(ETM)", fut+np.array([0.1, 0.2]), color=ORANGE, fontsize=9)
    ax.plot(*ego, "^", color=BLUE, ms=14); ax.annotate("우리", ego+np.array([-0.1, -0.4]), color=BLUE, fontsize=9, ha="center")
    ax.add_patch(FancyArrowPatch(ego, now, arrowstyle="-|>", mutation_scale=15, color="#888", ls="--"))
    ax.text(0.6, 1.2, "현재위치 조준\n→ 닫는 사이 적 빠져나감(lag)", color="#888", fontsize=8.5)
    ax.add_patch(FancyArrowPatch(ego, fut, arrowstyle="-|>", mutation_scale=15, color=BLUE, lw=2))
    ax.text(2.0, 0.6, "ETM: 예측위치 조준\n→ 회피 앞지름", color=BLUE, fontsize=8.5)
    ax.set_xlim(-1.5, 6); ax.set_ylim(-0.5, 6.5); ax.set_xticks([]); ax.set_yticks([]); ax.grid(False)
    ax.set_title("Fig 5.  ETM — 적 궤적 예측으로 회피를 앞지르는 조준", fontsize=11.5, loc="left")
    fig.savefig(os.path.join(FIG, "fig5_etm_concept.png")); plt.close(fig)


def fig8_deadlock():
    """Fig 8 — 관측-행동 deadlock 타임라인."""
    fig, ax = plt.subplots(figsize=(10, 3.6)); ax.set_xlim(0, 200); ax.set_ylim(0, 3)
    ax.axvspan(0, 40, color=BLUE, alpha=0.08); ax.axvspan(40, 200, color=GREEN, alpha=0.06)
    ax.text(20, 2.7, "관측 구간\n(유형 식별 ≈40s 필요)", ha="center", fontsize=9, color=BLUE)
    ax.text(120, 2.7, "행동 구간", ha="center", fontsize=9, color=GREEN)
    # action window for D2
    ax.add_patch(FancyBboxPatch((2, 1.4), 28, 0.5, boxstyle="round,pad=0.02", fc=ORANGE, alpha=0.5, ec=ORANGE))
    ax.text(16, 1.65, "D2 승리 창 (t=0 머지 필요)", ha="center", fontsize=8.5)
    ax.axvline(40, color="#444", ls="--"); ax.text(41, 0.6, "t≈40s: 유형 식별 가능\n(but 행동 창 이미 닫힘)", fontsize=8.5)
    ax.add_patch(FancyArrowPatch((40, 1.0), (15, 1.4), arrowstyle="-|>", mutation_scale=14, color=RED, ls=":"))
    ax.text(60, 0.3, "deadlock: 행동하려면 t=0에 유형을 알아야 하고, 알려면 관측해야 하는데, 관측하면 창이 닫힌다", fontsize=9, color=RED)
    ax.set_yticks([]); ax.set_xlabel("교전 시각 t (s)")
    ax.set_title("Fig 8.  블라인드 deadlock — D2 승리 창과 식별 지연의 충돌(Nash 천장=16/17)", fontsize=11.5, loc="left")
    fig.savefig(os.path.join(FIG, "fig8_deadlock.png")); plt.close(fig)


def fig7_results():
    """Fig 7 — 17개 결과 (적 HP, 우리 HP=100)."""
    opp = ["defensiv", "ace", "B1", "B2", "C1", "C2", "C3", "D1", "E1", "E2",
           "simple", "aggress", "A1", "A2", "D3", "A3★", "D2★"]
    ehp = [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 93, 93, 93, 81, 99, 95, 94]
    res = ["격추"]*10 + ["판정"]*5 + ["판정", "판정"]
    colors = [RED if r == "격추" else ORANGE for r in res]
    colors[-2] = PURPLE; colors[-1] = PURPLE
    fig, ax = plt.subplots(figsize=(11, 4.0))
    x = np.arange(len(opp))
    ax.bar(x, [100]*len(opp), color=BLUE, alpha=0.25, label="우리 HP=100(무손상)")
    ax.bar(x, ehp, color=colors, label="적 잔여 HP")
    for i, h in enumerate(ehp):
        ax.text(i, h+2, f"{h}", ha="center", fontsize=7.5)
    ax.set_xticks(x); ax.set_xticklabels(opp, rotation=45, ha="right", fontsize=8)
    ax.set_ylabel("HP"); ax.set_ylim(0, 108)
    ax.legend(loc="upper left", fontsize=9)
    ax.set_title("Fig 7.  결과 — 17/17(적 식별), 우리 무손상. 격추10(적HP0)·판정7·구회피자(A3·D2)★ 파훼", fontsize=11, loc="left")
    fig.savefig(os.path.join(FIG, "fig7_results.png")); plt.close(fig)


# ── 실데이터 그림 ────────────────────────────────────────────────────────────
def _run_traj(opp_name, tac_fn, dur=120.0):
    from exp_e22_chaseforce import _opp
    from lqr import GainScheduledLQR
    from autopilot import AutopilotConfig
    from match import Match
    from scenarios import spawn_adt_neutral
    from obs import compute_obs, _ned, P_LAT, P_LON, P_ALT
    gs = GainScheduledLQR([5000, 15000, 25000], [250, 350, 450]).build()
    cfg = AutopilotConfig(KP_PSI=0.25); cfg.MAX_PSI_RATE = math.radians(30.0)
    p1, p2 = spawn_adt_neutral()
    lat0, lon0, a0 = p1[P_LAT], p1[P_LON], p1[P_ALT]
    rec = {"rx": [], "ry": [], "t": [], "d": [], "ua": [], "ea": []}
    def fn(o):
        ob = compute_obs(p1, p2)
        en, ee, _ = _ned(p1, lat0, lon0, a0); on, oe, _ = _ned(p2, lat0, lon0, a0)
        dx, dy = on-en, oe-ee
        h = math.radians(ob.ego_psi_deg)
        rec["rx"].append((dx*math.cos(-h) - dy*math.sin(-h)) / 6076.0)
        rec["ry"].append((dx*math.sin(-h) + dy*math.cos(-h)) / 6076.0)
        rec["t"].append(len(rec["t"])*0.1); rec["d"].append(ob.distance_ft)
        rec["ua"].append(ob.ego_alt_ft); rec["ea"].append(ob.enm_alt_ft)
        return tac_fn(ob, p1, p2)
    m = Match(p1, p2, gs, cfg1=cfg, cfg2=AutopilotConfig(KP_PSI=0.10),
              control_hz=20, bt_hz=10, log_hz=60, controller1="indi", controller2="lqr")
    res = m.run(tactic_fn1=lambda o: fn(o), tactic_fn2=lambda o: _opp(opp_name)(compute_obs(p2, p1)), duration_s=dur)
    return rec, res


def fig3_shapes():
    """Fig 3 — 상대궤적 형상: 격추(spiral-in) vs 무승부(orbit). 실데이터."""
    from exp_e27_adaptive_subset import AdaptivePolicy
    from exp_e7_champion import _train
    from exp_e10_unified import DS_DA
    rf, tac = _train(DS_DA)
    base = AdaptivePolicy(rf, tac, corrections=True)
    cases = [("anchor_aggressive", "격추형(spiral-in)", RED),
             ("C2_OneCircleRad", "격추형(hook-in)", RED),
             ("A3_LagAngler", "무승부(standoff arc)", PURPLE),
             ("D2_LastDitch", "무승부(wide orbit)", PURPLE)]
    fig, axes = plt.subplots(1, 4, figsize=(15, 4.0))
    for ax, (opp, lab, c) in zip(axes, cases):
        b = AdaptivePolicy(rf, tac, corrections=True)
        rec, _ = _run_traj(opp, lambda ob, p1, p2, b=b: b.select(p1, p2), dur=120)
        ax.plot(rec["rx"], rec["ry"], lw=0.8, color=c)
        ax.plot(0, 0, "^", color=BLUE, ms=11); ax.plot(rec["rx"][0], rec["ry"][0], "o", color=GREEN, ms=6)
        ax.set_title(f"{opp}\n{lab}", fontsize=9.5); ax.set_aspect("equal"); ax.axhline(0, color="#ccc", lw=0.5)
        ax.set_xlabel("forward (nm)")
    axes[0].set_ylabel("right (nm)")
    fig.suptitle("Fig 3.  적 상대궤적 형상(우리=중심▲). 격추=중심으로 감겨듦(spiral-in), 무승부=큰 반경 orbit", fontsize=11.5, x=0.01, ha="left")
    fig.savefig(os.path.join(FIG, "fig3_shapes.png")); plt.close(fig)


def fig6_d2_sequence():
    """Fig 6 — D2 승리 시퀀스 6-phase 동안 거리·고도. 실데이터."""
    import guidance
    from tactic import Tactic as T
    guidance.ETM_TAU = 2.0
    SEQ = [T.LEAD_PURSUIT, T.VERTICAL_PURSUIT, T.SCISSORS, T.GUN_TRACK, T.LAG_PURSUIT, T.ETM_TRACK]
    names = ["LEAD", "VERTICAL", "SCISSORS", "GUN", "LAG", "ETM"]
    DUR, N = 180.0, 6
    st = {"t": 0.0}
    def fn(ob, p1, p2):
        st["t"] += 0.1
        if ob.ego_alt_ft < 2500: return T.CLIMB
        return SEQ[min(5, int(st["t"]/(DUR/N)))]
    rec, res = _run_traj("D2_LastDitch", fn, dur=DUR)
    fig, ax = plt.subplots(2, 1, figsize=(11, 5.2), sharex=True)
    ax[0].plot(rec["t"], rec["d"], color=BLUE, lw=1.4); ax[0].axhspan(500, 3000, color=GREEN, alpha=0.12)
    ax[0].set_ylabel("거리 (ft)"); ax[0].text(2, 3300, "WEZ 거리권", color=GREEN, fontsize=8)
    ax[1].plot(rec["t"], rec["ua"], color=BLUE, lw=1.4, label="우리 고도")
    ax[1].plot(rec["t"], rec["ea"], color=RED, lw=1.4, label="D2 고도")
    ax[1].set_ylabel("고도 (ft)"); ax[1].set_xlabel("t (s)"); ax[1].legend(fontsize=9)
    for i, nm in enumerate(names):
        x = i*DUR/N
        for a in ax: a.axvline(x, color="#bbb", ls=":", lw=0.8)
        ax[0].text(x+1, ax[0].get_ylim()[1]*0.93, nm, fontsize=8, color=PURPLE)
    fig.suptitle(f"Fig 6.  D2 승리 시퀀스 6-phase — 거리·고도 (결과 HP 100:{res.health2:.0f}, 무피해 판정승)", fontsize=11.5, x=0.01, ha="left")
    fig.savefig(os.path.join(FIG, "fig6_d2_sequence.png")); plt.close(fig)


def fig4_separability():
    """Fig 4 — 형상 특징 분리성: {A3,D2} vs 15 (reopen, aa_min). 실데이터."""
    from exp_e48_type_features import feats, FULL, DRAWS
    from exp_e27_adaptive_subset import AdaptivePolicy
    from exp_e7_champion import _train
    from exp_e10_unified import DS_DA
    from lqr import GainScheduledLQR
    from autopilot import AutopilotConfig
    rf, tac = _train(DS_DA)
    gs = GainScheduledLQR([5000, 15000, 25000], [250, 350, 450]).build()
    cfg = AutopilotConfig(KP_PSI=0.25); cfg.MAX_PSI_RATE = math.radians(20.0)
    fig, ax = plt.subplots(figsize=(7.6, 5.4))
    for opp in FULL:
        f = feats(opp, rf, tac, gs, cfg, 50.0)
        d = opp in DRAWS
        ax.scatter(f["reopen"], f["aa_min"], s=110 if d else 60,
                   c=(PURPLE if d else "#90cdf4"), edgecolors="#333", zorder=3 if d else 2)
        if d or opp.startswith(("anchor", "A3", "D2")):
            ax.annotate(opp.replace("anchor_", "").replace("_", "")[:7], (f["reopen"], f["aa_min"]),
                        fontsize=7.5, xytext=(4, 4), textcoords="offset points")
    ax.axvline(3000, color=PURPLE, ls="--", alpha=0.6); ax.axhline(30, color=RED, ls="--", alpha=0.6)
    ax.text(800, 33, "A3: reopen<3000", color=PURPLE, fontsize=8.5)
    ax.text(8200, 33, "D2: aa_min>30 ∧ rmin>3000", color=RED, fontsize=8.5)
    ax.set_xlabel("reopen (ft) — 최접근 후 재이탈량"); ax.set_ylabel("aa_min (deg) — 최소 aspect")
    ax.set_title("Fig 4.  형상 특징 분리성 — 무승부 회피자(보라★)가 15승 적과 분리(거짓양성 0)", fontsize=11, loc="left")
    fig.savefig(os.path.join(FIG, "fig4_separability.png")); plt.close(fig)


if __name__ == "__main__":
    print("스키매틱 그림..."); fig1_architecture(); fig2_wez_geometry(); fig5_etm_concept(); fig8_deadlock(); fig7_results()
    print("실데이터 그림(엔진 실행)...")
    fig3_shapes(); print("  fig3 ok")
    fig4_separability(); print("  fig4 ok")
    fig6_d2_sequence(); print("  fig6 ok")
    print("완료:", FIG); print(os.listdir(FIG))
