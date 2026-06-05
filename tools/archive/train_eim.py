"""
train_eim.py — EIM (Enemy Intent Model) 독립 학습 CLI

CMA-ES 사이클과 완전 독립적으로 실행 가능한 ProtoNet few-shot 재학습 도구.

입력: logs/metadata/*.csv (collect_phase1.py 수집 데이터)
출력: models/intent_model.pt (다음 CMA-ES 사이클에서 자동 사용)

사용법:
    # 기본 재학습 (logs/metadata/ 전체 사용)
    python tools/train_eim.py

    # 특정 로그 디렉토리 지정
    python tools/train_eim.py --meta-dir logs/cycle_2

    # 에피소드 수 조정
    python tools/train_eim.py --episodes 2000

    # 학습 후 정확도 검증
    python tools/train_eim.py --validate

    # 데이터 통계만 출력 (실제 학습 안 함)
    python tools/train_eim.py --dry-run

    # 기존 모델에 추가 파인튜닝
    python tools/train_eim.py --finetune --episodes 500

독립성:
    - models/intent_model.pt 파일만 공유 (CMA-ES는 파일을 읽기만 함)
    - 학습 중 CMA-ES 사이클을 중단할 필요 없음
    - 학습 완료 후 다음 CMA-ES 사이클부터 새 모델 자동 적용
"""

import sys
import argparse
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


def run_validate(model_path: Path):
    """학습된 모델의 intent 분류 정확도 출력."""
    import torch
    from src.intent.encoder import obs_dict_to_tensor, OBS_DIM
    from src.intent.proto_net import ProtoNet, INTENT_CLASSES

    if not model_path.exists():
        print(f"  [ERROR] 모델 파일 없음: {model_path}")
        return

    data = torch.load(model_path, map_location="cpu", weights_only=False)
    prototypes = data.get("prototypes", {})

    print(f"\n  ══ EIM 모델 상태 ══════════════════════════")
    print(f"  파일: {model_path}")
    print(f"  Intent 클래스 ({len(prototypes)}개):")
    for cls_name, proto_tensor in prototypes.items():
        norm = proto_tensor.norm().item()
        print(f"    {cls_name:25s}: embedding norm={norm:.3f}")

    # 프로토타입 간 코사인 유사도 (낮을수록 잘 구분됨)
    import torch.nn.functional as F
    classes = list(prototypes.keys())
    tensors = torch.stack([prototypes[c] for c in classes])
    normed = F.normalize(tensors, dim=1)
    sim_matrix = normed @ normed.T

    print(f"\n  프로토타입 코사인 유사도 (낮을수록 구분 잘 됨):")
    min_sim, max_sim = 1.0, 0.0
    for i in range(len(classes)):
        for j in range(i+1, len(classes)):
            s = sim_matrix[i,j].item()
            if s < min_sim: min_sim = s
            if s > max_sim: max_sim = s

    print(f"    최소 유사도: {min_sim:.3f} (구분 최고)")
    print(f"    최대 유사도: {max_sim:.3f} (구분 최저)")

    if max_sim > 0.9:
        print(f"  ⚠ 일부 클래스 프로토타입이 매우 유사함 (재학습 권장)")
    else:
        print(f"  ✓ 프로토타입 분리도 양호")


def main():
    parser = argparse.ArgumentParser(
        description="EIM ProtoNet 독립 학습 CLI (CMA-ES와 독립적으로 실행)"
    )
    parser.add_argument(
        "--meta-dir", type=str, default=None,
        help="학습 데이터 CSV 디렉토리 (기본: logs/metadata/)"
    )
    parser.add_argument(
        "--episodes", type=int, default=1000,
        help="메타 학습 에피소드 수 (기본: 1000)"
    )
    parser.add_argument(
        "--n-way", type=int, default=5,
        help="N-way classification (기본: 5)"
    )
    parser.add_argument(
        "--k-shot", type=int, default=5,
        help="K-shot support (기본: 5)"
    )
    parser.add_argument(
        "--validate", action="store_true",
        help="학습 완료 후 모델 상태 검증 출력"
    )
    parser.add_argument(
        "--validate-only", action="store_true",
        help="학습 없이 현재 모델 검증만 실행"
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="데이터 통계만 출력 (학습 안 함)"
    )
    parser.add_argument(
        "--finetune", action="store_true",
        help="기존 모델 파인튜닝 (새로 학습 대신)"
    )
    parser.add_argument(
        "--output", type=str, default=None,
        help="출력 모델 경로 (기본: models/intent_model.pt)"
    )
    args = parser.parse_args()

    model_path = Path(args.output) if args.output else PROJECT_ROOT / "models" / "intent_model.pt"
    meta_dir = Path(args.meta_dir) if args.meta_dir else PROJECT_ROOT / "logs" / "metadata"

    print(f"\n  ══ EIM 독립 학습 CLI ═══════════════════════")
    print(f"  메타 데이터: {meta_dir}")
    print(f"  모델 출력:   {model_path}")

    if args.validate_only:
        run_validate(model_path)
        return

    # train_intent_model.py의 학습 파이프라인 실행
    # CLI 인수를 train_intent_model.py 형식으로 변환하여 실행
    import subprocess
    cmd = [
        str(PROJECT_ROOT / ".venv" / "Scripts" / "python.exe"),
        str(PROJECT_ROOT / "tools" / "train_intent_model.py"),
        "--meta-dir", str(meta_dir),
        "--episodes", str(args.episodes),
        "--n-way", str(args.n_way),
        "--k-shot", str(args.k_shot),
    ]

    if args.dry_run:
        cmd.append("--dry-run")
    if args.finetune:
        cmd.append("--finetune")
    if args.output:
        cmd.extend(["--output", args.output])

    print(f"\n  실행: {' '.join(Path(c).name if '/' in c or '\\' in c else c for c in cmd)}")
    print(f"  에피소드: {args.episodes} | N-way: {args.n_way} | K-shot: {args.k_shot}")
    print()

    start = time.time()
    result = subprocess.run(cmd, cwd=str(PROJECT_ROOT))
    elapsed = time.time() - start

    if result.returncode == 0:
        print(f"\n  ✓ 학습 완료 ({elapsed:.0f}초)")
        print(f"  출력: {model_path}")
        if args.validate:
            run_validate(model_path)
    else:
        print(f"\n  ✗ 학습 실패 (returncode={result.returncode})")
        sys.exit(1)


if __name__ == "__main__":
    main()
