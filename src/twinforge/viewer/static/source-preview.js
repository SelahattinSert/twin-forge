// Read-only hover context. A photo is shown only for its recorded source frame.
export function sourcePreviewInfo(metadata, hit) {
  const frames = [...metadata.frames].sort((a, b) => a.timestamp_seconds - b.timestamp_seconds || a.frame_id - b.frame_id);
  const index = frames.findIndex(frame => frame.frame_id === hit.frameId), frame = frames[index];
  const hasPose = Boolean(metadata.cameras.find(record => record.frame_id === hit.frameId)?.camera_to_world);
  const viewLabel = index < 0 ? 'No recorded source view' : `View ${index + 1} of ${frames.length}`;
  return { key: `${hit.kind}:${hit.frameId}:${hit.pointIndex ?? ''}`, frameId: frame?.frame_id ?? null,
    kind: hit.kind === 'camera' ? 'Camera position' : 'Observed point',
    title: hit.kind === 'camera' ? viewLabel : `Point ${hit.pointIndex}`,
    detail: frame ? `${hit.kind === 'camera' ? '' : viewLabel + ' · '}Frame ${frame.frame_id} · ${frame.timestamp_seconds.toFixed(2)}s` : 'Source correspondence unavailable',
    imageURL: frame?.thumbnail_url ?? frame?.image_url ?? null, canLook: Boolean(frame && hasPose),
    note: !frame ? 'No nearby photo is substituted.' : hasPose ? 'Original source photo · estimated camera pose' : 'Source photo only · saved camera pose unavailable' };
}

export function previewPosition(x, y, viewportWidth, viewportHeight, cardWidth, cardHeight) {
  const gap = 18, inset = 12;
  const left = x + gap + cardWidth <= viewportWidth - inset ? x + gap : x - cardWidth - gap;
  return { left: Math.max(inset, Math.min(left, viewportWidth - cardWidth - inset)),
    top: Math.max(inset, Math.min(y - 35, viewportHeight - cardHeight - inset)) };
}

export class SourcePreview {
  constructor(byId, canvas, viewport, callbacks) {
    this.byId = byId; this.canvas = canvas; this.viewport = viewport; this.callbacks = callbacks;
    this.card = byId('hover-preview'); this.pending = null; this.dismiss = null; this.generation = 0; this.dragging = false;
    this.listeners = [];
    this.photos = new Map();
    this.overCard = false; this.keyboardFocus = false; this.motion = null; this.closing = false;
    const on = (element, type, fn) => { element.addEventListener(type, fn); this.listeners.push(() => element.removeEventListener(type, fn)); };
    on(canvas, 'pointermove', event => {
      if (event.pointerType === 'touch') return;
      if (this.dragging || event.buttons) { this.hide(); return; }
      this.point = { clientX: event.clientX, clientY: event.clientY };
      if (this.pending === null) this.pending = requestAnimationFrame(() => this.update());
    });
    on(canvas, 'pointerdown', () => { this.dragging = true; this.hide(); });
    on(canvas, 'pointerup', () => { this.dragging = false; });
    on(canvas, 'pointercancel', () => { this.dragging = false; this.hide(); });
    on(canvas, 'pointerleave', event => {
      this.cancelPending();
      this.dragging = false;
      if (!this.card.contains(event.relatedTarget)) this.scheduleHide();
    });
    on(canvas, 'wheel', () => this.hide());
    on(this.card, 'pointerenter', () => { this.overCard = true; this.keepOpen(); this.cancelPending(); });
    on(this.card, 'pointerleave', event => {
      this.overCard = false;
      if (!this.card.contains(event.relatedTarget)) this.scheduleHide();
    });
    on(this.card, 'pointerdown', () => { this.keyboardFocus = false; });
    on(this.card, 'focusin', event => {
      // Mouse focus must not pin a hover card after the pointer has left.
      this.keyboardFocus = Boolean(event.target?.matches?.(':focus-visible'));
      if (this.keyboardFocus) { this.keepOpen(); this.cancelPending(); }
    });
    on(this.card, 'focusout', event => {
      if (!this.card.contains(event.relatedTarget)) { this.keyboardFocus = false; this.scheduleHide(); }
    });
    on(viewport, 'keydown', event => { if (event.key === 'Escape') this.hide(); });
    byId('hover-close').onclick = () => this.hide();
    byId('hover-look').onclick = () => {
      if (!this.info?.canLook) return;
      const id = this.info.frameId; this.hide(); callbacks.look(id);
    };
  }
  cancelPending() { cancelAnimationFrame(this.pending); this.pending = null; }
  update() {
    this.pending = null;
    const hit = this.callbacks.hit(this.point);
    if (hit?.pending) { this.pending = requestAnimationFrame(() => this.update()); return; }
    if (hit) this.show(hit.info, this.point, hit.anchor); else this.scheduleHide();
  }
  scheduleHide() {
    if (this.card.hidden || this.overCard || (this.keyboardFocus && this.card.contains(document.activeElement)) || this.dismiss !== null || this.closing) return;
    // Do not extend this deadline on every pointer move across empty space.
    this.dismiss = setTimeout(() => { this.dismiss = null; this.fadeOut(); }, 70);
  }
  keepOpen() {
    clearTimeout(this.dismiss); this.dismiss = null;
    if (this.closing) {
      const opacity = this.currentOpacity(); this.stopMotion();
      this.animate([{ opacity }, { opacity: 1 }], 80, () => this.stopMotion());
    }
  }
  currentOpacity() { return Number(globalThis.getComputedStyle?.(this.card).opacity ?? 1); }
  stopMotion() {
    if (this.motion) { this.motion.onfinish = null; this.motion.cancel(); this.motion = null; }
    this.closing = false;
  }
  animate(keyframes, duration, finish) {
    if (!this.card.animate || globalThis.matchMedia?.('(prefers-reduced-motion: reduce)').matches) return false;
    this.motion = this.card.animate(keyframes, { duration, easing: 'cubic-bezier(.2,.8,.2,1)', fill: 'forwards' });
    const motion = this.motion;
    motion.onfinish = () => { if (this.motion === motion) finish(); };
    return true;
  }
  fadeOut() {
    const opacity = this.currentOpacity();
    this.stopMotion(); this.closing = true;
    this.byId('hover-marker').hidden = true;
    if (!this.animate([{ opacity }, { opacity: 0 }], 90, () => this.hide())) this.hide();
  }
  show(info, point, anchor = point) {
    const opening = this.card.hidden;
    this.keepOpen();
    const changed = this.info?.key !== info.key, photoChanged = this.info?.imageURL !== info.imageURL || this.card.hidden;
    this.info = info;
    this.byId('hover-kind').textContent = info.kind; this.byId('hover-title').textContent = info.title;
    this.byId('hover-detail').textContent = info.detail; this.byId('hover-note').textContent = info.note;
    this.byId('hover-image').alt = `${info.title} · ${info.detail}`;
    this.byId('hover-look').disabled = !info.canLook;
    this.byId('hover-look').setAttribute('aria-label', `${info.canLook ? 'Look from' : 'Unavailable camera pose for'} ${info.title}, ${info.detail}`);
    this.byId('hover-action').firstChild.textContent = info.canLook ? 'Look from view ' : 'Camera view unavailable ';
    this.card.hidden = false;
    if (opening) {
      this.stopMotion();
      this.animate([{ opacity: 0, transform: 'translateY(4px)' }, { opacity: 1, transform: 'translateY(0)' }], 120, () => this.stopMotion());
    }
    const rect = this.viewport.getBoundingClientRect(), marker = this.byId('hover-marker');
    marker.hidden = anchor.clientX < rect.left || anchor.clientX > rect.right || anchor.clientY < rect.top || anchor.clientY > rect.bottom;
    marker.style.left = `${anchor.clientX - rect.left}px`; marker.style.top = `${anchor.clientY - rect.top}px`;
    if (photoChanged) this.loadPhoto(info);
    if (changed || photoChanged) {
      const position = previewPosition(point.clientX - rect.left, point.clientY - rect.top, rect.width, rect.height,
        this.card.offsetWidth || 264, this.card.offsetHeight || 265);
      this.card.style.left = `${position.left}px`; this.card.style.top = `${position.top}px`;
    }
  }
  cancelPhoto() {
    if (!this.photoLoader) return;
    this.photoLoader.onload = this.photoLoader.onerror = null;
    this.photoLoader.removeAttribute('src'); this.photoLoader = null;
  }
  loadPhoto(info) {
    this.cancelPhoto();
    const token = ++this.generation, image = this.byId('hover-image'), fallback = this.byId('hover-photo-fallback');
    // Reuse the decoded image element itself: assigning its URL to another img
    // would request the same no-store thumbnail twice.
    image.hidden = true; fallback.hidden = false;
    fallback.textContent = info.imageURL ? 'Loading source photo…' : 'Source photo unavailable';
    if (!info.imageURL) return;
    const cached = this.photos.get(info.imageURL);
    if (cached) {
      this.photos.delete(info.imageURL); this.photos.set(info.imageURL, cached);
      cached.alt = `${info.title} · ${info.detail}`;
      if (image !== cached) image.replaceWith(cached);
      cached.hidden = false; fallback.hidden = true; return;
    }
    const loader = new Image(); loader.decoding = 'async'; loader.id = 'hover-image';
    this.photoLoader = loader;
    loader.onload = () => {
      if (this.disposed || this.photoLoader !== loader) return;
      this.photoLoader = null; loader.onload = loader.onerror = null;
      this.photos.delete(info.imageURL); this.photos.set(info.imageURL, loader);
      if (this.photos.size > 8) this.photos.delete(this.photos.keys().next().value);
      if (token !== this.generation || this.card.hidden) return;
      loader.alt = `${this.info.title} · ${this.info.detail}`;
      this.byId('hover-image').replaceWith(loader);
      loader.hidden = false; fallback.hidden = true;
    };
    loader.onerror = () => {
      if (this.photoLoader !== loader) return;
      this.photoLoader = null; loader.onload = loader.onerror = null;
      if (token === this.generation && !this.card.hidden) fallback.textContent = 'Source photo unavailable';
    };
    loader.src = info.imageURL;
  }
  hide() {
    const hadFocus = this.card.contains(document.activeElement);
    this.cancelPending(); clearTimeout(this.dismiss); this.dismiss = null;
    this.stopMotion(); this.overCard = false; this.keyboardFocus = false;
    this.cancelPhoto();
    this.generation++; this.info = null; this.card.hidden = true;
    this.byId('hover-marker').hidden = true;
    if (hadFocus) { this.canvas.tabIndex = 0; this.canvas.focus({ preventScroll: true }); }
  }
  dispose() { this.disposed = true; this.hide(); this.pointIndex?.reset(); this.photos.clear(); this.listeners.forEach(remove => remove()); this.listeners = []; }
}
