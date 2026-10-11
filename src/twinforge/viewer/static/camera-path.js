import * as THREE from 'three';

// This is a display overlay, not reconstructed scene geometry or a tracked
// continuous motion record. Straight segments connect adjacent saved views.
export function buildCameraPath(cameras, sceneRadius) {
  const group = new THREE.Group(); group.name = 'Estimated camera path';
  const samples = [...cameras].sort((a, b) =>
    (Number.isFinite(a.timestamp_seconds) ? a.timestamp_seconds : Infinity) -
    (Number.isFinite(b.timestamp_seconds) ? b.timestamp_seconds : Infinity) || a.frame_id - b.frame_id)
    .map(record => {
      const pose = record.camera_to_world;
      const valid = Array.isArray(pose) && pose.length === 4 && pose.every(row =>
        Array.isArray(row) && row.length === 4 && row.every(Number.isFinite));
      return { record, position: valid ? new THREE.Vector3(pose[0][3], pose[1][3], pose[2][3]) : null };
    });
  const usable = samples.filter(sample => sample.position);
  group.userData = { sampleCount: usable.length, segmentCount: 0,
    missingPoseCount: samples.length - usable.length,
    startFrameId: usable[0]?.record.frame_id ?? null,
    endFrameId: usable.at(-1)?.record.frame_id ?? null };
  if (!usable.length) return group;
  const scale = Number.isFinite(sceneRadius) && sceneRadius > 0 ? sceneRadius : 1;
  const extent = new THREE.Box3().setFromPoints(usable.map(sample => sample.position)).getSize(new THREE.Vector3()).length();
  const radius = Math.max(Number.EPSILON, Math.min(scale * .0015, extent > 0 ? extent * .01 : scale * .0015));
  const lineGeometry = new THREE.CylinderGeometry(1, 1, 1, 8);
  const nodeGeometry = new THREE.SphereGeometry(1, 12, 8);
  const material = new THREE.MeshBasicMaterial({ color: 0xe7c98a });
  const startMaterial = new THREE.MeshBasicMaterial({ color: 0xa5edcf });
  const endMaterial = new THREE.MeshBasicMaterial({ color: 0xff9e83 });
  const up = new THREE.Vector3(0, 1, 0);
  for (let i = 0; i < samples.length; i++) {
    const sample = samples[i]; if (!sample.position) continue;
    const first = sample === usable[0], last = sample === usable.at(-1);
    const node = new THREE.Mesh(nodeGeometry, first ? startMaterial : last ? endMaterial : material);
    node.position.copy(sample.position); node.scale.setScalar(radius * (first || last ? 3.5 : 1.8));
    node.userData = { kind: 'camera_path_node', frameId: sample.record.frame_id,
      timestampSeconds: sample.record.timestamp_seconds };
    group.add(node);
    const previous = samples[i - 1];
    // Missing poses break the path; coincident views add no artificial movement.
    if (!previous?.position) continue;
    const direction = sample.position.clone().sub(previous.position), length = direction.length();
    if (length === 0) continue;
    const segment = new THREE.Mesh(lineGeometry, material);
    segment.position.copy(previous.position).add(sample.position).multiplyScalar(.5);
    segment.scale.set(radius, length, radius); segment.quaternion.setFromUnitVectors(up, direction.normalize());
    segment.userData = { kind: 'camera_path_segment', fromFrameId: previous.record.frame_id, toFrameId: sample.record.frame_id };
    group.add(segment); group.userData.segmentCount++;
  }
  const used = new Set(); group.traverse(node => { if (node.geometry) used.add(node.geometry); if (node.material) used.add(node.material); });
  for (const resource of [lineGeometry, nodeGeometry, material, startMaterial, endMaterial]) if (!used.has(resource)) resource.dispose();
  return group;
}

export function disposeGeometryGroup(group) {
  const resources = new Set();
  group?.traverse(node => {
    if (node.geometry) resources.add(node.geometry);
    for (const material of Array.isArray(node.material) ? node.material : [node.material]) if (material) resources.add(material);
  });
  for (const resource of resources) resource.dispose();
}
