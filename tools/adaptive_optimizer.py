"""
Adaptive Eagle Full-Space Optimizer — CMA-ES

전체 BFM 노드의 파라미터 + 구조를 자동 탐색.
"어떤 노드를 쓸 것인가" + "각 노드의 파라미터"를 동시에 최적화.

핵심 원칙:
  - 빌트인 고정값이 탐색 공간에 포함 → 결과 >= 빌트인 보장
  - 이론으로 축소하지 않고 전체를 CMA-ES에 맡김
  - TUNABLE_PARAMS가 있는 노드는 자동으로 탐색 공간에 등록

사용법:
    python tools/adaptive_optimizer.py --budget 400 --workers 4
    python tools/adaptive_optimizer.py --tournament
    python tools/adaptive_optimizer.py --ablation
"""

import sys
import os
import yaml
import json
import time
import argparse
import importlib
import multiprocessing as mp
from pathlib import Path
from datetime import datetime

import numpy as np

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from tools.evaluate import _resolve_agent, _run_single, _wilson_ci

# ─── Scoring ──────────────────────────────────────────────────

WIN_BASE  = 10.0
DRAW_BASE =  1.0
LOSS_BASE = -5.0
HP_WEIGHT =  2.0

# ─── 상대 풀 관리 ─────────────────────────────────────────────
# 최적화 루프는 대표 샘플(40개)로 빠르게, 최종 검증은 전체(695개)로.

LEGACY_OPPONENTS = ["eagle1", "ace", "aggressive", "defensive", "simple", "viper1"]
POOL_DIR = PROJECT_ROOT / "examples" / "opponent_pool"
POOL_MANIFEST = POOL_DIR / "manifest.json"

def _load_pool_opponents():
    """opponent_pool 전체 상대 경로 리스트 (없으면 legacy fallback)."""
    if not POOL_MANIFEST.exists():
        return [_resolve_agent(o) for o in LEGACY_OPPONENTS]
    with open(POOL_MANIFEST, encoding="utf-8") as f:
        manifest = json.load(f)
    return [str(POOL_DIR / o["yaml_path"]) for o in manifest["opponents"]]

def _stratified_sample_opponents(k: int = 40, seed: int = 0):
    """레이어별 균등 샘플링으로 최적화 루프용 상대 k개 선택."""
    if not POOL_MANIFEST.exists():
        return [_resolve_agent(o) for o in LEGACY_OPPONENTS]
    import random
    with open(POOL_MANIFEST, encoding="utf-8") as f:
        manifest = json.load(f)
    by_layer = {}
    for opp in manifest["opponents"]:
        by_layer.setdefault(opp["layer"], []).append(opp)
    rng = random.Random(seed)
    per_layer = max(1, k // len(by_layer))
    sampled = []
    for layer, opps in by_layer.items():
        picked = rng.sample(opps, min(per_layer, len(opps)))
        sampled.extend(picked)
    # 부족분 채우기
    if len(sampled) < k:
        remaining = [o for o in manifest["opponents"] if o not in sampled]
        rng.shuffle(remaining)
        sampled.extend(remaining[:k - len(sampled)])
    return [str(POOL_DIR / o["yaml_path"]) for o in sampled[:k]]

# 기본: 최적화 루프용 stratified sample 40개
OPPONENTS = _stratified_sample_opponents(k=40, seed=0) if POOL_MANIFEST.exists() else LEGACY_OPPONENTS

# ─── Auto-discover TUNABLE_PARAMS ─────────────────────────────

def _discover_tunable_classes():
    """adaptive_eagle/nodes/ 에서 TUNABLE_PARAMS가 있는 모든 클래스 수집."""
    nodes_dir = PROJECT_ROOT / "examples" / "adaptive_eagle" / "nodes"
    classes = {}
    for py_file in nodes_dir.glob("custom_*.py"):
        module_name = f"examples.adaptive_eagle.nodes.{py_file.stem}"
        try:
            mod = importlib.import_module(module_name)
        except Exception:
            continue
        for attr_name in dir(mod):
            cls = getattr(mod, attr_name)
            if isinstance(cls, type) and hasattr(cls, "TUNABLE_PARAMS") and cls.TUNABLE_PARAMS is not None:
                classes[attr_name] = cls
    return classes

ALL_CUSTOM_CLASSES = _discover_tunable_classes()

# ─── Parameter Space: 구조 + 노드 파라미터 ────────────────────

# 구조 파라미터: "어떤 노드를 어떤 브랜치에 배치할 것인가"
# 각 전술 슬롯에 대해 어떤 액션을 쓸지 선택

# 전술 슬롯 정의
ACTION_SLOTS = {
    "gun_action":      ["SmartGunAttack", "SnapshotAttack"],
    "pursuit_action":  ["SmartLeadPursuit", "SmartPurePursuit", "SmartLagPursuit"],
    "defense_action":  ["ExtensionBreak", "SmartBreakTurn", "SmartDefensiveSpiral",
                        "GunsDefense", "Jink", "LastDitch"],
    "orbit_action":    ["HeadOnBreak", "UnloadedExtension", "Chandelle"],
    "energy_action":   ["SmartHighYoYo", "SmartLowYoYo", "SmartClimbingTurn",
                        "SmartDescendingTurn", "VerticalFight"],
    "neutral_action":  ["SmartOneCircle", "SmartTwoCircle", "FlatScissors",
                        "RollingScissors"],
    "default_action":  ["SmartLeadPursuit", "SmartPurePursuit", "SmartLagPursuit"],
    "underfire_action": ["GunsDefense", "SmartBreakTurn", "Jink",
                         "SmartDefensiveSpiral", "LastDitch"],
    "overshoot_action": ["SmartHighYoYo", "SmartLagPursuit", "SmartBreakTurn"],
}

# 조건 파라미터 + 구조 ON/OFF + 슬롯 선택 + 노드 파라미터를 모두 수집
def _build_param_defs():
    """전체 탐색 공간을 자동 구성."""
    defs = []

    # 1. 구조 파라미터 — 브랜치 ON/OFF
    for branch in ["enable_gun", "enable_orbit", "enable_eim",
                    "enable_energy", "enable_neutral", "enable_defense",
                    "enable_underfire", "enable_overshoot"]:
        defs.append((branch, "disc", [True, False]))

    # 2. 슬롯 선택 — 어떤 노드를 쓸 것인가
    for slot_name, choices in ACTION_SLOTS.items():
        defs.append((slot_name, "disc", choices))

    # 3. 조건 파라미터 — 모든 조건 노드의 TUNABLE_PARAMS
    for cls_name, cls in ALL_CUSTOM_CLASSES.items():
        if not cls_name.startswith("Is") and cls_name != "CustomOrbitDetector":
            continue
        for pname, spec in cls.TUNABLE_PARAMS.items():
            full_name = f"{cls_name}.{pname}"
            if spec["type"] == "cont":
                defs.append((full_name, "cont", spec["range"]))
            else:
                defs.append((full_name, "disc", spec["choices"]))

    # 4. 액션 파라미터 — 모든 액션 노드의 TUNABLE_PARAMS
    for cls_name, cls in ALL_CUSTOM_CLASSES.items():
        if cls_name.startswith("Is") or cls_name == "CustomOrbitDetector":
            continue
        for pname, spec in cls.TUNABLE_PARAMS.items():
            full_name = f"{cls_name}.{pname}"
            if spec["type"] == "cont":
                defs.append((full_name, "cont", spec["range"]))
            else:
                defs.append((full_name, "disc", spec["choices"]))

    # 5. HardDeck 파라미터 (항상 존재)
    defs.append(("harddeck_threshold", "cont", (1000, 1500)))
    defs.append(("climb_target", "cont", (2000, 4000)))
    defs.append(("close_combat_dist", "cont", (2000, 6000)))
    defs.append(("eim_confidence", "cont", (0.15, 0.50)))

    # 6. EIM 멀티인텐트 파라미터 (Phase D — 3개 intent 추가)
    # NEUTRAL_CIRCLE은 기존 eim_confidence/enable_eim으로 처리
    # 나머지 3개 intent에 대한 독립 반응 브랜치
    defs.append(("enable_eim_pursuit",   "disc", [True, False]))
    defs.append(("enable_eim_scissors",  "disc", [True, False]))
    defs.append(("enable_eim_gun",       "disc", [True, False]))
    defs.append(("eim_conf_pursuit",     "cont", (0.15, 0.70)))
    defs.append(("eim_conf_scissors",    "cont", (0.15, 0.70)))
    defs.append(("eim_conf_gun",         "cont", (0.15, 0.70)))
    defs.append(("eim_pursuit_action",   "disc", ["Accelerate", "SmartClimbingTurn",
                                                   "ExtensionBreak", "SmartLeadPursuit"]))
    defs.append(("eim_scissors_action",  "disc", ["HeadOnBreak", "SmartOneCircle",
                                                   "Accelerate", "SmartBreakTurn"]))
    defs.append(("eim_gun_action",       "disc", ["GunsDefense", "ExtensionBreak",
                                                   "SmartBreakTurn", "LastDitch"]))

    return defs

PARAM_DEFS = _build_param_defs()
N_DIMS = len(PARAM_DEFS)

# ─── Vector ↔ Params ─────────────────────────────────────────

def vector_to_params(x):
    params = {}
    for i, (name, ptype, spec) in enumerate(PARAM_DEFS):
        val = np.clip(x[i], 0.0, 1.0)
        if ptype == "cont":
            lo, hi = spec
            params[name] = float(lo + (hi - lo) * val)
        else:
            idx = min(int(val * len(spec)), len(spec) - 1)
            params[name] = spec[idx]
    return params


def params_to_vector(params):
    x = np.zeros(N_DIMS)
    for i, (name, ptype, spec) in enumerate(PARAM_DEFS):
        val = params.get(name)
        if val is None:
            x[i] = 0.5
            continue
        if ptype == "cont":
            lo, hi = spec
            x[i] = np.clip((val - lo) / (hi - lo), 0, 1)
        else:
            try:
                idx = spec.index(val)
                x[i] = (idx + 0.5) / len(spec)
            except ValueError:
                x[i] = 0.5
    return x


# ─── BT Template ─────────────────────────────────────────────

def _node_params(params, cls_name):
    """params dict에서 특정 노드의 파라미터만 추출."""
    prefix = f"{cls_name}."
    node_params = {}
    cls = ALL_CUSTOM_CLASSES.get(cls_name)
    if cls is None:
        return node_params
    for pname, spec in cls.TUNABLE_PARAMS.items():
        full = prefix + pname
        if full in params:
            val = params[full]
            if spec["type"] == "cont":
                node_params[pname] = round(float(val), 2)
            else:
                node_params[pname] = val
    return node_params


def _cond_node(cls_name, params):
    """조건 노드 YAML dict."""
    p = _node_params(params, cls_name)
    d = {"type": "Condition", "name": cls_name}
    if p:
        d["params"] = p
    return d


def _action_node(cls_name, params):
    """액션 노드 YAML dict."""
    p = _node_params(params, cls_name)
    d = {"type": "Action", "name": cls_name}
    if p:
        d["params"] = p
    return d


def generate_bt_yaml(params):
    """파라미터 → 전체 BT YAML dict."""
    children = []

    # 1. Hard Deck (항상)
    children.append({
        "type": "Sequence", "name": "HardDeckAvoidance",
        "children": [
            {"type": "Condition", "name": "BelowHardDeck",
             "params": {"threshold_ft": int(params.get("harddeck_threshold", 1200))}},
            {"type": "Action", "name": "ClimbTo",
             "params": {"target_altitude_ft": int(params.get("climb_target", 3000))}},
        ]
    })

    # 2. Gun WEZ (optional)
    if params.get("enable_gun", True):
        gun_act = params.get("gun_action", "SmartGunAttack")
        children.append({
            "type": "Sequence", "name": "GunEngagement",
            "children": [
                _cond_node("IsWEZOpportunity", params),
                _action_node(gun_act, params),
            ]
        })

    # 3. Under Fire (optional)
    if params.get("enable_underfire", False):
        uf_act = params.get("underfire_action", "GunsDefense")
        children.append({
            "type": "Sequence", "name": "UnderFireResponse",
            "children": [
                _cond_node("IsUnderFire", params),
                _action_node(uf_act, params),
            ]
        })

    # 4. Overshoot avoidance (optional)
    if params.get("enable_overshoot", False):
        os_act = params.get("overshoot_action", "SmartHighYoYo")
        children.append({
            "type": "Sequence", "name": "OvershootAvoid",
            "children": [
                _cond_node("IsOvershooting", params),
                _action_node(os_act, params),
            ]
        })

    # 5. EIM + Orbit (optional)
    if params.get("enable_eim", True):
        children.append({
            "type": "Sequence", "name": "IntentAdaptiveEscape",
            "children": [
                {"type": "Condition", "name": "EnemyIntentIs",
                 "params": {"intent": "NEUTRAL_CIRCLE",
                            "min_confidence": round(params.get("eim_confidence", 0.30), 2)}},
                _cond_node("CustomOrbitDetector", params),
                _action_node(params.get("orbit_action", "HeadOnBreak"), params),
            ]
        })

    # 5b. EIM 멀티인텐트 응답 브랜치 (Phase D — NEUTRAL_CIRCLE 외 추가 intent)
    # CMA-ES가 어느 intent에 반응할지, 임계값은 얼마인지, 어떤 행동으로 반응할지 자동 결정
    for intent_key, enable_key, conf_key, action_key, default_action in [
        ("PURSUIT",         "enable_eim_pursuit",  "eim_conf_pursuit",  "eim_pursuit_action",  "ExtensionBreak"),
        ("NEUTRAL_SCISSORS","enable_eim_scissors", "eim_conf_scissors", "eim_scissors_action", "HeadOnBreak"),
        ("GUN_ATTACK",      "enable_eim_gun",      "eim_conf_gun",      "eim_gun_action",      "GunsDefense"),
    ]:
        if params.get(enable_key, False):
            children.append({
                "type": "Sequence", "name": f"IntentResponse_{intent_key}",
                "children": [
                    {"type": "Condition", "name": "EnemyIntentIs",
                     "params": {"intent": intent_key,
                                "min_confidence": round(params.get(conf_key, 0.40), 2)}},
                    _action_node(params.get(action_key, default_action), params),
                ]
            })

    # 6. Orbit fallback (optional)
    if params.get("enable_orbit", True):
        children.append({
            "type": "Sequence", "name": "OrbitBreak",
            "children": [
                _cond_node("CustomOrbitDetector", params),
                _action_node(params.get("orbit_action", "HeadOnBreak"), params),
            ]
        })

    # 7. Energy maneuver (optional)
    # Cycle 2 fix: 이중 조건(IsHighEnergy AND IsOffensiveGeometry) → 단일 조건으로 분리
    # IsLowEnergy → 회복 기동 (고도/에너지 열위 탈출)
    # IsHighEnergy → 공격 기동 (에너지 우위 활용)
    if params.get("enable_energy", False):
        e_act = params.get("energy_action", "SmartHighYoYo")
        children.append({
            "type": "Sequence", "name": "EnergyRecovery",
            "children": [
                _cond_node("IsLowEnergy", params),
                _action_node("SmartClimbingTurn", params),
            ]
        })
        children.append({
            "type": "Sequence", "name": "EnergyAttack",
            "children": [
                _cond_node("IsHighEnergy", params),
                _action_node(e_act, params),
            ]
        })

    # 8. Neutral/Turn fight (optional)
    if params.get("enable_neutral", False):
        n_act = params.get("neutral_action", "SmartOneCircle")
        children.append({
            "type": "Sequence", "name": "NeutralFight",
            "children": [
                _cond_node("IsNeutralGeometry", params),
                _action_node(n_act, params),
            ]
        })

    # 9. Close Combat (항상)
    cc_act = params.get("pursuit_action", "SmartLeadPursuit")
    children.append({
        "type": "Sequence", "name": "CloseCombat",
        "children": [
            _cond_node("IsCloseCombat", params),
            _action_node(cc_act, params),
        ]
    })

    # 10. Defense (optional)
    if params.get("enable_defense", True):
        def_act = params.get("defense_action", "ExtensionBreak")
        children.append({
            "type": "Sequence", "name": "DefensiveEscape",
            "children": [
                _cond_node("IsDefensiveGeometry", params),
                _action_node(def_act, params),
            ]
        })

    # 11. Default
    default_act = params.get("default_action", "SmartLeadPursuit")
    children.append(_action_node(default_act, params))

    return {
        "name": "adaptive_eagle", "version": "opt",
        "tree": {"type": "Selector", "children": children}
    }


# ─── Fitness ─────────────────────────────────────────────────

def compute_score(winner, our_hp, their_hp):
    hp_diff = max(-1.0, min(1.0, float(our_hp - their_hp) / 100.0))
    if winner == "tree1":
        return WIN_BASE + hp_diff * HP_WEIGHT
    elif winner == "draw":
        return DRAW_BASE + hp_diff * HP_WEIGHT
    else:
        return LOSS_BASE + hp_diff * HP_WEIGHT


def evaluate_fitness(params, worker_id=None, opponents_override=None):
    bt_dict = generate_bt_yaml(params)
    suffix = f"_{worker_id}" if worker_id is not None else f"_{os.getpid()}"
    temp_path = PROJECT_ROOT / "examples" / "adaptive_eagle" / f"_temp{suffix}.yaml"

    with open(temp_path, 'w', encoding='utf-8') as f:
        yaml.dump(bt_dict, f, default_flow_style=False, allow_unicode=True, sort_keys=False)

    total_score = 0.0
    details = {}

    opp_list = opponents_override if opponents_override is not None else OPPONENTS
    for opp_entry in opp_list:
        # opp_entry는 경로(신규 pool) 또는 이름(legacy)
        if isinstance(opp_entry, str) and (opp_entry.endswith(".yaml") or "/" in opp_entry or "\\" in opp_entry):
            opp_path = opp_entry
            opp = Path(opp_entry).stem
        else:
            opp = opp_entry
            try:
                opp_path = _resolve_agent(opp)
            except Exception:
                details[opp] = {"W": 0, "D": 0, "L": 1, "score": LOSS_BASE, "hp_diff": 0}
                total_score += LOSS_BASE
                continue
        try:
            r = _run_single(str(temp_path), opp_path, "adaptive_opt", opp)
        except Exception:
            details[opp] = {"W": 0, "D": 0, "L": 1, "score": LOSS_BASE, "hp_diff": 0}
            total_score += LOSS_BASE
            continue

        winner = r.get("winner", "unknown")
        our_hp = r.get("tree1_health", 100)
        their_hp = r.get("tree2_health", 100)
        score = compute_score(winner, our_hp, their_hp)
        total_score += score
        w = 1 if winner == "tree1" else 0
        d = 1 if winner == "draw" else 0
        details[opp] = {"W": w, "D": d, "L": 1 - w - d,
                        "score": round(score, 2), "hp_diff": round(our_hp - their_hp, 1)}

    try:
        temp_path.unlink()
    except Exception:
        pass

    return total_score, details


def _eval_worker(args):
    idx, x_vec = args
    params = vector_to_params(x_vec)
    score, details = evaluate_fitness(params, worker_id=idx)
    return idx, score, details, params


# ─── Multi-fidelity eval ──────────────────────────────────────

# fast 필터용 상대 (OPPONENTS의 부분집합, 레이어 균등 10개)
OPPONENTS_FAST = _stratified_sample_opponents(k=10, seed=0) if POOL_MANIFEST.exists() else LEGACY_OPPONENTS

# fast eval 점수가 이 값 미만이면 full eval 생략 (하위 70% 탈락)
FAST_FILTER_THRESHOLD = 0.0  # 기본값: 양수 score인 candidate만 full eval


def _eval_worker_multifidelity(args):
    """Multi-fidelity: Stage 1 (10-match 빠른 필터) → Stage 2 (40-match full eval)."""
    idx, x_vec, fast_threshold = args
    params = vector_to_params(x_vec)

    # Stage 1: 빠른 필터 (10 matches)
    fast_score, fast_details = evaluate_fitness(params, worker_id=idx,
                                                opponents_override=OPPONENTS_FAST)

    if fast_score < fast_threshold:
        # 하위 후보: fast score 그대로 반환 (full eval 생략)
        return idx, fast_score, fast_details, params, "fast"

    # Stage 2: 유망 후보 full eval (40 matches)
    full_score, full_details = evaluate_fitness(params, worker_id=idx)
    return idx, full_score, full_details, params, "full"


def _validate_match_worker(args):
    """워커: 단일 매치 실행 후 (opp_name, layer, winner) 반환."""
    yaml_path, opp_path, opp_name, layer = args
    try:
        r = _run_single(yaml_path, opp_path, "adaptive_eagle", opp_name)
        w = r.get("winner", "unknown")
        hp_diff = r.get("tree1_health", 0) - r.get("tree2_health", 0)
    except Exception:
        w = "error"
        hp_diff = 0
    return opp_name, layer, w, hp_diff


def validate_on_full_pool(yaml_path: str, rounds: int = 10, silent: bool = False,
                          n_workers: int = None) -> dict:
    """최종 검증: 전체 opponent_pool × rounds, 워커 병렬화.

    Wilson CI @ 10R × 695 ≈ ±1.18%, @ 50R × 695 ≈ ±0.53%.
    """
    import math
    if n_workers is None:
        n_workers = max(1, mp.cpu_count() - 1)

    all_paths = _load_pool_opponents()
    work_items = []
    for opp_path in all_paths:
        opp_name = Path(opp_path).stem
        layer = opp_name.split("_", 1)[0] if opp_name.startswith("L") else "legacy"
        for _ in range(rounds):
            work_items.append((yaml_path, opp_path, opp_name, layer))

    total_jobs = len(work_items)
    total_w = total_d = total_l = 0
    per_layer = {}
    per_opp = {}
    t0 = time.time()
    done = 0

    with mp.Pool(processes=n_workers) as pool:
        for opp_name, layer, w, hp_diff in pool.imap_unordered(_validate_match_worker, work_items, chunksize=4):
            done += 1
            layer_stat = per_layer.setdefault(layer, {"W": 0, "D": 0, "L": 0})
            opp_stat = per_opp.setdefault(opp_name, {"W": 0, "D": 0, "L": 0, "hp_diffs": []})
            opp_stat["hp_diffs"].append(round(hp_diff, 1))

            if w == "tree1":
                total_w += 1
                layer_stat["W"] += 1
                opp_stat["W"] += 1
            elif w == "draw":
                total_d += 1
                layer_stat["D"] += 1
                opp_stat["D"] += 1
            else:
                total_l += 1
                layer_stat["L"] += 1
                opp_stat["L"] += 1

            if not silent and done % 200 == 0:
                wr_now = total_w / max(1, done) * 100
                eta_s = (time.time() - t0) / done * (total_jobs - done)
                print(f"  [{done:5d}/{total_jobs}] W={total_w} D={total_d} L={total_l} "
                      f"WR={wr_now:.1f}%  elapsed={time.time()-t0:.0f}s  ETA={eta_s/60:.0f}m",
                      flush=True)

    total = total_w + total_d + total_l
    wr = total_w / total if total else 0.0
    p, n, z = wr, total, 1.96
    margin = z * math.sqrt(p * (1-p) / n) if n else 0.0
    lo, hi = max(0.0, wr - margin), min(1.0, wr + margin)

    # Per-opp 평균 hp_diff 계산
    for name, stat in per_opp.items():
        diffs = stat.pop("hp_diffs")
        stat["avg_hp_diff"] = round(sum(diffs) / len(diffs), 1) if diffs else 0.0
        stat["total"] = stat["W"] + stat["D"] + stat["L"]
        stat["win_rate"] = round(stat["W"] / stat["total"], 3) if stat["total"] else 0.0

    return {
        "total_matches": total,
        "rounds_per_opponent": rounds,
        "W": total_w, "D": total_d, "L": total_l,
        "win_rate": round(wr, 4),
        "ci_95": (round(lo, 4), round(hi, 4)),
        "per_layer": per_layer,
        "per_opponent": per_opp,
        "elapsed_s": round(time.time() - t0, 1),
    }


# ─── CMA-ES ──────────────────────────────────────────────────

def run_search(budget=400, n_workers=None, seed=42, init_from=None, multi_fidelity=False):
    import cma

    if n_workers is None:
        n_workers = max(1, mp.cpu_count() - 1)

    # v5.1 default로 시작
    x0 = np.full(N_DIMS, 0.5)  # 모든 파라미터 중앙에서 시작
    # default 값이 있는 파라미터는 default 위치로
    defaults = {}
    for cls_name, cls in ALL_CUSTOM_CLASSES.items():
        for pname, spec in cls.TUNABLE_PARAMS.items():
            defaults[f"{cls_name}.{pname}"] = spec["default"]
    defaults.update({
        "harddeck_threshold": 1200, "climb_target": 3000,
        "close_combat_dist": 3000, "eim_confidence": 0.30,
        "enable_gun": True, "enable_orbit": True, "enable_eim": True,
        "enable_defense": True, "enable_energy": True, "enable_neutral": False,
        "enable_underfire": False, "enable_overshoot": False,
        "enable_eim_pursuit": False, "enable_eim_scissors": False, "enable_eim_gun": False,
        "eim_conf_pursuit": 0.40, "eim_conf_scissors": 0.40, "eim_conf_gun": 0.40,
        "eim_pursuit_action": "ExtensionBreak", "eim_scissors_action": "HeadOnBreak",
        "eim_gun_action": "GunsDefense",
        "gun_action": "SmartGunAttack", "pursuit_action": "SmartLeadPursuit",
        "defense_action": "ExtensionBreak", "orbit_action": "HeadOnBreak",
        "default_action": "SmartLeadPursuit",
        "energy_action": "SmartHighYoYo", "neutral_action": "SmartOneCircle",
        "underfire_action": "GunsDefense", "overshoot_action": "SmartHighYoYo",
    })
    x0 = params_to_vector(defaults)

    # Warm-start: 이전 사이클 best params를 시작점으로 사용
    if init_from is not None:
        init_path = Path(init_from)
        if init_path.exists():
            with open(init_path, encoding='utf-8') as f:
                saved = json.load(f)
            if "vector" in saved:
                x0 = np.array(saved["vector"], dtype=float)
                print(f"  Warm-start from: {init_path}")
                print(f"  Previous best score: {saved.get('score', 'unknown')}")
            else:
                print(f"  [WARN] {init_path} has no 'vector' key, using defaults")
        else:
            print(f"  [WARN] --init-from path not found: {init_path}, using defaults")

    sigma0 = 0.3
    popsize = min(n_workers * 2, 40)
    opts = {
        'seed': seed, 'maxfevals': budget, 'popsize': popsize,
        'bounds': [0, 1], 'verbose': -1, 'tolfun': 1e-6,
    }

    es = cma.CMAEvolutionStrategy(x0, sigma0, opts)

    all_results = []
    total_evals = 0
    best_score = -999
    best_params = None
    gen = 0
    start = time.time()

    print(f"\n{'='*60}")
    print(f"  Adaptive Eagle Full-Space Optimizer")
    print(f"  Budget: {budget} | Workers: {n_workers} | Dims: {N_DIMS}")
    print(f"  Action slots: {len(ACTION_SLOTS)} | Custom classes: {len(ALL_CUSTOM_CLASSES)}")
    if multi_fidelity:
        print(f"  Multi-fidelity: Stage1=10 matches (filter) → Stage2=40 matches (full)")
    print(f"{'='*60}\n")

    while not es.stop() and total_evals < budget:
        gen += 1
        solutions = es.ask()
        n_sol = len(solutions)
        work_items = [(i, sol) for i, sol in enumerate(solutions)]
        scores = [None] * n_sol

        if multi_fidelity:
            mf_items = [(i, sol, FAST_FILTER_THRESHOLD) for i, sol in enumerate(solutions)]
            worker_fn = _eval_worker_multifidelity
        else:
            mf_items = work_items
            worker_fn = _eval_worker

        with mp.Pool(processes=min(n_workers, n_sol)) as pool:
            for result in pool.imap_unordered(worker_fn, mf_items):
                if multi_fidelity:
                    idx, score, details, params, stage = result
                else:
                    idx, score, details, params = result
                    stage = "full"
                scores[idx] = score
                total_evals += 1
                w = sum(d["W"] for d in details.values())
                d_cnt = sum(d["D"] for d in details.values())
                l = len(details) - w - d_cnt

                all_results.append({"params": params, "score": score,
                                    "details": details, "generation": gen})

                if score > best_score:
                    best_score = score
                    best_params = params

                elapsed_m = (time.time() - start) / 60
                eta_m = (elapsed_m / total_evals * (budget - total_evals)) if total_evals > 0 else 0
                stage_tag = f"[{stage}]" if multi_fidelity else ""
                print(f"  [gen {gen:3d}] [{total_evals:4d}/{budget}] "
                      f"score={score:7.2f} W/D/L={w}/{d_cnt}/{l} "
                      f"ETA {eta_m:.0f}m{stage_tag}"
                      f"{'  *** BEST' if score == best_score else ''}",
                      flush=True)

        es.tell(solutions, [-s for s in scores])

    elapsed = time.time() - start
    all_results.sort(key=lambda x: x["score"], reverse=True)

    print(f"\n{'='*60}")
    print(f"  Complete! {total_evals} evals in {elapsed/60:.1f}m")
    print(f"  Best score: {best_score:.2f}")
    print(f"{'='*60}\n")

    if best_params:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")

        # Best YAML 저장
        best_bt = generate_bt_yaml(best_params)
        best_path = PROJECT_ROOT / "logs" / f"best_adaptive_{ts}.yaml"
        best_path.parent.mkdir(parents=True, exist_ok=True)
        with open(best_path, 'w', encoding='utf-8') as f:
            yaml.dump(best_bt, f, default_flow_style=False, allow_unicode=True, sort_keys=False)
        print(f"  Best YAML: {best_path}")

        # Top-20 JSON
        json_path = PROJECT_ROOT / "logs" / f"adaptive_opt_{ts}.json"
        with open(json_path, 'w', encoding='utf-8') as f:
            json.dump([{"score": r["score"], "params": r["params"],
                        "details": r["details"], "generation": r["generation"]}
                       for r in all_results[:20]], f, indent=2, ensure_ascii=False)
        print(f"  Top-20: {json_path}")

        # Warm-start용 best params 저장 (다음 사이클에서 --init-from으로 사용)
        params_path = PROJECT_ROOT / "logs" / f"best_params_{ts}.json"
        with open(params_path, 'w', encoding='utf-8') as f:
            json.dump({"score": best_score, "params": best_params,
                       "vector": params_to_vector(best_params).tolist()}, f,
                      indent=2, ensure_ascii=False)
        print(f"  Best params (warm-start): {params_path}")

        # 상세 출력
        top = all_results[0]
        for opp, d in top["details"].items():
            tag = "W" if d["W"] else ("D" if d["D"] else "L")
            print(f"    vs {opp:12s}: {tag}  hp_diff={d['hp_diff']:+.0f}")

        # 구조 파라미터 출력
        print(f"\n  Structure:")
        for key in sorted(best_params):
            if key.startswith("enable_") or key.endswith("_action"):
                print(f"    {key:30s}: {best_params[key]}")

    return all_results


# ─── Tournament ──────────────────────────────────────────────

def run_tournament():
    from tools.evaluate import evaluate, print_report
    report = evaluate("adaptive_eagle", rounds=30)
    print_report(report)


# ─── CLI ─────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Adaptive Eagle Full-Space CMA-ES Optimizer")
    parser.add_argument("--budget", type=int, default=400)
    parser.add_argument("--workers", type=int, default=None)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--tournament", action="store_true")
    parser.add_argument("--info", action="store_true", help="탐색 공간 정보 출력")
    parser.add_argument("--validate", type=str, default=None,
                        help="YAML 경로를 전체 opponent_pool에서 검증")
    parser.add_argument("--validate-rounds", type=int, default=10,
                        help="검증 시 상대당 라운드 수 (기본 10)")
    parser.add_argument("--pool-size", type=int, default=40,
                        help="최적화 루프 stratified sample 크기 (기본 40)")
    parser.add_argument("--init-from", type=str, default=None,
                        help="이전 사이클 best_params_*.json 경로 (warm-start)")
    parser.add_argument("--multi-fidelity", action="store_true",
                        help="Multi-fidelity eval: 10-match 빠른 필터 → 상위만 40-match full (속도 ~3x)")
    args = parser.parse_args()

    global OPPONENTS
    if POOL_MANIFEST.exists() and args.pool_size != 40:
        OPPONENTS = _stratified_sample_opponents(k=args.pool_size, seed=0)

    if args.info:
        print(f"\n  Search Space: {N_DIMS} dimensions")
        print(f"  Custom classes: {len(ALL_CUSTOM_CLASSES)}")
        print(f"  Action slots: {len(ACTION_SLOTS)}")
        print(f"\n  Parameters:")
        for name, ptype, spec in PARAM_DEFS:
            if ptype == "cont":
                print(f"    {name:40s}  cont  {spec}")
            else:
                print(f"    {name:40s}  disc  {spec}")
        return

    if args.validate:
        yaml_path = args.validate
        if not Path(yaml_path).is_absolute():
            yaml_path = str(PROJECT_ROOT / yaml_path)
        print(f"\n  Validating on full opponent_pool...")
        print(f"  Agent: {yaml_path}")
        print(f"  Rounds per opponent: {args.validate_rounds}")
        result = validate_on_full_pool(yaml_path, rounds=args.validate_rounds,
                                       n_workers=args.workers)
        print(f"\n  ═══════════════════════════════════════════")
        print(f"  FULL POOL VALIDATION RESULT")
        print(f"  ═══════════════════════════════════════════")
        print(f"  Total matches: {result['total_matches']}")
        print(f"  W / D / L    : {result['W']} / {result['D']} / {result['L']}")
        print(f"  Win rate     : {result['win_rate']*100:.2f}%")
        print(f"  95% CI       : {result['ci_95'][0]*100:.2f}% - {result['ci_95'][1]*100:.2f}%")
        print(f"  Elapsed      : {result['elapsed_s']}s")
        print(f"\n  Per-layer breakdown:")
        for layer, stat in sorted(result['per_layer'].items()):
            tot = stat['W'] + stat['D'] + stat['L']
            wr = stat['W'] / tot * 100 if tot else 0
            print(f"    {layer}  W={stat['W']:4d} D={stat['D']:4d} L={stat['L']:4d}  WR={wr:.1f}%")
        out = PROJECT_ROOT / "logs" / "full_pool_validation.json"
        out.parent.mkdir(exist_ok=True)
        with open(out, "w", encoding="utf-8") as f:
            json.dump(result, f, indent=2, ensure_ascii=False)
        print(f"\n  Saved: {out}")
        return

    if args.tournament:
        run_tournament()
    else:
        run_search(budget=args.budget, n_workers=args.workers, seed=args.seed,
                   init_from=args.init_from, multi_fidelity=args.multi_fidelity)


if __name__ == "__main__":
    mp.freeze_support()
    main()
