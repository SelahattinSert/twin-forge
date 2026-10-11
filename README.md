# TwinForge

TwinForge is an independent spatial reconstruction engine prototype. It turns an ordinary, previously recorded RGB video into a traceable point cloud, camera trajectory, scale statement, confidence summary, and quality report. It does not need capture metadata, a special camera application, or depth hardware.

TwinForge reconstructs observed geometry. It does not generate missing surfaces to make a scene look complete. Unobserved and uncertain areas remain unknown.

## Delivered scope

Phase 0 tests whether image-only MapAnything inference can produce coherent, approximately metric geometry from ordinary video. The current pipeline inspects the video, samples and scores candidate frames, runs MapAnything, converts results into TwinForge's right-handed Z-up coordinates, and exports a point cloud plus per-frame camera data. This is a feasibility prototype, not a survey instrument or production reconstruction service.

Phase 1 adds an offline saved-scene viewer, exact endpoint measurements, bounded
multi-view consistency evidence, and one-control uniform calibrated exports.
See [usage](docs/phase1-usage.md) and [delivery limits](docs/phase1-delivery.md).
Physical-reference evaluation occurred and exposed remaining shape errors;
calibration establishes scale but does not establish whole-room accuracy.

Phase 2 adds a persistent local scene library, browser video upload and review,
supervised processing with cancellation/recovery, source-photo observations,
immutable saved versions, and restorable downloads. Start it once with
`twinforge app --library output/phase2/library`, then use the browser for scene
tasks. See the [Phase 2 guide](docs/phase2-usage.md) and
[acceptance status](docs/phase2-delivery.md). A real 32-view CPU application run
completed and its scene was displayed in the browser. Human acceptance remains
pending; completed product code does not establish geometric accuracy.

## Requirements and installation

Use Python 3.12. TwinForge declares Python `>=3.12,<3.13`; the official MapAnything quick start currently creates a Python 3.12 environment. FFmpeg and ffprobe must be installed and on `PATH`.

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
# Install a PyTorch build appropriate for the machine first (CPU or CUDA):
# https://pytorch.org/get-started/locally/
python -m pip install -e '.[mapanything]'
```

On the verified Linux RTX 3060 Laptop GPU environment, PyTorch `2.13.0+cu130` and torchvision `0.28.0+cu130` worked with the installed NVIDIA driver. To reproduce that CUDA setup, install them before the MapAnything extra:

```bash
python -m pip install torch==2.13.0 torchvision==0.28.0 --index-url https://download.pytorch.org/whl/cu130
python -m pip install -e '.[mapanything]'
python -c "import torch; print(torch.cuda.is_available(), torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'no CUDA device')"
```

This is a tested configuration, not a promise that every driver, OS, or GPU supports it. Confirm `torch.cuda.is_available()` in the same environment used to run TwinForge; a CPU-only PyTorch build cannot use the GPU even when NVIDIA hardware is installed.

For development and unit tests:

```bash
python -m pip install -e '.[dev]'
pytest
```

The lightweight suite does not require PyTorch, MapAnything, Pillow, or model
weights. Install FFmpeg **and ffprobe** to run the real video-ingestion checks;
GitHub Actions installs both explicitly. The official MapAnything preprocessing
integration check runs only when the optional backend is installed and never
loads weights or performs inference. Synthetic coordinate/provenance tests still
run without that backend. Readiness tests simulate decoder availability rather
than depending on the developer machine's setup.

MapAnything weights are fetched from Hugging Face on first use unless cached. TwinForge defaults to `facebook/map-anything-apache` at immutable revision `00f9c245bbcb60522d1ed7f9e9d88462c6e3f38a`, whose checkpoint is published under Apache 2.0. The source-code license and model-weight license are separate; see [dependency and checkpoint licenses](docs/dependencies.md).

TwinForge's source code is licensed under [Apache-2.0](LICENSE). Model weights and third-party dependencies retain their own licenses; check the exact checkpoint before substituting it.

The backend supports CPU and CUDA as documented by MapAnything. CPU execution is technically exposed by the official quick start but can be impractically slow for video reconstruction. Install the PyTorch build that matches the machine before the MapAnything extra.

The pinned checkpoint file is about 4.9 GB before framework/runtime memory. Peak RAM/VRAM depends on selected frame count and image dimensions; TwinForge does not claim a universal minimum. The default frame limit is automatic, not 80.

After model loading, the default planning policy uses 75% of currently free CUDA memory and an adjustable allowance of 192 MiB per view. These are conservative **heuristics, not measured peak-memory requirements**. CPU or unavailable CUDA memory measurements use a 32-view cap. The policy never reduces below the configured minimum (three by default); even that minimum may not fit. `--max-keyframes` is an optional upper limit, still subject to this policy; `--no-auto-budget` disables the heuristic.

CUDA inference OOM triggers at most three retries, halving the frame count only when the next set meets the configured minimum. Reductions span the timeline, preserve frame IDs, and recompute neighbor overlap. Failed resources are released and the model reloaded; no silent CPU fallback occurs. `--no-oom-retry` disables retries. Model-load OOM fails immediately because reducing views cannot make the weights smaller. `run.json` records policy inputs, requested/used counts, each attempt and timings. Terminal backend failures retain a failed `run.json` and keyframe manifest, without claiming a completed scene. Unused earlier selected JPEGs may remain in `frames/`; `keyframes.json` is authoritative for views actually used.

The adapter also records the dense float32 XYZ payload lower bound after MapAnything preprocessing. This excludes weights, activations, auxiliary maps and allocator overhead, and is not a peak-memory forecast. Inference uses memory-efficient mode with dense-head minibatch size one.

## Usage

```bash
twinforge app --library output/phase2/library
# Optionally discover existing saved scenes under explicitly allowed roots:
twinforge app --library output/phase2/library --import-root output/saved-scenes --no-browser
twinforge inspect ./samples/room.mov
twinforge reconstruct ./samples/room.mov --output ./output
# Optional explicit upper limit:
twinforge reconstruct ./samples/room.mov --output ./output-small --max-keyframes 4 --device cuda
```

`inspect` reports the stream, display orientation, duration, frame rate, and approximate candidate count without loading the model. `reconstruct` writes to a deterministic directory based on the input filename:

TwinForge refuses to overwrite a nonempty run directory. For another run of the same video, use a different `--output` root so earlier geometry and provenance remain intact.

```text
output/room/
├── scene.json
├── run.json
├── quality.json
├── cameras.json
├── depthmaps.npz     # when supplied by the backend
├── keyframes.json
├── pointcloud.ply
├── preview.glb
└── frames/
```

The PLY is authoritative. It is binary little-endian and includes RGB, per-point confidence, source frame ID, and validity properties when supplied; masked/uncertain raw points are not silently discarded. Available camera-space depth maps are stored as binary `depthmaps.npz`. The GLB is a standards-based point primitive preview containing only points marked valid, not a mesh or fabricated surface. Some viewers may render point sizes differently.

Keyframes are sampled at a configurable interval (`--candidate-interval`), rejected for poor blur/exposure, and selected using perceptual hash and ORB feature overlap/novelty. Candidate JPEGs stay on disk; quality analysis reads one image at a time and retains compact feature/hash records, not all decoded RGB arrays. Memory still grows with candidate metadata and descriptors, and temporary disk usage grows with video duration. Timestamp-spread caps preserve the first/last usable observations; final-neighbor overlap is recomputed. Candidate sampling is uniform in time, not motion-adaptive. Variable-frame-rate indices and sampled source timing are approximate.

`quality.json` explicitly reports `scope: pipeline_and_input_health` and `geometry_validation.status: not_evaluated`. Blur, exposure, valid-point counts and temporal coverage do not establish geometric consistency or physical accuracy. `FRAME_COUNT_REDUCED` warns of resource-driven reductions; missing poses/low temporal coverage and insufficient final visual overlap have separate warnings.

## Coordinate system and scale

TwinForge stores world geometry in a right-handed coordinate frame with Z up. MapAnything's documented OpenCV world axes (+X right, +Y down, +Z forward) are converted with a proper rotation. Camera intrinsics are retained at backend inference resolution. A MapAnything metric scaling factor is recorded; its image-only result is labeled `estimated_metric`, with no invented confidence value. Physical-reference comparisons have been performed and did not establish sufficient room accuracy. A uniformly calibrated door remains too tall and observed floor/ceiling separation remains too large; see the Phase 1 delivery report.

Confidence maps are retained on exported points when MapAnything supplies them, with a mean per-frame value on camera records. If confidence is absent for some views but present for others, unavailable point entries are NaN in binary PLY/NPZ, not fabricated zero confidence; JSON statistics use finite observations only. If no view supplies confidence, the property is absent. Confidence values are not calibrated probabilities. Camera intrinsics include their backend inference image dimensions.

## Video guidance

- Walk through the space instead of rotating from one fixed point.
- Keep overlap between consecutive views while revealing new surfaces.
- Move at a moderate speed and avoid motion blur.
- Capture important surfaces from multiple viewpoints.
- Avoid abrupt edits, zoom changes, and unstable exposure.
- No dedicated capture application or special markers are required.

## Limitations

- Monocular RGB scale is approximate and is not guaranteed to meet survey-grade accuracy.
- Textureless and reflective surfaces can reconstruct poorly.
- Motion blur and moving objects can make geometry inconsistent.
- Unseen regions cannot be reliably reconstructed.
- Phone rotation metadata is applied during FFmpeg decode; actual behavior is reported in inspection metadata.
- Candidate source frame indices are estimates for variable-frame-rate video.
- No mesh fusion, texturing, or scene completion is performed.
- Automatic budgets and bounded retries reduce, but cannot eliminate, memory failures. Small GPU subsets may lose visual continuity even when timeline coverage is preserved.
- On the tested 6 GiB RTX 3060 Laptop GPU, `room2.mp4` completed with 4 selected views, but 8 views ran out of CUDA memory. Four widely spaced views are not enough to establish a coherent whole-room digital twin; this result validates the GPU execution path, not geometric quality or metric accuracy. Peak memory depends on the video and environment.
- CPU inference can be very slow. On the supplied 33-second `room2.mp4`, 32 selected views took about 14 minutes 48 seconds in a CPU-only Python environment; other hardware, images, and model versions will differ.
- The historical compressed MP4 input was coded at 1024×576 (displayed as 576×1024), despite being described as 1080p. The later original-phone MOV is coded at 3840×2160 (displayed as 2160×3840) and uses explicit HDR conversion. Always use `twinforge inspect` to verify the actual file.

For a manual smoke test, place a small video at `tests/data/sample.mp4` (not committed) and run the commands above.

The opt-in model test requires an already cached checkpoint and does not download weights:

```bash
TWINFORGE_RUN_MODEL_SMOKE=1 TWINFORGE_SMOKE_VIDEO=samples/room2.mp4 \
TWINFORGE_REQUIRE_CUDA=1 TWINFORGE_SMOKE_DEVICE=cuda \
TWINFORGE_SMOKE_MAX_KEYFRAMES=4 pytest tests/integration/test_mapanything_smoke.py -q
```

Set `HF_HOME`/`TORCH_HOME` to your existing cache paths if needed. The smoke checks nonempty finite geometry, valid points, poses, scale schema and frame provenance—not accuracy against physical ground truth. Keep private videos and marked measurement photos under ignored `samples/` (for example `samples/measurements/room2/`); keep generated evaluations under ignored `output/`. A coherent room and metric accuracy remain unproven until independently identified distances across multiple scenes are evaluated.
