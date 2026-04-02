import * as THREE from 'three';
import { GLTFLoader } from 'three/examples/jsm/loaders/GLTFLoader.js';
import { initCesium, setCameraToPlane, setOverviewCamera, getViewer, setControlsEnabled, setRenderOptimization } from './world/cesiumWorld';
import { CesiumTrail } from './plane/cesiumTrail';
import { PlanePhysics } from './plane/planePhysics';
import { PlaneController } from './plane/planeController';
import { movePosition } from './utils/math';
import { calculateDistance, reverseGeocode } from './world/regions';
import { HUD } from './ui/hud';
import { WeaponSystem } from './systems/weaponSystem';
import { soundManager } from './utils/soundManager';
import { NPCSystem } from './systems/npcSystem';
import { DialogueSystem } from './systems/dialogueSystem';
import * as Cesium from 'cesium';
import { particles } from './utils/particles';
import { connectWSClient, isWSConnected, getWSState } from './network/wsClient';

const States = {
	MENU: 'MENU',
	PICK_SPAWN: 'PICK_SPAWN',
	TRANSITIONING: 'TRANSITIONING',
	FLYING: 'FLYING',
	PAUSED: 'PAUSED',
	CRASHED: 'CRASHED',
	MATCH_RESULT: 'MATCH_RESULT'
};

let currentState = States.MENU;

let gameSettings = {
	graphicsQuality: 'medium',
	antialiasing: true,
	fogEffects: true,
	mouseSensitivity: 0.2,
	showHud: true,
	showHorizonLines: false,
	soundEnabled: true,
	minimapRange: 10
};

function loadSettings() {
	const saved = localStorage.getItem('flightSimSettings');
	if (saved) {
		try {
			const parsed = JSON.parse(saved);
			gameSettings = { ...gameSettings, ...parsed };
		} catch (e) {
			console.error('Failed to load settings', e);
		}
	}
	applySettings();
	updateSettingsUI();
}

function saveSettings() {
	localStorage.setItem('flightSimSettings', JSON.stringify(gameSettings));
}

function updateSettingsUI() {
	document.getElementById('graphicsQuality').value = gameSettings.graphicsQuality;
	document.getElementById('antialiasing').checked = gameSettings.antialiasing;
	document.getElementById('fogEffects').checked = gameSettings.fogEffects;
	document.getElementById('sensitivitySlider').value = gameSettings.mouseSensitivity;
	document.getElementById('sensitivityValue').textContent = gameSettings.mouseSensitivity;
	document.getElementById('showHud').checked = gameSettings.showHud;
	document.getElementById('showHorizonLines').checked = gameSettings.showHorizonLines;
	document.getElementById('soundEnabled').checked = gameSettings.soundEnabled;
	document.getElementById('minimapRange').value = gameSettings.minimapRange.toString();
}

function applySettings() {


	if (controller) {
		controller.setSensitivity(gameSettings.mouseSensitivity);
	}

	if (hud) {
		hud.setMinimapRange(gameSettings.minimapRange);
		hud.setShowHorizonLines(gameSettings.showHorizonLines);
	}

	if (soundManager && soundManager.listener) {
		soundManager.listener.setMasterVolume(gameSettings.soundEnabled ? 1.0 : 0.0);
	}

	const viewer = getViewer();
	if (viewer) {
		if (gameSettings.graphicsQuality === 'low') {
			viewer.resolutionScale = 0.5;
			viewer.scene.globe.maximumScreenSpaceError = 4;
		} else if (gameSettings.graphicsQuality === 'medium') {
			viewer.resolutionScale = 0.75;
			viewer.scene.globe.maximumScreenSpaceError = 2;
		} else {
			viewer.resolutionScale = 1.0;
			viewer.scene.globe.maximumScreenSpaceError = 1.3;
		}

		viewer.scene.postProcessStages.fxaa.enabled = gameSettings.antialiasing;

		viewer.scene.fog.enabled = gameSettings.fogEffects;
		viewer.scene.atmosphere.show = gameSettings.fogEffects;
	}

	const hudElements = [
		document.getElementById('hud-top-left'),
		document.getElementById('hud-top-right'),
		document.getElementById('hud-speed-box'),
		document.getElementById('hud-alt-box'),
		document.getElementById('coords'),
		document.getElementById('minimap-container')
	];

	hudElements.forEach(el => {
		if (el) {
			el.style.display = gameSettings.showHud ? 'block' : 'none';
		}
	});
}

let state = {
	lon: 127.4890,  // 청주시
	lat: 36.6424,   // 청주시
	alt: 3000,
	heading: 0,
	pitch: 0,
	roll: 0,
	speed: 0,
	throttle: 0,
	score: 0,
	weaponSystem: null
};

async function initUserLocation() {
	try {
		const data = await (await fetch('https://ipapi.co/json/')).json();
		if (data.latitude && data.longitude) {
			state.lat = data.latitude;
			state.lon = data.longitude;
		}
	} catch (e) { }
}

initUserLocation();

let currentRegionName = null;
let lastGeocodeTime = 0;
let lastGeocodePos = { lon: 0, lat: 0 };
const GEOCODE_INTERVAL = 10000;
const GEOCODE_MIN_DIST = 1000;

let lastGPWSWarningTime = 0;
const GPWS_COOLDOWN = 1800;
let gpwsActive = false;
let pauseStartTime = 0;

let scene, camera, renderer;
let planeModel;
let redFollowModel = null;  // follow=red 창 전용 카메라 공간 고정 메시
let cameraMode = 'third'; // 'third' | 'first' | 'overview'
// URL 파라미터 ?follow=red 로 적기 시점 창 전환 (기본 'blue')
const _followTarget = new URLSearchParams(window.location.search).get('follow') ?? 'blue';
let playerTrail = null; // AircraftTrail for blue aircraft
let mixer, clock;
let physics = new PlanePhysics();
let controller = new PlaneController();
let hud = new HUD();
let npcSystem;
let weaponSystem;
let dialogueSystem = new DialogueSystem();

// 페이지 로드 시 WS 선연결 (JSBSim 서버가 실행 중이면 자동 연결, 없으면 무시)
connectWSClient('ws://localhost:8765');

// WS 연결 시 자동 시작 (--cesium 모드: 사용자가 START 버튼을 누를 필요 없음)
const _autoStartInterval = setInterval(() => {
	if (currentState !== States.MENU) {
		clearInterval(_autoStartInterval);
		return;
	}
	if (isWSConnected() && getWSState()?.blue) {
		clearInterval(_autoStartInterval);
		const startBtn = document.getElementById('startBtn');
		if (startBtn && !startBtn.disabled) {
			startBtn.click();
		}
	}
}, 500);

let fps = 0;
let frameCount = 0;
let lastFpsUpdate = 0;

const BASE_PLANE_POS = new THREE.Vector3(0, -0.8, -2.75);
let visualOffset = new THREE.Vector3().copy(BASE_PLANE_POS);
let visualRotation = new THREE.Euler(0, 0, 0);
let boostRoll = 0;
let currentBoostZOffset = 0;
let boostRollDirection = 1;
let lastIsBoosting = false;
let initialCameraView = null;
let lastThrottleLevel = 0;

const mainMenu = document.getElementById('mainMenu');
const pauseMenu = document.getElementById('pauseMenu');
const crashMenu = document.getElementById('crashMenu');
const uiContainer = document.getElementById('uiContainer');
const threeContainer = document.getElementById('threeContainer');
const spawnInstruction = document.getElementById('spawnInstruction');
const confirmSpawnBtn = document.getElementById('confirmSpawnBtn');

let spawnMarker = null;

// 메뉴 지구 회전용
let menuCameraHeading = 0; // 헤딩 각도 (도)
const MENU_CAM_RANGE = 22000000; // 22,000km — 지구가 화면 중앙에 크게
const MENU_CAM_PITCH = -18;     // 약간 위에서 내려다보는 각도

function initMenuCamera() {
	const viewer = getViewer();
	if (!viewer) return;
	// lookAt(ZERO): Earth center 를 항상 화면 정중앙에 고정
	viewer.camera.lookAt(
		Cesium.Cartesian3.ZERO,
		new Cesium.HeadingPitchRange(
			Cesium.Math.toRadians(menuCameraHeading),
			Cesium.Math.toRadians(MENU_CAM_PITCH),
			MENU_CAM_RANGE
		)
	);
}

function updateMenuCamera(dt) {
	if (!loadingStatus.globe) return;
	const viewer = getViewer();
	if (!viewer) return;
	menuCameraHeading += dt * 2.5; // 약 144초에 1바퀴
	if (menuCameraHeading >= 360) menuCameraHeading -= 360;
	viewer.camera.lookAt(
		Cesium.Cartesian3.ZERO,
		new Cesium.HeadingPitchRange(
			Cesium.Math.toRadians(menuCameraHeading),
			Cesium.Math.toRadians(MENU_CAM_PITCH),
			MENU_CAM_RANGE
		)
	);
}

function playStartBurst(callback) {
	const canvas = document.createElement('canvas');
	canvas.style.cssText = 'position:fixed;inset:0;z-index:500;pointer-events:none;width:100%;height:100%;';
	canvas.width = window.innerWidth;
	canvas.height = window.innerHeight;
	document.body.appendChild(canvas);
	const ctx = canvas.getContext('2d');
	const cx = canvas.width / 2;
	const cy = canvas.height / 2;

	// 지구 반지름 추정 (화면 높이의 약 28%)
	const earthScreenR = Math.min(canvas.width, canvas.height) * 0.28;

	// 파티클: 지구 표면/내부에서 시작해 바깥으로 폭발
	const particles = Array.from({ length: 480 }, () => {
		const angle = Math.random() * Math.PI * 2;
		const startR = Math.random() * earthScreenR; // 지구 내부 랜덤 위치
		return {
			sx: cx + Math.cos(angle) * startR,
			sy: cy + Math.sin(angle) * startR,
			angle,
			speed: Math.random() * 7 + 2,
			size: Math.random() * 2.4 + 0.3,
			hue: Math.random() < 0.55 ? 188 + Math.random() * 30 : (Math.random() < 0.6 ? 210 : 310 + Math.random() * 30),
			delay: Math.random() * 0.35,
			twinkle: Math.random(),
		};
	});

	const viewer = getViewer();
	const startRange = MENU_CAM_RANGE;
	const endRange   = 380000000;
	let t0 = null;
	const dur = 1800;

	function frame(ts) {
		if (!t0) t0 = ts;
		const t = Math.min((ts - t0) / dur, 1);
		const eZoom  = 1 - Math.pow(1 - t, 2.5);        // 줌아웃 easing
		const eFlash = Math.pow(Math.sin(t * Math.PI), 1.5); // 플래시 (0→peak→0)

		// 지구 줌아웃 (lookAt 유지하며 range만 늘림)
		if (viewer) {
			const range = startRange + (endRange - startRange) * eZoom;
			viewer.camera.lookAt(
				Cesium.Cartesian3.ZERO,
				new Cesium.HeadingPitchRange(
					Cesium.Math.toRadians(menuCameraHeading),
					Cesium.Math.toRadians(MENU_CAM_PITCH),
					range
				)
			);
		}

		// 배경 점진 페이드
		ctx.fillStyle = `rgba(0,0,8,${Math.min(eZoom * 1.4, 0.95)})`;
		ctx.fillRect(0, 0, canvas.width, canvas.height);

		// 초기 폭발 플래시 (하얀 원형 글로우)
		if (eFlash > 0.01 && t < 0.35) {
			const flashR = earthScreenR * (1 + t * 3);
			const g = ctx.createRadialGradient(cx, cy, 0, cx, cy, flashR);
			g.addColorStop(0, `rgba(180,240,255,${eFlash * 0.35})`);
			g.addColorStop(0.4, `rgba(0,229,255,${eFlash * 0.15})`);
			g.addColorStop(1, 'rgba(0,0,0,0)');
			ctx.beginPath();
			ctx.fillStyle = g;
			ctx.arc(cx, cy, flashR, 0, Math.PI * 2);
			ctx.fill();
		}

		// 파티클 렌더
		const maxR = Math.hypot(cx, cy) * 1.15;
		particles.forEach(p => {
			const pt = Math.max(0, (t - p.delay) / (1 - p.delay));
			if (pt <= 0) return;
			const dist = pt * maxR * p.speed / 5;
			const x = p.sx + Math.cos(p.angle) * dist;
			const y = p.sy + Math.sin(p.angle) * dist;
			const alpha = Math.pow(1 - pt, 1.2) * 0.95;
			if (alpha <= 0.01) return;

			// 트레일
			const tailLen = p.speed * 18 * pt;
			const tx = p.sx + Math.cos(p.angle) * Math.max(0, dist - tailLen);
			const ty = p.sy + Math.sin(p.angle) * Math.max(0, dist - tailLen);
			const grad = ctx.createLinearGradient(tx, ty, x, y);
			grad.addColorStop(0, `hsla(${p.hue},100%,70%,0)`);
			grad.addColorStop(1, `hsla(${p.hue},100%,85%,${alpha * 0.55})`);
			ctx.beginPath();
			ctx.strokeStyle = grad;
			ctx.lineWidth = p.size * 0.5;
			ctx.moveTo(tx, ty);
			ctx.lineTo(x, y);
			ctx.stroke();

			// 별 점 (약간 반짝임)
			const twinkleA = alpha * (0.7 + p.twinkle * 0.3 * Math.sin(t * 40 + p.twinkle * 6));
			ctx.beginPath();
			ctx.fillStyle = `hsla(${p.hue},100%,92%,${twinkleA})`;
			ctx.arc(x, y, p.size * (1 - pt * 0.25), 0, Math.PI * 2);
			ctx.fill();
		});

		if (t < 1) {
			requestAnimationFrame(frame);
		} else {
			canvas.remove();
			// lookAt 제약 해제 후 콜백
			const v = getViewer();
			if (v) v.camera.lookAtTransform(Cesium.Matrix4.IDENTITY);
			callback();
		}
	}
	requestAnimationFrame(frame);
}

const startBtn = document.getElementById('startBtn');

const loadingIndicator = document.getElementById('loadingIndicator');
const loadingText = document.getElementById('loadingText');

const loadingStatus = {
	audio: false,
	model: false,
	cesium: false,
	globe: false,
	failed: false
};

function updateLoadingUI() {
	if (!loadingIndicator || !loadingText || !startBtn) return;

	if (currentState === States.FLYING || currentState === States.TRANSITIONING) {
		loadingIndicator.classList.add('hidden');
		return;
	}

	let msg = "";
	const isAllLoaded = loadingStatus.audio && loadingStatus.model && loadingStatus.cesium && loadingStatus.globe;

	if (loadingStatus.failed) {
		msg = "Loading Failed. Please Refresh.";
	} else if (!isAllLoaded) {
		if (!loadingStatus.audio) msg = "Loading Audio...";
		else if (!loadingStatus.model) msg = "Loading Aircraft Model...";
		else if (!loadingStatus.cesium) msg = "Loading Satellite Imagery...";
		else if (!loadingStatus.globe) msg = "Loading Globe Surface...";
	}

	if (msg) {
		loadingText.textContent = msg;
		startBtn.disabled = true;
		startBtn.style.pointerEvents = "none";
		loadingIndicator.classList.remove('hidden');

		if (loadingStatus.failed) {
			loadingText.style.color = "#f00";
			const spinner = loadingIndicator.querySelector('.spinner');
			if (spinner) {
				spinner.style.borderColor = "rgba(255, 0, 0, 0.3)";
				spinner.style.borderTopColor = "#f00";
			}
		}
	} else {
		loadingIndicator.classList.add('hidden');
		startBtn.disabled = false;
		startBtn.style.pointerEvents = "auto";
	}
}

async function initSounds() {
	soundManager.init(camera);

	await Promise.all([
		soundManager.loadSound('boost', '/assets/sounds/boost.mp3', false, 0.35),
		soundManager.loadSound('throttle', '/assets/sounds/throttle.mp3', false, 0.4),
		soundManager.loadSound('explode', '/assets/sounds/explode.mp3', false, 0.75),
		soundManager.loadSound('explosion-1', '/assets/sounds/explosion-1.mp3', false, 0.8),
		soundManager.loadSound('explosion-2', '/assets/sounds/explosion-2.mp3', false, 0.8),
		soundManager.loadSound('explosion-3', '/assets/sounds/explosion-3.mp3', false, 0.8),
		soundManager.loadSound('ambient-crash', '/assets/sounds/ambient.mp3', true, 0.5),
		soundManager.loadSound('weapon-warning', '/assets/sounds/weapon-warning-1.mp3', false, 1.0),
		soundManager.loadSound('jet-engine', '/assets/sounds/jet-engine.mp3', true, 0.5),
		soundManager.loadSound('spawn', '/assets/sounds/spawn.mp3', false, 0.5),
		soundManager.loadSound('roll', '/assets/sounds/roll.mp3', true, 0.75),
		soundManager.loadSound('pitch', '/assets/sounds/pitch.mp3', true, 0.75),
		soundManager.loadSound('button-click', '/assets/sounds/button-click.mp3', false, 1.0),
		soundManager.loadSound('weapon-switch', '/assets/sounds/weapon-switch.mp3', false, 0.75),
		soundManager.loadSound('button-hover', '/assets/sounds/button-hover.mp3', false, 0.25),
		soundManager.loadSound('zoom-in', '/assets/sounds/zoom-in.mp3', false, 0.5),
		soundManager.loadSound('missile-fire', '/assets/sounds/missile-firing-1.mp3', false, 0.75),
		soundManager.loadSound('m61-firing', '/assets/sounds/m61-firing.mp3', true, 0.75),
		soundManager.loadSound('rwr-tws', '/assets/sounds/rwr-tws.mp3', true, 0.2),
		soundManager.loadSound('rwr-lock', '/assets/sounds/rwr-lock.mp3', false, 0.2),
		soundManager.loadSound('wind', '/assets/sounds/wind.mp3', true, 0.25),
		soundManager.loadSound('terrain-pull-up', '/assets/sounds/terrain-pull-up.mp3', false, 0.9),
		soundManager.loadSound('warning', '/assets/sounds/warning.mp3', false, 0.6),
		soundManager.loadSound('glitch-1', '/assets/sounds/glitch-transition-1.mp3', false, 0.25),
		soundManager.loadSound('glitch-2', '/assets/sounds/glitch-transition-2.mp3', false, 0.25),
		soundManager.loadSound('glitch-3', '/assets/sounds/glitch-transition-3.mp3', false, 0.25),
		soundManager.loadSound('glitch-4', '/assets/sounds/glitch-transition-4.mp3', false, 0.25)
	]);

	loadingStatus.audio = true;
	updateLoadingUI();
	setupButtonSounds();
}

function stopAllFlyingSounds(fadeOut = 0.5) {
	soundManager.stopAll(fadeOut);
}

function pauseGameplaySounds() {
	pauseStartTime = Date.now();
	soundManager.pauseAll();
}

function resumeGameplaySounds() {
	const pauseDuration = Date.now() - pauseStartTime;
	if (lastGPWSWarningTime > 0) {
		lastGPWSWarningTime += pauseDuration;
	}
	soundManager.resumeAll();
}

function setupButtonSounds() {
	document.addEventListener('mouseover', (e) => {
		const target = e.target.closest('button, .menu-btn, .clickable-ui');
		if (target && !target._hovered) {
			soundManager.play('button-hover');
			target._hovered = true;
			target.addEventListener('mouseleave', () => { target._hovered = false; }, { once: true });
		}
	}, true);

	document.addEventListener('click', (e) => {
		const target = e.target.closest('button, .menu-btn, .clickable-ui, #search-toggle-btn');
		if (target) {
			soundManager.play('button-click');
		}
	}, true);
}

function initThree() {
	clock = new THREE.Clock();
	scene = new THREE.Scene();
	camera = new THREE.PerspectiveCamera(75, window.innerWidth / window.innerHeight, 0.1, 100000);

	renderer = new THREE.WebGLRenderer({ alpha: true, antialias: true });
	renderer.setSize(window.innerWidth, window.innerHeight);
	renderer.setPixelRatio(window.devicePixelRatio);
	renderer.setClearColor(0x000000, 0);
	threeContainer.appendChild(renderer.domElement);

	threeContainer.classList.add('hidden');

	const ambientLight = new THREE.AmbientLight(0xffffff, 1.0);
	scene.add(ambientLight);
	const directionalLight = new THREE.DirectionalLight(0xffffff, 1.0);
	directionalLight.position.set(5, 10, 5);
	scene.add(directionalLight);

	ambientLight.layers.enable(1);
	directionalLight.layers.enable(1);

	try { particles.init(scene, getViewer()); } catch (e) { }

	initSounds().catch(err => console.error('Failed to init sounds', err));

	const loader = new GLTFLoader();
	loader.load('/assets/models/f-16.glb', (gltf) => {
		const mesh = gltf.scene;

		planeModel = new THREE.Group();
		planeModel.add(mesh);
		scene.add(planeModel);

		planeModel.layers.set(1);
		planeModel.traverse(child => {
			child.layers.set(1);
		});

		const box = new THREE.Box3().setFromObject(mesh);
		const center = box.getCenter(new THREE.Vector3());
		mesh.position.sub(center);

		// 모델 크기에 관계없이 화면에 적절한 크기로 자동 스케일
		const size = box.getSize(new THREE.Vector3());
		const maxDim = Math.max(size.x, size.y, size.z);
		const autoScale = 4.6 / maxDim;

		planeModel.position.copy(BASE_PLANE_POS);
		planeModel.scale.set(autoScale, autoScale, autoScale);

		// follow=red 창 전용 카메라 공간 고정 모델 (적기 시점)
		if (_followTarget === 'red') {
			const redMesh = mesh.clone(true);
			redFollowModel = new THREE.Group();
			redFollowModel.add(redMesh);
			redFollowModel.scale.set(autoScale, autoScale, autoScale);
			redFollowModel.traverse(child => {
				child.layers.set(1);
				if (child.isMesh && child.material) {
					child.material = child.material.clone();
					child.material.color = new THREE.Color(1.0, 0.3, 0.3);
					child.material.emissive = new THREE.Color(0.3, 0.0, 0.0);
				}
			});
			redFollowModel.position.copy(BASE_PLANE_POS);
			redFollowModel.visible = false;
			scene.add(redFollowModel);
		}

		weaponSystem = new WeaponSystem(getViewer(), scene, planeModel);
		weaponSystem.onKill = (npc) => {
			state.score += 1000;
			try { soundManager.play('glitch-random'); } catch (e) { }
			if (hud) {
				hud.showKillNotification(npc.name, 1000);
			}
		};

		planeModel.traverse(child => {
			child.layers.set(1);
		});

		mixer = new THREE.AnimationMixer(mesh);
		const clip = THREE.AnimationClip.findByName(gltf.animations, 'flight_mode');
		if (clip) {
			const action = mixer.clipAction(clip);
			action.setLoop(THREE.LoopOnce);
			action.clampWhenFinished = true;
			action.play();
		}

		loadingStatus.model = true;
		updateLoadingUI();
	}, undefined, (error) => {
		console.error('Error loading model:', error);
	});
}

// ── 도그파이트 HUD ──
const _dfHud        = document.getElementById('dogfight-hud');
const _dfBlueFill   = document.getElementById('df-blue-fill');
const _dfRedFill    = document.getElementById('df-red-fill');
const _dfBlueHp     = document.getElementById('df-blue-hp');
const _dfRedHp      = document.getElementById('df-red-hp');
const _dfTimer      = document.getElementById('df-timer');
const _matchResult  = document.getElementById('match-result');
const _matchTitle   = document.getElementById('match-result-title');
const _matchWinner  = document.getElementById('match-result-winner');
let _dfMatchTime    = 0;
let _matchDone      = false;

function _updateDogfightHUD(wsState) {
	if (!wsState) return;

	// WS 연결 중이고 FLYING 상태면 HUD 항상 표시 (재연결 후 복구)
	if (currentState === States.FLYING && _dfHud && _dfHud.classList.contains('hidden') && !_matchDone) {
		_dfHud.classList.remove('hidden');
	}

	const bHp = Math.max(0, Math.round(wsState.blue?.health ?? 100));
	const rHp = Math.max(0, Math.round(wsState.red?.health  ?? 100));
	if (_dfBlueFill) _dfBlueFill.style.width = bHp + '%';
	if (_dfRedFill)  _dfRedFill.style.width  = rHp + '%';
	if (_dfBlueHp)   _dfBlueHp.textContent   = bHp;
	if (_dfRedHp)    _dfRedHp.textContent     = rHp;

	_dfMatchTime += 1/60;
	const mm = String(Math.floor(_dfMatchTime / 60)).padStart(2, '0');
	const ss = String(Math.floor(_dfMatchTime % 60)).padStart(2, '0');
	if (_dfTimer) _dfTimer.textContent = mm + ':' + ss;

	if (wsState.done && !_matchDone) {
		_matchDone = true;
		_showMatchResult(wsState.winner);
	}
}

function _showMatchResult(winner) {
	currentState = States.MATCH_RESULT;
	uiContainer.classList.add('hidden');
	_dfHud.classList.add('hidden');

	let winnerText = '';
	if (winner === 'tree1' || winner === 'blue') {
		winnerText = 'BLUE WINS';
		_matchTitle.style.color = '#00c8ff';
	} else if (winner === 'tree2' || winner === 'red') {
		winnerText = 'RED WINS';
		_matchTitle.style.color = '#ff3030';
	} else {
		winnerText = 'DRAW';
		_matchTitle.style.color = '#ffcc00';
	}
	_matchWinner.textContent = winnerText;
	_matchResult.classList.remove('hidden');
}

document.getElementById('match-restart-btn').onclick = () => {
	_matchResult.classList.add('hidden');
	_matchDone = false;
	_dfMatchTime = 0;
	location.reload();
};

function update(dt) {
	if (currentState !== States.FLYING) return;

	// 블록 스코프 버그 방지: if/else 밖에서 선언
	let prevSpeed = state.speed;
	let physicsResult = { isBoosting: false, boostDuration: 1, boostTimeRemaining: 0, boostRotations: 0 };
	let input = { isDragging: false, roll: 0, pitch: 0, yaw: 0, cameraPitch: 0, cameraYaw: 0 };

	const wsState = getWSState();
	if (isWSConnected() && wsState && wsState.blue) {
		// ── JSBSim 외부 제어 모드 ──
		input = controller.update();  // 카메라 오빗 입력은 WS 모드에서도 필요
		const b = wsState.blue;
		// Blue 상태를 기본으로 적용
		state.lon      = b.lon;
		state.lat      = b.lat;
		state.alt      = b.alt_m;
		state.heading  = b.heading;
		state.pitch    = b.pitch;
		state.roll     = b.roll;
		state.speed    = (b.speed_kts ?? 0) * 0.514444;  // kts → m/s
		state.throttle = b.throttle ?? state.throttle;
		state.isBoosting = false;

		// follow=red 창: Red 상태를 ego state로 덮어씌움 (대칭 아키텍처)
		if (_followTarget === 'red' && wsState.red) {
			const r = wsState.red;
			state.lon      = r.lon;
			state.lat      = r.lat;
			state.alt      = r.alt_m;
			state.heading  = r.heading;
			state.pitch    = r.pitch;
			state.roll     = r.roll;
			state.speed    = (r.speed_kts ?? 0) * 0.514444;
			state.throttle = r.throttle ?? state.throttle;
		}

		// physics quaternion 동기화 — ego 상태 기준 (카메라 방향 계산에 사용됨)
		const euler = new THREE.Euler(
			THREE.MathUtils.degToRad(state.pitch),
			THREE.MathUtils.degToRad(state.heading),
			THREE.MathUtils.degToRad(state.roll),
			'YXZ'
		);
		physics.quaternion.setFromEuler(euler);
		physics.heading = state.heading;
		physics.pitch   = state.pitch;
		physics.roll    = state.roll;
		physics.speed   = state.speed;

		// NPC 시스템: 상대 기체를 Cesium 엔티티로 등록 (대칭 아키텍처)
		if (npcSystem) {
			if (_followTarget === 'red') {
				// Red가 ego → Blue를 NPC로 등록
				npcSystem.updateExternal('BLUE_JSBSIM', b.lon, b.lat, b.alt_m,
					b.heading, b.pitch, b.roll);
				// RED_JSBSIM NPC가 있으면 제거 (ego는 카메라 공간 모델로 표시)
				const redNpcToRemove = npcSystem.npcs.find(n => n.id === 'RED_JSBSIM');
				if (redNpcToRemove) redNpcToRemove.destroyed = true;
			} else {
				// Blue가 ego (기본) → Red를 NPC로 등록
				if (wsState.red) {
					const r = wsState.red;
					npcSystem.updateExternal('RED_JSBSIM', r.lon, r.lat, r.alt_m,
						r.heading, r.pitch, r.roll);
				}
				// BLUE_JSBSIM NPC가 있으면 제거
				const blueJsbNpc = npcSystem.npcs.find(n => n.id === 'BLUE_JSBSIM');
				if (blueJsbNpc) blueJsbNpc.destroyed = true;
			}
		}

		_updateDogfightHUD(wsState);

		state.yaw = 0;
		state.weaponSystem = weaponSystem;
		state.npcs = npcSystem ? npcSystem.npcs : [];

		// WEZ 자동 기총 이펙트: 상대방 HP 감소 = 아군이 사격 중 (대칭 아키텍처)
		if (weaponSystem) {
			if (_followTarget === 'red') {
				// ?follow=red 창: Red 기체가 사격 → Blue HP 감소
				const curBlueHp = wsState.blue?.health ?? 100;
				if (wsState._prevBlueHp !== undefined && curBlueHp < wsState._prevBlueHp) {
					weaponSystem.fire(state);  // state = Red 위치
				}
				wsState._prevBlueHp = curBlueHp;
			} else if (wsState.red) {
				// ?follow=blue 창: Blue 기체가 사격 → Red HP 감소
				const curRedHp = wsState.red.health ?? 100;
				if (wsState._prevRedHp !== undefined && curRedHp < wsState._prevRedHp) {
					weaponSystem.fire(state);  // state = Blue 위치
				}
				wsState._prevRedHp = curRedHp;
			}
		}

		// WS 모드에서도 플레이어 무기 입력 처리 (시각적 효과 + 브라우저 피격 판정)
		if (weaponSystem) {
			if (input.weaponIndex !== -1) weaponSystem.selectWeapon(input.weaponIndex);
			if (input.toggleWeapon)       weaponSystem.toggleWeapon();
			if (input.fire)               weaponSystem.fire(state);
			if (input.fireFlare)          weaponSystem.fireFlare(state);
			weaponSystem.update(dt, state, input);
		}
	} else {
		// ── 기존 내부 물리 모드 (WS 미연결) ──
		input = controller.update();
		physicsResult = physics.update(input, dt);

		state.speed = physicsResult.speed;
		state.pitch = physicsResult.pitch;
		state.roll = physicsResult.roll;
		state.heading = physicsResult.heading;
		state.throttle = input.throttle;
		state.yaw = input.yaw;
		state.isBoosting = physicsResult.isBoosting;
		state.weaponSystem = weaponSystem;
		state.npcs = npcSystem ? npcSystem.npcs : [];

		if (weaponSystem) {
			if (input.weaponIndex !== -1) {
				weaponSystem.selectWeapon(input.weaponIndex);
			}
			if (input.toggleWeapon) {
				weaponSystem.toggleWeapon();
			}
			if (input.fire) {
				weaponSystem.fire(state);
			}
			if (input.fireFlare) {
				weaponSystem.fireFlare(state);
			}
			weaponSystem.update(dt, state, input);
		}

		const newPos = movePosition(state.lon, state.lat, state.alt, state.heading, state.pitch, state.speed * dt);
		state.lon = newPos.lon;
		state.lat = newPos.lat;
		state.alt = newPos.alt;
	}

	const nowTime = Date.now();
	const distFromLast = calculateDistance(state.lon, state.lat, lastGeocodePos.lon, lastGeocodePos.lat);

	if (nowTime - lastGeocodeTime > GEOCODE_INTERVAL || distFromLast > GEOCODE_MIN_DIST) {
		lastGeocodeTime = nowTime;
		lastGeocodePos = { lon: state.lon, lat: state.lat };

		reverseGeocode(state.lon, state.lat).then(name => {
			if (name && name !== currentRegionName) {
				currentRegionName = name;
				hud.showRegion(name);
			}
		});
	}

	checkCrash();
	checkGPWS();

	if (soundManager.isPlaying('jet-engine')) {
		const minSpeed = 100;
		const maxSpeed = 1000;
		const minVol = 0.5;
		const maxVol = 0.6;
		const speedFactor = Math.max(0, Math.min(1.0, (state.speed - minSpeed) / (maxSpeed - minSpeed)));
		const engineVol = minVol + speedFactor * (maxVol - minVol);
		soundManager.setVolume('jet-engine', engineVol);
	}

	if (state.isBoosting && !lastIsBoosting) {
		soundManager.play('boost');
	}

	if (state.throttle > lastThrottleLevel + 0.01) {
		if (!soundManager.isPlaying('throttle')) {
			soundManager.play('throttle');
		}
	}
	lastThrottleLevel = state.throttle;

	if (Math.abs(input.pitch) > 0.5) {
		if (!soundManager.isPlaying('pitch')) {
			soundManager.play('pitch', 0.1);
		}
	} else {
		if (soundManager.isPlaying('pitch')) {
			soundManager.stop('pitch', 0.1);
		}
	}

	if (Math.abs(input.roll) > 0.5 || Math.abs(input.yaw) > 0.5) {
		if (!soundManager.isPlaying('roll')) {
			soundManager.play('roll', 0.1);
		}
	} else {
		if (soundManager.isPlaying('roll')) {
			soundManager.stop('roll', 0.1);
		}
	}

	const planeHPR = new Cesium.HeadingPitchRoll(
		Cesium.Math.toRadians(state.heading),
		Cesium.Math.toRadians(state.pitch),
		Cesium.Math.toRadians(state.roll)
	);
	const planeQuat = Cesium.Quaternion.fromHeadingPitchRoll(planeHPR);

	const orbitHPR = new Cesium.HeadingPitchRoll(
		Cesium.Math.toRadians(input.cameraYaw),
		Cesium.Math.toRadians(-input.cameraPitch),
		0
	);
	const orbitQuat = Cesium.Quaternion.fromHeadingPitchRoll(orbitHPR);

	const finalQuat = Cesium.Quaternion.multiply(planeQuat, orbitQuat, new Cesium.Quaternion());
	const finalHPR = Cesium.HeadingPitchRoll.fromQuaternion(finalQuat);
	// 실제 카메라에 적용되는 롤을 HUD에 전달 (state.roll과 짐발락 때문에 다를 수 있음)
	state.cameraRoll = Cesium.Math.toDegrees(finalHPR.roll);

	if (cameraMode !== 'overview') {
		// state = ego 기체 (follow=blue → Blue, follow=red → Red)
		// finalHPR = ego HPR + 마우스 오빗 → 양쪽 창 모두 동일 로직
		setCameraToPlane(
			state.lon, state.lat, state.alt,
			Cesium.Math.toDegrees(finalHPR.heading),
			Cesium.Math.toDegrees(finalHPR.pitch),
			Cesium.Math.toDegrees(finalHPR.roll)
		);
	}

	if (npcSystem) {
		npcSystem.update(dt, state);
	}

	// 오버뷰 카메라: 양측 기체 중점에 카메라 배치 + blue 기체를 NPC로 등록
	if (cameraMode === 'overview') {
		const redNpc = npcSystem?.npcs.find(n => n.isExternal) ?? npcSystem?.npcs.find(n => n.id !== 'BLUE_PLAYER');
		const redPos = redNpc ? { lon: redNpc.lon, lat: redNpc.lat, alt: redNpc.alt } : null;
		if (redPos) {
			setOverviewCamera({ lon: state.lon, lat: state.lat, alt: state.alt }, redPos);
		}
		// 오버뷰 모드에서 아군기를 월드 공간 NPC로 등록 (3D 모델 가시화)
		if (npcSystem) {
			npcSystem.updateExternal('BLUE_PLAYER',
				state.lon, state.lat, state.alt,
				state.heading, state.pitch, state.roll);
		}
	} else if (npcSystem) {
		// 오버뷰 종료 시 BLUE_PLAYER NPC 제거
		const blueNpc = npcSystem.npcs.find(n => n.id === 'BLUE_PLAYER');
		if (blueNpc) blueNpc.destroyed = true;
	}

	// 플레이어 경로 trail 업데이트
	if (playerTrail) {
		playerTrail.update(state.lon, state.lat, state.alt);
	}

	hud.update(state, currentState === States.FLYING ? (npcSystem ? npcSystem.npcs : []) : []);

	if (planeModel) {
		const accel = (state.speed - prevSpeed) / dt;
		const accelInertia = input.isDragging ? 0 : Math.max(-0.5, Math.min(1.5, accel * 0.001));
		let targetZ = BASE_PLANE_POS.z - accelInertia;

		let boostZOffset = 0;
		if (physicsResult.isBoosting) {
			if (!lastIsBoosting) {
				boostRollDirection = Math.random() > 0.5 ? 1 : -1;
			}

			const T = physicsResult.boostDuration;
			const p = Math.max(0, Math.min(1.0, 1.0 - (physicsResult.boostTimeRemaining / T)));

			const totalRotationRad = Math.PI * 2 * physicsResult.boostRotations * boostRollDirection;

			if (p < 0.2) {
				const localP = p / 0.2;
				boostZOffset = -(localP * localP) * 1.5;
				boostRoll = 0;
			}
			else if (p < 0.8) {
				const localP = (p - 0.2) / 0.6;
				boostZOffset = -1.5;
				const easedP = localP < 0.5
					? 4 * localP * localP * localP
					: 1 - Math.pow(-2 * localP + 2, 3) / 2;
				boostRoll = easedP * (Math.PI * 2 * physicsResult.boostRotations) * boostRollDirection;
			}
			else {
				const localP = (p - 0.8) / 0.2;
				const easedReturn = localP * localP * (3 - 2 * localP);
				boostZOffset = -1.5 + (easedReturn * 0.7);
				boostRoll = (Math.PI * 2 * physicsResult.boostRotations) * boostRollDirection;
			}
		} else {
			boostRoll = 0;
			boostZOffset = 0;
		}
		lastIsBoosting = physicsResult.isBoosting;

		const zLerp = physicsResult.isBoosting ? 10.0 * dt : 2.0 * dt;
		currentBoostZOffset += (boostZOffset - currentBoostZOffset) * zLerp;
		targetZ += currentBoostZOffset;


		const time = performance.now() * 0.001;
		const idleX = Math.sin(time * 0.8) * 0.035;
		const idleY = Math.cos(time * 0.6) * 0.025;
		const idleRotX = Math.sin(time * 0.5) * 0.015;
		const idleRotY = Math.cos(time * 0.4) * 0.015;
		const idleRotZ = Math.sin(time * 0.7) * 0.025;

		const targetX = input.isDragging ? BASE_PLANE_POS.x : BASE_PLANE_POS.x - (input.roll * 0.6) - (input.yaw * 0.12) + idleX;
		const targetY = input.isDragging ? BASE_PLANE_POS.y : BASE_PLANE_POS.y - (input.pitch * 0.1) + idleY;

		// WS 모드: JSBSim 실제 롤/피치로 기체 모델 자세 표시 (NPC 엔티티와 동일 데이터)
		// 일반 모드: 컨트롤러 입력 기반 (기존 동작)
		let targetRotZ, targetRotX, targetRotY;
		if (input.isDragging) {
			targetRotZ = 0;
			targetRotX = 0;
			targetRotY = 0;
		} else if (isWSConnected()) {
			targetRotZ = THREE.MathUtils.degToRad(-state.roll) + idleRotZ;
			targetRotX = THREE.MathUtils.degToRad(state.pitch * 0.5) + idleRotX;
			targetRotY = idleRotY;
		} else {
			targetRotZ = THREE.MathUtils.degToRad(-input.roll * 15) + idleRotZ;
			targetRotX = THREE.MathUtils.degToRad(input.pitch * 10) + idleRotX;
			targetRotY = THREE.MathUtils.degToRad(-input.yaw * 4) + idleRotY;
		}

		const lerpFactor = physicsResult.isBoosting ? 3.0 * dt : 5.0 * dt;
		visualOffset.x += (targetX - visualOffset.x) * lerpFactor;
		visualOffset.y += (targetY - visualOffset.y) * lerpFactor;
		visualOffset.z += (targetZ - visualOffset.z) * lerpFactor;

		visualRotation.z += (targetRotZ - visualRotation.z) * lerpFactor;
		visualRotation.x += (targetRotX - visualRotation.x) * lerpFactor;
		visualRotation.y += (targetRotY - visualRotation.y) * lerpFactor;

		const orbitQ = new THREE.Quaternion().setFromEuler(
			new THREE.Euler(
				THREE.MathUtils.degToRad(-input.cameraPitch),
				THREE.MathUtils.degToRad(-input.cameraYaw),
				0,
				'YXZ'
			)
		);

		planeModel.position.copy(visualOffset);

		const flightLagQ = new THREE.Quaternion().setFromEuler(
			new THREE.Euler(visualRotation.x, visualRotation.y, visualRotation.z + boostRoll)
		);

		const combinedQ = orbitQ.clone().invert().multiply(flightLagQ);
		planeModel.quaternion.copy(combinedQ);

		// follow=red 창: redFollowModel을 동일 카메라 공간 고정 로직으로 갱신
		if (redFollowModel) {
			if (_followTarget === 'red' && isWSConnected()) {
				redFollowModel.visible = cameraMode === 'third';
				redFollowModel.position.copy(visualOffset);
				redFollowModel.quaternion.copy(combinedQ);
			} else {
				redFollowModel.visible = false;
			}
		}

	}
}

function checkGPWS() {
	if (currentState !== States.FLYING) {
		hud.setPullUpWarning(false);
		return;
	}

	const viewer = getViewer();
	if (!viewer) return;

	const cartographic = Cesium.Cartographic.fromDegrees(state.lon, state.lat);
	const terrainHeight = viewer.scene.globe.getHeight(cartographic);

	if (terrainHeight === undefined) return;

	const agl = state.alt - terrainHeight;
	const pitchRad = Cesium.Math.toRadians(state.pitch);
	const verticalSpeed = state.speed * Math.sin(pitchRad);

	let showWarning = false;

	if (state.pitch < -1) {
		if (agl < 450) {
			if (agl < 150) {
				showWarning = true;
			}

			if (verticalSpeed < -20) {
				showWarning = true;
			}
		}
	}

	hud.setPullUpWarning(showWarning);

	if (showWarning) {
		const now = Date.now();
		if (!gpwsActive || (now - lastGPWSWarningTime > GPWS_COOLDOWN && !soundManager.isPlaying('terrain-pull-up'))) {
			soundManager.play('terrain-pull-up');
			lastGPWSWarningTime = now;
		}
		gpwsActive = true;
	} else {
		if (gpwsActive) {
			soundManager.stop('terrain-pull-up', 0.1);
			gpwsActive = false;
		}
	}
}

let lastCrashCheck = 0;
let flightStartTime = 0;

function checkCrash() {
	if (currentState !== States.FLYING) return;

	const now = Date.now();
	if (now - lastCrashCheck < 100) return;
	lastCrashCheck = now;

	if (now - flightStartTime < 3000) return;

	const viewer = getViewer();
	if (!viewer) return;

	const cartographic = Cesium.Cartographic.fromDegrees(state.lon, state.lat);
	const terrainHeight = viewer.scene.globe.getHeight(cartographic);

	if (terrainHeight !== undefined && state.alt <= terrainHeight + 5) {
		currentState = States.CRASHED;
		if (dialogueSystem) dialogueSystem.stop();
		uiContainer.classList.add('hidden');
		const weaponsHud = document.getElementById('weapons-hud');
		if (weaponsHud) weaponsHud.classList.add('hidden');
		threeContainer.classList.add('hidden');
		crashMenu.classList.remove('hidden');
		hud.update(state, []);

		stopAllFlyingSounds(0.1);
		setTimeout(() => {
			soundManager.play('explode');
			soundManager.play('ambient-crash');
		}, 50);
	}
}

function animate() {
	requestAnimationFrame(animate);

	const dt = clock ? clock.getDelta() : 0.016;
	const now = performance.now();

	frameCount++;
	if (now - lastFpsUpdate >= 1000) {
		fps = (frameCount * 1000) / (now - lastFpsUpdate);
		frameCount = 0;
		lastFpsUpdate = now;
		hud.updateFPS(fps);

		const menuTimeElem = document.getElementById('menu-time');
		if (menuTimeElem) {
			menuTimeElem.textContent = new Date().toISOString().split('.')[0] + 'Z';
		}
	}

	if (currentState === States.FLYING || currentState === States.PAUSED || currentState === States.TRANSITIONING) {
		const viewer = getViewer();

		renderer.autoClear = false;
		renderer.clear();

		if (viewer && viewer.camera && viewer.camera.frustum.fovy) {
			const targetFov = Cesium.Math.toDegrees(viewer.camera.frustum.fovy);
			camera.fov = targetFov;
			camera.aspect = window.innerWidth / window.innerHeight;
			camera.updateProjectionMatrix();
		}

		camera.layers.set(0);

		if (currentState === States.FLYING) {
			update(dt);
		} else if (currentState === States.PAUSED) {
			hud.updatePauseMenu(state, currentRegionName, npcSystem ? npcSystem.npcs : []);
		}

		if (mixer) mixer.update(dt);

		try { if (currentState === States.FLYING) particles.update(dt); } catch (e) { }

		renderer.render(scene, camera);

		renderer.clearDepth();

		camera.fov = 75;
		camera.updateProjectionMatrix();

		camera.layers.set(1);

		renderer.render(scene, camera);

	} else {
		threeContainer.classList.add('hidden');
		if (currentState === States.MENU) {
			updateMenuCamera(dt);
		}
	}
}

function closeAllModals() {
	document.querySelectorAll('.modal').forEach(m => m.classList.add('hidden'));
}

function setupModalListeners() {
	document.getElementById('helpBtn').onclick = () => {
		closeAllModals();
		document.getElementById('helpModal').classList.remove('hidden');
	};

	document.getElementById('optionsBtn').onclick = () => {
		closeAllModals();
		updateSettingsUI();
		document.getElementById('optionsModal').classList.remove('hidden');
	};

	document.getElementById('pauseOptionsBtn').onclick = () => {
		closeAllModals();
		updateSettingsUI();
		document.getElementById('optionsModal').classList.remove('hidden');
	};

	document.getElementById('pauseHelpBtn').onclick = () => {
		closeAllModals();
		document.getElementById('helpModal').classList.remove('hidden');
	};




	document.getElementById('sensitivitySlider').oninput = (e) => {
		document.getElementById('sensitivityValue').textContent = e.target.value;
	};

	document.getElementById('saveOptionsBtn').onclick = () => {
		gameSettings.graphicsQuality = document.getElementById('graphicsQuality').value;
		gameSettings.antialiasing = document.getElementById('antialiasing').checked;
		gameSettings.fogEffects = document.getElementById('fogEffects').checked;
		gameSettings.mouseSensitivity = parseFloat(document.getElementById('sensitivitySlider').value);
		gameSettings.showHud = document.getElementById('showHud').checked;
		gameSettings.showHorizonLines = document.getElementById('showHorizonLines').checked;
		gameSettings.soundEnabled = document.getElementById('soundEnabled').checked;
		gameSettings.minimapRange = parseInt(document.getElementById('minimapRange').value);

		saveSettings();
		applySettings();
		closeAllModals();
	};

	document.querySelectorAll('.close-modal').forEach(btn => {
		btn.onclick = (e) => {
			e.stopPropagation();
			btn.closest('.modal').classList.add('hidden');
		};
	});

	window.addEventListener('click', (event) => {
		if (event.target.classList.contains('modal')) {
			event.target.classList.add('hidden');
		}
	});
}

document.getElementById('startBtn').onclick = () => {
	closeAllModals();

	playStartBurst(() => {
		mainMenu.classList.add('hidden');
		// WS 연결 시 초기 좌표를 JSBSim에서 받아와 지도 시작 위치로 설정
		const wsState = getWSState();
		if (isWSConnected() && wsState && wsState.blue) {
			const b = wsState.blue;
			state.lon     = b.lon;
			state.lat     = b.lat;
			state.alt     = b.alt_m;
			state.heading = b.heading;
		}
		enterSpawnPicking(false);
	});
};

setupModalListeners();

document.getElementById('resumeBtn').onclick = () => {
	closeAllModals();
	pauseMenu.classList.add('hidden');
	uiContainer.classList.remove('hidden');
	const weaponsHud = document.getElementById('weapons-hud');
	if (weaponsHud) weaponsHud.classList.remove('hidden');
	currentState = States.FLYING;
	if (dialogueSystem) dialogueSystem.resume();
	resumeGameplaySounds();
};

document.getElementById('restartBtn').onclick = () => {
	closeAllModals();
	pauseMenu.classList.add('hidden');
	if (dialogueSystem) dialogueSystem.stop();
	enterSpawnPicking(true);
};

document.getElementById('quitBtn').onclick = () => {
	closeAllModals();
	if (dialogueSystem) dialogueSystem.stop();
	setRenderOptimization(true);
	location.reload();
};

document.getElementById('respawnBtn').onclick = () => {
	closeAllModals();
	crashMenu.classList.add('hidden');
	if (dialogueSystem) dialogueSystem.stop();
	enterSpawnPicking(true);
};

function enterSpawnPicking(useVignette = true) {
	state.score = 0;
	if (npcSystem) npcSystem.clear();
	stopAllFlyingSounds(0.3);
	soundManager.play('zoom-in');
	soundManager.play('wind', 1.0);
	const vignette = document.getElementById('transition-vignette');
	if (useVignette && vignette) vignette.style.opacity = '1';

	const delay = useVignette ? 500 : 0;

	setTimeout(() => {
		spawnInstruction.classList.remove('hidden');
		threeContainer.classList.add('hidden');
		uiContainer.classList.add('hidden');
		const weaponsHud = document.getElementById('weapons-hud');
		if (weaponsHud) weaponsHud.classList.add('hidden');
		currentState = States.PICK_SPAWN;
		confirmSpawnBtn.classList.add('hidden');

		const searchInput = document.getElementById('locationSearch');
		const instructionText = document.getElementById('instruction-text');
		const resultsContainer = document.getElementById('search-results');

		if (searchInput) {
			searchInput.value = '';
			searchInput.style.display = 'none';
		}
		if (instructionText) {
			instructionText.style.display = 'block';
			instructionText.textContent = 'CLICK ANYWHERE ON THE MAP TO CHOOSE SPAWN POINT';
		}
		if (resultsContainer) {
			resultsContainer.style.display = 'none';
		}

		setControlsEnabled(true);

		if (spawnMarker) {
			const viewer = getViewer();
			viewer.entities.remove(spawnMarker);
			spawnMarker = null;
		}

		const viewer = getViewer();
		viewer.camera.flyTo({
			destination: Cesium.Cartesian3.fromDegrees(state.lon, state.lat, 15000),
			duration: 2.0,
			complete: () => {
				if (vignette) vignette.style.opacity = '0';
			}
		});
	}, delay);
}

function exitSpawnPicking() {
	soundManager.play('zoom-in');
	soundManager.stop('wind', 1.0);
	stopAllFlyingSounds(0.3);
	spawnInstruction.classList.add('hidden');
	confirmSpawnBtn.classList.add('hidden');
	mainMenu.classList.remove('hidden');
	currentState = States.MENU;
	loadingIndicator.classList.add('hidden');
	setRenderOptimization(true);

	setControlsEnabled(false);

	if (spawnMarker) {
		const viewer = getViewer();
		viewer.entities.remove(spawnMarker);
		spawnMarker = null;
	}

	const viewer = getViewer();
	viewer.camera.flyTo({
		...initialCameraView,
		duration: 2.5
	});
}

function setupSpawnPicker() {
	const viewer = getViewer();
	const handler = new Cesium.ScreenSpaceEventHandler(viewer.scene.canvas);
	const instructionText = document.getElementById('instruction-text');

	handler.setInputAction((click) => {
		if (currentState !== States.PICK_SPAWN) return;

		const ray = viewer.camera.getPickRay(click.position);
		const cartesian = viewer.scene.globe.pick(ray, viewer.scene);

		if (cartesian) {
			const cartographic = Cesium.Cartographic.fromCartesian(cartesian);
			const lon = Cesium.Math.toDegrees(cartographic.longitude);
			const lat = Cesium.Math.toDegrees(cartographic.latitude);

			state.lon = lon;
			state.lat = lat;
			state.alt = Math.max(0, cartographic.height) + 1500;

			instructionText.textContent = 'FETCHING LOCATION INFO...';

			reverseGeocode(lon, lat).then(regionName => {
				if (regionName && currentState === States.PICK_SPAWN) {
					instructionText.textContent = regionName;
					if (spawnMarker) {
						spawnMarker.label.text = regionName;
					}
				}
			}).catch(() => { });

			Cesium.sampleTerrainMostDetailed(viewer.terrainProvider, [cartographic])
				.then(([p]) => state.alt = Math.max(0, p.height || 0) + 1500)
				.catch(() => { });

			if (spawnMarker) {
				viewer.entities.remove(spawnMarker);
			}
			spawnMarker = viewer.entities.add({
				position: cartesian,
				point: {
					pixelSize: 15,
					color: Cesium.Color.RED,
					outlineColor: Cesium.Color.WHITE,
					outlineWidth: 2,
					disableDepthTestDistance: Number.POSITIVE_INFINITY
				},
				label: {
					text: "Target Spawn Location",
					font: `14pt ${getComputedStyle(document.body).fontFamily}`,
					style: Cesium.LabelStyle.FILL_AND_OUTLINE,
					outlineWidth: 2,
					verticalOrigin: Cesium.VerticalOrigin.BOTTOM,
					pixelOffset: new Cesium.Cartesian2(0, -20),
					disableDepthTestDistance: Number.POSITIVE_INFINITY
				}
			});

			confirmSpawnBtn.classList.remove('hidden');
		}
	}, Cesium.ScreenSpaceEventType.LEFT_CLICK);
}

function setupLocationSearch() {
	const searchInput = document.getElementById('locationSearch');
	const resultsContainer = document.getElementById('search-results');
	const instructionText = document.getElementById('instruction-text');
	const searchToggleBtn = document.getElementById('search-toggle-btn');
	const originalSearchIcon = searchToggleBtn ? searchToggleBtn.innerHTML : '';
	let debounceTimer;

	if (searchToggleBtn) {
		searchToggleBtn.onclick = (e) => {
			e.stopPropagation();
			const isSearching = searchInput.style.display === 'block';

			if (isSearching) {
				searchInput.style.display = 'none';
				instructionText.style.display = 'block';
				resultsContainer.style.display = 'none';
			} else {
				searchInput.style.display = 'block';
				instructionText.style.display = 'none';
				searchInput.focus();
			}
		};
	}

	searchInput.addEventListener('input', (e) => {
		clearTimeout(debounceTimer);
		const query = e.target.value.trim();

		if (query.length < 3) {
			resultsContainer.style.display = 'none';
			return;
		}

		debounceTimer = setTimeout(async () => {
			if (searchToggleBtn) {
				searchToggleBtn.innerHTML = '<div class="loader-spinner"></div>';
			}

			try {
				const response = await fetch(`https://nominatim.openstreetmap.org/search?format=json&q=${encodeURIComponent(query)}&limit=5`);
				const data = await response.json();

				resultsContainer.innerHTML = '';
				if (data.length > 0) {
					data.forEach(item => {
						const div = document.createElement('div');
						div.textContent = item.display_name;
						div.style.padding = '10px';
						div.style.cursor = 'pointer';
						div.onclick = () => {
							const lon = parseFloat(item.lon);
							const lat = parseFloat(item.lat);

							const viewer = getViewer();
							const position = Cesium.Cartesian3.fromDegrees(lon, lat);

							state.lon = lon;
							state.lat = lat;
							state.alt = 1500;

							const cartographic = Cesium.Cartographic.fromDegrees(lon, lat);
							Cesium.sampleTerrainMostDetailed(viewer.terrainProvider, [cartographic])
								.then(([p]) => {
									state.alt = Math.max(0, p.height || 0) + 1500;
								})
								.catch(() => { });

							viewer.camera.flyTo({
								destination: Cesium.Cartesian3.fromDegrees(lon, lat, 15000),
								duration: 1.5
							});

							if (spawnMarker) {
								viewer.entities.remove(spawnMarker);
							}
							spawnMarker = viewer.entities.add({
								position: position,
								point: {
									pixelSize: 15,
									color: Cesium.Color.RED,
									outlineColor: Cesium.Color.WHITE,
									outlineWidth: 2,
									disableDepthTestDistance: Number.POSITIVE_INFINITY
								},
								label: {
									text: item.display_name.split(',')[0],
									font: `14pt ${getComputedStyle(document.body).fontFamily}`,
									style: Cesium.LabelStyle.FILL_AND_OUTLINE,
									outlineWidth: 2,
									verticalOrigin: Cesium.VerticalOrigin.BOTTOM,
									pixelOffset: new Cesium.Cartesian2(0, -20),
									disableDepthTestDistance: Number.POSITIVE_INFINITY
								}
							});

							confirmSpawnBtn.classList.remove('hidden');
							resultsContainer.style.display = 'none';

							searchInput.style.display = 'none';
							instructionText.style.display = 'block';
							instructionText.textContent = item.display_name.split(',')[0].toUpperCase();
							searchInput.value = item.display_name;
						};
						resultsContainer.appendChild(div);
					});
					resultsContainer.style.display = 'block';
				} else {
					resultsContainer.style.display = 'none';
				}
			} catch (error) {
				console.error('Search error:', error);
			} finally {
				if (searchToggleBtn) {
					searchToggleBtn.innerHTML = originalSearchIcon;
				}
			}
		}, 500);
	});

	document.addEventListener('click', (e) => {
		if (!searchInput.contains(e.target) && !resultsContainer.contains(e.target) && !searchToggleBtn.contains(e.target)) {
			resultsContainer.style.display = 'none';
			if (searchInput.style.display === 'block') {
				searchInput.style.display = 'none';
				instructionText.style.display = 'block';
			}
		}
	});
}

document.getElementById('confirmSpawnBtn').onclick = () => {
	const vignette = document.getElementById('transition-vignette');
	if (vignette) vignette.style.opacity = '1';

	soundManager.play('spawn');

	setTimeout(() => {
		const viewer = getViewer();
		if (spawnMarker) {
			viewer.entities.remove(spawnMarker);
			spawnMarker = null;
		}

		setControlsEnabled(false);

		state.speed = 100;
		state.pitch = 0;
		state.roll = 0;

		try {
			const cam = viewer && viewer.camera;
			if (cam && typeof cam.heading === 'number') {
				state.heading = Cesium.Math.toDegrees(cam.heading);
			} else {
				state.heading = 0;
			}
		} catch (e) {
			state.heading = 0;
		}

		currentRegionName = null;
		lastGeocodeTime = 0;
		lastGeocodePos = { lon: 0, lat: 0 };

		visualOffset.copy(BASE_PLANE_POS);
		visualRotation.set(0, 0, 0);
		boostRoll = 0;
		currentBoostZOffset = 0;
		lastIsBoosting = false;

		controller.reset();
		physics = new PlanePhysics();
		physics.reset(state.lon, state.lat, state.alt, state.heading, state.pitch, state.roll);

		// JSBSim WebSocket 연결 시도 (연결 없으면 기존 내부 물리로 동작)
		connectWSClient('ws://localhost:8765', () => {
			console.log('[CesiumWS] JSBSim 데이터 수신 시작 — 물리 엔진 외부 제어 모드');
		});

		hud.resetTime();
		hud.resizeMinimap();

		if (weaponSystem && typeof weaponSystem.resetAmmo === 'function') {
			weaponSystem.resetAmmo();
		}

		if (npcSystem && !isWSConnected()) {
			// WS 연결 시 JSBSim Red 기체가 상대방 → 랜덤 AI NPC 불필요
			npcSystem.spawnNPC(state.lon, state.lat, state.alt);
		}

		spawnInstruction.classList.add('hidden');
		confirmSpawnBtn.classList.add('hidden');
		loadingIndicator.classList.add('hidden');

		currentState = States.TRANSITIONING;
		setRenderOptimization(false);

		viewer.camera.flyTo({
			destination: Cesium.Cartesian3.fromDegrees(state.lon, state.lat, state.alt),
			orientation: {
				heading: Cesium.Math.toRadians(state.heading),
				pitch: Cesium.Math.toRadians(state.pitch),
				roll: Cesium.Math.toRadians(state.roll)
			},
			duration: 2.0,
			easingFunction: Cesium.EasingFunction.QUADRATIC_IN_OUT,
			complete: () => {
				flightStartTime = Date.now();
				uiContainer.classList.remove('hidden');
				const weaponsHud = document.getElementById('weapons-hud');
				if (weaponsHud) weaponsHud.classList.remove('hidden');
				threeContainer.classList.remove('hidden');
				hud.resizeMinimap();
				currentState = States.FLYING;
				soundManager.play('jet-engine', 1.0);
				if (vignette) vignette.style.opacity = '0';
				// WS 연결된 경우 도그파이트 HUD 표시
				if (isWSConnected()) {
					_dfHud.classList.remove('hidden');
					_dfMatchTime = 0;
					_matchDone = false;
				}

				if (dialogueSystem && !isWSConnected()) {
					// WS 연결 시 tutorial dialogue 표시 안 함
					dialogueSystem.start();
				}
			}
		});
	}, 500);
};

window.addEventListener('keydown', (e) => {
	const key = e.key.toLowerCase();
	if (key === 'escape') {
		const openModals = document.querySelectorAll('.modal:not(.hidden)');
		if (openModals.length > 0) {
			openModals.forEach(m => m.classList.add('hidden'));
			return;
		}
	}

	if (key === 'escape' || key === 'p') {
		if (currentState === States.FLYING) {
			currentState = States.PAUSED;
			if (dialogueSystem) dialogueSystem.pause();
			uiContainer.classList.add('hidden');
			const weaponsHud = document.getElementById('weapons-hud');
			if (weaponsHud) weaponsHud.classList.add('hidden');
			pauseMenu.classList.remove('hidden');
			hud.resizeMinimap();
			pauseGameplaySounds();
			hud.update(state, []);
		} else if (currentState === States.PAUSED) {
			currentState = States.FLYING;
			if (dialogueSystem) dialogueSystem.resume();
			pauseMenu.classList.add('hidden');
			uiContainer.classList.remove('hidden');
			const weaponsHud = document.getElementById('weapons-hud');
			if (weaponsHud) weaponsHud.classList.remove('hidden');
			resumeGameplaySounds();
		} else if (currentState === States.PICK_SPAWN && key === 'escape') {
			exitSpawnPicking();
		}
	}

	if (key === 'z' && currentState === States.FLYING) {
		if (dialogueSystem) dialogueSystem.skip();
	}

	if (key === 'c' && currentState === States.FLYING) {
		if (cameraMode === 'third') cameraMode = 'first';
		else if (cameraMode === 'first') cameraMode = 'third';
		else cameraMode = 'third'; // overview → third
		if (planeModel)      planeModel.visible      = cameraMode === 'third' && _followTarget !== 'red';
		if (redFollowModel)  redFollowModel.visible  = cameraMode === 'third' && _followTarget === 'red';
	}

	if (key === 'tab' && currentState === States.FLYING) {
		e.preventDefault(); // 브라우저 탭 포커스 이동 방지
		cameraMode = cameraMode === 'overview' ? 'third' : 'overview';
		if (planeModel)      planeModel.visible      = cameraMode === 'third' && _followTarget !== 'red';
		if (redFollowModel)  redFollowModel.visible  = cameraMode === 'third' && _followTarget === 'red';
	}
});

// 스크린샷/외부 앱 전환 시 자동 일시정지 비활성화
// document.addEventListener('visibilitychange', () => { ... });
// window.addEventListener('blur', () => { ... });
window.addEventListener('blur', () => {
	// 포커스 잃어도 일시정지 안 함 (스크린샷 편의)
	void 0;
});

const viewer = initCesium();
initMenuCamera();

loadingStatus.cesium = true;
updateLoadingUI();

// 타임아웃 폴백: 최대 5초 후 강제 완료
const globeTimeout = setTimeout(() => {
	if (!loadingStatus.globe) {
		loadingStatus.globe = true;
		updateLoadingUI();
	}
}, 5000);

const unregisterGlobeTracker = viewer.scene.postRender.addEventListener(() => {
	if (loadingStatus.globe) {
		unregisterGlobeTracker();
		return;
	}
	const tilesLoaded = viewer.scene.globe.tilesLoaded;
	if (tilesLoaded) {
		const surface = viewer.scene.globe._surface;
		const hasTiles = surface && surface._tilesToRender && surface._tilesToRender.length > 0;
		if (hasTiles) {
			clearTimeout(globeTimeout);
			loadingStatus.globe = true;
			updateLoadingUI();
			unregisterGlobeTracker();
		}
	}
});

viewer.scene.globe.tileLoadProgressEvent.addEventListener((queueLength) => {
	if (loadingIndicator && loadingText) {
		if (currentState === States.PICK_SPAWN) {
			if (queueLength > 0) {
				loadingText.textContent = "Loading Terrain...";
				loadingIndicator.classList.remove('hidden');
			} else {
				loadingIndicator.classList.add('hidden');
			}
		} else {
			const isAllLoaded = loadingStatus.audio && loadingStatus.model && loadingStatus.cesium && loadingStatus.globe;
			if (isAllLoaded) {
				loadingIndicator.classList.add('hidden');
			}
		}
	}
});

const resumeAudio = () => {
	if (soundManager.listener.context.state === 'suspended') {
		soundManager.listener.context.resume();
	}
	window.removeEventListener('mousedown', resumeAudio);
	window.removeEventListener('keydown', resumeAudio);
};
window.addEventListener('mousedown', resumeAudio);
window.addEventListener('keydown', resumeAudio);

initialCameraView = {
	destination: viewer.camera.position.clone(),
	orientation: {
		heading: viewer.camera.heading,
		pitch: viewer.camera.pitch,
		roll: viewer.camera.roll
	}
};

initThree();
npcSystem = new NPCSystem(viewer, scene);
playerTrail = new CesiumTrail(viewer, 0x4488ff, 400);
setupSpawnPicker();
setupLocationSearch();
loadSettings();

uiContainer.classList.add('hidden');
threeContainer.classList.add('hidden');

updateLoadingUI();
animate();

window.addEventListener('resize', () => {
	camera.aspect = window.innerWidth / window.innerHeight;
	camera.updateProjectionMatrix();
	renderer.setSize(window.innerWidth, window.innerHeight);

	const viewer = getViewer();
	if (viewer) viewer.resize();
});

window.addEventListener('contextmenu', (e) => {
	e.preventDefault();
}, false);
