# TwinForge Phase 1 — Usable Measurement-Assisted Scene Implementation Plan

> **For agentic workers:** Execute the authorized implementation with `executing-plans`, completing the packages in order. Mark checkboxes only after implementation and verification. Preserve the existing uncommitted Phase 0 work.

**Goal:** Turn saved reconstructions into local scenes that users can open with one command, trace back to source observations, measure, and optionally calibrate using one physical reference.

**Architecture:** Retain the video → MapAnything → normalized geometry pipeline. Add a backend-independent saved-scene reader, local viewer, and measurement layer. Calibration creates a separate derived scene. Observation consistency, backend confidence, and physical accuracy remain separate.

**Tech stack:** Existing Python 3.12, NumPy, OpenCV, FFmpeg, and pinned MapAnything; Three.js and plain JavaScript for local rendering. No additional reconstruction model, database, or cloud service.

**Status:** Software implementation delivered on 2026-10-02. All five packages have automated/API verification; the single planned 32-view CPU acceptance completed. Browser visual acceptance remains unverified because the execution environment exposes no browser. See docs/phase1-delivery.md; unchecked visual requirements below remain pending, not waived.

## 1. Phase boundary and scope

Close the Phase 0 research loop with its recorded engineering evidence. Real inference, exports, software infrastructure, and repeatable geometry limitations have been established. General-purpose accurate metric room reconstruction has not been established. Moving to Phase 1 does not relabel that limitation as a success.

Phase 1 delivers an approximate spatial scene workbench that users can open, inspect, annotate, measure, save, and reopen. Unmeasured or inconsistent regions do not acquire an engineering-accuracy claim.

This is the authoritative Phase 1 plan. Historical reports remain unchanged; their suggested next experiments are not automatic tasks.

### Global constraints

- Complete the five delivery packages in the stated order.
- Deliver the first viewer using existing artifacts without waiting for another inference.
- No new backend, COLMAP tuning, M0/M1/M2 run, or DA3 comparison.
- Keep MapAnything 1.1.3 source revision `9d1db2dd728bd8a10e74b15d2eb646e1bf933791` and checkpoint `facebook/map-anything-apache@00f9c245bbcb60522d1ed7f9e9d88462c6e3f38a`.
- Preserve memory-efficient inference, minibatch one, and unmasked raw geometry retention. Record the actual device and precision.
- At most **one planned real inference acceptance run** at the end. A concrete implementation/setup failure permits one technical rerun after correction; undesirable geometry does not.
- No additional video, physical environment, or physical measurement is a prerequisite for the first deliveries.
- Commits, merges, pull requests, and pushes are not automatic steps.
- Every file intended for GitHub must be entirely English: documentation, code, comments, tests, UI text, filenames, and generated repository assets. Private artifacts guaranteed to remain inside ignored `output/` or `samples/` are exempt.
- Preserve existing private videos, benchmark references, and historical reconstruction files. Write new sessions under ignored `output/phase1/`.
- User authorization to implement this plan supersedes the earlier planning-only instruction. All scope and scientific limitations remain binding.

## 2. Verified starting point

| Area | Existing state | Phase 1 decision |
| --- | --- | --- |
| Engine | Ingest, selection, real MapAnything, normalization, PLY/GLB/JSON/depth exports exist in `src/twinforge/`. | Extend rather than rewrite. |
| Resources | Automatic frame budgets, bounded OOM retry, and disk-backed candidates exist. | Preserve these mechanisms. |
| Viewing | Point GLB exists; there is no useful integrated scene-inspection workflow. GLB contains XYZ/RGB only. | First deliverable addresses this gap. |
| Scale | `ScaleEstimate` supports relative, estimated_metric, calibrated_metric, measured_metric. | Reuse these types. |
| Provenance | PLY contains source frame ID, confidence, validity; model pixel indices are generally absent. | Add pixel provenance to new outputs; derive historical mappings only when justified. |
| Quality | `quality.json` reports input/pipeline health rather than geometric accuracy. | Keep it; add separate observation/measurement evidence. |
| Camera research | Repeated COLMAP controls did not establish a stable independent camera solution. | Not a prerequisite for this phase. |
| M0/M1/M2 | Actual controlled runs completed. M1 did not fix door aspect; M2 worsened endpoint consistency; input poses failed validation. | Do not promote these poses to trusted production conditioning. |
| DA3 | GPU 32-view DA3-BASE ran; superior door shape was not established; output is relative. | Do not repeat it as a supposedly new next task. |
| Original MOV | Actual 32-view result exists; some room-height errors improve, but the same door disagrees across views. | A separate inspection dataset, not an automatic winner. |
| 4K input defect | Sharpness is intensity-normalized, not spatial-resolution-normalized; all 65 MOV candidates fell below the blur threshold. | Targeted correction in Package 4. |
| HDR | MOV is HLG/BT.2020; metadata and decode do not explicitly record color conversion. | Make conversion explicit without assuming better geometry. |

Primary scene: **room2-video2**. `room2` remains the secondary poor-capture control.

First reader/viewer fixture: `output/room2-video2/scene.json`, the existing schema-0.1 32-view M0 output. This is a compatibility choice, not selection by smallest physical error. Second fixture: `output/room2-video2-original-20261001/scene/scene.json`. Keep runs separate; do not combine their clouds.

The worktree contains uncommitted Phase 0 hardening. Record its starting state; do not reset, discard, or claim unrelated changes. Continue on the existing feature branch, preserving the implementation on which this plan depends.

## 3. Good observations and one physical measurement

### 3.1 Choosing a view

Selecting a view because it happens to match ground truth would use the answer to choose geometry. A correct-looking door in one view does not validate its ceiling or objects.

Before reading the physical length, establish visible matching physical boundaries, finite valid XYZ, cross-view endpoint and length consistency, and pixel-selection sensitivity. Do not hide inconsistent views by averaging them. Backend confidence and duplicated observations do not replace these checks.

### 3.2 Uniform calibration

An optional measurement-assisted mode is appropriate. Select the same physical endpoints and enter a real length:

`s = physical reference length / reconstructed reference length`

Apply one positive scalar to all points and camera translations. Aspect ratio, curvature, and view disagreement remain unchanged.

Arithmetic illustration using the existing MP4 baseline; **no calibration was performed when preparing this plan**:

| Quantity | Existing | With door-width s≈0.909 | Physical |
| --- | ---: | ---: | ---: |
| Door width | 0.902 m | 0.820 m | 0.820 m |
| Door height | 2.392 m | approximately 2.174 m | 2.000 m |
| Pooled room height | 2.985 m | approximately 2.713 m | 2.300 m |

One scale can correct the control while leaving about 8.7% door-height and 18% room-height error. The MOV view disagreement is worse; one favorable view cannot validate the room.

A manually surveyed CAD room shell would require additional boundaries and measurements, especially the irregular region and opposite wall. It is not promised by this package.

### 3.3 Calibration and checks

The default optional demonstration uses **0.82 m inner door width** only if multi-view correspondence and consistency pass. Freeze its observations before fitting scale; do not choose the best-looking view or reference afterward.

| Reference | Role |
| --- | --- |
| Inner door width 0.82 m | Optional calibration; excluded from accuracy-success statistics when used. |
| Inner door height 2.00 m | Calibration-excluded shape/length check. |
| Corner to outer door casing 1.45 m | Check only when correspondence is adequate. |
| Main floor to main ceiling 2.30 m | Local observed-region checks; repeated patches do not become independent physical references. |
| TV wall to opposite main wall 6.40 m | Unmeasured if trustworthy opposing surfaces are absent. |
| Mirror 1.60 m | Retain provisional/single-view status. |
| Sofa 0.70 m; TV unit 2.00 m | No numeric result without matching physical boundaries. |

The 0.30 m door-top/ceiling gap is derived from 2.30−2.00; it is not a ninth independent measurement. Keep all eight references. These references have already been inspected, so remaining checks are not an untouched blind test set. Excluding them from calibration prevents fitting to them but does not establish cross-environment generalization.

RGB-only use remains available. Historical image-only benchmarks stay intact. Measurement-assisted outputs receive new derivation IDs and separate reports.

## 4. User workflow

1. Open a saved TwinForge scene with one local command.
2. Navigate points, inspect camera positions, and open a camera's source frame.
3. Select boundaries and inspect distance, observation count, and cross-view disagreement.
4. Optionally calibrate with the qualified 0.82 m reference.
5. Switch between source and derived views, inspect remaining checks, export, and reopen.

The delivered representation is point-based, with camera markers, measurement lines, source images, and explicit evidence states. Meshes, texturing, scene completion, and automatic architectural semantics are not required.

Proposed command: `twinforge view output/room2-video2/scene.json --workspace output/phase1/room2-video2`.
It becomes available in Package 1. Calibration/export use the same local interface rather than many additional CLI commands.

## 5. Data and architecture contracts

### 5.1 Dependency direction

`Saved scene → SceneReader → local Viewer → MeasurementSet → uniformly scaled DerivedScene`

Viewer/measurement code must not import MapAnything. Engine must not depend on the viewer. Backend-specific tensor and pixel layout knowledge remains in the adapter. Do not import private experiment modules into production.

### 5.2 Records

| Record | Responsibility |
| --- | --- |
| SceneArtifact | Manifest version/hash, coordinate system, scale, read-only PLY access, cameras, keyframe paths. |
| PreviewBundle | Selected actual points and exact original PLY indices; frame ID and pixel ID when available. Display reduction does not alter measurement data. |
| MeasurementObservation | Scene/hash, frame ID, source/model pixels when available, exact endpoint indices, XYZ, validity, selection origin/time. |
| MeasurementRecord | Reference/quantity, per-view observations and lengths, spread, correspondence state, optional physical value, calibration/check_only role. |
| GeometryEvidence | consistent_observations / conflicting_observations / insufficient_evidence for the examined measurement, with calculations and reasons. |
| CalibrationRecord | One s, control ID, original scale, artifact hashes, source/physical units, optional user-supplied measurement tolerance. |
| DerivedScene | Source link, transform, new geometry/cameras/depth references, calibration and check reports. |

No giant arrays in JSON. Records have schema_version. New scene fields use 0.2; keep 0.1 readable. Support the explicitly known original-MOV experimental schema through a limited import path; reject unknown schemas.

### 5.3 Independent states

Display separately:
- Scale: relative / estimated_metric / calibrated_metric.
- Measurement evidence: consistent / conflicting / insufficient.
- Use status: visualization_only or partially_checked, with per-reference outcomes rather than whole-scene accuracy percentages.

calibrated_metric means one physical control established scale. It does not validate every object or the entire room. Raw confidence is separately labeled.

### 5.4 Bounded consistency policy

Package 2 compares explicitly identified physical endpoints, not arbitrary all-scene matches.

- At least two distinct, nonduplicate source views; show observation count and limited support from nearby views.
- Finite valid endpoints; no invented source/model mapping.
- Report length spread `(max−min)/median` and corresponding endpoint XYZ spread divided by median segment length.
- Initial calibration thresholds: length spread ≤5%, endpoint spread ≤10% of reference length. These are configurable engineering selection heuristics, not accuracy guarantees.
- For ±2-model-pixel endpoint neighborhoods, P95−P5 distance span must be ≤10% of median length. Missing pixel provenance/sensitivity prevents automatic calibration qualification while leaving 3D inspection usable. This is not a statistical confidence interval.
- Apply thresholds before reading the physical length. Do not relax them to improve benchmark results; record missing coverage and rejection reasons.

These checks assess same-model internal consistency, not independent camera correctness. Two views can share the same wrong shape. A qualified segment does not qualify all points in its ROI.

## 6. Delivery packages

### Package 1 — Open and inspect saved scenes

**Delivery:** View the existing primary scene, cameras, and source frames without new inference.

**Files:**
- Create `src/twinforge/scene/{__init__,reader,types}.py`.
- Create `src/twinforge/viewer/{__init__,server,preview}.py`.
- Create `src/twinforge/viewer/static/{index.html,app.js,styles.css}` and pinned licensed Three.js modules under `static/vendor/`.
- Modify `src/twinforge/cli.py`, `pyproject.toml`, `docs/dependencies.md`.
- Tests: `tests/unit/test_scene_reader.py`, `test_preview.py`, `tests/integration/test_viewer.py`.

**Interfaces:** SceneReader normalizes the two known schemas to SceneArtifact. build_preview produces PreviewBundle; viewer consumes only backend-independent records.

- [x] Record the starting worktree and protected scene hashes under output/phase1/development.
- [x] Read binary little-endian PLY by property name; support optional confidence/frame/valid fields. Reject malformed byte counts, missing referenced files, unsupported schemas.
- [x] Deterministically distribute at most 500,000 actual preview points across frames, retaining exact PLY indices without voxel averaging. Show original and displayed counts.
- [x] Provide complete per-frame points and source image access for later measurements.
- [ ] Render colored Points/BufferGeometry with orbit/pan/zoom, camera trajectory and selection. Z-up display must not rescale stored XYZ or imply measured gravity.
- [x] Add model-free twinforge view with bundled local assets and no runtime CDN/internet. Print the local URL if automatic browser launch fails.
- [x] Bind only loopback; preserve source files read-only; write annotations only to the chosen workspace. Reject path escapes and exports over source directories.
- [ ] Test a small synthetic scene, then open both real fixtures in a browser and capture verification screenshots.

**Acceptance:** Navigation and correct source JPEG selection work without loading weights. Protected hashes unchanged. Measure the 500k-point first-view target of 10 seconds on this machine rather than claiming it universally.

**Stop:** Proceed to Package 2 when viewing/source association works; do not add mesh or texturing work.

### Package 2 — Measurement, provenance, disagreement

**Delivery:** Select physical endpoints, review them in another view, and inspect disagreement.

**Files:**
- Create `src/twinforge/measurements/{__init__,types,observations,consistency,storage}.py`.
- Create `src/twinforge/scene/provenance.py`.
- Modify core/types.py, backends/mapanything.py, backends/mapanything_outputs.py, export/ply.py, reconstruction/orchestrator.py, and viewer files.
- Tests: unit/test_measurements.py, test_geometry_evidence.py, test_pixel_provenance.py and existing adapter/export tests.

**Interfaces:** MeasurementObservation uses exact PLY indices. measure_segment calculates length; evaluate_observations produces GeometryEvidence without physical lengths as input.

- [x] Enable 3D point picking and measurement lines with source frame IDs; resolve preview picks through original indices.
- [x] Enable image endpoint picking only when pixel/XYZ provenance is justified. Record grid, crop/resize, pixel-center convention.
- [x] Generate source_pixel_index = v×model_width+u before finite/stride selection in new outputs; apply the identical point mask. Export it as an optional PLY property.
- [x] Record actual official preprocessing dimensions/transforms in the adapter; do not guess crop from size ratios or replace native learned-ray XYZ by K backprojection.
- [x] Derive historical pixel indices only after verifying full-grid counts, stride, ordering, and finite-point conditions. Label them derived; otherwise retain frame links with unavailable pixel mapping.
- [x] Import frozen door references into the workspace with hashes/reasons; do not reselect boundaries for favorable results.
- [x] Show all per-view lengths, endpoint spread, pixel sensitivity, and raw confidence under the policy in 5.4. Reopening a saved record must select the same points.
- [x] Provide RGB/source-view/evidence views. Unknown regions do not become green-qualified. Persist manually hidden views/ROIs without labeling them corrected.
- [x] Test correct synthetic paired observations, a 25% disagreement, invalid/masked points, missing provenance, and invariance under rigid world transforms.

**Acceptance:** Observation agreement is computed without ground truth; stable historical door views and conflicting MOV views are visible separately. Averaging must not conceal contradiction.

**Stop:** Endpoint measurements and historical-report provenance only. No dense matching, new plane segmentation, or SLAM; keep historical floor/ceiling reports intact.

### Package 3 — One-reference calibration and derived export

**Delivery:** Enter a qualified real distance, inspect s and remaining checks, save a calibrated copy.

**Files:**
- Create measurements/calibration.py and scene/derive.py.
- Modify measurement types/storage, viewer, and minimal existing export/JSON helpers.
- Tests: unit/test_calibration.py, integration/test_calibrated_scene.py.

**Interfaces:** fit_uniform_scale accepts a qualified MeasurementRecord and physical reference to produce CalibrationRecord. derive_scene applies it once to SceneArtifact and writes a separate DerivedScene.

- [x] Validate explicit cm/m units, positive finite physical length, nonzero reconstructed segment. Do not invent measurement tolerance.
- [x] Freeze observations before computing s from their median. Reject conflicting controls rather than silently selecting a favorable view.
- [x] Apply the same positive s to XYZ, camera centers, and derived camera-Z depth. Preserve rotations, intrinsics, rays, pixel indices, and confidence.
- [x] Never multiply camera rotation blocks by s. Export metre coordinates with meters_per_unit=1; store s as audit data and prevent double application.
- [x] Preserve original estimated_metric details. Derived scale is calibrated_metric with unavailable confidence; retain independent evidence/coverage states.
- [x] Show source/derived views, control, scalar, view count, and calibration-excluded checks. Control residual is not a success statistic. Browser interaction remains unverified.
- [x] Export new PLY/GLB/cameras/records without changing protected files. Scale depth correctly or omit its reference; never attach old depth with incorrect units.
- [x] Test uniform axis/random-distance scaling, invariant aspect ratios and projections when p/t scale together, repeated-export handling, and source overwrite protection.
- [x] Demonstrate the 0.82 m control if qualified; report independent door-height/other checks and preserve uncertain TV/sofa/opposite-wall status.

**Acceptance:** One uniform scalar, preserved source, reopenable derived output, visible remaining errors. Unsupported calibration explains the reason while raw viewing remains usable.

**Stop:** No per-axis/per-view scale, affine fitting, hidden multi-reference fitting, or manually repaired room shell.

### Package 4 — Reliable original-phone-video ingest

**Delivery:** Original MOV candidates receive resolution-aware quality analysis and recorded color/dimension transforms.

**Files:**
- Modify keyframes/quality.py, selector.py, ingest/video.py, config.py, core/types.py, reconstruction/orchestrator.py.
- Create ingest/color.py for policy/filter construction.
- Tests: unit/test_quality.py, test_video.py, test_color_policy.py, integration/test_video_preprocessing.py.

**Interfaces:** Optional color primaries/transfer/matrix/range/pixel-format metadata. Sharpness uses a separate analysis image without modifying inference JPEG geometry.

- [x] Analyze sharpness on aspect-preserving images with longest edge ≤512 pixels; never upscale smaller images. Record analysis dimensions and correct misleading documentation.
- [x] Test sharp/blurred versions of the same scene across resolutions; reject actual severe blur. Do not target all images passing or tune against physical errors.
- [x] Run inexpensive MOV decode/selection; eliminate resolution-caused blanket rejection and record remaining reasons. No neural inference in this step.
- [x] Read HLG/PQ/SDR metadata. Bypass HDR conversion for SDR; explicitly record missing/conflicting metadata and support a user-specified color policy when needed.
- [x] Use one versioned HDR→SDR path: metadata-aware linearization → fixed Hable tone mapping → BT.709/sRGB → recorded 8-bit input. Record white/peak assumptions, FFmpeg version and exact filters; no parameter sweep.
- [x] zscale/tonemap availability was checked during planning. On other systems, missing filters produce actionable setup/SDR-input errors, not silent alternate transforms. HLG display assumptions are not physical camera calibration.
- [x] Preserve the audited rotation/coordinate chain; record source/display/JPEG/model dimensions and crop/resize transforms. Avoid double rotation.
- [x] Test HDR gradients, SDR bypass, portrait rotation and pixel mapping deterministically. Do not regenerate old outputs under the new policy.

**Acceptance:** Reproducible clear input path; original MOV reaches selection without a special bypass. This alone does not demonstrate improved geometry.

**Stop:** No HDR/resize inference matrix or reopened capture-quality research.

### Package 5 — Acceptance workflow, documentation, closure

**Delivery:** Repeatable usage, openable source/derived examples, report of software and geometry limits.

**Files:**
- Create integration/test_scene_workflow.py, docs/phase1-usage.md, docs/phase1-delivery.md.
- Modify README, architecture/decisions/dependencies docs and this progress checklist.
- Private artifacts remain under output/phase1; samples/output remain ignored.

- [x] Run lightweight tests, lint/format, fake-backend end-to-end scene flow. Viewer/calibration must not require model downloads. Final: 259 passed, one opt-in smoke skipped; Ruff clean.
- [x] Complete existing-scene open → source frame → paired measure → qualified calibration → export → reopen; verify protected hashes. Automated/API and saved real artifacts verified; interactive browser execution remains separately pending.
- [x] Perform one normal CLI acceptance on samples/room2-video2.MOV: pinned MapAnything, CPU, at most 32 selected views, automatic reduction/OOM retry disabled. Actual: 129 candidates, 32 normally selected views, no bypass/reduction.
- [x] Label this a product acceptance run, not a controlled model comparison: selection/color policy changed. API artifact usability verified; rendered browser usability not claimed.
- [x] If resources prevent inference, record the actual obstacle and retain viewer delivery. Completed successfully; one planned run used, zero technical reruns used.
- [x] Record frames, timings, RAM/VRAM accessibility, points/cameras, scale source, and observed conflicts. Actual: CPU, 974.34 seconds, 9.22 GiB peak RSS, 4,873,344 points, 32 cameras, estimated_metric. CUDA unavailable to the executing process.
- [x] Correct stale README claims that physical accuracy was never evaluated: evaluation occurred but did not prove sufficient accuracy. Historical reports unchanged.
- [x] Report software/workflow delivery and geometric use limits independently.

**Acceptance:** User opens, traces, measures, calibrates when qualified or sees the reason, exports and reopens. Documented commands exist. Historical benchmarks remain intact. Failed results are not described as successful.

**Stop:** Write closure report and end this phase; no automatic new model investigation.

## 7. Workspace layout

Under output/phase1/room2-video2:

| Artifact | Meaning |
| --- | --- |
| session.json | Source/hash, view selections, software/schema. |
| preview/ | Regenerable bounded display data, not measurement authority. |
| measurements.json | Physical boundaries, all per-view observations, calibration/check roles. |
| geometry-evidence.json | Evidence only for examined measurements; unknown coverage explicit. |
| calibration.json | s/provenance or rejection reason. |
| derived/scene.json | New source-linked manifest. |
| derived/pointcloud.ply, preview.glb, cameras.json | Uniformly scaled outputs. |
| derived/depthmaps.npz | Correctly scaled if included; omit when units are unresolved. |
| check-report.json | Calibration-excluded references, unmeasurable states, coverage. |

Sessions can be saved/reopened. Source scenes remain available. Private images, marked photos, model cache and generated scenes stay outside the repository.

## 8. Progress and effort budget

| Order | Delivery | New neural experiment | Estimated engineering effort |
| --- | --- | ---: | ---: |
| 1 | Viewer | 0 | 1–2 days |
| 2 | Measurements/provenance/consistency | 0 | 2–3 days |
| 3 | Uniform calibration/derived export | 0 | 1–2 days |
| 4 | Resolution/HDR ingest | 0 | 1–2 days |
| 5 | Acceptance and closure | At most one planned run | 0.5–1 day |

These are engineering estimates, not calendar promises. Approximately 6–10 engineering days overall; the first visible delivery comes after Package 1. Historical CPU 32-view inference took approximately 14–15 minutes, not the full development effort.

Progress updates identify the completed package, visible output, remaining packages and concrete blockers. Proceed when acceptance passes; routine choices do not require another approval loop.

## 9. Closure checklist

- [x] Open existing geometry and associate source images through saved artifacts/API; rendered navigation remains pending below.
- [x] Measure exact point identities and reopen selections through automated/API workflow; browser picking remains pending below.
- [x] Compute multi-view agreement without physical lengths.
- [x] Derive uniformly calibrated copies where qualified; preserve shape errors.
- [x] No XYZ smoothing/warping/fusion beyond the explicit uniform scalar.
- [x] Record phone-video dimensions/color transforms; fix known sharpness defect.
- [x] Complete lightweight tests and usage checks; explicitly report unavailable acceptance steps.
- [x] Separate software delivery from validated geometry in the delivery report.
- [ ] Verify real browser rendering/navigation/picking and collect screenshots/first-render timing. No browser surface was available; HTTP tests do not close this requirement.

If shape remains wrong, scene status stays visualization_only or partially_checked. Adding convenient references does not change that. The product is the viewing/measurement/calibration workflow; a perfect automatic room model is not claimed.

Decide Phase 2 only after the user sees this delivery. This document does not start Phase 2 model/SLAM/mesh research.

## 10. Evidence reviewed

Paths below are relative to the repository. Private output artifacts may be absent on GitHub.

- README, pyproject, architecture, decisions, dependencies, phase0-hardening-report.
- Existing core/types, config, CLI, ingest/video, keyframes/quality, MapAnything adapter/normalizer, orchestrator, quality analyzer, PLY/GLB exporters.
- output/mapanything-m012-exploratory-20260930/report.md: completed conditioning, persistent shape error, insufficient camera solution.
- output/da3-comparison-20260928/report.md: completed relative comparison; no repetitive new-model task.
- output/camera-local-pairs-20260930/report.md: bounded camera-control failure and stopping result.
- output/room2-video2-original-20261001/report.md: original MOV, blur defect, view conflict/color differences.
- output/door-axis-benchmark-20260927/reviewed-references.json and output/distortion-diagnosis-20260927/image-references.json: frozen independent physical-boundary selections.
- Official Three.js [Points](https://threejs.org/docs/pages/Points.html), [BufferGeometry](https://threejs.org/docs/pages/BufferGeometry.html), [Raycaster](https://threejs.org/docs/pages/Raycaster.html), [MIT license](https://github.com/mrdoob/three.js/blob/dev/LICENSE). Pin the selected distribution and retain its license.
- Installed FFmpeg zscale/tonemap help checked during planning; implementation tests verify conversion behavior.

## 11. Execution status

- [x] Inspect implementation and relevant final research reports.
- [x] Define uniform calibration limits and reference roles.
- [x] Specify packages, acceptance criteria, research bounds, and first visible delivery.
- [x] Package 1 software delivered; browser visual acceptance remains pending.
- [x] Package 2 complete (code/workflow review; browser visual acceptance separately pending).
- [x] Package 3 complete (code/workflow review; browser visual acceptance separately pending).
- [x] Package 4 complete.
- [x] Package 5 software/workflow delivered and report written; browser acceptance boundary explicitly recorded.

**Disposition:** Software delivery closed; one planned real inference completed, no technical rerun. Manual browser acceptance remains pending without any new reconstruction requirement. Historical sources and benchmarks are preserved; no Git publication was performed. No Phase 2 or further model research is started by this closure.
