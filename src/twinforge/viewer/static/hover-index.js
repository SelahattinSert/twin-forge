// Display-only screen-space picking. No resampling or changes to source XYZ.
export class HoverIndex {
  constructor() { this.reset(); }
  reset() {
    this.geometry = this.positions = this.indices = this.matrix = null;
    this.signature = ''; this.cursor = 0; this.count = 0;
    this.heads = this.next = this.x = this.y = this.z = null;
  }
  prepare(cloud, camera, width, height, budgetMs = 3) {
    camera.updateMatrixWorld(); cloud.updateMatrixWorld();
    const signature = [...camera.projectionMatrix.elements, ...camera.matrixWorldInverse.elements,
      ...cloud.matrixWorld.elements, width, height].join(',');
    if (this.geometry !== cloud.geometry || this.positions !== cloud.geometry.attributes.position.array ||
      this.indices !== cloud.geometry.index?.array || signature !== this.signature) {
      this.geometry = cloud.geometry; this.signature = signature; this.cursor = 0;
      this.positions = cloud.geometry.attributes.position.array;
      this.indices = cloud.geometry.index?.array;
      this.count = this.indices?.length ?? this.positions.length / 3;
      this.width = width; this.height = height; this.cellSize = 8;
      this.columns = Math.ceil(width / this.cellSize); this.rows = Math.ceil(height / this.cellSize);
      if (this.x?.length !== this.count) {
        this.x = new Float32Array(this.count); this.y = new Float32Array(this.count);
        this.z = new Float32Array(this.count); this.next = new Int32Array(this.count);
      }
      if (this.heads?.length !== this.columns * this.rows) this.heads = new Int32Array(this.columns * this.rows);
      this.heads.fill(-1);
      this.matrix = camera.projectionMatrix.clone().multiply(camera.matrixWorldInverse).multiply(cloud.matrixWorld).elements;
    }
    const started = performance.now(), m = this.matrix, p = this.positions;
    // Check the time in small batches; never scan the full cloud in a hover event.
    while (this.cursor < this.count) {
      const end = Math.min(this.cursor + 256, this.count);
      for (; this.cursor < end; this.cursor++) {
        const slot = this.cursor, index = (this.indices?.[slot] ?? slot) * 3;
        const x = p[index], y = p[index + 1], z = p[index + 2];
        const w = m[3] * x + m[7] * y + m[11] * z + m[15];
        if (!(w > 0)) continue;
        const px = ((m[0]*x + m[4]*y + m[8]*z + m[12])/w + 1) * width / 2;
        const py = (1 - (m[1]*x + m[5]*y + m[9]*z + m[13])/w) * height / 2;
        const depth = (m[2]*x + m[6]*y + m[10]*z + m[14])/w;
        if (!(px >= 0 && px < width && py >= 0 && py < height && depth >= -1 && depth <= 1)) continue;
        const cell = Math.floor(py / this.cellSize) * this.columns + Math.floor(px / this.cellSize);
        this.x[slot] = px; this.y[slot] = py; this.z[slot] = depth;
        this.next[slot] = this.heads[cell]; this.heads[cell] = slot;
      }
      if (performance.now() - started >= budgetMs) break;
    }
    return this.cursor === this.count;
  }
  query(x, y, radius = 5) {
    if (!this.geometry || this.cursor !== this.count) return null;
    let best = null, depth = Infinity, distance = Infinity;
    for (let row = Math.max(0, Math.floor((y-radius)/this.cellSize)); row <= Math.min(this.rows-1, Math.floor((y+radius)/this.cellSize)); row++) {
      for (let col = Math.max(0, Math.floor((x-radius)/this.cellSize)); col <= Math.min(this.columns-1, Math.floor((x+radius)/this.cellSize)); col++) {
        for (let slot = this.heads[row*this.columns+col]; slot !== -1; slot = this.next[slot]) {
          const d = (this.x[slot]-x)**2 + (this.y[slot]-y)**2;
          if (d <= radius**2 && (this.z[slot] < depth || (this.z[slot] === depth && d < distance))) {
            best = this.indices?.[slot] ?? slot; depth = this.z[slot]; distance = d;
          }
        }
      }
    }
    return best;
  }
  get byteLength() { return [this.x, this.y, this.z, this.next, this.heads].reduce((sum, array) => sum + (array?.byteLength ?? 0), 0); }
}
