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

# classify_unknown_sub() 결과 → intent 힌트 (active_node 매핑 없을 때 폴백)
BFM_TO_INTENT_HINT = {
    "UNK_SCISSORS":     "NEUTRAL_SCISSORS",   # UNKNOWN 교착 → 선회 교착
    "UNK_DISENGAGING":  "NEUTRAL_SCISSORS",   # UNKNOWN 이탈 → 선회 교착 (재접근 쌍)
    "UNK_NEAR_OFF":     "GUN_ATTACK",         # UNKNOWN 공격직전 → GUN_ATTACK 전조
}


# ──────────────────────────────────────────────
# Manifest 로드 (archetype → intent 매핑)
# ──────────────────────────────────────────────

def load_manifest() -> dict[str, str]:
    """agent_name → intent_class 딕셔너리 반환."""
    if not MANIFEST_PATH.exists():
        print(f"[경고] manifest 없음: {MANIFEST_PATH}")
        return {}
    with open(MANIFEST_PATH, encoding="utf-8") as f:
        data = json.load(f)
    return {name: info["intent"] for name, info in data["agents"].items()}


# ──────────────────────────────────────────────
# CSV 로드 + window 추출
# ──────────────────────────────────────────────

def csv_to_windows(
    csv_path: Path,
    agent_intent_map: dict[str, str],
    window_size: int = WINDOW_SIZE,
    stride: int = STRIDE,
) -> list[tuple[torch.Tensor, str]]:
    """
    단일 CSV → (window_tensor, intent_label) 리스트.

    레이블 전략:
      - step-level: dominant active_node in window → NODE_TO_INTENT
      - 폴백: tree_name → manifest intent
      - 둘 다 없으면 스킵
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

        # tree_name 기반 폴백 intent
        tree_name = adf["tree_name"].iloc[0] if "tree_name" in adf.columns else ""
        fallback_intent = agent_intent_map.get(tree_name)

        # active_node 컬럼 정리
        nodes = adf["active_node"].fillna("").tolist() if "active_node" in adf.columns else []

        # sliding window
        for start in range(0, len(adf) - window_size + 1, stride):
            end = start + window_size
            window_rows = adf.iloc[start:end]

            # ── 레이블 결정 ──────────────────
            # BFM 서브분류 계산 (UNKNOWN ≥ 30% 시 우선 적용)
            bfm_vals = window_rows["bfm_situation"].fillna("").tolist() \
                if "bfm_situation" in window_rows.columns else []
            unk_count = sum(1 for b in bfm_vals if b == "UNKNOWN")
            bfm_intent = None
            if unk_count >= window_size * 0.3:   # 30%+ UNKNOWN → 전술 상황 우선
                ata_vals = [float(r.get("ata_deg", 0.0)) * 180.0
                            for r in window_rows.to_dict("records")
                            if str(r.get("bfm_situation", "")) == "UNKNOWN"]
                closure_vals = [float(r.get("closure_rate_kts", 0.0))
                                for r in window_rows.to_dict("records")
                                if str(r.get("bfm_situation", "")) == "UNKNOWN"]
                if ata_vals:
                    mid = len(ata_vals) // 2
                    median_ata = sorted(ata_vals)[mid]
                    median_closure = sorted(closure_vals)[mid]
                    sub = classify_unknown_sub(median_ata, median_closure)
                    bfm_intent = BFM_TO_INTENT_HINT.get(sub)

            # 1) UNKNOWN ≥ 30% → BFM 서브분류 우선 (전술 상황 기반 레이블)
            if bfm_intent:
                intent = bfm_intent
            else:
                # 2) active_node 다수결
                window_nodes = nodes[start:end]
                intent_votes = Counter()
                for nd in window_nodes:
                    mapped = node_to_intent(nd)
                    if mapped:
                        intent_votes[mapped] += 1

                if intent_votes:
                    intent = intent_votes.most_common(1)[0][0]
                elif fallback_intent:
                    intent = fallback_intent
                else:
                    continue   # 레이블 불명 → 스킵

            # ── feature 텐서 빌드 ─────────────
            tensors = []
            valid = True
            for _, row in window_rows.iterrows():
                obs = row.to_dict()
                # UNKNOWN BFM → classify_unknown_sub으로 세분화 (인코딩 정밀도 향상)
                if str(obs.get("bfm_situation", "")) == "UNKNOWN":
                    ata = float(obs.get("ata_deg", 0.0)) * 180.0
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


def load_all_windows(
    meta_dir: Path,
    agent_intent_map: dict[str, str],
    max_files: int = 0,
    window_size: int = WINDOW_SIZE,
    stride: int = STRIDE,
) -> EpisodeDataset:
    """meta_dir의 모든 CSV를 읽어 EpisodeDataset 구성."""
    csv_files = sorted(meta_dir.glob("*_meta.csv"))
    if max_files:
        csv_files = csv_files[:max_files]

    print(f"\n[load_all_windows] CSV {len(csv_files)}개 처리 중...")
    dataset = EpisodeDataset(window_size=window_size)
    total_windows = 0

    for i, csv_path in enumerate(csv_files):
        pairs = csv_to_windows(csv_path, agent_intent_map, window_size, stride)
        for tensor, intent in pairs:
            dataset.add(tensor, intent)
            total_windows += 1
        if (i + 1) % 100 == 0:
            print(f"  {i+1}/{len(csv_files)} ... {total_windows}개 windows")

    print(f"\n  완료: {total_windows}개 windows")
    counts = dataset.class_counts()
    for cls in INTENT_CLASSES:
        n = counts.get(cls, 0)
        bar = "█" * (n // 50)
        print(f"  {cls:<16} {n:>6}개  {bar}")

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
    ap.add_argument("--dry-run",    action="store_true", help="데이터 통계만 출력, 학습 안 함")
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
    dataset = load_all_windows(
        meta_dir=meta_dir,
        agent_intent_map=agent_intent_map,
        max_files=args.max_files,
        window_size=args.window,
        stride=args.stride,
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
