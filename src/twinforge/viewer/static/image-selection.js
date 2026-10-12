// Raster-center coordinates are authoritative; transforms affect display only.
export function imageTransform(width, height, viewportWidth, viewportHeight, zoom = 1, pan = [0, 0]) {
  if (![width, height, viewportWidth, viewportHeight, zoom].every(n => Number.isFinite(n) && n > 0)) throw new Error('Image dimensions are unavailable.');
  const scale = Math.min(viewportWidth / width, viewportHeight / height) * zoom;
  return { width, height, scale, x: (viewportWidth - width * scale) / 2 + pan[0], y: (viewportHeight - height * scale) / 2 + pan[1] };
}

export function sourceToDisplay(pixel, transform) {
  return [transform.x + (pixel[0] + .5) * transform.scale, transform.y + (pixel[1] + .5) * transform.scale];
}

export function displayToSource(position, transform) {
  const pixel = [(position[0] - transform.x) / transform.scale - .5, (position[1] - transform.y) / transform.scale - .5];
  return pixel.every(Number.isFinite) && pixel[0] >= -.5 && pixel[1] >= -.5 && pixel[0] < transform.width - .5 && pixel[1] < transform.height - .5 ? pixel : null;
}

const copy = points => points.map(point => [...point]);
export const sameContext = (a, b) => Object.keys(a).length === Object.keys(b).length && Object.keys(a).every(key => a[key] === b[key]);

export class ImageLoadGate {
  generation = 0;
  begin(context) { this.context = { ...context }; return ++this.generation; }
  valid(token, context) { return token === this.generation && sameContext(this.context, context); }
  cancel() { this.generation++; }
}

export class ImageSelection {
  constructor(context, width, height, points = []) {
    this.context = { ...context }; this.width = width; this.height = height;
    this.original = copy(points); this.points = copy(points); this.history = [];
  }
  valid(pixel) { return pixel?.length === 2 && pixel.every(Number.isFinite) && pixel[0] >= -.5 && pixel[1] >= -.5 && pixel[0] < this.width - .5 && pixel[1] < this.height - .5; }
  checkpoint() { this.history.push(copy(this.points)); }
  place(pixel) { if (this.points.length < 2) { if (!this.valid(pixel)) throw new Error('Endpoint is outside the image.'); this.checkpoint(); this.points.push([...pixel]); } }
  move(index, pixel, checkpoint = true) { if (!this.points[index] || !this.valid(pixel)) throw new Error('Endpoint is outside the image.'); if (checkpoint) this.checkpoint(); this.points[index] = [...pixel]; }
  nudge(index, dx, dy) { const pixel = this.points[index]; if (!pixel) return; this.move(index, [Math.max(0, Math.min(this.width - 1, pixel[0] + dx)), Math.max(0, Math.min(this.height - 1, pixel[1] + dy))]); }
  clear() { this.checkpoint(); this.points = []; }
  undo() { if (this.history.length) this.points = this.history.pop(); }
  cancel() { return copy(this.original); }
  confirm(context) {
    if (!sameContext(this.context, context)) throw new Error('Image selection context changed. Reopen the editor.');
    if (this.points.length !== 2 || !this.points.every(point => this.valid(point))) throw new Error('Select two valid image endpoints.');
    return copy(this.points);
  }
}

export function matchingSelections(observations, frameId) {
  return observations.filter(item => item.frame_id === frameId && item.source_pixels?.length === 2);
}
