# Camera previews and geometry-preservation audit

## Scope

Read-only viewer improvements: camera icons, responsive hover context, small
source thumbnails and bounded caches. No model, inference, calibration, pose,
point-cloud export or benchmark was changed. No reconstruction was started.

## Reported doubled furniture

Both ready development scenes were audited against their existing registered
run hashes. All 37 references in the linked original-source run and all 40
references in the managed-video run matched, including point cloud, cameras,
manifest and source photographs. The managed run's prepared preview hash also
matched its saved record.

Each cloud contains 4,873,344 source rows. Both 500,000-row previews have unique
source row indices, and every preview XYZ is exactly equal to its referenced PLY
row (maximum coordinate difference: **0.0**).

The actual `display()` routine was exercised repeatedly with bundled Three.js:
it removes/disposes the previous point cloud, creates exactly one replacement,
passes the original XYZ array unchanged, and applies an identity world matrix.
Visibility controls change only the rendered index list. Camera overlays have
separate object types and do not add point-cloud rows.

This rules out the inspected UI replacement/transport paths duplicating or
reflecting geometry. It does **not** establish the exact cause of the reported
sofa appearance. Disagreeing per-view reconstructed surfaces can produce
ghosting in the unchanged all-view cloud. Identifying that specific sofa's
contributing frame clusters requires its exact scene/view or screenshot;
this audit did not invent a semantic correspondence or hide suspected points.

## Implementation

- Camera icons share a 64-by-64 local SVG texture and sprite material, sit at
  saved camera centers, and retain depth testing. They are never exported.
- Camera hit testing runs first over the small overlay set. No dense cloud scan
  is required to open a camera photo.
- Hover pointer events coalesce through `requestAnimationFrame`; the previous
  140 ms debounce is removed.
- Dense point hover uses a typed-array screen-space index of rendered rows.
  A completed index queries nearby cells and selects the frontmost projected
  sample inside a CSS-pixel radius. Building uses approximately 3 ms batches;
  camera, projection, viewport or geometry changes invalidate it. No source
  points are moved, averaged, fabricated or silently discarded.
- Click-to-measure and exact source-image endpoint picking are unchanged.
- Hover/timeline thumbnails have a 320-pixel maximum long edge. The original
  source-photo editor retains full-size images and unchanged provenance.
- Server caches are capped at 32 thumbnails / 4 MiB per scene service and decode
  serially within that service. Browser hover caches retain eight decoded image
  elements, cancel superseded requests, and reuse the loaded DOM image rather
  than issuing a second no-store URL request.
- Scene replacement and page teardown release old overlays, index buffers and
  preview resources. No external service, hosted font or image dependency added.

## Measurements on the saved managed preview

The automatic hover interaction was subsequently narrowed to camera icons/path
positions following the sticky-card report. The following dense-index timings
describe the retained diagnostic picker, not work performed on camera hover.
Automatic camera previews now avoid building the 7.68 MiB grid entirely.

Bundled Three.js and Node, 500,000 rendered points, 1280-by-720 viewport,
100 queries aimed at actual source samples:

| CPU operation | Median | P95 |
| --- | ---: | ---: |
| Previous full-cloud Three.js raycast | 6.882 ms | 7.631 ms |
| Cached screen query, including camera signature check | 0.055 ms | 0.106 ms |

The previous fixed 140 ms wait was additional to raycast time. Cold grid build
took 25.559 ms total CPU over nine chunks; the longest measured chunk was
3.494 ms. The index occupied 8,057,600 bytes (about 7.68 MiB), not one JavaScript
object per point. Browser scheduling spreads chunks across animation frames,
so cold/changed-camera point previews still have a warm-up period. Camera
previews do not wait for that grid.

These are CPU microbenchmarks, **not** rendered browser FPS or end-to-end latency
claims. The previous world-distance raycast and new CSS-pixel hover picker do
not have identical selection tolerances. Geometry and measurement picking are
unchanged. Dense overlapping screen cells can still increase query work.

Read-only thumbnail audit for the two scenes:

| Scene run | Original photos, total | Thumbnails, total | Cold encode median | Cached lookup median |
| --- | ---: | ---: | ---: | ---: |
| Linked original source | 11,568,473 B | 302,363 B | 27.482 ms | 0.025 ms |
| Managed video | 12,378,007 B | 313,869 B | 38.938 ms | 0.030 ms |

That reduces encoded photo bytes by approximately 97.4–97.5% for these 32-view
sets. It is not a promise for arbitrary images or a measurement of network
latency. Full-resolution measurement photographs remain available separately.

## Reproducing the diagnostics

```bash
node scripts/benchmark_viewer_hover.mjs path/to/preview.tfp
.venv/bin/python scripts/audit_viewer_artifacts.py path/to/run.json
```

Both commands read existing data and print JSON to stdout. They do not modify
artifacts. The artifact audit can also build a deterministic preview in RAM for
linked scenes without a saved preview file.

## Acceptance

Final lightweight suite: **527 passed, 1 skipped** (the opt-in model smoke
test), in 145.60 seconds. The focused viewer/measurement suite passed 74 tests;
three isolated thumbnail/module HTTP checks passed. Ruff lint, formatting,
JavaScript syntax checks and tracked-diff whitespace checks passed.

Automated coverage includes real Three.js display replacement, camera icon
positions/resource sharing, screen queries against an independent brute-force
projection, frontmost/hidden/offscreen rows, camera/geometry invalidation,
incremental work and teardown. Preview tests cover event coalescing, photo races,
cancelled requests, bounded caching, exact source frame navigation and missing
provenance. HTTP tests cover thumbnail sizing, original preservation, invalid
images and per-scene routing/cache isolation.

No enabled browser surface was available for rendered WebGL acceptance. Restart
the application to load the Python thumbnail endpoint, then hard-refresh the
scene. Check camera icons, immediate camera-card context, photo click-to-look,
rapid switching, clipping, source/derived copies and original-image measurement
picking in a WebGL-enabled browser. The existing suite's heavyweight inference
test remains explicitly opt-in; this UI work does not require new inference.

## Hover dismissal follow-up

The reported scene URL identifies the existing managed run `run_52b21fc55df7460bb632a615e3405a0a`,
whose source point cloud was produced on October 8. This is not the October 1
linked reconstruction. Both use 32 views but different timestamp selections;
the existing registered artifact hashes still match. The screenshot alone does
not establish a before/after geometric regression in the same saved run.
The running loopback server was queried read-only at the supplied scene API:
its active point-cloud hash also matched the registered managed run (`d18b5b991ed9…`),
with 4,873,344 source rows and a 500,000-row default preview.
No geometry was rewritten to conceal the reported overlapping furniture.

Two interaction issues explained the apparently sticky popup: repeated pointer
misses restarted its dismissal timer, and dense points below camera icons could
immediately substitute a new card. Dismissal now uses a non-extending 70 ms
deadline, a short 90 ms fade, and camera-only automatic targeting. Entering the
card cancels/reverses closure; leaving it for the canvas also closes it without
requiring another pointer move. Mouse-acquired button focus does not pin it;
keyboard focus remains supported. A 120 ms opening animation and all reversal
animations honor reduced-motion preferences and cancel safely on teardown.

Follow-up validation: **532 passed, 1 skipped** in 144.63 seconds; 76 focused
viewer/measurement tests passed. Added regression cases cover non-extending
miss deadlines, stationary exits from the card, mouse versus keyboard focus,
animation reversal/stale completion, reduced motion and camera-only targeting.
JavaScript syntax, Ruff and whitespace checks passed. Rendered browser acceptance
remains manual because no browser control surface was available.
