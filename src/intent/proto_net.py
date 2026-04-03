"""
proto_net.py — Prototypical Network for Enemy Intent Recognition

N-way K-shot 메타 학습:
  - N: intent class 수 (최대 5)
  - K: support shot 수 (기본 5)
  - Q: query 수 per class (기본 15)

훈련 루프:
  episode 샘플링 → prototype 계산 → query distance → loss
"""

import torch
import torch.nn as nn
import torch.nn.functional as F
import numpy as np
from pathlib import Path
from typing import Optional

from .encoder import TacticalEncoder, OBS_DIM


# ──────────────────────────────────────────────
# Intent Labels
# ──────────────────────────────────────────────

INTENT_CLASSES = ["GUN_ATTACK", "PURSUIT", "DEFENSIVE", "ENERGY", "NEUTRAL_CIRCLE", "NEUTRAL_SCISSORS"]
INTENT_TO_IDX  = {c: i for i, c in enumerate(INTENT_CLASSES)}
IDX_TO_INTENT  = {i: c for i, c in enumerate(INTENT_CLASSES)}

# active_node → intent 매핑 (ground truth 레이블 생성용)
NODE_TO_INTENT = {
    # Standard nodes
    "GunAttack":         "GUN_ATTACK",
    "PNAttack":          "GUN_ATTACK",   # golden custom
    "ViperStrike":       "GUN_ATTACK",   # viper1 custom
    "LeadPursuit":       "PURSUIT",
    "PurePursuit":       "PURSUIT",
    "Pursue":            "PURSUIT",
    "PNPursuit":         "PURSUIT",      # golden custom
    "Accelerate":        "PURSUIT",      # viper1 custom
    "LagPursuit":        "NEUTRAL_CIRCLE",   # HABFM 선회 교전
    "OneCircleFight":    "NEUTRAL_CIRCLE",   # HABFM 1-circle turn fight
    "BreakTurn":         "DEFENSIVE",
    "DefensiveManeuver": "DEFENSIVE",
    "DefensiveSpiral":   "DEFENSIVE",
    "BarrelRoll":        "DEFENSIVE",
    "HighYoYo":          "ENERGY",
    "ClimbingTurn":      "ENERGY",
    "AltitudeAdvantage": "ENERGY",
    "ClimbTo":           "ENERGY",
    # viper1 custom
    "EnergyManeuver":    "ENERGY",
    # golden custom
    "EnergyRecovery":    "ENERGY",
    # alpha2 / archetypes custom — UNKNOWN BFM 교착/이탈
    "ScissorsAccel":     "NEUTRAL_SCISSORS",
    "ReengageClimb":     "NEUTRAL_SCISSORS",
}


def node_to_intent(node: str) -> Optional[str]:
    """active_node 문자열 → intent class. 매핑 없으면 None."""
    clean = node.strip('"').strip("'")
    return NODE_TO_INTENT.get(clean)


# ──────────────────────────────────────────────
# Episode Dataset
# ──────────────────────────────────────────────

class EpisodeDataset:
    """
    메타데이터 CSV에서 추출한 window-level 샘플 저장소.
    각 샘플: (window_tensor: (K, OBS_DIM), intent_label: str)
    """

    def __init__(self, window_size: int = 20):
        self.window_size = window_size
        self.samples: dict[str, list[torch.Tensor]] = {c: [] for c in INTENT_CLASSES}

    def add(self, window: torch.Tensor, intent: str):
        if intent in self.samples:
            self.samples[intent].append(window)

    def class_counts(self) -> dict[str, int]:
        return {c: len(v) for c, v in self.samples.items()}

    def sample_episode(
        self,
        n_way: int = 5,
        k_shot: int = 5,
        n_query: int = 15,
        classes: Optional[list[str]] = None,
        max_per_class: int = 0,
    ) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor, torch.Tensor]:
        """
        N-way K-shot 에피소드 샘플링.

        Returns:
            support_x: (N, K, obs_dim)
            support_y: (N,)  — class index
            query_x:   (N*Q, obs_dim... wait, (N*Q, K, obs_dim))
            query_y:   (N*Q,)
        """
        # max_per_class cap: 균형 샘플링 (0=무제한)
        if max_per_class > 0:
            pools = {c: self.samples[c][:max_per_class] for c in INTENT_CLASSES}
        else:
            pools = {c: self.samples[c] for c in INTENT_CLASSES}

        available = [c for c in INTENT_CLASSES
                     if len(pools[c]) >= k_shot + n_query]
        if len(available) < n_way:
            raise ValueError(
                f"에피소드 샘플링 불가: 사용 가능 클래스 {len(available)} < {n_way}.\n"
                f"클래스별 샘플 수: {self.class_counts()}"
            )
        if classes is None:
            chosen = list(np.random.choice(available, n_way, replace=False))
        else:
            chosen = classes[:n_way]

        sup_x, sup_y, qry_x, qry_y = [], [], [], []
        for local_idx, cls in enumerate(chosen):
            pool = pools[cls]
            perm = np.random.permutation(len(pool))
            sup_idxs = perm[:k_shot]
            qry_idxs = perm[k_shot:k_shot + n_query]

            for i in sup_idxs:
                sup_x.append(pool[i])
            sup_y.extend([local_idx] * k_shot)
            for i in qry_idxs:
                qry_x.append(pool[i])
            qry_y.extend([local_idx] * n_query)

        return (
            torch.stack(sup_x),                         # (N*K, window, obs)
            torch.tensor(sup_y, dtype=torch.long),      # (N*K,)
            torch.stack(qry_x),                         # (N*Q, window, obs)
            torch.tensor(qry_y, dtype=torch.long),      # (N*Q,)
        )


# ──────────────────────────────────────────────
# Prototypical Network
# ──────────────────────────────────────────────

class ProtoNet(nn.Module):
    """
    Prototypical Network (Snell et al., 2017).
    prototype = class별 support embedding 평균.
    분류 = query embedding과 가장 가까운 prototype.
    """

    def __init__(self, encoder: TacticalEncoder, temperature: float = 1.0):
        super().__init__()
        self.encoder = encoder
        self.temperature = nn.Parameter(torch.tensor(temperature))
        # 추론용 prototype 캐시 (학습 후 저장)
        self._prototypes: Optional[dict[str, torch.Tensor]] = None

    # ── 학습 ────────────────────────────────

    def episode_loss(
        self,
        sup_x: torch.Tensor,   # (N*K, window_len, obs_dim)
        sup_y: torch.Tensor,   # (N*K,)
        qry_x: torch.Tensor,   # (N*Q, window_len, obs_dim)
        qry_y: torch.Tensor,   # (N*Q,)
    ) -> tuple[torch.Tensor, float]:
        """단일 에피소드 loss + accuracy."""
        # Encode
        sup_emb = self.encoder(sup_x)   # (N*K, embed_dim)
        qry_emb = self.encoder(qry_x)   # (N*Q, embed_dim)

        # Prototype 계산
        n_way = sup_y.max().item() + 1
        protos = []
        for c in range(int(n_way)):
            mask = sup_y == c
            protos.append(sup_emb[mask].mean(0))
        protos = torch.stack(protos)    # (N, embed_dim)

        # Euclidean distance → scaled logits
        dists = torch.cdist(qry_emb, protos)      # (N*Q, N)
        logits = -dists / self.temperature.abs()  # (N*Q, N)

        loss = F.cross_entropy(logits, qry_y)
        acc  = (logits.argmax(-1) == qry_y).float().mean().item()
        return loss, acc

    # ── 추론용 prototype 빌드/저장 ───────────

    def build_prototypes(
        self,
        dataset: EpisodeDataset,
        n_samples_per_class: int = 200,
    ) -> dict[str, torch.Tensor]:
        """
        전체 데이터셋에서 class별 prototype 계산.
        학습 완료 후 1회 호출하여 _prototypes에 캐시.
        """
        self.encoder.eval()
        protos = {}
        with torch.no_grad():
            for cls, windows in dataset.samples.items():
                if not windows:
                    continue
                idxs = np.random.choice(
                    len(windows),
                    min(n_samples_per_class, len(windows)),
                    replace=False,
                )
                batch = torch.stack([windows[i] for i in idxs])
                embs  = self.encoder(batch)
                protos[cls] = embs.mean(0)   # (embed_dim,)
        self._prototypes = protos
        return protos

    def predict(self, window: torch.Tensor) -> tuple[str, dict[str, float]]:
        """
        window: (K, obs_dim) 단일 텐서
        Returns: (predicted_intent, {class: confidence})
        """
        if self._prototypes is None:
            raise RuntimeError("build_prototypes()를 먼저 호출하세요.")
        self.encoder.eval()
        with torch.no_grad():
            emb = self.encoder(window.unsqueeze(0)).squeeze(0)  # (embed_dim,)
        classes = list(self._prototypes.keys())
        protos  = torch.stack([self._prototypes[c] for c in classes])
        dists   = torch.norm(emb.unsqueeze(0) - protos, dim=-1)  # (N,)
        logits  = -dists
        probs   = F.softmax(logits, dim=-1).tolist()
        conf    = {c: float(p) for c, p in zip(classes, probs)}
        pred    = classes[int(dists.argmin())]
        return pred, conf

    # ── 체크포인트 ────────────────────────────

    def save(self, path: str):
        data = {
            "encoder_state": self.encoder.state_dict(),
            "temperature":   self.temperature.item(),
            "prototypes":    self._prototypes,
        }
        torch.save(data, path)
        print(f"[ProtoNet] 저장: {path}")

    @classmethod
    def load(cls, path: str, encoder_kwargs: dict = None) -> "ProtoNet":
        data = torch.load(path, map_location="cpu", weights_only=False)
        enc  = TacticalEncoder(**(encoder_kwargs or {}))
        enc.load_state_dict(data["encoder_state"])
        net  = cls(enc, temperature=data["temperature"])
        net._prototypes = data["prototypes"]
        print(f"[ProtoNet] 로드: {path}")
        return net


# ──────────────────────────────────────────────
# Training Loop
# ──────────────────────────────────────────────

def train_proto_net(
    dataset: EpisodeDataset,
    n_episodes: int = 2000,
    n_way: int = 5,
    k_shot: int = 5,
    n_query: int = 15,
    lr: float = 1e-3,
    eval_every: int = 200,
    save_path: Optional[str] = None,
    hidden_dim: int = 128,
    embed_dim: int = 64,
    max_per_class: int = 0,
) -> ProtoNet:
    """end-to-end ProtoNet 학습."""

    encoder = TacticalEncoder(
        obs_dim=OBS_DIM,
        hidden_dim=hidden_dim,
        embed_dim=embed_dim,
    )
    model  = ProtoNet(encoder)
    optim  = torch.optim.Adam(model.parameters(), lr=lr, weight_decay=1e-4)
    sched  = torch.optim.lr_scheduler.StepLR(optim, step_size=500, gamma=0.5)

    best_acc  = 0.0
    acc_hist  = []

    print(f"\n[ProtoNet] 학습 시작: {n_episodes} episodes, {n_way}-way {k_shot}-shot")
    print(f"  데이터: {dataset.class_counts()}")

    for ep in range(1, n_episodes + 1):
        model.train()
        try:
            sup_x, sup_y, qry_x, qry_y = dataset.sample_episode(
                n_way=n_way, k_shot=k_shot, n_query=n_query,
                max_per_class=max_per_class,
            )
        except ValueError as e:
            print(f"  [경고] {e}")
            break

        optim.zero_grad()
        loss, acc = model.episode_loss(sup_x, sup_y, qry_x, qry_y)
        loss.backward()
        nn.utils.clip_grad_norm_(model.parameters(), 5.0)
        optim.step()
        sched.step()
        acc_hist.append(acc)

        if ep % eval_every == 0:
            avg_acc = np.mean(acc_hist[-eval_every:])
            print(f"  ep {ep:>5}/{n_episodes}  loss={loss.item():.4f}  "
                  f"acc={avg_acc:.3f}  lr={sched.get_last_lr()[0]:.6f}")
            if avg_acc > best_acc:
                best_acc = avg_acc
                if save_path:
                    model.build_prototypes(dataset)
                    model.save(save_path)

    # 최종 prototype 빌드
    model.build_prototypes(dataset)
    if save_path:
        model.save(save_path)

    print(f"\n[ProtoNet] 학습 완료. best_acc={best_acc:.3f}")
    return model
