"""report.txt 집계 — 여러 매치 report 를 한 표로 모아 공통 실패 레버 도출.

매 경기 report.txt(plot_match_3d_nme.match_report 출력)를 정규식 파싱 → 비교 표 + 집계.
usage: python tools/aggregate_reports.py [replays_glob]
  (기본: new_match_engine/replays/pol_*/report.txt)
"""
from __future__ import annotations
import glob
import os
import re
import sys

_RX = {
    "outcome": re.compile(r"outcome=(\S+)"),
    "dur":     re.compile(r"dur=(\d+)s"),
    "hp_us":   re.compile(r"HP us=(\-?\d+)"),
    "hp_op":   re.compile(r"opp=(\-?\d+)\s+dmg"),
    "dmg":     re.compile(r"dmg dealt=(\-?\d+)"),
    "taken":   re.compile(r"taken=(\-?\d+)"),
    "wez_n":   re.compile(r"WEZ\(us\):\s*(\d+)회"),
    "wez_dw":  re.compile(r"WEZ\(us\):.*?dwell=([\d.]+)s"),
    "dmin":    re.compile(r"거리:\s*min=(\d+)m"),
    "dmean":   re.compile(r"min=\d+m mean=(\d+)m"),
    "far":     re.compile(r"원>3 (\d+)%"),
    "closing": re.compile(r"closing (\d+)%"),
    "esus":    re.compile(r"Es us=(\-?\d+)"),
    "esop":    re.compile(r"Es us=\-?\d+ opp=(\-?\d+)"),
    "esdiff":  re.compile(r"Es_diff>0 (\d+)%"),
    "corner":  re.compile(r"코너±30kt 준수 (\d+)%"),
    "hdgrms":  re.compile(r"hdg RMS=([\d.]+)"),
    "pattern": re.compile(r"pattern=(\S+)"),
    "verdict": re.compile(r"⑦ 판정:\s*(.+)$", re.MULTILINE),
}


def parse_report(path):
    txt = open(path, encoding="utf-8").read()
    out = {"name": os.path.basename(os.path.dirname(path))}
    for k, rx in _RX.items():
        m = rx.search(txt)
        out[k] = m.group(1) if m else ""
    return out


def main():
    pat = sys.argv[1] if len(sys.argv) > 1 else \
        os.path.join(os.path.dirname(__file__), "..", "new_match_engine",
                     "replays", "pol_*", "report.txt")
    paths = sorted(glob.glob(pat))
    if not paths:
        print(f"report.txt 없음: {pat}"); return
    rows = [parse_report(p) for p in paths]
    # 최신 run 만 (이름 끝 _NNNN 최대) — 같은 spawn_opp 중복 시
    latest = {}
    for r in rows:
        base = re.sub(r"_\d+$", "", r["name"])
        if base not in latest or r["name"] > latest[base]["name"]:
            latest[base] = r
    rows = [latest[k] for k in sorted(latest)]

    hdr = ("match", "out", "dmg", "tkn", "WEZ#", "dwl", "dmin", "dmean",
           "far%", "cls%", "Esd%", "crn%", "hdgRMS", "pattern")
    print("%-26s %-7s %4s %4s %5s %5s %6s %6s %5s %5s %5s %5s %6s %s" % hdr)
    nwin = 0
    for r in rows:
        oc = r["outcome"]
        if oc.startswith("WIN"): nwin += 1
        print("%-26s %-7s %4s %4s %5s %5s %6s %6s %5s %5s %5s %5s %6s %s" % (
            r["name"][:26], oc[:7], r["dmg"], r["taken"], r["wez_n"], r["wez_dw"],
            r["dmin"], r["dmean"], r["far"], r["closing"], r["esdiff"],
            r["corner"], r["hdgrms"], r["pattern"]))
    print(f"\n총 {len(rows)} 매치 · WIN {nwin} · 미교전(WEZ#=0) "
          f"{sum(1 for r in rows if r['wez_n'] in ('0',''))}")
    # 공통 레버 집계
    def _avg(key, cast=float):
        vals = [cast(r[key]) for r in rows if r[key] not in ("", None)]
        return sum(vals) / len(vals) if vals else 0.0
    print(f"평균 dmg={_avg('dmg'):.0f} taken={_avg('taken'):.0f} | "
          f"WEZ dwell={_avg('wez_dw'):.1f}s | 원거리={_avg('far'):.0f}% | "
          f"Es_diff>0={_avg('esdiff'):.0f}% | 코너준수={_avg('corner'):.0f}% | "
          f"hdgRMS={_avg('hdgrms'):.0f}°")


if __name__ == "__main__":
    main()
