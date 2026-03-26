"""
CesiumJS WebSocket Server

JSBSim 매치 상태를 브라우저 CesiumJS 뷰어에 실시간 브로드캐스트.
asyncio WebSocket 서버를 백그라운드 스레드에서 실행 — 매치 루프를 블로킹하지 않음.
"""

import asyncio
import functools
import http.server
import json
import math
import os
import threading

try:
    import websockets
    _HAS_WS = True
except ImportError:
    _HAS_WS = False


def _get_agent_state(agent) -> dict:
    """AircraftSimulator에서 위치/자세/속도 추출 → dict 반환"""
    lon, lat, alt_m = agent.get_geodetic()    # lon[deg], lat[deg], alt[m]
    roll_r, pitch_r, yaw_r = agent.get_rpy()  # radians
    try:
        vn, ve, vu = agent.get_velocity()     # m/s
        speed_kts = math.sqrt(vn**2 + ve**2 + vu**2) / 0.514444
    except Exception:
        speed_kts = 0.0
    return {
        "lon":       round(lon, 6),
        "lat":       round(lat, 6),
        "alt_m":     round(alt_m, 1),
        "heading":   round(math.degrees(yaw_r) % 360, 2),
        "pitch":     round(math.degrees(pitch_r), 2),
        "roll":      round(math.degrees(roll_r), 2),
        "speed_kts": round(speed_kts, 1),
    }


def _start_static_server(static_dir: str, port: int = 5173):
    """내장 http.server로 정적 파일 서빙 (배포용, 백그라운드 스레드).

    Args:
        static_dir: 서빙할 디렉터리 (예: web-flight-simulator/dist)
        port: HTTP 포트 (기본 5173)
    """
    handler = functools.partial(
        http.server.SimpleHTTPRequestHandler,
        directory=os.path.abspath(static_dir),
    )
    server = http.server.HTTPServer(("", port), handler)
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    print(f"[CesiumStatic] http://localhost:{port} → {static_dir}")
    return server


class CesiumWSServer:
    """JSBSim 상태를 WebSocket으로 브라우저에 브로드캐스트하는 서버"""

    def __init__(self, host: str = "localhost", port: int = 8765,
                 serve_static: str = None, static_port: int = 5173):
        self.host = host
        self.port = port
        self._clients: set = set()
        self._loop: asyncio.AbstractEventLoop = None
        self._latest: dict = None
        self._thread: threading.Thread = None
        self._ready = threading.Event()
        self._static_server = None
        if serve_static:
            self._static_server = _start_static_server(serve_static, static_port)

    def start(self):
        """백그라운드 스레드에서 WebSocket 서버 시작"""
        if not _HAS_WS:
            print("[CesiumWS] 경고: 'websockets' 패키지 없음 → pip install websockets")
            return
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()
        self._ready.wait(timeout=3.0)

    def _run_loop(self):
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        self._loop.run_until_complete(self._serve())

    async def _serve(self):
        async with websockets.serve(self._handler, self.host, self.port):
            print(f"[CesiumWS] ws://{self.host}:{self.port} — 브라우저에서 연결하세요")
            self._ready.set()
            await asyncio.Future()

    async def _handler(self, ws):
        self._clients.add(ws)
        try:
            if self._latest is not None:
                try:
                    await ws.send(json.dumps(self._latest))
                except Exception:
                    pass
            await ws.wait_closed()
        finally:
            self._clients.discard(ws)

    def broadcast(self, data: dict):
        """매 step 호출 — thread-safe, non-blocking"""
        self._latest = data
        if self._loop is None or not self._clients:
            return
        payload = json.dumps(data)
        asyncio.run_coroutine_threadsafe(self._broadcast_all(payload), self._loop)

    async def _broadcast_all(self, payload: str):
        dead = set()
        for ws in list(self._clients):
            try:
                await ws.send(payload)
            except Exception:
                dead.add(ws)
        self._clients -= dead

    def broadcast_from_env(self, env, health1: float, health2: float,
                           step: int, done: bool = False, winner=None):
        """env에서 직접 상태를 읽어 브로드캐스트 (runner.py step_hook에서 호출)"""
        try:
            ego = env.agents.get(env.ego_ids[0])
            enm = env.agents.get(env.enm_ids[0])
            if ego is None or enm is None:
                return
            blue = _get_agent_state(ego)
            blue["health"] = round(float(health1), 1)
            red = _get_agent_state(enm)
            red["health"] = round(float(health2), 1)
            self.broadcast({
                "t":      round(step * getattr(env, "time_interval", 0.2), 2),
                "blue":   blue,
                "red":    red,
                "done":   bool(done),
                "winner": winner,
            })
        except Exception:
            pass  # 시각화 실패가 매치를 중단하면 안 됨

    def stop(self):
        if self._loop and self._loop.is_running():
            self._loop.call_soon_threadsafe(self._loop.stop)
        if self._static_server:
            self._static_server.shutdown()
