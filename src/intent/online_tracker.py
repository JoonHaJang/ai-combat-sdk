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

    @staticmethod
    def _enrich_bfm(obs: dict) -> dict:
        """
        bfm_situation = UNKNOWN일 때 UNK 서브분류 주입.
        학습 데이터(CSV)는 degrees 기반 classify_unknown_sub를 사용했으므로
        여기서도 degrees 값(이미 _to_deg 변환된 후)을 사용.
        """
        bfm = obs.get("bfm_situation", "")
        if bfm != "UNKNOWN":
            return obs
        try:
            from tools.analyze_metadata import classify_unknown_sub
            ata = float(obs.get("ata_deg", 0.0))
            closure = float(obs.get("closure_rate_kts", 0.0))
            sub = classify_unknown_sub(ata, closure)
            out = dict(obs)
            out["bfm_situation"] = sub
            return out
        except Exception:
            return obs

    def update(self, enemy_obs: dict) -> Optional[str]:
        """
        매 tick 호출. 적 obs dict를 버퍼에 추가하고,
        update_interval마다 intent를 재계산.

        Returns:
            새 intent 예측값 (갱신된 경우), 아니면 None
        """
        self._buffer.append(self._enrich_bfm(enemy_obs))
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

    def update_prototypes_from_match(self, alpha: float = 0.1, n_min: int = 5):
        """
        교전 종료 후 호출. 이번 교전 데이터로 prototype을 EMA 업데이트.

        Args:
            alpha: 업데이트 강도 (0=변화없음, 1=완전 교체)
            n_min: 최소 샘플 수 (미만이면 스킵)
        """
        self._apply_prototype_update(alpha=alpha, n_min=n_min)
        self._online_windows = {c: [] for c in INTENT_CLASSES}

    def update_online(self, n_min: int = 10, alpha: float = 0.05):
        """
        매치 중 호출. 누적 샘플이 n_min 이상인 클래스에 즉시 EMA 업데이트.
        update_every_ticks 마다 자동 호출하면 mid-match few-shot 효과.

        Args:
            n_min:  즉시 업데이트 기준 샘플 수
            alpha:  EMA 강도 (교전 중이라 보수적으로 작게)
        """
        updated = []
        for cls, windows in self._online_windows.items():
            if len(windows) >= n_min:
                self._update_one_proto(cls, windows, alpha)
                updated.append(cls)
        # 업데이트한 클래스 버퍼만 초기화
        for cls in updated:
            self._online_windows[cls] = []
        return updated

    def _apply_prototype_update(self, alpha: float, n_min: int):
        """내부: 버퍼 전체 EMA 업데이트."""
        if self.model._prototypes is None:
            return
        for cls, windows in self._online_windows.items():
            if len(windows) < n_min:
                continue
            self._update_one_proto(cls, windows, alpha)

    def _update_one_proto(self, cls: str, windows: list, alpha: float):
        """내부: 단일 클래스 prototype EMA 업데이트."""
        if not windows or self.model._prototypes is None:
            return
        self.model.encoder.eval()
        with torch.no_grad():
            batch = torch.stack(windows)
            new_embs = self.model.encoder(batch)
            new_proto = new_embs.mean(0)
        old_proto = self.model._prototypes.get(cls)
        if old_proto is None:
            self.model._prototypes[cls] = new_proto
        else:
            self.model._prototypes[cls] = (
                (1 - alpha) * old_proto + alpha * new_proto
            )

    def save_prototypes(self, model_path: str):
        """
        업데이트된 prototype을 모델 파일에 저장.
        매치 종료 후 update_prototypes_from_match() 와 함께 호출.
        멀티프로세스 환경에서 filelock으로 동시 쓰기 충돌 방지 (Windows/Linux 공통).
        """
        if self.model._prototypes is None:
            return
        import logging
        from filelock import FileLock, Timeout
        lock_path = model_path + ".lock"
        try:
            with FileLock(lock_path, timeout=10):
                existing = torch.load(model_path, map_location="cpu", weights_only=False)
                existing["prototypes"] = self.model._prototypes
                torch.save(existing, model_path)
        except Timeout:
            logging.getLogger(__name__).warning("prototype 저장 실패: lock timeout (10s)")
        except Exception as e:
            logging.getLogger(__name__).warning(f"prototype 저장 실패: {e}")

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
