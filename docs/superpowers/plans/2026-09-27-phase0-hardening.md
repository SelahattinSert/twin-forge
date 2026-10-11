# Phase 0 resource hardening implementation plan

> **For agentic workers:** Execute inline with `executing-plans`, one red/green test cycle per task. The user approved this scope on 2026-09-27. Do not discard existing scene outputs.

**Goal:** Make the existing Phase 0 pipeline resource-conscious and directly test its fragile normalization boundary, without claiming geometric feasibility.

**Architecture:** Keep the adapter boundary. Candidates hold paths and timing only; selection decodes one image at a time and retains compact ORB/hash/quality evidence. After model preparation, a backend-neutral device-memory snapshot feeds a documented conservative planning policy. Final frame reductions preserve timestamp coverage, recompute neighboring overlap, and retain source IDs. Only domain-specific inference OOM triggers bounded halving/reload retries.

**Tech stack:** Existing Python 3.12, NumPy, OpenCV, FFmpeg, optional PyTorch/official pinned MapAnything. No new runtime dependencies.

## Constraints and decisions

- Unknown geometry is preferable to fabricated geometry. No mesh completion, COLMAP, TSDF, new backend, or training.
- No generic peak-memory formula is claimed. CUDA policy reserves 25% of free memory **after model load** and plans 192 MiB per view as an adjustable heuristic, not a measured requirement; actual OOM is authoritative. CPU/unknown-device auto cap is 32.
- `--max-keyframes` is an optional upper limit, not default 80. Both selection/backend typed caps accept `None`; auto policy can reduce explicit caps unless disabled with `--no-auto-budget`.
- Minimum selected frame count is never violated by retries. At most three OOM retries; `--no-oom-retry` disables them. Model-load OOM cannot be fixed by reducing inference views and fails clearly.
- Model preparation/reloads are timed separately from inference attempts. `run.json` records initial selected count, final count, policy inputs, reductions, attempt outcomes, final timestamps, and settings. No silent CPU fallback.
- An OOM retry may degrade overlap; recompute it and warn. Keep original candidate/keyframe provenance; output manifests refer only to final frames.
- Invalid/absent tensors must not masquerade as valid camera data or certainty. Partial confidence aligns with every point using NaN for unavailable values, documented in binary PLY only; finite JSON statistics remain honest.
- Quality reports explicitly describe pipeline/input health and leave geometric validation unavailable. No fabricated geometric error, overall score, or accuracy threshold.
- Private reference photos live under existing ignored `samples/measurements/room2/`; local evaluation paths and hashes remain valid.

## Task 1 — File-based candidate selection

Files: `src/twinforge/ingest/video.py`, `src/twinforge/keyframes/selector.py`, `tests/unit/test_selector.py`, `tests/unit/test_video.py`, `tests/integration/test_fake_backend_pipeline.py`.

- [x] Add a regression asserting decoded candidates have no resident image arrays; verify the old implementation fails.
- [x] Replace `CandidateFrame.image` with width/height. Decode and discard each JPEG during validation. Selector independently decodes one candidate at a time, storing only metadata/features; remove stale-image-shape use.
- [x] Tighten blur assertion to `rejected_blur >= 1` and assert the blurred source index is absent. Update tests to construct path-only candidates and verify selection still preserves timeline.
- [x] Run `.venv/bin/pytest tests/unit/test_selector.py tests/unit/test_video.py tests/integration/test_fake_backend_pipeline.py -q`.
- [x] Correct the high-overlap/low-novelty comment and explicitly retain uniform temporal candidate sampling as a limitation.

## Task 2 — Automatic budgets and OOM retry

Files: `src/twinforge/config.py`, `src/twinforge/backends/base.py`, `src/twinforge/backends/mapanything.py`, new `src/twinforge/reconstruction/memory.py`, `src/twinforge/reconstruction/orchestrator.py`, `src/twinforge/cli.py`, new unit/integration tests.

Interfaces: `DeviceMemory(device: str, free_bytes: int | None, total_bytes: int | None)` from backend `memory_info()`; `MemoryConfig` for heuristic and retry settings; `plan_frame_budget(info, config, requested, available_count, minimum)` returns JSON-safe policy/count; selector `reduce(frames, limit)` returns a timeline-spread final list with updated stats/overlap.

- [x] Test parser/config defaults are `None`, explicit 80 remains valid, invalid fractions/retries fail.
- [x] Test a loaded CUDA device with 800 MiB free chooses at most four views and preserves the minimum. CPU chooses up to 32; unknown free memory is recorded as fallback, never guessed.
- [x] Add controlled backend OOM integration regression: initial eight views, then four, then success; verify first/last timestamps, final camera/manifest IDs, attempt records and cleanup. Test terminal minimum, disabled retries, and non-OOM propagation.
- [x] Implement planning function, normalized memory snapshot, reduction/recomputed overlap, and bounded retry loop. CUDA-only domain OOM can retry; release failed resources outside exception scope before reloading.
- [x] Emit `run.json`/`keyframes.json` for failure too, including attempts, instead of leaving provenance unknown.
- [x] Run the resource unit/integration tests and all lightweight tests.

## Task 3 — Synthetic adapter normalization

Files: `src/twinforge/backends/mapanything.py`, new `src/twinforge/backends/mapanything_outputs.py` if normalization needs a focused module, new `tests/unit/test_mapanything_outputs.py`.

Interfaces: Adapter's inference remains official `load_images`, `from_pretrained`, `infer`. A focused normalizer is called by actual adapter code and consumes real documented prediction dictionaries, not a test-only API.

- [x] Synthetic NumPy-backed tensor-like fixtures exercise `detach().cpu().numpy()` without installing/importing torch in default CI.
- [x] Red tests cover batched/unbatched XYZ, one-pixel spatial axes, finite filtering, masks retained (not deleting raw geometry), partial/absent confidence, depth maps, intrinsics, poses, metric/relative scale, mismatched count/shape, invalid matrices and missing XYZ.
- [x] Implement minimal explicit dimensional validation. Preserve shape axes and reject unsupported layouts with `ReconstructionFailedError`, not incidental NumPy exceptions.
- [x] Verify exact coordinate rotation, point RGB/confidence/source ID alignment, per-frame statistics, absent fields as `None`, scale confidence unavailable.
- [x] Run `.venv/bin/pytest tests/unit/test_mapanything_outputs.py -q` and the full suite.

## Task 4 — Smoke geometry invariants, documentation, real checks

Files: `tests/integration/test_mapanything_smoke.py`, shared test-only artifact validator and tests, `src/twinforge/quality/analyzer.py`, `README.md`, `docs/architecture.md`, `docs/decisions.md`.

- [x] Add failing tests that reject empty/nonfinite PLY, missing/nonfinite poses, zero valid geometry, bad scale schema, inconsistent selected/camera/point frame IDs. Implement actual binary PLY inspection and JSON validation shared with the opt-in smoke test.
- [x] Smoke cap/device use environment overrides, default conservative cap 4; require cached weights and honor opt-in/accelerator requirements. Keep download-free default pytest.
- [x] Explicitly label quality scope and unmeasured geometric accuracy; tests assert these unavailable fields.
- [x] Document heuristic vs measured memory, every retry/adjustment, path-only candidate RAM behavior, limitation of small GPU subsets, and private benchmark photo workflow.
- [x] Run `pytest`, `ruff check src tests`, `ruff format --check src tests`, dependency compatibility, `git diff --check`, and private-data ignore checks.
- [x] Re-run a small actual CUDA smoke if host GPU/cache permit, and a forced eight-view OOM-to-four-view retry in a separate ignored run directory; never overwrite prior raw scene outputs. Report exact success/failure rather than claiming all Phase 0 geometry proven.

## Completion gate

No geometry-accuracy success declaration. A usable 3–5-scene benchmark and independently identified 10–20 physical distances per scene require new observations from the user and remain future evaluation work, not fabricated fixtures.
