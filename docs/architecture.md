# TwinForge architecture

```text
RGB video
   ↓
VideoIngestor ── ffprobe metadata; FFmpeg display-oriented candidate decode
   ↓
KeyframeSelector ── sharpness, exposure, duplicate, ORB overlap and novelty
   ↓
ReconstructionBackend ── MapAnything adapter owns model-specific API/tensors
   ↓
ReconstructionResult ── TwinForge cameras, points, scale and confidence
   ↓
Quality analyzer (including selected timeline coverage) + PLY / GLB / JSON exporters
```

`VideoIngestor` uses FFmpeg tooling so codecs and phone rotation metadata are handled consistently. Candidates are sampled rather than decoding every source frame into the model. `KeyframeSelector` is deterministic for a fixed decoded input and settings. Candidate timestamps are preserved; source frame numbers are approximate on variable-frame-rate footage.

Candidates contain paths, dimensions and timing only. Decode validation and selection each read one JPEG at a time. Selection retains quality/hash/ORB evidence rather than full RGB arrays; descriptors/metadata and temporary JPEG storage still scale with duration.

`ReconstructionBackend` separates the normalized TwinForge representation from backend image preprocessing, tensor shapes, model fields, and coordinate conventions. `MapAnythingBackend` follows the official package API (`MapAnything.from_pretrained`, `mapanything.utils.image.load_images`, `model.infer`) and converts returned OpenCV world axes into TwinForge's right-handed Z-up world. Missing backend fields remain unavailable in normalized output.

After preparation, backend-neutral `DeviceMemory` supplies actual device/free memory to the planning policy. Default CUDA planning reserves 25% of free memory and allocates 192 MiB per view as an adjustable heuristic, not a measured requirement. CPU/unknown memory uses a cap of 32. CUDA inference OOM alone triggers up to three halving/reload retries, never below the configured minimum. Model-load failure and non-OOM errors are not retried. Actual final neighbor evidence and IDs are preserved; `run.json` records budgets/attempts, including terminal failure.

The adapter's additional dense float32 XYZ lower bound uses actual preprocessed dimensions and does not predict peak memory. Inference remains official memory-efficient mode with dense-head minibatch one. A focused, directly tested normalizer validates documented tensor axes without squeezing away single-pixel spatial dimensions. Raw finite geometry and model masks remain separate; missing partial confidence uses NaN in binary arrays.

The selector evaluates every quality-usable candidate before applying `maximum_keyframes`. If the candidate set exceeds the cap, it keeps a deterministic timestamp-spread subset, including the first and last usable observations, and recomputes ORB overlap/novelty between the final neighbors. Quality output reports the selected timeline span and fraction of video duration; low coverage or missing camera poses yields `CAMERA_TRAJECTORY_INCOMPLETE`.

The Phase 0 scene is point based. PLY is authoritative and carries per-point confidence, source frame IDs, and validity as PLY scalar properties where supplied. Raw points remain in PLY; optional camera-space depth maps are stored in NPZ. GLB is a standards-based `POINTS` primitive filtered to valid points for convenient preview; no mesh is inferred. JSON files contain metadata and references, not dense tensors.

Quality measures pipeline/input health only. `geometry_validation.status` remains `not_evaluated`; valid tensors or complete exports do not prove coherent geometry or metric accuracy. Ground-truth comparisons require observations and endpoints independently matched to the reconstruction.

The saved-scene dependency direction is `Saved scene → SceneReader → local Viewer
→ MeasurementSet → uniformly scaled DerivedScene`. Viewer and measurement modules
do not import MapAnything; the reconstruction engine does not depend on the viewer.
Backend tensor and pixel layout knowledge stays in the adapter. Production modules
do not import private experiment code.

SceneReader memory-maps authoritative PLY rows read-only and binds measurements to
artifact and source-image hashes. Preview reduction preserves original row IDs.
MeasurementStore atomically publishes versioned observations and evidence into a
separate workspace. Exact source/model pixel transforms enable image picks and
complete endpoint neighborhoods; unavailable provenance remains unavailable.
Scene schemas 0.1 and 0.2 are readable, alongside the explicitly supported limited
historical original-MOV import. Unknown schemas are rejected.

One qualified control freezes evidence before physical input and creates one
uniform scalar. DerivedScene publishes a new source-linked 0.2 directory with
scaled XYZ, camera translations, and recognized depth, preserved rotations,
intrinsics and scalar point attributes, calibration, and control-excluded checks.
Source overlap and repeated scaling are rejected. JSON contains metadata and
references rather than dense arrays. Scale, evidence, use status, and raw confidence
are independent. See [workflow](phase1-usage.md) and [limits](phase1-delivery.md).

Other backends, COLMAP tuning, fusion, multi-fragment reconstruction, and shape
repair remain outside this phase.

## Local application and persistent library

`ApplicationServer` serves the browser shell on loopback. `LibraryStore` owns
durable scene/run/session/version identities and annotation workspaces under
one configured library; linked original artifacts remain read-only. Scene
requests carry all three context identities, so tabs cannot replace a global
active scene. A bounded leased LRU caches viewer services. Library cards read
metadata and small thumbnails, without loading full point clouds. Browser
modules, Three.js and fonts are packaged locally.

`UploadStore` accepts finite declared lengths, streams into managed disk storage,
hashes the original bytes and publishes media only after bounded FFmpeg/ffprobe
inspection. Review settings remain separate from processing submission. Setup
checks and explicit preparation live in `ReadinessManager`; the HTTP parent does
not import the model. Standard selects CPU and up to 32 useful images with no
automatic budget reduction or OOM retries. Quick preview uses the existing
automatic policy. These application profiles do not change backend geometry or
measurement thresholds.

`JobManager` freezes input hashes and settings, journals durable jobs, and
supervises one owned worker process group. Preparation and other heavy operations
share its file-lock admission slot. Worker identity includes PID birth identity
and nonce. Processing uses prepared caches with external networking denied in
the worker. The parent retains bounded stage events and diagnostics and serves
browsing/polling during compute. Completion receipts bind to the job/config;
output integrity and preview validation precede transactional Ready publication.
Cancel/shutdown stop owned children. Restart reconciles interrupted jobs and
publication journals without launching inference; retries allocate new runs.
Unresolved ownership blocks heavy admission.

Photo-editor transforms map display coordinates back to original source pixels
and draw feedback locally. Verified source/model provenance resolves submitted
pixels to authoritative PLY rows. Observation correction/exclusion retains
history. Missing provenance or insufficient evidence remains explicit.

Calibration creates a new immutable version session linked to original geometry,
with frozen observations, artifact hashes and control-excluded reports. Default
version selection is persistent and changes explicitly. Recalibration from a
frozen reference starts from the original geometry, avoiding compounded scaling.
`ExportStore` retains allowlisted disk-backed PLY/GLB or full packages and streams
downloads. Package descriptors hash members; restoration enforces shared export/
restore limits, ZIP/ZIP64 central-directory admission before eager parsing,
expanded-size limits, metadata bounds and absolute transfer deadlines. A verified
package becomes a separate managed scene and needs no original source location.
Full packages contain source images/evidence but exclude original videos and
model caches. Archive retains data and frees no storage.

The synthetic [application workflow tests](../tests/integration/test_application_workflow.py)
exercise these boundaries through actual HTTP/storage and owned worker doubles.
They establish recovery and isolation, not browser rendering or neural geometry.
See [application usage](phase2-usage.md) and [acceptance evidence](phase2-delivery.md).
