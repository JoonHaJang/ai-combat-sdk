import * as Cesium from 'cesium';

const SAMPLE_DIST_SQ = 30 * 30; // 30m마다 점 추가

export class CesiumTrail {
	/**
	 * @param {Cesium.Viewer} viewer
	 * @param {number} colorHex  - 0x4488ff / 0xff3333 등
	 * @param {number} maxPoints
	 */
	constructor(viewer, colorHex, maxPoints = 400) {
		this.viewer    = viewer;
		this.positions = [];
		this.lastPos   = null;
		this.maxPoints = maxPoints;

		const r = ((colorHex >> 16) & 0xff) / 255;
		const g = ((colorHex >> 8)  & 0xff) / 255;
		const b = ( colorHex        & 0xff) / 255;
		const color = new Cesium.Color(r, g, b, 0.9);

		this.entity = viewer.entities.add({
			polyline: {
				positions: new Cesium.CallbackProperty(() => this.positions, false),
				width: 3,
				material: new Cesium.PolylineGlowMaterialProperty({
					glowPower: 0.25,
					color,
				}),
				arcType: Cesium.ArcType.NONE,
				clampToGround: false,
			},
		});
	}

	/** 매 프레임 또는 step마다 호출 */
	update(lon, lat, alt) {
		const pos = Cesium.Cartesian3.fromDegrees(lon, lat, alt);

		// 첫 점이거나 30m 이상 이동 시 추가
		if (!this.lastPos ||
			Cesium.Cartesian3.distanceSquared(this.lastPos, pos) >= SAMPLE_DIST_SQ) {
			this.lastPos = pos;
			this.positions.push(pos);
			if (this.positions.length > this.maxPoints) {
				this.positions.shift();
			}
		}
	}

	setVisible(v) {
		if (this.entity) this.entity.show = v;
	}

	dispose() {
		if (this.entity) {
			this.viewer.entities.remove(this.entity);
			this.entity = null;
		}
		this.positions = [];
	}
}
