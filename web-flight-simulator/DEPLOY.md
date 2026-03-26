# CesiumJS Viewer — 실행 및 배포 가이드

## 의존성

### Node.js (프론트엔드)
```
Node.js >= 18
npm install       # package.json 기준 자동 설치
```

주요 패키지 (`package.json`):
| 패키지 | 버전 | 용도 |
|--------|------|------|
| cesium | ^1.137 | WGS84 지구 + 지형 스트리밍 |
| three | ^0.182 | GLB 모델 + 파티클 |
| vite | ^7.3 | 번들러 |
| vite-plugin-cesium | ^1.2 | Cesium 에셋 자동 복사 |

### Python (백엔드 — ai-combat-sdk)
```
pip install -r requirements.txt
```

주요 추가 패키지:
| 패키지 | 용도 |
|--------|------|
| websockets>=12.0 | JSBSim → 브라우저 실시간 브로드캐스트 |

환경변수 (`.env`):
```
VITE_CESIUM_TOKEN=<your_cesium_ion_token>
```

---

## 개발 환경 (2 프로세스)

```bash
# Terminal 1 — 브라우저 뷰어
cd web-flight-simulator
npm run dev
# → http://localhost:5173

# Terminal 2 — JSBSim 매치 + WS 서버
# ai-combat-sdk 루트에서 실행
cd ai-combat-sdk
python scripts/run_match.py --agent1 eagle1 --agent2 simple_fighter --cesium
# → ws://localhost:8765 자동 시작
```

---

## 배포 환경 (1 프로세스)

```bash
# 1. 프론트엔드 빌드 (한 번만)
cd web-flight-simulator
npm run build
# → dist/ 생성

# 2. Python이 WS + 정적파일 동시 서빙
cd ai-combat-sdk
python scripts/run_match.py \
  --agent1 eagle1 --agent2 simple_fighter \
  --cesium \
  --serve-static web-flight-simulator/dist \
  --static-port 8080
# → http://localhost:8080  (뷰어)
# → ws://localhost:8765   (데이터)
```

> `--serve-static` 플래그는 Python 내장 `http.server`로 dist/를 서빙합니다.
> 추가 패키지 불필요 (websockets만 있으면 됨).

---

## 포트 정리

| 포트 | 용도 | 프로세스 |
|------|------|----------|
| 5173 | 브라우저 뷰어 (개발) | npm run dev |
| 8080 | 브라우저 뷰어 (배포) | Python http.server |
| 8765 | JSBSim WebSocket | Python cesium_ws_server |
| 42674 | Tacview 실시간 | Python (선택) |
| 5550/5551 | FlightGear UDP | Python (선택) |
