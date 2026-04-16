"""
train_intent_model.py — EIM (Enemy Intent Model) 학습 파이프라인

Step 1: 메타데이터 CSV 로드 + window 추출 + intent 레이블 생성
Step 2: EpisodeDataset 구성
Step 3: ProtoNet 메타 학습
Step 4: 모델 저장 (models/intent_model.pt)

Intent 레이블 전략 (우선순위):
  1. active_node → NODE_TO_INTENT 매핑 (step-level, 직접 ground truth)
  2. archetype manifest의 tree_name → intent (파일명 기반, 폴백)
  3. 둘 다 없으면 해당 window 스킵

Usage:
    python tools/train_intent_model.py
    python tools/train_intent_model.py --meta-dir logs/metadata --episodes 2000
    python tools/train_intent_model.py --dry-run   # 데이터 통계만 출력
"""

import sys
import json
import argparse
import numpy as np
import pandas as pd
from pathlib import Path
from collections import Counter

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.intent.encoder import obs_dict_to_tensor, CONT_FEATURES, BOOL_FEATURES, BFM_CLASSES, OBS_DIM
from src.intent.proto_net import (
    ProtoNet, EpisodeDataset, train_proto_net,
    INTENT_CLASSES, NODE_TO_INTENT, node_to_intent,
)
from tools.analyze_metadata import classify_unknown_sub

import torch

# ──────────────────────────────────────────────
# 설정
# ──────────────────────────────────────────────

META_DIR      = PROJECT_ROOT / "logs" / "metadata"
MANIFEST_PATH = PROJECT_ROOT / "examples" / "archetypes" / "manifest.json"
MODEL_DIR     = PROJECT_ROOT / "models"
MODEL_PATH    = MODEL_DIR / "intent_model.pt"

WINDOW_SIZE   = 20   # K-step window
STRIDE        = 5    # window 추출 stride (겹침 허용)

# BFM 상황 → intent 직접 매핑 (1차 레이블 소스)
BFM_TO_INTENT = {
    "OBFM":  "PURSUIT",           # 공격 우위 → 추격
    "DBFM":  "DEFENSIVE",         # 방어 상황 → 방어
    "HABFM": "NEUTRAL_CIRCLE",    # 정면 교전 → 선회 중립
}

# UNKNOWN 서브분류 → intent
UNKNOWN_SUB_TO_INTENT = {
    "UNK_NEAR_OFF":    "GUN_ATTACK",        # 공격 직전 → GUN_ATTACK 전조
    "UNK_SCISSORS":    "NEUTRAL_SCISSORS",  # 교착
    "UNK_DISENGAGING": "NEUTRAL_SCISSORS",  # 이탈
}

# GunAttack 노드 집합 (BFM보다 우선)
GUN_NODES = {"GunAttack", "PNAttack", "ViperStrike"}

# 에너지 기동 노드 집합 (BFM보다 우선)
ENERGY_NODES = {"HighYoYo", "ClimbingTurn", "AltitudeAdvantage", "ClimbTo",
                "EnergyManeuver", "EnergyRecovery"}


# ──────────────────────────────────────────────
# Manifest 로드 (archetype → intent 매핑)
# ──────────────────────────────────────────────

def load_manifest() -> dict[str, str]:
    """agent_name → intent_class 딕셔너리 반환.

    manifest의 NEUTRAL → NEUTRAL_CIRCLE, SCISSORS → NEUTRAL_SCISSORS 으로 변환
    (manifest 레거시 이름 vs. INTENT_CLASSES 실제 이름 동기화).
    """
    _ALIAS = {"NEUTRAL": "NEUTRAL_CIRCLE", "SCISSORS": "NEUTRAL_SCISSORS"}
    if not MANIFEST_PATH.exists():
        print(f"[경고] manifest 없음: {MANIFEST_PATH}")
        return {}
    with open(MANIFEST_PATH, encoding="utf-8") as f:
        data = json.load(f)
    return {
        name: _ALIAS.get(info["intent"], info["intent"])
        for name, info in data["agents"].items()
    }


# ──────────────────────────────────────────────
# CSV 로드 + window 추출
# ──────────────────────────────────────────────

def _step_intent(node: str, bfm: str, ata_deg: float, closure_kts: float,
                 in_wez: bool = False) -> str:
    """
    단일 step의 intent 결정.

    우선순위:
      1. GUN 노드 → GUN_ATTACK
      2. ENERGY 노드 → ENERGY
      3. BFM 상황 → PURSUIT / DEFENSIVE / NEUTRAL_CIRCLE
      4. UNKNOWN BFM → classify_unknown_sub → NEUTRAL_SCISSORS / GUN_ATTACK
      5. 없으면 빈 문자열
    """
    clean_node = node.strip('"').strip("'")
    if clean_node in GUN_NODES:
        return "GUN_ATTACK"
    if clean_node in ENERGY_NODES:
        return "ENERGY"
    mapped_bfm = BFM_TO_INTENT.get(bfm)
    if mapped_bfm:
        return mapped_bfm
    if bfm == "UNKNOWN":
        sub = classify_unknown_sub(ata_deg, closure_kts)
        return UNKNOWN_SUB_TO_INTENT.get(sub, "NEUTRAL_SCISSORS")
    return ""


def csv_to_windows(
    csv_path: Path,
    agent_intent_map: dict[str, str],
    window_size: int = WINDOW_SIZE,
    stride: int = STRIDE,
) -> list[tuple[torch.Tensor, str]]:
    """
    단일 CSV → (window_tensor, intent_label) 리스트.

    레이블 전략 (BFM 우선):
      - step-level: GUN 노드 > ENERGY 노드 > BFM 상황 > UNKNOWN 서브분류
      - window intent = step-level 다수결
      - 레이블 미확정 시 스킵
    """
    try:
        df = pd.read_csv(csv_path, low_memory=False)
    except Exception as e:
        print(f"  [오류] {csv_path.name}: {e}")
        return []

    results = []

    # 두 에이전트를 각각 처리
    for agent_id in df["agent_id"].unique():
        adf = df[df["agent_id"] == agent_id].reset_index(drop=True)
        if len(adf) < window_size:
            continue

        # manifest intent: tree_name → agent_intent_map 조회 (intent 전용 에이전트)
        tree_name = adf["tree_name"].iloc[0] if "tree_name" in adf.columns else ""
        manifest_intent = agent_intent_map.get(tree_name, "")

        # 컬럼 추출
        nodes    = adf["active_node"].fillna("").tolist()    if "active_node"    in adf.columns else [""] * len(adf)
        bfms     = adf["bfm_situation"].fillna("").tolist()  if "bfm_situation"  in adf.columns else [""] * len(adf)
        atas     = adf["ata_deg"].fillna(0.0).tolist()       if "ata_deg"        in adf.columns else [0.0] * len(adf)
        closures = adf["closure_rate_kts"].fillna(0.0).tolist() if "closure_rate_kts" in adf.columns else [0.0] * len(adf)
        # step-level intent 사전 계산
        step_intents = [
            _step_intent(nodes[i], bfms[i], float(atas[i]), float(closures[i]))
            for i in range(len(adf))
        ]

        # Option B: GunAttack 발동 직전 20스텝도 GUN_ATTACK으로 소급 레이블
        # 의미: 실제 사격 전 추격/조준 단계도 GUN_ATTACK intent로 포함
        GUN_PRECURSOR_STEPS = 20
        for i in range(len(step_intents)):
            if step_intents[i] == "GUN_ATTACK":
                for j in range(max(0, i - GUN_PRECURSOR_STEPS), i):
                    if step_intents[j] in ("PURSUIT", ""):
                        step_intents[j] = "GUN_ATTACK"

        # sliding window
        for start in range(0, len(adf) - window_size + 1, stride):
            end = start + window_size
            window_rows = adf.iloc[start:end]

            # ── 레이블 결정 ─────────────────────────────────────────
            # manifest intent 에이전트 (probe_gun_aggro, arch_gun_attack_* 등):
            #   step-level 다수결 대신 manifest intent를 ground truth로 사용.
            #   이 에이전트들은 설계상 단일 intent에 집중 → manifest가 더 정확한 레이블.
            if manifest_intent:
                intent = manifest_intent
            else:
                votes = Counter(s for s in step_intents[start:end] if s)
                if votes:
                    intent = votes.most_common(1)[0][0]
                else:
                    continue   # 레이블 미확정 → 스킵

            # ── feature 텐서 빌드 ─────────────
            tensors = []
            valid = True
            for _, row in window_rows.iterrows():
                obs = row.to_dict()
                # UNKNOWN BFM → classify_unknown_sub으로 세분화 (인코딩 정밀도 향상)
                if str(obs.get("bfm_situation", "")) == "UNKNOWN":
                    ata = float(obs.get("ata_deg", 0.0))
                    closure = float(obs.get("closure_rate_kts", 0.0))
                    obs["bfm_situation"] = classify_unknown_sub(ata, closure)
                try:
                    t = obs_dict_to_tensor(obs)
                    tensors.append(t)
                except Exception:
                    valid = False
                    break
            if not valid or len(tensors) != window_size:
                continue

            window_tensor = torch.stack(tensors)  # (K, OBS_DIM)
            results.append((window_tensor, intent))

    return results


CACHE_PATH = PROJECT_ROOT / "models" / "windows_cache.pt"


def load_all_windows(
    meta_dir: Path,
    agent_intent_map: dict[str, str],
    max_files: int = 0,
    window_size: int = WINDOW_SIZE,
    stride: int = STRIDE,
    cap_per_class: int = 0,
    force_rebuild: bool = False,
) -> EpisodeDataset:
    """meta_dir의 모든 CSV를 읽어 EpisodeDataset 구성.

    캐시 전략:
      - models/windows_cache.pt 존재 + 최신 CSV보다 신선하면 캐시 로드 (빠름)
      - 없거나 오래됐으면 CSV 전체 파싱 → 캐시 저장

    cap_per_class > 0: 각 클래스가 cap에 도달하면 해당 클래스 추가 중단.
    """
    csv_files = sorted(meta_dir.rglob("*_meta.csv"), reverse=True)  # 하위 디렉토리 포함 재귀 탐색
    if max_files:
        csv_files = csv_files[:max_files]

    # ── 캐시 유효성 검사 ──────────────────────────────────────
    if not force_rebuild and CACHE_PATH.exists() and csv_files:
        newest_csv_mtime = max(f.stat().st_mtime for f in csv_files[:10])
        cache_mtime = CACHE_PATH.stat().st_mtime
        if cache_mtime > newest_csv_mtime:
            print(f"\n[load_all_windows] 캐시 로드: {CACHE_PATH}")
            cached = torch.load(CACHE_PATH, map_location="cpu", weights_only=False)
            dataset = EpisodeDataset(window_size=window_size)
            dataset.samples = cached["samples"]
            counts = dataset.class_counts()
            total = sum(counts.values())
            print(f"  캐시에서 {total}개 windows 로드")
            for cls in INTENT_CLASSES:
                n = counts.get(cls, 0)
                bar = "█" * (n // 500)
                print(f"  {cls:<20} {n:>6}개  {bar}")
            return dataset

    # ── CSV 파싱 ─────────────────────────────────────────────
    print(f"\n[load_all_windows] CSV {len(csv_files)}개 파싱 중... (첫 실행 시 시간 소요)")
    dataset = EpisodeDataset(window_size=window_size)
    total_windows = 0

    for i, csv_path in enumerate(csv_files):
        pairs = csv_to_windows(csv_path, agent_intent_map, window_size, stride)
        for tensor, intent in pairs:
            if cap_per_class and len(dataset.samples.get(intent, [])) >= cap_per_class:
                continue
            dataset.add(tensor, intent)
            total_windows += 1

        if (i + 1) % 50 == 0:
            counts = dataset.class_counts()
            if cap_per_class:
                # 모든 클래스가 max_per_class(=cap//5) 이상이면 학습 준비 완료
                min_ok  = cap_per_class // 5
                ready   = sum(1 for c in INTENT_CLASSES if counts.get(c, 0) >= min_ok)
                mins    = {c: counts.get(c, 0) for c in INTENT_CLASSES}
                print(f"  {i+1}/{len(csv_files)} ... {total_windows}개 windows"
                      f"  (학습준비: {ready}/{len(INTENT_CLASSES)}, "
                      f"최소={min(mins.values())} GUN={mins.get('GUN_ATTACK',0)})")
                if ready == len(INTENT_CLASSES):
                    print("  → 전 클래스 학습 가능, 로딩 종료")
                    break
            else:
                print(f"  {i+1}/{len(csv_files)} ... {total_windows}개 windows")

    print(f"\n  완료: {total_windows}개 windows")
    counts = dataset.class_counts()
    for cls in INTENT_CLASSES:
        n = counts.get(cls, 0)
        bar = "█" * (n // 500)
        print(f"  {cls:<20} {n:>6}개  {bar}")

    # ── 캐시 저장 ─────────────────────────────────────────────
    torch.save({"samples": dataset.samples}, CACHE_PATH)
    print(f"  캐시 저장: {CACHE_PATH}")

    return dataset


# ──────────────────────────────────────────────
# 데이터 품질 검사
# ──────────────────────────────────────────────

def check_dataset_quality(dataset: EpisodeDataset, k_shot: int, n_query: int):
    """에피소드 샘플링 가능한지 확인."""
    min_required = k_shot + n_query
    insufficient = []
    for cls, windows in dataset.samples.items():
        if len(windows) < min_required:
            insufficient.append((cls, len(windows)))

    if insufficient:
        print(f"\n[경고] 샘플 부족 클래스 (필요: {min_required}개):")
        for cls, n in insufficient:
            print(f"  {cls}: {n}개 (부족)")
        print("\n  해결책:")
        print("  1. python tools/collect_phase1.py --probes  (프로브 에이전트 추가 수집)")
        print("  2. --stride 1 로 window 중첩 최대화")
        print("  3. --k-shot / --n-query 값 줄이기")
        return False
    return True


# ──────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser(description="Enemy Intent Model 학습")
    ap.add_argument("--meta-dir",   default=str(META_DIR))
    ap.add_argument("--model-path", default=str(MODEL_PATH))
    ap.add_argument("--episodes",   type=int,   default=2000)
    ap.add_argument("--n-way",      type=int,   default=5)
    ap.add_argument("--k-shot",     type=int,   default=5)
    ap.add_argument("--n-query",    type=int,   default=15)
    ap.add_argument("--window",     type=int,   default=WINDOW_SIZE)
    ap.add_argument("--stride",     type=int,   default=STRIDE)
    ap.add_argument("--max-files",  type=int,   default=0)
    ap.add_argument("--hidden-dim", type=int,   default=128)
    ap.add_argument("--embed-dim",  type=int,   default=64)
    ap.add_argument("--lr",            type=float, default=1e-3)
    ap.add_argument("--eval-every",    type=int,   default=200)
    ap.add_argument("--max-per-class", type=int,   default=5000,
                    help="클래스당 최대 샘플 수 cap (에피소드 균형 샘플링, 0=무제한)")
    ap.add_argument("--dry-run",       action="store_true", help="데이터 통계만 출력, 학습 안 함")
    ap.add_argument("--rebuild-cache", action="store_true", help="캐시 무시하고 CSV 재파싱")
    args = ap.parse_args()

    meta_dir = Path(args.meta_dir)
    if not meta_dir.exists():
        print(f"[오류] meta_dir 없음: {meta_dir}")
        sys.exit(1)

    MODEL_DIR.mkdir(parents=True, exist_ok=True)

    # ── Manifest 로드 ──────────────────────
    agent_intent_map = load_manifest()
    print(f"[manifest] {len(agent_intent_map)}개 에이전트 intent 매핑 로드")

    # ── 데이터 로드 ────────────────────────
    # cap_per_class: 로딩 중 각 클래스가 이 수에 도달하면 해당 클래스 추가 중단
    # max_per_class의 5배 정도 (에피소드 다양성 확보, 너무 크면 희소 클래스 도달 불가)
    load_cap = args.max_per_class * 5 if args.max_per_class else 0
    dataset = load_all_windows(
        meta_dir=meta_dir,
        agent_intent_map=agent_intent_map,
        max_files=args.max_files,
        window_size=args.window,
        stride=args.stride,
        cap_per_class=load_cap,
        force_rebuild=args.rebuild_cache,
    )

    if args.dry_run:
        print("\n[dry-run] 데이터 통계 출력 완료. 학습 생략.")
        return

    # ── 품질 검사 ──────────────────────────
    ok = check_dataset_quality(dataset, args.k_shot, args.n_query)
    if not ok:
        print("\n[경고] 데이터 부족. --dry-run으로 확인 후 수집을 늘리세요.")
        # 부족해도 일단 진행 (가능한 클래스만 사용)

    # ── 학습 ───────────────────────────────
    model = train_proto_net(
        dataset=dataset,
        n_episodes=args.episodes,
        n_way=args.n_way,
        k_shot=args.k_shot,
        n_query=args.n_query,
        lr=args.lr,
        eval_every=args.eval_every,
        save_path=args.model_path,
        hidden_dim=args.hidden_dim,
        embed_dim=args.embed_dim,
        max_per_class=args.max_per_class,
    )

    # ── 검증: 전체 prototype 분류 정확도 ──
    print("\n[검증] Prototype 분류 정확도 (전체 샘플)")
    model.encoder.eval()
    correct, total = 0, 0
    for true_intent, windows in dataset.samples.items():
        for w in windows:
            pred, _ = model.predict(w)
            if pred == true_intent:
                correct += 1
            total += 1
    if total:
        print(f"  전체 정확도: {correct}/{total} = {correct/total:.3f}")

    print(f"\n[완료] 모델 저장: {args.model_path}")
    print("\n다음 단계:")
    print("  python tools/train_intent_model.py --dry-run   # 데이터 확인")
    print("  from src.intent import OnlineIntentTracker")
    print("  tracker = OnlineIntentTracker.from_file('models/intent_model.pt')")


if __name__ == "__main__":
    main()
