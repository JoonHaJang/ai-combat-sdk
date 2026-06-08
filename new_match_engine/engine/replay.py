"""Replay — 결정론 검증 + ACMI(Tacview) 출력.

결정론: 우리 엔진은 RNG 없음 (JSBSim 결정론 + side-switch 없음).
  같은 IC → 같은 결과. 검증: 2회 실행 → 궤적·health 동일.

ACMI: 120Hz 로그 → Tacview .acmi (text/acmi 2.2). 시각화·plot 호환.
  좌표계: T=Longitude|Latitude|Altitude(m)|Roll|Pitch|Yaw(=heading), 도/m.
"""
from __future__ import annotations
import sys, os, math
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "control"))

from plant import F16Plant
from lqr import GainScheduledLQR
from tactic import Tactic, WEZ_ATA_DEG, WEZ_MIN_FT, WEZ_MAX_FT, HARD_DECK_FT
from obs import FT_PER_DEG_LAT
from match import Match
from constants import FT_TO_M


def _in_wez(ata, dist):
    """WEZ 진입 여부 (judge 규약). Tacview InWEZ 플래그."""
    return 1 if (ata < WEZ_ATA_DEG and WEZ_MIN_FT <= dist <= WEZ_MAX_FT) else 0


class GunVisualizer:
    """Tacview 상에서 기총 궤적을 레이저(Beam) 형태로 시각화합니다."""
    def __init__(self, owner_acmi_id: str, color: str = "Orange"):
        self.owner_id = owner_acmi_id
        self.color = color
        self.beam_id = f"{self.owner_id}_LASER"
        self.is_firing = False
        
    def step(self, f, t: float, dt: float, is_firing: bool, lon: float, lat: float, alt_m: float, hdg: float, pitch: float):
        if is_firing:
            if not self.is_firing:
                # 레이저(Beam) 객체 생성. Tacview에서 텍스트 라벨이 표시되지 않게 Name 생략
                # 반투명 효과를 위해 Color=0xAARRGGBB 포맷 사용, 두께(Radius)를 10으로 키워 굵은 반투명 기둥 형성
                f.write(f"{self.beam_id},Type=Beam,Color={self.color},Length=1000,Radius=10\n")
                self.is_firing = True
            
            # 레이저 중심점 계산 (기수에서 500m 앞)
            dist = 500.0
            p_rad = math.radians(pitch)
            h_rad = math.radians(hdg)
            
            dx = dist * math.cos(p_rad) * math.sin(h_rad)  # East
            dy = dist * math.cos(p_rad) * math.cos(h_rad)  # North
            dz = dist * math.sin(p_rad)                    # Up
            
            R = 6378137.0
            dlat = math.degrees(dy / R)
            dlon = math.degrees(dx / (R * math.cos(math.radians(lat))))
            
            b_lon = lon + dlon
            b_lat = lat + dlat
            b_alt = alt_m + dz
            
            # 레이저 위치 및 자세 업데이트
            f.write(f"{self.beam_id},T={b_lon:.8f}|{b_lat:.8f}|{b_alt:.2f}|0|{pitch:.2f}|{hdg:.2f}\n")
        else:
            if self.is_firing:
                # 사격 중지 시 레이저 삭제
                f.write(f"-{self.beam_id}\n")
                self.is_firing = False


def next_run_dir(base: str, prefix: str = "run") -> str:
    """replays/ 아래 새 시도 전용 폴더 생성 (run_0001, run_0002, ...).

    ★ 새 시도마다 별도 폴더 (덮어쓰기 방지, 비교 가능).
    """
    os.makedirs(base, exist_ok=True)
    existing = [d for d in os.listdir(base)
                if d.startswith(prefix + "_") and os.path.isdir(os.path.join(base, d))]
    idx = 1 + max([int(d.split("_")[-1]) for d in existing if d.split("_")[-1].isdigit()],
                  default=0)
    run_dir = os.path.join(base, f"{prefix}_{idx:04d}")
    os.makedirs(run_dir, exist_ok=True)
    return run_dir


def write_acmi(log: list, path: str, title: str = "new_match_engine"):
    """120Hz 로그 → Tacview ACMI 2.2 text."""
    with open(path, "w", encoding="utf-8-sig") as f:
        f.write("FileType=text/acmi/tacview\n")
        f.write("FileVersion=2.2\n")
        f.write(f"0,ReferenceTime=2026-01-01T00:00:00Z,Title={title}\n")
        # 객체 2기 (101=blue, 102=red)
        f.write("101,Type=Air+FixedWing,Name=F-16,Color=Blue\n")
        f.write("102,Type=Air+FixedWing,Name=F-16,Color=Red\n")
        last_t = -1.0
        
        # 투명도(Alpha) 50% = 80 (Hex) 적용 (순수 AARRGGBB 문자열)
        gun1 = GunVisualizer("101", "800000FF")  # 반투명 파랑
        gun2 = GunVisualizer("102", "80FF0000")  # 반투명 빨강
        
        for row in log:
            t = row["t"]
            if t - last_t < 1e-6:
                continue
            dt = t - last_t if last_t >= 0 else 0.0
            last_t = t
            f.write(f"#{t:.4f}\n")
            # ACMI: T=Lon|Lat|Alt(m)|Roll|Pitch|Yaw
            f.write(f"101,T={row['lon1']:.8f}|{row['lat1']:.8f}|{row['alt1']*FT_TO_M:.2f}"
                    f"|{row['phi1']:.2f}|{row['theta1']:.2f}|{row['psi1']:.2f},"
                    f"Health={row['H1']:.1f}\n")
            f.write(f"102,T={row['lon2']:.8f}|{row['lat2']:.8f}|{row['alt2']*FT_TO_M:.2f}"
                    f"|{row['phi2']:.2f}|{row['theta2']:.2f}|{row['psi2']:.2f},"
                    f"Health={row['H2']:.1f}\n")
            
            # Gun tracer
            firing1 = bool(_in_wez(row['ata12'], row['dist']))
            firing2 = bool(_in_wez(row['ata21'], row['dist']))
            if dt > 0:
                gun1.step(f, t, dt, firing1, row['lon1'], row['lat1'], row['alt1']*FT_TO_M, row['psi1'], row['theta1'])
                gun2.step(f, t, dt, firing2, row['lon2'], row['lat2'], row['alt2']*FT_TO_M, row['psi2'], row['theta2'])
    return path


def write_acmi_plot(log: list, path: str, title: str = "new_match_engine"):
    """plot_match_3d_v2.py 호환 ACMI.

    ★ A0100(us=p1) / B0100(opp=p2) ID + BFM 필드(ATA/AA/Distance/CAS/HDG/...).
      plot 도구가 3D궤적·circle fit·phase lock(figure-8)·WEZ·에너지 분석.
    좌표: T=Lon|Lat|Alt(m)|Roll|Pitch|Yaw(=HDG).
    BFM 필드는 A0100(우리 관점)에 부착.
    """
    with open(path, "w", encoding="utf-8-sig") as f:
        # ── 헤더 (legacy runner_core.py 구조와 동일) ──
        f.write("FileType=text/acmi/tacview\n")
        f.write("FileVersion=2.2\n")
        f.write("0,ReferenceTime=2026-01-01T00:00:00Z\n")
        f.write(f"0,Title={title}\n")
        # ★ Type 선언은 첫 timestamp(#0.0) **뒤** = 프레임 0 안에서 (legacy 방식).
        #   global 섹션(#t 전)이 아니라 #0.0 후에 두어야 Tacview 가 객체를 정상 생성.
        f.write("#0.00\n")
        # ★ legacy 와 동일: Type 에 CallSign/Pilot 부착 (Tacview 객체 식별·라벨 유지).
        f.write("A0100,Type=Air+FixedWing,Name=F-16,CallSign=Blue1,Pilot=us,Color=Blue\n")
        f.write("B0100,Type=Air+FixedWing,Name=F-16,CallSign=Red1,Pilot=opp,Color=Red\n")
        last_t = -1.0
        prev_t = -1.0
        # ★ legacy(5Hz) 밀도로 다운샘플 (60Hz·11.6MB 고밀도가 Tacview 스트림 문제 의심).
        #   ~15Hz 면 시각화 충분, 파일 1/4. (분석은 별도 full-rate CSV 사용)
        MIN_DT = 1.0 / 15.0

        # 투명도(Alpha) 50% = 80 (Hex) 적용 (순수 AARRGGBB 문자열)
        gun1 = GunVisualizer("A0100", "800000FF")  # 반투명 파랑
        gun2 = GunVisualizer("B0100", "80FF0000")  # 반투명 빨강
        # ★ Tacview Event Log 상태 (legacy: tactic 전환·WEZ·피격을 0,Event=Message 로)
        pt1 = pt2 = None; pw1 = pw2 = 0
        hit1 = hit2 = 100.0      # ★ 마지막 HIT 이벤트 시점 HP (직전 프레임 아님 — 느린 연속피해 누적 검출)
        hd1 = hd2 = False; ko1 = ko2 = False    # 하드덱·격추 1회 이벤트 플래그

        for r in log:
            t = r["t"]
            if t - last_t < 1e-6:
                continue
            last_t = t
            if prev_t >= 0 and t - prev_t < MIN_DT:
                continue                    # 다운샘플 (legacy 밀도)
            dt = t - prev_t if prev_t >= 0 else 0.0
            prev_t = t
            f.write(f"#{t:.4f}\n")
            # ── Tacview Event Log (legacy 0,Event=Message|<id>|<text> 형식) ──
            #   tactic 전환 → 현재 전술명, WEZ 진입 → GUN, 피격 → damage. Event Log 패널 채움.
            wez1 = _in_wez(r['ata12'], r['dist']); wez2 = _in_wez(r['ata21'], r['dist'])
            if r['tac1'] != pt1:
                f.write(f"0,Event=Message|A0100|[Blue] us: {r['tac1']}\n"); pt1 = r['tac1']
            if r['tac2'] != pt2:
                f.write(f"0,Event=Message|B0100|[Red] opp: {r['tac2']}\n"); pt2 = r['tac2']
            if wez1 and not pw1:
                f.write(f"0,Event=Message|A0100|[Blue] us: GUN WEZ — firing\n")
            if wez2 and not pw2:
                f.write(f"0,Event=Message|B0100|[Red] opp: GUN WEZ — firing\n")
            if r['H1'] <= hit1 - 1.0:
                f.write(f"0,Event=Message|A0100|[Blue] us: HIT (HP {r['H1']:.0f})\n"); hit1 = r['H1']
            if r['H2'] <= hit2 - 1.0:
                f.write(f"0,Event=Message|B0100|[Red] opp: HIT (HP {r['H2']:.0f})\n"); hit2 = r['H2']
            # ★ Hard Deck (1000ft 미만) — judge 최우선 패배조건. 진입 시 1회 경고.
            if r['alt1'] < HARD_DECK_FT and not hd1:
                f.write(f"0,Event=Message|A0100|[Blue] us: HARD DECK ({r['alt1']:.0f}ft) — LOSS\n"); hd1 = True
            if r['alt2'] < HARD_DECK_FT and not hd2:
                f.write(f"0,Event=Message|B0100|[Red] opp: HARD DECK ({r['alt2']:.0f}ft) — LOSS\n"); hd2 = True
            # ★ 격추(HP 0) 이벤트
            if r['H1'] <= 0 and not ko1:
                f.write(f"0,Event=Message|A0100|[Blue] us: DESTROYED\n"); ko1 = True
            if r['H2'] <= 0 and not ko2:
                f.write(f"0,Event=Message|B0100|[Red] opp: DESTROYED\n"); ko2 = True
            pw1, pw2 = wez1, wez2
            # ★ legacy 좌표 그대로 (lat60/lon120) — legacy 도 동일 좌표로 Tacview 정상 렌더.
            lo1, la1 = r['lon1'], r['lat1']
            lo2, la2 = r['lon2'], r['lat2']
            # ── 위치 줄: 좌표 + Name + Color (★ legacy 와 동일 — Name 누락 시 Tacview 객체 cull 의심) ──
            f.write(f"A0100,T={lo1:.8f}|{la1:.8f}|{r['alt1']*FT_TO_M:.2f}"
                    f"|{r['phi1']:.2f}|{r['theta1']:.2f}|{r['psi1']:.2f},Name=F16,Color=Blue\n")
            f.write(f"B0100,T={lo2:.8f}|{la2:.8f}|{r['alt2']*FT_TO_M:.2f}"
                    f"|{r['phi2']:.2f}|{r['theta2']:.2f}|{r['psi2']:.2f},Name=F16,Color=Red\n")
            # ── 속성 줄: uid별 별도 줄 (legacy format_combat_info 방식) ──
            #   CAS 는 m/s (legacy 규약 — kts 로 쓰면 ~1.944배 오표시). plot 도구도 줄별 파싱 OK.
            f.write(f"A0100,HDG={r['psi1']:.2f},CAS={r['vc1']*0.514444:.2f},"
                    f"Health={r['H1']:.1f},ATA={r['ata12']:.2f},AA={r['aa12']:.2f},"
                    f"Distance={r['dist']:.1f},ClosureRate={r['clos12']:.1f},"
                    f"RelBearing={r['relb12']:.2f},InWEZ={wez1},Advantage={r['adv12']:.3f},"
                    f"Tactic={r['tac1']},EsDiff={r.get('ediff', 0.0):.0f},"
                    f"SetptHDG={r.get('sp_psi', 0.0):.1f},SetptAlt={r.get('sp_h', 0.0):.0f},"
                    f"SetptCAS={r.get('sp_v', 0.0):.1f},RollControlInput={r['ail1']:.4f},"
                    f"PitchControlInput={r['elev1']:.4f},YawControlInput={r['rud1']:.4f},"
                    f"Throttle={r['thr1']:.4f}\n")
            f.write(f"B0100,HDG={r['psi2']:.2f},CAS={r['vc2']*0.514444:.2f},"
                    f"Health={r['H2']:.1f},ATA={r['ata21']:.2f},AA={r['aa21']:.2f},"
                    f"Distance={r['dist']:.1f},InWEZ={wez2},Tactic={r['tac2']},"
                    f"RollControlInput={r['ail2']:.4f},PitchControlInput={r['elev2']:.4f},"
                    f"YawControlInput={r['rud2']:.4f},Throttle={r['thr2']:.4f}\n")

            # Gun tracer (legacy 좌표 그대로)
            if dt > 0:
                gun1.step(f, t, dt, bool(wez1), lo1, la1, r['alt1']*FT_TO_M, r['psi1'], r['theta1'])
                gun2.step(f, t, dt, bool(wez2), lo2, la2, r['alt2']*FT_TO_M, r['psi2'], r['theta2'])

    return path


def write_csv(log: list, path: str):
    """plot/분석용 CSV (전 필드)."""
    if not log:
        return path
    cols = list(log[0].keys())
    with open(path, "w", encoding="utf-8") as f:
        f.write(",".join(cols) + "\n")
        for row in log:
            # ★ string 컬럼(tac1/tac2) 은 그대로, float 만 6자리 포맷
            f.write(",".join(
                f"{v:.6f}" if isinstance(v, float) else str(v)
                for v in (row[c] for c in cols)) + "\n")
    return path


def _build_match(gs, log_hz=120.0):
    p1 = F16Plant(); p1.set_ic(15000.0, 350.0, psi_deg=0.0); p1.trim(); p1.step(5)
    p2 = F16Plant(); p2.set_ic(15000.0, 350.0, psi_deg=0.0)
    p2["ic/lat-gc-deg"] = 800.0 / FT_PER_DEG_LAT; p2["ic/psi-true-deg"] = 0.0
    p2.fdm.run_ic(); p2.trim(); p2.step(5)
    return Match(p1, p2, gs, log_hz=log_hz)


if __name__ == "__main__":
    import numpy as np
    print("=" * 60)
    print("  Replay — 결정론 검증 + ACMI 출력")
    print("=" * 60)

    gs = GainScheduledLQR([5000,15000,25000],[250,350,450]).build()
    lvl = lambda o: Tactic.LEVEL_FLIGHT

    # ── 결정론: 2회 실행 비교 ────────────────────────────────────────────
    print("\n[결정론] 동일 IC 2회 실행 → 결과 동일?")
    m1 = _build_match(gs); r1 = m1.run(lvl, lvl, duration_s=10.0)
    m2 = _build_match(gs); r2 = m2.run(lvl, lvl, duration_s=10.0)
    same_h = (abs(r1.health1 - r2.health1) < 1e-9 and abs(r1.health2 - r2.health2) < 1e-9)
    same_t = (r1.time_s == r2.time_s)
    # 궤적 체크섬 (마지막 행 위치)
    same_traj = True
    if r1.log and r2.log and len(r1.log) == len(r2.log):
        for a, b in zip(r1.log, r2.log):
            if abs(a["lat1"]-b["lat1"]) > 1e-12 or abs(a["alt2"]-b["alt2"]) > 1e-9:
                same_traj = False; break
    else:
        same_traj = False
    print(f"  health 동일: {same_h}  (run1 H2={r1.health2:.4f}, run2 H2={r2.health2:.4f})")
    print(f"  kill time 동일: {same_t}  ({r1.time_s:.3f}s)")
    print(f"  궤적 bit 동일: {same_traj}  (행수 {len(r1.log)})")
    det_ok = same_h and same_t and same_traj
    print(f"  → {'✅ 결정론 확인' if det_ok else '❌ 비결정론!'}")

    # ── ACMI / CSV 출력 (새 시도 = 별도 폴더) ───────────────────────────
    print("\n[출력] 120Hz 로그 → 별도 run 폴더")
    base = os.path.join(os.path.dirname(__file__), "..", "replays")
    run_dir = next_run_dir(base)
    acmi = write_acmi(r1.log, os.path.join(run_dir, "match.acmi"))
    csv  = write_csv(r1.log,  os.path.join(run_dir, "match.csv"))
    print(f"  폴더: {os.path.relpath(run_dir)}/")
    print(f"  ACMI: match.acmi  ({len(r1.log)} frames @120Hz)")
    print(f"  CSV : match.csv")
    print(f"  → Tacview 로 .acmi 열어 궤적 확인 가능")
