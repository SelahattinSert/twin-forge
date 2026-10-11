import * as THREE from 'three';
import { validClipRanges } from '/view-state.js';

export function makeClipBox(bounds, ranges) {
  if (!validClipRanges(ranges) || bounds.isEmpty()) throw new Error('Invalid viewing clip box.');
  const size = bounds.getSize(new THREE.Vector3());
  const min = bounds.min.clone(), max = bounds.min.clone();
  for (const [i, axis] of ['x', 'y', 'z'].entries()) {
    // Flat scenes still need a nonzero display interval. Original points stay put.
    const span = Math.max(size[axis], 1e-6), origin = bounds.min[axis] - (span - size[axis]) / 2;
    min[axis] = origin + span * ranges[i][0] / 100;
    max[axis] = origin + span * ranges[i][1] / 100;
  }
  return new THREE.Box3(min, max);
}

export function boxPlanes(box) {
  return [new THREE.Plane(new THREE.Vector3(1, 0, 0), -box.min.x), new THREE.Plane(new THREE.Vector3(-1, 0, 0), box.max.x),
    new THREE.Plane(new THREE.Vector3(0, 1, 0), -box.min.y), new THREE.Plane(new THREE.Vector3(0, -1, 0), box.max.y),
    new THREE.Plane(new THREE.Vector3(0, 0, 1), -box.min.z), new THREE.Plane(new THREE.Vector3(0, 0, -1), box.max.z)];
}

export function focusPoint(camera, controls, xyz) {
  const target = new THREE.Vector3(...xyz), offset = target.clone().sub(controls.target);
  if (![...xyz, ...camera.position.toArray()].every(Number.isFinite)) return false;
  // Translate the orbit center and camera together: no jump in orientation/zoom.
  camera.position.add(offset); controls.target.copy(target); controls.update(); return true;
}

export class CameraTimeline {
  constructor(byId, select, look) {
    this.byId = byId; this.select = select; this.look = look; this.frames = []; this.selected = null;
    byId('timeline-previous').onclick = () => this.move(-1);
    byId('timeline-next').onclick = () => this.move(1);
    byId('timeline-look').onclick = () => this.look();
    byId('camera-timeline').onkeydown = event => {
      if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return;
      if (!event.target.classList.contains('timeline-frame')) return;
      event.preventDefault();
      const index = event.key === 'Home' ? 0 : event.key === 'End' ? this.frames.length - 1 :
        Math.max(0, Math.min(this.frames.length - 1, this.frames.findIndex(frame => frame.frame_id === this.selected) + (event.key === 'ArrowLeft' ? -1 : 1)));
      this.choose(index, true);
    };
  }
  render(metadata) {
    this.frames = [...metadata.frames].sort((a, b) => a.timestamp_seconds - b.timestamp_seconds || a.frame_id - b.frame_id);
    this.cameras = metadata.cameras;
    this.byId('timeline-count').textContent = `${this.frames.length} views`;
    this.buttons = [];
    const strip = this.byId('camera-timeline'); strip.replaceChildren();
    this.frames.forEach((frame, index) => {
      const button = document.createElement('button'); button.type = 'button'; button.className = 'timeline-frame';
      button.setAttribute('aria-label', `Select frame ${frame.frame_id} at ${frame.timestamp_seconds.toFixed(2)} seconds`);
      const image = document.createElement('img'); image.loading = 'lazy'; image.decoding = 'async'; image.alt = '';
      const fallback = document.createElement('span'); fallback.className = 'thumbnail-fallback'; fallback.textContent = 'Photo unavailable'; fallback.hidden = true;
      image.onerror = () => { image.hidden = true; fallback.hidden = false; }; image.src = frame.thumbnail_url ?? frame.image_url;
      const label = document.createElement('span'); label.textContent = `${frame.timestamp_seconds.toFixed(2)}s`;
      const detail = document.createElement('small'); detail.textContent = `Frame ${frame.frame_id}`;
      button.append(image, fallback, label, detail); button.onclick = () => this.choose(index);
      strip.append(button); this.buttons.push(button);
    });
    this.sync(this.selected, false);
  }
  choose(index, focus = false) {
    const frame = this.frames[index]; if (!frame) return;
    this.select(frame.frame_id); if (focus) this.buttons[index].focus();
  }
  move(direction) {
    const current = this.frames.findIndex(frame => frame.frame_id === this.selected);
    this.choose(current < 0 ? (direction > 0 ? 0 : this.frames.length - 1) : current + direction);
  }
  sync(frameId, scroll = true) {
    this.selected = frameId;
    const index = this.frames.findIndex(frame => frame.frame_id === frameId);
    this.buttons?.forEach((button, i) => {
      button.setAttribute('aria-pressed', String(i === index)); button.tabIndex = i === (index < 0 ? 0 : index) ? 0 : -1;
    });
    if (scroll && index >= 0 && this.byId('source-views').open) this.buttons[index].scrollIntoView({ block: 'nearest', inline: 'nearest', behavior: 'instant' });
    this.byId('timeline-previous').disabled = !this.frames.length || index === 0;
    this.byId('timeline-next').disabled = !this.frames.length || index === this.frames.length - 1;
    this.byId('timeline-look').disabled = !this.cameras?.find(record => record.frame_id === frameId)?.camera_to_world;
    this.byId('timeline-status').textContent = index < 0 ? `${this.frames.length} saved views · choose a photo to inspect` :
      `View ${index + 1} of ${this.frames.length} · ${this.frames[index].timestamp_seconds.toFixed(2)}s · frame ${frameId}`;
  }
}
