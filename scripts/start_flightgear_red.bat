@echo off
REM ============================================================
REM  FlightGear - Red F-16 (enemy agent)
REM  UDP port 5551, native-fdm receiver
REM  Run BEFORE: python scripts/run_match.py --flightgear
REM ============================================================

set FG_EXE=C:\Program Files\FlightGear 2024.1\bin\fgfs.exe
set FG_ROOT=C:\Users\USER\FlightGear\Downloads\fgdata_2024_1
set FG_AIRCRAFT=C:\Users\USER\FlightGear\Downloads\Aircraft\org.flightgear.fgaddon.stable_2024\Aircraft

echo [Red] Starting FlightGear F-16 on UDP port 5551...

"%FG_EXE%" ^
  --fg-root="%FG_ROOT%" ^
  --fg-aircraft="%FG_AIRCRAFT%" ^
  --aircraft=f16-block-52 ^
  --fdm=null ^
  --native-fdm=socket,in,60,,5551,udp ^
  --lat=60.0 ^
  --lon=120.001 ^
  --altitude=15000 ^
  --heading=0 ^
  --vc=400 ^
  --in-air ^
  --timeofday=noon ^
  --disable-auto-coordination ^
  --prop:/sim/rendering/fps-display=true ^
  --prop:/sim/current-view/view-number=1 ^
  --prop:/sim/model/livery/file=Aircraft/f16/Models/Liveries/Block50/93-0553.xml ^
  --prop:/environment/rain=0 ^
  --prop:/environment/snow=0 ^
  --callsign=Red

pause
