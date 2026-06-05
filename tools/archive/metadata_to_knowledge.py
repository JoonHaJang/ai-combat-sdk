"""
metadata_to_knowledge.py — collect_phase1 metadata CSV → knowledge DB

collect_phase1.py가 생성한 per-tick CSV에서 풍부한 통계를 추출해
logs/knowledge/matches.jsonl, situations.jsonl에 저장.

ACMI 분석보다 훨씬 상세:
  - 매 tick BFM situation (OBFM/DBFM/HABFM/UNKNOWN)
  - 매 tick active_node, in_wez, overshoot_risk 등
  - BFM 전이 통계 (UNKNOWN → OBFM 등)
  - Rigid-behavior 자동 탐지
  - 상황별 승/패 상관관계

사용:
    python tools/metadata_to_knowledge.py ingest logs/metadata/gwangpung/
    python tools/metadata_to_knowledge.py summary
    python tools/metadata_to_knowledge.py situations
"""

import argparse
import csv
import json
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from tools.hypothesis_tracker import register_situation

KNOWLEDGE_DIR = PROJECT_ROOT / "logs" / "knowledge"
MATCHES_DB = KNOWLEDGE_DIR / "matches.jsonl"


def parse_csv_match(csv_path: Path):
    """CSV + 대응 result.json 파싱 → rich record dict."""
    result_path = csv_path.with_name(csv_path.stem + "_result.json")
    result = {}
    if result_path.exists():
        with open(result_path, encoding="utf-8") as f:
            result = json.load(f)

    # per-tick 수집 (ego agent만 — agent_id=='0' 또는 name match)
    ticks_ego = []   # 1번 agent 관점
    ticks_enm = []

    with open(csv_path, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            try:
                step = int(row["step"])
            except Exception:
                continue
            agent_id = row.get("agent_id", "")
            # 1v1 기준 첫 agent를 ego로
            if step == 0 and not ticks_ego:
                ticks_ego.append(row)
                ego_id = agent_id
                ticks_ego = []  # reset, 정확한 id 기반으로 다시
                break

    # 다시 읽되 ego/enm 구분
    ego_id = None
    with open(csv_path, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if ego_id is None:
                ego_id = row["agent_id"]
            if row["agent_id"] == ego_id:
                ticks_ego.append(row)
            else:
                ticks_enm.append(row)

    n = len(ticks_ego)
    if n == 0:
        return None

    def _f(row, key, default=0.0):
        try:
            return float(row.get(key, default))
        except Exception:
            return default

    def _b(row, key):
        v = row.get(key, "false")
        return str(v).strip().lower() in ("true", "1")

    # 집계
    bfm_counts = Counter()
    node_counts = Counter()
    wez_ticks = 0
    overshoot_ticks = 0
    energy_adv_ticks = 0
    alt_adv_ticks = 0
    hp_decrease_ticks = 0
    bfm_transitions = Counter()  # (prev, cur) → count

    ata_list, aa_list, dist_list, closure_list, e_diff_list = [], [], [], [], []

    prev_hp = None
    prev_bfm = None
    for row in ticks_ego:
        bfm = row.get("bfm_situation", "UNKNOWN")
        bfm_counts[bfm] += 1
        if prev_bfm and prev_bfm != bfm:
            bfm_transitions[(prev_bfm, bfm)] += 1
        prev_bfm = bfm

        node = row.get("active_node", "").strip('"')
        if node:
            node_counts[node] += 1

        if _b(row, "in_wez"):
            wez_ticks += 1
        if _b(row, "overshoot_risk"):
            overshoot_ticks += 1
        if _b(row, "energy_advantage"):
            energy_adv_ticks += 1
        if _b(row, "alt_advantage"):
            alt_adv_ticks += 1

        hp = _f(row, "ego_health", 100)
        if prev_hp is not None and hp < prev_hp - 0.1:
            hp_decrease_ticks += 1
        prev_hp = hp

        ata_list.append(_f(row, "ata_deg"))
        aa_list.append(_f(row, "aa_deg"))
        dist_list.append(_f(row, "distance_ft"))
        closure_list.append(_f(row, "closure_rate_kts"))
        e_diff_list.append(_f(row, "energy_diff_ft"))

    def _stats(vals):
        if not vals:
            return {"min": 0, "max": 0, "avg": 0, "median": 0}
        s = sorted(vals)
        return {
            "min": round(s[0], 1),
            "max": round(s[-1], 1),
            "avg": round(sum(vals) / len(vals), 1),
            "median": round(s[len(s)//2], 1),
        }

    winner = result.get("winner", "unknown")
    # collect_phase1 JSON uses tree1_hp/tree2_hp; older code used tree1_health.
    tree1_hp = result.get("tree1_hp", result.get("tree1_health", 100))
    tree2_hp = result.get("tree2_hp", result.get("tree2_health", 100))
    hp_diff = tree1_hp - tree2_hp

    # outcome category
    if abs(hp_diff) < 0.5 and tree1_hp > 99 and tree2_hp > 99:
        outcome = "DRAW_NO_ENGAGEMENT"
    elif hp_diff > 10:
        outcome = "WIN_DOMINANT"
    elif hp_diff > 2:
        outcome = "WIN_MARGINAL"
    elif hp_diff > -2:
        outcome = "DRAW_ENGAGED"
    elif hp_diff > -10:
        outcome = "LOSS_MARGINAL"
    else:
        outcome = "LOSS_DOMINANT"

    ego_name = (result.get("tree1_agent") or result.get("tree1_name")
                or csv_path.stem.split("_vs_")[0].split("_", 2)[-1])
    enm_name = (result.get("tree2_agent") or result.get("tree2_name")
                or csv_path.stem.split("_vs_")[-1].replace("_meta", ""))

    return {
        "schema_version": "1.0",
        "ts": datetime.now().isoformat(),
        "source": "metadata_csv",
        "data_path": str(csv_path),
        "agent": {
            "name": ego_name,
            "version": None,         # caller가 채움
            "yaml_path": None,
        },
        "opponent": {
            "name": enm_name,
            "yaml_path": None,
        },
        "tags": {
            "agent_name": ego_name,
            "agent_version": None,
            "source_tool": "metadata_to_knowledge",
            "collection_batch": None,
            "hypothesis_id": None,
            "cycle_id": None,
        },
        "outcome": {
            "winner": winner,
            "category": outcome,
            "tree1_hp": tree1_hp,
            "tree2_hp": tree2_hp,
            "hp_diff": round(hp_diff, 2),
            "duration_s": n * 0.2,
            "n_ticks": n,
        },
        "metrics": {
            "wez_pct": round(100 * wez_ticks / n, 2),
            "overshoot_pct": round(100 * overshoot_ticks / n, 1),
            "energy_adv_pct": round(100 * energy_adv_ticks / n, 1),
            "alt_adv_pct": round(100 * alt_adv_ticks / n, 1),
            "hp_decrease_ticks": hp_decrease_ticks,
            "ata": _stats(ata_list),
            "aa": _stats(aa_list),
            "distance": _stats(dist_list),
            "closure": _stats(closure_list),
            "energy_diff": _stats(e_diff_list),
        },
        "bfm_pct": {k: round(100 * v / n, 1) for k, v in bfm_counts.items()},
        "bfm_transitions": {f"{a}->{b}": c for (a, b), c in bfm_transitions.most_common(10)},
        "top_nodes": dict(node_counts.most_common(8)),
    }


def _parse_kv_tag(tag_str):
    """"key1=val1,key2=val2" → dict."""
    if not tag_str:
        return {}
    out = {}
    for part in tag_str.split(","):
        part = part.strip()
        if "=" in part:
            k, v = part.split("=", 1)
            out[k.strip()] = v.strip()
    return out


def ingest_directory(path: Path, tag=None, agent_version=None,
                     agent_yaml=None, collection_batch=None,
                     hypothesis_id=None, cycle_id=None):
    """디렉토리의 모든 CSV를 knowledge DB에 추가.

    Args:
        path: CSV 디렉토리
        tag: "key1=val1,key2=val2" 형식 (backward compat)
        또는 개별 파라미터로 명시
    """
    KNOWLEDGE_DIR.mkdir(parents=True, exist_ok=True)
    csv_files = sorted(Path(path).glob("*_meta.csv"))
    if not csv_files:
        print(f"  No CSV found in {path}")
        return []

    # tag string을 dict로 파싱 (backward compat)
    kv = _parse_kv_tag(tag) if isinstance(tag, str) else {}
    agent_version = agent_version or kv.get("agent_version")
    collection_batch = collection_batch or kv.get("collection_batch")
    hypothesis_id = hypothesis_id or kv.get("hypothesis_id")
    cycle_id = cycle_id or kv.get("cycle_id")

    added = []
    with open(MATCHES_DB, "a", encoding="utf-8") as f:
        for csv_path in csv_files:
            try:
                rec = parse_csv_match(csv_path)
                if rec is None:
                    continue
                # 태그 채우기
                rec["agent"]["version"] = agent_version
                rec["agent"]["yaml_path"] = agent_yaml
                rec["tags"]["agent_version"] = agent_version
                rec["tags"]["collection_batch"] = collection_batch
                rec["tags"]["hypothesis_id"] = hypothesis_id
                rec["tags"]["cycle_id"] = cycle_id

                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
                added.append(rec)
                oc = rec["outcome"]["category"]
                hp = rec["outcome"]["hp_diff"]
                wez = rec["metrics"]["wez_pct"]
                ata = rec["metrics"]["ata"]["avg"]
                print(f"  + {csv_path.name[:50]}: {oc}  hp_diff={hp:+.1f}  "
                      f"wez={wez}%  ATA={ata}°")
            except Exception as e:
                print(f"  ! {csv_path.name}: {e}")
    print(f"\n  Ingested {len(added)} records → {MATCHES_DB}")
    return added


def extract_situations_from_matches(agent_version=None):
    """matches.jsonl에서 상황 패턴 자동 추출.

    Args:
        agent_version: 특정 버전만 필터 (None이면 전체)
    """
    if not MATCHES_DB.exists():
        return
    # Schema 1.0 레코드만 + (선택) 버전 필터
    records = []
    with open(MATCHES_DB, encoding="utf-8") as f:
        for line in f:
            if line.strip():
                try:
                    r = json.loads(line)
                    # schema 1.0만
                    if r.get("schema_version") != "1.0":
                        continue
                    if agent_version and r.get("tags", {}).get("agent_version") != agent_version:
                        continue
                    records.append(r)
                except Exception:
                    pass

    if not records:
        print(f"  No schema_v1 records {f'for {agent_version}' if agent_version else ''}.")
        return

    # 그룹핑 (schema 1.0: outcome.category)
    wins = [r for r in records if r["outcome"]["category"].startswith("WIN")]
    losses = [r for r in records if r["outcome"]["category"].startswith("LOSS")]
    draws = [r for r in records if r["outcome"]["category"].startswith("DRAW")]

    print(f"\n  Win: {len(wins)}  Draw: {len(draws)}  Loss: {len(losses)}")

    def _avg(records, path):
        vals = []
        for r in records:
            v = r
            try:
                for p in path:
                    v = v[p]
                vals.append(float(v))
            except Exception:
                pass
        return sum(vals) / len(vals) if vals else 0

    print(f"\n  {'Metric':25s}  {'WIN':>10s}  {'DRAW':>10s}  {'LOSS':>10s}")
    print(f"  {'-'*25}  {'-'*10}  {'-'*10}  {'-'*10}")
    # schema 1.0 경로: metrics.*
    metrics = [
        ("ATA avg", ["metrics", "ata", "avg"]),
        ("AA avg", ["metrics", "aa", "avg"]),
        ("Distance avg", ["metrics", "distance", "avg"]),
        ("Closure avg", ["metrics", "closure", "avg"]),
        ("Energy diff avg", ["metrics", "energy_diff", "avg"]),
        ("WEZ %", ["metrics", "wez_pct"]),
        ("Overshoot %", ["metrics", "overshoot_pct"]),
        ("Energy adv %", ["metrics", "energy_adv_pct"]),
    ]
    for label, path in metrics:
        w = _avg(wins, path)
        d = _avg(draws, path)
        l = _avg(losses, path)
        print(f"  {label:25s}  {w:>+10.1f}  {d:>+10.1f}  {l:>+10.1f}")

    # BFM 분포 (schema 1.0: bfm_pct)
    print(f"\n  BFM distribution:")
    for cat, subset in [("WIN", wins), ("DRAW", draws), ("LOSS", losses)]:
        if not subset:
            continue
        bfm_avg = defaultdict(float)
        for r in subset:
            for k, v in r.get("bfm_pct", {}).items():
                bfm_avg[k] += v
        for k in bfm_avg:
            bfm_avg[k] /= len(subset)
        parts = "  ".join(f"{k}={v:.0f}%" for k, v in sorted(bfm_avg.items(), key=lambda x: -x[1]))
        print(f"    {cat:5s} ({len(subset)}): {parts}")

    # BFM 전이
    print(f"\n  Top BFM transitions (WIN vs LOSS):")
    for cat, subset in [("WIN", wins), ("LOSS", losses)]:
        trans = Counter()
        for r in subset:
            for k, v in r.get("bfm_transitions", {}).items():
                trans[k] += v
        parts = "  ".join(f"{k}={v}" for k, v in trans.most_common(5))
        print(f"    {cat}: {parts}")

    # 자동 상황 등록
    if wins and losses:
        # 대표 조건 (schema 1.0 경로)
        w_ata = _avg(wins, ["metrics", "ata", "avg"])
        l_ata = _avg(losses, ["metrics", "ata", "avg"])
        w_wez = _avg(wins, ["metrics", "wez_pct"])
        l_edf = _avg(losses, ["metrics", "energy_diff", "avg"])

        register_situation(
            "ADVANTAGE",
            f"avg_ATA < {(w_ata + l_ata)/2:.0f}",
            freq=len(wins),
            outcome_mix={"WIN": 1.0, "DRAW": 0.0, "LOSS": 0.0},
            source="metadata_csv_auto",
        )
        if l_edf > 3000:
            register_situation(
                "DISADVANTAGE",
                f"avg_ATA > {(w_ata + l_ata)/2:.0f} AND energy_diff > {l_edf*0.8:.0f}",
                freq=len(losses),
                outcome_mix={"WIN": 0.0, "LOSS": 1.0},
                source="metadata_csv_auto",
            )
        print(f"\n  Registered situations from metadata_csv.")


def main():
    ap = argparse.ArgumentParser(description="Metadata CSV → Knowledge DB")
    sub = ap.add_subparsers(dest="cmd")

    p_in = sub.add_parser("ingest", help="CSV 디렉토리를 knowledge DB로 추가")
    p_in.add_argument("path")
    p_in.add_argument("--tag", default=None,
                      help="key1=val1,key2=val2 형식")
    p_in.add_argument("--agent-version", default=None)
    p_in.add_argument("--agent-yaml", default=None)
    p_in.add_argument("--collection-batch", default=None)
    p_in.add_argument("--hypothesis-id", default=None)
    p_in.add_argument("--cycle-id", default=None)

    p_sit = sub.add_parser("situations", help="metadata_csv 레코드에서 상황 추출")
    p_sit.add_argument("--agent-version", default=None,
                       help="특정 버전만 필터")

    args = ap.parse_args()

    if args.cmd == "ingest":
        ingest_directory(
            Path(args.path),
            tag=args.tag,
            agent_version=args.agent_version,
            agent_yaml=args.agent_yaml,
            collection_batch=args.collection_batch,
            hypothesis_id=args.hypothesis_id,
            cycle_id=args.cycle_id,
        )
    elif args.cmd == "situations":
        extract_situations_from_matches(agent_version=args.agent_version)
    else:
        ap.print_help()


if __name__ == "__main__":
    main()