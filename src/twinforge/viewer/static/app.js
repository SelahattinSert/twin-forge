import * as THREE from 'three';
import { OrbitControls } from '/vendor/OrbitControls.js';
import { frameSelection, visiblePoint } from '/measurement-state.js';
import { calibrationEligibility, formatCalibrationReport, resetReferenceState, selectWorkspaceStep } from '/workspace-ui.js';
import { imageTransform, ImageLoadGate, matchingSelections } from '/image-selection.js';
import { ImageEditor, annotatePhoto, drawOverlay } from '/image-editor.js';
import { measurementSummary, calibrationSummary } from '/result-summary.js';
import { sceneFetch as fetch, sceneContext, saveView, loadView } from '/scene-client.js';
import { buildCameraPath, disposeGeometryGroup } from '/camera-path.js';
import { captureView, restoreCamera } from '/view-state.js';
import { makeClipBox, boxPlanes, focusPoint, CameraTimeline } from '/scene-exploration.js';
import { ExplorationUI } from '/exploration-ui.js';
import { composeSnapshot } from '/scene-snapshot.js';
import { SourcePreview, sourcePreviewInfo } from '/source-preview.js';
import { HoverIndex } from '/hover-index.js';
import { buildCameraMarkers } from '/camera-markers.js';

const byId = id => document.getElementById(id);
const started = performance.now();
const viewport = byId('viewport');
let renderer, camera, controls, world, cloud, current, metadata, selectedFrame;
let preview, bounds, cameraGroup, cameraPath, cameraTargets = [], requestGeneration = 0;
let measurement, measurementLines, pickMode = null, endpointPicks = [];
let visibility = { hidden_frame_ids: [], hidden_rois: [] };
let sceneVariant = 'source', calibrationScalar = 1;
let referenceGeneration = 0, sceneCopyGeneration = 0;
let workspace = { loading: false, derivedAvailable: false };
let imageEditor, correction = null, submissionKey = null, submitting = false;
let mutationTail = Promise.resolve(), measurementOperation = 0, acceptedMeasurementOperation = 0;
let photoCleanups = [];
let animationFrame, disposed = false;
let exploration, timeline, clipVolume = null, clipOutline;
let inspectTimer;
let sourcePreview, cameraIconTexture;
const sourceLoadGate = new ImageLoadGate();
const raycaster = new THREE.Raycaster();
const pointer = new THREE.Vector2();

function calibrationState() {
  return { ...workspace, loading: workspace.loading || workspace.calibrating, sceneVariant, measurement, referenceId: byId('reference-id').value,
    quantity: byId('quantity').value, physicalLength: byId('physical-length').value };
}

function updateCalibration() {
  const result = calibrationEligibility(calibrationState());
  byId('calibrate').disabled = !result.eligible;
  byId('calibration-eligibility').textContent = result.reason;
  byId('calibration-reference').textContent = measurement ? `${measurement.read_only ? 'Archived reference' : 'Active reference'}: ${measurement.record.reference_id}` : 'No active reference';
}

function clearEndpointPicks(message = 'No endpoints selected. Choose a picking method to begin.') {
  endpointPicks = []; pickMode = null;
  submissionKey = null; correction = null;
  imageEditor?.cancel();
  byId('correction-panel').hidden = true;
  byId('save-observation').disabled = true;
  byId('correspondence-reviewed').checked = false;
  byId('endpoint-status').textContent = message;
  if (metadata) drawSourceSelections();
}

function clearActiveReference(next = {}) {
  referenceGeneration++;
  const previousMeasurement = measurement;
  const state = resetReferenceState(calibrationState(), next);
  measurement = state.measurement;
  byId('reference-id').value = state.referenceId;
  byId('quantity').value = state.quantity;
  byId('physical-length').value = state.physicalLength;
  byId('saved-measurements').value = '';
  byId('archived-measurements').value = '';
  byId('reference-status').textContent = 'New reference';
  byId('measurement-name').value = '';
  byId('measurement-summary').textContent = 'Select two points on a source photo.';
  byId('observation-list').replaceChildren();
  byId('observation-history').replaceChildren('No corrections.');
  photoCleanups.forEach(cleanup => cleanup()); photoCleanups = [];
  byId('measurement-evidence').textContent = 'No examined reference. Insufficient evidence.';
  clearEndpointPicks();
  if (measurementLines) {
    world.remove(measurementLines);
    for (const line of measurementLines.children) { line.geometry.dispose(); line.material.dispose(); }
    measurementLines = null;
  }
  byId('reference-id').disabled = false; byId('quantity').disabled = false;
  byId('measurement-name').disabled = false;
  updateCalibration();
  if (metadata && previousMeasurement?.read_only) selectFrame(selectedFrame?.frame_id ?? null);
  byId('pick-3d').disabled = sceneVariant !== 'source' || workspace.loading;
  if (current && previousMeasurement && byId('color-mode').value === 'evidence') display(current, byId('view-label').textContent);
}

function imageContext() {
  return { frame: selectedFrame?.frame_id, reference: byId('reference-id').value,
    generation: referenceGeneration, copy: sceneCopyGeneration };
}

function enqueueMeasurementMutation(value, generation, copy) {
  const request = mutationTail.then(() => {
    if (generation !== referenceGeneration || copy !== sceneCopyGeneration) return null;
    return postWorkspace('/api/measurements',value);
  });
  mutationTail = request.catch(() => {});
  return request;
}

function confirmImageSelection(points, context, intent = null) {
  if (intent && (intent.id !== correction?.id || intent.revision !== correction?.revision)) byId('correction-reason').value = '';
  correction = intent;
  byId('correction-panel').hidden = !correction;
  if (correction) byId('correction-status').textContent = `Correcting saved observation: revision ${correction.revision} → ${correction.revision + 1}. Supply a reason before saving; the prior revision remains in history.`;
  endpointPicks = points.map(sourcePixel => ({sourcePixel,frameId:context.frame})); pickMode = 'image';
  submissionKey = null; byId('correspondence-reviewed').checked = false;
  byId('endpoint-status').textContent = 'Selection confirmed. Review A/B and identify physical correspondence, then Add observation.';
  byId('save-observation').disabled = false; drawSourceSelections();
}

function drawSourceSelections() {
  const image = byId('source-image'), svg = byId('source-overlay');
  svg.replaceChildren();
  if (!selectedFrame || image.hidden || !image.naturalWidth || !image.clientWidth) return;
  const selections = matchingSelections(measurement?.record.observations || [], selectedFrame.frame_id).map(item => item.source_pixels);
  if (endpointPicks.length && endpointPicks.every(item => item.frameId === selectedFrame.frame_id && item.sourcePixel)) selections.push(endpointPicks.map(item => item.sourcePixel));
  svg.setAttribute('viewBox', `0 0 ${image.clientWidth} ${image.clientHeight}`);
  drawOverlay(svg, selections, imageTransform(image.naturalWidth,image.naturalHeight,image.clientWidth,image.clientHeight));
}

function previousObservation() {
  const item = [...(measurement?.record.observations || [])].reverse().find(item => item.source_pixels && item.frame_id !== selectedFrame?.frame_id);
  const frame = item && metadata.frames.find(frame => frame.frame_id === item.frame_id);
  return frame ? { frame, points: item.source_pixels } : null;
}

function startMeasurement() {
  clearActiveReference({ referenceId: `measurement-${crypto.randomUUID()}` });
  byId('measurement-name').value = `Measurement ${Number(metadata?.reference_count || 0) + 1}`;
  byId('measurement-name').focus();
}

function renderObservations(value) {
  photoCleanups.forEach(cleanup => cleanup()); photoCleanups = [];
  const list = byId('observation-list'); list.replaceChildren();
  const cardFor = (item, index, history = false) => {
    const card = document.createElement('article'); card.className = 'observation-card';
    const title = document.createElement('p');
    title.textContent = `Observation ${index + 1} · Frame ${item.frame_id} · revision ${item.revision || 1}${history ? ' · superseded' : ''}`;
    card.append(title);
    if (item.correction_reason) { const reason = document.createElement('p'); reason.textContent = `Correction: ${item.correction_reason}`; card.append(reason); }
    const frame = metadata.frames.find(frame => frame.frame_id === item.frame_id);
    if (frame && item.source_pixels) {
      const photo = document.createElement('div'); card.append(photo);
      photoCleanups.push(annotatePhoto(photo,frame.image_url,item.source_pixels,`Observation ${index + 1}, frame ${item.frame_id}, endpoints A and B`));
      const replay = document.createElement('button'); replay.textContent = 'Replay photo';
      replay.onclick = () => { selectFrame(frame.frame_id); imageEditor.open(frame,item.source_pixels,null,true); }; card.append(replay);
      if (!history && !value.read_only && sceneVariant === 'source') {
        const correct = document.createElement('button'); correct.textContent = 'Correct observation';
        correct.onclick = () => {
          selectFrame(frame.frame_id);
          const intent = { id: item.observation_id || `legacy-${index + 1}`, revision: item.revision || 1 };
          imageEditor.open(frame,item.source_pixels,previousObservation(),false,intent);
        }; card.append(correct);
      }
    } else { const note = document.createElement('p'); note.textContent = 'Photo replay unavailable: no recorded source pixels or matching source photo. Original point identities remain in Technical details.'; card.append(note); }
    return card;
  };
  value.record.observations.forEach((item,index) => list.append(cardFor(item,index)));
  const history = byId('observation-history'); history.replaceChildren();
  (value.record.observation_history || []).forEach((item,index) => history.append(cardFor(item,index,true)));
  if (!history.childNodes.length) history.textContent = 'No corrections.';
}

async function fetchChecked(url) {
  const response = await fetch(url);
  if (!response.ok) throw new Error(await responseError(response));
  return response;
}

async function loadBundle(url) {
  const buffer = await (await fetchChecked(url)).arrayBuffer();
  if (new TextDecoder().decode(new Uint8Array(buffer, 0, 4)) !== 'TFP1') throw new Error('Invalid preview response');
  const size = new DataView(buffer).getUint32(4, true);
  const header = JSON.parse(new TextDecoder().decode(new Uint8Array(buffer, 8, size)));
  const types = { '<f4': Float32Array, '|u1': Uint8Array, '<u8': BigUint64Array, '<u4': Uint32Array, '<i8': BigInt64Array };
  const columns = {};
  for (const [name, info] of Object.entries(header.columns)) {
    const Type = types[info.dtype];
    if (!Type) throw new Error(`Unsupported point column: ${info.dtype}`);
    columns[name] = new Type(buffer, info.offset, info.bytes / Type.BYTES_PER_ELEMENT);
  }
  return { header, ...columns };
}

function showError(error) {
  const panel = byId('loading'); panel.hidden = false; panel.classList.add('error');
  const heading = document.createElement('h2'); heading.textContent = 'This scene could not be opened';
  const message = document.createElement('p'); message.textContent = error.message;
  const help = document.createElement('p'); help.textContent = 'Return to Scenes to check the source or restore a saved package. If this happened during an interrupted request, try again.';
  const actions = document.createElement('div'); actions.className = 'buttons';
  const back = document.createElement('a'); back.href = '/'; back.className = 'back-link'; back.textContent = 'Back to scenes';
  const retry = document.createElement('button'); retry.textContent = 'Try again'; retry.onclick = () => window.location.reload();
  actions.append(back, retry); panel.replaceChildren(heading, message, help, actions);
  console.error(error);
}

function display(bundle, label, fit = false) {
  sourcePreview?.hide();
  if (cloud) { world.remove(cloud); cloud.geometry.dispose(); cloud.material.dispose(); }
  current = bundle;
  const geometry = new THREE.BufferGeometry();
  geometry.setAttribute('position', new THREE.BufferAttribute(bundle.xyz, 3));
  geometry.setAttribute('color', new THREE.BufferAttribute(bundle.rgb, 3, true));
  if (byId('color-mode').value === 'evidence') {
    const colors = new Uint8Array(bundle.header.count * 3).fill(130);
    if (measurement) {
      const endpoints = new Set(measurement.record.observations.flatMap(item => item.point_indices.map(String)));
      const color = measurement.evidence.state === 'conflicting_observations' ? [255, 92, 92] : measurement.evidence.calibration_qualified ? [90, 205, 140] : [235, 185, 85];
      for (let i = 0; i < bundle.header.count; i++) if (endpoints.has(bundle.point_indices[i].toString())) colors.set(color, i * 3);
    }
    geometry.setAttribute('color', new THREE.BufferAttribute(colors, 3, true));
  }
  // Keep all frame rows in memory; render only explicitly valid finite points.
  const visible = [];
  const box = new THREE.Box3();
  const point = new THREE.Vector3();
  for (let i = 0; i < bundle.header.count; i++) {
    if (bundle.valid[i] && visiblePoint(bundle.frame_ids?.[i] ?? null, bundle.pixel_ids?.[i] ?? null, visibility, metadata.pixel_transforms)) {
      point.fromArray(bundle.xyz, i * 3);
      if (Number.isFinite(point.x) && Number.isFinite(point.y) && Number.isFinite(point.z) && (!clipVolume || clipVolume.containsPoint(point))) {
        visible.push(i); box.expandByPoint(point);
      }
    }
  }
  geometry.setIndex(visible);
  if (box.isEmpty()) box.set(new THREE.Vector3(-1, -1, -1), new THREE.Vector3(1, 1, 1));
  geometry.boundingBox = box;
  geometry.boundingSphere = box.getBoundingSphere(new THREE.Sphere());
  cloud = new THREE.Points(geometry, new THREE.PointsMaterial({ size: Number(byId('point-size').value), vertexColors: true, sizeAttenuation: false }));
  world.add(cloud);
  byId('view-label').textContent = label;
  const note = bundle.header.frame_id === null ? 'sampled' : 'full frame';
  byId('display-count').textContent = `${visible.length.toLocaleString()} rendered / ${bundle.header.count.toLocaleString()} ${note}`;
  if (fit) fitScene();
}

function fitScene() {
  const sphere = bounds.getBoundingSphere(new THREE.Sphere());
  const radius = Math.max(sphere.radius, 0.1);
  controls.target.copy(sphere.center);
  camera.position.copy(sphere.center).add(new THREE.Vector3(1, -1.4, 0.9).normalize().multiplyScalar(radius * 2.7));
  camera.near = Math.max(radius / 10000, 0.00001);
  camera.far = radius * 1000;
  controls.maxDistance = radius * 200;
  camera.updateProjectionMatrix(); controls.update();
}

function resetControlsForUp() {
  // OrbitControls derives its orbit-axis transform when it is constructed.
  const target = controls.target.clone();
  const maxDistance = controls.maxDistance;
  controls.dispose();
  controls = new OrbitControls(camera, renderer.domElement);
  controls.enableDamping = !matchMedia('(prefers-reduced-motion: reduce)').matches;
  controls.target.copy(target);
  controls.maxDistance = maxDistance;
}

function cameraPose(record) {
  return record.camera_to_world ? new THREE.Matrix4().set(...record.camera_to_world.flat()) : null;
}

function addCameras() {
  cameraGroup = new THREE.Group();
  const icons = buildCameraMarkers(metadata.cameras, cameraIconTexture);
  cameraGroup.add(icons); cameraGroup.userData.iconTargets = icons.children;
  const radius = bounds.getBoundingSphere(new THREE.Sphere()).radius;
  const depth = Math.max(radius * 0.035, 0.015);
  for (const record of metadata.cameras) {
    const pose = cameraPose(record);
    if (!pose) continue;
    const origin = new THREE.Vector3().setFromMatrixPosition(pose);
    const k = record.intrinsics;
    const width = record.image_width, height = record.image_height;
    let corners;
    if (k && width && height && k[0][0] > 0 && k[1][1] > 0) {
      corners = [[0, 0], [width, 0], [width, height], [0, height]].map(([u, v]) => new THREE.Vector3((u - k[0][2]) / k[0][0] * depth, (v - k[1][2]) / k[1][1] * depth, depth).applyMatrix4(pose));
    } else {
      // A pose marker is still useful when intrinsics are absent.
      corners = [[-1, -1], [1, -1], [1, 1], [-1, 1]].map(([x, y]) => new THREE.Vector3(x * depth * .5, y * depth * .5, depth).applyMatrix4(pose));
    }
    const segments = [];
    for (let i = 0; i < 4; i++) segments.push(origin, corners[i], corners[i], corners[(i + 1) % 4]);
    const frustum = new THREE.LineSegments(new THREE.BufferGeometry().setFromPoints(segments), new THREE.LineBasicMaterial({ color: 0x7ee0cd }));
    frustum.userData.frameId = record.frame_id;
    cameraTargets.push(frustum); cameraGroup.add(frustum);
  }
  cameraPath = buildCameraPath(metadata.cameras, radius);
  cameraPath.visible = byId('show-path').checked;
  cameraGroup.visible = byId('show-cameras').checked;
  byId('show-path').disabled = cameraPath.userData.sampleCount < 2;
  const pathInfo = cameraPath.userData;
  byId('path-status').textContent = pathInfo.sampleCount < 2 ? 'Not enough saved camera poses to show a path.' :
    `${pathInfo.sampleCount} camera positions · start: frame ${pathInfo.startFrameId} · end: frame ${pathInfo.endFrameId}.${pathInfo.missingPoseCount ? ' Missing poses leave breaks in the path.' : ''} Straight links join selected views; movement between them is unknown.`;
  world.add(cameraGroup, cameraPath);
  raycaster.params.Points.threshold = depth * .25;
  raycaster.params.Line.threshold = depth * .25;
}

function selectFrame(frameId) {
  sourcePreview?.hide();
  clearTimeout(inspectTimer);
  timeline?.sync(frameId);
  const compatible3dPick = pickMode === '3d' && endpointPicks.length > 0 && endpointPicks.every(item => item.frameId === frameId);
  if (selectedFrame?.frame_id !== frameId && !compatible3dPick) clearEndpointPicks('Choose Select A/B to measure this photo.');
  imageEditor?.cancel();
  sourceLoadGate.cancel();
  selectedFrame = metadata.frames.find(frame => frame.frame_id === frameId);
  byId('frame-select').value = selectedFrame ? String(frameId) : '';
  for (const target of cameraTargets) target.material.color.setHex(target.userData.frameId === frameId ? 0xffba69 : 0x7ee0cd);
  const record = metadata.cameras.find(item => item.frame_id === frameId);
  byId('camera-view').disabled = !record?.camera_to_world;
  byId('frame-points').disabled = !selectedFrame || !metadata.point_provenance_available;
  byId('pick-image').disabled = workspace.loading || measurement?.read_only || sceneVariant === 'derived' || !selectedFrame || !metadata.pixel_provenance_available || !metadata.pixel_transforms.some(item => item.frame_id === frameId);
  byId('hide-frame').disabled = !selectedFrame;
  byId('hide-roi').disabled = byId('pick-image').disabled;
  byId('image-selection-reason').textContent = workspace.loading ? 'Scene is loading. Wait before selecting endpoints.' : measurement?.read_only ? 'Saved source observations are read-only in this exported copy.' : sceneVariant === 'derived' ? 'Switch to source geometry to select endpoints.' : !selectedFrame ? 'Choose a source frame to select image endpoints.' : byId('pick-image').disabled ? 'Verified image-to-point mapping is unavailable for this frame. No nearby surface will be substituted.' : 'Select A/B opens a large photo. Confirm your selection, then Add observation.';
  byId('source-overlay').replaceChildren();
  if (!selectedFrame) {
    byId('source-image').hidden = true;
    byId('source-image').removeAttribute('src');
    byId('image-link').removeAttribute('href');
    byId('frame-details').textContent = 'Choose a source frame.';
    byId('image-note').textContent = 'No source frame selected.';
    return;
  }
  const image = byId('source-image');
  image.hidden = true;
  image.alt = `Source frame ${frameId} at ${selectedFrame.timestamp_seconds.toFixed(2)} seconds`;
  byId('image-link').href = selectedFrame.image_url;
  const modelSize = record?.image_width && record?.image_height ? `${record.image_width} × ${record.image_height}` : 'unrecorded';
  byId('frame-details').textContent = `Frame ${frameId} · ${selectedFrame.timestamp_seconds.toFixed(2)}s · model resolution ${modelSize}`;
  const photoContext = () => ({frame:selectedFrame?.frame_id,copy:sceneCopyGeneration});
  const context = photoContext(), token = sourceLoadGate.begin(context), frame = selectedFrame;
  const loader = new Image();
  loader.onload = () => {
    if (!sourceLoadGate.valid(token,photoContext())) return;
    image.onload = () => { if (sourceLoadGate.valid(token,photoContext())) drawSourceSelections(); };
    image.src = frame.image_url; image.hidden = false;
    byId('image-note').textContent = `Saved image: ${loader.naturalWidth} × ${loader.naturalHeight}. Source → model pixel mapping is ${metadata.source_to_model_mapping_available ? 'recorded in the artifact' : 'unavailable'}.`;
  };
  loader.onerror = () => { if (sourceLoadGate.valid(token,photoContext())) byId('image-note').textContent = 'Source photo is unavailable.'; };
  loader.src = frame.image_url;
}

function lookFromCamera() {
  sourcePreview?.hide();
  const record = metadata.cameras.find(item => item.frame_id === selectedFrame?.frame_id);
  const pose = record && cameraPose(record);
  if (!pose) return;
  camera.position.setFromMatrixPosition(pose);
  // Saved camera-local axes follow OpenCV: +Z forward and +Y down.
  const forward = new THREE.Vector3(0, 0, 1).transformDirection(pose);
  camera.up.copy(new THREE.Vector3(0, -1, 0).transformDirection(pose));
  resetControlsForUp();
  controls.target.copy(camera.position).addScaledVector(forward, Math.max(bounds.getBoundingSphere(new THREE.Sphere()).radius, .1));
  controls.update();
}

function inspectClick(event) {
  const rect = renderer.domElement.getBoundingClientRect();
  pointer.set((event.clientX - rect.left) / rect.width * 2 - 1, -(event.clientY - rect.top) / rect.height * 2 + 1);
  raycaster.setFromCamera(pointer, camera);
  if (cameraGroup.visible) {
    const hit = raycaster.intersectObjects([...(cameraGroup.userData.iconTargets ?? []), ...cameraTargets]).find(hit => !clipVolume || clipVolume.containsPoint(hit.point));
    if (hit) { selectFrame(hit.object.userData.frameId); return; }
  }
  const hit = visibleCloudHit();
  if (!hit) return;
  const i = hit.index;
  const xyz = Array.from(current.xyz.subarray(i * 3, i * 3 + 3));
  const frameId = current.frame_ids ? current.frame_ids[i] : null;
  let text = `PLY index ${current.point_indices[i].toString()} · XYZ (${xyz.map(value => value.toFixed(5)).join(', ')}) · source frame ${frameId ?? 'unavailable'} · valid ${Boolean(current.valid[i])}`;
  if (current.confidence) text += ` · raw confidence ${current.confidence[i].toPrecision(5)}`;
  if (current.pixel_ids) text += ` · pixel ID ${current.pixel_ids[i].toString()}`;
  byId('point-details').textContent = text;
  if (pickMode === '3d') addEndpoint({ index: Number(current.point_indices[i]), frameId });
  if (frameId !== null) selectFrame(frameId);
}

function visibleCloudHit() {
  return raycaster.intersectObject(cloud).find(hit => {
    const i = hit.index, point = new THREE.Vector3().fromArray(current.xyz, i * 3);
    return current.valid[i] && (!clipVolume || clipVolume.containsPoint(point)) &&
      visiblePoint(current.frame_ids?.[i] ?? null, current.pixel_ids?.[i] ?? null, visibility, metadata.pixel_transforms);
  });
}

function focusAtPointer(event) {
  sourcePreview?.hide();
  if (workspace.loading || pickMode === '3d') return;
  const rect = renderer.domElement.getBoundingClientRect();
  pointer.set((event.clientX - rect.left) / rect.width * 2 - 1, -(event.clientY - rect.top) / rect.height * 2 + 1);
  raycaster.setFromCamera(pointer, camera);
  const hit = visibleCloudHit();
  if (!hit) { byId('focus-status').textContent = 'Double-click a visible point to focus.'; return; }
  const xyz = Array.from(current.xyz.subarray(hit.index * 3, hit.index * 3 + 3));
  focusPoint(camera, controls, xyz);
  byId('focus-status').textContent = 'Orbit center moved to this point. Viewing coordinates only; geometry is unchanged.';
}

function applyViewingClip() {
  if (!renderer || !world || !bounds || !exploration) return;
  clipVolume = exploration.enabled ? makeClipBox(bounds, exploration.ranges) : null;
  renderer.clippingPlanes = clipVolume ? boxPlanes(clipVolume) : [];
  if (clipOutline) { world.remove(clipOutline); disposeGeometryGroup(clipOutline); clipOutline = null; }
  if (clipVolume) {
    clipOutline = new THREE.Box3Helper(clipVolume, 0xe7c98a);
    world.add(clipOutline);
  }
  if (current) display(current, byId('view-label').textContent);
}

function setupExploration() {
  timeline = new CameraTimeline(byId, id => { if (!workspace.loading) selectFrame(id); }, () => { if (!workspace.loading) lookFromCamera(); });
  timeline.render(metadata);
  exploration = new ExplorationUI(byId, {
    clipChanged: applyViewingClip,
    captureView: () => {
      if (workspace.loading) throw new Error('Wait for the scene copy to finish loading.');
      return captureView(camera, controls, selectedFrame?.frame_id, exploration.enabled, exploration.ranges);
    },
    restoreView: value => {
      if (workspace.loading) throw new Error('Wait for the scene copy to finish loading.');
      restoreCamera(value, camera, controls); resetControlsForUp(); controls.target.fromArray(value.target); controls.update();
      selectFrame(metadata.frames.some(frame => frame.frame_id === value.frameId) ? value.frameId : null);
    },
    screenshot: (title, note) => {
      if (workspace.loading || !byId('loading').hidden) throw new Error('Wait for the scene to finish loading.');
      if (exploration.pendingClip !== null) { cancelAnimationFrame(exploration.pendingClip); exploration.pendingClip = null; applyViewingClip(); }
      const context = { captured_at: new Date().toISOString(), scene_name: metadata.name, scene_copy: sceneVariant,
        manifest_sha256: metadata.manifest_sha256, point_cloud_sha256: metadata.point_cloud_sha256,
        scale: metadata.scale, display_label: byId('view-label').textContent, display_count: byId('display-count').textContent,
        color_mode: byId('color-mode').value, selected_frame_id: selectedFrame?.frame_id ?? null,
        clip: { enabled: exploration.enabled, ranges: exploration.ranges.map(pair => [...pair]) }, hidden_frame_count: visibility.hidden_frame_ids.length,
        hidden_roi_count: visibility.hidden_rois.length, path_visible: cameraPath.visible, cameras_visible: cameraGroup.visible,
        reference_id: measurement?.record.reference_id ?? null };
      // Render and copy synchronously before WebGL may clear its drawing buffer.
      renderer.render(world, camera); return composeSnapshot(renderer.domElement, context, title, note);
    }
  });
  exploration.setScene(metadata, sceneContext?.apiPrefix, sceneVariant);
}

function previewHit(event, cameraOnly = false) {
  if (workspace.loading || pickMode === '3d' || !cloud) return null;
  const rect = renderer.domElement.getBoundingClientRect();
  pointer.set((event.clientX - rect.left) / rect.width * 2 - 1, -(event.clientY - rect.top) / rect.height * 2 + 1);
  raycaster.setFromCamera(pointer, camera);
  const targets = [...(cameraGroup.visible ? [...(cameraGroup.userData.iconTargets ?? []), ...(cameraOnly ? [] : cameraTargets)] : []),
    ...(cameraPath.visible ? cameraPath.children.filter(node => node.userData.kind === 'camera_path_node') : [])];
  const cameraHit = raycaster.intersectObjects(targets, false).find(hit => !clipVolume || clipVolume.containsPoint(hit.point));
  let info, position;
  if (cameraHit) {
    const frameId = cameraHit.object.userData.frameId;
    info = sourcePreviewInfo(metadata, { kind: 'camera', frameId });
    const pose = metadata.cameras.find(record => record.frame_id === frameId)?.camera_to_world;
    position = pose ? new THREE.Vector3(pose[0][3], pose[1][3], pose[2][3]) : cameraHit.point.clone();
  } else {
    if (cameraOnly) return null;
    const indexer = sourcePreview.pointIndex ??= new HoverIndex();
    if (!indexer.prepare(cloud, camera, rect.width, rect.height)) return { pending: true };
    const index = indexer.query(event.clientX - rect.left, event.clientY - rect.top,
      Math.max(4, Number(byId('point-size').value) / 2));
    if (index === null) return null;
    const xyz = new THREE.Vector3().fromArray(current.xyz, index * 3);
    if (!current.valid[index] || (clipVolume && !clipVolume.containsPoint(xyz)) ||
      !visiblePoint(current.frame_ids?.[index] ?? null, current.pixel_ids?.[index] ?? null, visibility, metadata.pixel_transforms)) return null;
    info = sourcePreviewInfo(metadata, { kind: 'point', frameId: current.frame_ids?.[index] ?? null,
      pointIndex: current.point_indices[index].toString() });
    position = xyz;
  }
  const projected = position.project(camera);
  const anchor = projected.z >= -1 && projected.z <= 1 ? {
    clientX: rect.left + (projected.x + 1) / 2 * rect.width,
    clientY: rect.top + (1 - projected.y) / 2 * rect.height } : event;
  return { info, anchor };
}

function setupSourcePreview() {
  sourcePreview = new SourcePreview(byId, renderer.domElement, viewport, {
    // A dense surface below an icon must not immediately replace its popup.
    hit: point => previewHit(point, true),
    look: frameId => {
      if (workspace.loading || pickMode === '3d') return;
      selectFrame(frameId); lookFromCamera();
    }
  });
}

function addEndpoint(pick) {
  if (workspace.loading || sceneVariant !== 'source' || measurement?.read_only) return;
  if (endpointPicks.length === 2) endpointPicks = [];
  if (endpointPicks.length && endpointPicks[0].frameId !== pick.frameId) throw new Error('Choose both endpoints from one source frame. Save this observation before choosing another view.');
  endpointPicks.push(pick);
  submissionKey = null; byId('correspondence-reviewed').checked = false;
  byId('endpoint-status').textContent = endpointPicks.map((item, i) => `${i ? 'B' : 'A'}: frame ${item.frameId}, ${item.index === undefined ? `source pixel ${item.sourcePixel.map(value => value.toFixed(2)).join(', ')}` : `original PLY index ${item.index}`}`).join(' · ');
  byId('save-observation').disabled = endpointPicks.length !== 2;
  drawSourceSelections();
}

async function responseError(response) {
  if (response.headers?.get('Content-Type')?.includes('application/json')) {
    try { return (await response.json()).error?.message || 'The request could not be completed. Review your selection and retry.'; }
    catch { return 'The response was unavailable. Reopen the observation and retry.'; }
  }
  return response.text();
}

async function postWorkspace(path, value) {
  const response = await fetch(path, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(value) });
  if (!response.ok) throw new Error(await responseError(response));
  return response.json();
}

async function refreshMeasurements() {
  const generation = sceneCopyGeneration;
  const prefix = sceneVariant === 'derived' ? '/api/derived' : '/api';
  const ids = await (await fetchChecked('/api/measurements')).json();
  if (generation !== sceneCopyGeneration) return;
  const select = byId('saved-measurements');
  select.replaceChildren(new Option(ids.length ? 'Choose a saved reference' : 'No saved references yet', ''));
  for (const id of ids) select.append(new Option(metadata.measurement_names?.[id] || (measurement?.record.reference_id === id ? measurement.record.display_name || id : id.replace(/^measurement-[a-f0-9-]+$/,'Saved measurement')), id));
  if (measurement && !measurement.read_only) select.value = measurement.record.reference_id;
  const refreshedMetadata = await (await fetchChecked(`${prefix}/scene`)).json();
  if (generation !== sceneCopyGeneration) return;
  metadata = refreshedMetadata;
  for (const option of select.options || []) if (option.value && metadata.measurement_names?.[option.value]) option.textContent = metadata.measurement_names[option.value];
  showSceneStatus();
}

function showSceneStatus() {
  const displayed = byId('display-count')?.textContent || 'Loading…';
  const rows = [ ['Scale', metadata.scale.type], ['Saved observations', String(metadata.observation_count)], ['Saved references', String(metadata.reference_count)], ['Per-reference evidence', 'See individual saved measurements'], ['Use', metadata.usage_status], ['Original', `${metadata.original_point_count.toLocaleString()} points`], ['Displayed', displayed] ];
  byId('scene-status').replaceChildren();
  for (const [label, value] of rows) {
    const dt = document.createElement('dt'); dt.textContent = label;
    const dd = document.createElement('dd'); dd.textContent = value;
    if (label === 'Displayed') dd.id = 'display-count';
    byId('scene-status').append(dt, dd);
  }
}

function showMeasurement(value) {
  measurement = value;
  byId('reference-id').value = value.record.reference_id;
  byId('quantity').value = value.record.quantity;
  byId('measurement-name').value = value.record.display_name || value.record.reference_id;
  const option = [...(byId('saved-measurements').options || [])].find(option => option.value === value.record.reference_id);
  if (option) option.textContent = byId('measurement-name').value;
  byId('measurement-name').disabled = Boolean(value.read_only);
  byId('physical-length').value = '';
  byId('reference-id').disabled = Boolean(value.read_only);
  byId('quantity').disabled = true;
  byId('pick-3d').disabled = Boolean(value.read_only) || sceneVariant !== 'source' || workspace.loading;
  byId('reference-status').textContent = value.read_only ? 'Read-only archive' : 'Saved scene reference';
  byId('measurement-summary').textContent = measurementSummary(value);
  updateCalibration();
  selectFrame(selectedFrame?.frame_id ?? null);
  const evidence = value.evidence;
  const percent = value => value === null ? 'unavailable' : `${(value * 100).toFixed(2)}%`;
  const lines = [`${evidence.state} · ${evidence.observation_count} observations / ${evidence.distinct_view_count} nonduplicate views`, `Calibration selection: ${evidence.calibration_qualified ? 'qualified by engineering heuristics' : 'not qualified'}`, `Length spread: ${percent(evidence.length_spread_ratio)}`, `Corresponding endpoint XYZ spread / median length: ${percent(evidence.endpoint_spread_ratio)}`, 'Thresholds: length 5%; endpoints 10%; ±2-pixel P95−P5 span 10%.'];
  if (value.read_only) lines.unshift(`Read-only archived source observations · source manifest ${value.source_manifest_sha256} · source PLY ${value.source_point_cloud_sha256} · original XYZ retained; display scalar ${value.display_scalar} applied once. Active workspace measurements are separate.`);
  for (const [i, item] of value.record.observations.entries()) lines.push(`Frame ${item.frame_id}: ${item.length.toFixed(6)} scene units · original indices ${item.point_indices.join(', ')} · pixel provenance ${item.pixel_provenance} · neighborhood span / median segment ${percent(evidence.pixel_sensitivity_span_ratios[i])} (${item.sensitivity_complete ? 'complete' : 'incomplete'}) · raw confidence ${item.raw_confidence.join(', ')} · correspondence ${item.correspondence_state}`);
  lines.push(`Reasons: ${evidence.reasons.join(', ') || 'all bounded checks passed'}`, evidence.support_note);
  lines.unshift(`Reference ID: ${value.record.reference_id}`);
  lines.push('Full measurement and evidence records:', JSON.stringify(value,null,2));
  byId('measurement-evidence').textContent = lines.join('\n');
  renderObservations(value); drawSourceSelections();
  if (measurementLines) { world.remove(measurementLines); for (const line of measurementLines.children) { line.geometry.dispose(); line.material.dispose(); } }
  measurementLines = new THREE.Group();
  const displayScalar = value.read_only ? value.display_scalar : sceneVariant === 'derived' ? calibrationScalar : 1;
  for (const item of value.record.observations) measurementLines.add(new THREE.Line(new THREE.BufferGeometry().setFromPoints(item.xyz.map(xyz => new THREE.Vector3(...xyz).multiplyScalar(displayScalar))), new THREE.LineBasicMaterial({ color: evidence.state === 'conflicting_observations' ? 0xff5c5c : evidence.calibration_qualified ? 0x5acd8c : 0xebb955 })));
  world.add(measurementLines);
  display(current, byId('view-label').textContent);
}

async function saveVisibility() {
  visibility = await postWorkspace('/api/visibility', { hidden_frame_ids: visibility.hidden_frame_ids, hidden_rois: visibility.hidden_rois });
  byId('visibility-note').textContent = `${visibility.hidden_frame_ids.length} hidden views; ${visibility.hidden_rois.length} hidden ROIs. Manually hidden; geometry has not been corrected.`;
  display(current, byId('view-label').textContent);
}

async function init() {
  metadata = await (await fetchChecked('/api/scene')).json();
  visibility = await (await fetchChecked('/api/visibility')).json();
  byId('scene-name').textContent = metadata.name;
  if (typeof sceneContext !== 'undefined' && sceneContext) {
    byId('scenes-breadcrumb').hidden = false;
    byId('active-version').hidden = false;
    byId('active-version').textContent = `${metadata.version.label}${metadata.default_version_id === metadata.version.version_id ? ' · Default' : ''}`;
    const { mountVersionActions } = await import('/version-actions.js');
    await mountVersionActions(byId('version-actions'), metadata, { sceneId: sceneContext.sceneId,
      request: async (url, method = 'GET', value) => {
        const response = await fetch(url, { method, ...(value ? { headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(value) } : {}) });
        if (!response.ok) throw new Error('Operation unavailable. Check source availability and active processing, then retry.');
        return response.json();
      }, go: url => { window.location.href = url; } });
  }
  for (const step of ['inspect', 'measure', 'calibrate']) byId(`step-${step}`).onclick = () => selectWorkspaceStep(step, byId);
  document.title = `${metadata.name} — TwinForge`;
  showSceneStatus();
  byId('artifact-hash').textContent = `Manifest SHA-256: ${metadata.manifest_sha256}`;
  byId('pixel-note').textContent = metadata.pixel_provenance_available ? 'Pixel IDs are preserved as recorded.' : 'Pixel provenance is unavailable in this artifact. No image correspondence is inferred.';
  for (const frame of metadata.frames) {
    const option = document.createElement('option'); option.value = String(frame.frame_id);
    option.textContent = `Frame ${frame.frame_id} · ${frame.timestamp_seconds.toFixed(2)}s`;
    byId('frame-select').append(option);
  }
  try { renderer = new THREE.WebGLRenderer({ antialias: true }); }
  catch (cause) { throw new Error('The browser could not create the 3D view. Enable WebGL and hardware acceleration, or try another browser.', { cause }); }
  renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
  renderer.setClearColor(0x0b1117); viewport.append(renderer.domElement);
  world = new THREE.Scene(); camera = new THREE.PerspectiveCamera(50, 1, .001, 10000);
  camera.up.set(0, 0, 1); controls = new OrbitControls(camera, renderer.domElement);
  controls.enableDamping = !matchMedia('(prefers-reduced-motion: reduce)').matches;
  preview = await loadBundle('/api/preview');
  bounds = new THREE.Box3();
  for (let i = 0; i < preview.header.count; i++) bounds.expandByPoint(new THREE.Vector3().fromArray(preview.xyz, i * 3));
  if (bounds.isEmpty()) bounds.set(new THREE.Vector3(-1, -1, -1), new THREE.Vector3(1, 1, 1));
  cameraIconTexture = new THREE.TextureLoader().load('/camera-icon.svg');
  cameraIconTexture.colorSpace = THREE.SRGBColorSpace;
  display(preview, 'All source frames · deterministic preview', true); addCameras();
  setupExploration();
  setupSourcePreview();
  const resize = () => { sourcePreview?.hide(); const width = viewport.clientWidth, height = viewport.clientHeight; renderer.setSize(width, height); camera.aspect = width / height; camera.updateProjectionMatrix(); };
  new ResizeObserver(resize).observe(viewport); resize();
  new ResizeObserver(drawSourceSelections).observe(byId('source-image'));
  imageEditor = new ImageEditor(byId,imageContext,confirmImageSelection);
  const animate = () => { if (disposed) return; controls.update(); renderer.render(world, camera); animationFrame = requestAnimationFrame(animate); };
  animate();
  byId('loading').hidden = true;
  byId('timing').textContent = `First render: ${((performance.now() - started) / 1000).toFixed(2)}s · server preview preparation: ${metadata.preview_seconds.toFixed(2)}s`;
  byId('fit').onclick = () => { sourcePreview?.hide(); camera.up.set(0, 0, 1); resetControlsForUp(); fitScene(); };
  byId('all').onclick = () => { if (workspace.loading) return; requestGeneration++; byId('loading').hidden = true; display(preview, 'All source frames · deterministic preview'); };
  byId('point-size').oninput = event => { cloud.material.size = Number(event.target.value); byId('point-size-value').textContent = event.target.value; };
  byId('show-cameras').onchange = event => { cameraGroup.visible = event.target.checked; sourcePreview?.hide(); };
  byId('show-path').onchange = event => { cameraPath.visible = event.target.checked; sourcePreview?.hide(); };
  byId('frame-select').onchange = event => selectFrame(frameSelection(event.target.value));
  byId('pick-3d').onclick = () => { if (workspace.loading || sceneVariant !== 'source' || measurement?.read_only) return; clearEndpointPicks('Click endpoint A then B in the 3D view.'); pickMode = '3d'; };
  byId('pick-image').onclick = () => {
    if (byId('pick-image').disabled) return;
    if (!byId('reference-id').value) {
      byId('reference-id').value = `measurement-${crypto.randomUUID()}`;
      byId('measurement-name').value ||= `Measurement ${metadata.reference_count + 1}`;
    }
    imageEditor.open(selectedFrame,endpointPicks.filter(item => item.sourcePixel).map(item => item.sourcePixel),previousObservation(),false,correction);
  };
  byId('clear-picks').onclick = () => clearEndpointPicks('Endpoint picks cleared.');
  byId('correspondence-reviewed').onchange = () => { submissionKey = null; };
  byId('correction-reason').oninput = () => { submissionKey = null; };
  byId('save-observation').onclick = async () => {
    if (submitting || workspace.loading || sceneVariant !== 'source' || measurement?.read_only || endpointPicks.length !== 2) return;
    if (!byId('reference-id').value) { byId('reference-id').value = `measurement-${crypto.randomUUID()}`; byId('measurement-name').value ||= `Measurement ${metadata.reference_count + 1}`; }
    if (correction && !byId('correction-reason').value.trim()) { byId('endpoint-status').textContent = 'Enter a reason for this correction. The old revision will remain in history.'; byId('correction-reason').focus(); return; }
    const generation = referenceGeneration, copyGeneration = sceneCopyGeneration;
    const operation = ++measurementOperation;
    const value = { reference_id: byId('reference-id').value, display_name: byId('measurement-name').value, quantity: byId('quantity').value, correspondence_state: byId('correspondence-reviewed').checked ? 'identified' : 'unreviewed', idempotency_key: submissionKey ||= crypto.randomUUID() };
    if (correction) Object.assign(value,{correction_id:correction.id,expected_revision:correction.revision,correction_reason:byId('correction-reason').value.trim()});
    if (pickMode === 'image') { value.source_pixels = endpointPicks.map(item => item.sourcePixel); value.frame_id = endpointPicks[0].frameId; }
    else value.point_indices = endpointPicks.map(item => item.index);
    byId('save-observation').disabled = true;
    submitting = true;
    byId('endpoint-status').textContent = 'Saving observation…';
    try {
      const saved = await enqueueMeasurementMutation(value,generation,copyGeneration);
      if (!saved || generation !== referenceGeneration || copyGeneration !== sceneCopyGeneration) return;
      if (operation > acceptedMeasurementOperation) {
        acceptedMeasurementOperation = operation;
        const pendingName = byId('measurement-name').value;
        showMeasurement(saved);
        if (operation !== measurementOperation) byId('measurement-name').value = pendingName;
      }
      await refreshMeasurements();
      if (generation === referenceGeneration && copyGeneration === sceneCopyGeneration) clearEndpointPicks('Observation saved. Select another source view to compare the same endpoints.');
    } catch (error) { if (generation === referenceGeneration && copyGeneration === sceneCopyGeneration) { byId('endpoint-status').textContent = `Could not save: ${error.message}`; byId('save-observation').disabled = endpointPicks.length !== 2; } }
    finally {
      submitting = false;
      if (generation === referenceGeneration && copyGeneration === sceneCopyGeneration) byId('save-observation').disabled = workspace.loading || sceneVariant !== 'source' || Boolean(measurement?.read_only) || endpointPicks.length !== 2;
    }
  };
  byId('new-reference').onclick = startMeasurement;
  byId('reference-id').oninput = () => clearActiveReference({ referenceId: byId('reference-id').value, quantity: byId('quantity').value });
  byId('quantity').onchange = () => clearActiveReference({ referenceId: byId('reference-id').value, quantity: byId('quantity').value });
  byId('measurement-name').oninput = () => { submissionKey = null; };
  byId('measurement-name').onchange = async () => {
    if (!measurement || measurement.read_only) return;
    const generation = referenceGeneration, copy = sceneCopyGeneration;
    const operation = ++measurementOperation;
    const payload = {action:'rename',reference_id:measurement.record.reference_id,display_name:byId('measurement-name').value};
    try {
      const value = await enqueueMeasurementMutation(payload,generation,copy);
      if (value && generation === referenceGeneration && copy === sceneCopyGeneration && operation > acceptedMeasurementOperation) {
        acceptedMeasurementOperation = operation;
        const pendingName = byId('measurement-name').value;
        showMeasurement(value);
        if (operation !== measurementOperation) byId('measurement-name').value = pendingName;
      }
    } catch(error) { if (generation === referenceGeneration && copy === sceneCopyGeneration && operation === measurementOperation) byId('endpoint-status').textContent = `Could not rename: ${error.message}`; }
  };
  byId('physical-length').oninput = updateCalibration;
  byId('physical-unit').onchange = updateCalibration;
  byId('saved-measurements').onchange = async event => {
    const id = event.target.value;
    clearActiveReference({ referenceId: id });
    if (!id) return;
    byId('saved-measurements').value = id;
    const generation = referenceGeneration, copyGeneration = sceneCopyGeneration;
    byId('measurement-summary').textContent = 'Opening saved reference…';
    try {
      const value = await (await fetchChecked(`/api/measurements/${encodeURIComponent(id)}`)).json();
      if (generation !== referenceGeneration || copyGeneration !== sceneCopyGeneration) return;
      showMeasurement(value);
    } catch (error) { if (generation === referenceGeneration && copyGeneration === sceneCopyGeneration) byId('measurement-summary').textContent = `Could not open reference: ${error.message}`; }
  };
  byId('color-mode').onchange = () => display(current, byId('view-label').textContent);
  byId('hide-frame').onclick = async () => { if (selectedFrame && !visibility.hidden_frame_ids.includes(selectedFrame.frame_id)) visibility.hidden_frame_ids.push(selectedFrame.frame_id); try { await saveVisibility(); } catch (error) { byId('visibility-note').textContent = error.message; } };
  byId('hide-roi').onclick = async () => {
    const roi = byId('roi-bounds').value.split(',').map(Number);
    if (!selectedFrame || roi.length !== 4 || roi.some(value => !Number.isFinite(value))) { byId('visibility-note').textContent = 'Enter four finite model pixel bounds.'; return; }
    visibility.hidden_rois.push({ frame_id: selectedFrame.frame_id, bounds: roi });
    try { await saveVisibility(); } catch (error) { byId('visibility-note').textContent = error.message; }
  };
  byId('reset-visibility').onclick = async () => { visibility = { hidden_frame_ids: [], hidden_rois: [] }; try { await saveVisibility(); } catch (error) { byId('visibility-note').textContent = error.message; } };
  await refreshMeasurements();
  const archive = await (await fetchChecked('/api/archive')).json();
  const archiveSelect = byId('archived-measurements');
  if (archive.status === 'available') {
    archiveSelect.replaceChildren(new Option('Choose an archived source reference', ''));
    archive.measurements.forEach((value, index) => archiveSelect.append(new Option(`${value.record.reference_id} · ${value.record.role} · read-only`, String(index))));
    archiveSelect.onchange = event => {
      const index = event.target.value;
      clearActiveReference();
      if (index !== '') {
        archiveSelect.value = index;
        showMeasurement({ ...archive.measurements[Number(index)], read_only: true, display_scalar: archive.display_scalar, source_manifest_sha256: archive.source_manifest_sha256, source_point_cloud_sha256: archive.source_point_cloud_sha256 });
        clearEndpointPicks('Archived observations are read-only. Use New reference to start a scene measurement.');
      }
    };
    byId('archive-status').textContent = `${archive.validation_scope}\nFrozen calibration and checks:\n${JSON.stringify({ calibration: archive.calibration, check_report: archive.check_report }, null, 2)}`;
  } else {
    archiveSelect.disabled = true;
    byId('archive-status').textContent = archive.status === 'unavailable' ? `Exported archive unavailable: ${archive.reason}` : 'No exported source archive.';
  }
  byId('scene-variant').options[1].disabled = !metadata.derived_available;
  workspace.derivedAvailable = metadata.derived_available;
  workspace.calibratedScene = metadata.scale.type === 'calibrated_metric';
  updateCalibration();
  const showCalibration = async () => {
    const calibration = await (await fetchChecked('/api/calibration')).json();
    const report = await (await fetchChecked('/api/check-report')).json();
    calibrationScalar = calibration.scalar;
    byId('calibration-report').textContent = formatCalibrationReport(calibration, report);
    byId('calibration-summary').textContent = calibrationSummary(calibration, report);
  };
  if (workspace.calibratedScene) {
    byId('calibration-summary').textContent = archive.status === 'available' ? calibrationSummary(archive.calibration,archive.check_report) : 'Scale is set, but the frozen source evidence is unavailable. Shape accuracy is not verified.';
    byId('calibration-report').textContent = archive.status === 'available'
      ? formatCalibrationReport(archive.calibration, archive.check_report, { archived: true })
      : `Frozen calibration report unavailable: ${archive.status === 'unavailable' ? archive.reason : 'No validated exported source archive is available for this calibrated scene.'}`;
  } else if (metadata.derived_available) await showCalibration();
  byId('calibrate').onclick = async () => {
    try {
      const eligibility = calibrationEligibility(calibrationState());
      if (!eligibility.eligible) throw new Error(eligibility.reason);
      const payload = { reference_id: measurement.record.reference_id, physical_value: eligibility.physicalValue, physical_unit: byId('physical-unit').value };
      workspace.calibrating = true; byId('scene-variant').disabled = true; updateCalibration();
      byId('calibration-report').textContent = 'Saving uniform calibrated copy…';
      const saved = await postWorkspace('/api/calibration', payload);
      if (saved?.version && typeof sceneContext !== 'undefined' && sceneContext) {
        window.location.href = `/scenes/${sceneContext.sceneId}/runs/${saved.version.run_id}/sessions/${saved.version.session_id}`;
        return;
      }
      workspace.derivedAvailable = true;
      byId('scene-variant').options[1].disabled = false;
      await showCalibration();
    } catch (error) { byId('calibration-report').textContent = `${error.message}. Raw source viewing remains available.`; }
    finally { workspace.calibrating = false; byId('scene-variant').disabled = false; updateCalibration(); }
  };
  byId('scene-variant').onchange = async event => {
    sourcePreview?.hide();
    clearTimeout(inspectTimer);
    const generation = ++requestGeneration;
    sceneCopyGeneration++;
    const variant = event.target.value;
    referenceGeneration++;
    if (!measurement) {
      byId('saved-measurements').value = '';
      byId('measurement-summary').textContent = 'No examined reference. More than one view is needed to assess consistency.';
    }
    byId('physical-length').value = resetReferenceState(calibrationState()).physicalLength;
    workspace.loading = true; updateCalibration();
    clearEndpointPicks('Switching scene copy…');
    byId('copy-status').textContent = `Loading ${variant} scene…`;
    byId('pick-3d').disabled = true; byId('pick-image').disabled = true;
    try {
      const prefix = variant === 'derived' ? '/api/derived' : '/api';
      const nextMetadata = await (await fetchChecked(`${prefix}/scene`)).json();
      if (generation !== requestGeneration) return;
      const nextPreview = await loadBundle(`${prefix}/preview`);
      if (generation !== requestGeneration) return;
      metadata = nextMetadata; preview = nextPreview; sceneVariant = variant;
      byId('active-version').textContent = metadata.version ? `${metadata.version.label}${metadata.default_version_id === metadata.version.version_id ? ' · Default' : ''}` : variant === 'source' ? 'Source scene' : 'Uniform calibrated copy';
      workspace.loading = false;
      bounds = new THREE.Box3();
      for (let i = 0; i < preview.header.count; i++) bounds.expandByPoint(new THREE.Vector3().fromArray(preview.xyz, i * 3));
      world.remove(cameraGroup, cameraPath); disposeGeometryGroup(cameraGroup); disposeGeometryGroup(cameraPath);
      cameraTargets = []; addCameras();
      cameraGroup.visible = byId('show-cameras').checked;
      selectFrame(null); endpointPicks = []; pickMode = null;
      byId('pick-3d').disabled = sceneVariant === 'derived';
      byId('pick-image').disabled = true; byId('save-observation').disabled = true;
      display(preview, `${sceneVariant} scene · deterministic preview`, true);
      timeline?.render(metadata); exploration?.setScene(metadata, sceneContext?.apiPrefix, sceneVariant);
      if (measurement) showMeasurement(measurement);
      clearEndpointPicks(measurement?.read_only ? 'Archived observations are read-only. Use New reference to start a scene measurement.' : sceneVariant === 'derived' ? 'Switch to the source scene to add observations.' : 'Source scene ready. Choose a picking method to begin.');
      updateCalibration();
      byId('copy-status').textContent = `${sceneVariant === 'source' ? 'Source geometry' : 'Uniform calibrated copy'} · ready for inspection`;
      showSceneStatus();
      byId('artifact-hash').textContent = `Manifest SHA-256: ${metadata.manifest_sha256}`;
    } catch (error) {
      if (generation === requestGeneration) {
        workspace.loading = false; byId('scene-variant').value = sceneVariant; updateCalibration();
        selectFrame(selectedFrame?.frame_id ?? null);
        byId('pick-3d').disabled = sceneVariant !== 'source' || Boolean(measurement?.read_only);
        clearEndpointPicks('Scene switch failed. Endpoint picks were cleared; choose a picking method to resume.');
        byId('copy-status').textContent = `Could not switch scene: ${error.message}. Still viewing ${sceneVariant}.`;
      }
    }
  };
  byId('camera-view').onclick = lookFromCamera;
  byId('frame-points').onclick = async () => {
    const frame = selectedFrame;
    if (!frame || workspace.loading) return;
    const generation = ++requestGeneration;
    byId('loading').textContent = `Loading original points for frame ${frame.frame_id}…`; byId('loading').hidden = false;
    try {
      const bundle = await loadBundle(frame.points_url);
      if (generation === requestGeneration) {
        display(bundle, `Source frame ${frame.frame_id} · every original point row`);
        byId('loading').hidden = true;
      }
    } catch (error) { if (generation === requestGeneration) showError(error); }
  };
  let down;
  renderer.domElement.addEventListener('pointerdown', event => { down = [event.clientX, event.clientY]; });
  renderer.domElement.addEventListener('pointerup', event => {
    if (down && Math.hypot(event.clientX - down[0], event.clientY - down[1]) < 4) {
      const point = { clientX: event.clientX, clientY: event.clientY };
      const inspect = () => { if (workspace.loading || disposed) return; try { inspectClick(point); } catch (error) { byId('endpoint-status').textContent = error.message; } };
      // A focus double-click must not first change source frame or draft picks.
      clearTimeout(inspectTimer);
      if (pickMode === '3d') inspect(); else inspectTimer = setTimeout(inspect, 300);
    }
    down = null;
  });
  renderer.domElement.addEventListener('pointercancel', () => { down = null; clearTimeout(inspectTimer); });
  renderer.domElement.addEventListener('dblclick', event => { clearTimeout(inspectTimer); focusAtPointer(event); });
  const remembered = loadView();
  if (remembered) {
    if (metadata.frames.some(frame => frame.frame_id === remembered.frameId)) selectFrame(remembered.frameId);
    if ([remembered.position, remembered.target].every(values => Array.isArray(values) && values.length === 3 && values.every(Number.isFinite))) {
      camera.position.fromArray(remembered.position); controls.target.fromArray(remembered.target); controls.update();
    }
  }
  if (metadata.version?.frozen) {
    byId('scene-variant').value = 'derived';
    await byId('scene-variant').onchange({ target: { value: 'derived' } });
  }
}

globalThis.window?.addEventListener('pagehide', () => {
  if (camera && controls) saveView({ frameId: selectedFrame?.frame_id ?? null, position: camera.position.toArray(), target: controls.target.toArray() });
  disposed = true; requestGeneration++; referenceGeneration++; sceneCopyGeneration++;
  clearTimeout(inspectTimer);
  endpointPicks = []; pickMode = null; imageEditor?.cancel(); sourceLoadGate.cancel();
  photoCleanups.forEach(cleanup => cleanup()); cancelAnimationFrame(animationFrame);
  controls?.dispose();
  exploration?.dispose();
  sourcePreview?.dispose();
  disposeGeometryGroup(world);
  cameraIconTexture?.dispose();
  renderer?.dispose(); renderer?.forceContextLoss();
});
globalThis.window?.addEventListener('pageshow', event => { if (event.persisted) window.location.reload(); });
init().catch(showError);
