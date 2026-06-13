"""situation_cost — 명시적·설명가능 relational cost/value (RF 블랙박스 → 읽히는 BFM 규칙).

이론(docs/NEW_ENGINE_ADAPTIVE_METHODOLOGY.md §4.6): cost = 미분게임 가치 V(상태) 근사.
구조(§4.7, E32 value-margin): crisp core(정렬 상황, 에너지×거리로 분기) = 명시 cost 항,
fuzzy(고HCA rate)=soft blend. 손-N개 아님 — value margin이 dictate.

  V(obs) = Σ_s w_s(obs) · J_s(obs)
   · w_s = 상황 soft 멤버십 — 전부 *관측-차(상대값)* sigmoid. 절대 dist/alt 금지(틱-의존·비불변).
   · J_s = 그 상황 *지배 물리량* (BFM·E-M). real_rollout._cost_* 계승. 가중치=추후 RL-튜너블.
   · V 높음=우리 우세(격추 가능 쪽), 낮음=열세. (미분게임 capture set 근사.)

설명가능: 각 항이 읽히는 규칙(if 적 뒤→방어 deny; 정렬+에너지→rate out-turn; …). 추후 RL은 *구조 아닌
가중치만* 튜닝(exploitability 최소화). [[mpc-failure-analysis]]: relational cost 보존 + rollout 제거.
"""
from __future__ import annotations
import math

# ── 게임 규칙 상수 (judge 일치, 변경 금지) ─ WEZ는 게임규칙이라 *절대거리 허용*(상황게이트엔 금지) ─
WEZ_ATA_DEG = 12.0
WEZ_MIN_FT, WEZ_MAX_FT = 500.0, 3000.0
_G = 32.174
_KT2FPS = 1.68781


def _sig(x: float) -> float:
    return 1.0 / (1.0 + math.exp(-max(-30.0, min(30.0, x))))


def _hca(o) -> float:
    """heading crossing angle = 두 속도벡터 교차각 (상대량). head-on→180, 추격정렬→0."""
    return abs(((o.ego_psi_deg - o.enm_psi_deg) + 180.0) % 360.0 - 180.0)


def _es(alt_ft: float, vc_kts: float) -> float:
    """비에너지 Es = 고도 + V²/2g (ft). E-M 이론(Boyd)."""
    return alt_ft + (vc_kts * _KT2FPS) ** 2 / (2.0 * _G)


def es_diff(o) -> float:
    """상대 에너지 우위 (우리 Es − 적 Es, ft). +면 우리 우위."""
    return _es(o.ego_alt_ft, o.ego_vc_kts) - _es(o.enm_alt_ft, o.enm_vc_kts)


def wez_margin(o) -> float:
    """우리 위치 품질 [0,1] — nose-on(ata↓) × WEZ거리 근접. judge WEZ 규칙 부드러운 근사 (상대 기하)."""
    ang = max(0.0, 1.0 - o.ata_deg / 60.0)                       # ata<60° 가까울수록↑
    if o.distance_ft <= WEZ_MIN_FT:
        rng = o.distance_ft / WEZ_MIN_FT
    elif o.distance_ft <= WEZ_MAX_FT:
        rng = 1.0
    else:
        rng = max(0.0, 1.0 - (o.distance_ft - WEZ_MAX_FT) / 6000.0)  # WEZ 밖 거리감쇠
    return ang * rng


def _energy_norm(o) -> float:
    """Es차 → [-1,+1] (tanh). 상대 에너지, 보조항."""
    return math.tanh(es_diff(o) / 6000.0)


# ── 상황 soft 멤버십 (관측-차 only). E32 crisp core 근거 ────────────────────
def memberships(o) -> dict:
    """5 상황 soft 가중 (합 1 정규화 전). 전부 ata/aa/hca/es_diff 상대량 — 절대 dist/alt 0."""
    ata, aa, hca = o.ata_deg, o.aa_deg, _hca(o)
    e = _energy_norm(o)                                          # 에너지 우위 [-1,1]
    w = {
        # 적이 우리 뒤(aa↑) = 방어 (최우선)
        "DEFENSIVE": _sig((aa - 110.0) / 20.0),
        # 우리가 적 뒤·정렬(ata↓,aa↓) = 공격/추격 → WEZ 몰이
        "OFFENSIVE": _sig((35.0 - ata) / 15.0) * _sig((90.0 - aa) / 30.0),
        # 교차(hca↑) + 에너지 우위 = rate fight(2-circle)
        "TWO_CIRCLE": _sig((hca - 90.0) / 30.0) * _sig((e + 0.0) / 0.4) * _sig((ata - 20.0) / 20.0),
        # 교차 + 에너지 열세/대등 = radius fight(1-circle, 최소반경)
        "ONE_CIRCLE": _sig((hca - 60.0) / 30.0) * _sig((-e + 0.0) / 0.4) * _sig((ata - 20.0) / 20.0),
        # 위 어디도 강하지 않음 = 중립/재진입 (fuzzy 잔여)
    }
    s = sum(w.values())
    w["NEUTRAL"] = max(0.0, 1.0 - s)                            # 잔여 = fuzzy blend
    tot = sum(w.values()) + 1e-9
    return {k: v / tot for k, v in w.items()}


# ── 상황별 cost J_s (지배 물리량, 상대량). real_rollout._cost_* 계승·확장 ────
def J_offensive(o) -> float:
    """추격/공격: dominant = 우리 WEZ 안착(위치 품질). pursuit curve + WEZ."""
    return wez_margin(o)

def J_two_circle(o) -> float:
    """2-circle rate: dominant = out-rate(우리 nose가 적보다 앞섬) + 에너지 유지(corner 밑천)."""
    out_rate = wez_margin(o) - max(0.0, 1.0 - o.aa_deg / 60.0)   # 우리 위치 − 적 위치우위 근사
    return out_rate + 0.5 * _energy_norm(o)

def J_one_circle(o) -> float:
    """1-circle radius: dominant = 최소반경 각 우위. 저에너지서 각 따기(반경 우위)."""
    return wez_margin(o) - 0.3 * max(0.0, _energy_norm(o))       # 에너지 적을 때 각으로 승부

def J_defensive(o) -> float:
    """방어: dominant = 적 gun solution 거부 + 에너지 보존(생존 밑천). 같은 방향(비충돌)."""
    deny = 1.0 - max(0.0, 1.0 - o.aa_deg / 60.0)                 # 적이 우리 nose-on 못 하게
    return 2.0 * deny + 0.5 * (_energy_norm(o) + 1.0)

def J_neutral(o) -> float:
    """중립/fuzzy: 위치 + 에너지 우위 (균형). Nash 영역이라 약한 신호."""
    return 0.5 * wez_margin(o) + 0.5 * _energy_norm(o)


_J = {"OFFENSIVE": J_offensive, "TWO_CIRCLE": J_two_circle, "ONE_CIRCLE": J_one_circle,
      "DEFENSIVE": J_defensive, "NEUTRAL": J_neutral}


def their_margin(o) -> float:
    """적이 *우리*를 위협하는 위치 품질 [0,1]. aa↑(적이 우리 뒤·겨눔) × 근접. (우리 obs로 추정.)"""
    ang = max(0.0, (o.aa_deg - 110.0) / 70.0)                   # aa>110 = 적 후방반구 점유(위협)
    rng = 1.0 if o.distance_ft <= WEZ_MAX_FT else max(0.0, 1.0 - (o.distance_ft - WEZ_MAX_FT) / 6000.0)
    return max(0.0, min(1.0, ang)) * rng


def value(o) -> float:
    """★ 미분게임 가치 근사 V(obs) = *zero-sum 위치우위* (우리 위협 − 적 위협) + 에너지우위.
    높음=우리 우세(capture 쪽), 음수=열세(적이 우리 capture). 일관된 게임 value (단일 척도)."""
    return wez_margin(o) - their_margin(o) + 0.3 * _energy_norm(o)


# 주: memberships + J_s 는 *행동 선택*(policy)용 — 어느 상황서 무엇을 최적화하나(별개 레이어).
#    value(o) 는 *상태 가치*(zero-sum) — 누가 이기고 있나. 둘은 분리.


def explain(o) -> str:
    """value(상태우위) + 행동선택용 상황 분해 (인용가능)."""
    w = memberships(o)
    dom = max(w.items(), key=lambda kv: kv[1])
    return (f"V={value(o):+.3f} (우리margin {wez_margin(o):.2f} − 적margin {their_margin(o):.2f} "
            f"+ E {_energy_norm(o):+.2f}) | 행동상황={dom[0]}(w{dom[1]:.2f})")
