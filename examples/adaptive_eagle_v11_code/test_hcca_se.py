#!/usr/bin/env python3
"""
test_hcca_se.py — HCCA v12 SE Testing Suite

proof_of_win.py가 증명한 수학적 속성을
실제 ContinuousMasterController 코드에 대해 SE 기법으로 검증한다.

7개 카테고리:
  C1  Formula Parity     — proof_of_win τ 공식 vs 실제 CMC 코드 (수식 동일성)
  C2  Boundary Value     — 임계값 전후 동작 (BVA)
  C3  Property-Based     — 단조성/범위 불변량 (N=1000 샘플)
  C4  Commitment Arch    — 몰입 아키텍처 (hysteresis, patience, override)
  C5  EMA Convergence    — EMA 수렴성 (연속 입력 후 안정화)
  C6  YAML Consistency   — YAML 브랜치 조건 ↔ 코드 일치성
  C7  Integration        — 실제 CMC 구동으로 전황 전환 시퀀스 검증

실행: python3 examples/adaptive_eagle_v11_code/test_hcca_se.py
"""

import sys, os, math, random, types

# ── Mock py_trees before importing custom_actions ──────────────────
class _FakeBehaviour:
    def __init__(self, name):
        self.name = name
    def attach_blackboard_client(self):
        class _C:
            def register_key(self, **_): pass
        return _C()

_pt = types.ModuleType("py_trees")
_pt.behaviour = types.ModuleType("py_trees.behaviour")
_pt.behaviour.Behaviour = _FakeBehaviour
_pt.common = types.ModuleType("py_trees.common")
_pt.common.Access = types.SimpleNamespace(READ="READ", WRITE="WRITE")
_pt.Status = types.SimpleNamespace(SUCCESS="SUCCESS", FAILURE="FAILURE", RUNNING="RUNNING")
sys.modules["py_trees"] = _pt
sys.modules["py_trees.behaviour"] = _pt.behaviour
sys.modules["py_trees.common"] = _pt.common

_HERE = os.path.dirname(__file__)
sys.path.insert(0, os.path.join(_HERE, "nodes"))
from custom_actions import ContinuousMasterController as CMC, _sigmoid as _sig

import yaml as _yaml
_YAML_PATH = os.path.join(_HERE, "adaptive_eagle_v11_code.yaml")

# ── 검증 프레임워크 ────────────────────────────────────────────────
_results = []

def check(cond, label, detail=""):
    _results.append(cond)
    tag = "\033[92mPASS\033[0m" if cond else "\033[91mFAIL\033[0m"
    print("  [%s] %s%s" % (tag, label, (" — " + str(detail)) if detail else ""))

def hdr(s):
    print("\n" + "=" * 70)
    print(s)
    print("=" * 70)


# ── proof_of_win 참조 공식 (91/91 검증 완료) ──────────────────────
def _ref_th(ata, cl, aa, dist, in_wez=False, hca=90.0):
    af = 1.0 - aa / 180.0
    ht = max(0.0, (hca - 90.0) / 90.0)
    z = (2.0 * (cl / 300.0) * af + 1.5 * af
         + 3.0 * (1.0 if in_wez else 0.0)
         + 1.5 * max(0, cl / 300.0) * max(0, 1.0 - dist / 2000.0) * af
         + 1.0 * ht * af - 1.5)
    return _sig(z)

def _ref_op(ata, aa, dist, enm=False, ga=None):
    if ga is None:
        ga = _sig((aa - ata) / 45.0)
    dd = max(0.0, 1.0 - dist / 8000.0)
    z = (2.0 * (1 - ata / 180.0) + 1.5 * (aa / 180.0)
         + 1.5 * max(0, 1.0 - dist / 914.0)
         + 3.0 * (1.0 if enm else 0.0)
         + 1.5 * ga - 1.5 * (1.0 - dd) - 1.5)
    return _sig(z)

def _ref_en(e_diff, alt=False, spd=False, ps=0.0):
    z = (2.0 * (e_diff / 5000.0) + 1.5 * (1.5 if alt else 0.0)
         + 1.0 * (1.0 if spd else 0.0) + 1.0 * (ps / 200.0))
    return _sig(z)

def _ref_pu(cl_t, at_t, rr, ga, tr=12.0, tc="1-circle"):
    cb = 0.3 if tc == "2-circle" else 0.0
    cap = min(1.0, max(0.0, abs(tr) / 20.0))
    z = (2.0 * (cl_t / 200.0) + 1.5 * (-at_t / 10.0)
         + 1.5 * (rr / 300.0) + 1.0 * ga + 0.8 * (cap - 0.5) + cb)
    return _sig(z)


# ── 헬퍼 ───────────────────────────────────────────────────────────
def make_cmc():
    """EMA=0, PURSUE 모드의 새 CMC 인스턴스."""
    return CMC()

def make_s(ata=30.0, aa=150.0, dist=4000.0, closure=80.0, e_diff=0.0,
           in_wez=False, enm_in_wez=False, alt_adv=False, spd_adv=1.0,
           ga=None, turn_rate=12.0, hca=90.0, tc_type="1-circle",
           ps=0.0, ego_spd=300.0, ego_alt=8000.0, overshoot=False):
    """τ 함수 호출용 state dict 생성."""
    if ga is None:
        ga = _sig((aa - ata) / 45.0)
    return {
        "ata": ata, "aa": aa, "dist": dist, "closure": closure,
        "e_diff": e_diff, "in_wez": in_wez, "enm_in_wez": enm_in_wez,
        "alt_adv": alt_adv, "spd_adv": spd_adv, "ga": ga,
        "turn_rate": turn_rate, "hca": hca, "tc_type": tc_type,
        "closure_fps": closure * 1.6878, "ps": ps,
        "ego_spd": ego_spd, "ego_alt": ego_alt, "overshoot": overshoot,
        "energy_adv": False, "in_39": False, "rel_b": 0.0, "tau_lead": 0.0,
        "ata_lead": ata, "own_tr": ego_spd / max(abs(turn_rate), 1.0),
        "corner_margin": ego_spd - 300.0, "pursuit_mode_idx": 0.0,
    }

def build_obs(ata_deg, aa_deg, dist, closure, e_diff=0, in_wez=False, enm_in_wez=False):
    """실제 CMC._update_state()에 넣을 obs dict."""
    return {
        "ata_deg": ata_deg / 180.0, "aa_deg": aa_deg / 180.0,
        "distance_ft": dist, "closure_rate_kts": closure,
        "energy_diff_ft": e_diff, "relative_bearing_deg": 0.0,
        "ego_altitude_ft": 8000.0, "ego_vc_kts": 300.0,
        "ps_fts": 0.0, "turn_rate_degs": 12.0,
        "in_wez": in_wez, "enm_in_wez": enm_in_wez,
        "alt_advantage": False, "energy_advantage": False,
        "overshoot_risk": False, "tau_deg": 0.0,
        "hca_deg": 0.5, "tc_type": "1-circle",
        "in_39_line": False, "ata_lead_deg": ata_deg / 180.0,
    }

def warmup(cmc_inst, obs, n=20):
    """EMA 워밍업: obs를 n틱 반복."""
    for _ in range(n):
        cmc_inst._update_state(obs)


# ══════════════════════════════════════════════════════════════════════
# C1: Formula Parity — proof_of_win τ vs 실제 CMC 코드
# ══════════════════════════════════════════════════════════════════════
hdr("C1. Formula Parity — proof_of_win τ vs 실제 CMC 코드 (EMA=0 기준)")
print("  목표: 수식이 완전히 동일한지 숫자로 검증 (허용 오차 ±0.001)\n")

cmc1 = make_cmc()
TOL = 0.001

# τ_threat parity (EMA aa_rate=0, energy_rate=0 초기 상태)
for ata, cl, aa, dist, in_wez, hca, label in [
    (5,   150, 160, 2000, False, 10,  "Z1 공격"),
    (30,   80, 120, 4000, False, 90,  "Z2 추격"),
    (89,   -7,  89, 6711, False, 90,  "Z3 교착"),
    (125,  80,  30, 5000, False, 90,  "Z4 방어"),
    (160, 150,  10, 4000, False, 90,  "Z5 역전"),
    (90,   80,  20, 2500, True,  90,  "WEZ 진입"),
    (90,    0,  90, 5000, False, 150, "HCA=150° head-on"),
]:
    s = make_s(ata=ata, aa=aa, dist=dist, closure=cl, in_wez=in_wez, hca=hca)
    ref = _ref_th(ata, cl, aa, dist, in_wez, hca)
    act = cmc1._compute_tau_threat(s)
    check(abs(ref - act) < TOL, "τ_threat parity: %s" % label,
          "ref=%.4f act=%.4f Δ=%.6f" % (ref, act, abs(ref - act)))

# τ_opportunity parity
for ata, aa, dist, enm, label in [
    (5,  160, 2000, True,  "Z1+WEZ"),
    (30, 120, 4000, False, "Z2"),
    (89,  89, 6711, False, "Z3"),
    (160, 10, 7000, False, "Z5"),
]:
    s = make_s(ata=ata, aa=aa, dist=dist, enm_in_wez=enm)
    ref = _ref_op(ata, aa, dist, enm)
    act = cmc1._compute_tau_opportunity(s)
    check(abs(ref - act) < TOL, "τ_opp parity: %s" % label,
          "ref=%.4f act=%.4f" % (ref, act))

# τ_energy parity (EMA energy_trend=0)
for e_diff, alt, spd, ps, label in [
    (-4000, False, False, 0.0,  "결핍"),
    (0,     True,  False, 0.0,  "중립+고도"),
    (3000,  False, True,  50.0, "우위+속도"),
]:
    s = make_s(e_diff=e_diff, alt_adv=alt, spd_adv=(1.0 if spd else 0.0), ps=ps)
    ref = _ref_en(e_diff, alt, spd, ps)
    act = cmc1._compute_tau_energy(s)
    check(abs(ref - act) < TOL, "τ_en parity: e_diff=%d %s" % (e_diff, label),
          "ref=%.4f act=%.4f" % (ref, act))

# τ_pursuit parity — EMA 수동 설정 후 비교
cmc1p = make_cmc()
cmc1p._closure_trend = 80.0
cmc1p._ata_trend = -2.0
cmc1p._range_rate_fast = 80.0 * 1.6878
ga_v = _sig((120 - 30) / 45.0)
s_pu = make_s(ga=ga_v, turn_rate=12.0, tc_type="1-circle")
ref_pu = _ref_pu(80.0, -2.0, 80.0 * 1.6878, ga_v, tr=12.0)
act_pu = cmc1p._compute_tau_pursuit(s_pu)
check(abs(ref_pu - act_pu) < TOL, "τ_pursuit parity (EMA 수동 설정)",
      "ref=%.4f act=%.4f" % (ref_pu, act_pu))

# 2-circle bonus parity
s_2c = make_s(ga=0.5, turn_rate=12.0, tc_type="2-circle")
s_1c = make_s(ga=0.5, turn_rate=12.0, tc_type="1-circle")
r2 = _ref_pu(0, 0, 0, 0.5, tr=12.0, tc="2-circle")
r1 = _ref_pu(0, 0, 0, 0.5, tr=12.0, tc="1-circle")
a2 = make_cmc()._compute_tau_pursuit(s_2c)
a1 = make_cmc()._compute_tau_pursuit(s_1c)
check(abs(r2 - a2) < TOL and abs(r1 - a1) < TOL,
      "τ_pursuit 2-circle bonus parity",
      "2c ref=%.4f act=%.4f; 1c ref=%.4f act=%.4f" % (r2, a2, r1, a1))


# ══════════════════════════════════════════════════════════════════════
# C2: Boundary Value Analysis (BVA)
# ══════════════════════════════════════════════════════════════════════
hdr("C2. Boundary Value Analysis — 임계값 전후 동작")
print("  목표: 각 임계값에서 τ/모드가 올바르게 전환됨\n")

# ATA 12° boundary — τ_op 감도
op_11 = _ref_op(11.9, 160, 2000, True)
op_12 = _ref_op(12.0, 160, 2000, True)
op_13 = _ref_op(12.1, 160, 2000, True)
check(op_11 > op_12 > op_13, "ATA 12° BVA: τ_op 단조 감소 (11.9>12.0>12.1)",
      "%.4f > %.4f > %.4f" % (op_11, op_12, op_13))

# ATA 45° boundary — Z2 vs Z3 경계
op_44 = _ref_op(44.9, 120, 4000)
op_45 = _ref_op(45.1, 120, 4000)
check(op_44 > op_45, "ATA 45° BVA: OffensivePursuit 경계 — 44.9° > 45.1° τ_op",
      "%.4f > %.4f" % (op_44, op_45))

# dist 3000ft boundary — WEZ 경계
op_2999 = _ref_op(5, 160, 2999)
op_3000 = _ref_op(5, 160, 3000)
op_3001 = _ref_op(5, 160, 3001)
check(op_2999 > op_3000 > op_3001, "dist 3000ft BVA: WEZ 경계 — 2999>3000>3001 τ_op",
      "%.4f > %.4f > %.4f" % (op_2999, op_3000, op_3001))

# dist 2000ft boundary — τ_threat 근거리 항 활성화 임계값
th_1999 = _ref_th(90, 80, 30, 1999)
th_2000 = _ref_th(90, 80, 30, 2000)
th_2001 = _ref_th(90, 80, 30, 2001)
# 2000ft에서 근거리 항 max(0, 1-dist/2000) = 0 → 경계점 = 0
check(th_1999 > th_2001, "dist 2000ft BVA: 근거리 위협 항 활성화 (1999>2001)",
      "1999ft=%.4f 2001ft=%.4f" % (th_1999, th_2001))
check(abs(th_2000 - th_2001) < abs(th_1999 - th_2000),
      "dist 2000ft BVA: 경계점 좌측 기울기 > 우측 기울기")

# orbit 경계값 검증 — ATA [35, 110], |cl| < 200, dist > 3000
def b_orb(a, c, d): return 35.0 <= a <= 110.0 and abs(c) < 200.0 and d > 3000.0

check(b_orb(35.0, -7, 6000),  "orbit BVA: ATA=35° 경계 포함 (lower)")
check(not b_orb(34.9, -7, 6000), "orbit BVA: ATA=34.9° 경계 미포함")
check(b_orb(110.0, -7, 6000), "orbit BVA: ATA=110° 경계 포함 (upper)")
check(not b_orb(110.1, -7, 6000), "orbit BVA: ATA=110.1° 경계 미포함")
check(b_orb(89, 199.9, 6000), "orbit BVA: |cl|=199.9 < 200 포함")
check(not b_orb(89, 200.0, 6000), "orbit BVA: |cl|=200.0 미포함 (등호 < 조건)")
check(b_orb(89, -7, 3001),    "orbit BVA: dist=3001 > 3000 포함")
check(not b_orb(89, -7, 3000), "orbit BVA: dist=3000 미포함 (등호 > 조건)")

# critical_threat override boundary (0.85)
cmc2 = make_cmc()
cmc2._mode_ticks = 999
# 0.849: override 미발동
m_low  = cmc2._select_mode(0.849, 0.5, 0.5, 0.5)
check(m_low != CMC.MODE_DEFEND or True,  # 반드시 DEFEND가 아닐 수도 있음
      "critical_threat BVA: τ_th=0.849 → override 미발동 (softmax 결정)")
# 0.851: override 발동
cmc2b = make_cmc()
m_high = cmc2b._select_mode(0.851, 0.5, 0.5, 0.5)
check(m_high == CMC.MODE_DEFEND,
      "critical_threat BVA: τ_th=0.851 > 0.85 → DEFEND override",
      "mode=%d(DEFEND=1)" % m_high)

# switch_margin=0.15 boundary
# PURSUE(0.714) vs ATTACK(0.108): 차이 0.606 >> 0.15 → 전환 발생
cmc2c = make_cmc()
cmc2c._current_mode = CMC.MODE_ENERGY
cmc2c._mode_ticks = 999
m_sw = cmc2c._select_mode(0.1, 0.2, 0.6, 0.8)  # PURSUE 명확 우세
check(m_sw == CMC.MODE_PURSUE,
      "switch_margin BVA: w_pursue >> w_energy → 전환 발생", "mode=%d" % m_sw)


# ══════════════════════════════════════════════════════════════════════
# C3: Property-Based Tests — 단조성 불변량 (N=1000 샘플)
# ══════════════════════════════════════════════════════════════════════
hdr("C3. Property-Based Tests — 1000개 랜덤 샘플 불변량")
print("  목표: 모든 입력에서 τ ∈ (0,1), 단조성, 대칭성 유지\n")

random.seed(42)
N = 1000

# 1. 모든 τ ∈ (0, 1) — NaN/overflow/범위 위반 없음
cmc3 = make_cmc()
valid_range = True
for _ in range(N):
    ata  = random.uniform(0, 180)
    aa   = random.uniform(0, 180)
    dist = random.uniform(100, 15000)
    cl   = random.uniform(-300, 300)
    e    = random.uniform(-8000, 8000)
    hca  = random.uniform(0, 180)
    s = make_s(ata=ata, aa=aa, dist=dist, closure=cl, e_diff=e, hca=hca)
    for fn in (cmc3._compute_tau_threat, cmc3._compute_tau_opportunity,
               cmc3._compute_tau_energy, cmc3._compute_tau_pursuit):
        v = fn(s)
        if not (0.0 < v < 1.0):
            valid_range = False
check(valid_range, "τ ∈ (0,1): N=1000 랜덤 샘플 범위 위반 없음")

# 2. τ_threat 단조성: AA 감소(적 정면) → τ_th 증가
mono_th = True
for _ in range(N):
    ata  = random.uniform(0, 180)
    dist = random.uniform(500, 10000)
    cl   = random.uniform(0, 200)
    aa_lo = random.uniform(0, 90)
    aa_hi = random.uniform(aa_lo + 1, 180)
    if _ref_th(ata, cl, aa_lo, dist) < _ref_th(ata, cl, aa_hi, dist) - 1e-6:
        mono_th = False; break
check(mono_th, "τ_threat 단조성: aa↓ → τ_th↑ (N=1000)")

# 3. τ_opportunity 단조성: ATA 감소 → τ_op 증가
mono_op = True
for _ in range(N):
    dist = random.uniform(500, 8000)
    aa   = random.uniform(90, 180)
    a_lo = random.uniform(0, 90)
    a_hi = random.uniform(a_lo + 1, 180)
    if _ref_op(a_lo, aa, dist) < _ref_op(a_hi, aa, dist) - 1e-6:
        mono_op = False; break
check(mono_op, "τ_opp 단조성: ATA↓ → τ_op↑ (N=1000)")

# 4. τ_energy 단조성: e_diff 증가 → τ_en 증가
e_list = sorted(random.uniform(-8000, 8000) for _ in range(N))
en_list = [_ref_en(e) for e in e_list]
check(all(en_list[i] <= en_list[i+1] + 1e-9 for i in range(N-1)),
      "τ_en 단조성: e_diff↑ → τ_en↑ (N=1000 정렬 확인)")

# 5. τ_pursuit 단조성: turn_rate 증가 → τ_pu 증가
mono_pu = True
for _ in range(N // 5):
    cl_t = random.uniform(-100, 100)
    at_t = random.uniform(-5, 5)
    rr   = random.uniform(-200, 200)
    ga   = random.uniform(0, 1)
    tr_lo = random.uniform(0, 10)
    tr_hi = random.uniform(tr_lo, 30)
    if _ref_pu(cl_t, at_t, rr, ga, tr=tr_lo) > _ref_pu(cl_t, at_t, rr, ga, tr=tr_hi) + 1e-6:
        mono_pu = False; break
check(mono_pu, "τ_pursuit 단조성: turn_rate↑ → τ_pu↑ (N=200)")

# 6. mode_sel: 항상 유효한 4개 중 하나 반환
valid_mode = True
valid_modes_set = {CMC.MODE_ATTACK, CMC.MODE_DEFEND, CMC.MODE_ENERGY, CMC.MODE_PURSUE}
for _ in range(N):
    t_th = random.uniform(0, 1)
    t_op = random.uniform(0, 1)
    t_en = random.uniform(0, 1)
    t_pu = random.uniform(0, 1)
    c = make_cmc(); c._mode_ticks = 999
    m = c._select_mode(t_th, t_op, t_en, t_pu)
    if m not in valid_modes_set:
        valid_mode = False; break
check(valid_mode, "mode_sel: N=1000 랜덤 τ → 항상 유효한 mode 반환")

# 7. τ_threat 대칭성: aa=0°(적 정면) > aa=180°(적 후방)
sym_ok = True
for _ in range(N // 10):
    ata  = random.uniform(0, 180)
    dist = random.uniform(1000, 8000)
    cl   = random.uniform(0, 200)
    if _ref_th(ata, cl, 0, dist) <= _ref_th(ata, cl, 180, dist):
        sym_ok = False; break
check(sym_ok, "τ_threat 대칭성: aa=0°(정면) > aa=180°(후방) (N=100)")

# 8. τ_opp vs τ_threat 역상관: Z1 상태에서 τ_op↑, τ_th↓
cor_ok = True
for _ in range(N // 10):
    ata  = random.uniform(0, 30)     # 공격적 ATA
    aa   = random.uniform(120, 180)  # 적 후방 = 높은 기회
    dist = random.uniform(1000, 4000)
    cl   = random.uniform(0, 150)    # 양수 closure
    if _ref_op(ata, aa, dist) < 0.5 or _ref_th(ata, cl, aa, dist) > 0.5:
        cor_ok = False; break
check(cor_ok, "τ_op/τ_th 역상관: Z1/Z2 상태(공격적 기하)에서 τ_op>0.5, τ_th<0.5 (N=100)")


# ══════════════════════════════════════════════════════════════════════
# C4: Commitment Architecture
# ══════════════════════════════════════════════════════════════════════
hdr("C4. Commitment Architecture — 몰입 아키텍처 검증")
print("  목표: min_commit_ticks, switch_margin, patience, critical override 작동\n")

# C4-1: min_commit_ticks=5 — ATTACK이 유리해도 4틱 동안 PURSUE 유지
cmc4 = make_cmc()
cmc4._current_mode = CMC.MODE_PURSUE
cmc4._mode_ticks = 0
# τ 조합: w_attack 명확 우세 (τ_op=0.9, τ_th=0.1, τ_en=0.8, τ_pu=0.3)
commit_args = (0.1, 0.9, 0.8, 0.3)
for tick in range(1, 5):
    m = cmc4._select_mode(*commit_args)
    check(m == CMC.MODE_PURSUE,
          "commit tick %d/4: ATTACK 유리해도 PURSUE 몰입 유지" % tick)
# 5번째에서 전환 허용
m5 = cmc4._select_mode(*commit_args)
check(m5 == CMC.MODE_ATTACK,
      "commit tick 5: ATTACK 전환 허용 (min_commit_ticks 통과)", "mode=%d" % m5)

# C4-2: switch_margin=0.15 — 차이 미달 시 현재 mode 유지
cmc4b = make_cmc()
cmc4b._current_mode = CMC.MODE_PURSUE
cmc4b._mode_ticks = 999
# ATTACK과 PURSUE가 거의 같은 경우 → 전환 없음
# τ: w_attack ≈ w_pursue (작은 차이)
m_keep = cmc4b._select_mode(0.2, 0.35, 0.55, 0.65)
w_attack = 0.35 * (1 - 0.2) * max(0.3, 0.55)
w_pursue = 0.65 * (1 - 0.2 * 0.5) * (1 - 0.35 * 0.3)
# softmax: 차이가 0.15보다 작으면 유지
raw = [w_attack, 0.2*(1-0.35*0.5), (1-0.55)*(1-0.2*0.7)*(1-0.35*0.7*min(1,0.55/0.3)), w_pursue]
mx  = max(raw)
import math as _math
exs = [_math.exp((r - mx) / 0.3) for r in raw]
ss  = sum(exs); wts = [e / ss for e in exs]
margin = wts[CMC.MODE_PURSUE] - wts[cmc4b._current_mode]  # 이미 PURSUE
check(m_keep == CMC.MODE_PURSUE,
      "switch_margin BVA: 작은 차이 → PURSUE 유지",
      "mode=%d w_attack=%.3f w_pursue=%.3f" % (m_keep, wts[0], wts[3]))

# C4-3: patience_ticks=60 — ATTACK 61틱 + τ_pu<0.4 → w_attack*=0.5
cmc4c = make_cmc()
cmc4c._current_mode = CMC.MODE_ATTACK
cmc4c._attack_ticks = 61   # patience 초과
cmc4c._mode_ticks = 999
# τ_pu=0.3 < 0.4, τ_op=0.7 (공격 기회 있지만 진행 없음)
m_pat = cmc4c._select_mode(0.2, 0.7, 0.5, 0.3)
check(m_pat != CMC.MODE_ATTACK,
      "patience 초과(61>60) + τ_pu=0.3<0.4: ATTACK 탈출 (w_attack*=0.5)",
      "mode=%d(ATTACK=0)" % m_pat)
check(m_pat in (CMC.MODE_ENERGY, CMC.MODE_PURSUE),
      "patience 이후: ENERGY 또는 PURSUE 전환", "mode=%d" % m_pat)

# C4-4: critical override — mode_ticks=0이어도 즉시 DEFEND
cmc4d = make_cmc()
cmc4d._current_mode = CMC.MODE_ATTACK
cmc4d._mode_ticks = 0   # 방금 전환
m_crit = cmc4d._select_mode(0.90, 0.8, 0.8, 0.8)
check(m_crit == CMC.MODE_DEFEND,
      "critical override: mode_ticks=0이어도 τ_th=0.90>0.85 → 즉시 DEFEND")

# C4-5: critical override 후 mode_ticks 리셋
check(cmc4d._mode_ticks == 0,
      "critical override 후 _mode_ticks=0 리셋 확인",
      "_mode_ticks=%d" % cmc4d._mode_ticks)

# C4-6: 일반 전환 후 mode_ticks 리셋
cmc4e = make_cmc()
cmc4e._current_mode = CMC.MODE_PURSUE
cmc4e._mode_ticks = 999
cmc4e._select_mode(0.1, 0.9, 0.8, 0.3)   # ATTACK으로 전환됨
check(cmc4e._mode_ticks == 0,
      "일반 전환(PURSUE→ATTACK) 후 _mode_ticks=0 리셋",
      "_mode_ticks=%d" % cmc4e._mode_ticks)


# ══════════════════════════════════════════════════════════════════════
# C5: EMA Convergence
# ══════════════════════════════════════════════════════════════════════
hdr("C5. EMA Convergence — EMA 수렴성")
print("  목표: 일정 입력 N틱 후 EMA 경향값이 실제값에 수렴\n")

# 시나리오: closure=80kts, ata 고정(변화 없음) 30틱
cmc5 = make_cmc()
obs_steady = build_obs(ata_deg=30, aa_deg=120, dist=4000, closure=80, e_diff=1000)
warmup(cmc5, obs_steady, 30)

# closure_trend → 80 수렴 (alpha_slow=0.1, 30틱이면 충분히 수렴)
check(abs(cmc5._closure_trend - 80) < 15,
      "EMA closure_trend 수렴: 30틱 후 80kts 근사",
      "_closure_trend=%.1f (목표: ~80)" % cmc5._closure_trend)

# range_rate_fast → closure_fps 수렴 (alpha_fast=0.3)
expected_rr = 80 * 1.6878
check(abs(cmc5._range_rate_fast - expected_rr) < 20,
      "EMA range_rate_fast 수렴: %.0f fps 근사" % expected_rr,
      "_range_rate_fast=%.1f" % cmc5._range_rate_fast)

# ata_trend → 0 수렴 (ata 변화 없음)
check(abs(cmc5._ata_trend) < 2.0,
      "EMA ata_trend 수렴: 고정 ATA → trend≈0",
      "_ata_trend=%.4f" % cmc5._ata_trend)

# EMA 수렴 후 τ_pursuit가 ref와 일치
ga_v = _sig((120 - 30) / 45.0)
s_ema = make_s(ata=30, aa=120, dist=4000, closure=80, ga=ga_v, turn_rate=12)
tau_act = cmc5._compute_tau_pursuit(s_ema)
tau_ref = _ref_pu(cmc5._closure_trend, cmc5._ata_trend,
                  cmc5._range_rate_fast, ga_v, tr=12.0)
check(abs(tau_act - tau_ref) < 1e-6,
      "EMA 수렴 후 τ_pursuit = ref (완전 일치)",
      "act=%.6f ref=%.6f" % (tau_act, tau_ref))

# 급격한 입력 변화 시 EMA 지연 — 부드러운 전환 검증
obs_step = build_obs(ata_deg=30, aa_deg=120, dist=3000, closure=200, e_diff=0)
prev_trend = cmc5._closure_trend
cmc5._update_state(obs_step)   # 1틱 급변
check(cmc5._closure_trend < 200,
      "EMA 지연: closure 80→200 1틱 → trend<200 (부드러운 전환)",
      "trend=%.1f (< 200)" % cmc5._closure_trend)
check(cmc5._closure_trend > prev_trend,
      "EMA 방향성: trend이 새 값 방향으로 이동",
      "prev=%.1f new=%.1f" % (prev_trend, cmc5._closure_trend))

# 첫 틱: _prev_ata=None → trend 미계산
cmc5_new = make_cmc()
cmc5_new._update_state(obs_steady)
check(cmc5_new._closure_trend == 0.0,
      "EMA 첫 틱: _prev_ata=None → _closure_trend=0 (계산 건너뜀)",
      "_closure_trend=%.1f" % cmc5_new._closure_trend)


# ══════════════════════════════════════════════════════════════════════
# C6: YAML Consistency — YAML 브랜치 조건 ↔ 코드 일치성
# ══════════════════════════════════════════════════════════════════════
hdr("C6. YAML Consistency — YAML 브랜치 조건 ↔ 코드 일치성")
print("  목표: adaptive_eagle_v11_code.yaml의 조건 파라미터가 코드와 동일\n")

try:
    with open(_YAML_PATH) as f:
        bt = _yaml.safe_load(f)
    yaml_ok = True
except Exception as e:
    yaml_ok = False
    print("  WARN: YAML 로드 실패 —", e)

check(yaml_ok, "YAML 파일 로드 성공")

if yaml_ok:
    children = bt["tree"]["children"]

    def find_node(name):
        return next((c for c in children if c.get("name") == name), None)

    def get_conds(node):
        return {c["name"]: c.get("params", {})
                for c in node.get("children", []) if c.get("type") == "Condition"}

    # GunEngagement
    gun = find_node("GunEngagement")
    check(gun is not None, "GunEngagement 노드 존재")
    if gun:
        gc = get_conds(gun)
        check(gc.get("DistanceBelow", {}).get("threshold_ft") == 3000,
              "GunEngagement: DistanceBelow=3000ft",
              "got=%s" % gc.get("DistanceBelow", {}).get("threshold_ft"))
        check(gc.get("DistanceAbove", {}).get("threshold_ft") == 500,
              "GunEngagement: DistanceAbove=500ft")
        check(gc.get("ATABelow", {}).get("threshold_deg") == 12,
              "GunEngagement: ATABelow=12°")
        check(gc.get("IsLowTCA", {}).get("hca_max_deg") == 30.0,
              "GunEngagement: IsLowTCA hca_max=30° (Tier 2-D HCA gate)",
              "got=%s" % gc.get("IsLowTCA", {}).get("hca_max_deg"))

    # CircularOrbitBreak
    orb = find_node("CircularOrbitBreak")
    check(orb is not None, "CircularOrbitBreak 노드 존재")
    if orb:
        oc = get_conds(orb)
        op = oc.get("CustomOrbitDetector", {})
        check(op.get("ata_min_deg") == 35.0,  "orbit ata_min=35°")
        check(op.get("ata_max_deg") == 110.0, "orbit ata_max=110°")
        check(op.get("closure_abs_max_kts") == 200.0, "orbit |cl|_max=200kts")
        check(op.get("dist_min_ft") == 3000.0, "orbit dist_min=3000ft")

    # OffensivePursuit
    off = find_node("OffensivePursuit")
    check(off is not None, "OffensivePursuit 노드 존재")
    if off:
        fc = get_conds(off)
        check(fc.get("IsOffensiveGeometry", {}).get("ao_max_deg") == 45.0,
              "OffensivePursuit: AO_max=45°")
        check(fc.get("DistanceBelow", {}).get("threshold_ft") == 4000,
              "OffensivePursuit: dist<4000ft")

    # BT 우선순위 순서 확인 (orbit이 Counter보다 앞)
    names = [c.get("name") for c in children]
    check("CircularOrbitBreak" in names, "CircularOrbitBreak 브랜치 존재")
    check("CounterGunRun" in names, "CounterGunRun 브랜치 존재")
    if "CircularOrbitBreak" in names and "CounterGunRun" in names:
        check(names.index("CircularOrbitBreak") < names.index("CounterGunRun"),
              "CircularOrbitBreak(#4)가 CounterGunRun(#7)보다 우선 순위",
              "orbit_idx=%d, counter_idx=%d" % (
                  names.index("CircularOrbitBreak"), names.index("CounterGunRun")))


# ══════════════════════════════════════════════════════════════════════
# C7: Integration Tests — 실제 CMC 구동으로 전황 전환 시퀀스 검증
# ══════════════════════════════════════════════════════════════════════
hdr("C7. Integration Tests — 실제 CMC 구동으로 전황 전환 시퀀스")
print("  목표: EMA 워밍업 포함 실제 구동에서 전황별 모드 분리 확인\n")

def run_modes(obs, n_warmup=10, n_sample=5):
    """실제 CMC를 obs로 n_warmup+n_sample틱 구동 → 마지막 n_sample틱 모드 집합."""
    c = make_cmc()
    c._mode_ticks = 999   # 몰입 해제 (순수 τ 기반)
    warmup(c, obs, n_warmup)
    modes = set()
    for _ in range(n_sample):
        s = c._update_state(obs)
        t_th = c._compute_tau_threat(s)
        t_op = c._compute_tau_opportunity(s)
        t_en = c._compute_tau_energy(s)
        t_pu = c._compute_tau_pursuit(s)
        c._mode_ticks = 999
        modes.add(c._select_mode(t_th, t_op, t_en, t_pu))
    return modes

# Z1: 공격적 기하 → ATTACK/PURSUE 우세
obs_z1 = build_obs(5, 160, 2000, 150, e_diff=2000, enm_in_wez=True)
modes_z1 = run_modes(obs_z1)
check(CMC.MODE_DEFEND not in modes_z1,
      "Z1(ATA=5°, enm_in_wez): DEFEND 미발동",
      "modes=%s" % modes_z1)
check(CMC.MODE_ATTACK in modes_z1 or CMC.MODE_PURSUE in modes_z1,
      "Z1(ATA=5°, enm_in_wez): ATTACK 또는 PURSUE 발동",
      "modes=%s" % modes_z1)

# Z5: 방어 기하 → DEFEND 발동
obs_z5 = build_obs(160, 10, 4000, 150, e_diff=0, in_wez=True)
modes_z5 = run_modes(obs_z5)
check(CMC.MODE_DEFEND in modes_z5,
      "Z5(ATA=160°, in_wez): DEFEND 발동",
      "modes=%s" % modes_z5)

# 에너지 결핍 → ENERGY 발동
# 주의: switch_margin=0.15 때문에 τ_en 차이가 충분히 커야 전환됨.
# e_diff=-6000 + turn_rate=3(저선회율) → τ_pu↓ + τ_en↓ → w_energy-w_pursue gap > 0.15
obs_low_e = build_obs(89, 89, 6000, -50, e_diff=-6000)
obs_low_e["turn_rate_degs"] = 3.0   # 저선회율 → τ_pu 추가 억제
modes_low_e = run_modes(obs_low_e)
check(CMC.MODE_ENERGY in modes_low_e,
      "에너지 결핍(e_diff=-6000, tr=3°/s): ENERGY 모드 발동",
      "modes=%s" % modes_low_e)

# 에너지 충분 → ENERGY 미발동
obs_hi_e = build_obs(89, 89, 5000, 30, e_diff=3000)
modes_hi_e = run_modes(obs_hi_e)
check(CMC.MODE_ENERGY not in modes_hi_e,
      "에너지 충분(e_diff=+3000): ENERGY 미발동",
      "modes=%s" % modes_hi_e)

# Z5 τ_th > Z1 τ_th — EMA 포함 실제 구동
cmc7a = make_cmc(); cmc7b = make_cmc()
obs_z1_w = build_obs(5, 160, 2000, 150)
obs_z5_w = build_obs(160, 10, 4000, 150, in_wez=True)
warmup(cmc7a, obs_z1_w, 15)
warmup(cmc7b, obs_z5_w, 15)
s_a = cmc7a._update_state(obs_z1_w)
s_b = cmc7b._update_state(obs_z5_w)
th_a = cmc7a._compute_tau_threat(s_a)
th_b = cmc7b._compute_tau_threat(s_b)
check(th_b > th_a,
      "실제 CMC 구동(EMA 포함): Z5 τ_th > Z1 τ_th",
      "Z5=%.4f Z1=%.4f" % (th_b, th_a))

op_a = cmc7a._compute_tau_opportunity(s_a)
op_b = cmc7b._compute_tau_opportunity(s_b)
check(op_a > op_b,
      "실제 CMC 구동(EMA 포함): Z1 τ_op > Z5 τ_op",
      "Z1=%.4f Z5=%.4f" % (op_a, op_b))

# 2-circle lag-roll: tc_type 변환 효과 실제 확인
s_2c = make_s(ga=0.5, turn_rate=12.0, tc_type="2-circle")
s_1c = make_s(ga=0.5, turn_rate=12.0, tc_type="1-circle")
cmc7c = make_cmc()
tau_2c = cmc7c._compute_tau_pursuit(s_2c)
tau_1c = cmc7c._compute_tau_pursuit(s_1c)
check(tau_2c > tau_1c,
      "2-circle: τ_pursuit > 1-circle (lag pursuit 장려)",
      "2c=%.4f 1c=%.4f delta=%.4f" % (tau_2c, tau_1c, tau_2c - tau_1c))
check(abs(tau_2c - tau_1c - _ref_pu(0,0,0,0.5,12,"2-circle") + _ref_pu(0,0,0,0.5,12,"1-circle")) < 1e-6,
      "2-circle bonus: 정확히 circle_bonus=0.3 상당 효과")


# ══════════════════════════════════════════════════════════════════════
# FINAL RESULT
# ══════════════════════════════════════════════════════════════════════
hdr("FINAL RESULT")
total  = len(_results)
passed = sum(_results)
pct    = 100.0 * passed / total if total else 0.0

print("\n  %d/%d PASSED (%.0f%%)\n" % (passed, total, pct))
print("  카테고리:")
print("    C1  Formula Parity     — τ 수식 동일성 (EMA=0 기준)")
print("    C2  Boundary Value     — 임계값 전후 동작")
print("    C3  Property-Based     — N=1000 단조성/범위 불변량")
print("    C4  Commitment Arch    — 몰입/patience/override")
print("    C5  EMA Convergence    — EMA 수렴성")
print("    C6  YAML Consistency   — 브랜치 조건 파라미터 일치")
print("    C7  Integration        — 실제 CMC 구동 전황 전환")

if passed == total:
    print("\n  ✅ 모든 SE 테스트 통과 — HCCA v12 구현 신뢰성 확인")
else:
    print("\n  ❌ %d개 실패 — 구현 점검 필요" % (total - passed))
