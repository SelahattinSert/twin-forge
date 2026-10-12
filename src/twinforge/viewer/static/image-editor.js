import { imageTransform, sourceToDisplay, displayToSource, ImageSelection, ImageLoadGate } from '/image-selection.js';

const svgNS = 'http://www.w3.org/2000/svg';
export function drawOverlay(svg, selections, transform, labels = true) {
  svg.replaceChildren();
  for (const points of selections) {
    if (!points || points.length === 0) continue;
    const positions = points.map(point => sourceToDisplay(point, transform));
    if (positions.length === 2) {
      const line = document.createElementNS(svgNS, 'line');
      ['x1','y1','x2','y2'].forEach((name, i) => line.setAttribute(name, positions[Math.floor(i / 2)][i % 2]));
      line.setAttribute('class', 'selection-line'); svg.append(line);
    }
    positions.forEach(([x, y], index) => {
      const circle = document.createElementNS(svgNS, 'circle');
      circle.setAttribute('cx', x); circle.setAttribute('cy', y); circle.setAttribute('r', 9);
      circle.setAttribute('class', 'selection-marker'); svg.append(circle);
      if (labels) {
        const text = document.createElementNS(svgNS, 'text'); text.setAttribute('x', x + 13); text.setAttribute('y', y - 12);
        text.setAttribute('class', 'selection-label'); text.textContent = index ? 'B' : 'A'; svg.append(text);
      }
    });
  }
}

export function annotatePhoto(container, url, points, alt = 'Saved observation') {
  const image = document.createElement('img'); image.alt = alt;
  const svg = document.createElementNS(svgNS, 'svg'); svg.setAttribute('aria-hidden', 'true');
  container.replaceChildren(image, svg); container.classList.add('annotated-photo');
  const draw = () => {
    if (!image.naturalWidth || !image.clientWidth) return;
    const width = image.clientWidth, height = image.clientHeight;
    svg.setAttribute('viewBox', `0 0 ${width} ${height}`);
    drawOverlay(svg, [points], imageTransform(image.naturalWidth, image.naturalHeight, width, height));
  };
  image.onload = draw; image.src = url;
  const observer = new ResizeObserver(draw); observer.observe(image);
  return () => observer.disconnect();
}

export class ImageEditor {
  constructor(byId, getContext, onConfirm) {
    this.byId = byId; this.getContext = getContext; this.onConfirm = onConfirm; this.gate = new ImageLoadGate();
    this.dialog = byId('image-editor'); this.surface = byId('editor-surface'); this.image = byId('editor-image');
    byId('editor-cancel').onclick = () => this.cancel();
    this.dialog.addEventListener('cancel', event => { event.preventDefault(); this.cancel(); });
    byId('editor-confirm').onclick = () => {
      if (this.readOnly) return;
      try { const points = this.selection.confirm(this.getContext()); const context = this.selection.context, intent = this.intent; this.close(); this.onConfirm(points, context, intent); }
      catch (error) { byId('editor-instruction').textContent = error.message; }
    };
    byId('editor-fit').onclick = () => { this.zoom = 1; this.pan = [0,0]; this.render(); };
    byId('editor-zoom-in').onclick = () => this.changeZoom(1.25);
    byId('editor-zoom-out').onclick = () => this.changeZoom(.8);
    byId('editor-undo').onclick = () => { this.selection?.undo(); this.render(); };
    byId('editor-clear').onclick = () => { this.selection?.clear(); this.active = 0; this.render(); };
    for (const index of [0,1]) byId(`editor-${index ? 'b' : 'a'}`).onclick = () => { this.active = index; this.surface.focus(); this.render(); };
    this.surface.addEventListener('keydown', event => {
      if (!this.selection || this.readOnly) return;
      const directions = {ArrowLeft:[-1,0],ArrowRight:[1,0],ArrowUp:[0,-1],ArrowDown:[0,1]};
      if (directions[event.key]) {
        event.preventDefault(); const [dx,dy] = directions[event.key], step = event.shiftKey ? 10 : 1;
        this.selection.nudge(this.active, dx * step, dy * step); this.render();
      }
      if (event.key === 'Enter' && this.selection.points.length < 2) {
        event.preventDefault(); this.selection.place([(this.selection.width - 1) / 2, (this.selection.height - 1) / 2]); this.active = this.selection.points.length - 1; this.render();
      }
    });
    this.dialog.addEventListener('keydown', event => {
      if (event.key !== 'Tab') return;
      const focusable = [...this.dialog.querySelectorAll('button:not(:disabled),input:not(:disabled),[tabindex="0"]')].filter(node => !node.hidden);
      const first = focusable[0], last = focusable.at(-1);
      if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
      else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
    });
    this.surface.addEventListener('pointerdown', event => {
      if (!this.selection || event.button !== 0) return;
      event.preventDefault(); const position = this.position(event), transform = this.transform();
      const hit = this.selection.points.findIndex(point => Math.hypot(...sourceToDisplay(point,transform).map((n,i)=>n-position[i])) < 22);
      const pan = byId('editor-pan').checked || event.altKey || this.readOnly;
      this.gesture = {position, pan: [...this.pan], mode: pan ? 'pan' : hit >= 0 ? 'move' : 'place', index: hit, moved: false};
      if (!pan && hit >= 0) { this.active = hit; this.selection.checkpoint(); }
      this.surface.setPointerCapture(event.pointerId);
    });
    this.surface.addEventListener('pointermove', event => {
      const gesture = this.gesture; if (!gesture) return;
      const position = this.position(event), dx = position[0]-gesture.position[0], dy=position[1]-gesture.position[1];
      if (Math.hypot(dx,dy)>3) gesture.moved = true;
      if (gesture.mode === 'pan') this.pan = [gesture.pan[0]+dx,gesture.pan[1]+dy];
      else if (gesture.mode === 'move') { const pixel = displayToSource(position,this.transform()); if (pixel) this.selection.move(gesture.index,pixel,false); }
      this.render();
    });
    this.surface.addEventListener('pointerup', event => {
      const gesture = this.gesture; this.gesture = null; if (!gesture) return;
      if (gesture.mode === 'place' && !gesture.moved && !this.readOnly) {
        const pixel = displayToSource(this.position(event),this.transform());
        if (pixel) { this.selection.place(pixel); this.active = this.selection.points.length - 1; }
      }
      this.render();
    });
    this.surface.addEventListener('pointercancel', () => { this.gesture = null; });
    this.surface.addEventListener('wheel', event => { event.preventDefault(); this.changeZoom(event.deltaY < 0 ? 1.1 : 1/1.1); },{passive:false});
    new ResizeObserver(() => this.render()).observe(this.surface);
  }
  position(event) { const rect = this.surface.getBoundingClientRect(); return [event.clientX-rect.left,event.clientY-rect.top]; }
  transform() { return imageTransform(this.selection.width,this.selection.height,this.surface.clientWidth,this.surface.clientHeight,this.zoom,this.pan); }
  changeZoom(factor) { this.zoom = Math.max(1,Math.min(12,this.zoom * factor)); this.render(); }
  open(frame, points = [], previous = null, readOnly = false, intent = null) {
    this.cancel(); this.opener = document.activeElement; this.zoom = 1; this.pan = [0,0]; this.active = 0; this.readOnly = readOnly;
    this.intent = intent ? {...intent} : null;
    this.byId('editor-pan').checked = readOnly; this.selection = null;
    const context = this.getContext(), token = this.gate.begin(context);
    this.byId('editor-title').textContent = `${readOnly ? 'Observation replay' : 'Select A and B'} · Frame ${frame.frame_id} · ${frame.timestamp_seconds.toFixed(2)}s`;
    this.byId('editor-instruction').textContent = 'Loading source photo…'; this.byId('editor-confirm').disabled = true;
    this.image.hidden = true; this.byId('editor-overlay').replaceChildren();
    this.previousCleanup?.(); this.previousCleanup = null;
    this.byId('editor-previous').hidden = !previous;
    if (previous) {
      this.previousCleanup = annotatePhoto(this.byId('editor-previous-photo'),previous.frame.image_url,previous.points,'Previous observation — match these physical points');
      const link = this.byId('editor-previous-link'); link.href = previous.frame.image_url;
    }
    for (const id of ['editor-a','editor-b','editor-undo','editor-clear']) this.byId(id).disabled = readOnly;
    this.byId('editor-confirm').hidden = readOnly;
    this.dialog.showModal();
    // Each request owns a separate loader so an obsolete event cannot read a new URL.
    const loader = new Image();
    loader.onload = () => {
      if (!this.dialog.open || token !== this.gate.generation) return;
      if (!this.gate.valid(token,this.getContext())) { this.cancel(); return; }
      this.selection = new ImageSelection(context,loader.naturalWidth,loader.naturalHeight,points);
      this.image.src = frame.image_url; this.image.hidden = false; this.image.alt = `Source frame ${frame.frame_id}`;
      this.render(); this.surface.focus();
    };
    loader.onerror = () => {
      if (!this.dialog.open || token !== this.gate.generation) return;
      if (!this.gate.valid(token,this.getContext())) { this.cancel(); return; }
      this.byId('editor-instruction').textContent = 'Source photo is unavailable. Cancel and choose an available source frame.';
    };
    loader.src = frame.image_url;
  }
  render() {
    if (!this.selection || !this.dialog.open || !this.surface.clientWidth || !this.surface.clientHeight) return;
    if (!this.gate.valid(this.gate.generation,this.getContext())) { this.cancel(); return; }
    const t = this.transform();
    Object.assign(this.image.style,{left:`${t.x}px`,top:`${t.y}px`,width:`${t.width*t.scale}px`,height:`${t.height*t.scale}px`});
    const svg = this.byId('editor-overlay'); svg.setAttribute('viewBox',`0 0 ${this.surface.clientWidth} ${this.surface.clientHeight}`);
    drawOverlay(svg,[this.selection.points],t);
    this.byId('editor-instruction').textContent = this.readOnly ? 'Read-only replay. Source pixels and A/B order are preserved.' : this.selection.points.length === 0 ? 'Select the start point (A). Enter places a point at the image center; arrow keys adjust it.' : this.selection.points.length === 1 ? 'Select the end point (B).' : `${this.active ? 'B (end)' : 'A (start)'} selected. Drag its marker or use arrow keys (Shift: 10 pixels). Confirm selection, then Add observation.`;
    this.byId('editor-confirm').disabled = this.readOnly || this.selection.points.length !== 2;
    this.byId('editor-zoom-value').textContent = `${this.zoom.toFixed(2)}×`;
    this.byId('editor-a').setAttribute('aria-pressed',String(this.active === 0)); this.byId('editor-b').setAttribute('aria-pressed',String(this.active === 1));
  }
  close() { this.gate.cancel(); this.selection = null; this.intent = null; this.gesture = null; this.previousCleanup?.(); this.previousCleanup = null; if (this.dialog.open) this.dialog.close(); this.opener?.focus(); }
  cancel() { this.close(); }
}
