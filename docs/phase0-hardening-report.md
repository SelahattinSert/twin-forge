# Phase 0 hardening — 2026-09-27

## Implemented

The existing pipeline was retained. No new backend, mesh generation, COLMAP, TSDF, or application-specific behavior was introduced.

- Optional frame caps replace the old default of 80. After model loading, a backend-neutral device-memory snapshot feeds a configurable conservative budget. Default CUDA allowance: 75% of free memory / 192 MiB per view. This is a heuristic, not a measured peak requirement. CPU/unavailable-memory fallback cap: 32.
- CUDA inference OOM alone can halve the view count and reload the model, at most three times and never below the configured minimum. Source IDs and timeline endpoints survive reductions; neighbor overlap is recomputed. Attempts, budgets and timings are recorded. Model-load/non-OOM failures do not trigger retries or silent device fallback.
- Candidates retain paths/dimensions/timing, not all RGB arrays. Quality analysis reads individual JPEGs and keeps compact feature/hash records. This does not make metadata, descriptors, or temporary disk usage constant-sized.
- Output normalization has synthetic tests for documented layouts, singleton spatial axes, masks/raw geometry, confidence, depth, RGB, camera matrices and scale. Partial confidence uses unavailable NaN entries in binary arrays. Malformed camera matrices fail before export.
- The real smoke validates finite nonempty points, nonzero valid geometry, poses, scale schema and frame provenance. It remains opt-in, cached-weights-only, with configurable view cap/device.
- Failure records cover inference, reload, cleanup and export. Cleanup errors cannot replace an earlier primary error. Quality explicitly describes pipeline/input health; geometric accuracy is not evaluated.

## Architecture and files

Video → FFmpeg ingest → file-backed quality/ORB selection → prepared backend memory budget → bounded inference attempts → normalized reconstruction → input/output health analysis → PLY/GLB/NPZ/JSON.

Main changes: `config.py`, `ingest/video.py`, `keyframes/selector.py`, `backends/base.py`, `backends/mapanything.py`, new `backends/mapanything_outputs.py`, new `reconstruction/memory.py`, `reconstruction/orchestrator.py`, `quality/analyzer.py`, CLI, unit/integration tests, README and architecture/decision documentation.

Reference photos were moved into ignored `samples/measurements/room2/` with semantic names. Their SHA-256 hashes did not change. Local evaluation paths were updated; existing 32-view reconstruction/evaluation data was not replaced. There is no filename-specific WhatsApp ignore rule.

## Backend

Official MapAnything 1.1.3; source pin `9d1db2dd728bd8a10e74b15d2eb646e1bf933791`; checkpoint `facebook/map-anything-apache`, revision `00f9c245bbcb60522d1ed7f9e9d88462c6e3f38a`. Integration remains `from_pretrained` → official `load_images` → `model.infer` → TwinForge normalization.

The first updated real smoke exposed an official documentation/runtime mismatch: `metric_scaling_factor` is documented as `(B,)` but returned `(1, 1)` in this image-only run. That run failed honestly with a failure record. A red-first regression and explicit singleton-scalar normalization fixed it without applying scale twice; subsequent real runs passed.

## Real CUDA evidence

Input `room2.mp4`: 33.281667 seconds, approximately 29.986 FPS, coded 1024×576, displayed 576×1024 after rotation, 67 candidate frames. GPU: RTX 3060 Laptop, 6 GiB; Python 3.12.14; PyTorch 2.13.0+cu130 / CUDA 13.0. No new weight download was required.

| Experiment | Views | Result |
| --- | --- | --- |
| Strengthened smoke, upper cap 4 | 4 → 3 by auto budget | Passed; 456,876 points, 3 cameras/depth maps; pytest 23.50 s |
| Auto budget disabled for OOM exercise | 8 OOM → 4 after reload | Passed; 609,168 points, 4 cameras/depth maps; stage durations sum ≈40.34 s |
| Normal CLI, no explicit cap | 33 selected → 3 by auto budget | Passed; 456,876 points, 3 cameras/depth maps |

Successful runs have `estimated_metric`, meters-per-unit 1.0, independent scale confidence unavailable. Smoke confidence mean ≈1.0896, median ≈1.0147; these backend values are not probabilities. Warnings: `METRIC_SCALE_UNCERTAIN`, `LOW_VISUAL_DIVERSITY`, `FRAME_COUNT_REDUCED`. Both OOM attempts are recorded, with original IDs and device-memory snapshots. Shared artifact validation also passed on the OOM/retry output.

Private run evidence is under ignored `output/hardening-smoke-fixed-20260927/`, `output/hardening-oom-retry-20260927/` and `output/hardening-auto-default-20260927/`. Prior `output/room2` remains intact.

## Verification and limitations

Final lightweight suite: **107 passed, 1 skipped**. Ruff lint/format and diff whitespace checks passed; all 104 installed packages were compatible. The heavy test is skipped by ordinary pytest; its actual CUDA invocation separately passed (1 passed). Tests do not download model weights. Independent review found camera validation and export/cleanup logging issues, which were reproduced with failing tests and fixed; final review reported no important blockers.

This verifies software integrity and resource handling, **not whole-room coherence or metric accuracy**. Candidate sampling remains uniform in time. Descriptor memory and disk usage still grow with long videos; no 15-minute empirical RAM benchmark was run. Auto budgets can still fail; small view sets can weaken continuity. No calibrated confidence, cross-view depth/reprojection gate, or multi-environment distance benchmark is claimed.

The next justified step is independently matched endpoint-distance evaluation of the preserved 32-view output, then repetition on multiple measured environments. Report raw scale error separately from any fitted/calibrated scale and reject ambiguous endpoint matches rather than fabricating a benchmark result.
