"""L0 — 적 풀(bt_zoo) 적절성 점검 (합성 obs 격자 probe).

목적: 데이터 생성 입력인 적 BT 풀이 학습에 쓸 만한지 bottom-up 판단.
방법: 실제 plant(JSBSim) 대신 feature 공간을 덮는 합성 obs 격자에서 각 적 함수의
      tactic 응답을 측정 → 행동 지문(signature). plant 미생성이라 빠르고 입력공간 전반 탐침.

검사:
  1) 로드 성공/실패 (yaml_bt.load_bt)
  2) 행동 다양성 — 격자 위 고유 tactic 수 / 응답 시그니처
  3) 퇴화 — 격자 전체에서 동일 tactic, 특히 전부 PURE_PURSUIT(미지원 어휘 default 의심)
  4) 중복 — 동일 시그니처로 묶이는 잉여 적 수
  5) tactic 커버리지 — 풀 전체가 자극하는 고유 tactic
"""
from __future__ import annotations
import sys, os, glob, itertools
from collections import Counter

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "control"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "engine"))

from yaml_bt import load_bt

PROOT = os.path.join(os.path.dirname(__file__), "..", "..")


class SimObs:
    """_cond / Geom 이 읽는 obs 필드만 갖춘 합성 관측."""
    __slots__ = ("ego_alt_ft", "ego_vc_kts", "ego_phi_deg", "ego_theta_deg",
                 "ego_psi_deg", "ego_r_dps", "enm_alt_ft", "enm_vc_kts",
                 "enm_psi_deg", "distance_ft", "rel_b_deg", "ata_deg", "aa_deg",
                 "closure_kts", "advantage", "alt_gap_ft")

    def __init__(self, ata, aa, dist, ego_alt, closure, hca, ego_vc=350.0):
        self.ata_deg = ata
        self.aa_deg = aa
        self.distance_ft = dist
        self.ego_alt_ft = ego_alt
        self.closure_kts = closure
        self.ego_vc_kts = ego_vc
        self.enm_vc_kts = 350.0
        self.enm_alt_ft = 15000.0
        self.alt_gap_ft = ego_alt - 15000.0
        self.advantage = 1.0 - (ata + aa) / 180.0
        self.rel_b_deg = ata if ata <= 180 else 180.0   # LOS 근사
        self.ego_phi_deg = 30.0
        self.ego_theta_deg = 0.0
        self.ego_r_dps = 0.0
        self.ego_psi_deg = 0.0
        self.enm_psi_deg = hca           # hca = |psi_us - psi_op|, psi_us=0


def _grid():
    atas = [0, 40, 90, 140, 180]
    aas = [0, 60, 120, 180]
    dists = [800, 3000, 8000, 13000]
    alts = [3000, 15000]
    closures = [-60, 0, 90]
    hcas = [0, 90, 180]
    return [SimObs(*c) for c in itertools.product(atas, aas, dists, alts, closures, hcas)]


def _pools():
    return {
        "archetypes":    sorted(glob.glob(os.path.join(PROOT, "examples", "archetypes", "*.yaml"))),
        "opponent_pool": sorted(glob.glob(os.path.join(PROOT, "examples", "opponent_pool", "*.yaml"))),
        "examples":      sorted(glob.glob(os.path.join(PROOT, "examples", "*.yaml"))),
    }


def main():
    grid = _grid()
    pools = _pools()
    total = sum(len(v) for v in pools.values())
    print(f"=== L0 적 풀 적절성 점검 (합성 격자 {len(grid)}점 probe) ===")
    print("풀: " + ", ".join(f"{k}={len(v)}" for k, v in pools.items()) + f"  총 {total}개\n")

    load_fail, sigs, sig_count = [], {}, Counter()
    all_tactics = Counter()
    degenerate, all_pursuit = [], []
    ndistinct = []

    for pname, files in pools.items():
        for f in files:
            try:
                fn = load_bt(f)
                resp = tuple(fn(o).name for o in grid)
            except Exception as e:
                load_fail.append((os.path.relpath(f, PROOT), repr(e)[:80]))
                continue
            sigs[f] = resp
            sig_count[resp] += 1
            uniq = set(resp)
            ndistinct.append(len(uniq))
            for t in resp:
                all_tactics[t] += 1
            if len(uniq) == 1:
                only = next(iter(uniq))
                degenerate.append((os.path.relpath(f, PROOT), only))
                if only == "PURE_PURSUIT":
                    all_pursuit.append(os.path.relpath(f, PROOT))

    n_ok = len(sigs)
    print(f"[1] 로드: 성공 {n_ok}/{total}, 실패 {len(load_fail)}")
    for p, e in load_fail[:8]:
        print(f"    FAIL {p}  {e}")
    if len(load_fail) > 8:
        print(f"    ... 외 {len(load_fail)-8}")

    import statistics
    print(f"\n[2] 행동 다양성:")
    print(f"    고유 시그니처 {len(sig_count)}종 / {n_ok}개 적")
    if ndistinct:
        print(f"    적당 고유 tactic 수: 평균 {statistics.mean(ndistinct):.1f}, "
              f"최소 {min(ndistinct)}, 최대 {max(ndistinct)}")
        hist = Counter(ndistinct)
        print(f"    분포(고유tactic수: 적수): " +
              ", ".join(f"{k}:{hist[k]}" for k in sorted(hist)))

    print(f"\n[3] 퇴화: 격자 전체 동일 tactic = {len(degenerate)}개")
    for t, c in Counter(t for _, t in degenerate).most_common():
        print(f"      {c:4d}x  항상 {t}")
    print(f"    전부 PURE_PURSUIT(default 의심) = {len(all_pursuit)}개")

    print(f"\n[4] 중복: 고유화 시 {len(sig_count)}종으로 축약 "
          f"(잉여 {n_ok - len(sig_count)}개 동일행동)")
    print(f"    최다 동일행동 시그니처 = {sig_count.most_common(1)[0][1]}개")

    print(f"\n[5] tactic 커버리지 (격자×적 전체 등장):")
    for t, c in all_tactics.most_common():
        print(f"      {c:8d}  {t}")
    print(f"    풀이 자극하는 고유 tactic = {len(set(all_tactics))}종")

    print(f"\n=== 판정 요약 ===")
    print(f"  로드 성공          = {n_ok}/{total}")
    print(f"  비퇴화(유효) 적    = {n_ok - len(degenerate)}개")
    print(f"  고유 행동 적       = {len(sig_count)}종")
    print(f"  default 퇴화 제거후보 = {len(all_pursuit)}개")


if __name__ == "__main__":
    main()
