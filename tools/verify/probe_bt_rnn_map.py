"""전체 BT 액션공간 → RNN → JSBSim transfer-function 전수 측정 (2026-06-01).

사용자 지시: "매핑 먼저 전체 공간 면밀히 → 규칙 도출 → 전략".
국소 재발견(hdg 해상도/throttle/state-dep)을 한 번에 끝내기 위한 단일 probe.

방법:
  - PROBE_ACTION="alt,hdg,vel" env 로 우리 BT가 관측 무시하고 고정 액션 반환.
  - 우리 agent(고정) vs simple(레퍼런스) 짧은 매치 → ACMI 에서 우리(A0100) 진짜
    CAS/HDG/alt 궤적 추출 + CSV 에서 신뢰가능한 throttle(ll_act) 추출.
  - steady-state(후반부) 평균: throttle, dCAS/dt, turn_rate(dHDG/dt), climb(dalt/dt).

출력: results/bt_rnn_map.csv  (225 행: alt,hdg,vel,throttle,cas,dcas,turn,climb)

usage:
    python tools/verify/probe_bt_rnn_map.py            # full 225
    python tools/verify/probe_bt_rnn_map.py --quick    # 축별 sweep (19개)
"""
from __future__ import annotations
import os, sys, re, csv, glob, subprocess, math
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "results" / "bt_rnn_map.csv"
OUT.parent.mkdir(parents=True, exist_ok=True)
MAX_STEPS = 120          # 24s — steady-state 도달 충분
SETTLE = 60              # 후반 60 step 만 steady-state 로 사용
KTS = 1.0


def latest(pattern):
    fs = sorted(glob.glob(str(ROOT / pattern)), key=os.path.getmtime)
    return fs[-1] if fs else None


def parse_acmi_track(acmi_path, uid_prefix="A0100"):
    """ACMI 에서 한 기체의 (t, lon, lat, alt_m, hdg) 궤적.
    T= 필드 = lon|lat|alt|roll|pitch|yaw. heading=yaw. CAS 없음 → 위치델타로 속도산출."""
    out = []
    cur_t = 0.0
    for line in open(acmi_path, encoding="utf-8", errors="replace"):
        line = line.strip()
        if line.startswith("#"):
            try: cur_t = float(line[1:])
            except: pass
            continue
        if line.startswith(uid_prefix + ",T="):
            seg = line.split("T=", 1)[1].split(",", 1)[0]
            parts = seg.split("|")
            try:
                lon = float(parts[0]); lat = float(parts[1]); alt = float(parts[2])
                yaw = float(parts[5]) if len(parts) > 5 and parts[5] else None
            except:
                continue
            out.append((cur_t, lon, lat, alt, yaw))
    return out


def unwrap_deg(seq):
    if not seq: return seq
    out = [seq[0]]
    for v in seq[1:]:
        d = v - out[-1]
        while d > 180: d -= 360
        while d < -180: d += 360
        out.append(out[-1] + d)
    return out


def run_probe(alt, hdg, vel):
    env = os.environ.copy()
    env["PROBE_ACTION"] = f"{alt},{hdg},{vel}"
    env.pop("ADVERSARY", None)
    csv_dir = ROOT / "results" / "probe_csv"
    csv_dir.mkdir(parents=True, exist_ok=True)
    cmd = ["python", "scripts/run_match.py",
           "--agent1", "examples/pursuit_chase_v1/pursuit_chase_btcost.yaml",
           "--agent2", "simple", "--rounds", "1", "--max-steps", str(MAX_STEPS),
           "--scenario", "bt_vs_bt", "--quiet",
           "--log-csv", str(csv_dir / f"p_{alt}_{hdg}_{vel}.csv")]
    try:
        subprocess.run(cmd, capture_output=True, text=True, timeout=90, cwd=ROOT, env=env)
    except Exception as e:
        return None
    acmi = latest("replays/*pursuit_chase_btcost_vs_simple*.acmi")
    if not acmi:
        return None
    trk = parse_acmi_track(acmi, "A0100")
    if len(trk) < SETTLE + 5:
        return None
    tail = trk[-SETTLE:]
    ts  = [r[0] for r in tail]
    lons = [r[1] for r in tail]; lats = [r[2] for r in tail]
    alts = [r[3] * 3.28084 for r in tail]          # m→ft
    hdgs = unwrap_deg([r[4] for r in tail if r[4] is not None])
    dt = (ts[-1] - ts[0]) / max(1, len(ts) - 1)
    # 속도 = 위치 델타 (ground speed, kt). lat/lon deg → m.
    lat0 = sum(lats) / len(lats)
    mlat = 111320.0; mlon = 111320.0 * math.cos(math.radians(lat0))
    spd = []
    for i in range(1, len(tail)):
        ddt = ts[i] - ts[i-1]
        if ddt <= 0: continue
        dN = (lats[i]-lats[i-1])*mlat; dE = (lons[i]-lons[i-1])*mlon
        dU = (alts[i]-alts[i-1])/3.28084
        spd.append(math.sqrt(dN*dN+dE*dE+dU*dU)/ddt * 1.94384)   # m/s→kt
    def rate(seq):
        if len(seq) < 2: return 0.0
        return (seq[-1] - seq[0]) / max(1e-6, (len(seq) - 1) * dt)
    cas_mean = sum(spd) / len(spd) if spd else 0.0
    climb = rate(alts)                              # ft/s
    turn = rate(hdgs) if len(hdgs) > 1 else 0.0     # deg/s
    dcas = (spd[-1]-spd[0])/max(1e-6,(len(spd)-1)*dt) if len(spd) > 1 else 0.0  # kt/s
    # throttle: CSV ll_act (신뢰)
    thr = 0.0
    csvf = csv_dir / f"p_{alt}_{hdg}_{vel}.csv"
    inner = sorted(glob.glob(str(csvf).replace(".csv", ".csv") + "/*.csv") +
                   glob.glob(str(csvf) + "/*.csv"))
    cand = inner[-1] if inner else (str(csvf) if csvf.exists() else None)
    if cand and os.path.isfile(cand):
        rows = [r for r in csv.DictReader(open(cand, encoding="utf-8"))
                if str(r.get("agent_id", "")).startswith("A")]
        thr_vals = []
        for r in rows[-SETTLE:]:
            try: thr_vals.append(float(r["throttle"]))
            except: pass
        thr = sum(thr_vals) / len(thr_vals) if thr_vals else 0.0
    return dict(alt=alt, hdg=hdg, vel=vel, throttle=round(thr, 3),
               cas=round(cas_mean, 1), dcas=round(dcas, 3),
               turn=round(turn, 2), climb=round(climb, 2))


def main():
    quick = "--quick" in sys.argv
    if quick:
        combos = ([(2, 4, v) for v in range(5)] +          # vel sweep
                  [(2, h, 3) for h in range(9)] +          # hdg sweep
                  [(a, 4, 2) for a in range(5)])           # alt sweep
    else:
        combos = [(a, h, v) for a in range(5) for h in range(9) for v in range(5)]
    print(f"probe {len(combos)} combos, max_steps={MAX_STEPS}")
    results = []
    for i, (a, h, v) in enumerate(combos):
        r = run_probe(a, h, v)
        if r:
            results.append(r)
            print(f"[{i+1}/{len(combos)}] a{a} h{h} v{v} | thr={r['throttle']:.2f} "
                  f"cas={r['cas']:.0f} dcas={r['dcas']:+.2f} turn={r['turn']:+.1f} climb={r['climb']:+.1f}")
        else:
            print(f"[{i+1}/{len(combos)}] a{a} h{h} v{v} | FAILED")
    with open(OUT, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["alt","hdg","vel","throttle","cas","dcas","turn","climb"])
        w.writeheader()
        for r in results:
            w.writerow(r)
    print(f"\nsaved {len(results)} rows → {OUT}")


if __name__ == "__main__":
    main()
