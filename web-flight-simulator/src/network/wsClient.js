/**
 * JSBSim WebSocket 클라이언트 — 싱글톤
 *
 * Python cesium_ws_server.py 에서 브로드캐스트하는 JSON 수신.
 * WS 연결 여부와 관계없이 기존 단독 비행 모드는 그대로 동작.
 */

let _ws = null;
let _state = null;      // 최신 수신 상태 { t, blue, red, done, winner }
let _connected = false;
let _url = 'ws://localhost:8765';
let _onConnect = null;

export function connectWSClient(url = 'ws://localhost:8765', onConnect = null) {
	_url = url;
	_onConnect = onConnect;
	_tryConnect();
}

function _tryConnect() {
	try {
		_ws = new WebSocket(_url);
	} catch (e) {
		console.warn('[WS] 연결 실패:', e);
		return;
	}

	_ws.onopen = () => {
		_connected = true;
		console.log('[WS] JSBSim 서버 연결됨:', _url);
		if (_onConnect) _onConnect();
	};

	_ws.onmessage = (e) => {
		try {
			_state = JSON.parse(e.data);
		} catch {}
	};

	_ws.onclose = () => {
		_connected = false;
		_ws = null;
		// 서버가 없을 수 있으므로 조용히 재시도 (5초)
		setTimeout(_tryConnect, 5000);
	};

	_ws.onerror = () => {
		// onclose가 이어서 호출되므로 여기선 무시
	};
}

/** WS 연결 중인지 */
export function isWSConnected() {
	return _connected;
}

/** 최신 수신 상태 반환. 미연결 시 null */
export function getWSState() {
	return _state;
}

/** WS 연결 명시적 종료 */
export function disconnectWSClient() {
	if (_ws) {
		_ws.onclose = null; // 재연결 루프 방지
		_ws.close();
		_ws = null;
	}
	_connected = false;
	_state = null;
}
