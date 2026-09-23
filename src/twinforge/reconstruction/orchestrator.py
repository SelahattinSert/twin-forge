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
from twinforge.core.types import VideoMetadata, json_safe
from twinforge.exceptions import ExportError
from twinforge.export.depth import write_depth_maps
from twinforge.export.glb import write_point_glb
from twinforge.export.ply import write_ply
from twinforge.ingest.video import VideoIngestor
from twinforge.keyframes.selector import KeyframeSelector
from twinforge.quality.analyzer import analyze_quality

logger = logging.getLogger(__name__)


class ReconstructionOrchestrator:
    def __init__(self, backend: ReconstructionBackend, config: TwinForgeConfig):
        config.validate()
        self.backend, self.config = backend, config
        self.ingestor = VideoIngestor()
        self.selector = KeyframeSelector(config.keyframes)

    def run(
        self,
        video_path: Path,
        output_root: Path | None = None,
        device: str | None = None,
        debug: bool = False,
    ) -> Path:
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
        start = time.monotonic()
        with tempfile.TemporaryDirectory(prefix="twinforge-") as temporary:
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
            if len(frames) > self.config.backend.maximum_keyframes:
                raise ValueError(
                    f"Selected {len(frames)} frames, above the configured backend maximum "
                    f"({self.config.backend.maximum_keyframes}). Increase --max-keyframes or selector maximum."
                )
            _write_json(
                run_dir / "keyframes.json",
                {
                    "candidate_count": len(candidates),
                    "selected_count": len(frames),
                    "sampling_interval_seconds": self.config.video.candidate_interval_seconds,
                    "source_frame_index_note": "Approximate when the source is variable-frame-rate.",
                    "frames": [
                        {
                            **frame.to_dict(),
                            "image_path": f"frames/frame_{frame.frame_id:04d}.jpg",
                        }
                        for frame in frames
                    ],
                },
            )
            # Candidate images can dominate host RAM for long videos; selected JPEGs
            # have already been copied into the run directory.
            del candidates

            logger.info("[3/5] Loading reconstruction backend")
            requested_device = device or self.config.backend.device
            logger.info(
                "Backend: %s; checkpoint: %s; device request: %s",
                type(self.backend).__name__,
                getattr(self.backend, "checkpoint", "n/a"),
                requested_device,
            )
            start = time.monotonic()
            context = ReconstructionContext(requested_device, debug)
            try:
                self.backend.prepare(context)
                timings["model_loading"] = time.monotonic() - start
                logger.info("[4/5] Running reconstruction")
                start = time.monotonic()
                reconstruction = self.backend.reconstruct(frames, context)
                timings["reconstruction"] = time.monotonic() - start
            finally:
                self.backend.close()

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
        _write_json(run_dir / "quality.json", quality)
        timings["export"] = time.monotonic() - start
        scene = {
            "schema_version": "0.1",
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


def _run_metadata(
    metadata: VideoMetadata,
    result,
    selection,
    frames,
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
            vram = {"free_bytes": int(free), "total_bytes": int(total)}
    except ImportError:
        pass
    return {
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
