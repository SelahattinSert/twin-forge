import * as THREE from 'three';

export function buildCameraMarkers(cameras, texture) {
  const group = new THREE.Group();
  const material = new THREE.SpriteMaterial({ map: texture, transparent: true, depthTest: true,
    depthWrite: false, sizeAttenuation: false, alphaTest: .1 });
  for (const camera of cameras) {
    const pose = camera.camera_to_world;
    if (!Array.isArray(pose) || pose.length !== 4 || !pose.every(row => Array.isArray(row) && row.length === 4 && row.every(Number.isFinite))) continue;
    const marker = new THREE.Sprite(material);
    marker.position.set(pose[0][3], pose[1][3], pose[2][3]); marker.scale.set(.035, .035, 1);
    marker.userData = { kind: 'camera_icon', frameId: camera.frame_id };
    group.add(marker);
  }
  if (!group.children.length) material.dispose();
  return group;
}
