"""End-to-end run coordination and reproducible artifact writing."""

from __future__ import annotations

import json
import logging
import platform
import sys
import tempfile
import time
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from twinforge import __version__
from twinforge.backends.base import ReconstructionBackend, ReconstructionContext
from twinforge.config import TwinForgeConfig
from twinforge.core.types import FrameObservation, ReconstructionResult, VideoMetadata, json_safe
from twinforge.exceptions import (
    ExportError,
    OutOfMemoryReconstructionError,
    ReconstructionFailedError,
)
from twinforge.export.depth import write_depth_maps
from twinforge.export.glb import write_point_glb
from twinforge.export.ply import write_ply
from twinforge.ingest.video import VideoIngestor
from twinforge.keyframes.selector import KeyframeSelector, SelectionStats
from twinforge.quality.analyzer import analyze_quality
from twinforge.reconstruction.memory import plan_frame_budget
from twinforge.reconstruction.progress import ProgressReporter

logger = logging.getLogger(__name__)


class ReconstructionOrchestrator:
    def __init__(self, backend: ReconstructionBackend, config: TwinForgeConfig):
        config.validate()
        self.backend, self.config = backend, config
        self.ingestor = VideoIngestor(config.video.color_policy)
        self.selector = KeyframeSelector(config.keyframes)

    def run(
        self,
        video_path: Path,
        output_root: Path | None = None,
        device: str | None = None,
        debug: bool = False,
        *,
        scratch_root: Path | None = None,
        on_progress=None,
    ) -> Path:
        progress = ProgressReporter(on_progress)
        try:
            return self._run(video_path, output_root, device, debug, scratch_root, progress)
        except Exception as exc:
            progress.emit(progress.stage, "failed", failure_type=type(exc).__name__)
            raise

    def _run(self, video_path, output_root, device, debug, scratch_root, progress) -> Path:
        root = output_root or self.config.output.root
        run_dir = root / Path(video_path).stem
        if run_dir.exists() and (not run_dir.is_dir() or any(run_dir.iterdir())):
            raise ExportError(
                f"Output directory already contains data: {run_dir}. "
                "Choose another --output root to preserve the existing run."
            )
        run_dir.mkdir(parents=True, exist_ok=True)
        timings: dict[str, float] = {}

        logger.info("[1/5] Inspecting video")
        progress.emit("inspecting")
        start = time.monotonic()
        metadata = self.ingestor.inspect(video_path)
        timings["video_inspection"] = time.monotonic() - start
        logger.info(
            "%s | %.2fs | %dx%d display | %s fps | rotation %d°",
            metadata.codec,
            metadata.duration_seconds,
            metadata.display_width,
            metadata.display_height,
            _fmt(metadata.fps),
            metadata.rotation_degrees,
        )

        logger.info("[2/5] Selecting keyframes")
        progress.emit("selecting_images")
        start = time.monotonic()
        with tempfile.TemporaryDirectory(prefix="twinforge-", dir=scratch_root) as temporary:
            candidate_dir = Path(temporary)
            candidates = self.ingestor.decode_candidates(
                metadata,
                self.config.video.candidate_interval_seconds,
                self.config.video.max_decode_width,
                candidate_dir,
            )
            frames_dir = run_dir / "frames"
            frames = self.selector.select(candidates, frames_dir)
            timings["keyframe_selection"] = time.monotonic() - start
            logger.info("Selected %d of %d sampled candidates", len(frames), len(candidates))
            progress.emit(
                "selecting_images",
                "images_selected",
                selected_images=len(frames),
                candidate_images=len(candidates),
            )
            del candidates

            logger.info("[3/5] Loading reconstruction backend")
            requested_device = device or self.config.backend.device
            logger.info(
                "Backend: %s; checkpoint: %s; device request: %s",
                type(self.backend).__name__,
                getattr(self.backend, "checkpoint", "n/a"),
                requested_device,
            )
            context = ReconstructionContext(requested_device, debug)
            frames, reconstruction, adjustment, attempts = self._infer(
                frames, context, run_dir, timings, metadata, progress
            )

        # Persist inference evidence before any exporter can fail.
        reconstruction.backend_metadata["video_preprocessing"] = self.ingestor.preprocessing
        export_record = _run_metadata(
            metadata, reconstruction, self.selector.stats, frames, requested_device, self.config
        )
        export_record.update(
            status="exporting",
            memory_adjustment=adjustment,
            memory_settings=asdict(self.config.memory),
            reconstruction_attempts=attempts,
            timings_seconds=timings,
            timestamp_utc=datetime.now(UTC).isoformat(),
        )
        _write_json(run_dir / "run.json", export_record)
        export_start = time.monotonic()
        progress.emit("exporting")
        try:
            return self._export_result(
                run_dir,
                metadata,
                reconstruction,
                frames,
                requested_device,
                timings,
                adjustment,
                attempts,
            )
        except Exception as exc:
            timings["export"] = time.monotonic() - export_start
            export_record.update(
                status="failed", failure={"stage": "export", "type": type(exc).__name__}
            )
            _write_json(run_dir / "run.json", export_record)
            if isinstance(exc, ExportError):
                raise
            raise ExportError(
                f"Result export failed: {exc}. Inference attempts remain in run.json."
            ) from exc

    def _export_result(
        self,
        run_dir: Path,
        metadata: VideoMetadata,
        reconstruction: ReconstructionResult,
        frames: list[FrameObservation],
        requested_device: str,
        timings: dict[str, float],
        adjustment: dict[str, Any],
        attempts: list[dict[str, Any]],
    ) -> Path:
        logger.info("[5/5] Analyzing quality and exporting")
        start = time.monotonic()
        write_ply(run_dir / "pointcloud.ply", reconstruction.points)
        if reconstruction.depth_maps:
            write_depth_maps(run_dir / "depthmaps.npz", reconstruction.depth_maps)
        valid_point_count = (
            int(reconstruction.points.valid_mask.sum())
            if reconstruction.points.valid_mask is not None
            else len(reconstruction.points.xyz)
        )
        preview_available = self.config.output.preview_glb and valid_point_count > 0
        if preview_available:
            write_point_glb(run_dir / "preview.glb", reconstruction.points)
        _write_json(
            run_dir / "cameras.json",
            {
                "coordinate_system": "TwinForge right-handed, Z-up",
                "pose_convention": "camera_to_world; rotation maps OpenCV camera-local axes into TwinForge world",
                "cameras": json_safe(reconstruction.cameras),
            },
        )
        quality = analyze_quality(reconstruction, self.selector.stats, metadata)
        if adjustment["reason"] is not None:
            quality["warnings"].append(
                {
                    "code": "FRAME_COUNT_REDUCED",
                    "message": "Memory policy or CUDA OOM reduced views; inspect run.json and final overlap before trusting coverage.",
                }
            )
        _write_json(run_dir / "quality.json", quality)
        timings["export"] = time.monotonic() - start
        scene = {
            "schema_version": "0.2",
            "source": {"type": "video", "file": Path(metadata.path).name},
            "coordinate_system": {
                "handedness": "right",
                "up_axis": "Z",
                "units": "meters when scale type is metric",
            },
            "scale": json_safe(reconstruction.scale),
            "geometry": {
                "point_cloud": "pointcloud.ply",
                "depth_maps": "depthmaps.npz" if reconstruction.depth_maps else None,
                "point_count": len(reconstruction.points.xyz),
                "valid_point_count": valid_point_count,
                "preview": "preview.glb" if preview_available else None,
                "preview_primitive": "points",
            },
            "cameras": "cameras.json",
            "keyframes": "keyframes.json",
            "quality": "quality.json",
            "confidence": json_safe(reconstruction.confidence),
            "pixel_transforms": reconstruction.pixel_transforms,
            "video_preprocessing": self.ingestor.preprocessing,
        }
        _write_json(run_dir / "scene.json", scene)
        run_metadata = _run_metadata(
            metadata, reconstruction, self.selector.stats, frames, requested_device, self.config
        )
        run_metadata.update(
            {
                "timestamp_utc": datetime.now(UTC).isoformat(),
                "timings_seconds": timings,
                "warnings": [item["code"] for item in quality["warnings"]],
                "status": "complete",
                "memory_adjustment": adjustment,
                "memory_settings": asdict(self.config.memory),
                "reconstruction_attempts": attempts,
            }
        )
        _write_json(run_dir / "run.json", run_metadata)
        logger.info(
            "Complete: %d points, %d cameras → %s",
            len(reconstruction.points.xyz),
            len(reconstruction.cameras),
            run_dir,
        )
        return run_dir

    def _write_keyframes(self, run_dir: Path, frames: list[FrameObservation]) -> None:
        _write_json(
            run_dir / "keyframes.json",
            {
                "candidate_count": self.selector.stats.candidate_count,
                "schema_version": "0.2",
                "video_preprocessing": self.ingestor.preprocessing,
                "selected_count": len(frames),
                "sampling_interval_seconds": self.config.video.candidate_interval_seconds,
                "source_frame_index_note": "Approximate when the source is variable-frame-rate.",
                "frames": [
                    {**frame.to_dict(), "image_path": f"frames/frame_{frame.frame_id:04d}.jpg"}
                    for frame in frames
                ],
            },
        )

    def _infer(
        self,
        frames: list[FrameObservation],
        context: ReconstructionContext,
        run_dir: Path,
        timings: dict[str, float],
        metadata: VideoMetadata,
        progress: ProgressReporter | None = None,
    ) -> tuple[list[FrameObservation], ReconstructionResult, dict[str, Any], list[dict[str, Any]]]:
        """Bounded CUDA-only retries; release failed tensors before loading again."""
        attempts = []
        adjustment = {
            "requested_keyframes": len(frames),
            "used_keyframes": len(frames),
            "reason": None,
        }
        timings["model_loading"] = 0.0
        timings["reconstruction"] = 0.0
        loaded = False
        failure_type: str | None = None
        cleanup_failure: dict[str, str] | None = None

        def record_failure() -> None:
            self._write_keyframes(run_dir, frames)
            _write_json(
                run_dir / "run.json",
                {
                    "schema_version": "0.1",
                    "status": "failed",
                    "twinforge_version": __version__,
                    "timestamp_utc": datetime.now(UTC).isoformat(),
                    "failure": {"type": failure_type},
                    "cleanup_failure": cleanup_failure,
                    "requested_device": context.device,
                    "backend": type(self.backend).__name__,
                    "backend_settings": asdict(self.config.backend),
                    "selection_settings": asdict(self.config.keyframes),
                    "video_settings": asdict(self.config.video),
                    "video_preprocessing": self.ingestor.preprocessing,
                    "video": {**asdict(metadata), "path": Path(metadata.path).name},
                    "memory_adjustment": adjustment,
                    "memory_settings": asdict(self.config.memory),
                    "reconstruction_attempts": attempts,
                    "candidate_frames": self.selector.stats.candidate_count,
                    "selected_keyframes": len(frames),
                    "timings_seconds": timings,
                },
            )

        def prepare() -> None:
            nonlocal loaded
            if progress:
                progress.emit("loading_model")
            start = time.monotonic()
            loaded = True  # close partially prepared backends too
            try:
                self.backend.prepare(context)
            finally:
                timings["model_loading"] += time.monotonic() - start

        try:
            self._write_keyframes(run_dir, frames)
            prepare()
            memory = self.backend.memory_info()
            adjustment = plan_frame_budget(
                memory,
                self.config.memory,
                self.config.backend.maximum_keyframes,
                len(frames),
                self.config.keyframes.minimum_keyframes,
            )
            frames = self.selector.reduce(frames, adjustment["used_keyframes"])
            logger.info(
                "[4/5] Running reconstruction with %d views (%s)",
                len(frames),
                adjustment["policy"]["basis"],
            )
            while True:
                if progress:
                    progress.emit(
                        "reconstructing",
                        selected_images=len(frames),
                        actual_device=memory.device,
                        resource_adjustment=adjustment,
                    )
                self._write_keyframes(run_dir, frames)
                start = time.monotonic()
                attempt = {
                    "frame_count": len(frames),
                    "frame_ids": [frame.frame_id for frame in frames],
                    "device": memory.device,
                    "device_memory": asdict(memory),
                }
                attempts.append(attempt)
                retry = False
                try:
                    result = self.backend.reconstruct(frames, context)
                    attempt["outcome"] = "success"
                    return frames, result, adjustment, attempts
                except OutOfMemoryReconstructionError:
                    attempt["outcome"] = (
                        "cuda_oom" if memory.device.startswith("cuda") else "out_of_memory"
                    )
                    next_count = len(frames) // 2
                    retry = (
                        memory.device.startswith("cuda")
                        and len(attempts) <= self.config.memory.maximum_oom_retries
                        and next_count >= self.config.keyframes.minimum_keyframes
                    )
                    if not retry:
                        raise
                except Exception:
                    attempt["outcome"] = "failed"
                    raise
                finally:
                    attempt["duration_seconds"] = time.monotonic() - start
                    timings["reconstruction"] += attempt["duration_seconds"]
                # Leave the exception scope so its traceback no longer retains GPU tensors.
                if retry:
                    loaded = False
                    self.backend.close()
                    frames = self.selector.reduce(frames, next_count)
                    adjustment.update(used_keyframes=len(frames), reason="cuda_oom")
                    logger.warning(
                        "CUDA OOM: retrying with %d views; timeline endpoints retained", len(frames)
                    )
                    prepare()
                    memory = self.backend.memory_info()
        except Exception as exc:
            failure_type = type(exc).__name__
            record_failure()
            raise
        finally:
            if loaded:
                try:
                    self.backend.close()
                except Exception as exc:
                    cleanup_failure = {"type": type(exc).__name__}
                    if failure_type is not None:
                        logger.exception(
                            "Backend cleanup also failed; preserving the original failure"
                        )
                        record_failure()
                    else:
                        failure_type = "ReconstructionFailedError"
                        record_failure()
                        raise ReconstructionFailedError(
                            "Backend cleanup failed; reconstruction attempt records remain in run.json."
                        ) from exc


def _run_metadata(
    metadata: VideoMetadata,
    result: ReconstructionResult,
    selection: SelectionStats,
    frames: list[FrameObservation],
    requested_device: str,
    config: TwinForgeConfig,
) -> dict[str, Any]:
    torch_version, cuda_version, gpu_name, vram = None, None, None, None
    try:
        import torch

        torch_version, cuda_version = torch.__version__, torch.version.cuda
        if torch.cuda.is_available():
            gpu_name = torch.cuda.get_device_name()
            free, total = torch.cuda.mem_get_info()
            vram = {
                "free_bytes": int(free),
                "total_bytes": int(total),
                "measurement_stage": "after_backend_close",
            }
    except (ImportError, RuntimeError, ValueError, TypeError):
        logger.debug("Optional runtime telemetry unavailable", exc_info=True)
    return {
        "schema_version": "0.1",
        "twinforge_version": __version__,
        "python_version": sys.version.split()[0],
        "operating_system": platform.system() + " " + platform.release(),
        "backend": result.backend,
        "backend_version": result.backend_version,
        "checkpoint": result.checkpoint,
        "backend_metadata": result.backend_metadata,
        "device": getattr(result, "backend_metadata", {}).get("device", requested_device),
        "requested_device": requested_device,
        "torch_version": torch_version,
        "cuda_version": cuda_version,
        "gpu_name": gpu_name,
        "available_vram": vram,
        "video": {
            "file": Path(metadata.path).name,
            "container": metadata.container,
            "codec": metadata.codec,
            "width": metadata.width,
            "height": metadata.height,
            "display_width": metadata.display_width,
            "display_height": metadata.display_height,
            "fps": metadata.fps,
            "duration_seconds": metadata.duration_seconds,
            "rotation_degrees": metadata.rotation_degrees,
            "approximate_frame_count": metadata.frame_count,
        },
        "candidate_frames": selection.candidate_count,
        "selected_keyframes": len(frames),
        "selection_settings": asdict(config.keyframes),
        "video_settings": asdict(config.video),
        "video_preprocessing": result.backend_metadata.get("video_preprocessing", {}),
        "model_pixel_transforms": result.pixel_transforms,
        "backend_settings": {
            "requested_maximum_keyframes": config.backend.maximum_keyframes,
            "checkpoint": config.backend.checkpoint,
            "checkpoint_revision": config.backend.checkpoint_revision,
        },
        "memory_adjustment": {
            "requested_keyframes": len(frames),
            "used_keyframes": len(frames),
            "reason": None,
        },
        "point_count": len(result.points.xyz),
        "depth_map_count": len(result.depth_maps),
        "camera_count": len(result.cameras),
        "nondeterminism_note": "Keyframe selection is deterministic; neural inference may vary by hardware and backend kernels.",
    }


def _write_json(path: Path, data: Any) -> None:
    path.write_text(json.dumps(json_safe(data), indent=2, allow_nan=False) + "\n", encoding="utf-8")


def _fmt(value: float | None) -> str:
    return "unknown" if value is None else f"{value:.3f}"
