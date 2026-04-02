import * as THREE from 'three';
import * as Cesium from 'cesium';

// 50m 이동할 때마다 히스토리 포인트 저장
const SAMPLE_DIST_SQ = 50 * 50;

// 깊이 비례 폭: halfW = SCREEN_FRAC * |camZ|
// → 거리와 무관하게 화면상 일정 두께 (0.003 ≈ FOV75에서 약 2px@1080p)
const SCREEN_FRAC  = 0.003;
const MIN_HALF_W   = 15;    // 아주 멀 때도 최소 선 두께 유지 (m)
const MAX_HALF_W   = 150;   // 매우 가까울 때 화면 가득 차는 것 방지 (m)

const VAPOR_FRAC   = 0.005; // 흰 증기 폭 (색상 리본보다 조금 더 넓게)
const VAPOR_PTS    = 100;   // 흰 증기 최근 포인트 수 (늘림)

export class AircraftTrail {
	/**
	 * @param {THREE.Scene} scene
	 * @param {number} color  - 경로선 색상 (hex)
	 * @param {number} maxPoints - 최대 포인트 수 (기본 150 = ~7500m 경로)
	 */
	constructor(scene, color, maxPoints = 150) {
		this.maxPoints    = maxPoints;
		this.worldPositions = []; // 히스토리 ECEF 좌표 (최대 maxPoints-1개)
		this.lastPos      = null;
		this._scratchCam  = new Cesium.Cartesian3();

		// 렌더용 카메라 공간 XY + Z (히스토리 + 현재 포인트)
		this._camX = new Float32Array(maxPoints);
		this._camY = new Float32Array(maxPoints);
		this._camZ = new Float32Array(maxPoints);

		// ── 색상 리본 ──
		// 버텍스: 포인트당 좌·우 2개 = maxPoints*2, 인덱스: 세그먼트당 6
		const idxArr = new Uint32Array((maxPoints - 1) * 6);
		for (let i = 0; i < maxPoints - 1; i++) {
			const v = i * 2, j = i * 6;
			idxArr[j]   = v;   idxArr[j+1] = v+2; idxArr[j+2] = v+1;
			idxArr[j+3] = v+1; idxArr[j+4] = v+2; idxArr[j+5] = v+3;
		}
		const idxAttr = new THREE.BufferAttribute(idxArr, 1);

		this.posAttr = new THREE.BufferAttribute(new Float32Array(maxPoints * 2 * 3), 3);
		this.posAttr.setUsage(THREE.DynamicDrawUsage);

		this.geometry = new THREE.BufferGeometry();
		this.geometry.setAttribute('position', this.posAttr);
		this.geometry.setIndex(idxAttr);
		this.geometry.setDrawRange(0, 0);

		this.material = new THREE.MeshBasicMaterial({
			color,
			transparent: true,
			opacity: 0.85,
			side: THREE.DoubleSide,
			depthWrite: false,
			blending: THREE.AdditiveBlending,
		});

		this.mesh = new THREE.Mesh(this.geometry, this.material);
		this.mesh.frustumCulled = false;
		scene.add(this.mesh);

		// ── 흰색 증기 리본 (최근 VAPOR_PTS 포인트) ──
		const vMax = Math.min(VAPOR_PTS, maxPoints);
		const wIdxArr = new Uint32Array((vMax - 1) * 6);
		for (let i = 0; i < vMax - 1; i++) {
			const v = i * 2, j = i * 6;
			wIdxArr[j]   = v;   wIdxArr[j+1] = v+2; wIdxArr[j+2] = v+1;
			wIdxArr[j+3] = v+1; wIdxArr[j+4] = v+2; wIdxArr[j+5] = v+3;
		}

		this.wPosAttr = new THREE.BufferAttribute(new Float32Array(vMax * 2 * 3), 3);
		this.wPosAttr.setUsage(THREE.DynamicDrawUsage);

		this.wGeometry = new THREE.BufferGeometry();
		this.wGeometry.setAttribute('position', this.wPosAttr);
		this.wGeometry.setIndex(new THREE.BufferAttribute(wIdxArr, 1));
		this.wGeometry.setDrawRange(0, 0);

		this.wMaterial = new THREE.MeshBasicMaterial({
			color: 0xffffff,
			transparent: true,
			opacity: 0.14,
			side: THREE.DoubleSide,
			depthWrite: false,
			blending: THREE.AdditiveBlending,
		});

		this.wMesh = new THREE.Mesh(this.wGeometry, this.wMaterial);
		this.wMesh.frustumCulled = false;
		scene.add(this.wMesh);

		this._dir  = new THREE.Vector2();
		this._perp = new THREE.Vector2();
	}

	/**
	 * 매 프레임 호출.
	 * 현재 위치를 항상 마지막 포인트로 추가 → 엔진에서 trail이 시작하는 것처럼 보임.
	 * @param {Cesium.Matrix4} viewMatrix
	 * @param {number} lon
	 * @param {number} lat
	 * @param {number} alt - 미터
	 */
	update(viewMatrix, lon, lat, alt) {
		const worldPos = Cesium.Cartesian3.fromDegrees(lon, lat, alt);

		// 50m 이상 이동 시 히스토리에 저장 (maxPoints-1개: 마지막 슬롯은 현재 위치용)
		if (!this.lastPos ||
			Cesium.Cartesian3.distanceSquared(this.lastPos, worldPos) >= SAMPLE_DIST_SQ) {
			this.lastPos = worldPos;
			this.worldPositions.push(worldPos);
			if (this.worldPositions.length > this.maxPoints - 1) this.worldPositions.shift();
		}

		// 렌더 포인트 = 히스토리 + 현재 위치 (항상 엔진에서 끝남)
		const hist = this.worldPositions;
		const n = hist.length + 1; // +1 for current

		if (n < 2) {
			this.geometry.setDrawRange(0, 0);
			this.wGeometry.setDrawRange(0, 0);
			return;
		}

		// ECEF → 카메라 공간
		const cx = this._camX, cy = this._camY, cz = this._camZ;
		for (let i = 0; i < hist.length; i++) {
			Cesium.Matrix4.multiplyByPoint(viewMatrix, hist[i], this._scratchCam);
			cx[i] = this._scratchCam.x;
			cy[i] = this._scratchCam.y;
			cz[i] = this._scratchCam.z;
		}
		// 현재 위치 (항상 마지막)
		Cesium.Matrix4.multiplyByPoint(viewMatrix, worldPos, this._scratchCam);
		cx[n-1] = this._scratchCam.x;
		cy[n-1] = this._scratchCam.y;
		cz[n-1] = this._scratchCam.z;

		// ── 색상 리본 버텍스 ──
		this._buildRibbon(this.posAttr.array, cx, cy, cz, n, SCREEN_FRAC, VAPOR_FRAC * 0, false);
		this.posAttr.needsUpdate = true;
		this.geometry.setDrawRange(0, (n - 1) * 6);

		// ── 흰색 증기 리본 (최근 VAPOR_PTS 포인트) ──
		const vMax = Math.min(VAPOR_PTS, this.maxPoints);
		const wStart = Math.max(0, n - vMax);
		const wCount = n - wStart;
		if (wCount >= 2) {
			this._buildRibbon(this.wPosAttr.array, cx, cy, cz, n, VAPOR_FRAC, VAPOR_FRAC, true, wStart);
			this.wPosAttr.needsUpdate = true;
			this.wGeometry.setDrawRange(0, (wCount - 1) * 6);
		} else {
			this.wGeometry.setDrawRange(0, 0);
		}
	}

	/**
	 * 리본 버텍스 배열 채우기.
	 * @param {Float32Array} arr   - 버텍스 배열 (버텍스당 L·R × 3floats)
	 * @param {Float32Array} cx/cy/cz - 카메라 공간 좌표
	 * @param {number} n           - 전체 포인트 수
	 * @param {number} frac        - 스크린 비례 반폭 계수
	 * @param {number} _unused
	 * @param {boolean} reindex    - true이면 wStart 기준으로 재인덱싱
	 * @param {number} start       - 시작 인덱스 (reindex=true 시)
	 */
	_buildRibbon(arr, cx, cy, cz, n, frac, _unused, reindex, start = 0) {
		const dir = this._dir, perp = this._perp;
		const end = reindex ? n : n;
		const count = reindex ? n - start : n;
		for (let ii = 0; ii < count; ii++) {
			const i = reindex ? start + ii : ii;
			const next = i < n - 1 ? i + 1 : i;
			const prev = i > 0 ? i - 1 : i;
			if (i < n - 1) {
				dir.set(cx[next] - cx[i], cy[next] - cy[i]);
			} else {
				dir.set(cx[i] - cx[prev], cy[i] - cy[prev]);
			}
			const len = dir.length();
			if (len > 0.001) dir.divideScalar(len); else dir.set(1, 0);

			// 깊이 비례 폭 (가까울수록 자동으로 얇아짐)
			const depth = Math.abs(cz[i]);
			const halfW = Math.max(MIN_HALF_W, Math.min(MAX_HALF_W, frac * depth));

			perp.set(-dir.y, dir.x).multiplyScalar(halfW);

			const vi = ii * 2 * 3;
			arr[vi]   = cx[i] - perp.x; arr[vi+1] = cy[i] - perp.y; arr[vi+2] = cz[i];
			arr[vi+3] = cx[i] + perp.x; arr[vi+4] = cy[i] + perp.y; arr[vi+5] = cz[i];
		}
	}

	/** 가시성 제어 */
	setVisible(v) {
		this.mesh.visible = v;
		this.wMesh.visible = v;
	}

	dispose() {
		this.geometry.dispose();
		this.material.dispose();
		if (this.mesh.parent) this.mesh.parent.remove(this.mesh);
		this.wGeometry.dispose();
		this.wMaterial.dispose();
		if (this.wMesh.parent) this.wMesh.parent.remove(this.wMesh);
	}
}
