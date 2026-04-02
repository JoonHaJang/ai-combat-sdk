import * as THREE from 'three';
import * as Cesium from 'cesium';
import { Missile } from '../weapon/missile';
import { Bullet } from '../weapon/bullet';
import { Flare } from '../weapon/flare';
import { soundManager } from '../utils/soundManager';
import { movePosition } from '../utils/math';

export class WeaponSystem {
	constructor(viewer, scene, playerModel) {
		this.viewer = viewer;
		this.scene = scene;
		this.playerModel = playerModel;

		this.weapons = [
			{ id: 'gun', name: 'M61A1 CANNON', ammo: Infinity, maxAmmo: Infinity, fireRate: 0.05, lastFire: 0 },
			{ id: 'missile', name: 'AIM-9 SIDEWINDER', ammo: 50, maxAmmo: 50, fireRate: 1.0, lastFire: 0, type: 'AIM-9' }
		];

		this.flareWeapon = { id: 'flare', name: 'MJU-7A', ammo: 30, maxAmmo: 30, fireRate: 0.2, lastFire: 0 };

		this.selectedWeaponIndex = 0;
		this.projectiles = [];
		this.flares = [];
		this.onKill = null;

		this.target = null;
		this.isGunOverheated = false;
		this.gunHeat = 0;

		this.lockTime = 0;
		this.lockRequiredTime = 2.0;
		this.lockStatus = 'NONE';
		this.lockingTarget = null;

		this.flareQueue = 0;
		this.flareInterval = 0.15;
		this.lastFlarePulse = 0;

		this.lastMissileSide = false;

		this.emptyWarningTimers = {
			gun: 0,
			missile: 0,
			flare: 0
		};
		this.lastEmptyWarningSoundTime = 0;
	}

	resetAmmo() {
		this.selectedWeaponIndex = 0;
		for (const w of this.weapons) {
			if (typeof w.maxAmmo !== 'undefined') w.ammo = w.maxAmmo;
		}
		if (this.flareWeapon && typeof this.flareWeapon.maxAmmo !== 'undefined') {
			this.flareWeapon.ammo = this.flareWeapon.maxAmmo;
		}
		this.gunHeat = 0;
		this.isGunOverheated = false;

		this.emptyWarningTimers = {
			gun: 0,
			missile: 0,
			flare: 0
		};
	}

	getCurrentWeapon() {
		return this.weapons[this.selectedWeaponIndex];
	}

	toggleWeapon() {
		this.selectedWeaponIndex = (this.selectedWeaponIndex + 1) % this.weapons.length;
		try { soundManager.play('weapon-switch'); } catch (e) { }
	}

	selectWeapon(index) {
		if (index >= 0 && index < this.weapons.length) {
			this.selectedWeaponIndex = index;
		}
		try { soundManager.play('weapon-switch'); } catch (e) { }
	}

	// 카메라 스페이스 하드포인트 → 지리 좌표 변환
	// Three.js 카메라 스페이스 좌표(cx,cy,cz)를 Cesium invView로 역변환
	// 모델이 화면 고정 위치에 있으므로, 파츠 위치를 카메라 스페이스로 정의하면 항상 정확
	calculateWeaponPosCameraSpace(cx, cy, cz) {
		const viewMatrix = this.viewer.camera.viewMatrix;
		const invView = new Cesium.Matrix4();
		Cesium.Matrix4.inverse(viewMatrix, invView);
		const worldPos = Cesium.Matrix4.multiplyByPoint(
			invView,
			new Cesium.Cartesian3(cx, cy, cz),
			new Cesium.Cartesian3()
		);
		const carto = Cesium.Cartographic.fromCartesian(worldPos);
		if (!carto) return null;
		return {
			lon: Cesium.Math.toDegrees(carto.longitude),
			lat: Cesium.Math.toDegrees(carto.latitude),
			alt: carto.height
		};
	}

	// ENU 세계 좌표 기반 무장 위치 계산
	// forwardM: 기수 방향 (m), rightM: 우익 방향 (m), upM: 위 방향 (m)
	calculateWeaponPosWorld(playerState, forwardM, rightM, upM) {
		const headingRad = Cesium.Math.toRadians(playerState.heading);
		const pitchRad   = Cesium.Math.toRadians(playerState.pitch);
		const latRad     = Cesium.Math.toRadians(playerState.lat);

		// ENU 축: Forward, Right (수평 수직), Up
		const fE = Math.sin(headingRad) * Math.cos(pitchRad);
		const fN = Math.cos(headingRad) * Math.cos(pitchRad);
		const fU = Math.sin(pitchRad);

		const rE =  Math.cos(headingRad);
		const rN = -Math.sin(headingRad);

		const dE = fE * forwardM + rE * rightM;
		const dN = fN * forwardM + rN * rightM;
		const dU = fU * forwardM + upM;

		return {
			lon: playerState.lon + dE / (111320 * Math.cos(latRad)),
			lat: playerState.lat + dN / 111320,
			alt: playerState.alt + dU
		};
	}

	fire(playerState, specificWeaponId = null) {
		const weapon = specificWeaponId
			? this.weapons.find(w => w.id === specificWeaponId)
			: this.weapons[this.selectedWeaponIndex];

		if (!weapon) return;

		const now = performance.now() * 0.001;

		if (weapon.ammo <= 0) {
			if (now - this.lastEmptyWarningSoundTime > 2.0) {
				this.emptyWarningTimers[weapon.id] = 1.0;
				this.lastEmptyWarningSoundTime = now;
				try { soundManager.play('weapon-warning'); } catch (e) { }
			}
			return;
		}
		if (weapon.id === 'gun' && this.isGunOverheated) return;
		if (now - weapon.lastFire < weapon.fireRate) return;

		if (weapon.id === 'missile' && this.lockStatus !== 'LOCKED') {
			return;
		}

		weapon.lastFire = now;
		if (weapon.ammo !== Infinity) weapon.ammo--;

		const startPos = {
			lon: playerState.lon,
			lat: playerState.lat,
			alt: playerState.alt
		};

		if (weapon.id === 'gun') {
			this.gunHeat += 0.02;
			if (this.gunHeat >= 1.0) {
				this.isGunOverheated = true;
				try { soundManager.play('weapon-warning'); } catch (e) { }
			}

			// 기수 앞 5m — 1인칭/3인칭/WS 모드 모두 정확
			const nosePos = this.calculateWeaponPosWorld(playerState, 5, 0, 0);

			const bullet = new Bullet(
				this.scene,
				this.viewer,
				nosePos,
				playerState.heading,
				playerState.pitch,
				playerState.speed,
				this.onKill
			);
			this.projectiles.push(bullet);
		} else if (weapon.id === 'missile') {
			this.lastMissileSide = !this.lastMissileSide;
			const side = this.lastMissileSide ? 1 : -1;
			// 좌/우 날개 하드포인트 (기체 기준 세계 좌표)
			const launchPos = this.calculateWeaponPosWorld(playerState, 0, side * 8, -2);

			const target = this.target;
			const missile = new Missile(
				this.scene,
				this.viewer,
				launchPos,
				playerState.heading,
				playerState.pitch,
				playerState.speed,
				target,
				this.onKill
			);
			this.projectiles.push(missile);

			try { soundManager.play('missile-fire'); } catch (e) { }
		}
	}

	fireFlare(playerState) {
		const flareWeapon = this.flareWeapon;
		const now = performance.now() * 0.001;

		if (!flareWeapon || flareWeapon.ammo <= 0) {
			if (now - this.lastEmptyWarningSoundTime > 2.0) {
				this.emptyWarningTimers['flare'] = 1.0;
				this.lastEmptyWarningSoundTime = now;
				try { soundManager.play('weapon-warning'); } catch (e) { }
			}
			return;
		}
		if (now - flareWeapon.lastFire < 1.0) return;

		flareWeapon.ammo--;
		flareWeapon.lastFire = now;

		this.flareQueue = 6;
		this.lastFlarePulse = 0;
	}

	_spawnSingleFlare(playerState) {
		// 플레어 방출구: 기체 후방 3m, 하단 1m
		const startPos = this.calculateWeaponPosWorld(playerState, -3, 0, -1);

		const flare = new Flare(
			this.scene,
			this.viewer,
			startPos,
			playerState.heading,
			playerState.pitch,
			playerState.speed
		);

		this.flares.push(flare);
	}

	update(dt, playerState, input = null) {
		const prevLockStatus = this.lockStatus;
		const currentWeapon = this.getCurrentWeapon();

		try {
			const isFiringGun = input && input.fire && currentWeapon.id === 'gun' && !this.isGunOverheated && currentWeapon.ammo > 0;
			if (isFiringGun) {
				if (!soundManager.isPlaying('m61-firing')) {
					soundManager.play('m61-firing');
				}
			} else {
				if (soundManager.isPlaying('m61-firing')) {
					soundManager.stop('m61-firing');
				}
			}
		} catch (e) { }

		if (currentWeapon.id === 'missile') {
			const potentialTarget = this.findPotentialTarget(playerState);

			if (potentialTarget) {
				if (this.lockingTarget === potentialTarget) {
					this.lockTime += dt;
					if (this.lockTime >= this.lockRequiredTime) {
						this.lockStatus = 'LOCKED';
						this.target = potentialTarget;
					} else {
						this.lockStatus = 'LOCKING';
					}
				} else {
					this.lockingTarget = potentialTarget;
					this.lockTime = 0;
					this.lockStatus = 'LOCKING';
					this.target = null;
				}
			} else {
				this.lockingTarget = null;
				this.lockTime = 0;
				this.lockStatus = 'NONE';
				this.target = null;
			}
		} else {
			this.lockingTarget = null;
			this.lockTime = 0;
			this.lockStatus = 'NONE';
			this.target = null;
		}

		try {
			if (this.lockStatus === 'LOCKING') {
				if (!soundManager.isPlaying('rwr-tws')) {
					soundManager.play('rwr-tws');
				}
			} else {
				if (soundManager.isPlaying('rwr-tws')) {
					soundManager.stop('rwr-tws');
				}
			}

			if (prevLockStatus !== this.lockStatus && this.lockStatus === 'LOCKED') {
				soundManager.play('rwr-lock');
			}
			if (prevLockStatus === 'LOCKED' && this.lockStatus !== 'LOCKED') {
				if (soundManager.isPlaying('rwr-lock')) {
					soundManager.stop('rwr-lock');
				}
			}
		} catch (e) { }

		if (this.flareQueue > 0) {
			this.lastFlarePulse += dt;
			if (this.lastFlarePulse >= this.flareInterval || this.flareQueue === 6) {
				this._spawnSingleFlare(playerState);
				this.flareQueue--;
				this.lastFlarePulse = 0;
			}
		}

		if (this.gunHeat > 0) {
			this.gunHeat -= dt * 0.2;
			if (this.gunHeat <= 0) {
				this.gunHeat = 0;
				this.isGunOverheated = false;
			}
			if (this.isGunOverheated && this.gunHeat < 0.3) {
				this.isGunOverheated = false;
			}
		}

		for (const key in this.emptyWarningTimers) {
			if (this.emptyWarningTimers[key] > 0) {
				this.emptyWarningTimers[key] -= dt;
				if (this.emptyWarningTimers[key] < 0) this.emptyWarningTimers[key] = 0;
			}
		}

		const npcs = playerState.npcs || [];

		for (let i = this.projectiles.length - 1; i >= 0; i--) {
			const p = this.projectiles[i];
			p.update(dt, npcs);
			const hasTrail = p.trail && p.trail.length > 0;
			if (!p.active && !hasTrail) {
				this.projectiles.splice(i, 1);
			}
		}

		for (let i = this.flares.length - 1; i >= 0; i--) {
			const f = this.flares[i];
			f.update(dt);
			if (!f.active) {
				this.flares.splice(i, 1);
			}
		}
	}

	findPotentialTarget(playerState) {
		if (!playerState.npcs || playerState.npcs.length === 0) return null;

		let bestTarget = null;
		let maxDot = 0.985;

		for (const npc of playerState.npcs) {
			if (npc.destroyed) continue;

			const dot = this.calculateDotProduct(playerState, npc);
			if (dot > maxDot) {
				const dist = this.calculateDist(playerState, npc);
				if (dist < 10000) {
					bestTarget = npc;
					maxDot = dot;
				}
			}
		}
		return bestTarget;
	}

	calculateDotProduct(player, npc) {
		const hRad = Cesium.Math.toRadians(player.heading);
		const pRad = Cesium.Math.toRadians(player.pitch);
		const pDir = new THREE.Vector3(
			Math.sin(hRad) * Math.cos(pRad),
			Math.sin(pRad),
			Math.cos(hRad) * Math.cos(pRad)
		);

		const dLon = (npc.lon - player.lon) * 111320 * Math.cos(Cesium.Math.toRadians(player.lat));
		const dLat = (npc.lat - player.lat) * 111320;
		const dAlt = npc.alt - player.alt;
		const toNpc = new THREE.Vector3(dLon, dAlt, dLat).normalize();

		return pDir.dot(toNpc);
	}

	calculateDist(player, npc) {
		const dLon = (npc.lon - player.lon) * 111320 * Math.cos(Cesium.Math.toRadians(player.lat));
		const dLat = (npc.lat - player.lat) * 111320;
		const dAlt = npc.alt - player.alt;
		return Math.sqrt(dLon * dLon + dLat * dLat + dAlt * dAlt);
	}
}
