# Phase 1 delivery and limits

The saved-scene software workflow provides a local offline viewer, source-frame
traceability, exact original-row endpoint measurements, bounded per-reference
consistency checks, one-control uniform calibration, and separate reopenable
derived exports. SceneReader supports the known 0.1 and 0.2 schemas and a limited
explicit historical original-MOV import; unknown schemas are rejected. No dense
arrays are stored in JSON. No new backend, mesh repair, or model comparison is
part of this delivery.

The actual retained source is `output/room2-video2/scene.json`: 4,873,344 points and
32 cameras. Frozen qualified observations are retained in
`output/phase1/workspaces/package2-20261002/mp4/door-width.json`. The delivered
workspace is `output/phase1/room2-video2/`; its primary derived example is
`output/phase1/room2-video2/derived/scene.json`. Source preservation hashes are in
`output/phase1/room2-video2/source-preservation.json`. Historical reports remain
unchanged. These private artifacts are not shipped to GitHub.

The two observed control lengths are 0.8905448814579201 and 0.9137106871033178
source units (median 0.902127784280619). Length spread is 2.567907%, endpoint spread
5.514983%, and complete pixel-neighborhood spans are 5.073812% and 4.773652%.
At physical door width 0.82 m, the scalar is 0.9089621385000242. No measurement
tolerance was supplied. These are frozen Package 3 results, not predictions for
the final MOV acceptance run.

Uniform calibration leaves material geometry error. The door height remains
2.1742863621 m against 2.00 m, and the pooled main floor/ceiling separation remains
2.7130600764 m against 2.30 m. Corner-to-outer-casing distance is 1.4967450213 m
against 1.45 m. Local middle and TV-side floor/ceiling separations are
2.6958873833 m and 2.7235152366 m; the door-side main ceiling is unobserved.
These local patches share one physical reference. Nonparallel plane separation
is not a universal room height. The TV/opposite-wall distance is unmeasured;
mirror, sofa, and TV-unit boundaries remain provisional or unavailable.

The width control is excluded from the seven other reference rows. Previously
inspected reference checks are not blind tests, and uncertain correspondence has
no validated numeric outcome. No whole-scene accuracy percentage is justified.
Physical comparisons occurred and revealed insufficient accuracy; software
health and established scale must not be presented as room accuracy.

The final normal CLI product acceptance uses the original MOV, pinned
MapAnything 1.1.3 source and checkpoint, CPU, no automatic budget or OOM retry,
and at most 32 normally selected views. Selection and color policy changed, so
this is a product workflow acceptance rather than a controlled model comparison.
The planned run completed on 2026-10-02 with exit status 0. Output is
`output/phase1/acceptance/room2-video2/scene.json`. No technical rerun was needed.

| Acceptance measurement | Observed result |
| --- | --- |
| Input | Original HEVC/HLG MOV, 64.543 s, approximately 60 FPS |
| Encoded / display dimensions | 3840×2160 / 2160×3840; rotation 270 degrees |
| Candidates / selected views | 129 / 32; no quality bypass or view reduction |
| Selected time span | 0–64 s; adjacent gaps 2–3 s |
| Saved JPEG / model grid | 1920×3414 / 294×518 |
| Device | CPU, 8 threads; CUDA unavailable to this process |
| Total elapsed / peak process RSS | 974.34 s (16 min 14 s) / 9,664,124 KiB (9.22 GiB) |
| Selection / model loading / inference / export | 54.50 / 22.09 / 893.47 / 2.17 s |
| Points / cameras / depth maps | 4,873,344 / 32 / 32 |
| Scale | estimated_metric, meters_per_unit=1, no independent scale confidence |
| Metric scalar reported by backend | 2.1122922897338867; not a calibration or accuracy certificate |
| Raw point confidence median / mean | 1.51155 / 2.54370; uncalibrated model scores |
| Warning | METRIC_SCALE_UNCERTAIN |

MapAnything 1.1.3 source revision is
`9d1db2dd728bd8a10e74b15d2eb646e1bf933791`; checkpoint is
`facebook/map-anything-apache@00f9c245bbcb60522d1ed7f9e9d88462c6e3f38a`.
The process used PyTorch 2.13.0+cu130. CUDA 13.0 is the build version, not evidence
of GPU execution. Precision metadata records float32 input/export geometry, AMP
requested with bfloat16, and the official helper's effective autocast dtype
`torch.float16`. This does not mean every operation or parameter used float16.
Memory-efficient inference and dense-head minibatch one were retained.

The fixed `phone-hable-srgb-v1` conversion assumes 100-nit reference white and
1000-nit peak. Its exact FFmpeg filter, source/display/JPEG pixel transforms,
official resize/crop dimensions and pixel-center conventions are recorded in
the run and scene metadata. Integer resize produced 294×522, followed by the
official crop to 294×518. Source 4K dimensions therefore do not become a 4K neural
input. This acceptance changes ingest/selection and must not be used as a
controlled comparison against historical benchmark runs.

Independent read-only checks examined all finite XYZ/confidence rows, matching
frame/camera IDs, all 32 native pixel grids, actual saved JPEG dimensions, all
depth/confidence/validity arrays, and 500,000 exact original preview rows. The
saved scene opened without importing Torch or MapAnything. These establish
artifact integrity, not physical geometry accuracy. No new ground-truth
benchmark or calibration was performed on this acceptance scene. Normalized
geometry and camera-Z depth are retained; original native learned-ray tensors
and pre-metric geometry are not newly archived in this scope.

Final lightweight validation: 259 tests passed in 13.92 seconds, one opt-in
model smoke test skipped; Ruff passed and 67 Python files were already
formatted. Derivation and storage share source-authoritative observation
resolution: supplied validity, pixel provenance and sensitivity cannot qualify
a control unless they match its source rows and transforms. Exported derived scenes expose frozen source
observations, calibration and excluded checks as a separate read-only archive,
not native measurements in the scaled scene's new active workspace.

Real HTTP checks also opened the primary MP4, retained historical MOV, calibrated
derived copy and new acceptance scene, including source JPEGs and exact frame
point bundles. The derived archive remained available in a fresh workspace.
All seven recorded protected historical artifact/reference hashes were unchanged.

Browser/WebGL visual acceptance, first-render performance, and interactive picking
remain unverified: CUA has no enabled browser or app. HTTP, binary, and automated
logic tests do not establish visual usability. The saved examples remain available
for manual browser inspection. Installed GPU hardware must be distinguished from
CUDA access in the executing process. No further reconstruction or model research
is authorized by this closure.

## Delivery disposition

All five software packages are implemented and the automated/API workflow is
verified, including export and standalone reopening. The planned real CPU run
completed. The broad code review's provenance-boundary finding was corrected;
two viewer success fixtures were also replaced with real measured native-grid
observations rather than invented qualification fields.

Acceptance is **partial**, not unconditional: browser rendering, navigation,
interactive point/image picking and first-render timing still require manual
verification. The plan retains those unchecked requirements. No additional
inference is necessary for this step. Geometry remains approximate and only
partially checked. No commit, merge, pull request or push was performed; the
existing feature branch and pre-existing uncommitted Phase 0 work are preserved.
