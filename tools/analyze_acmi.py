"""
analyze_acmi.py — ACMI 파일 기하학/에너지 분석

ACMI Tacview 포맷을 파싱하여:
  - WEZ 진입 통계 (152~914ft, ATA<12°)
  - 기하학 phase 분류 (OBFM/DBFM/HABFM/NEUTRAL)
  - 에너지 우위 시계열 (Specific Energy = h + v²/2g)
  - BFM 이벤트 (first blood, last WEZ, energy crossover)
  - 무승부/패배 원인 진단

Usage:
    python tools/analyze_acmi.py replays/ace/adaptive_eagle_vs_ace.acmi
    python tools/analyze_acmi.py replays/ --summary   # 전체 replays 비교
"""

import argparse
import re
import sys
from collections import defaultdict
from pathlib import Path

# ─── 상수 ──────────────────────────────────────

G_FTS2 = 32.174   # ft/s²
KTS_TO_FTS = 1.68781   # knot → ft/s

WEZ_ATA_MAX = 12.0
WEZ_DIST_MIN = 152.0
WEZ_DIST_MAX = 914.0


def specific_energy_ft(alt_ft, cas_kts):
    """Es = h + v²/2g (단위: ft)."""
    v_fts = cas_kts * KTS_TO_FTS
    return alt_ft + (v_fts * v_fts) / (2 * G_FTS2)


def classify_phase(ata, aa):
    """기하학 phase 분류.

    OBFM: ATA<45°, AA>135° (나는 적의 뒤)
    DBFM: ATA>135°, AA<45° (적이 내 뒤)
    HABFM: |HCA|에 의존하지만 여기선 ATA, AA 둘 다 ~90° → 선회전 영역
    NEUTRAL: 그 외
    """
    if ata < 45 and aa > 135:
        return "OBFM"
    if ata > 135 and aa < 45:
        return "DBFM"
    if 45 <= ata <= 135 and 45 <= aa <= 135:
        return "HABFM"
    return "NEUTRAL"


# ─── ACMI 파서 ─────────────────────────────────

class ACMIParser:
    def __init__(self, path):
        self.path = Path(path)
        self.ego_id = "A0100"
        self.enm_id = "B0100"
        self.ego_name = "ego"
        self.enm_name = "enm"
        self.frames = []   # list of dict per timestamp
        self.events = []   # (t, actor, msg)
        self._parse()

    def _parse(self):
        current_t = 0.0
        state = {
            "ego": {"alt": 0, "cas": 0, "dist": 0, "ata": 0, "aa": 0, "hca": 0,
                    "tau": 0, "closure": 0, "reward": 0, "health": 100,
                    "in_wez": False, "active_node": "", "lat": 0, "lon": 0},
            "enm": {"alt": 0, "cas": 0, "health": 100, "lat": 0, "lon": 0},
        }

        with open(self.path, encoding="utf-8-sig") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue

                # 타임스탬프
                if line.startswith("#"):
                    # 이전 frame 저장
                    if current_t > 0:
                        self.frames.append({
                            "t": current_t,
                            "ego": dict(state["ego"]),
                            "enm": dict(state["enm"]),
                        })
                    try:
                        current_t = float(line[1:])
                    except ValueError:
                        pass
                    continue

                # 초기 등록
                if line.startswith("A0100,Type") or line.startswith("A0100,Pilot"):
                    m = re.search(r"CallSign=([^,]+)", line)
                    if m:
                        self.ego_name = m.group(1)
                    continue
                if line.startswith("B0100,Type") or line.startswith("B0100,Pilot"):
                    m = re.search(r"CallSign=([^,]+)", line)
                    if m:
                        self.enm_name = m.group(1)
                    continue

                # 좌표 + HDG
                if line.startswith("A0100,T="):
                    self._parse_position(line[len("A0100,"):], state["ego"])
                    continue
                if line.startswith("B0100,T="):
                    self._parse_position(line[len("B0100,"):], state["enm"])
                    continue

                # CAS
                if line.startswith("A0100,HDG="):
                    m = re.search(r"CAS=([\d.]+)", line)
                    if m:
                        state["ego"]["cas"] = float(m.group(1))
                    continue
                if line.startswith("B0100,HDG="):
                    m = re.search(r"CAS=([\d.]+)", line)
                    if m:
                        state["enm"]["cas"] = float(m.group(1))
                    continue

                # 메트릭
                for key_acmi, key_state in [
                    ("Distance", "dist"), ("ATA", "ata"), ("AA", "aa"),
                    ("HCA", "hca"), ("TAU", "tau"), ("ClosureRate", "closure"),
                    ("Reward", "reward"), ("Health", "health"),
                ]:
                    if line.startswith(f"A0100,{key_acmi}="):
                        try:
                            state["ego"][key_state] = float(line.split("=")[1])
                        except ValueError:
                            pass
                        break
                    if line.startswith(f"B0100,Health="):
                        try:
                            state["enm"]["health"] = float(line.split("=")[1])
                        except ValueError:
                            pass
                        break

                if line.startswith("A0100,InWEZ="):
                    state["ego"]["in_wez"] = (line.split("=")[1] == "True")
                    continue

                if line.startswith("A0100,ActiveNode="):
                    state["ego"]["active_node"] = line.split("=", 1)[1]
                    continue

                # 이벤트
                if "Event=Message" in line:
                    self.events.append((current_t, "msg", line))

        # 마지막 frame
        if current_t > 0:
            self.frames.append({
                "t": current_t,
                "ego": dict(state["ego"]),
                "enm": dict(state["enm"]),
            })

    def _parse_position(self, s, target):
        # T=lon|lat|alt|...
        m = re.search(r"T=([^,]+)", s)
        if not m:
            return
        parts = m.group(1).split("|")
        if len(parts) >= 3:
            try:
                target["lon"] = float(parts[0])
                target["lat"] = float(parts[1])
                target["alt"] = float(parts[2]) * 3.28084  # m → ft
            except ValueError:
                pass


# ─── 분석기 ────────────────────────────────────

def analyze(parser: ACMIParser):
    n = len(parser.frames)
    if n == 0:
        return {"error": "no frames"}

    # 1. WEZ 통계
    ego_in_wez = sum(1 for f in parser.frames if f["ego"]["in_wez"])

    # 2. Phase 분류
    phase_counts = defaultdict(int)
    for f in parser.frames:
        p = classify_phase(f["ego"]["ata"], f["ego"]["aa"])
        phase_counts[p] += 1

    # 3. 에너지 시계열
    es_ego = [specific_energy_ft(f["ego"]["alt"], f["ego"]["cas"]) for f in parser.frames]
    es_enm = [specific_energy_ft(f["enm"]["alt"], f["enm"]["cas"]) for f in parser.frames]
    es_diff = [(a - b) for a, b in zip(es_ego, es_enm)]

    es_adv_ticks = sum(1 for d in es_diff if d > 500)
    es_disadv_ticks = sum(1 for d in es_diff if d < -500)

    # 4. 거리 시계열 + closure 패턴
    dists = [f["ego"]["dist"] for f in parser.frames]
    min_dist = min(dists)
    max_dist = max(dists)
    avg_dist = sum(dists) / n
    final_dist = dists[-1]

    # 5. ATA / AA 평균
    avg_ata = sum(f["ego"]["ata"] for f in parser.frames) / n
    avg_aa = sum(f["ego"]["aa"] for f in parser.frames) / n

    # 6. 노드 사용 통계
    node_usage = defaultdict(int)
    for f in parser.frames:
        node_usage[f["ego"]["active_node"]] += 1

    # 7. 첫 WEZ 진입 시점
    first_wez_t = None
    for f in parser.frames:
        if f["ego"]["in_wez"]:
            first_wez_t = f["t"]
            break

    # 8. Closure rate 평균
    closures = [f["ego"]["closure"] for f in parser.frames]
    avg_closure = sum(closures) / n
    positive_closure = sum(1 for c in closures if c > 0)  # 접근 중

    # 9. HP
    final_ego_hp = parser.frames[-1]["ego"]["health"]
    final_enm_hp = parser.frames[-1]["enm"]["health"]

    return {
        "n_frames": n,
        "duration_s": parser.frames[-1]["t"],
        "ego_name": parser.ego_name,
        "enm_name": parser.enm_name,
        "wez": {
            "ego_in_wez_ticks": ego_in_wez,
            "ego_in_wez_pct": round(100 * ego_in_wez / n, 1),
            "first_wez_t": first_wez_t,
        },
        "phases": {k: round(100 * v / n, 1) for k, v in phase_counts.items()},
        "energy": {
            "ego_avg": round(sum(es_ego) / n),
            "enm_avg": round(sum(es_enm) / n),
            "diff_avg": round(sum(es_diff) / n),
            "adv_pct": round(100 * es_adv_ticks / n, 1),
            "disadv_pct": round(100 * es_disadv_ticks / n, 1),
            "start_diff": round(es_diff[0]) if es_diff else 0,
            "end_diff": round(es_diff[-1]) if es_diff else 0,
        },
        "distance": {
            "min": round(min_dist),
            "max": round(max_dist),
            "avg": round(avg_dist),
            "final": round(final_dist),
        },
        "angles": {
            "avg_ata": round(avg_ata, 1),
            "avg_aa": round(avg_aa, 1),
        },
        "closure": {
            "avg_kts": round(avg_closure, 1),
            "approach_pct": round(100 * positive_closure / n, 1),
        },
        "hp": {
            "ego_final": final_ego_hp,
            "enm_final": final_enm_hp,
            "diff": round(final_ego_hp - final_enm_hp, 1),
        },
        "node_usage_top": sorted(node_usage.items(), key=lambda x: -x[1])[:5],
    }


def diagnose(result):
    """분석 결과로부터 무승부/패배 원인 자동 진단."""
    diag = []
    hp_diff = result["hp"]["diff"]
    wez_pct = result["wez"]["ego_in_wez_pct"]
    e_diff = result["energy"]["diff_avg"]
    min_dist = result["distance"]["min"]
    phases = result["phases"]
    avg_closure = result["closure"]["avg_kts"]
    approach_pct = result["closure"]["approach_pct"]

    # 결과 판단
    if abs(hp_diff) < 0.5 and result["hp"]["ego_final"] > 99 and result["hp"]["enm_final"] > 99:
        outcome = "DRAW_NO_ENGAGEMENT"
    elif hp_diff > 5:
        outcome = "WIN"
    elif hp_diff < -5:
        outcome = "LOSS"
    elif hp_diff < 0:
        outcome = "NEAR_LOSS"
    else:
        outcome = "NEAR_DRAW"

    diag.append(f"RESULT: {outcome} (hp_diff={hp_diff:+.1f})")

    # WEZ 진입 실패
    if wez_pct < 1:
        diag.append(f"⚠ WEZ 진입 실패 ({wez_pct}%) — 한 번도 사격 기회 없음")
    elif wez_pct < 5:
        diag.append(f"⚠ WEZ 진입 희박 ({wez_pct}%)")
    else:
        diag.append(f"✓ WEZ 진입 {wez_pct}%")

    # 에너지
    if e_diff < -1000:
        diag.append(f"⚠ 에너지 열위 지속 (avg diff {e_diff} ft)")
    elif e_diff > 1000:
        diag.append(f"✓ 에너지 우위 유지 (avg diff {e_diff} ft)")
    else:
        diag.append(f"• 에너지 대등 (diff {e_diff} ft)")

    # 거리 패턴
    if min_dist > 2000:
        diag.append(f"⚠ 최단 거리 {min_dist}ft — 절대 근접 못함 (거리 정체)")
    elif approach_pct < 40:
        diag.append(f"⚠ 접근률 {approach_pct}% — 추격보다 회피/유지")

    # Phase 분포
    if phases.get("OBFM", 0) < 5 and outcome != "WIN":
        diag.append(f"⚠ OBFM {phases.get('OBFM', 0)}% — 공격 자세 거의 없음")
    if phases.get("DBFM", 0) > 20:
        diag.append(f"⚠ DBFM {phases.get('DBFM', 0)}% — 방어 자세 빈번")
    if phases.get("HABFM", 0) > 50:
        diag.append(f"• HABFM {phases.get('HABFM', 0)}% — 선회전 지배적 (교착)")
    if phases.get("NEUTRAL", 0) > 50:
        diag.append(f"• NEUTRAL {phases.get('NEUTRAL', 0)}% — 중립 구간 지배적")

    return diag


def print_report(path, result, diag):
    print(f"\n{'='*70}")
    print(f"  {Path(path).name}")
    print(f"  {result['ego_name']} vs {result['enm_name']}   "
          f"duration={result['duration_s']:.1f}s  frames={result['n_frames']}")
    print('='*70)

    print(f"\n  HP Final   : ego={result['hp']['ego_final']:.0f}  "
          f"enm={result['hp']['enm_final']:.0f}  diff={result['hp']['diff']:+.1f}")

    print(f"\n  WEZ        : {result['wez']['ego_in_wez_pct']}%  "
          f"({result['wez']['ego_in_wez_ticks']} ticks)  "
          f"first={result['wez']['first_wez_t']}")

    print(f"\n  Distance   : min={result['distance']['min']}  "
          f"avg={result['distance']['avg']}  "
          f"max={result['distance']['max']}  "
          f"final={result['distance']['final']}")

    print(f"\n  Angles     : ATA avg={result['angles']['avg_ata']}°  "
          f"AA avg={result['angles']['avg_aa']}°")

    print(f"\n  Closure    : avg={result['closure']['avg_kts']} kts  "
          f"approach%={result['closure']['approach_pct']}%")

    print(f"\n  Energy     : ego={result['energy']['ego_avg']}  "
          f"enm={result['energy']['enm_avg']}  diff={result['energy']['diff_avg']:+d}")
    print(f"               start diff={result['energy']['start_diff']:+d}  "
          f"end diff={result['energy']['end_diff']:+d}  "
          f"adv%={result['energy']['adv_pct']}  "
          f"disadv%={result['energy']['disadv_pct']}")

    print(f"\n  Phases     : ", end="")
    for p, pct in sorted(result['phases'].items(), key=lambda x: -x[1]):
        print(f"{p}={pct}%  ", end="")
    print()

    print(f"\n  Top Nodes  :")
    for node, cnt in result['node_usage_top']:
        pct = 100 * cnt / result['n_frames']
        print(f"    {node:30s} {cnt:5d}  {pct:5.1f}%")

    print(f"\n  Diagnosis  :")
    for d in diag:
        print(f"    {d}")
    print()


def main():
    ap = argparse.ArgumentParser(description="ACMI 기하학/에너지 분석")
    ap.add_argument("path", help="ACMI 파일 또는 디렉토리")
    args = ap.parse_args()

    p = Path(args.path)
    if p.is_file():
        paths = [p]
    elif p.is_dir():
        paths = sorted(p.rglob("*.acmi"))
    else:
        print(f"ERROR: {p} not found")
        return 1

    for path in paths:
        try:
            parser = ACMIParser(path)
            result = analyze(parser)
            diag = diagnose(result)
            print_report(path, result, diag)
        except Exception as e:
            print(f"ERROR analyzing {path}: {e}")
            import traceback
            traceback.print_exc()
    return 0


if __name__ == "__main__":
    sys.exit(main())