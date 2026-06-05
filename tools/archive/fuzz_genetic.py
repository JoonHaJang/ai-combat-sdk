"""GA-style fuzzing — multi-BT × multi-variant × multi-scenario.

Fitness = Σ (dmg vs opp × weight). 큰 모집단 + 반복 generation + best 누적.
멈춤 X — 백그라운드 무한 실행, log per generation.

사용:
    python tools/fuzz_genetic.py --pop 16 --gens 20 --runs 1 --bg
"""
import argparse
import json
import os
import random
import re
import statistics
import subprocess
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SELECTOR = ROOT / "examples/pursuit_chase_v1/nodes/cost_branch_selector.py"
RESULTS_DIR = ROOT / "logs/fuzz_genetic"
RESULTS_DIR.mkdir(parents=True, exist_ok=True)


# Opponents (Round 4 2026-05-28: head-on 강화 + lookup hook 추가 후 검증.
# 사용자 우선: base 4 + 최신 (v10/v11/v51) + 1 hard-counter sample)
OPPONENTS = [
    # 사용자 명령 2026-05-29: 편식 방지 = 모든 opp 가중치 동등 1.0
    # 각 sub-situation 동등 학습 받도록.
    ("simple", 1.0),
    ("defensive", 1.0),
    ("aggressive", 1.0),
    ("ace", 1.0),
    ("adaptive_eagle_v10", 1.0),
    ("adaptive_eagle_v11_code", 1.0),
    ("adaptive_eagle_v51", 1.0),
    ("adaptive_eagle_v6", 1.0),
    ("adaptive_eagle_v6h4", 1.0),
]
SCENARIOS = ["bt_vs_bt", "tail_chase_us_attack", "tail_chase_us_defend"]  # 사용자 명령 2026-05-29: R15 = tail_chase 의 side switch (50/50 follower/leader) 발견 후 분리. cost+action framework 가 두 케이스 독립 학습. bt_vs_bt = neutral merge.
MAX_STEPS = 1500
TIMEOUT = 100


# Tunable knobs — Round 5 (2026-05-28): 상황별 SITMULT 추가 (사용자 명령 "if-then 분기 per situation")
KNOBS = {
    # 기존 LAMBDA (R2 champion 값 baseline)
    "STUCK_THR":            (30, 100, "int"),
    "STUCK_MAX":            (1.0, 4.0, "float"),
    "LAMBDA_D":             (5.0, 30.0, "float"),
    "LAMBDA_OFFENSIVE":     (3.0, 10.0, "float"),
    "LAMBDA_CUTOFF":        (1.0, 5.0, "float"),
    "LAMBDA_BREAK":         (2.0, 10.0, "float"),
    "LAMBDA_HIGHYOYO":      (0.5, 4.0, "float"),
    "LAMBDA_DIVE":          (2.0, 8.0, "float"),
    "LAMBDA_TCV":           (1.0, 6.0, "float"),
    "LAMBDA_EXT":           (1.0, 5.0, "float"),
    # NEW: on_to_on (head-on spawn) 상황 multiplier
    "SITMULT_OTO_GUN":         (0.5, 3.0, "float"),  # 1.5 default
    "SITMULT_OTO_BREAK":       (0.5, 2.5, "float"),  # 1.2
    "SITMULT_OTO_OFFENSIVE":   (0.3, 2.0, "float"),  # 0.8
    "SITMULT_OTO_CUTOFF":      (0.3, 2.0, "float"),  # 0.8
    "SITMULT_OTO_DIVE":        (0.3, 2.0, "float"),  # 0.8
    "SITMULT_OTO_TCV":         (0.3, 2.0, "float"),  # 0.6
    "SITMULT_OTO_EXT":         (0.3, 2.0, "float"),  # 0.7
    # NEW: chase (tail_chase / 가까운 6시) 상황 multiplier
    "SITMULT_CHASE_GUN":       (0.5, 2.5, "float"),  # 1.0
    "SITMULT_CHASE_BREAK":     (0.3, 2.0, "float"),  # 0.9
    "SITMULT_CHASE_OFFENSIVE": (0.5, 3.0, "float"),  # 1.2
    "SITMULT_CHASE_CUTOFF":    (0.5, 3.0, "float"),  # 1.2
    "SITMULT_CHASE_DIVE":      (0.5, 3.0, "float"),  # 1.3
    "SITMULT_CHASE_TCV":       (0.5, 3.0, "float"),  # 1.3
    "SITMULT_CHASE_EXT":       (0.3, 2.0, "float"),  # 1.1
    # v3.30 (사용자 vision 2026-05-28): WEZ-dwell quality (overshoot 방지 = 긴 dmg 기간)
    "WEZ_DWELL_CLOSURE_OPT_KTS": (10.0, 150.0, "float"),  # 50 default
    "WEZ_DWELL_CLOSURE_SIGMA":   (30.0, 200.0, "float"),  # 80
    "WEZ_DWELL_WEIGHT":          (0.0, 6.0, "float"),     # 2.0 (off→strong)
    # v3.31 (T-45A ACMFP-03 doctrine): defensive escape phase weights
    "DEFESC_WEIGHT_SURVIVE":     (3.0, 15.0, "float"),    # 8.0 default
    "DEFESC_WEIGHT_OVERSHOOT":   (2.0, 12.0, "float"),    # 6.0
    "DEFESC_WEIGHT_BUGOUT":      (2.0, 12.0, "float"),    # 5.0
    "DEFESC_WEIGHT_LASTDITCH":   (5.0, 20.0, "float"),    # 10.0
    # v3.32 (AETC TTP 11-1 doctrine): pursuit curve weights
    "PURSUIT_LEAD_WEIGHT":       (0.0, 8.0, "float"),     # 3.0
    "PURSUIT_LAG_WEIGHT":        (0.0, 8.0, "float"),     # 3.0
    "PURSUIT_LAG_CLOSURE_LIMIT_KTS": (100.0, 350.0, "float"),  # 200
    # v3.33 (사용자 명령): 초기 chase 가속
    "INITACC_WEIGHT":            (0.0, 12.0, "float"),    # 5.0
    "INITACC_SPEED_MIN_KTS":     (250.0, 450.0, "float"), # 350
    "INITACC_DIST_MIN_FT":       (2000.0, 7000.0, "float"), # 4000
    # v3.34 (gun fight 자료): tracking vs snapshot 분리
    "GUN_TRACKING_TCA_MAX_DEG":  (20.0, 70.0, "float"),    # 40
    "GUN_SNAPSHOT_TCA_MIN_DEG":  (40.0, 100.0, "float"),   # 60
    "GUN_TRACKING_WEIGHT":       (5.0, 25.0, "float"),     # 12
    "GUN_SNAPSHOT_WEIGHT":       (1.0, 12.0, "float"),     # 6
    # v3.35 (counter-defense 자료): 적 방어 type 카운터
    "COUNTER_BARRELROLL_WEIGHT": (0.0, 10.0, "float"),     # 4
    "COUNTER_LAG_WEIGHT":        (0.0, 8.0, "float"),      # 3
    "COUNTER_PATIENCE_WEIGHT":   (0.0, 8.0, "float"),      # 3
    # v3.36 gap-driven anti-reversal (사용자 명령, v51 케이스)
    "ANTI_REVERSAL_WEIGHT":      (0.0, 10.0, "float"),     # 4
    # v3.37 전종횡 WEZ envelope + Lead TOF (DTIC AD1130933 자료)
    "WEZ_ENVELOPE_WEIGHT":       (0.0, 20.0, "float"),     # 10
    "WEZ_HIGHASPECT_ATA_OPT":    (15.0, 60.0, "float"),    # 30
    "WEZ_HIGHASPECT_TCA_OPT":    (60.0, 130.0, "float"),   # 90
    # v3.38 sub-situation knobs (사용자 vision: per-sub-situation if-then)
    "HOM_GUN_BOOST":             (0.3, 3.0, "float"),
    "HOM_BREAK_BOOST":           (0.3, 3.0, "float"),
    "HOM_CUTOFF_BOOST":          (0.3, 3.0, "float"),
    "HOM_DIVE_BOOST":            (0.3, 3.0, "float"),
    "HOM_EXT_PENALTY":           (0.0, 2.0, "float"),
    "OFFTC_GUN_BOOST":           (0.3, 3.0, "float"),
    "OFFTC_ACCEL_BOOST":         (0.3, 3.0, "float"),
    "OFFTC_DIVE_BOOST":          (0.3, 3.0, "float"),
    "OFFTC_TCV_BOOST":           (0.3, 3.0, "float"),
    "OFFTC_LEAD_BOOST":          (0.3, 3.0, "float"),
    "OFFLAG_DWELL_BOOST":        (0.3, 3.0, "float"),
    "OFFLAG_TCV_BOOST":          (0.3, 3.0, "float"),
    "OFFLAG_HIGHYOYO_BOOST":     (0.3, 3.0, "float"),
    "OFFLAG_CUTOFF_BOOST":       (0.3, 3.0, "float"),
    "OFFLAG_PATIENCE":           (0.0, 2.0, "float"),
    "LUFB_VERTICAL_BOOST":       (0.3, 3.0, "float"),
    "LUFB_HIGHYOYO_BOOST":       (0.3, 3.0, "float"),
    "LUFB_DIVE_BOOST":           (0.3, 3.0, "float"),
    "LUFB_BREAK_BOOST":          (0.3, 3.0, "float"),
    "LUFB_BARRELROLL_BOOST":     (0.3, 3.0, "float"),
    "DEFSPIRAL_BREAK_BOOST":     (0.3, 3.0, "float"),
    "DEFSPIRAL_HARD_DECK_PENALTY": (0.0, 2.0, "float"),
    # v3.40 PD action_gun_engagement knobs
    "PD_GUN_KP":                 (0.3, 2.5, "float"),
    "PD_GUN_KD":                 (0.0, 1.5, "float"),
    # v3.40 OFFP 5-rule thresholds
    "OFFP_DIST_WIDEN_THRESH":    (10.0, 100.0, "float"),
    "OFFP_ATA_WORSEN_THRESH":    (1.0, 8.0, "float"),
    "OFFP_OVERSHOOT_CLOSURE":    (150.0, 400.0, "float"),
    "OFFP_FAR_DIST":             (4000.0, 12000.0, "float"),
    "OFFP_SPRINT_ATA_MAX":       (15.0, 50.0, "float"),
    "OFFP_ENERGY_DIVE_THRESH":   (1000.0, 5000.0, "float"),
    # v3.41 1C/2C
    "ONE_CIRCLE_VEL":            (1.0, 2.0, "float"),
    "TWO_CIRCLE_VEL":            (3.0, 4.0, "float"),
    # v3.43 bt_vs_bt 강제 engage
    "FORCE_ENGAGE_WEIGHT":       (0.0, 10.0, "float"),
}


def gen_random_variant():
    v = {}
    for name, (lo, hi, t) in KNOBS.items():
        if t == "int":
            v[name] = random.randint(int(lo), int(hi))
        else:
            v[name] = round(random.uniform(lo, hi), 2)
    return v


def mutate(parent: dict, rate: float = 0.3, sigma: float = 0.2) -> dict:
    child = dict(parent)
    for name, (lo, hi, t) in KNOBS.items():
        if random.random() < rate:
            if t == "int":
                jitter = random.randint(-5, 5)
                child[name] = max(int(lo), min(int(hi), parent[name] + jitter))
            else:
                jitter = parent[name] * random.gauss(0, sigma)
                child[name] = round(max(lo, min(hi, parent[name] + jitter)), 2)
    return child


def crossover(p1: dict, p2: dict) -> dict:
    return {k: (p1[k] if random.random() < 0.5 else p2[k]) for k in p1}


def apply_variant(v: dict):
    """cost_branch_selector.py 의 knobs swap. 단순 정규식 치환 — 회귀 시 immediate revert."""
    src = SELECTOR.read_text(encoding="utf-8")
    # STUCK_THR
    src = re.sub(r'if self\._branch_tick > \d+:',
                 f"if self._branch_tick > {v['STUCK_THR']}:", src)
    src = re.sub(r'min\([\d.]+, \(self\._branch_tick - \d+\) / 50\.0\)',
                 f"min({v['STUCK_MAX']}, (self._branch_tick - {v['STUCK_THR']}) / 50.0)", src)
    # LAMBDA_D
    src = re.sub(r'LAMBDA_D = [\d.]+',     f"LAMBDA_D = {v['LAMBDA_D']}", src)
    # cost weights — find first occurrence of weight (-X.Y * ...) per cost fn
    # cost_offensive_pursuit base = -4.5
    src = re.sub(r'base = -[\d.]+ \* pos_q \* dist_q',
                 f"base = -{v['LAMBDA_OFFENSIVE']} * pos_q * dist_q", src)
    # cost_cutoff_pursuit return = -2.0 * ata_q * ...
    src = re.sub(r'return -[\d.]+ \* ata_q \* \(0\.3 \+ 0\.7 \* closure_q\)',
                 f"return -{v['LAMBDA_CUTOFF']} * ata_q * (0.3 + 0.7 * closure_q)", src)
    # cost_high_yoyo return = -1.5
    src = re.sub(r'return -[\d.]+ \* min\(1\.0, score\)',
                 f"return -{v['LAMBDA_HIGHYOYO']} * min(1.0, score)", src)
    # cost_break_turn return = -3.5 (v3.8.3 약화)
    src = re.sub(r'return -[\d.]+ \* threat_score',
                 f"return -{v['LAMBDA_BREAK']} * threat_score", src)
    # cost_dive_attack
    src = re.sub(r'return -[\d.]+ \* alt_adv_q \* ata_q \* dist_q',
                 f"return -{v['LAMBDA_DIVE']} * alt_adv_q * ata_q * dist_q", src)
    # cost_tail_chase_vertical
    src = re.sub(r'return -[\d.]+ \* closing_penalty \* dist_q \* alt_room',
                 f"return -{v['LAMBDA_TCV']} * closing_penalty * dist_q * alt_room", src)
    # cost_extension
    src = re.sub(r'return -[\d.]+ \* dist_q \* ata_q',
                 f"return -{v['LAMBDA_EXT']} * dist_q * ata_q", src)
    # v3.29 (Round 5): situation multiplier knobs (각각 단순 패턴)
    for sm_name in ("SITMULT_OTO_GUN", "SITMULT_OTO_BREAK", "SITMULT_OTO_OFFENSIVE",
                    "SITMULT_OTO_CUTOFF", "SITMULT_OTO_DIVE", "SITMULT_OTO_TCV",
                    "SITMULT_OTO_EXT", "SITMULT_CHASE_GUN", "SITMULT_CHASE_BREAK",
                    "SITMULT_CHASE_OFFENSIVE", "SITMULT_CHASE_CUTOFF",
                    "SITMULT_CHASE_DIVE", "SITMULT_CHASE_TCV", "SITMULT_CHASE_EXT",
                    "WEZ_DWELL_CLOSURE_OPT_KTS", "WEZ_DWELL_CLOSURE_SIGMA",
                    "WEZ_DWELL_WEIGHT",
                    # v3.31 defensive escape
                    "DEFESC_WEIGHT_SURVIVE", "DEFESC_WEIGHT_OVERSHOOT",
                    "DEFESC_WEIGHT_BUGOUT", "DEFESC_WEIGHT_LASTDITCH",
                    # v3.32 pursuit curve
                    "PURSUIT_LEAD_WEIGHT", "PURSUIT_LAG_WEIGHT",
                    "PURSUIT_LAG_CLOSURE_LIMIT_KTS",
                    # v3.33 initial accel
                    "INITACC_WEIGHT", "INITACC_SPEED_MIN_KTS", "INITACC_DIST_MIN_FT",
                    # v3.34 gun two-mode
                    "GUN_TRACKING_TCA_MAX_DEG", "GUN_SNAPSHOT_TCA_MIN_DEG",
                    "GUN_TRACKING_WEIGHT", "GUN_SNAPSHOT_WEIGHT",
                    # v3.35 counter-defense
                    "COUNTER_BARRELROLL_WEIGHT", "COUNTER_LAG_WEIGHT",
                    "COUNTER_PATIENCE_WEIGHT",
                    # v3.36 + v3.37
                    "ANTI_REVERSAL_WEIGHT", "WEZ_ENVELOPE_WEIGHT",
                    "WEZ_HIGHASPECT_ATA_OPT", "WEZ_HIGHASPECT_TCA_OPT",
                    # v3.38 sub-situation 22 knobs
                    "HOM_GUN_BOOST", "HOM_BREAK_BOOST", "HOM_CUTOFF_BOOST",
                    "HOM_DIVE_BOOST", "HOM_EXT_PENALTY",
                    "OFFTC_GUN_BOOST", "OFFTC_ACCEL_BOOST", "OFFTC_DIVE_BOOST",
                    "OFFTC_TCV_BOOST", "OFFTC_LEAD_BOOST",
                    "OFFLAG_DWELL_BOOST", "OFFLAG_TCV_BOOST", "OFFLAG_HIGHYOYO_BOOST",
                    "OFFLAG_CUTOFF_BOOST", "OFFLAG_PATIENCE",
                    "LUFB_VERTICAL_BOOST", "LUFB_HIGHYOYO_BOOST", "LUFB_DIVE_BOOST",
                    "LUFB_BREAK_BOOST", "LUFB_BARRELROLL_BOOST",
                    "DEFSPIRAL_BREAK_BOOST", "DEFSPIRAL_HARD_DECK_PENALTY",
                    # v3.40-43 actions + bt force engage
                    "PD_GUN_KP", "PD_GUN_KD",
                    "OFFP_DIST_WIDEN_THRESH", "OFFP_ATA_WORSEN_THRESH",
                    "OFFP_OVERSHOOT_CLOSURE", "OFFP_FAR_DIST",
                    "OFFP_SPRINT_ATA_MAX", "OFFP_ENERGY_DIVE_THRESH",
                    "ONE_CIRCLE_VEL", "TWO_CIRCLE_VEL",
                    "FORCE_ENGAGE_WEIGHT"):
        if sm_name in v:
            src = re.sub(rf'^{sm_name} = [\d.]+$',
                         f"{sm_name} = {v[sm_name]}", src, flags=re.MULTILINE)
    SELECTOR.write_text(src, encoding="utf-8")


def run_match(opp: str, scen: str, max_steps: int = MAX_STEPS) -> float:
    """Δ fitness + WIN/LOSS bonus (사용자 명령 2026-05-29).

    사용자 framework: "상황별 정리 → 아군 유리해지는 방향 GA → BT 개선"
    이전 us_dmg only fitness 가 *유리* 를 측정 못 함 → 12 round 모두 잘못 학습.
    수정: Δ + bonus → 진짜 *WIN-oriented* optimization.
    """
    env = os.environ.copy()
    if opp in ("aggressive", "defensive"):
        env["ADVERSARY"] = opp
    else:
        env.pop("ADVERSARY", None)
    try:
        r = subprocess.run(
            ["python", "scripts/run_match.py",
             "--agent1", "examples/pursuit_chase_v1/pursuit_chase_btcost.yaml",
             "--agent2", opp, "--rounds", "1", "--max-steps", str(max_steps),
             "--scenario", scen],
            capture_output=True, text=True, timeout=TIMEOUT, cwd=ROOT, env=env)
        out = r.stdout + r.stderr
        pat = re.compile(r":\s*[\d.]+\s*HP\s*\(데미지\s+([\d.]+)\s*가함\)")
        dmgs = pat.findall(out)
        if len(dmgs) < 2:
            return 0.0
        opp_dmg = float(dmgs[-2])
        us_dmg = float(dmgs[-1])
        # 편식 방지 (사용자 명령 2026-05-29): 각 cell 동등 영향력
        # Δ clip [-100, +100] (HP 100 한계) + W/L bonus ±50 → cell score ∈ [-150, +150]
        delta = max(-100.0, min(100.0, us_dmg - opp_dmg))
        if "승리" in out:
            return delta + 50.0
        if "패배" in out:
            return delta - 50.0
        return delta
    except Exception:
        return 0.0


def _match_worker(args):
    """병렬 실행용 single-match worker. Pool 에서 호출."""
    opp, scen, max_steps = args
    return run_match(opp, scen, max_steps)


def fitness(variant: dict, scenarios=None, opp_subset=None, runs: int = 1,
            n_workers: int = 1) -> dict:
    """사용자 명령 2026-05-29:
    - 편식 방지: 모든 cell 동등 가중 (opp/scen weight 모두 1.0)
    - 병렬 실행: n_workers parallel match (GA 의 본질 = meta-heuristic + parallel)
    """
    apply_variant(variant)
    scenarios = scenarios or SCENARIOS
    opps = opp_subset or OPPONENTS
    # 모든 (opp, scen) × runs 매치 task 생성
    tasks = []
    keys = []
    for opp, _ in opps:
        for scen in scenarios:
            for _ in range(runs):
                tasks.append((opp, scen, MAX_STEPS))
                keys.append(f"{opp}@{scen}")
    # 병렬 실행
    if n_workers > 1:
        from multiprocessing import Pool
        with Pool(n_workers) as pool:
            dmgs = pool.map(_match_worker, tasks)
    else:
        dmgs = [_match_worker(t) for t in tasks]
    # 집계 — 모든 cell 동등 영향력 (편식 방지)
    cell_dmgs = {}
    for key, d in zip(keys, dmgs):
        cell_dmgs.setdefault(key, []).append(d)
    score = 0.0
    detail = {}
    for key, vals in cell_dmgs.items():
        avg = sum(vals) / len(vals)
        detail[key] = avg
        score += avg  # weight=1.0 (편식 방지)
    return {"score": round(score, 2), "detail": detail}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pop", type=int, default=12)
    ap.add_argument("--gens", type=int, default=10)
    ap.add_argument("--runs", type=int, default=1)
    ap.add_argument("--elite", type=int, default=3)
    ap.add_argument("--mutate-rate", type=float, default=0.4)
    ap.add_argument("--opp-subset", type=str, default="",
                    help="comma-separated subset (default = all)")
    ap.add_argument("--scen-subset", type=str, default="",
                    help="comma-separated (default = all)")
    ap.add_argument("--n-workers", type=int, default=1,
                    help="병렬 worker 수 (사용자 명령 2026-05-29: GA = parallel)")
    args = ap.parse_args()

    if args.opp_subset:
        names = args.opp_subset.split(",")
        opp_subset = [(o, w) for o, w in OPPONENTS if o in names]
    else:
        opp_subset = OPPONENTS
    if args.scen_subset:
        scens = args.scen_subset.split(",")
    else:
        scens = SCENARIOS

    print(f"=== GA fuzzing: pop={args.pop} gens={args.gens} runs={args.runs} ===", flush=True)
    print(f"  opps: {[o for o,_ in opp_subset]}", flush=True)
    print(f"  scenarios: {scens}", flush=True)
    print(f"  knobs: {list(KNOBS.keys())}", flush=True)

    # 백업 (revert 용)
    backup = SELECTOR.read_text(encoding="utf-8")
    backup_path = SELECTOR.parent / f"cost_branch_selector.backup.{int(time.time())}.py"
    backup_path.write_text(backup, encoding="utf-8")
    print(f"  backup: {backup_path}", flush=True)

    # population init — Round 5 baseline = R2 champion + situation multiplier defaults
    baseline = {
        # R2 champion (best for base 4)
        "STUCK_THR": 35, "STUCK_MAX": 2.36,
        "LAMBDA_D": 7.13, "LAMBDA_OFFENSIVE": 3.15,
        "LAMBDA_CUTOFF": 2.8, "LAMBDA_BREAK": 4.47,
        "LAMBDA_HIGHYOYO": 1.11, "LAMBDA_DIVE": 5.66,
        "LAMBDA_TCV": 5.52, "LAMBDA_EXT": 4.28,
        # situation multiplier defaults (코드의 값)
        "SITMULT_OTO_GUN": 1.5, "SITMULT_OTO_BREAK": 1.2,
        "SITMULT_OTO_OFFENSIVE": 0.8, "SITMULT_OTO_CUTOFF": 0.8,
        "SITMULT_OTO_DIVE": 0.8, "SITMULT_OTO_TCV": 0.6,
        "SITMULT_OTO_EXT": 0.7,
        "SITMULT_CHASE_GUN": 1.0, "SITMULT_CHASE_BREAK": 0.9,
        "SITMULT_CHASE_OFFENSIVE": 1.2, "SITMULT_CHASE_CUTOFF": 1.2,
        "SITMULT_CHASE_DIVE": 1.3, "SITMULT_CHASE_TCV": 1.3,
        "SITMULT_CHASE_EXT": 1.1,
        # v3.30 WEZ dwell defaults
        "WEZ_DWELL_CLOSURE_OPT_KTS": 50.0,
        "WEZ_DWELL_CLOSURE_SIGMA": 80.0,
        "WEZ_DWELL_WEIGHT": 2.0,
        # v3.31 defensive escape (T-45A) defaults
        "DEFESC_WEIGHT_SURVIVE": 8.0,
        "DEFESC_WEIGHT_OVERSHOOT": 6.0,
        "DEFESC_WEIGHT_BUGOUT": 5.0,
        "DEFESC_WEIGHT_LASTDITCH": 10.0,
        # v3.32 pursuit curve (AETC) defaults
        "PURSUIT_LEAD_WEIGHT": 3.0,
        "PURSUIT_LAG_WEIGHT": 3.0,
        "PURSUIT_LAG_CLOSURE_LIMIT_KTS": 200.0,
        # v3.33 initial chase accel defaults
        "INITACC_WEIGHT": 5.0,
        "INITACC_SPEED_MIN_KTS": 350.0,
        "INITACC_DIST_MIN_FT": 4000.0,
        # v3.34 gun two-mode defaults
        "GUN_TRACKING_TCA_MAX_DEG": 40.0,
        "GUN_SNAPSHOT_TCA_MIN_DEG": 60.0,
        "GUN_TRACKING_WEIGHT": 12.0,
        "GUN_SNAPSHOT_WEIGHT": 6.0,
        # v3.35 counter-defense defaults
        "COUNTER_BARRELROLL_WEIGHT": 4.0,
        "COUNTER_LAG_WEIGHT": 3.0,
        "COUNTER_PATIENCE_WEIGHT": 3.0,
        # v3.36 + v3.37 defaults
        "ANTI_REVERSAL_WEIGHT": 4.0,
        "WEZ_ENVELOPE_WEIGHT": 10.0,
        "WEZ_HIGHASPECT_ATA_OPT": 30.0,
        "WEZ_HIGHASPECT_TCA_OPT": 90.0,
        # v3.38 sub-situation defaults (all 1.0 = neutral)
        "HOM_GUN_BOOST": 1.0, "HOM_BREAK_BOOST": 1.0, "HOM_CUTOFF_BOOST": 1.0,
        "HOM_DIVE_BOOST": 1.0, "HOM_EXT_PENALTY": 1.0,
        "OFFTC_GUN_BOOST": 1.0, "OFFTC_ACCEL_BOOST": 1.0, "OFFTC_DIVE_BOOST": 1.0,
        "OFFTC_TCV_BOOST": 1.0, "OFFTC_LEAD_BOOST": 1.0,
        "OFFLAG_DWELL_BOOST": 1.0, "OFFLAG_TCV_BOOST": 1.0,
        "OFFLAG_HIGHYOYO_BOOST": 1.0, "OFFLAG_CUTOFF_BOOST": 1.0,
        "OFFLAG_PATIENCE": 1.0,
        "LUFB_VERTICAL_BOOST": 1.0, "LUFB_HIGHYOYO_BOOST": 1.0,
        "LUFB_DIVE_BOOST": 1.0, "LUFB_BREAK_BOOST": 1.0, "LUFB_BARRELROLL_BOOST": 1.0,
        "DEFSPIRAL_BREAK_BOOST": 1.0, "DEFSPIRAL_HARD_DECK_PENALTY": 1.0,
        # v3.40-43 defaults
        "PD_GUN_KP": 1.2, "PD_GUN_KD": 0.5,
        "OFFP_DIST_WIDEN_THRESH": 30.0, "OFFP_ATA_WORSEN_THRESH": 3.0,
        "OFFP_OVERSHOOT_CLOSURE": 280.0, "OFFP_FAR_DIST": 7000.0,
        "OFFP_SPRINT_ATA_MAX": 30.0, "OFFP_ENERGY_DIVE_THRESH": 2500.0,
        "ONE_CIRCLE_VEL": 1.0, "TWO_CIRCLE_VEL": 4.0,
        "FORCE_ENGAGE_WEIGHT": 4.0,
    }
    pop = [baseline]   # always include baseline
    for _ in range(args.pop - 1):
        if random.random() < 0.5:
            # baseline + small mutation
            pop.append(mutate(baseline, rate=0.5, sigma=0.15))
        else:
            pop.append(gen_random_variant())

    all_results = []
    best_ever = {"score": -1.0, "variant": None, "detail": None, "gen": -1}

    try:
        for gen in range(args.gens):
            print(f"\n━━━ Generation {gen} ━━━", flush=True)
            evals = []
            for i, v in enumerate(pop):
                t0 = time.time()
                res = fitness(v, scenarios=scens, opp_subset=opp_subset,
                              runs=args.runs, n_workers=args.n_workers)
                dt = time.time() - t0
                evals.append({"variant": v, **res})
                print(f"  v{i:02d} score={res['score']:>6.2f}  "
                      f"({dt:.1f}s)  detail={res['detail']}", flush=True)
                if res["score"] > best_ever["score"]:
                    best_ever = {"score": res["score"], "variant": v,
                                  "detail": res["detail"], "gen": gen}
                    print(f"    🏆 NEW BEST score={res['score']}", flush=True)
            evals.sort(key=lambda e: -e["score"])
            print(f"  gen {gen} top: score={evals[0]['score']:.2f}, "
                  f"median={statistics.median([e['score'] for e in evals]):.2f}", flush=True)
            all_results.append({"gen": gen, "best": evals[0], "all": evals})
            # save generation
            (RESULTS_DIR / f"gen_{gen:03d}.json").write_text(
                json.dumps(all_results[-1], indent=2, ensure_ascii=False))

            # next generation: elite + crossover + mutation
            elite = [e["variant"] for e in evals[:args.elite]]
            new_pop = list(elite)
            while len(new_pop) < args.pop:
                p1, p2 = random.sample(elite + [e["variant"] for e in evals[:args.pop//2]], 2)
                child = mutate(crossover(p1, p2), rate=args.mutate_rate)
                new_pop.append(child)
            pop = new_pop

    finally:
        # restore baseline
        SELECTOR.write_text(backup, encoding="utf-8")
        # save final
        (RESULTS_DIR / "best_ever.json").write_text(
            json.dumps(best_ever, indent=2, ensure_ascii=False))
        print(f"\n=== FINAL ===", flush=True)
        print(f"  best_ever (gen {best_ever['gen']}): score={best_ever['score']}", flush=True)
        print(f"  variant: {best_ever['variant']}", flush=True)
        print(f"  detail: {best_ever['detail']}", flush=True)


if __name__ == "__main__":
    main()
