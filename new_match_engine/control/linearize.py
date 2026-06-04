"""운영점 선형화 — JSBSim F-16 [native FLCS + 기체] 의 (A, B) 유한차분 추출.

방법 (IC-섭동 중앙차분):
  1. 운영점에서 trim → x0, u0.
  2. f(x,u) = xdot 를 "IC로 상태 세팅 → 입력 고정 → 1 tick → (x_next−x)/dt" 로 근사.
  3. A[:,j] = (f(x0+δ e_j, u0) − f(x0−δ e_j, u0)) / 2δ   (상태 섭동)
     B[:,j] = (f(x0, u0+δ e_j) − f(x0, u0−δ e_j)) / 2δ   (입력 섭동)

검증: A 의 종/횡 부블록 고유값이 F-16 고전 모드와 일치하는가.
"""
from __future__ import annotations
import numpy as np
from plant import (F16Plant, STATE_ORDER, INPUT_ORDER)

# 상태를 IC property 로 되돌려 세팅 (섭동된 x 를 JSBSim 에 주입)
IC_FROM_STATE = {
    "V":     ("ic/vt-fps",      1.0,            None),
    "alpha": ("ic/alpha-deg",   np.degrees(1),  None),
    "theta": ("ic/theta-deg",   np.degrees(1),  None),
    "q":     ("ic/q-rad_sec",   1.0,            None),
    "beta":  ("ic/beta-deg",    np.degrees(1),  None),
    "phi":   ("ic/phi-deg",     np.degrees(1),  None),
    "p":     ("ic/p-rad_sec",   1.0,            None),
    "r":     ("ic/r-rad_sec",   1.0,            None),
    "h":     ("ic/h-sl-ft",     1.0,            None),
    "psi":   ("ic/psi-true-deg", np.degrees(1), None),
}
N = len(STATE_ORDER)      # 10
M = len(INPUT_ORDER)      # 4

# 섭동 크기 (상태/입력)
DX = {"V": 1.0, "alpha": np.radians(0.5), "theta": np.radians(0.5), "q": 0.01,
      "beta": np.radians(0.5), "phi": np.radians(0.5), "p": 0.01, "r": 0.01,
      "h": 10.0, "psi": np.radians(0.5)}
DU = 0.01


def _set_state_ic(p: F16Plant, x: np.ndarray):
    """상태 벡터 x 를 JSBSim IC 로 주입하고 run_ic."""
    f = p.fdm
    for k, val in zip(STATE_ORDER, x):
        prop, scale, _ = IC_FROM_STATE[k]
        # rad 상태는 deg IC 로 변환
        if "deg" in prop:
            f[prop] = float(np.degrees(val))
        else:
            f[prop] = float(val)
    f.run_ic()


def _xdot(p: F16Plant, x: np.ndarray, u: np.ndarray, n_steps: int = 10) -> np.ndarray:
    """f(x,u) ≈ (x_next − x)/(n_steps*dt) : IC 주입 → 입력 고정 → n_steps tick.

    n_steps > 1 이유:
      F-16 native FLCS에 kinematic(rate-limited) actuator가 있어 1 tick에서는
      표면 이동이 거의 없고 FCS transient만 잡힘 → B 행렬 부호 역전 버그.
      n_steps=10(≈83ms)로 actuator transient 통과 후 공력 응답을 포착.
      참조: Linearization of nonlinear FCS — Stevens & Lewis §5 numerical 방법.
    """
    _set_state_ic(p, x)
    p.set_input(u)
    dt_total = p.dt * n_steps
    for _ in range(n_steps):
        p.step(1)
    x_next = p.get_state()
    d = (x_next - x) / dt_total
    # psi wrap 보정
    ip = STATE_ORDER.index("psi")
    d[ip] = (((x_next[ip] - x[ip] + np.pi) % (2 * np.pi)) - np.pi) / dt_total
    return d


def linearize(alt_ft: float, vc_kts: float, model: str = "f16"):
    """운영점에서 (A, B, x0, u0) 반환."""
    p = F16Plant(model=model)
    p.set_ic(alt_ft=alt_ft, vc_kts=vc_kts)
    p.trim()
    p.step(1)
    x0 = p.get_state()
    u0 = p.get_input()

    A = np.zeros((N, N))
    for j, k in enumerate(STATE_ORDER):
        d = DX[k]
        xp, xm = x0.copy(), x0.copy()
        xp[j] += d; xm[j] -= d
        A[:, j] = (_xdot(p, xp, u0) - _xdot(p, xm, u0)) / (2 * d)

    B = np.zeros((N, M))
    for j in range(M):
        up, um = u0.copy(), u0.copy()
        up[j] += DU; um[j] -= DU
        B[:, j] = (_xdot(p, x0, up) - _xdot(p, x0, um)) / (2 * DU)

    return A, B, x0, u0


# 종/횡 상태 인덱스 (모드 검증용)
LON_IDX = [STATE_ORDER.index(k) for k in ("V", "alpha", "theta", "q")]
LAT_IDX = [STATE_ORDER.index(k) for k in ("beta", "phi", "p", "r")]


def _modes(A, idx, label):
    sub = A[np.ix_(idx, idx)]
    ev = np.linalg.eigvals(sub)
    print(f"  {label} 고유값:")
    for e in ev:
        if abs(e.imag) > 1e-3:
            wn = abs(e); zeta = -e.real / wn
            print(f"    {e.real:+.4f} {e.imag:+.4f}j   (wn={wn:.3f} rad/s, zeta={zeta:+.3f})")
        else:
            print(f"    {e.real:+.4f}            (real, tau={1/abs(e.real) if abs(e.real)>1e-6 else float('inf'):.2f}s)")


if __name__ == "__main__":
    ALT, VC = 15000.0, 350.0
    print(f"=== 선형화 @ alt={ALT}ft vc={VC}kts ===")
    A, B, x0, u0 = linearize(ALT, VC)
    np.set_printoptions(precision=3, suppress=True, linewidth=160)
    print("x0 =", np.round(x0, 3))
    print("u0 =", np.round(u0, 4))
    print("\n종(longitudinal) [V,alpha,theta,q] / 횡(lat-dir) [beta,phi,p,r] 모드 검증:")
    _modes(A, LON_IDX, "종")
    _modes(A, LAT_IDX, "횡")
