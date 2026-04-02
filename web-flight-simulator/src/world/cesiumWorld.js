import * as Cesium from 'cesium';

Cesium.Ion.defaultAccessToken = import.meta.env.VITE_CESIUM_TOKEN;

let viewer;
let miniViewer;
let pauseMiniViewer;

export function initCesium() {
	viewer = new Cesium.Viewer("cesiumContainer", {
		terrain: Cesium.Terrain.fromWorldTerrain(),
		timeline: false,
		animation: false,
		baseLayerPicker: false,
		geocoder: false,
		homeButton: false,
		infoBox: false,
		sceneModePicker: false,
		selectionIndicator: false,
		navigationHelpButton: false,
		fullscreenButton: false,
		shouldAnimate: false,
	});

	miniViewer = new Cesium.Viewer("minimapCesium", {
		terrain: null,
		timeline: false,
		animation: false,
		baseLayerPicker: false,
		geocoder: false,
		homeButton: false,
		infoBox: false,
		sceneModePicker: false,
		selectionIndicator: false,
		navigationHelpButton: false,
		fullscreenButton: false,
		shouldAnimate: false,
		skyBox: false,
		skyAtmosphere: false,
		contextOptions: {
			webgl: {
				preserveDrawingBuffer: true
			}
		}
	});

	pauseMiniViewer = new Cesium.Viewer("pauseMinimapCesium", {
		terrain: null,
		timeline: false,
		animation: false,
		baseLayerPicker: false,
		geocoder: false,
		homeButton: false,
		infoBox: false,
		sceneModePicker: false,
		selectionIndicator: false,
		navigationHelpButton: false,
		fullscreenButton: false,
		shouldAnimate: false,
		skyBox: false,
		skyAtmosphere: false,
		contextOptions: {
			webgl: {
				preserveDrawingBuffer: true
			}
		}
	});

	[viewer, miniViewer, pauseMiniViewer].forEach(v => {
		v.scene.requestRenderMode = false;
		v.scene.maximumRenderTimeChange = 0;
		v.scene.globe.maximumScreenSpaceError = 2;
		v.resolutionScale = 0.75;

		v.scene.screenSpaceCameraController.enableRotate = false;
		v.scene.screenSpaceCameraController.enableTranslate = false;
		v.scene.screenSpaceCameraController.enableZoom = false;
		v.scene.screenSpaceCameraController.enableTilt = false;
		v.scene.screenSpaceCameraController.enableLook = false;

		v.scene.screenSpaceCameraController.maximumZoomDistance = 25000000;

		v.scene.globe.tileCacheSize = 2048;
		v.scene.globe.preloadAncestors = true;
		v.scene.globe.preloadSiblings = true;
		v.scene.globe.loadingDescendantLimit = 20;

		v.scene.globe.skipLevelOfDetail = true;
		v.scene.globe.baseScreenSpaceError = 1024;
		v.scene.globe.skipScreenSpaceErrorFactor = 16;
		v.scene.globe.skipLevels = 1;

		v._cesiumWidget._creditContainer.style.display = "none";
	});

	[miniViewer, pauseMiniViewer].forEach(v => {
		v.scene.globe.enableLighting = false;
		v.scene.globe.showGroundAtmosphere = false;
		v.scene.fog.enabled = false;
		v.scene.highDynamicRange = false;
		v.scene.postProcessStages.fxaa.enabled = false;
		v.resolutionScale = 1.0;
		v.scene.globe.maximumScreenSpaceError = 2;
		v.scene.globe.baseColor = Cesium.Color.BLACK;
		if (v.scene.skyAtmosphere) v.scene.skyAtmosphere.show = false;
	});

	viewer.scene.globe.enableLighting = true;
	viewer.scene.highDynamicRange = true;
	viewer.scene.postProcessStages.fxaa.enabled = true;
	viewer.scene.skyAtmosphere = new Cesium.SkyAtmosphere();

	viewer.scene.fog.enabled = true;
	viewer.scene.fog.density = 0.0001;

	// 메인 뷰어 고화질 설정 (1.0 = 기본 해상도, 로딩 속도 유지)
	viewer.resolutionScale = 1.0;
	viewer.scene.globe.maximumScreenSpaceError = 2;

	setControlsEnabled(false);

	return viewer;
}

export function setRenderOptimization(isMenu) {
	if (!viewer || !miniViewer || !pauseMiniViewer) return;

	[viewer, miniViewer, pauseMiniViewer].forEach(v => {
		v.scene.requestRenderMode = !isMenu;
		v.scene.maximumRenderTimeChange = !isMenu ? Infinity : 0;
	});
}

export function setControlsEnabled(enabled) {
	if (!viewer) return;
	const ctrl = viewer.scene.screenSpaceCameraController;
	ctrl.enableRotate = enabled;
	ctrl.enableTranslate = enabled;
	ctrl.enableZoom = enabled;
	ctrl.enableTilt = enabled;
	ctrl.enableLook = enabled;
}

export function setCameraToPlane(lon, lat, alt, heading, pitch, roll, thirdPerson = false) {
	if (!viewer) return;

	let destLon = lon, destLat = lat, destAlt = alt, destPitch = pitch;

	if (thirdPerson) {
		const DIST_BACK = 500;  // 항공기 뒤쪽 오프셋 (m)
		const HEIGHT_UP  = 80;  // 위쪽 오프셋 (m)
		const headingRad = Cesium.Math.toRadians(heading);
		const cosLat     = Math.cos(Cesium.Math.toRadians(lat));
		destLon  = lon - Math.sin(headingRad) * DIST_BACK / (111320 * cosLat);
		destLat  = lat - Math.cos(headingRad) * DIST_BACK / 111320;
		destAlt  = alt + HEIGHT_UP;
		destPitch = pitch - Math.atan2(HEIGHT_UP, DIST_BACK) * 180 / Math.PI;
	}

	viewer.camera.setView({
		destination: Cesium.Cartesian3.fromDegrees(destLon, destLat, destAlt),
		orientation: {
			heading: Cesium.Math.toRadians(heading),
			pitch: Cesium.Math.toRadians(destPitch),
			roll: Cesium.Math.toRadians(roll)
		}
	});

	viewer.scene.requestRender();
}

/**
 * 양측 기체를 동시에 볼 수 있는 오버뷰 카메라.
 * @param {{ lon, lat, alt }} blue
 * @param {{ lon, lat, alt }} red
 */
export function setOverviewCamera(blue, red) {
	if (!viewer) return;
	const midLon = (blue.lon + red.lon) / 2;
	const midLat = (blue.lat + red.lat) / 2;
	const midAlt = Math.max(blue.alt, red.alt);
	const cosLat = Math.cos(Cesium.Math.toRadians(midLat));
	const dx = (blue.lon - red.lon) * 111320 * cosLat;
	const dy = (blue.lat - red.lat) * 111320;
	const dist = Math.sqrt(dx * dx + dy * dy);
	const camAlt = midAlt + Math.max(dist * 0.6, 1500);
	// bearing from red → blue so camera faces the engagement from the side
	const bearing = Math.atan2(dx, dy) * 180 / Math.PI;
	viewer.camera.setView({
		destination: Cesium.Cartesian3.fromDegrees(midLon, midLat, camAlt),
		orientation: {
			heading: Cesium.Math.toRadians(bearing + 180),
			pitch: Cesium.Math.toRadians(-35),
			roll: 0,
		},
	});
	viewer.scene.requestRender();
}

export function setMinimapCamera(lon, lat, altitude, heading) {
	if (!miniViewer) return;

	if (miniViewer.canvas.width === 0 || miniViewer.canvas.height === 0) {
		return;
	}

	miniViewer.camera.setView({
		destination: Cesium.Cartesian3.fromDegrees(lon, lat, altitude),
		orientation: {
			heading: Cesium.Math.toRadians(heading),
			pitch: Cesium.Math.toRadians(-90),
			roll: 0
		}
	});

	miniViewer.scene.requestRender();
}

export function setPauseMinimapCamera(lon, lat, altitude, heading) {
	if (!pauseMiniViewer) return;

	if (pauseMiniViewer.canvas.width === 0 || pauseMiniViewer.canvas.height === 0) {
		return;
	}

	pauseMiniViewer.camera.setView({
		destination: Cesium.Cartesian3.fromDegrees(lon, lat, altitude),
		orientation: {
			heading: Cesium.Math.toRadians(heading),
			pitch: Cesium.Math.toRadians(-90),
			roll: 0
		}
	});

	pauseMiniViewer.scene.requestRender();
}

export function getViewer() {
	return viewer;
}

export function getMiniViewer() {
	return miniViewer;
}

export function getPauseMiniViewer() {
	return pauseMiniViewer;
}
