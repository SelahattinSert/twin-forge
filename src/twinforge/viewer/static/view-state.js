// Browser-local viewing preferences. No observation, scale or XYZ is rewritten.
export const MAX_SAVED_VIEWS = 20;
export const fullClipRanges = () => [[0, 100], [0, 100], [0, 100]];
const finiteVector = value => Array.isArray(value) && value.length === 3 && value.every(Number.isFinite);

export function validClipRanges(value) {
  return Array.isArray(value) && value.length === 3 && value.every(pair =>
    Array.isArray(pair) && pair.length === 2 && pair.every(Number.isFinite) &&
    pair[0] >= 0 && pair[1] <= 100 && pair[0] < pair[1]);
}

export function validView(value) {
  if (!value || ![value.position, value.target, value.up].every(finiteVector)) return false;
  const length = values => Math.hypot(...values);
  return length(value.up) > 1e-12 &&
    length(value.position.map((item, i) => item - value.target[i])) > 1e-12 &&
    Number.isFinite(value.fov) && value.fov >= 10 && value.fov <= 120 &&
    Number.isFinite(value.near) && value.near > 0 && Number.isFinite(value.far) && value.far > value.near &&
    typeof value.clipEnabled === 'boolean' && validClipRanges(value.clipRanges) &&
    (value.frameId === null || Number.isSafeInteger(value.frameId));
}

export function captureView(camera, controls, frameId, clipEnabled, clipRanges) {
  const value = { position: camera.position.toArray(), target: controls.target.toArray(), up: camera.up.toArray(),
    fov: camera.fov, near: camera.near, far: camera.far, frameId: frameId ?? null,
    clipEnabled, clipRanges: clipRanges.map(pair => [...pair]) };
  if (!validView(value)) throw new Error('The current camera view is not available yet.');
  return value;
}

export function restoreCamera(value, camera, controls) {
  if (!validView(value)) throw new Error('This saved view is invalid.');
  camera.position.fromArray(value.position); camera.up.fromArray(value.up);
  camera.fov = value.fov; camera.near = value.near; camera.far = value.far;
  camera.updateProjectionMatrix(); controls.target.fromArray(value.target);
}

export function viewStorageKey(metadata, identity, variant) {
  // Legacy viewers also have artifact identity; identical coordinates are not
  // enough to share preferences across a different scene/version/session.
  return `twinforge-saved-views:v1:${JSON.stringify([identity || 'legacy',
    metadata.manifest_sha256, metadata.point_cloud_sha256, variant])}`;
}

export class ViewStore {
  constructor(storage, key) { this.storage = storage; this.key = key; }
  list() {
    const text = this.storage.getItem(this.key);
    if (text === null) return [];
    if (text.length > 100000) throw new Error('Local saved-view data is too large.');
    const data = JSON.parse(text);
    if (data?.schema_version !== '1' || !Array.isArray(data.views) || data.views.length > MAX_SAVED_VIEWS ||
      data.views.some(item => !item || typeof item.id !== 'string' || !item.id || typeof item.name !== 'string' ||
        !item.name.trim() || item.name.length > 80 || !validView(item.view)) ||
      new Set(data.views.map(item => item.id)).size !== data.views.length) throw new Error('Local saved-view data is invalid.');
    return data.views;
  }
  write(views) { this.storage.setItem(this.key, JSON.stringify({ schema_version: '1', views })); }
  add(name, view, id) {
    const views = this.list();
    if (!name.trim() || name.trim().length > 80 || !validView(view) || typeof id !== 'string' || !id) throw new Error('Enter a view name and use a valid camera view.');
    if (views.length >= MAX_SAVED_VIEWS) throw new Error(`Remove a saved view first. The limit is ${MAX_SAVED_VIEWS}.`);
    if (views.some(item => item.id === id)) throw new Error('This view identifier already exists.');
    views.push({ id, name: name.trim(), view }); this.write(views); return id;
  }
  rename(id, name) {
    const views = this.list(), item = views.find(item => item.id === id);
    if (!item || !name.trim() || name.trim().length > 80) throw new Error('Select a saved view and enter its new name.');
    item.name = name.trim(); this.write(views);
  }
  remove(id) { this.write(this.list().filter(item => item.id !== id)); }
}
