"""new_match_engine 물리·단위 상수 — 단일 진실(single source of truth).

모든 파일은 여기서 import. 중복 정의 금지.

정밀도 기준:
  단위 변환: IEEE 754 double(float64) 기준 최대 유효 자릿수.
  물리 상수: NIST 2018 CODATA 권고값 (항공 표준 ICAO와 동일).

부동소수점 reciprocal 일관성:
  FT_S_TO_KNOT = 1.0 / KNOT_TO_FT_S  ← 반드시 이렇게 정의 (별도 값 금지).
  그래야 kts→fps→kts 왕복 오차가 float64 machine epsilon(~2e-16) 수준.
  (0.592484를 독립 상수로 정의하면 왕복 오차 ~1e-4 발생 — 이전 버그.)
"""

# ── 속도 단위 변환 ─────────────────────────────────────────────────────────
# 1 knot = 1 NM/h = 1852 m/h = 1852/3600 m/s = 1852 * 3.28084 / 3600 ft/s
# ICAO 표준: 1 NM = 1852 m (exact), 1 ft = 0.3048 m (exact)
# → 1 kts = 1852 / 3600 / 0.3048 ft/s = 1852 / (3600 * 0.3048)
# = 1852 / 1097.28 = 1.6878098574...
KNOT_TO_FT_S: float = 1852.0 / (3600.0 * 0.3048)   # = 1.6878098524...  kts → ft/s
FT_S_TO_KNOT: float = 1.0 / KNOT_TO_FT_S             # = 0.5924838...    ft/s → kts
# ★ 위처럼 reciprocal로 정의해야 KNOT_TO_FT_S * FT_S_TO_KNOT = 1.0 (float64 수준)

# ── 거리 단위 변환 ─────────────────────────────────────────────────────────
M_TO_FT: float = 1.0 / 0.3048   # m → ft  (0.3048 exact per ICAO)
FT_TO_M: float = 0.3048          # ft → m

# ── 각도 단위 변환 ─────────────────────────────────────────────────────────
import math as _math
DEG_TO_RAD: float = _math.pi / 180.0
RAD_TO_DEG: float = 180.0 / _math.pi

# ── 물리 상수 ──────────────────────────────────────────────────────────────
G_M_S2:  float = 9.80665         # m/s²   표준중력 (NIST, exact)
G_FT_S2: float = G_M_S2 * M_TO_FT  # ft/s²  = 32.17404856...

# ── 최소 분모 guard (0나눗셈 방지) ────────────────────────────────────────
# 제어 계산 분모에 직접 사용: max(EPS_DENOM, denominator)
EPS_DENOM: float = 1e-6   # 물리량에 비해 무시 가능하나 0나눗셈 방지 충분

# ── F-16 성능 상수 (§10 실측, 변경 시 TACTIC_SPEC.md §7도 갱신) ──────────
# (tactic.py 에도 있음 — tactic.py에서 import, 여기서 중복 정의 안 함)
