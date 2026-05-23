"""β path — Dispatch policy 학습 (REINFORCE).

Policy: 13 obs → 6 mode softmax (PN, Corner, YoYo, LDT, T, IPA)
Mode 선택 → optimal_control({mode: 1.0}) → u_star → quantize → BT action.

학습 환경:
    - SingleCombatEnv (1v1/NoWeapon/bt_vs_bt)
    - 적: aggressive (BT YAML 로 fixed-policy)
    - 우리 BT 의 Theorem 분기 자리 만 NN 으로 대체 (다른 분기는 closed-form 유지)
    - reward: ∫(D_us - D_them) dt + HP delta terminal

Output:
    models/dispatch_pg_aggressive.npz (NN weights as numpy)
    학습 progress: logs/train_pg/

Usage:
    python scripts/train_dispatch_pg.py --episodes 50 --lr 1e-3
"""

from __future__ import annotations

# 본 skeleton 은 β-1 단계의 *환경 설정 + 학습 루프 골격* 만 정의.
# β-2 에서 본격 학습 실행. β-3 에서 trained weights → numpy 추출.

import argparse
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_PROJECT_ROOT / "src"))


def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("--episodes", type=int, default=50)
    p.add_argument("--lr", type=float, default=1e-3)
    p.add_argument("--gamma", type=float, default=0.99, help="discount factor")
    p.add_argument("--hidden", type=int, default=64)
    p.add_argument("--save", type=str, default="models/dispatch_pg_aggressive.npz")
    p.add_argument("--log_dir", type=str, default="logs/train_pg")
    p.add_argument("--opponent", type=str, default="aggressive")
    p.add_argument("--seed", type=int, default=42)
    return p.parse_args()


def main():
    args = parse_args()

    # ── Setup ──
    import torch
    import torch.nn as nn
    import torch.optim as optim
    import numpy as np
    torch.manual_seed(args.seed)
    np.random.seed(args.seed)

    log_dir = Path(args.log_dir); log_dir.mkdir(parents=True, exist_ok=True)
    save_path = Path(args.save); save_path.parent.mkdir(parents=True, exist_ok=True)

    # ── Policy ──
    OBS_DIM = 13     # our existing 13 obs (per docs)
    N_MODES = 6      # pn, corner, yoyo, ldt, T, ipa
    MODE_NAMES = ["pn", "corner", "yoyo", "ldt", "T", "ipa"]

    class DispatchPolicy(nn.Module):
        def __init__(self, obs_dim=OBS_DIM, hidden=args.hidden, n_modes=N_MODES):
            super().__init__()
            self.net = nn.Sequential(
                nn.Linear(obs_dim, hidden), nn.ReLU(),
                nn.Linear(hidden, hidden), nn.ReLU(),
                nn.Linear(hidden, n_modes),
            )
        def forward(self, obs):
            logits = self.net(obs)
            return torch.softmax(logits, dim=-1)

    policy = DispatchPolicy()
    optimizer = optim.Adam(policy.parameters(), lr=args.lr)
    print(f"[train] Policy: {OBS_DIM} → {args.hidden} → {args.hidden} → {N_MODES} modes")
    print(f"[train] Episodes: {args.episodes}, lr: {args.lr}, opponent: {args.opponent}")

    # ── Environment + BT integration ──
    # 본 skeleton 은 *학습 루프 골격*만 정의. β-2 에서 실제 매치 실행 통합.
    # 필요 sub-task:
    #   1. SingleCombatEnv reset → obs_pair (us, them)
    #   2. our_obs → 13-feature → policy → mode selection → optimal_control → u_star → bin
    #   3. their_obs → aggressive BT (YAML loader 또는 fixed policy) → u_e
    #   4. env.step(action_pair) → next obs, done
    #   5. reward = D_us - D_them per tick + terminal HP delta
    #   6. REINFORCE: loss = -Σ log π(a|s) · G_t
    print("\n[train] β-1 skeleton ready. β-2 에서 sub-tasks 1-6 통합 + 본 학습 실행.")
    print(f"[train] Save target: {save_path}")


if __name__ == "__main__":
    main()
