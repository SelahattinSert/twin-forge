// Read-only CPU microbenchmark; does not launch inference or a browser.
// Usage: node scripts/benchmark_viewer_hover.mjs path/to/preview.tfp
import { readFileSync } from 'node:fs';
import * as THREE from '../src/twinforge/viewer/static/vendor/three.module.min.js';
import { HoverIndex } from '../src/twinforge/viewer/static/hover-index.js';

if (!process.argv[2]) throw new Error('Supply a saved TFP1 preview path.');
const bytes = readFileSync(process.argv[2]);
if (bytes.subarray(0, 4).toString() !== 'TFP1') throw new Error('Expected TFP1 preview.');
const header = JSON.parse(bytes.subarray(8, 8 + bytes.readUInt32LE(4)).toString());
const buffer = bytes.buffer.slice(bytes.byteOffset, bytes.byteOffset + bytes.byteLength);
const column = (name, Type) => {
  const c = header.columns[name]; return new Type(buffer, c.offset, c.bytes / Type.BYTES_PER_ELEMENT);
};
const xyz = column('xyz', Float32Array), valid = column('valid', Uint8Array);
const geometry = new THREE.BufferGeometry().setAttribute('position', new THREE.BufferAttribute(xyz, 3));
geometry.setIndex(Array.from({ length: header.count }, (_, i) => i).filter(i => valid[i] && xyz.subarray(i*3, i*3+3).every(Number.isFinite)));
geometry.computeBoundingSphere();
const cloud = new THREE.Points(geometry, new THREE.PointsMaterial()); cloud.updateMatrixWorld();
const { center, radius } = geometry.boundingSphere;
const width = 1280, height = 720;
const camera = new THREE.PerspectiveCamera(50, width / height, radius / 10000, radius * 1000);
camera.up.set(0, 0, 1); camera.position.copy(center).add(new THREE.Vector3(1,-1.4,.9).normalize().multiplyScalar(radius*2.7));
camera.lookAt(center); camera.updateMatrixWorld();
const index = new HoverIndex(), chunks = [], started = performance.now();
let ready;
do { const t = performance.now(); ready = index.prepare(cloud, camera, width, height); chunks.push(performance.now()-t); } while (!ready);
const coldMs = performance.now() - started;
const raycaster = new THREE.Raycaster(); raycaster.params.Points.threshold = Math.max(radius*.035,.015)*.25;
const queries = [], oldMs = [], newMs = [];
// Aim at actual rendered points, not only empty background.
for (let i = 0; i < 100; i++) {
  const row = geometry.index.array[Math.floor(i*geometry.index.count/100)];
  const p = new THREE.Vector3().fromArray(xyz, row*3).project(camera);
  queries.push([(p.x+1)*width/2, (1-p.y)*height/2]);
}
for (const [x, y] of queries) {
  raycaster.setFromCamera(new THREE.Vector2(x/width*2-1, 1-y/height*2), camera);
  let t = performance.now(); raycaster.intersectObject(cloud); oldMs.push(performance.now()-t);
  t = performance.now(); index.prepare(cloud,camera,width,height); index.query(x,y); newMs.push(performance.now()-t);
}
const percentile = (samples, p) => [...samples].sort((a,b)=>a-b)[Math.ceil(samples.length*p)-1];
console.log(JSON.stringify({
  points: header.count, rendered_points: geometry.index.count, queries: queries.length,
  viewport_css_pixels: [width,height], previous_fixed_hover_delay_ms: 140,
  cold_index_build_ms: coldMs, index_build_chunks: chunks.length, longest_build_chunk_ms: Math.max(...chunks),
  index_bytes: index.byteLength,
  previous_full_raycast_ms: {median:percentile(oldMs,.5),p95:percentile(oldMs,.95)},
  cached_screen_query_including_signature_ms: {median:percentile(newMs,.5),p95:percentile(newMs,.95)},
  limitation: 'Node CPU microbenchmark, not browser FPS or end-to-end latency. Hover uses a CSS-pixel radius and frontmost projected sample; measurement picking remains unchanged.'
}, null, 2));
index.reset(); geometry.dispose(); cloud.material.dispose();
