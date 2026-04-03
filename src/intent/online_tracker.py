"""
online_tracker.py — OnlineIntentTracker

교전 중 실시간 적 의도 추적:
  - 슬라이딩 윈도우로 최근 K step 적 obs 유지
  - 매 T tick마다 ProtoNet으로 intent 예측
  - 신뢰도 임계값 미만 시 UNKNOWN 반환 (안전 모드)
  - 교전 종료 후 온라인 prototype 업데이트 (선택)
"""

from collections import deque
from typing import Optional
import torch

from .encoder import obs_dict_to_tensor, window_to_tensor, OBS_DIM
from .proto_net import ProtoNet, INTENT_CLASSES


class OnlineIntentTracker:
    """
    1v1 교전 중 적 의도를 실시간으로 추적.

    사용 예:
        tracker = OnlineIntentTracker.from_file("models/intent_model.pt")
        # 매 tick:
        tracker.update(enemy_obs_dict)
        intent, conf = tracker.current_intent()
        # BT 조건: if intent == "GUN_ATTACK": activate defensive maneuver
    """

    def __init__(
        self,
        model: ProtoNet,
        window_size: int = 20,
        update_interval: int = 10,
        confidence_threshold: float = 0.35,
    ):
        """
        Args:
            model:               학습된 ProtoNet
            window_size:         슬라이딩 윈도우 길이 (step 수)
            update_interval:     예측 갱신 주기 (tick 수)
            confidence_threshold: 이 신뢰도 미만이면 UNKNOWN 반환
        """
        self.model       = model
        self.window_size = window_size
        self.update_interval    = update_interval
        self.confidence_threshold = confidence_threshold

        self._buffer: deque[dict] = deque(maxlen=window_size)
        self._tick:   int = 0

        self._last_intent: str = "UNKNOWN"
        self._last_conf:   dict[str, float] = {c: 0.0 for c in INTENT_CLASSES}
        self._history:     list[tuple[int, str, float]] = []  # (tick, intent, max_conf)

        # 온라인 업데이트용 미니 버퍼 (매치 종료 후 prototype 업데이트)
        self._online_windows: dict[str, list[torch.Tensor]] = {c: [] for c in INTENT_CLASSES}

    # ── 상태 업데이트 ───────────────────────

    def update(self, enemy_obs: dict) -> Optional[str]:
        """
        매 tick 호출. 적 obs dict를 버퍼에 추가하고,
        update_interval마다 intent를 재계산.

        Returns:
            새 intent 예측값 (갱신된 경우), 아니면 None
        """
        self._buffer.append(enemy_obs)
        self._tick += 1

        if (len(self._buffer) >= self.window_size
                and self._tick % self.update_interval == 0):
            self._recompute()
            return self._last_intent
        return None

    def _recompute(self):
        window = list(self._buffer)   # 최근 K step
        tensor = window_to_tensor(window)  # (K, OBS_DIM)
        intent, conf = self.model.predict(tensor)
        max_conf = conf[intent]

        if max_conf < self.confidence_threshold:
            self._last_intent = "UNKNOWN"
        else:
            self._last_intent = intent
        self._last_conf = conf

        self._history.append((self._tick, self._last_intent, max_conf))

        # 온라인 업데이트 버퍼에 추가 (신뢰도 높은 경우만)
        if max_conf >= self.confidence_threshold:
            self._online_windows[intent].append(tensor)

    # ── 조회 API ───────────────────────────

    def current_intent(self) -> tuple[str, dict[str, float]]:
        """
        현재 예측된 적 의도와 신뢰도 dict 반환.

        Returns:
            (intent_label, {class: confidence})
        """
        return self._last_intent, self._last_conf

    def is_intent(self, intent: str) -> bool:
        """BT 조건 노드용 — 현재 의도가 intent와 일치하는지."""
        return self._last_intent == intent

    def confidence(self, intent: str) -> float:
        """특정 intent에 대한 신뢰도 (0~1)."""
        return self._last_conf.get(intent, 0.0)

    def dominant_intent_in_match(self) -> str:
        """지금까지의 history에서 가장 빈번한 intent 반환."""
        if not self._history:
            return "UNKNOWN"
        from collections import Counter
        counts = Counter(h[1] for h in self._history if h[1] != "UNKNOWN")
        if not counts:
            return "UNKNOWN"
        return counts.most_common(1)[0][0]

    # ── 온라인 prototype 업데이트 ───────────

    def update_prototypes_from_match(self, alpha: float = 0.1):
        """
        교전 종료 후 호출. 이번 교전 데이터로 prototype을 EMA 업데이트.

        Args:
            alpha: 업데이트 강도 (0=변화없음, 1=완전 교체)
        """
        if self.model._prototypes is None:
            return
        self.model.encoder.eval()
        for intent, windows in self._online_windows.items():
            if len(windows) < 5:   # 샘플 부족 시 스킵
                continue
            with torch.no_grad():
                batch = torch.stack(windows)
                new_embs = self.model.encoder(batch)
                new_proto = new_embs.mean(0)
            old_proto = self.model._prototypes.get(intent)
            if old_proto is None:
                self.model._prototypes[intent] = new_proto
            else:
                self.model._prototypes[intent] = (
                    (1 - alpha) * old_proto + alpha * new_proto
                )
        # 버퍼 초기화
        self._online_windows = {c: [] for c in INTENT_CLASSES}

    # ── 리셋 ───────────────────────────────

    def reset(self):
        """새 교전 시작 시 호출."""
        self._buffer.clear()
        self._tick = 0
        self._last_intent = "UNKNOWN"
        self._last_conf   = {c: 0.0 for c in INTENT_CLASSES}
        self._history     = []
        self._online_windows = {c: [] for c in INTENT_CLASSES}

    # ── 팩토리 ─────────────────────────────

    @classmethod
    def from_file(
        cls,
        model_path: str,
        window_size: int = 20,
        update_interval: int = 10,
        confidence_threshold: float = 0.35,
    ) -> "OnlineIntentTracker":
        model = ProtoNet.load(model_path)
        return cls(
            model=model,
            window_size=window_size,
            update_interval=update_interval,
            confidence_threshold=confidence_threshold,
        )

    # ── 요약 출력 ──────────────────────────

    def summary(self) -> str:
        lines = [f"  총 {self._tick} ticks, {len(self._history)} 예측"]
        from collections import Counter
        counts = Counter(h[1] for h in self._history)
        for intent in INTENT_CLASSES + ["UNKNOWN"]:
            n = counts.get(intent, 0)
            lines.append(f"    {intent:<16} {n:>4}회")
        dominant = self.dominant_intent_in_match()
        lines.append(f"  → 지배적 의도: {dominant}")
        return "\n".join(lines)
