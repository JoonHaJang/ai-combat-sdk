"""
Phase 1 대규모 메타데이터 수집 스크립트 v2

목적:
  알려진 모든 에이전트 조합을 매치시켜 per-step CSV + result JSON을 수집.
  수집된 데이터로 상대별 행동 패턴, WEZ 진입 선행 조건, 취약 구간을 분석.

전략:
  1. 기본 에이전트 매치 (42 pairs): simple/aggressive/defensive/eagle1/ace/viper1/golden
  2. 전술 프로브 매치 (--probes): 특정 BFM 상황/노드를 강제 활성화하는 프로브 에이전트
     - probe_wez: PNAttack/in_wez 강제 활성화
     - probe_defensive: BreakTurn/DefensiveSpiral 강제 활성화
     - probe_energy: HighYoYo/AltitudeAdvantage/ClimbTo 강제 활성화
     - probe_obfm: OneCircleFight/PurePursuit 강제 활성화
     - probe_habfm: ClimbingTurn/HighYoYo HABFM 집중
  3. CMA-ES 연계 (--budget N): adaptive_optimizer.py 호출하여 다양한 BT 후보 수집

실행:
  python tools/collect_phase1.py                          # 기본 42 매치, 순차
  python tools/collect_phase1.py --probes                 # 기본 + 프로브 (72 매치)
  python tools/collect_phase1.py --probes --workers 4     # 병렬 4개
  python tools/collect_phase1.py --dry-run --probes       # 실행 계획만 출력
  python tools/collect_phase1.py --coverage               # 기존 CSV 커버리지 분석만

출력:
  logs/metadata/<timestamp>_<agent1>_vs_<agent2>_meta.csv
  logs/metadata/<timestamp>_<agent1>_vs_<agent2>_meta_result.json
"""

import sys
import json
import argparse
import multiprocessing as mp
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
from datetime import datetime
from itertools import product
from collections import defaultdict, Counter

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from scripts.run_match import run_match

# ─── 에이전트 목록 ────────────────────────────────────────────

# 기본 에이전트 (7종) + 가설 기반 생성 에이전트 (7종)
AGENTS = [
    "simple",
    "aggressive",
    "defensive",
    "eagle1",
    "ace",
    "viper1",
    "golden",
    # 가설 기반 (tools/generate_agents.py로 생성)
    "gen_rush",        # 근거리 돌진 → WEZ 이벤트 증가
    "gen_gunfighter",  # GunAttack 특화 → 정밀 교전 데이터
    "gen_evader",      # 극단적 회피 → DBFM 데이터
    "gen_breaker",     # BreakTurn 특화 → 급선회 데이터
    "gen_energy",      # 에너지 전투 → 고도/속도 우위 데이터
    "gen_midrange",    # 중거리 유지 → BFM 전이 구간 데이터
    "gen_allbranch",   # 전 브랜치 ON → 노드 다양성
]

# 전술 프로브 에이전트 (5종) — examples/probe_*.yaml
# 목적: 각각 특정 BFM 상황과 액션 노드를 강제 활성화
PROBE_AGENTS = [
    "probe_wez",        # PNAttack/in_wez/enm_in_wez 커버
    "probe_defensive",  # BreakTurn/DefensiveSpiral/DefensiveManeuver/DBFM 커버
    "probe_energy",     # HighYoYo/AltitudeAdvantage/energy_diff 커버
    "probe_obfm",       # OneCircleFight/PurePursuit/overshoot_risk/in_39_line 커버
    "probe_habfm",      # ClimbingTurn/HABFM 커버
    "probe_gun_aggro",  # GunAttack 극단 공격 — WEZ 2km/45° (GUN_ATTACK 데이터 보강)
    "probe_gun_close",  # GunAttack 근거리 — WEZ 1km/25° (gen_gunfighter 변형)
]

MANIFEST_PATH = PROJECT_ROOT / "examples" / "archetypes" / "manifest.json"


def load_archetype_agents() -> list[str]:
    """manifest.json에서 아키타입 에이전트 이름 목록 반환.

    에이전트 이름 형식: 'examples/archetypes/{name}.yaml'
    (get_tree_path가 '/'를 직접 경로로 처리 → PROJECT_ROOT/examples/archetypes/{name}.yaml)
    """
    if not MANIFEST_PATH.exists():
        print(f"[경고] manifest 없음: {MANIFEST_PATH}  →  expand_archetypes.py 먼저 실행")
        return []
    with open(MANIFEST_PATH, encoding="utf-8") as f:
        data = json.load(f)
    return [
        f"examples/archetypes/{name}.yaml"
        for name, info in data["agents"].items()
        if info.get("source") == "archetype"
    ]


# 관측값 필드 — 커버리지 분석 대상
BOOL_OBS_FIELDS = [
    "in_wez", "enm_in_wez", "in_39_line", "overshoot_risk",
    "energy_advantage", "alt_advantage", "spd_advantage",
]
BFM_SITUATIONS = ["OBFM", "DBFM", "HABFM", "UNKNOWN"]


# ─── 매치 목록 빌드 ───────────────────────────────────────────

def build_match_list(base_agents, probe_agents=None):
    """
    매치 목록 생성.

    - base_agents 간 모든 쌍 (A vs B, B vs A)
    - probe_agents가 있으면: probe vs base, base vs probe (양방향)
      단, probe vs probe는 불필요하므로 제외
    """
    pairs = []

    # 기본 에이전트 간 매치
    for a1, a2 in product(base_agents, base_agents):
        if a1 != a2:
            pairs.append((a1, a2))

    if probe_agents:
        # 프로브 vs 기본 에이전트 (양방향)
        for probe in probe_agents:
            for agent in base_agents:
                pairs.append((probe, agent))
                pairs.append((agent, probe))

    return pairs


# ─── 단일 매치 실행 ───────────────────────────────────────────

def run_single_match(args):
    """Worker 함수 — (agent1, agent2, output_dir) 튜플 받아 매치 실행"""
    agent1, agent2, output_dir = args
    try:
        results = run_match(
            agent1=agent1,
            agent2=agent2,
            rounds=1,
            verbose=False,
            metadata_log=output_dir,
        )
        if results:
            r = results[0]
            return (agent1, agent2, r.get("winner", "?"),
                    r.get("tree1_health", 0), r.get("tree2_health", 0), None)
        return (agent1, agent2, "no_result", 0, 0, None)
    except Exception as e:
        return (agent1, agent2, "error", 0, 0, str(e))


def run_batch(batch_args):
    """Worker 함수 — 매치 배치를 순차 실행 (spawn 오버헤드 최소화).

    Args:
        batch_args: [(agent1, agent2, output_dir), ...] 리스트
    Returns:
        [(agent1, agent2, winner, hp1, hp2, err), ...]
    """
    return [run_single_match(a) for a in batch_args]


# ─── 커버리지 분석 ────────────────────────────────────────────

def analyze_coverage(output_dir: str):
    """
    수집된 CSV 파일의 커버리지 분석.

    확인 항목:
      - 총 rows, 매치 수
      - BFM 상황 분포 (OBFM/DBFM/HABFM/UNKNOWN)
      - Bool 관측값 True 비율 (in_wez, enm_in_wez, in_39_line, overshoot_risk, ...)
      - active_node 다양성 (발동된 BT 노드 수)
      - HP 감소 이벤트 비율 (데미지 발생 여부)
      - 클래스 분포 (승/무/패) — result JSON 집계
    """
    import csv
    import json

    meta_dir = Path(output_dir)
    csv_files = list(meta_dir.glob("*_meta.csv"))
    json_files = list(meta_dir.glob("*_result.json"))

    if not csv_files:
        print(f"  [커버리지] CSV 파일 없음: {output_dir}")
        return

    print(f"\n{'='*60}")
    print(f"  Phase 1 커버리지 분석")
    print(f"  CSV: {len(csv_files)}개  JSON: {len(json_files)}개")
    print(f"{'='*60}")

    # 전체 rows 집계
    total_rows = 0
    bfm_counts = defaultdict(int)
    bool_true_counts = defaultdict(int)
    active_nodes = set()
    hp_decrease_rows = 0
    prev_hp = {}  # (agent_id) → last health

    col_idx = {}  # column name → index

    for csv_path in csv_files:
        try:
            with open(csv_path, encoding='utf-8') as f:
                reader = csv.reader(f)
                header = next(reader)
                if not col_idx:
                    col_idx = {h: i for i, h in enumerate(header)}

                bfm_col = col_idx.get("bfm_situation", -1)
                node_col = col_idx.get("active_node", -1)
                health_col = col_idx.get("ego_health", -1)
                agent_col = col_idx.get("agent_id", -1)

                bool_cols = {f: col_idx.get(f, -1) for f in BOOL_OBS_FIELDS}

                file_prev_hp = {}
                for row in reader:
                    if not row:
                        continue
                    total_rows += 1

                    # BFM 상황
                    if bfm_col >= 0 and bfm_col < len(row):
                        bfm_counts[row[bfm_col]] += 1

                    # Bool 관측값
                    for field, ci in bool_cols.items():
                        if ci >= 0 and ci < len(row):
                            val = row[ci].strip().lower()
                            if val in ("true", "1"):
                                bool_true_counts[field] += 1

                    # active_node 수집
                    if node_col >= 0 and node_col < len(row):
                        node = row[node_col].strip().strip('"')
                        if node:
                            active_nodes.add(node)

                    # HP 감소 이벤트
                    if health_col >= 0 and agent_col >= 0 and health_col < len(row):
                        try:
                            agent = row[agent_col]
                            hp = float(row[health_col])
                            if agent in file_prev_hp and hp < file_prev_hp[agent]:
                                hp_decrease_rows += 1
                            file_prev_hp[agent] = hp
                        except (ValueError, IndexError):
                            pass
        except Exception as e:
            print(f"  [경고] {csv_path.name}: {e}")

    # result JSON 집계
    winners = {"tree1": 0, "tree2": 0, "draw": 0, "other": 0}
    for jp in json_files:
        try:
            with open(jp, encoding='utf-8') as f:
                d = json.load(f)
            w = d.get("winner", "other")
            if w in winners:
                winners[w] += 1
            else:
                winners["other"] += 1
        except Exception:
            pass

    total_matches = len(json_files)
    if total_rows == 0:
        print("  rows 없음")
        return

    print(f"\n  [규모]")
    print(f"    총 rows:   {total_rows:,}")
    print(f"    총 매치:   {total_matches}")
    print(f"    rows/매치: {total_rows / max(total_matches, 1):.0f}")

    print(f"\n  [클래스 분포]")
    total_m = sum(winners.values())
    for k, v in winners.items():
        pct = v / max(total_m, 1) * 100
        bar = "█" * int(pct / 3)
        print(f"    {k:8s}: {v:4d} ({pct:5.1f}%)  {bar}")

    print(f"\n  [BFM 상황 분포]")
    for sit in BFM_SITUATIONS + [k for k in bfm_counts if k not in BFM_SITUATIONS]:
        cnt = bfm_counts.get(sit, 0)
        pct = cnt / max(total_rows, 1) * 100
        bar = "█" * int(pct / 2)
        status = "" if sit not in ("",) else "  ← 주의"  # UNKNOWN은 SDK 정상 분류 (BFM 전이 구간)
        print(f"    {sit:10s}: {cnt:7,} ({pct:5.1f}%)  {bar}{status}")

    print(f"\n  [Bool 관측값 True 비율]")
    for field in BOOL_OBS_FIELDS:
        cnt = bool_true_counts.get(field, 0)
        pct = cnt / max(total_rows, 1) * 100
        bar = "█" * max(1, int(pct / 2)) if cnt > 0 else ""
        status = "  ← 미활성화" if cnt == 0 else ("  ← 희소" if pct < 1.0 else "")
        print(f"    {field:22s}: {cnt:7,} ({pct:5.1f}%)  {bar}{status}")

    print(f"\n  [HP 감소 이벤트]")
    hp_pct = hp_decrease_rows / max(total_rows, 1) * 100
    print(f"    HP 감소 rows: {hp_decrease_rows:,} ({hp_pct:.2f}%)")

    print(f"\n  [active_node 다양성]")
    print(f"    발동된 BT 노드 수: {len(active_nodes)}")
    for node in sorted(active_nodes):
        print(f"    - {node}")

    # ── UNKNOWN BFM 심층 분석 ──
    # UNKNOWN = Neutral Engagement (양측 측면 교착, scissors/neutral merge)
    # Phase 2 커스텀 노드 설계의 핵심 입력
    print(f"\n  [UNKNOWN BFM 분석 — Neutral Engagement]")
    unk_stats = {"count": 0, "ata": [], "aa": [], "hca": [], "dist": [], "closure": [],
                 "turn_rate": [], "next_bfm": Counter()}
    ata_col = col_idx.get("ata_deg", -1)
    aa_col = col_idx.get("aa_deg", -1)
    hca_col = col_idx.get("hca_deg", -1)
    dist_col = col_idx.get("distance_ft", -1)
    closure_col = col_idx.get("closure_rate_kts", -1)
    tr_col = col_idx.get("turn_rate_degs", -1)

    for csv_path in csv_files:
        try:
            with open(csv_path, encoding='utf-8') as f:
                reader = csv.reader(f)
                header = next(reader)
                prev_bfm = None
                for row in reader:
                    if not row or bfm_col < 0 or bfm_col >= len(row):
                        continue
                    cur_bfm = row[bfm_col]
                    # UNKNOWN → 다음 BFM 전이 추적
                    if prev_bfm == "UNKNOWN" and cur_bfm != "UNKNOWN":
                        unk_stats["next_bfm"][cur_bfm] += 1
                    if cur_bfm == "UNKNOWN":
                        unk_stats["count"] += 1
                        try:
                            if ata_col >= 0: unk_stats["ata"].append(float(row[ata_col]))
                            if aa_col >= 0: unk_stats["aa"].append(float(row[aa_col]))
                            if hca_col >= 0: unk_stats["hca"].append(float(row[hca_col]))
                            if dist_col >= 0: unk_stats["dist"].append(float(row[dist_col]))
                            if closure_col >= 0: unk_stats["closure"].append(float(row[closure_col]))
                            if tr_col >= 0: unk_stats["turn_rate"].append(float(row[tr_col]))
                        except (ValueError, IndexError):
                            pass
                    prev_bfm = cur_bfm
        except Exception:
            pass

    if unk_stats["count"] > 100:
        import statistics
        print(f"    총 UNKNOWN rows: {unk_stats['count']:,}")
        for fname, label in [("ata", "ATA°"), ("aa", "AA°"), ("hca", "HCA°"),
                              ("dist", "Dist(ft)"), ("closure", "Closure(kts)"),
                              ("turn_rate", "TurnRate(°/s)")]:
            vals = unk_stats[fname]
            if vals:
                print(f"    {label:15s}: median={statistics.median(vals):7.1f}  "
                      f"p25={sorted(vals)[len(vals)//4]:7.1f}  "
                      f"p75={sorted(vals)[3*len(vals)//4]:7.1f}")
        print(f"\n    UNKNOWN → 전이 목적지:")
        total_trans = sum(unk_stats["next_bfm"].values())
        for dest, cnt in unk_stats["next_bfm"].most_common():
            pct = cnt / max(total_trans, 1) * 100
            bar = "█" * int(pct / 3)
            print(f"      → {dest:10s}: {cnt:5,} ({pct:5.1f}%)  {bar}")
        print(f"    [Phase 2 시사점] UNKNOWN에서 가장 많이 전이하는 BFM으로의")
        print(f"    전이를 유도하는 커스텀 노드 설계 가능")
    else:
        print(f"    UNKNOWN rows 부족 ({unk_stats['count']}), 분석 생략")

    # 커버리지 판정
    print(f"\n  [커버리지 판정]")
    issues = []
    if total_matches < 200:
        issues.append(f"규모 부족: {total_matches}매치 < 200 (CMA-ES --collect-csv 권장)")
    if winners["draw"] / max(total_m, 1) > 0.35:
        issues.append(f"무승부 과다: {winners['draw']/max(total_m,1)*100:.0f}% > 35%")
    for f in BOOL_OBS_FIELDS:
        if bool_true_counts.get(f, 0) == 0:
            issues.append(f"미활성화: {f} (probe 에이전트 추가 필요)")
        elif bool_true_counts.get(f, 0) / max(total_rows, 1) < 0.005:
            issues.append(f"희소: {f} ({bool_true_counts[f]/max(total_rows,1)*100:.2f}%)")
    # UNKNOWN은 SDK의 정상 BFM 분류 — OBFM/DBFM/HABFM 전이 구간
    # (13.2.3 BFM 경계 문제 참조: ATA~50°, dist~6000ft 등 중간 상태)
    if len(active_nodes) < 8:
        issues.append(f"노드 다양성 부족: {len(active_nodes)}종 < 8")

    if issues:
        print(f"  ❌ 개선 필요 ({len(issues)}개 항목):")
        for issue in issues:
            print(f"    - {issue}")
    else:
        print("  ✅ 커버리지 충분")

    print(f"\n  [Phase 1 완료 기준]")
    print(f"    - 총 매치: {total_matches} / 목표 200+")
    print(f"    - 다음 단계: python tools/adaptive_optimizer.py --budget 400 --collect-csv")
    print(f"{'='*60}\n")


# ─── main ─────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Phase 1 대규모 메타데이터 수집 v2")
    parser.add_argument("--agents", nargs="+", default=None,
                        help="수집할 에이전트 목록 (기본: 전체 7종)")
    parser.add_argument("--probes", action="store_true",
                        help="전술 프로브 에이전트 포함 (5종 × 7 기본 × 2방향 = +70 매치)")
    parser.add_argument("--archetypes", action="store_true",
                        help="아키타입 에이전트 포함 (manifest에서 로드, 168개 × 기본 에이전트 양방향)")
    parser.add_argument("--output", type=str, default="logs/metadata",
                        help="출력 폴더 (기본: logs/metadata)")
    parser.add_argument("--workers", type=int, default=1,
                        help="병렬 워커 수 (기본: 1 순차, 권장: CPU 코어 수)")
    parser.add_argument("--chunk-size", type=int, default=0,
                        help="워커당 배치 크기 (기본: 자동, 총매치/workers/4)")
    parser.add_argument("--dry-run", action="store_true",
                        help="실행 계획만 출력, 실제 매치 없음")
    parser.add_argument("--coverage", action="store_true",
                        help="기존 CSV 커버리지 분석만 출력 (매치 실행 없음)")
    args = parser.parse_args()

    output_dir = str(PROJECT_ROOT / args.output)
    Path(output_dir).mkdir(parents=True, exist_ok=True)

    # 커버리지 분석 모드
    if args.coverage:
        analyze_coverage(output_dir)
        return

    base_agents = args.agents or AGENTS
    probe_agents = PROBE_AGENTS if args.probes else None

    # 아키타입 에이전트 로드 (--archetypes 플래그 시)
    archetype_agents = load_archetype_agents() if args.archetypes else None
    if archetype_agents:
        print(f"  아키타입 에이전트: {len(archetype_agents)}개 로드")

    pairs = build_match_list(base_agents, probe_agents)
    # 아키타입 에이전트는 기본 에이전트와 양방향 매치만 (arch × arch는 불필요)
    if archetype_agents:
        for arch in archetype_agents:
            for agent in base_agents:
                pairs.append((arch, agent))
                pairs.append((agent, arch))

    total = len(pairs)

    all_agents = base_agents + (probe_agents or []) + (archetype_agents or [])
    base_count = len(base_agents) * (len(base_agents) - 1)
    probe_count = total - base_count

    print(f"\n{'='*60}")
    print(f"  Phase 1 메타데이터 대규모 수집 v2")
    print(f"  기본 에이전트: {base_agents}")
    if probe_agents:
        print(f"  프로브 에이전트: {probe_agents}")
    if archetype_agents:
        print(f"  아키타입 에이전트: {len(archetype_agents)}개")
    print(f"  총 매치: {total}")
    print(f"    기본 매치: {base_count} ({len(base_agents)}×{len(base_agents)-1})")
    if probe_agents:
        print(f"    프로브 매치: {probe_count} (5프로브 × {len(base_agents)}기본 × 2방향)")
    print(f"  출력: {output_dir}")
    print(f"  워커: {args.workers}")
    print(f"{'='*60}\n")

    if args.dry_run:
        print("[ DRY RUN — 실행 계획 ]")
        for i, (a1, a2) in enumerate(pairs, 1):
            kind = "(probe)" if (a1 in (probe_agents or []) or a2 in (probe_agents or [])) else ""
            print(f"  {i:3d}. {a1:20s} vs {a2:20s} {kind}")
        return

    start = datetime.now()
    work_items = [(a1, a2, output_dir) for a1, a2 in pairs]

    results_summary = []
    if args.workers <= 1:
        for i, item in enumerate(work_items, 1):
            a1, a2, _ = item
            kind = " (P)" if (a1 in (probe_agents or []) or a2 in (probe_agents or [])) else "    "
            print(f"[{i:3d}/{total}] {a1:20s} vs {a2:20s}{kind} ...", end=" ", flush=True)
            result = run_single_match(item)
            _, _, winner, hp1, hp2, err = result
            if err:
                print(f"ERROR: {err}")
            else:
                tag = "W" if winner == "tree1" else ("D" if winner == "draw" else "L")
                print(f"{tag}  hp={hp1:.0f}/{hp2:.0f}")
            results_summary.append(result)
    else:
        # 배치 분할 — spawn 오버헤드를 줄이고 각 워커가 연속 실행
        chunk = args.chunk_size or max(1, total // (args.workers * 4))
        batches = [work_items[s:s + chunk] for s in range(0, total, chunk)]
        print(f"  배치: {len(batches)}개 × ~{chunk}매치/배치, 워커: {args.workers}")

        done = 0
        with ProcessPoolExecutor(max_workers=args.workers) as ex:
            futures = {ex.submit(run_batch, b): b for b in batches}
            for fut in as_completed(futures):
                batch_results = fut.result()
                for res in batch_results:
                    a1, a2, winner, hp1, hp2, err = res
                    done += 1
                    tag = "W" if winner == "tree1" else ("D" if winner == "draw" else "L")
                    status = f"ERROR: {err}" if err else f"{tag}  hp={hp1:.0f}/{hp2:.0f}"
                    elapsed_s = (datetime.now() - start).total_seconds()
                    eta = elapsed_s / done * (total - done) if done > 0 else 0
                    print(f"[{done:4d}/{total}] {a1:25s} vs {a2:25s}  {status}"
                          f"  ETA {eta/60:.1f}m", flush=True)
                    results_summary.append(res)

    elapsed = (datetime.now() - start).total_seconds()

    # 수집 요약
    wins   = sum(1 for r in results_summary if r[2] == "tree1")
    draws  = sum(1 for r in results_summary if r[2] == "draw")
    losses = sum(1 for r in results_summary if r[2] == "tree2")
    errors = sum(1 for r in results_summary if r[5])

    print(f"\n{'='*60}")
    print(f"  수집 완료!")
    print(f"  총 매치: {total}  W/D/L = {wins}/{draws}/{losses}  오류: {errors}")
    print(f"  소요: {elapsed/60:.1f}분")
    print(f"  출력 폴더: {output_dir}")
    print(f"{'='*60}\n")

    # 에이전트별 승률
    win_table = defaultdict(lambda: {"W": 0, "D": 0, "L": 0})
    for a1, a2, winner, *_ in results_summary:
        if winner == "tree1":
            win_table[a1]["W"] += 1
        elif winner == "draw":
            win_table[a1]["D"] += 1
        else:
            win_table[a1]["L"] += 1

    print("  에이전트별 승률:")
    for agent in all_agents:
        t = win_table[agent]
        total_m = t["W"] + t["D"] + t["L"]
        rate = t["W"] / total_m * 100 if total_m > 0 else 0
        kind = " [probe]" if agent in (probe_agents or []) else ""
        print(f"    {agent:20s}  W={t['W']:2d} D={t['D']:2d} L={t['L']:2d}  ({rate:.0f}%){kind}")

    # 커버리지 분석
    print()
    analyze_coverage(output_dir)


if __name__ == "__main__":
    mp.freeze_support()
    main()
