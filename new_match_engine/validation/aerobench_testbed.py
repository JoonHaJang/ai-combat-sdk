"""고AoA 검증 테스트베드 — TP-1538(AeroBench Morelli) plant 위에서 INDI vs LQR(내측) 비교.

목적: JSBSim+limiter 가 못 들어간 고받음각 영역에서 INDI 가 LQR 한계를 넘는지 *데이터로* 검증.
plant: AeroBench(stanleybak) Morelli 다항식 F-16 6-DOF (공력=NASA TP-1538 고AoA/실속후 데이터).
  · white-box 해석모델 → 깨끗한 선형화(A,B)·ḡ, 고α 비선형(Cm 역전·롤요 커플링) 포함.

구조 (LQR-vs-INDI 공정 비교 = 외측 동일, 내측만 swap):
  외측 자세 P: (θ_cmd,φ_cmd) → rate_ref(p,q,r)
  내측 A=LQR : u_surf = u0 − K_r·([P,Q,R] − rate_ref)        (rate 부분상태 CARE)
  내측 B=INDI: Δδ = ḡ⁻¹·(ν − ω̇),  ν = PI(rate_ref − [P,Q,R]) (증분, ω̇ 측정)

검증(사용자 프레임워크 A·B): 고α pull/반전 × {정상, 모델불확실성(제어효과↓), 센서노이즈}
지표: 자세/rate 추종 RMSE, max α, LOC(departure) 여부, 제어활동.
"""
from __future__ import annotations
import sys, os, math
sys.path.insert(0, os.path.dirname(__file__))
import numpy as np
from scipy.linalg import solve_continuous_are
from scipy.optimize import fsolve
from aerobench.lowlevel.subf16_model import subf16_model
from aerobench.lowlevel.tgear import tgear

VT, AL, BE, PH, TH, PS, P, Q, R, PN, PE, H, POW = range(13)
RATE = [P, Q, R]          # 내측 제어 상태
SURF = [1, 2, 3]          # u: elev, ail, rud (deg)
RTOD = 57.29578


def xdot(x, u):
    return np.asarray(subf16_model(x, u, "morelli")[0], dtype=float)


def trim_level(vt=502.0, h=15000.0):
    """정상 수평비행 trim: (alpha, elev_deg, throttle) 로 [VTdot, alphadot, qdot]=0."""
    def eqs(z):
        alpha, el, thr = z
        x = np.zeros(13)
        x[VT] = vt; x[AL] = alpha; x[TH] = alpha; x[H] = h; x[POW] = tgear(thr)
        u = np.array([thr, el, 0.0, 0.0])
        xd = xdot(x, u)
        return [xd[VT], xd[AL], xd[Q]]
    a, el, thr = fsolve(eqs, [0.05, -2.0, 0.2], full_output=False)
    x0 = np.zeros(13)
    x0[VT] = vt; x0[AL] = a; x0[TH] = a; x0[H] = h; x0[POW] = tgear(thr)
    u0 = np.array([thr, el, 0.0, 0.0])
    return x0, u0


def linearize(x0, u0, dx=1e-4, du=1e-3):
    """중앙차분 A=∂f/∂x (13×13), B=∂f/∂u (13×4)."""
    n, m = 13, 4
    A = np.zeros((n, n)); B = np.zeros((n, m))
    for j in range(n):
        xp = x0.copy(); xm = x0.copy()
        d = dx * (abs(x0[j]) + 1.0)
        xp[j] += d; xm[j] -= d
        A[:, j] = (xdot(xp, u0) - xdot(xm, u0)) / (2*d)
    for j in range(m):
        up = u0.copy(); um = u0.copy()
        up[j] += du; um[j] -= du
        B[:, j] = (xdot(x0, up) - xdot(x0, um)) / (2*du)
    return A, B


def make_lqr_rate(A, B, rr_scale=1.0):
    """rate 부분상태 [P,Q,R] LQR (CARE). rr_scale↓ = 입력페널티↓ = 더 공격적."""
    Ar = A[np.ix_(RATE, RATE)]
    Br = B[np.ix_(RATE, SURF)]
    Qr = np.diag([20.0, 40.0, 20.0])      # roll,pitch,yaw rate 가중
    Rr = np.diag([1.0, 1.0, 1.0]) * 0.01 * rr_scale
    Pr = solve_continuous_are(Ar, Br, Qr, Rr)
    Kr = np.linalg.inv(Rr) @ Br.T @ Pr
    return Kr, Br


# ── 제어기 (외측 자세 P 공통; 내측만 LQR/INDI) ──
class _Ctl:
    def __init__(self, A, B, u0, dt, gains=None):
        g = gains or {}
        self.Kr, self.Br = make_lqr_rate(A, B, rr_scale=g.get("rr_scale", 1.0))
        self.gbar = self.Br                  # INDI 제어효과 ḡ (rate×surf 3×3)
        self.u0_surf = u0[1:].copy()
        self.dt = dt
        # 외측 자세 P (LQR·INDI 공통), 내측 INDI PI
        self.K_TH = g.get("K_TH", 6.0)
        self.K_PH = g.get("K_PH", 7.0)       # θ,φ → q_ref,p_ref
        self.K_NU = g.get("K_NU", 25.0)
        self.KI_NU = g.get("KI_NU", 12.0)    # rate err → ν (INDI)
        self.reset()

    def reset(self):
        self._u_prev = self.u0_surf.copy()
        self._prev_rate = None
        self._int = np.zeros(3)

    def rate_ref(self, x, th_cmd, ph_cmd):
        q_ref = np.clip(self.K_TH*(th_cmd - x[TH]), -math.radians(80), math.radians(80))
        p_ref = np.clip(self.K_PH*(ph_cmd - x[PH]), -math.radians(120), math.radians(120))
        r_ref = -2.0 * x[BE]                  # 협조(β→0)
        return np.array([p_ref, q_ref, r_ref])

    def step_lqr(self, x, th_cmd, ph_cmd):
        ref = self.rate_ref(x, th_cmd, ph_cmd)
        rate = np.array([x[P], x[Q], x[R]])
        dsurf = -self.Kr @ (rate - ref)
        return np.clip(self.u0_surf + dsurf, -25.0, 25.0)

    def step_indi(self, x, th_cmd, ph_cmd):
        ref = self.rate_ref(x, th_cmd, ph_cmd)
        rate = np.array([x[P], x[Q], x[R]])
        # ω̇ 측정 (유한차분)
        if self._prev_rate is None:
            wdot = np.zeros(3)
        else:
            wdot = (rate - self._prev_rate) / self.dt
        self._prev_rate = rate.copy()
        # ν = PI(rate_err)  →  Δδ = ḡ⁻¹(ν − ω̇)
        err = ref - rate
        self._int = np.clip(self._int + err*self.dt, -10, 10)
        nu = self.K_NU*err + self.KI_NU*self._int
        dsurf = np.linalg.solve(self.gbar, nu - wdot)
        u = np.clip(self._u_prev + dsurf, -25.0, 25.0)
        self._u_prev = u.copy()
        return u


def run(engine, A, B, x0, u0, th_cmd, ph_cmd, T=8.0, dt=1/100.0,
        ceff=1.0, noise=0.0, seed=0, gains=None):
    ctl = _Ctl(A, B, u0, dt, gains=gains)
    x = x0.copy(); thr = u0[0]
    rng = np.random.default_rng(seed)
    nt = int(T/dt); n_sub = 4
    alpha_max = 0.0; loc = False
    th_errs, ph_errs = [], []; rate_max = np.zeros(3); u_rms = 0.0
    for k in range(nt):
        surf = ctl.step_lqr(x, th_cmd, ph_cmd) if engine == "lqr" else ctl.step_indi(x, th_cmd, ph_cmd)
        u = np.array([thr, surf[0], surf[1], surf[2]])
        u_act = u.copy(); u_act[1:] *= ceff
        if noise > 0:
            u_act[1:] += noise * rng.standard_normal(3)
        u_act[1:] = np.clip(u_act[1:], -25, 25)
        # RK4 적분 (n_sub 서브스텝)
        h = dt / n_sub
        for _ in range(n_sub):
            k1 = xdot(x, u_act); k2 = xdot(x + 0.5*h*k1, u_act)
            k3 = xdot(x + 0.5*h*k2, u_act); k4 = xdot(x + h*k3, u_act)
            x = x + (h/6.0)*(k1 + 2*k2 + 2*k3 + k4)
        if not np.all(np.isfinite(x)) or abs(x[AL]*RTOD) > 70 or abs(x[BE]*RTOD) > 45:
            loc = True; break
        alpha_max = max(alpha_max, abs(x[AL]*RTOD))
        rate_max = np.maximum(rate_max, np.abs(np.degrees([x[P], x[Q], x[R]])))
        th_errs.append(math.degrees(x[TH] - th_cmd)); ph_errs.append(math.degrees(x[PH] - ph_cmd))
        u_rms += float(np.sum(surf**2))
    th_errs = np.array(th_errs) if th_errs else np.array([math.degrees(th_cmd)])
    ph_errs = np.array(ph_errs) if ph_errs else np.array([math.degrees(ph_cmd)])
    nss = max(1, int(2.0/dt))                      # 마지막 2s = 정상상태
    # 정착시간: |θ오차|<2° 로 들어가 유지되는 첫 시점
    settle = T
    for i in range(len(th_errs)):
        if np.all(np.abs(th_errs[i:]) < 2.0):
            settle = i*dt; break
    return dict(loc=loc, alpha_max=alpha_max,
                th_rmse=float(np.sqrt(np.mean(th_errs**2))),
                ph_rmse=float(np.sqrt(np.mean(ph_errs**2))),
                th_ss=float(np.mean(np.abs(th_errs[-nss:]))),    # ★ 정상상태 |θ오차|
                ph_ss=float(np.mean(np.abs(ph_errs[-nss:]))),    # ★ 정상상태 |φ오차|
                settle=settle,
                p_max=rate_max[0], q_max=rate_max[1], r_max=rate_max[2],
                u_rms=math.sqrt(u_rms/max(1, len(th_errs))))


MANEUVERS = {
    "pitch_pull_25":  (math.radians(25.0), 0.0),     # 고α pull
    "roll_60_pull20": (math.radians(20.0), math.radians(60.0)),  # 복합 고기동
}
CONDS = (("nominal", 1.0, 0.0), ("ceff0.5", 0.5, 0.0), ("noise", 1.0, 2.0))

if __name__ == "__main__":
    print("=" * 96)
    print("  고AoA 검증 — TP-1538(AeroBench Morelli) plant 위 INDI(B) vs LQR(A) 내측 비교")
    print("=" * 96)
    x0, u0 = trim_level(502.0, 15000.0)
    A, B = linearize(x0, u0)
    print(f"trim: α={math.degrees(x0[AL]):.2f}° elev={u0[1]:.2f}° thr={u0[0]:.3f}  "
          f"| rate-LQR·INDI ḡ from A,B(13×13)")
    hdr = "%-16s %-5s %-9s | %5s %7s %7s %6s | %5s %5s %5s"
    print(hdr % ("maneuver", "eng", "cond", "αmax", "θss(정상)", "θRMSE", "정착s",
                 "qmax", "pmax", "LOC"))
    print("  (★ θss = 정상상태 |θ오차| = 진짜 추종품질 / θRMSE = 과도구간 포함)")
    for mn, (thc, phc) in MANEUVERS.items():
        for cond, ceff, noise in CONDS:
            for eng in ("lqr", "indi"):
                r = run(eng, A, B, x0, u0, thc, phc, ceff=ceff, noise=noise)
                print(hdr % (mn if (eng == "lqr") else "", "A" if eng == "lqr" else "B",
                             cond if eng == "lqr" else "",
                             "%.1f" % r["alpha_max"], "%.2f" % r["th_ss"], "%.2f" % r["th_rmse"],
                             "%.1f" % r["settle"], "%.0f" % r["q_max"], "%.0f" % r["p_max"],
                             "DEPART" if r["loc"] else "-"))
        print("-" * 96)
    print("\n해석: θss(정상상태 오차) 작고 DEPART 없는 쪽이 강건. RMSE는 21° 계단 과도구간 포함.")
