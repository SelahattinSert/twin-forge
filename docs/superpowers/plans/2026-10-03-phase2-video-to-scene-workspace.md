# TwinForge Phase 2 — Video-to-Scene Workspace Plan

> **For agentic workers:** This is the current whole-application product and
> delivery plan. Implementation was authorized after the planning request.
> Use `executing-plans`, work through the
> packages in order, and update the progress ledger here. Do not restart the
> Phase 0 model experiments. Do not require repeated approval for routine choices
> already resolved in this plan. Commits and publication require separate scope.

**Goal:** A person can add their own ordinary video, follow local processing,
open the resulting scene, return to a library of many scenes, and optionally
measure and set scale without managing commands, file paths, or technical reports.

**Architecture:** Add a local application shell and durable job manager around
the existing reconstruction engine and scene workbench. Run expensive work in
one supervised child process at a time. Keep each reconstruction, annotation
session, and calibrated version explicitly bound to its own immutable source.

**Tech stack:** Existing Python 3.12, NumPy, OpenCV, FFmpeg, pinned MapAnything,
plain JavaScript, Three.js, and local Manrope assets. Start with atomic JSON
records and the existing local HTTP foundation; no database, frontend framework,
distributed queue, or cloud service is required for this phase.

**Status:** Implementation authorized on 2026-10-03. P2-01 through P2-03
code/review complete; rendered-browser acceptance pending. P2-04 is in progress.
**Owner:** TwinForge implementation engineer; user performs final usability acceptance.
**Primary platform:** The current local Fedora desktop. Narrow-layout support
does not imply that smartphone browsers run the reconstruction engine.

## 1. Product decision

The application should open to **Scenes**, not directly to a measurement form.
The primary experience is creating and exploring a scene. Measurement and scale
adjustment are optional tools inside that scene. A person should not need to
understand reconstruction models to begin.

The product promise for this phase is: "Add a video of your space, follow its
processing on this computer, and explore the saved result. Keep multiple scenes
organized and inspect the observations behind any measurement."

This is a product workflow milestone. It does not promise a watertight mesh,
photorealism, or accurate dimensions for every recorded environment. A completed
processing job means a result is available to inspect, not that geometry has
passed a physical accuracy benchmark.

### Decisions rather than a list of possibilities

| Decision | Reason and trade-off |
| --- | --- |
| Library first, viewer second | Multiple videos and rooms need a stable home, persistent identities, and a way back. |
| One video creates one scene initially | Keeps the source and result understandable; no multi-video fusion is implied. |
| One active reconstruction, a persistent queue for others | Keeps the interface responsive and avoids competing for the same RAM/VRAM. |
| Local browser application | Reuses working components; installation and app startup remain separate from daily scene tasks. |
| One supported reconstruction method by default | MapAnything is integrated; M0/M1/M2 are conditioning experiments, not three production engines. |
| Scene viewing before measurement | Users receive value even when image picking or calibration is unavailable. |
| Enlarged image editor and a previous-view reference | Makes endpoint identity visible, addressing the actual selection mistakes observed. |
| Plain summaries with expandable evidence | Users can act without reading internal terminology; evidence is still retained. |
| Recoverable archive before permanent deletion | Removes clutter without risking private source or historical experiment files. |

An all-model comparison dashboard is deferred. DA3 and independent camera
solutions need separate integration and quality evidence before becoming choices
for ordinary users. Attractive rendering cannot select the most accurate model.

## 2. Current evidence and gaps

The existing CLI already performs real video ingestion, keyframe selection,
MapAnything reconstruction, normalized export, and resource handling. The viewer
opens saved scenes and supports measurements, consistency checks, uniform scale
adjustment, and separate derived exports. Recent lightweight verification was
283 passed and one heavy smoke test skipped; this planning task does not rerun
or extend that verification.

The user reports successful viewing, a qualified two-view reference, calibration,
and direct reopening with frozen reports. This is user-reported manual evidence;
no new automated browser run, screenshot audit, or first-render timing is claimed.

| Observed gap | Consequence | Phase 2 response |
| --- | --- | --- |
| `twinforge view` requires a prebuilt scene | The user cannot start with their own video in the UI. | Add a local app launcher and Add video workflow. |
| One scene/workspace is attached to a server | No scene library or safe multi-tab scene isolation. | Stable scene/run IDs and request-scoped scene services. |
| CLI processing is synchronous | Browser requests must not wait for model completion. | A supervised worker and durable jobs. |
| Output directory follows the input filename | Two `room.mp4` files can collide. | ID-based storage; user names are display metadata. |
| Existing progress is mostly human log text | No dependable UI state or recovery after refresh. | Typed stage events and saved job state. |
| GPU budgeting may reduce the view set considerably | Fast completion may present very limited coverage. | Explicit resource profiles and visible actual view counts. |
| Small photo with no A/B markers | Clicks are difficult to verify or correct. | Enlarged editor, zoom, markers, line, undo, correction, confirmation. |
| Endpoint identity is explained only in text | Width at several different heights is confused with the same physical segment. | Annotated previous-view reference alongside the next image. |
| Internal reference IDs are user-facing | Naming feels like configuring software. | Automatic IDs and optional human-readable names. |
| Repeated Add observation creates more records | Double clicks or retries can inflate observation counts. | Request idempotency and explicit observation review. |
| Raw evidence dominates results | Users cannot tell what succeeded or what to do next. | Actionable summaries, persistent limits, technical drawer. |
| Historical image picking uses workspace sidecars | A fresh workspace can lose image-to-point mapping. | An explicit validated legacy import path; no manual copy instructions in normal use. |
| Export/reopen still requires terminal paths | The result feels temporary and hard to find. | In-app versions, downloads, and persistent library navigation. |

## 3. The application map

```text
TwinForge
├── Scenes                         default landing page
│   ├── Add video                 select, inspect, configure, start
│   ├── Scene cards               thumbnail, name, status, open
│   ├── Search and status filter
│   └── Archived scenes           restore without deleting data
├── Activity                       active job and queued/failed jobs
├── Scene workspace
│   ├── Explore                   primary 3D view and source photos
│   ├── Measure                   saved measurements and guided observations
│   ├── Set scale                 optional action within Measure
│   ├── Details                   processing, evidence, provenance
│   └── Versions and Export       source result and calibrated copies
└── Settings & setup               runtime readiness and local storage
```

Scenes and Activity are the only primary navigation destinations. Settings is
a utility action. Within a scene, a visible breadcrumb returns to Scenes, and
the header always names the scene and active version. Avoid a large dashboard
of technical statistics before a user has created anything.

### Scenes

Use a responsive grid/list of cards. Each card has a source-image thumbnail
clearly labeled as a photo, editable scene name, creation date, processing state,
and a primary action: Continue setup, View progress, Open scene, or Review issue.
Do not present a source photograph as a rendered 3D preview. A capture of an
actually rendered scene can replace it once available, without extra inference.

Provide search by name, recent/name sorting, status filtering, rename, and archive.
Show an honest empty state with Add video and concise capture guidance. Names
such as Room 1/Room 2/Room 3 are user choices, not room-specific engine semantics.
Duplicate names are allowed; distinct IDs and dates distinguish them.

Run state and geometric evidence are separate. A card can say `Ready to view`
with `Estimated scale`; it must not say `Accurate` because inference succeeded.

## 4. Add video and setup

1. **Select:** Choose or drop one `.mp4`, `.mov`, or `.mkv` file. The app stores a
   managed local copy and shows the destination policy and file size. File choice
   does not start neural inference. Label the action Add video, not cloud upload.
2. **Inspect:** Transfer with actual byte progress, then use the existing ingest
   validation to report duration, display orientation, resolution, and decode
   readiness. FFmpeg validation is authoritative, not the filename extension.
3. **Review:** Offer an editable scene name, oriented preview images, expected
   device/profile, resource notes, and Start processing. Advanced options expose
   existing controls rather than dozens of new settings.
4. **Start:** Persist the job and its input/configuration, show Activity, and let
   the user return to Scenes. Another video can be added and queued.

Browser support for playing a phone codec is not a prerequisite for processing.
If inline playback fails but FFmpeg decodes the file, use decoded stills and say
`Video playback is unavailable in this browser. The file can still be processed.`
Use actual encoded/display properties. A 4K source must not imply a 4K model grid.

Readiness checks cover FFmpeg/ffprobe and required HDR filters, installed backend,
cached checkpoint/revision, usable device in the worker environment, and writable
storage. Viewing existing scenes remains available when reconstruction setup is
missing. Missing weights receive an explicit Prepare model action with the
actual download size when discoverable; do not silently start a multi-GB download
when someone opens the app. Do not run package managers or repair GPU drivers
automatically from the application.

The original file remains byte-identical. Tone mapping, rotation, resizing, and
selected frames retain existing pipeline provenance. Prefer original-phone files
in concise capture help; do not require a particular transfer application.

### Resource decision for this machine

Default the initial product profile to **Standard scene: up to 32 useful images**,
using CPU on the known 6 GiB GPU setup where 32-view CPU execution is established
and a much smaller GPU reconstruction is not an equivalent substitute. Treat the
historical roughly 15–16 minute CPU runs as labeled examples for this machine,
not a promised ETA for another file.

Expose device choice under Advanced. A separate **Quick preview** profile may use
the existing automatic GPU budget and bounded OOM reduction, with explicit text
that fewer images may omit coverage. It is not a competing reconstruction engine.
For Standard, do not automatically reduce a requested view budget after OOM;
offer a new CPU or reduced-preview run. Quality-based selection may legitimately
retain fewer than 32; show why and the actual count. The selected settings,
resource adjustments, and actual device are always recorded with the run.

Larger GPUs are not assumed to fit 32 views without evidence. Reuse existing
memory mechanisms and flags rather than inventing a new capacity guarantee.

## 5. Processing, cancellation, and recovery

The browser submits work and polls saved status. Heavy inference belongs to a
separate process using the same Python environment and pinned backend. The app
stays usable while it runs. Exactly one heavy job is active; others remain queued.

Durable states:

```text
uploading → inspecting → ready_to_start → queued
  → running → validating_output → ready
       └→ cancelling → cancelled
       └→ failed
       └→ interrupted
```

Upload and inspection may also fail or be cancelled. Invalid inputs never enter
the reconstruction queue. Within `running`, report actual stages: selecting
images, loading model, reconstructing, and exporting. Show elapsed time, current
stage, selected image count once known, and actionable warnings. Use numerical
progress only where the work total is known. Neural inference may remain at an
indeterminate stage with a live elapsed timer. A heartbeat means the worker is
alive, not that mathematical progress has been proved. Logs remain in Details.

Closing the browser tab does not stop the application worker. Refreshing or
reopening the app reconnects to the saved job. Closing the local application or
shutting down the computer interrupts processing; do not promise continued work
or in-memory inference resume. Restart reconciles job records with actual worker
ownership and outputs, marks interrupted jobs truthfully, and offers Retry as a
new run. Do not automatically spend compute after a restart.

Cancel stops only the owned worker and its FFmpeg children. Wait for confirmed
termination before releasing the queue slot. A bounded graceful stop may be
followed by forced termination of that owned process group. Preserve diagnostics
and classify partial outputs as incomplete. A ready result must not become
cancelled because a late cancellation races with validated completion.

Validate the completed manifest, files, readable geometry, frame/camera linkage,
and expected provenance before publishing Ready. This is artifact integrity,
not a physical accuracy score. Failed or cancelled runs never become the default
scene version. Existing successful versions remain accessible.

## 6. Scene workspace

Open Explore with the 3D stage dominant. Keep Fit scene, camera navigation, point
size, and source-photo access immediately available. Put identifiers, hashes,
raw confidence, and model settings in Details. Point rendering limitations must
not be concealed by smoothing or invented surfaces.

Use a thumbnail strip with timestamps for selecting source images. Highlight the
selected camera and photograph together. Show whether the photograph supports
image-based measurement and explain unavailable support inline. Keep keyboard
navigation and a compact list alternative to the strip.

Use explicit action labels: `Select points on photo` and `Select points in 3D`.
The latter is an advanced alternative. A short first-use hint distinguishes the
two surfaces. Full frame points and manual visibility remain advanced view tools.
When points are manually hidden, show `Some points are hidden` with Reset view;
visibility is not a reconstruction correction.

Switching scenes disposes old GPU display resources, resets temporary picks,
and resolves the new scene by ID. Saved per-scene view preferences can restore
the selected image and camera position. No server-global "current scene" may
change data belonging to another tab.

## 7. Guided measurement, including the approved image editor

This package incorporates the approved
[source-image selection design](../specs/2026-10-03-source-image-endpoint-selection-design.md).
That document remains the detailed coordinate/editor contract. This Phase 2
plan is the authoritative sequence; do not implement it as an unrelated fork.

### Replace configuration work with a measurement task

The user selects Add measurement. Generate an internal immutable ID and a
default display name such as Measurement 1; let the user rename it freely.
Hide filename-format restrictions. Optional display names are escaped text, never
paths or HTML. UI copy is English; privately stored user-entered names need not
be restricted to English. Existing reference IDs remain valid and visible in
Details. Quantity defaults to Segment; Width/Height remain optional labels.

The flow is `Choose photo → Select A/B → Review → Add observation → Compare in
another photo`. Explain the next action beside the relevant control. Saving must
show success and the saved observation thumbnail, not only a list of coordinates.

### Visible, correct selection

Use a large dialog with the photograph, A/B markers, connecting line, zoom/pan,
Fit image, Undo, Clear, Confirm selection, and Cancel. Two clicks place the
initial endpoints. Selected markers can be dragged or adjusted using the
keyboard. Image panning never places a point. A/B order remains explicit.

Keep source pixels as authoritative selection coordinates and display transforms
separate. Letterboxing, zoom, pan, browser resize, and portrait images must not
change the selected physical pixels. Missing point support produces a reason;
do not silently snap to a nearby surface or generate geometry.

### Help users match the second observation

When choosing another image, show the prior photograph with its annotated A/B
points in a small reference pane next to the large active image. Label it
`Previous observation — match these physical points`. Do not overlay the old
pixel positions onto a different photograph as if they were corresponding points.
Let users enlarge either photo. Do not automatically choose views based on which
measurement best matches a physical answer.

Allow replaying each saved observation on its source photograph. Show the two
source images used, not just `2 views`. Repeated observations in the same image
are distinguishable but do not count as additional independent views.

### Correction without erasing evidence

Prevent double-click/network-retry duplicates with a per-submission idempotency
key. A deliberate new observation still has its own ID. For an accidental saved
selection, offer Correct observation with an explicit old/new revision and a
reason. Preserve the superseded selection in history. Do not quietly remove
disagreement or provide a "keep only good views" action.

An observation frozen into a calibrated export stays frozen there. A correction
updates the active source measurement revision and invalidates its old evidence
until recalculated. It never edits existing derived geometry or reports. This
requires a small versioned measurement-storage extension, not just new buttons.

## 8. Results, scale, versions, and export

Primary summaries describe what the user can do:

| State | Main message and action |
| --- | --- |
| No observations | `Select two points on a source photo.` |
| One useful view | `Add the same points from another image.` |
| Consistent and qualified | `These observations are consistent. You can set scale using this reference.` |
| Conflicting endpoints | `The selected points do not line up across images. Review the observations.` |
| Incomplete support | Explain missing view, pixel support, or correspondence separately. |
| Calibrated version | `Scale set from your reference. Shape accuracy is not verified.` |
| Provisional/unmeasured check | `No evaluated physical-distance comparison is available for this reference.` |

Keep every numerical value and reason in expandable Technical details. A count
of saved references must not imply those references are validated. Preserve
scale, per-reference evidence, and scene-use status as separate concepts.

Set scale appears after opening a qualified source measurement and remains
optional. Show the active reference and two thumbnails, an empty physical-length
field with explicit units, and a concise preview of the uniform scale. Explain
that it applies throughout the scene but cannot fix shape distortion. Save as a
new version; exclude its control from independent accuracy statistics.

Use one source reconstruction per run and zero or more explicitly named
calibrated versions. Implement each calibration through an isolated annotation
session and existing immutable derived export semantics. Preserve its frozen
source observations and reports. Correcting a length creates another version
from the original source, never scales the previous calibrated geometry again.
No version is silently declared "best". The user can choose the default displayed
version, and the header makes that choice visible.

Export is an in-app action for PLY, point-based GLB when available, and a complete
scene package with manifest, camera data, source frames, measurement/provenance
records, and required binary artifacts. Explain that the full package contains
source images of the private space. Generate large downloads on disk and stream
them; do not hold entire PLY or archives in memory. Links come from an allowlisted
artifact map. A full package must reopen without its original workspace paths;
validate packaging of legacy provenance or report the missing dependency.

## 9. Local data model and durability

Keep application storage under the already ignored `output/phase2/library/` by
default, with an explicit alternative root at startup. Do not scan the entire
computer. User names, uploaded files, thumbnails, generated geometry, logs,
and measurement sessions never enter Git by default.

```text
library/
├── library.json                   settings and schema version
├── runtime/                       instance/worker ownership, transient status
├── uploads/<upload_id>/           bounded partial transfer and its receipt
├── scenes/<scene_id>/
│   ├── scene-record.json          name, archive flag, default run/version
│   ├── media/<media_id>/           original video and inspection record
│   └── runs/<run_id>/
│       ├── job.json               durable state, settings, timestamps, failure
│       ├── events.jsonl           bounded structured stage/event history
│       ├── engine-output/         engine-created scene directory and raw exports
│       └── workspaces/<session_id>/
│           ├── measurements and evidence
│           └── derived/           one immutable calibrated export per session
└── exports/<export_id>/            generated portable/download bundles
```

Scene, media, run, session, observation, and version IDs are distinct. The run's
artifact location is recorded from the actual engine return value; do not assume
the user-facing scene name equals a video stem. Scene rename changes metadata
only. A retry gets a new run directory. A new video creates a new scene in this
phase; combining separate room captures is not implied.

Use atomic file replacement, per-record mutations under locks, one application
owner per library, and explicit schema versions. Derived summaries/indexes are
rebuildable; the per-scene and per-run records are authoritative. Persist state
before acknowledging a mutating request. A corrupt scene record is isolated and
reported; it must not prevent opening other scenes.

Archive is reversible and does not free disk. State that clearly. A separate
storage action can remove validated disposable previews/download caches and
incomplete uploads with visible scope. Permanent source/run deletion is deferred
until dependency-aware removal is designed; it is not hidden behind Archive.

Legacy scenes can be imported from an explicitly configured local import root.
The user sees discovered manifests and chooses which to register; no automatic
import of every historical experiment. Referenced sources remain read-only.
An optional existing workspace supplies legacy provenance only after all source
and proof hashes pass the existing validation. A fresh annotation session may
copy that verified mapping without copying measurements. No silent inference
from point counts and no hardcoded `room2` fallback are allowed.

If imported external files are moved, show Source unavailable with Locate source;
rebind only after matching hashes. It is a linked import, clearly distinguished
from a video managed inside the library. Browser file choice provides bytes and
a filename, not a trustworthy absolute source path; use explicit server-side
import roots for linked imports. See the [MDN File API guide](https://developer.mozilla.org/en-US/docs/Web/API/File_API/Using_files_from_web_applications).

## 10. Implementation boundaries and planned contracts

The following are proposed TwinForge interfaces, not claims that these functions
already exist. The existing engine `ReconstructionOrchestrator.run(...)`,
`SceneReader.read()`, `MeasurementStore`, and `derive_scene(...)` remain the
authoritative components they wrap.

```text
Application browser
    ├── Library / upload / activity HTTP routes
    │       ├── LibraryStore        identities and persistent metadata
    │       ├── UploadStore         bounded transfer and inspection
    │       └── JobManager          queue, ownership, state, cancellation
    │               └── worker process
    │                       └── existing ReconstructionOrchestrator
    └── scene/run/session-scoped viewer routes
            └── SceneService       SceneReader + measurements + derivation
```

### Modules and responsibilities

| Planned file | Responsibility |
| --- | --- |
| `src/twinforge/application/types.py` | Versioned scene, media, job, version, and event records. |
| `src/twinforge/application/config.py` | Local roots, upload limits, queue/resource profiles, and bounded caches. |
| `src/twinforge/application/library.py` | Atomic metadata, stable IDs, rename/archive/import, record recovery. |
| `src/twinforge/application/uploads.py` | Stream transfer, receipt validation, input inspection, safe managed files. |
| `src/twinforge/application/readiness.py` | Runtime/checkpoint/device availability and actionable setup states. |
| `src/twinforge/application/jobs.py` | Durable queue, one worker, cancellation, retry, terminal-state reconciliation. |
| `src/twinforge/application/worker.py` | Invoke the existing engine, emit events, isolate heavy dependencies. |
| `src/twinforge/application/exports.py` | Portable bundle manifests, disk-backed assembly, download lifetime. |
| `src/twinforge/application/server.py` | Local app routes, scoped context, upload/download streaming. |
| `src/twinforge/reconstruction/progress.py` | Backend-neutral stage event type and optional callback contract. |
| `src/twinforge/viewer/service.py` | Extract reusable per-artifact/workspace operations from ViewerServer. |
| `src/twinforge/viewer/static/image-selection.js` | Pure coordinate transform and draft-selection state. |
| `src/twinforge/viewer/static/image-editor.js` | Dialog, image load lifecycle, pointer/keyboard interaction and overlays. |
| `src/twinforge/viewer/static/result-summary.js` | Plain-language summaries derived from actual evidence. |
| `src/twinforge/viewer/static/library.js` | Library, add-video and activity interaction. |
| `src/twinforge/viewer/static/scene-client.js` | Resolve API prefix and scene/run/session identity for the viewer. |

Add `__init__.py` where needed. Extend existing static HTML/CSS and package-data
allowlists. Keep modules focused; do not grow `app.js` or `server.py` into a
single application containing library storage, worker management, and geometry.
Reuse presentation helpers and existing measurement algorithms.

The planned launcher is `twinforge app --library ./output/phase2/library`.
It opens Scenes and prints a local fallback URL. Existing `inspect`,
`reconstruct`, and `view` commands continue working. A desktop shortcut can invoke
the same launcher during installation; an Electron/Tauri rewrite or installer
project is not a prerequisite for the browser workflow.

The engine never imports `application` or `viewer`. It may expose an optional
`on_progress` callback receiving a typed event with stage, sequence, event time,
known completed/total counts, message code, and small details. Adding this callback
must preserve existing default CLI behavior and numerical output. Do not parse
third-party console wording to decide whether a stage or run has completed.
Record failures from inspection/selection as well as backend/export stages,
because early failures currently occur before the engine's inference run record.

### Local HTTP contract

| Operation | Proposed route and behavior |
| --- | --- |
| List/create scenes | `GET/POST /api/library/scenes`; stable IDs and summary metadata only. |
| Name/archive | `PATCH /api/library/scenes/{scene_id}`; atomic metadata, no source edits. |
| Transfer | `POST /api/uploads`, then `PUT /api/uploads/{upload_id}/content`; bytes stream to a partial file. |
| Inspect/finish transfer | `POST /api/uploads/{upload_id}/complete`; exact expected bytes, hash, and decode checks. |
| Queue a run | `POST /api/library/scenes/{scene_id}/runs`; validated media/profile and idempotency key. |
| Job status | `GET /api/jobs/{job_id}` and `GET /api/jobs`; small durable state suitable for polling. |
| Cancel/retry | `POST /api/jobs/{job_id}/cancel` or `/retry`; retry creates a new run. |
| View/measure | `/api/scenes/{scene_id}/runs/{run_id}/sessions/{session_id}/...`; existing viewer operations in a fixed context. |
| Export | `POST /api/exports` and `GET /api/exports/{export_id}`; allowlisted version and streamed bundle. |

Browser URLs identify their scene/run/session. The single-scene legacy command
can retain its existing `/api/...` routes. `SceneService` accepts a base URL for
its resource links; do not leave `/api/frames/...` hardcoded to the wrong scene.
Route bindings and source hashes are validated on both reads and writes. Two
tabs with different scenes must never share selected frame, measurement IDs, or
calibration state merely because their reference names match.

Keep large transfer separate from the existing 16 KiB measurement JSON limit.
Use a finite configured upload cap, initially 8 GiB as an application policy,
and reject oversized declarations before receiving the body. Stream bounded
chunks to disk; never base64 or buffer a full video. Store client names only as
metadata. Use generated internal basenames and allowlisted extensions, then
verify contents. Incomplete transfers are not runnable. Interrupted upload
restarts explicitly; resumable chunk transfer is deferred.

Check free disk before accepting a transfer and before decoding/exporting, and
check again during writes. Temporary candidates must live inside the job-owned
scratch directory so cancelled jobs can be recovered/cleaned safely. A storage
estimate may be conservative and labeled; do not promise that video size predicts
final point-cloud or temporary-JPEG size exactly.

Retain loopback binding, validated Host/Origin, static allowlists, path confinement,
and source write protection. Add an instance-bound request token for application
mutations and bounded request handling; do not expose arbitrary shell commands or
filesystem paths through job options. Spawn workers with argument arrays, no
shell interpolation, and owned process-group identity. Python documents this
process model in [subprocess](https://docs.python.org/3.12/library/subprocess.html).

The current [Python HTTP server](https://docs.python.org/3.12/library/http.server.html)
is a local tooling foundation, not an internet deployment platform. Keep Phase 2
loopback-only. An internet/cloud product would require a separate service design;
do not expand this phase by introducing authentication or remote hosting.

### Memory and storage while browsing many scenes

Library cards load metadata and thumbnails only. Do not eagerly create a
500,000-point preview for every scene. Scene services use a bounded cache;
unreferenced memmaps/previews can be released, and large frame bundles are loaded
on demand. The browser disposes Three.js geometry/materials when leaving a scene.
Account for app plus worker memory when reporting measured usage, not only the
model subprocess. Keep original and displayed point counts distinguishable in
Details.

## 11. Delivery packages and acceptance gates

This is one master plan with six bounded delivery packages. Every package has a
usable outcome and a gate. The code steps below specify implementation contracts
and verification, not code written as part of today's planning request. Resolve
local function signatures during each package against its current call sites;
do not invent external backend APIs. No automatic commit step is included.

### P2-01 — Understandable measurement and visible selections

**Outcome:** The current scene workbench becomes usable without coordinate-reading
or verbal coaching. This incorporates the already approved interaction work and
can ship before the multi-scene shell is complete.

**Files:** New `image-selection.js`, `image-editor.js`, `result-summary.js`;
existing `index.html`, `styles.css`, `app.js`, `workspace-ui.js`, static allowlist;
`measurements/types.py` and `storage.py` for optional display names, observation
IDs/revisions, and request idempotency with old-record compatibility.

- [ ] Capture existing source/benchmark hashes and the dirty worktree baseline.
- [ ] Add meaningful failing tests for source-pixel invariance under fit/zoom/pan,
  image letterboxing, A/B order, undo/cancel, stale image loads, and context change.
- [ ] Build the enlarged editor and persistent matching-frame overlays; verify
  pointer and keyboard correction, focus, and no accidental save on cancellation.
- [ ] Add previous-photo reference and observation replay; generate generic IDs
  and human-readable names without changing old saved record identities.
- [ ] Add duplicate-submit prevention and explicit correction history. Preserve
  frozen calibration snapshots and recalculate evidence after active corrections.
- [ ] Add plain summaries for consistent/conflicting/insufficient/unavailable
  evidence, plus the existing full technical report and independent-check limits.
- [ ] Run `pytest tests/unit/test_image_selection.py
  tests/unit/test_viewer_workspace_ui.py tests/unit/test_measurements.py
  tests/integration/test_viewer.py`; retain existing coordinate/scalar tests.
- [ ] Manually select, correct, save, reopen, and compare two observations in a
  real browser. Do not require successful calibration from an inconsistent pick.

**Gate:** A/B remain visibly attached to the selected physical pixels; source
selection is preserved across zoom/resizing and same-reference view comparison;
the main report says what to do next. All data/evidence invariants remain intact.

### P2-02 — Persistent scene library and scoped viewing

**Outcome:** The app starts at Scenes and opens any selected scene safely.

**Files:** `application/{__init__,types,config,library,server}.py`,
`viewer/service.py`, `library.js`, `scene-client.js`; adapt `viewer/server.py`,
`app.js`, `cli.py`, and static packaging. Tests:
`tests/unit/test_library.py`, `tests/integration/test_application_scenes.py`.

- [ ] Define ID-based library records and atomic rename/archive/default-version
  writes with recovery and one owner per library. Preserve legacy scene schemas.
- [ ] Extract per-scene services without changing existing `twinforge view` behavior.
- [ ] Add the launcher, Scenes empty/list states, search/sort, scene cards,
  breadcrumbs, selected version, and per-scene navigation state.
- [ ] Implement explicit linked-scene import from configured roots, optionally
  bringing validated pixel provenance to a fresh session. No automatic historical
  measurement or best-result import.
- [ ] Test two scenes with identical display/reference names, concurrent tabs,
  rename persistence, invalid/moved imports, read-only originals, and bounded caches.
- [ ] Run `pytest tests/unit/test_library.py
  tests/integration/test_application_scenes.py tests/integration/test_viewer.py`.

**Gate:** At least three small synthetic scene records coexist, survive restart,
and open independently; an existing real scene is reachable through the library.
Synthetic fixtures remain explicitly test data, not claimed reconstruction results.

### P2-03 — Add a video with clear readiness and local transfer

**Outcome:** A user supplies an ordinary video entirely through the app and sees
whether it can be processed before launching the model.

**Files:** `application/uploads.py`, `readiness.py`, `config.py`, `server.py`,
`library.js`; reuse `ingest/video.py` and `ingest/color.py`. Tests:
`tests/unit/test_uploads.py`, `tests/integration/test_application_ingest.py`.

- [ ] Implement bounded streamed file transfer, receipts, server-generated paths,
  explicit completion, hashing, partial-file handling, and quota/disk errors.
- [ ] Reuse ffprobe/decode validation and existing oriented/color-correct preview
  logic. Present real dimensions and a still-photo fallback for unsupported playback.
- [ ] Present backend/checkpoint/device readiness with viewing still available.
  Separate model preparation from file selection and processing start.
- [ ] Add name/profile review and Start processing state; processing remains
  disabled for incomplete, invalid, undecodable, or unconfigured input.
- [ ] Test duplicate filenames, Unicode display names, invalid extensions/content,
  disconnected/oversized transfers, missing FFmpeg/model, HLG portrait input,
  and browser-playback-unavailable but decodable input.
- [ ] Run `pytest tests/unit/test_uploads.py
  tests/integration/test_application_ingest.py tests/integration/test_video_preprocessing.py`.

**Gate:** A new video reaches a durable ready-to-start scene with meaningful
feedback and no neural inference merely from selecting or inspecting it.

### P2-04 — Background processing and automatic result opening

**Outcome:** Start processing, leave/return, follow progress, and open the result.

**Files:** `application/jobs.py`, `worker.py`, `types.py`, server/UI activity
routes; `reconstruction/progress.py` and a minimal optional hook in
`orchestrator.py`. Route job scratch through the existing decode flow. Tests:
`tests/unit/test_jobs.py`, `tests/integration/test_application_jobs.py`, and
existing fake-backend/memory retry tests.

- [x] Add durable transitions, idempotent job creation, one-worker queue, event
  sequence, process ownership, and an explicit frozen processing configuration.
- [x] Add typed engine progress events and failure coverage for early stages;
  preserve numerical outputs when no event callback is supplied.
- [x] Implement worker cancellation including children, startup reconciliation,
  interrupted/failed states, and explicit retry into new output directories.
- [x] Validate result integrity and publish the actual returned scene path only
  after success. Build its preview without blocking the application request loop.
- [x] Present stage/elapsed time, resource reductions, queue position, and errors;
  return to the library freely. When ready, show Open scene, not a fake final
  percentage or a mandatory calibration screen.
- [x] Use fake workers for slow stages, OOM, backend crash, early decode failure,
  export failure, duplicate requests, cancellation races, and app restart.
- [x] Run `pytest tests/unit/test_jobs.py tests/integration/test_application_jobs.py
  tests/integration/test_fake_backend_pipeline.py tests/integration/test_memory_retry.py`.

**Gate:** A full synthetic test flow uses the same application job contract;
the interface stays responsive and only one heavy process owns resources.
No fake output is ever exposed as a real user reconstruction.

### P2-05 — Versions, portable exports, and recoverable organization

**Outcome:** Scenes remain usable after restart, recalibration, and export.

**Files:** `application/library.py`, `exports.py`, `server.py`, viewer/UI version
actions; reuse `scene/derive.py`, `viewer/archive.py`, and existing measurements.
Tests: `tests/integration/test_application_versions.py`,
`test_application_exports.py`, existing derived/archive suites.

- [ ] Map each calibrated version to an isolated source-bound session, freeze
  its control, and maintain explicit run/version lineage and default selection.
- [ ] Create another calibrated version from the original source when requested;
  never overwrite an existing one or multiply a previously scaled cloud again.
- [ ] Add visible PLY/GLB/full-package downloads, streamed delivery, package
  provenance, and independent reopening. Report unavailable optional exports.
- [ ] Add rename/archive/restore and explicit storage information; distinguish
  linked original data, managed videos, disposable caches, and retained exports.
- [ ] Test cross-version isolation, moved linked sources, repeated calibration,
  archive restore, large download streaming, portable pixel evidence, and preserved
  frozen reports after active observation correction.
- [ ] Run `pytest tests/integration/test_application_versions.py
  tests/integration/test_application_exports.py tests/integration/test_calibrated_scene.py
  tests/integration/test_derived_archive.py`.

**Gate:** A saved version reopens independently with its images, control, and
reports; source and sibling scenes/versions remain unchanged and recognizable.

### P2-06 — Product acceptance and closure

**Outcome:** The user completes the whole journey without developer assistance.

**Files:** `tests/integration/test_application_workflow.py`,
`docs/phase2-usage.md`, `docs/phase2-delivery.md`, README/architecture updates,
and this progress ledger. Public files remain entirely English.

- [x] Run the full lightweight suite, Ruff/format, JavaScript syntax, offline
  wheel asset checks, and source/benchmark preservation checks.
- [ ] Exercise the new UI in a real browser: keyboard/focus, portrait/landscape
  images, narrow layout, zoomed picking, refresh during processing, two tabs,
  errors, cancel/retry, saved names, versions, and export/reopen.
- [x] Measure library loading without full clouds, first scene display, endpoint
  response, bounded transfer memory, and app-plus-worker peak memory on this host.
  Initial engineering targets: 50 metadata-only cards within 2 seconds, a cached
  500k-point first scene display within 10 seconds, and visible pick feedback on
  the next rendered frame without a server round trip. Report misses honestly;
  these are responsiveness targets, not previously measured guarantees.
- [x] Perform at most one planned real video-to-scene app acceptance with the
  existing original-phone video and documented Standard settings. Reuse existing
  artifacts for other library/viewer checks. A concrete implementation/setup failure
  permits one technical rerun after correction; disappointing shape does not.
- [x] Record actual device, frame count/distribution, stage durations, resource
  use, artifact counts, and outcome. This is product acceptance, not a new model
  comparison or a new physical accuracy claim.
- [ ] Have the user add a video, return to a multi-scene library, open the result,
  select visible A/B points, understand a consistency result, and reopen a saved
  version/download. Record which actions still required explanation.
- [ ] Close Phase 2 with passed/failed/pending acceptance items and concrete limits.
  If browser acceptance is unavailable, leave that item open explicitly. Do not
  reopen the reconstruction research loop to avoid closing a UI delivery.

**Gate:** The end-to-end workflow is demonstrated, recovery is tested, evidence
remains honest, and no routine scene task requires copying sidecars or typing
scene-specific terminal commands after application startup.

## 12. Priority, effort, and explicit exclusions

All six packages are needed to call this Phase 2 complete. P2-01 gives immediate
value; P2-02 through P2-04 deliver the main new video-to-library journey; P2-05
and P2-06 establish retention and acceptance.

| Package | Rough focused engineering effort | Completion evidence |
| --- | --- | --- |
| P2-01 | 2–3 days | Visible selection, clear summaries, observation lifecycle tests and manual use. |
| P2-02 | 2–3 days | Multiple isolated persistent scenes with current viewer compatibility. |
| P2-03 | 1–2 days | Real local input/readiness flow with bounded transfers. |
| P2-04 | 2–4 days | Durable supervised processing, cancellation, recovery, and result publication. |
| P2-05 | 1–2 days | Immutable versions and independently usable exports. |
| P2-06 | 1–2 days | Browser acceptance, one bounded real run, documentation and closure. |

Total is roughly 9–16 focused engineering days, an estimate rather than a
calendar promise. Publish package status and concrete blockers as work proceeds.
Do not restart completed packages or add model experiments without a changed
requirement. Use tests appropriate to each behavioral change, not snapshot churn
for every wording/spacing edit.

Deferred: alternative backend integration, M0/M1/M2 selection, automatic best-model
ranking, dense fusion/meshes/texturing, multi-video alignment, floorplan generation,
object recognition, automatic endpoint matching, automatic anisotropic correction,
accounts/cloud collaboration, mobile capture app, distributed processing, arbitrary
host file browsing, permanent source deletion, and inference checkpoint resume.

A camera view or measurement may remain unavailable when data is insufficient.
This does not block library delivery or justify inventing a result. Good usability
means explaining the limit and preserving other actions, not bypassing it.

## 13. Progress ledger and continuation rule

| Package | Status | Next action |
| --- | --- | --- |
| P2-01 | Implemented and reviewed | Photo-editor browser checks executed; unassisted human acceptance remains open. |
| P2-02 | Implemented and reviewed | Library rendering and two simultaneous scene contexts checked in the browser. |
| P2-03 | Implemented and reviewed | Original MOV upload/inspection executed; incomplete-transfer recovery has automated coverage. |
| P2-04 | Implemented and reviewed | Real CPU32 result published Ready and reopened; cancellation has automated coverage. |
| P2-05 | Implemented and reviewed | Synthetic browser version/default/package restoration journey executed. |
| P2-06 | Engineering verification complete; human acceptance open | 489 tests passed, one opt-in skip; build, preservation and scoped final re-review passed. See delivery limits. |

**Current checkpoint: P2-06 handoff, 2026-10-11.** Earlier packages are not
restarted. The final review findings and narrow follow-up are resolved. The
interrupted attempt remains retained; its one permitted technical retry completed
with the same frozen Standard/CPU32 settings and rendered in a fresh browser.
Do not launch another inference merely to close this ledger. Human usability
acceptance and explicitly unexecuted browser cases remain open; see
[delivery evidence](../../phase2-delivery.md).
Do not ask the user to choose routine
libraries, internal IDs, or individual control labels already specified here.
The subsequent user request authorized implementation, including ordinary video
extension, real-content, size, and disk-space validation. It did not authorize
commit or publication. Update this ledger as implementation progresses.

This file is the durable starting point for future sessions. Read it and the
linked editor design before making Phase 2 changes. The original Phase 1 plan
and its historical delivery report remain unchanged. The later user-reported
successful browser workflow is recorded here without silently rewriting earlier
"unverified" evidence. Record new verification as new evidence.

## 14. Files and sources inspected for this plan

- `README.md`, `docs/architecture.md`, `docs/phase1-usage.md`,
  `docs/phase1-delivery.md`, the original Phase 1 plan, and the October 2 UI plan.
- `src/twinforge/cli.py`, `config.py`, `reconstruction/orchestrator.py`,
  `reconstruction/memory.py`, `viewer/server.py`, viewer static HTML/JS,
  `scene/provenance.py`, and `measurements/storage.py`.
- The approved October 3 editor design linked above and the user's actual
  endpoint-selection, consistency, calibration, and reopening feedback.
- [MDN File API](https://developer.mozilla.org/en-US/docs/Web/API/File_API/Using_files_from_web_applications),
  [Python 3.12 HTTP server](https://docs.python.org/3.12/library/http.server.html),
  and [Python 3.12 subprocess](https://docs.python.org/3.12/library/subprocess.html)
  for the browser/local-service boundaries. These do not establish reconstruction
  accuracy or measured hardware capacity.

The original planning task created only this document. Implementation evidence
is recorded separately as packages progress; historical artifacts remain protected.
