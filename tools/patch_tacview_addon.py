"""Tacview ai-combat-analysis addon 패치: 에너지단위 버그 수정 + Roll/Pitch 자세각 추가 + 버전 라벨.

Program Files는 admin 권한 필요 → staging(Desktop\\main_patched.lua)에 수정본 저장.
설치: 관리자 PowerShell에서  Copy-Item <staging> '<addon>\\main.lua'
"""
import os, sys

SRC = r"C:\Program Files (x86)\Tacview\AddOns\ai-combat-analysis-0.6\main.lua"
OUT = r"C:\Users\USER\Desktop\main_patched.lua"

s = open(SRC, encoding="utf-8").read()
orig = s
patches = []

def rep(old, new, tag):
    global s
    if old in s:
        s = s.replace(old, new, 1); patches.append(f"✓ {tag}")
    else:
        patches.append(f"✗ {tag} (원본 매칭 실패 — 수동확인 필요)")

# 1) Roll/Pitch 로컬 선언
rep('local _md = "-"\n',
    'local _md = "-"\nlocal _ro0, _pi0, _ro1, _pi1 = 0, 0, 0, 0   -- Roll/Pitch(deg) 자세각\n',
    "locals 선언")

# 2) 에너지 단위 버그 (kts→ft/s: *1.6878, 2g=64.34)
rep('local _af = _de + (_gf * _gf) / 64.4',
    'local _af = _de + (_gf * 1.6878) * (_gf * 1.6878) / 64.34',
    "에너지단위 obj0")
rep('local _ze = _fe + (_df * _df) / 64.4',
    'local _ze = _fe + (_df * 1.6878) * (_df * 1.6878) / 64.34',
    "에너지단위 obj1")

# 3) obj0 Roll/Pitch 계산 (altitude 읽은 직후)
rep('\t\t_de = _ob.altitude * _ge\n',
    '\t\t_de = _ob.altitude * _ge\n'
    '\t\t_ro0 = _ob.roll and round(_ob.roll * 180 / math.pi) or 0\n'
    '\t\t_pi0 = _ob.pitch and round(_ob.pitch * 180 / math.pi) or 0\n',
    "obj0 roll/pitch 계산")

# 4) obj1 Roll/Pitch 계산
rep('\t\t_fe = _jb.altitude * _ge\n',
    '\t\t_fe = _jb.altitude * _ge\n'
    '\t\t_ro1 = _jb.roll and round(_jb.roll * 180 / math.pi) or 0\n'
    '\t\t_pi1 = _jb.pitch and round(_jb.pitch * 180 / math.pi) or 0\n',
    "obj1 roll/pitch 계산")

# 5) obj0 패널에 Roll/Pitch 표시
rep('\t\t\t\t\t\t.."\\nG-Force: ".._je.." g"\n',
    '\t\t\t\t\t\t.."\\nG-Force: ".._je.." g"\n'
    '\t\t\t\t\t\t.."\\nRoll: ".._ro0.."  Pitch: ".._pi0\n',
    "obj0 패널 roll/pitch")

# 6) obj1 패널에 Roll/Pitch 표시
rep('\t\t\t\t\t\t.."\\nG-Force: ".._oe.." g"\n',
    '\t\t\t\t\t\t.."\\nG-Force: ".._oe.." g"\n'
    '\t\t\t\t\t\t.."\\nRoll: ".._ro1.."  Pitch: ".._pi1\n',
    "obj1 패널 roll/pitch")

# 7) 버전 라벨
rep('_jd.SetTitle("AI Combat Analysis 0.5")', '_jd.SetTitle("AI Combat Analysis 0.6")', "title 0.6")
rep('_jd.SetVersion("0.5.4")', '_jd.SetVersion("0.6.0")', "version 0.6.0")

open(OUT, "w", encoding="utf-8").write(s)
print("=== 패치 결과 ===")
for p in patches: print(" ", p)
print(f"\n변경: {len(orig)} → {len(s)} bytes")
print(f"수정본 저장: {OUT}")
print(f"\n설치(관리자 PowerShell):")
print(f'  Copy-Item "{OUT}" "{SRC}" -Force')
