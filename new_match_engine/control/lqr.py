"""Gain-scheduled LQR — F-16 저수준 제어기.

설계: Stevens, Lewis & Johnson, Aircraft Control and Simulation, 3rd ed. (Wiley)
     scipy.linalg.solve_continuous_are → Riccati 해 P → K = R^-1 B^T P

스케줄 변수: Mach × alt (운영점 격자)
런타임:  현재 (Mach, alt) → 인접 K 쌍선형 보간 → u = -K(x - x*)

입력:
    x  = get_state() 10-벡터 [V,alpha,theta,q, beta,phi,p,r, h,psi]
    x* = setpoint    (heading psi*, alt h*, speed V* 만 지정, 나머지 trim 값)
출력:
    u  = [throttle, elevator, aileron, rudder]
"""
from __future__ import annotations
import math
import numpy as np
from scipy.linalg import solve_continuous_are
from plant import STATE_ORDER, INPUT_ORDER
from linearize import linearize, LON_IDX, LAT_IDX
from constants import FT_S_TO_KNOT  # fps → kts (보간 인덱스용, reciprocal 보장)

N = len(STATE_ORDER)   # 10
M = len(INPUT_ORDER)   # 4


# ── Q, R 기본값 (튜닝 파라미터) ──────────────────────────────────────────
# Q 대각: 상태 오차 가중치.  R 대각: 입력 사용량 페널티.
# 단위: [fps, rad, rad, rad/s, rad, rad, rad/s, rad/s, ft, rad]
#       [throttle, elevator, aileron, rudder]
# Stevens & Lewis §6: "LQR Q = C^T C 에서 출발, 성능 trade-off 로 조정."
"""LQR 설계 원칙 (Stevens & Lewis §6, Bryson's method):

★ 구조: Inner loop 전용. h·psi는 OUTER loop(PI)가 담당.
  Inner loop 상태: [V, alpha, theta, q, beta, phi, p, r, h, psi]
  하지만 LQR이 h·psi를 직접 추적하면 throttle·aileron 채널과
  cross-coupling이 생겨 불안정.
  → h·psi는 Q에서 매우 약하게(≈0) 설정 → LQR은 태도(attitude) 안정만.
  → outer PI가 h_err→theta_cmd, psi_err→phi_cmd 변환하여 LQR에 전달.

Bryson's method: Q[i] = 1/max_err[i]², R[j] = 1/max_input[j]²
Inner loop 최대허용오차:
  V=100fps, alpha=5°=0.087rad, theta=30°=0.52rad, q=30°/s=0.52rad/s
  beta=5°=0.087rad, phi=60°=1.05rad, p=30°/s=0.52rad/s, r=30°/s=0.52rad/s
  h=10000ft(느슨하게), psi=π(느슨하게 — outer PI가 담당)
"""
"""Bryson Q/R — 종(lon)·횡(lat) 분리 원칙:
  full-state Q에서 K[ail,theta]·K[elev,phi] 교차결합이 크면
  pitch오차→aileron 진동, bank오차→elevator 진동 → 제어 불안정.
  해결: 종횡 간 교차 항목 Q를 0으로 → Riccati가 교차결합 게인을 억제.
  실제: Q를 대각으로 유지하되 종(V,alpha,theta,q,h)과 횡(beta,phi,p,r,psi)
  가중치를 분리 설계. 교차 결합은 R을 통해 간접 억제.
"""
DEFAULT_Q = np.diag([
    # 종방향 (longitudinal) ─────────────────────────────────
    1/200**2,      # V   (fps)   — 느슨 (outer PI 담당)
    1/0.087**2,    # alpha (rad) — ★ 강하게 (5° — 실속 방지)
    1/0.087**2,    # theta (rad) — ★★ 강하게 (5° — outer PI pitch 추적)
    1/0.35**2,     # q   (rad/s) — 20°/s
    # 횡방향 (lateral) ──────────────────────────────────────
    1/0.087**2,    # beta  (rad) — ★ 강하게 (5° — 사이드슬립)
    1/0.087**2,    # phi  (rad)  — ★★ 강하게 (5° — bank-to-turn)
    1/0.35**2,     # p   (rad/s) — 20°/s
    1/0.35**2,     # r   (rad/s) — 20°/s
    # 항법 (navigation) — outer PI가 담당, LQR은 무시 ────────
    1/20000**2,    # h    (ft)
    1/math.pi**2,  # psi  (rad)
])
# Bryson's R: 종횡 채널 독립성을 위해 aileron·rudder 권한 충분히
DEFAULT_R = np.diag([
    1/0.6**2,   # throttle
    1/0.4**2,   # elevator  — 종 채널 권한
    1/0.4**2,   # aileron   — 횡 채널 권한
    1/0.25**2,  # rudder
])


class LQRPoint:
    """단일 운영점 LQR."""

    def __init__(self, alt_ft: float, vc_kts: float,
                 Q: np.ndarray | None = None, R: np.ndarray | None = None):
        self.alt_ft  = alt_ft
        self.vc_kts  = vc_kts
        Q = DEFAULT_Q if Q is None else Q
        R = DEFAULT_R if R is None else R

        A, B, self.x0, self.u0 = linearize(alt_ft, vc_kts)
        self.A, self.B = A, B

        # Riccati 풀기
        P = solve_continuous_are(A, B, Q, R)
        self.K = np.linalg.inv(R) @ B.T @ P
        self.P = P

        # Structured LQR — 종·횡 교차 결합 항목 제거
        # 물리적 근거: 엘리베이터는 종(pitch) 담당, 에일러론/러더는 횡(roll/yaw) 담당.
        # F-16 동역학 A행렬의 종·횡 결합 때문에 K에 교차 항목이 생기지만,
        # 이를 유지하면 pitch 오차→aileron 진동 발생 (실측 확인).
        # 참조: Wie & Bernstein (1992), "Benchmark problems for robust control design"
        #       분리 설계가 실용적으로 더 안정적임을 보임.
        _LON = [STATE_ORDER.index(k) for k in ("V","alpha","theta","q","h")]
        _LAT = [STATE_ORDER.index(k) for k in ("beta","phi","p","r","psi")]
        _ELEV = INPUT_ORDER.index("elevator")
        _THR  = INPUT_ORDER.index("throttle")
        _AIL  = INPUT_ORDER.index("aileron")
        _RUD  = INPUT_ORDER.index("rudder")
        # 엘리베이터·throttle은 종방향 상태만 (횡방향 교차 항목 = 0)
        for j in _LAT:
            self.K[_ELEV, j] = 0.0
            self.K[_THR,  j] = 0.0
        # 에일러론·러더는 횡방향 상태만 (종방향 교차 항목 = 0)
        for j in _LON:
            self.K[_AIL, j] = 0.0
            self.K[_RUD, j] = 0.0

        # 안정성 검증 — closed-loop 고유값 전부 좌반평면
        cl_ev = np.linalg.eigvals(A - B @ self.K)
        self.stable = bool(np.all(cl_ev.real < 0))
        self.cl_eigenvalues = cl_ev

    def command(self, x: np.ndarray, x_star: np.ndarray) -> np.ndarray:
        """u = u0 - K(x - x*)  (trim feed-forward + 오차 피드백)"""
        u = self.u0 - self.K @ (x - x_star)
        # 입력 포화 clamp
        u[0] = np.clip(u[0], 0.0, 1.0)    # throttle
        u[1:] = np.clip(u[1:], -1.0, 1.0) # 조종면
        return u

    def gain_margin_db(self) -> float:
        """종 채널 (q → elevator) 단순 게인 마진 추정 (dB).

        K[elev, q] = 0 이면 루프가 끊어진 것 → ∞ dB 반환.
        """
        il = LON_IDX.index(STATE_ORDER.index("q"))
        iu = INPUT_ORDER.index("elevator")
        k = abs(self.K[iu, LON_IDX[il]])
        if k < 1e-9:    # 사실상 0 → 루프 미연결
            return float('inf')
        return 20.0 * np.log10(1.0 / k)


class GainScheduledLQR:
    """운영점 격자(alt × Mach) 위에 LQR 점을 빌드하고, 런타임에 보간."""

    def __init__(self,
                 alts_ft:  list[float] = [5_000.0, 15_000.0, 25_000.0],
                 vcs_kts:  list[float] = [250.0,   350.0,    450.0],
                 Q: np.ndarray | None = None,
                 R: np.ndarray | None = None):
        self.alts  = np.array(alts_ft)
        self.vcs   = np.array(vcs_kts)
        self.Q, self.R = Q, R
        self.grid: dict[tuple, LQRPoint] = {}
        print(f"[GainScheduledLQR] {len(alts_ft)}×{len(vcs_kts)} = {len(alts_ft)*len(vcs_kts)} 점 설계 중...")

    def build(self):
        for alt in self.alts:
            for vc in self.vcs:
                key = (float(alt), float(vc))
                print(f"  trim @ alt={alt:.0f}ft  vc={vc:.0f}kts ...", end=" ")
                pt = LQRPoint(alt, vc, self.Q, self.R)
                self.grid[key] = pt
                ev_re = sorted(pt.cl_eigenvalues.real)[:2]
                print(f"stable={pt.stable}  slowest_cl_ev={ev_re[0]:.4f},{ev_re[1]:.4f}")
        all_stable = all(p.stable for p in self.grid.values())
        print(f"[GainScheduledLQR] 빌드 완료. 전점 안정={all_stable}")
        return self

    def _interp_K(self, alt: float, vc: float) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """현재 (alt, vc) → 인접 4점 쌍선형 보간 → (K, x0, u0)."""
        a0 = self.alts[np.searchsorted(self.alts, alt, side='right').clip(1, len(self.alts)-1) - 1]
        a1 = self.alts[min(np.searchsorted(self.alts, alt, side='right'), len(self.alts)-1)]
        v0 = self.vcs[np.searchsorted(self.vcs, vc, side='right').clip(1, len(self.vcs)-1) - 1]
        v1 = self.vcs[min(np.searchsorted(self.vcs, vc, side='right'), len(self.vcs)-1)]

        wa = (alt - a0) / (a1 - a0) if a1 != a0 else 0.0
        wv = (vc  - v0) / (v1 - v0) if v1 != v0 else 0.0

        def g(a, v): return self.grid[(float(a), float(v))]
        K  = ((1-wa)*(1-wv)*g(a0,v0).K  + wa*(1-wv)*g(a1,v0).K +
              (1-wa)*wv    *g(a0,v1).K  + wa*wv    *g(a1,v1).K)
        x0 = ((1-wa)*(1-wv)*g(a0,v0).x0 + wa*(1-wv)*g(a1,v0).x0 +
              (1-wa)*wv    *g(a0,v1).x0  + wa*wv    *g(a1,v1).x0)
        u0 = ((1-wa)*(1-wv)*g(a0,v0).u0 + wa*(1-wv)*g(a1,v0).u0 +
              (1-wa)*wv    *g(a0,v1).u0  + wa*wv    *g(a1,v1).u0)
        return K, x0, u0

    def command(self, x: np.ndarray, x_star: np.ndarray) -> np.ndarray:
        h   = x[STATE_ORDER.index("h")]
        V   = x[STATE_ORDER.index("V")]
        # V fps → kts 변환 (보간 인덱스용)
        vc  = V * FT_S_TO_KNOT   # fps → kts (constants.py 정밀 reciprocal)
        K, x0, u0 = self._interp_K(
            np.clip(h,  self.alts[0], self.alts[-1]),
            np.clip(vc, self.vcs[0],  self.vcs[-1]),
        )
        u = u0 - K @ (x - x_star)
        u[0] = np.clip(u[0], 0.0, 1.0)
        u[1:] = np.clip(u[1:], -1.0, 1.0)
        return u


# ── 안정성 증명 출력 ──────────────────────────────────────────────────────
def print_stability_proof(pt: LQRPoint):
    print(f"\n=== 안정성 증명 @ alt={pt.alt_ft:.0f}ft vc={pt.vc_kts:.0f}kts ===")
    print(f"  stable (모든 cl 고유값 좌반평면): {pt.stable}")
    print("  closed-loop 고유값:")
    for e in sorted(pt.cl_eigenvalues, key=lambda x: x.real):
        if abs(e.imag) > 1e-3:
            wn = abs(e); zeta = -e.real / wn
            print(f"    {e.real:+.4f}{e.imag:+.4f}j  wn={wn:.3f} ζ={zeta:.3f}")
        else:
            print(f"    {e.real:+.4f}            tau={1/max(abs(e.real),1e-6):.2f}s")
    print(f"  K shape: {pt.K.shape}  (gain matrix 명시)")
    print(f"  종 elevator gain (q축): {pt.K[INPUT_ORDER.index('elevator'), STATE_ORDER.index('q')]:+.4f}")
    print(f"  횡 aileron gain  (phi축): {pt.K[INPUT_ORDER.index('aileron'), STATE_ORDER.index('phi')]:+.4f}")


if __name__ == "__main__":
    # 1) 단일점 설계 + 증명
    print("▶ 단일점 LQR (alt=15000ft, vc=350kts)")
    pt = LQRPoint(15_000.0, 350.0)
    print_stability_proof(pt)

    # 2) 간단한 step 응답 시뮬 (scipy ODE, plant 없이 선형 모델로)
    from scipy.integrate import solve_ivp
    x0 = pt.x0.copy()
    # setpoint: heading +20deg, 나머지 trim
    x_star = x0.copy()
    ip = STATE_ORDER.index("psi")
    x_star[ip] = x0[ip] + np.radians(20.0)

    def cl_dynamics(t, x):
        u = pt.command(x, x_star)
        return pt.A @ (x - x0) + pt.B @ (u - pt.u0)

    sol = solve_ivp(cl_dynamics, [0, 30], x0, max_step=0.1, dense_output=True)
    t_eval = np.arange(0, 30, 0.5)
    X = sol.sol(t_eval)
    psi_err = np.degrees(X[ip] - x_star[ip])
    print(f"\n▶ heading step +20° 응답 (선형 모델 시뮬)")
    print(f"  t=0s  err={psi_err[0]:+.1f}°")
    print(f"  t=5s  err={psi_err[t_eval.tolist().index(min(t_eval, key=lambda t: abs(t-5.0)))]:+.1f}°")
    print(f"  t=15s err={psi_err[t_eval.tolist().index(min(t_eval, key=lambda t: abs(t-15.0)))]:+.1f}°")
    print(f"  t=30s err={psi_err[-1]:+.1f}°")

    # 3) gain-scheduled 빌드 (3×3)
    print("\n▶ Gain-Scheduled LQR 빌드 (3 alt × 3 vc = 9점)")
    gs = GainScheduledLQR(
        alts_ft=[5_000.0, 15_000.0, 25_000.0],
        vcs_kts=[250.0,   350.0,    450.0],
    ).build()
