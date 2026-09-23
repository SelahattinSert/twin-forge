# TwinForge

TwinForge is an independent spatial reconstruction engine prototype. It turns an ordinary, previously recorded RGB video into a traceable point cloud, camera trajectory, scale statement, confidence summary, and quality report. It does not need capture metadata, a special camera application, or depth hardware.

TwinForge reconstructs observed geometry. It does not generate missing surfaces to make a scene look complete. Unobserved and uncertain areas remain unknown.

## Phase 0 scope

Phase 0 tests whether image-only MapAnything inference can produce coherent, approximately metric geometry from ordinary video. The current pipeline inspects the video, samples and scores candidate frames, runs MapAnything, converts results into TwinForge's right-handed Z-up coordinates, and exports a point cloud plus per-frame camera data. This is a feasibility prototype, not a survey instrument or production reconstruction service.

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

MapAnything weights are fetched from Hugging Face on first use unless cached. TwinForge defaults to `facebook/map-anything-apache` at immutable revision `00f9c245bbcb60522d1ed7f9e9d88462c6e3f38a`, whose checkpoint is published under Apache 2.0. The source-code license and model-weight license are separate; see [dependency and checkpoint licenses](docs/dependencies.md).

TwinForge's source code is licensed under [Apache-2.0](LICENSE). Model weights and third-party dependencies retain their own licenses; check the exact checkpoint before substituting it.

The backend supports CPU and CUDA as documented by MapAnything. CPU execution is technically exposed by the official quick start but can be impractically slow for video reconstruction. Install the PyTorch build that matches the machine before the MapAnything extra.

The pinned checkpoint file is about 4.9 GB before framework/runtime memory. Peak RAM/VRAM depends on selected frame count and image dimensions; TwinForge does not claim a universal minimum. Begin with a small `--max-keyframes` value on constrained hardware and increase it only after a successful run.

Before inference, `run.json` records a lower-bound byte estimate for the dense float32 XYZ prediction payload using the image sizes after MapAnything preprocessing, and compares it with currently free CUDA VRAM when available. This is not a peak-memory forecast: it excludes model weights, intermediate activations, other returned maps, and allocator overhead. TwinForge calls MapAnything's memory-efficient mode with a dense-head minibatch of one to reduce memory use; all selected views and their returned predictions still consume memory. The configurable keyframe cap remains the operator-controlled limit, and an OOM error reports the selected count and a suggested smaller cap.

## Usage

```bash
twinforge inspect ./samples/room.mov
twinforge reconstruct ./samples/room.mov --output ./output --max-keyframes 64 --device auto
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

Keyframes are sampled at a configurable interval (`--candidate-interval`), rejected for poor blur/exposure, and selected using perceptual hash and ORB feature overlap/novelty. `--max-keyframes` controls the selected frame cap. If quality-valid candidates exceed that cap, TwinForge deterministically spreads the retained views over the valid timeline rather than stopping at the earliest frames, then recomputes neighbor overlap for the final set. `quality.json` records selected time span and fraction of source duration covered; it warns `CAMERA_TRAJECTORY_INCOMPLETE` when coverage is below 50% or camera poses are missing. Candidate sampling is uniform in time, not motion-adaptive. Variable-frame-rate source indices are approximate; selected timestamps are retained in `keyframes.json`.

## Coordinate system and scale

TwinForge stores world geometry in a right-handed coordinate frame with Z up. MapAnything's documented OpenCV world axes (+X right, +Y down, +Z forward) are converted with a proper rotation. Camera intrinsics are retained at backend inference resolution. A MapAnything metric scaling factor is recorded; its image-only result is labeled `estimated_metric`, with no invented confidence value. Metric accuracy has not been measured against physical ground truth.

Confidence maps are retained on exported points when MapAnything supplies them, with a mean per-frame value on camera records. Confidence summaries describe those values; they are not a claim of calibrated probability. Camera intrinsics include their backend inference image dimensions.

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
- Large frame sets can exceed available memory. Reduce `--max-keyframes` and rerun; the exact requested and used keyframe counts are recorded.
- On the tested 6 GiB RTX 3060 Laptop GPU, `room2.mp4` completed with 4 selected views, but 8 views ran out of CUDA memory. Four widely spaced views are not enough to establish a coherent whole-room digital twin; this result validates the GPU execution path, not geometric quality or metric accuracy. Peak memory depends on the video and environment.
- CPU inference can be very slow. On the supplied 33-second `room2.mp4`, 32 selected views took about 14 minutes 48 seconds in a CPU-only Python environment; other hardware, images, and model versions will differ.
- Source videos in the current workspace were coded at 1024×576 (displayed as 576×1024 after rotation metadata), despite being described as 1080p. Always use `twinforge inspect` to verify the file itself.

For a manual smoke test, place a small video at `tests/data/sample.mp4` (not committed) and run the commands above.
