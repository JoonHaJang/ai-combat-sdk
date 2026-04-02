import * as THREE from 'three';
import * as Cesium from 'cesium';
import { GLTFLoader } from 'three/examples/jsm/loaders/GLTFLoader.js';
import { CesiumTrail } from '../plane/cesiumTrail';
import { movePosition } from '../utils/math';

export class NPCSystem {
	constructor(viewer, scene) {
		this.viewer = viewer;
		this.scene  = scene;
		this.npcs   = [];
		this.npcNames = [
			'PHOENIX', 'MARVEL', 'VIPER', 'GHOST', 'RAVEN',
			'EAGLE', 'FALCON', 'BLADE', 'STRIKER', 'STORM', 'KNIGHT', 'TITAN',
		];
		this.lastSpawnTime = 0;

		this.modelTemplate = null;
		this.animations    = [];
		this.loaded        = false;

		// scratch 재사용 (GC 최소화)
		this._scratchMatrix     = new Cesium.Matrix4();
		this._scratchHPR        = new Cesium.HeadingPitchRoll();
		this._scratchCartesian  = new Cesium.Cartesian3();
		this._scratchThreeMatrix = new THREE.Matrix4();
		this._scratchCameraMatrix = new Cesium.Matrix4();

		this._loadModel();
	}

	// ─── 모델 로딩 ────────────────────────────────────────────────────────────

	_loadModel() {
		const loader = new GLTFLoader();
		loader.load('/assets/models/f-16.glb', (gltf) => {
			this.modelTemplate = gltf.scene;
			this.animations    = gltf.animations;
			this.modelTemplate.traverse((child) => {
				if (child.isMesh) {
					child.castShadow    = true;
					child.receiveShadow = true;
				}
			});
			this.loaded = true;

			// 로딩 완료 전에 생성된 NPC 메시 소급 생성
			for (const npc of this.npcs) {
				if (!npc.mesh) this._attachMesh(npc);
			}
		});
	}

	// ─── NPC 생성 ─────────────────────────────────────────────────────────────

	spawnNPC(playerLon, playerLat, playerAlt) {
		if (!this.loaded) return null;

		const angle  = Math.random() * Math.PI * 2;
		const dist   = 5000 + Math.random() * 15000;
		const cosLat = Math.cos(Cesium.Math.toRadians(playerLat));

		const lon = playerLon + (dist * Math.cos(angle)) / (111320 * cosLat);
		const lat = playerLat + (dist * Math.sin(angle)) / 111320;
		const alt = Math.max(playerAlt + (Math.random() - 0.5) * 1000, 1500);

		const name = this.npcNames[Math.floor(Math.random() * this.npcNames.length)]
		           + ' ' + (100 + Math.floor(Math.random() * 900));

		return this._createNPC(name, lon, lat, alt, Math.random() * 360, 250 + Math.random() * 100);
	}

	_createNPC(id, lon, lat, alt, heading, speed) {
		const isRed  = id.startsWith('RED_') || id.toLowerCase().includes('red');
		const isBlue = id.startsWith('BLUE_');
		const trailColor = isRed ? 0xff3333 : isBlue ? 0x4488ff : 0x888888;

		const npc = {
			id,
			name: id,
			mesh: null,
			mixer: null,

			lon, lat, alt,
			heading,
			pitch: 0, roll: 0,
			speed,
			throttle: 0.7,
			isBoosting: false,

			targetHeading: heading,
			targetPitch:   0,
			behaviorTimer:     5 + Math.random() * 10,
			terrainCheckTimer: Math.random() * 2,
			time: Math.random() * 100,

			destroyed:  false,
			isExternal: false,

			trail: new CesiumTrail(this.viewer, trailColor, 400),
		};

		this.npcs.push(npc);

		if (this.loaded) this._attachMesh(npc);

		return npc;
	}

	_attachMesh(npc) {
		const group = new THREE.Group();
		const model = this.modelTemplate.clone();

		// 원본(f-15)과 동일한 축 보정 — f-16을 Blender에서 f-15 축에 맞췄으므로 동일 적용
		model.rotation.x = Math.PI / 2;

		// RED 계열 NPC는 붉은 tint
		if (npc.id.startsWith('RED_') || npc.id.toLowerCase().includes('red')) {
			model.traverse(child => {
				if (child.isMesh && child.material) {
					child.material = child.material.clone();
					child.material.color    = new THREE.Color(1.0, 0.4, 0.4);
					child.material.emissive = new THREE.Color(0.2, 0.0, 0.0);
				}
			});
		}

		group.add(model);
		group.matrixAutoUpdate = false;
		this.scene.add(group);

		npc.mesh = group;

		if (this.animations.length > 0) {
			const mixer = new THREE.AnimationMixer(model);
			const clip  = THREE.AnimationClip.findByName(this.animations, 'flight_mode');
			if (clip) {
				const action = mixer.clipAction(clip);
				action.setLoop(THREE.LoopOnce);
				action.clampWhenFinished = true;
				action.play();
			}
			npc.mixer = mixer;
		}
	}

	// ─── 매 프레임 업데이트 ───────────────────────────────────────────────────

	update(dt, playerPos) {
		const viewMatrix = this.viewer.camera.viewMatrix;

		for (let i = this.npcs.length - 1; i >= 0; i--) {
			const npc = this.npcs[i];

			if (npc.destroyed) {
				if (npc.mesh) this.scene.remove(npc.mesh);
				if (npc.trail) npc.trail.dispose();
				this.npcs.splice(i, 1);
				continue;
			}

			// 외부 제어(JSBSim): AI 건너뛰고 변환만 갱신
			if (!npc.isExternal) {
				this._runAI(npc, dt);
			}

			if (npc.mesh) this._updateMeshMatrix(npc, viewMatrix);
			if (npc.trail) npc.trail.update(npc.lon, npc.lat, npc.alt);
			if (npc.mixer) npc.mixer.update(dt);
		}

		// 외부 NPC 없을 때만 AI NPC 자동 스폰 (최대 3기)
		if (!this.npcs.some(n => n.isExternal)
		    && this.npcs.length < 3
		    && playerPos
		    && Date.now() - this.lastSpawnTime > 5000) {
			this.spawnNPC(playerPos.lon, playerPos.lat, playerPos.alt);
			this.lastSpawnTime = Date.now();
		}

		this.viewer.scene.requestRender();
	}

	// ─── Three.js 메시 매트릭스 갱신 ─────────────────────────────────────────

	_updateMeshMatrix(npc, viewMatrix) {
		const pos = Cesium.Cartesian3.fromDegrees(npc.lon, npc.lat, npc.alt, undefined, this._scratchCartesian);

		// 원본과 동일: pitch↔roll 슬롯 스왑
		this._scratchHPR.heading = Cesium.Math.toRadians(npc.heading);
		this._scratchHPR.pitch   = Cesium.Math.toRadians(npc.roll);   // roll → pitch 슬롯
		this._scratchHPR.roll    = Cesium.Math.toRadians(npc.pitch);  // pitch → roll 슬롯

		const modelMatrix = Cesium.Transforms.headingPitchRollToFixedFrame(
			pos,
			this._scratchHPR,
			Cesium.Ellipsoid.WGS84,
			Cesium.Transforms.eastNorthUpToFixedFrame,
			this._scratchMatrix,
		);

		const camMatrix = Cesium.Matrix4.multiply(viewMatrix, modelMatrix, this._scratchCameraMatrix);

		for (let k = 0; k < 16; k++) {
			this._scratchThreeMatrix.elements[k] = camMatrix[k];
		}

		npc.mesh.matrix.copy(this._scratchThreeMatrix);
		npc.mesh.updateMatrixWorld(true);
	}

	// ─── AI 행동 ──────────────────────────────────────────────────────────────

	_runAI(npc, dt) {
		npc.time              += dt;
		npc.behaviorTimer     -= dt;
		npc.terrainCheckTimer -= dt;

		if (npc.behaviorTimer <= 0) {
			npc.targetHeading = (npc.heading + (Math.random() - 0.5) * 120 + 360) % 360;
			npc.targetPitch   = (Math.random() - 0.5) * 25;
			npc.behaviorTimer = 8 + Math.random() * 15;
			npc.isBoosting    = Math.random() > 0.7;
			npc.throttle      = 0.6 + Math.random() * 0.4;
		}

		if (npc.terrainCheckTimer <= 0) {
			npc.terrainCheckTimer = 0.5;
			const carto       = Cesium.Cartographic.fromDegrees(npc.lon, npc.lat);
			const terrainH    = this.viewer.scene.globe.getHeight(carto);
			if (terrainH !== undefined) {
				const relAlt = npc.alt - terrainH;
				if (relAlt < 500) {
					npc.targetPitch = Math.max(npc.targetPitch, 25);
					npc.isBoosting  = true;
					npc.throttle    = 1.0;
					if (relAlt < 100) npc.targetPitch = 45;
				}
			}
		}

		// 헤딩 수렴
		let hdgDiff = npc.targetHeading - npc.heading;
		while (hdgDiff < -180) hdgDiff += 360;
		while (hdgDiff >  180) hdgDiff -= 360;
		const maxTurn = (npc.isBoosting ? 90 : 30) * dt;
		npc.heading = (npc.heading + Math.max(-maxTurn, Math.min(maxTurn, hdgDiff)) + 360) % 360;

		// 피치 수렴
		npc.pitch += (npc.targetPitch - npc.pitch) * dt * 0.6;

		// 롤
		const desiredRoll = Math.abs(hdgDiff) > 0.5
			? -Math.sign(hdgDiff) * 90 * Math.min(1, Math.abs(hdgDiff) / 45)
			: 0;
		npc.roll += (desiredRoll - npc.roll) * Math.min(1, dt * 3.0);
		npc.roll  = Math.max(-90, Math.min(90, npc.roll));

		// 위치 이동
		const newPos = movePosition(npc.lon, npc.lat, npc.alt, npc.heading, npc.pitch, npc.speed * dt);
		npc.lon = newPos.lon;
		npc.lat = newPos.lat;
		npc.alt = newPos.alt;
	}

	// ─── 외부 상태 주입 (JSBSim WS) ──────────────────────────────────────────

	updateExternal(id, lon, lat, alt_m, heading, pitch, roll) {
		let npc = this.npcs.find(n => n.id === id);
		if (!npc) {
			npc = this._createNPC(id, lon, lat, alt_m, heading, 0);
			if (!npc) return;
			npc.isExternal = true;
		}
		npc.lon     = lon;
		npc.lat     = lat;
		npc.alt     = alt_m;
		npc.heading = heading;
		npc.pitch   = pitch;
		npc.roll    = roll;
	}

	// ─── 전체 정리 ────────────────────────────────────────────────────────────

	clear() {
		this.npcs.forEach(npc => {
			if (npc.mesh)  this.scene.remove(npc.mesh);
			if (npc.trail) npc.trail.dispose();
		});
		this.npcs = [];
	}
}
