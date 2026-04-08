"""
query_lag_policy.py — LAG 정책 쿼리 및 전술 패턴 추출

LAG baseline_model.pt를 (AO, TA, R) 그리드에서 쿼리하여
각 전술 상황에서 RL이 선택한 최적 행동 패턴을 수집.

출력:
  logs/analysis/lag_policy_table.json   — 전체 그리드 결과
  logs/analysis/lag_tactic_summary.txt  — 인간 해석 요약

사용:
  python tools/query_lag_policy.py
"""

import sys
import json
import math
import numpy as np
import torch
import torch.nn as nn
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

LAG_MODEL_PATH = PROJECT_ROOT / "LAG" / "envs" / "JSBSim" / "model" / "baseline_model.pt"
OUTPUT_DIR = PROJECT_ROOT / "logs" / "analysis"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# ─────────────────────────────────────────────
# 1. 최소 네트워크 재구성 (LAG 의존성 없이)
# ─────────────────────────────────────────────

class LayerNorm1D(nn.Module):
    """LAG MLPBase의 LayerNorm."""
    def __init__(self, size):
        super().__init__()
        self.norm = nn.LayerNorm(size)
    def forward(self, x): return self.norm(x)


class LAGActor(nn.Module):
    """
    LAG PPOActor 재구성.
    state_dict 키 구조:
      base.mlp.fc.{0,2,3,5}: MLP layers + LayerNorm
      rnn.gru.*: GRU
      rnn.norm.*: GRU 후 LayerNorm
      act.action_outs.{0..3}.logits_net.*: 출력 헤드 4개
    """

    def __init__(self, obs_dim: int = 12, hidden: int = 128):
        super().__init__()
        # MLP: fc.0(Linear) fc.2(LN weight) fc.3(Linear) fc.5(LN weight)
        # 실제 구조: Linear → LN → ReLU → Linear → LN → ReLU
        self.fc1   = nn.Linear(obs_dim, hidden)
        self.ln1   = nn.LayerNorm(hidden)
        self.fc2   = nn.Linear(hidden, hidden)
        self.ln2   = nn.LayerNorm(hidden)
        self.act_fn = nn.ReLU()
        # GRU
        self.gru   = nn.GRU(hidden, hidden, batch_first=True)
        self.gru_norm = nn.LayerNorm(hidden)
        # 출력 헤드 (aileron 41, elevator 41, rudder 41, throttle 30)
        self.heads = nn.ModuleList([
            nn.Linear(hidden, 41),  # aileron
            nn.Linear(hidden, 41),  # elevator
            nn.Linear(hidden, 41),  # rudder
            nn.Linear(hidden, 30),  # throttle
        ])

    def load_lag_weights(self, path: str):
        sd = torch.load(path, map_location="cpu", weights_only=False)
        self.fc1.weight.data   = sd["base.mlp.fc.0.weight"]
        self.fc1.bias.data     = sd["base.mlp.fc.0.bias"]
        self.ln1.weight.data   = sd["base.mlp.fc.2.weight"]
        self.ln1.bias.data     = sd["base.mlp.fc.2.bias"]
        self.fc2.weight.data   = sd["base.mlp.fc.3.weight"]
        self.fc2.bias.data     = sd["base.mlp.fc.3.bias"]
        self.ln2.weight.data   = sd["base.mlp.fc.5.weight"]
        self.ln2.bias.data     = sd["base.mlp.fc.5.bias"]
        self.gru.weight_ih_l0.data = sd["rnn.gru.weight_ih_l0"]
        self.gru.weight_hh_l0.data = sd["rnn.gru.weight_hh_l0"]
        self.gru.bias_ih_l0.data   = sd["rnn.gru.bias_ih_l0"]
        self.gru.bias_hh_l0.data   = sd["rnn.gru.bias_hh_l0"]
        self.gru_norm.weight.data  = sd["rnn.norm.weight"]
        self.gru_norm.bias.data    = sd["rnn.norm.bias"]
        for i, head in enumerate(self.heads):
            head.weight.data = sd[f"act.action_outs.{i}.logits_net.weight"]
            head.bias.data   = sd[f"act.action_outs.{i}.logits_net.bias"]
        print(f"[LAG] 모델 로드 완료: {path}")

    def forward(self, obs: torch.Tensor, hx: torch.Tensor = None):
        """
        obs: (batch, obs_dim)
        hx:  (1, batch, hidden) — GRU hidden state
        returns: (actions, hx_next)
          actions: list of argmax per head [aileron, elevator, rudder, throttle]
        """
        x = self.act_fn(self.ln1(self.fc1(obs)))
        x = self.act_fn(self.ln2(self.fc2(x)))
        # GRU: (batch, 1, hidden)
        x_seq = x.unsqueeze(1)
        if hx is None:
            hx = torch.zeros(1, obs.shape[0], 128)
        gru_out, hx_next = self.gru(x_seq, hx)
        x = self.gru_norm(gru_out.squeeze(1))
        actions = [head(x).argmax(dim=-1).item() for head in self.heads]
        return actions, hx_next

    def get_probs(self, obs: torch.Tensor, hx: torch.Tensor = None):
        """확률 분포 반환 (분석용)."""
        x = self.act_fn(self.ln1(self.fc1(obs)))
        x = self.act_fn(self.ln2(self.fc2(x)))
        x_seq = x.unsqueeze(1)
        if hx is None:
            hx = torch.zeros(1, obs.shape[0], 128)
        gru_out, hx_next = self.gru(x_seq, hx)
        x = self.gru_norm(gru_out.squeeze(1))
        probs = [torch.softmax(head(x), dim=-1).detach().numpy()[0] for head in self.heads]
        return probs, hx_next


# ─────────────────────────────────────────────
# 2. 관측값 구성
# ─────────────────────────────────────────────

def make_obs(ao_deg: float, ta_deg: float, r_m: float,
             ego_speed_ms: float = 200.0,
             alt_m: float = 5000.0,
             alt_delta_m: float = 0.0,
             side: int = 1) -> torch.Tensor:
    """
    LAG obs 12개 구성 (state_dict input_dim=12 기준).
    실제 LAG get_obs()와 동일한 정규화 적용.

    obs[0]  = alt / 5000
    obs[1]  = sin(roll) ≈ 0 (수평 비행 가정)
    obs[2]  = cos(roll) ≈ 1
    obs[3]  = sin(pitch) ≈ 0
    obs[4]  = cos(pitch) ≈ 1
    obs[5]  = body_vx / 340
    obs[6]  = body_vy / 340 ≈ 0
    obs[7]  = body_vz / 340 ≈ 0
    obs[8]  = airspeed / 340
    obs[9]  = enemy_vx_delta / 340 ≈ 0 (동일 속도 가정)
    obs[10] = alt_delta / 1000
    obs[11] = AO (radians)
    obs[12] = TA (radians)   ← 13번째 feature인데 input=12이면 TA 없을 수도
    obs[13] = R / 10000
    obs[14] = side_flag

    주의: input_dim=12이므로 일부 feature는 제외됨.
    가장 가능한 조합: [alt, roll_s, roll_c, pitch_s, pitch_c, vx, vy, vz, v, rel_vx, AO, R]
    또는: [alt, roll_s, roll_c, pitch_s, pitch_c, vx, vy, vz, v, alt_delta, AO, TA]
    """
    ao_rad = math.radians(ao_deg)
    ta_rad = math.radians(ta_deg)
    v_norm = ego_speed_ms / 340.0
    r_norm = r_m / 10000.0
    alt_norm = alt_m / 5000.0
    alt_delta_norm = alt_delta_m / 1000.0

    # 12개 feature (LAG 실제 입력 순서 추정)
    vec = [
        alt_norm,          # 0: altitude
        0.0,               # 1: sin(roll) — 수평 가정
        1.0,               # 2: cos(roll)
        0.0,               # 3: sin(pitch)
        1.0,               # 4: cos(pitch)
        v_norm,            # 5: body_vx
        0.0,               # 6: body_vy
        0.0,               # 7: body_vz
        v_norm,            # 8: airspeed
        alt_delta_norm,    # 9: alt_delta (enemy - ego)
        ao_rad,            # 10: AO
        ta_rad,            # 11: TA (r_norm 대신 TA — 12개 맞추기)
    ]
    # NOTE: 만약 TA가 없고 R이 있다면 아래로 교체:
    # vec[11] = r_norm

    return torch.tensor(vec, dtype=torch.float32).unsqueeze(0)


def action_to_description(actions: list) -> dict:
    """
    LAG action [aileron(0-40), elevator(0-40), rudder(0-40), throttle(0-29)]
    → 인간이 이해할 수 있는 설명으로 변환.

    aileron:  0=-1.0(좌 롤), 20=0.0(중립), 40=+1.0(우 롤)
    elevator: 0=-1.0(기수 내림), 20=0.0, 40=+1.0(기수 올림)
    rudder:   0=-1.0(좌 요), 20=0.0, 40=+1.0(우 요)
    throttle: 0=0.4, 29=0.9 (min 40%, max 90%)
    """
    ail, ele, rud, thr = actions
    ail_val = ail / 20.0 - 1.0
    ele_val = ele / 20.0 - 1.0
    rud_val = rud / 20.0 - 1.0
    thr_val = thr / 58.0 + 0.4

    return {
        "aileron_idx": ail, "aileron_val": round(ail_val, 2),
        "elevator_idx": ele, "elevator_val": round(ele_val, 2),
        "rudder_idx": rud, "rudder_val": round(rud_val, 2),
        "throttle_idx": thr, "throttle_val": round(thr_val, 2),
        # 해석
        "roll":    "left" if ail_val < -0.1 else ("right" if ail_val > 0.1 else "neutral"),
        "pitch":   "down" if ele_val < -0.1 else ("up" if ele_val > 0.1 else "neutral"),
        "yaw":     "left" if rud_val < -0.1 else ("right" if rud_val > 0.1 else "neutral"),
        "thrust":  "low" if thr_val < 0.55 else ("high" if thr_val > 0.75 else "medium"),
    }


# ─────────────────────────────────────────────
# 3. 그리드 쿼리
# ─────────────────────────────────────────────

def run_grid_query(model: LAGActor):
    """
    (AO, TA, R, alt_delta) 그리드에서 LAG 정책 쿼리.

    AO (Attack Offset = 우리 ata_deg):
      0°=완전 조준, 45°=측면, 90°=수직, 180°=완전 반대
    TA (Target Aspect = 적 aa_deg):
      0°=적이 우리를 정면으로 봄(위협), 90°=측면, 180°=적이 등을 보임(기회)
    R:
      500m(초근거리), 1000m, 2000m, 3000m(최적 공격 거리), 5000m, 8000m
    alt_delta (우리 고도 - 적 고도):
      -2000m(적이 높음), 0(동일), +2000m(우리가 높음)
    """
    AO_GRID  = [0, 15, 30, 45, 60, 90, 120, 150]  # degrees
    TA_GRID  = [0, 30, 60, 90, 120, 150, 180]       # degrees
    R_GRID   = [500, 1000, 2000, 3000, 5000, 8000]  # meters
    ALT_GRID = [-2000, 0, 2000]                      # meters

    results = []
    model.eval()

    with torch.no_grad():
        for ao in AO_GRID:
            for ta in TA_GRID:
                for r in R_GRID:
                    for alt_d in ALT_GRID:
                        obs = make_obs(ao, ta, r, alt_delta_m=alt_d)
                        actions, _ = model.forward(obs)
                        desc = action_to_description(actions)

                        # 전술 상황 분류
                        if ao < 30 and ta > 120:
                            situation = "OFFENSIVE_PRIME"  # 우리가 적 후방
                        elif ao < 30 and ta < 60:
                            situation = "HEAD_ON"          # 정면 대결
                        elif ao > 90 and ta < 60:
                            situation = "DEFENSIVE"        # 우리가 불리
                        elif ao > 90 and ta > 120:
                            situation = "OVERSHOOT"        # 우리 오버슈트
                        elif 30 <= ao <= 90 and 60 <= ta <= 120:
                            situation = "NEUTRAL"          # 중립
                        else:
                            situation = "TRANSITION"

                        results.append({
                            "ao_deg": ao, "ta_deg": ta, "r_m": r,
                            "alt_delta_m": alt_d,
                            "situation": situation,
                            "actions": actions,
                            **desc,
                        })

    return results


def summarize_by_situation(results: list) -> dict:
    """상황별 행동 패턴 집계."""
    from collections import defaultdict, Counter

    by_sit = defaultdict(list)
    for r in results:
        by_sit[r["situation"]].append(r)

    summary = {}
    for sit, rows in by_sit.items():
        rolls    = Counter(r["roll"] for r in rows)
        pitches  = Counter(r["pitch"] for r in rows)
        thrusts  = Counter(r["thrust"] for r in rows)
        avg_thr  = sum(r["throttle_val"] for r in rows) / len(rows)
        avg_ele  = sum(r["elevator_val"] for r in rows) / len(rows)
        summary[sit] = {
            "n": len(rows),
            "roll_dominant":   rolls.most_common(1)[0][0],
            "pitch_dominant":  pitches.most_common(1)[0][0],
            "thrust_dominant": thrusts.most_common(1)[0][0],
            "avg_throttle":    round(avg_thr, 3),
            "avg_elevator":    round(avg_ele, 3),
            "roll_dist":       dict(rolls),
            "pitch_dist":      dict(pitches),
            "thrust_dist":     dict(thrusts),
        }
    return summary


# ─────────────────────────────────────────────
# 4. BT 매핑 추출
# ─────────────────────────────────────────────

def extract_bt_mapping(results: list) -> dict:
    """
    LAG 행동 → 우리 BT action 매핑 추출.

    LAG의 연속 제어 → 우리 이산 5×9×5 action space 근사:
      elevator↑ + throttle high → alt_idx=3(상승) + vel_idx=3(가속)
      elevator↓ + throttle low  → alt_idx=1(하강) + vel_idx=1(감속)
      aileron 강 + elevator↑    → hdg_idx=0or8(급선회) + alt_idx=3
    """
    from collections import defaultdict

    def lag_to_bt(ail, ele, rud, thr):
        ail_v = ail / 20.0 - 1.0
        ele_v = ele / 20.0 - 1.0
        thr_v = thr / 58.0 + 0.4

        # altitude action (0=급하강, 2=유지, 4=급상승)
        if ele_v > 0.4:   alt_idx = 4
        elif ele_v > 0.1: alt_idx = 3
        elif ele_v < -0.4: alt_idx = 0
        elif ele_v < -0.1: alt_idx = 1
        else:              alt_idx = 2

        # heading action (0=급좌, 4=직진, 8=급우)
        if ail_v > 0.6:    hdg_idx = 7
        elif ail_v > 0.2:  hdg_idx = 6
        elif ail_v < -0.6: hdg_idx = 1
        elif ail_v < -0.2: hdg_idx = 2
        else:              hdg_idx = 4

        # velocity action (0=급감속, 2=유지, 4=급가속)
        if thr_v > 0.80:   vel_idx = 4
        elif thr_v > 0.65: vel_idx = 3
        elif thr_v < 0.48: vel_idx = 0
        elif thr_v < 0.55: vel_idx = 1
        else:               vel_idx = 2

        return [alt_idx, hdg_idx, vel_idx]

    bt_by_situation = defaultdict(list)
    for r in results:
        bt_action = lag_to_bt(*r["actions"])
        bt_by_situation[r["situation"]].append({
            "ao": r["ao_deg"], "ta": r["ta_deg"], "r": r["r_m"],
            "bt": bt_action,
            "throttle": r["throttle_val"],
            "elevator": r["elevator_val"],
        })

    return dict(bt_by_situation)


# ─────────────────────────────────────────────
# 5. 메인
# ─────────────────────────────────────────────

def main():
    print("=" * 60)
    print("  LAG 정책 쿼리 — Adaptive BT 설계 재료 추출")
    print("=" * 60)

    # 모델 로드
    model = LAGActor(obs_dim=12, hidden=128)
    model.load_lag_weights(str(LAG_MODEL_PATH))

    # 그리드 쿼리
    print("\n[1] 그리드 쿼리 시작 (AO×TA×R×alt_delta)...")
    results = run_grid_query(model)
    print(f"    총 {len(results)}개 상태 쿼리 완료")

    # JSON 저장
    out_json = OUTPUT_DIR / "lag_policy_table.json"
    with open(out_json, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    print(f"    저장: {out_json}")

    # 상황별 요약
    print("\n[2] 상황별 행동 패턴 분석...")
    summary = summarize_by_situation(results)
    bt_mapping = extract_bt_mapping(results)

    # 텍스트 리포트
    lines = []
    lines.append("=" * 60)
    lines.append("  LAG 정책 전술 패턴 요약")
    lines.append("=" * 60)
    lines.append("")
    lines.append("※ 상황 정의:")
    lines.append("  OFFENSIVE_PRIME : AO<30° + TA>120° (우리가 적 후방)")
    lines.append("  HEAD_ON         : AO<30° + TA<60°  (정면 대결)")
    lines.append("  DEFENSIVE       : AO>90° + TA<60°  (우리가 불리)")
    lines.append("  OVERSHOOT       : AO>90° + TA>120° (오버슈트)")
    lines.append("  NEUTRAL         : 그 외 중립 상황")
    lines.append("")

    for sit, s in sorted(summary.items()):
        lines.append(f"[{sit}] (n={s['n']})")
        lines.append(f"  Roll:    {s['roll_dist']}")
        lines.append(f"  Pitch:   {s['pitch_dist']}")
        lines.append(f"  Thrust:  {s['thrust_dist']}")
        lines.append(f"  평균 throttle: {s['avg_throttle']:.3f}")
        lines.append(f"  평균 elevator: {s['avg_elevator']:.3f}")
        lines.append("")

    lines.append("")
    lines.append("=" * 60)
    lines.append("  BT 매핑 (LAG → 우리 5×9×5 action space)")
    lines.append("=" * 60)
    lines.append("  형식: [alt_idx, hdg_idx, vel_idx]")
    lines.append("  alt: 0=급하강 2=유지 4=급상승")
    lines.append("  hdg: 0=급좌(-90°) 4=직진 8=급우(+90°)")
    lines.append("  vel: 0=급감속 2=유지 4=급가속")
    lines.append("")

    for sit, rows in sorted(bt_mapping.items()):
        from collections import Counter
        bt_counts = Counter(tuple(r["bt"]) for r in rows)
        top3 = bt_counts.most_common(3)
        lines.append(f"[{sit}] 상위 BT 행동:")
        for bt, cnt in top3:
            pct = cnt / len(rows) * 100
            lines.append(f"  {list(bt)} ({pct:.0f}%)")
        lines.append("")

    report_text = "\n".join(lines)
    print(report_text)

    out_txt = OUTPUT_DIR / "lag_tactic_summary.txt"
    with open(out_txt, "w", encoding="utf-8") as f:
        f.write(report_text)
    print(f"\n저장: {out_txt}")

    return results, summary, bt_mapping


if __name__ == "__main__":
    main()
