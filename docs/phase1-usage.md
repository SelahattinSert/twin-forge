# Saved scene workflow

Install the lightweight application with `pip install -e '.[dev]'` in a Python 3.12
environment. Viewing, measuring, and calibrating saved artifacts need neither
MapAnything nor downloaded weights. The viewer uses locally packaged Three.js
and Manrope; it makes no CDN requests.

Open the existing source and a separate writable annotation workspace:

```bash
twinforge view output/room2-video2/scene.json --workspace output/phase1/room2-video2 --no-browser
```

Open the printed loopback URL in a WebGL-capable browser. The large point-cloud
view sits beside an inspector with freely selectable **Inspect**, **Measure**,
and optional **Calibrate** steps. Select a source frame
and inspect its original saved image. Display point reduction retains exact PLY
row identities; measurements use original XYZ. Source image picking is available
only when the saved source/model pixel transform and point pixel IDs are proven.
Unavailable provenance is reported rather than inferred from point count.

In Measure, start with a blank reference identifier and the generic Segment
quantity. For example, use `reference-01`. Identifiers start with an ASCII letter
or digit and may contain letters, digits, underscores, periods, or hyphens, up to
100 characters. Width and Height are available when those labels fit the task.
No object type is required. The shared Camera & image card stays available in
each step, including while choosing image endpoints.

Identify the same physical endpoints in at least two distinct source views.
Save both observations under one reference and explicitly confirm correspondence.
The viewer reports observation count, length spread, endpoint spread, and endpoint
pixel sensitivity. Nearby views provide limited support because model and camera
errors can be shared. Missing pixel neighborhoods or provenance prevents automatic
calibration qualification while leaving 3D inspection available.

Reopen existing measurements in **Saved in this scene**. These are scene-bound
workspace records, not defaults for a new scene. **New reference** clears the
identifier, endpoint picks, correspondence confirmation, qualification selection,
and physical-length entry. Editing the identifier or quantity also invalidates
the previous selection; finish naming the reference before picking endpoints.
Numerical evidence, raw confidence, hashes, pixel diagnostics, and visibility
tools remain available in expandable details.

Qualification occurs before the physical length is read. Default engineering
thresholds are 5% length spread, 10% endpoint spread, and a complete ±2-model-pixel
P95−P5 distance span no greater than 10% of median length. These are selection
heuristics, not accuracy guarantees or statistical confidence intervals.

Calibration is optional. For an active qualified source reference, select
Calibrate and explicitly enter a finite positive physical value and `m` or `cm`
unit. There is no default physical length. Selecting or editing a reference,
opening an archive, starting a new reference, or switching scene copies clears
the length. Archived/control lengths never populate this entry. The disabled
calibration action explains its missing requirement. Save a uniform calibrated
copy in the workspace's separate derived directory. One scalar scales all XYZ,
camera translations, and recognized camera-Z depth; camera rotations and intrinsics
remain unchanged. Existing destinations, source overlap, and repeated calibration
are rejected. The source stays intact and the export retains calibration, frozen
observations, and control-excluded checks. When a copy is already saved, use the
scene-copy selector; the UI disables repeated export and retains the report.
Reopen the delivered example:

```bash
twinforge view output/phase1/room2-video2/derived/scene.json --no-browser
```

Direct derived reopening displays the frozen calibration and control-excluded
checks, with a separate read-only exported-source reference selector. Original
observation hashes, XYZ, roles, and source image identities are retained. Lines
use the recorded scalar once for display on already scaled geometry. Validation
binds the archive to derivation hashes and checks endpoint rows and copied image
hashes; it does not reopen external historical evidence files. An unsupported,
unsafe, or stale archive shows an explicit unavailable reason. New measurements
belong to the separate active workspace and cannot overwrite these archives.
The frozen control and control-excluded checks are also shown read-only in
**Calibrate** when opening a calibrated export directly. An unavailable archive
is reported explicitly; its physical control is never filled into the entry form.
The **Exported source archive** section is explicitly read-only; use New reference
to leave it before adding observations to the active scene workspace.

Scale (`relative`, `estimated_metric`, `calibrated_metric`), per-reference evidence
(`consistent`, `conflicting`, `insufficient`), and use status (`visualization_only`,
`partially_checked`) answer different questions. Calibrated metric establishes
scale from one physical control. It does not certify the room or correct shape.
Manual hiding is a visibility annotation, not geometry repair. Raw confidence is
an uncalibrated model score.

See [UI refresh notes](phase1-ui-refresh.md) for interaction details and the
current browser-validation limitations.

Run the repeatable offline workflow test without neural inference:

```bash
.venv/bin/pytest tests/integration/test_scene_workflow.py -q
```

The final product acceptance command uses the cached immutable checkpoint:

```bash
HF_HOME="$PWD/.model-cache/huggingface" TORCH_HOME="$PWD/.model-cache/torch" \
HF_HUB_OFFLINE=1 OMP_NUM_THREADS=8 MKL_NUM_THREADS=8 \
.venv/bin/twinforge reconstruct samples/room2-video2.MOV \
  --output output/phase1/acceptance --max-keyframes 32 --device cpu \
  --checkpoint facebook/map-anything-apache \
  --checkpoint-revision 00f9c245bbcb60522d1ed7f9e9d88462c6e3f38a \
  --no-auto-budget --no-oom-retry
```

This command documents the single planned acceptance, not an invitation to launch
another reconstruction during this phase. Selection may retain fewer than 32
usable views. Defaults use 0.5-second candidate sampling, width bounded to 1920,
and automatic color policy. FFmpeg must provide zscale and tonemap for HDR input.
The fixed Hable/sRGB policy and model preprocessing are recorded separately.
Private scenes, videos, and model caches remain in ignored directories.
