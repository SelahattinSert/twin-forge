"""Adapter for the official MapAnything image-only inference API."""

from __future__ import annotations

import importlib.metadata
import logging
from typing import Any

import cv2
import numpy as np

from twinforge.backends.base import ReconstructionBackend, ReconstructionContext
from twinforge.core.coordinates import (
    convert_points_opencv_world_to_twinforge,
    convert_pose_opencv_world_to_twinforge,
)
from twinforge.core.types import (
    Camera,
    ConfidenceSummary,
    DepthMap,
    PointCloud,
    ReconstructionResult,
    ScaleEstimate,
)
from twinforge.exceptions import (
    BackendUnavailableError,
    ModelLoadError,
    OutOfMemoryReconstructionError,
    ReconstructionFailedError,
)

logger = logging.getLogger(__name__)


class MapAnythingBackend(ReconstructionBackend):
    """Runs ``MapAnything.from_pretrained`` / ``model.infer`` and normalizes its outputs."""

    def __init__(
        self,
        checkpoint: str = "facebook/map-anything-apache",
        checkpoint_revision: str | None = "00f9c245bbcb60522d1ed7f9e9d88462c6e3f38a",
        point_stride: int = 1,
    ):
        self.checkpoint = checkpoint
        self.checkpoint_revision = checkpoint_revision
        self.point_stride = max(1, point_stride)
        self._model: Any = None
        self._torch: Any = None
        self.device: str | None = None

    def _load(self, requested_device: str) -> None:
        try:
            import torch
            from mapanything.models import MapAnything
        except ImportError as exc:
            raise BackendUnavailableError(
                "MapAnything is not installed. Use Python 3.12 and install TwinForge with `pip install -e '.[mapanything]'`, then install a PyTorch build for this machine."
            ) from exc
        device = requested_device
        if device == "auto":
            device = "cuda" if torch.cuda.is_available() else "cpu"
        if device.startswith("cuda") and not torch.cuda.is_available():
            raise BackendUnavailableError(
                "CUDA was requested but this PyTorch build has no available CUDA device."
            )
        if device not in ("cpu", "cuda") and not device.startswith("cuda:"):
            raise BackendUnavailableError(
                f"MapAnything documentation currently supports CPU or CUDA, not {device!r}."
            )
        try:
            self._model = MapAnything.from_pretrained(
                self.checkpoint, revision=self.checkpoint_revision
            ).to(device).eval()
        except Exception as exc:
            raise ModelLoadError(
                f"Could not load MapAnything checkpoint {self.checkpoint!r}: {exc}"
            ) from exc
        self._torch = torch
        self.device = device

    def prepare(self, context: ReconstructionContext) -> None:
        self._load(context.device)

    def close(self) -> None:
        if self._model is not None:
            del self._model
            self._model = None
        if self._torch is not None and self.device and self.device.startswith("cuda"):
            self._torch.cuda.empty_cache()
        self._torch = None
        self.device = None

    def reconstruct(
        self,
        frames,
        context: ReconstructionContext,
    ) -> ReconstructionResult:
        if self._model is None:
            self._load(context.device)
        torch = self._torch
        try:
            from mapanything.utils.image import load_images

            views = load_images([frame.image_path for frame in frames])
            memory_preflight = _memory_preflight(views, torch, self.device)
            if memory_preflight["xyz_output_exceeds_free_vram"] is True:
                logger.warning(
                    "The float32 XYZ outputs alone have a lower-bound size of %.2f GiB, "
                    "larger than currently free VRAM (%.2f GiB). Peak inference memory "
                    "cannot be reliably predicted; consider --max-keyframes.",
                    memory_preflight["xyz_output_lower_bound_bytes"] / 1024**3,
                    memory_preflight["free_vram_bytes"] / 1024**3,
                )
            else:
                logger.info(
                    "Memory preflight: float32 XYZ output lower bound %.2f GiB; free VRAM %s. "
                    "This is not a peak-memory prediction.",
                    memory_preflight["xyz_output_lower_bound_bytes"] / 1024**3,
                    (
                        f"{memory_preflight['free_vram_bytes'] / 1024**3:.2f} GiB"
                        if memory_preflight["free_vram_bytes"] is not None
                        else "unavailable"
                    ),
                )
            with torch.inference_mode():
                predictions = self._model.infer(
                    views,
                    memory_efficient_inference=True,
                    minibatch_size=1,
                    use_amp=True,
                    # Retain raw prediction geometry; store validity separately.
                    apply_mask=False,
                    mask_edges=False,
                    apply_confidence_mask=False,
                )
            del views
        except Exception as exc:
            if _is_oom(exc, torch):
                vram = _available_vram(torch, self.device)
                raise OutOfMemoryReconstructionError(
                    f"MapAnything ran out of memory with {len(frames)} selected frames. "
                    f"Available VRAM: {vram or 'unavailable'}. Try --max-keyframes {max(3, len(frames) // 2)}."
                ) from exc
            if context.debug:
                logger.exception("MapAnything inference failed")
            raise ReconstructionFailedError(f"MapAnything inference failed: {exc}") from exc
        if len(predictions) != len(frames):
            raise ReconstructionFailedError(
                f"MapAnything returned {len(predictions)} view outputs for {len(frames)} input frames."
            )
        xyz_parts: list[np.ndarray] = []
        rgb_parts: list[np.ndarray] = []
        confidence_parts: list[np.ndarray] = []
        source_parts: list[np.ndarray] = []
        validity_parts: list[np.ndarray] = []
        cameras: list[Camera] = []
        depth_maps: list[DepthMap] = []
        scale_factors: list[float] = []
        # Drop each backend tensor bundle as soon as it has been normalized so
        # multi-view outputs do not all remain resident on the accelerator.
        for frame in frames:
            prediction = predictions.pop(0)
            points = _array(prediction.get("pts3d"))
            if points is None:
                raise ReconstructionFailedError(
                    "MapAnything output did not contain the documented `pts3d` field."
                )
            points = _single_batch(points)
            height, width = points.shape[:2]
            colors = _array(prediction.get("img_no_norm"))
            if colors is not None:
                colors = _single_batch(colors)
                if colors.shape[:2] != (height, width):
                    colors = cv2.resize(
                        colors.astype(np.float32), (width, height), interpolation=cv2.INTER_AREA
                    )
                if colors.max(initial=0.0) <= 1.0:
                    colors = colors * 255.0
                colors = np.clip(colors, 0, 255).astype(np.uint8)
            else:
                image = cv2.imread(frame.image_path, cv2.IMREAD_COLOR)
                colors = cv2.cvtColor(cv2.resize(image, (width, height)), cv2.COLOR_BGR2RGB)
            confidence = _array(prediction.get("conf"))
            if confidence is not None:
                confidence = np.squeeze(_single_batch(confidence))
            depth_z = _array(prediction.get("depth_z"))
            if depth_z is not None:
                depth_z = np.squeeze(_single_batch(depth_z)).astype(np.float32, copy=False)
            mask = _array(prediction.get("non_ambiguous_mask"))
            if mask is None:
                mask = _array(prediction.get("mask"))
            if mask is not None:
                mask = np.squeeze(_single_batch(mask)).astype(bool)
            else:
                mask = np.ones((height, width), dtype=bool)
            if depth_z is not None:
                if depth_z.shape != (height, width):
                    depth_z = cv2.resize(
                        depth_z, (width, height), interpolation=cv2.INTER_NEAREST
                    )
                depth_confidence = confidence
                if depth_confidence is not None and depth_confidence.shape != (height, width):
                    depth_confidence = cv2.resize(
                        depth_confidence.astype(np.float32),
                        (width, height),
                        interpolation=cv2.INTER_LINEAR,
                    )
                depth_maps.append(
                    DepthMap(
                        frame_id=frame.frame_id,
                        timestamp_seconds=frame.timestamp_seconds,
                        depth_z=depth_z,
                        confidence=depth_confidence.astype(np.float32, copy=False)
                        if depth_confidence is not None
                        else None,
                        valid_mask=mask & np.isfinite(depth_z),
                    )
                )
            frame_confidence = None
            if confidence is not None:
                confidence_valid = mask & np.isfinite(confidence)
                if confidence_valid.any():
                    frame_confidence = float(np.mean(confidence[confidence_valid]))
            sampled = np.zeros((height, width), dtype=bool)
            sampled[:: self.point_stride, :: self.point_stride] = True
            finite_points = sampled & np.isfinite(points).all(axis=2)
            selected_points = points[finite_points].astype(np.float32, copy=False)
            xyz_parts.append(
                convert_points_opencv_world_to_twinforge(selected_points).astype(
                    np.float32, copy=False
                )
            )
            rgb_parts.append(colors[finite_points])
            source_parts.append(np.full(len(selected_points), frame.frame_id, dtype=np.uint32))
            validity_parts.append(mask[finite_points])
            if confidence is not None:
                confidence_parts.append(confidence[finite_points].astype(np.float32, copy=False))
            intrinsics = _array(prediction.get("intrinsics"))
            pose = _array(prediction.get("camera_poses"))
            camera_matrix = _first_matrix(intrinsics, (3, 3))
            pose_matrix = _first_matrix(pose, (4, 4))
            if pose_matrix is not None:
                pose_matrix = convert_pose_opencv_world_to_twinforge(pose_matrix)
            cameras.append(
                Camera(
                    frame_id=frame.frame_id,
                    timestamp_seconds=frame.timestamp_seconds,
                    intrinsics=camera_matrix.tolist() if camera_matrix is not None else None,
                    camera_to_world=pose_matrix.tolist() if pose_matrix is not None else None,
                    confidence=frame_confidence,
                    image_width=width,
                    image_height=height,
                )
            )
            factor = _scalar(prediction.get("metric_scaling_factor"))
            if factor is not None:
                scale_factors.append(factor)
            del prediction
        xyz = np.concatenate(xyz_parts, axis=0) if xyz_parts else np.empty((0, 3), dtype=np.float32)
        rgb = np.concatenate(rgb_parts, axis=0) if rgb_parts else np.empty((0, 3), dtype=np.uint8)
        confidence_values = np.concatenate(confidence_parts) if confidence_parts else None
        source_ids = np.concatenate(source_parts) if source_parts else np.empty(0, dtype=np.uint32)
        validity = np.concatenate(validity_parts) if validity_parts else np.empty(0, dtype=bool)
        if not len(xyz):
            raise ReconstructionFailedError(
                "MapAnything returned no valid 3D points after applying its validity mask."
            )
        finite_confidence = (
            confidence_values[np.isfinite(confidence_values)]
            if confidence_values is not None
            else np.empty(0, dtype=np.float32)
        )
        if confidence_values is not None:
            summary = ConfidenceSummary(
                available=True,
                mean=float(np.mean(finite_confidence)) if finite_confidence.size else None,
                median=float(np.median(finite_confidence)) if finite_confidence.size else None,
                p10=float(np.percentile(finite_confidence, 10)) if finite_confidence.size else None,
                p90=float(np.percentile(finite_confidence, 90)) if finite_confidence.size else None,
                valid_point_count=int(finite_confidence.size),
                source="MapAnything per-pixel `conf` output",
            )
        else:
            summary = ConfidenceSummary(available=False, source=None)
        if scale_factors:
            scale = ScaleEstimate(
                type="estimated_metric",
                meters_per_unit=1.0,
                confidence=None,
                source="MapAnything image-only metric reconstruction",
                details={"metric_scaling_factor_values": scale_factors},
            )
        else:
            scale = ScaleEstimate(
                type="relative", meters_per_unit=None, confidence=None, source=None
            )
        try:
            version = importlib.metadata.version("mapanything")
        except importlib.metadata.PackageNotFoundError:
            version = None
        return ReconstructionResult(
            points=PointCloud(
                xyz=xyz,
                rgb=rgb,
                confidence=confidence_values,
                source_frame_id=source_ids,
                valid_mask=validity,
            ),
            cameras=cameras,
            scale=scale,
            confidence=summary,
            backend="MapAnything",
            backend_version=version,
            checkpoint=self.checkpoint,
            depth_maps=depth_maps,
            backend_metadata={
                "device": self.device,
                "checkpoint_revision": self.checkpoint_revision,
                "point_stride": self.point_stride,
                "source_coordinate_convention": "OpenCV world coordinates; +X right, +Y down, +Z forward",
                "memory_preflight": memory_preflight,
            },
        )


def estimate_minimum_xyz_output_bytes(views: list[dict[str, Any]]) -> int:
    """Return dense float32 XYZ payload size, not total inference memory.

    MapAnything documents one (B, H, W, 3) point prediction per input view.
    Use the image dimensions after ``load_images`` resizes source frames. This
    excludes activations, other outputs, allocator overhead, and host copies.
    """
    bytes_per_xyz = 3 * np.dtype(np.float32).itemsize
    return sum(
        int(view["img"].shape[0])
        * int(view["img"].shape[2])
        * int(view["img"].shape[3])
        * bytes_per_xyz
        for view in views
    )


def _memory_preflight(views: list[dict[str, Any]], torch: Any, device: str | None) -> dict[str, Any]:
    output_floor = estimate_minimum_xyz_output_bytes(views)
    free_vram = None
    if (
        torch is not None
        and device
        and device.startswith("cuda")
        and torch.cuda.is_available()
    ):
        try:
            free_vram = int(torch.cuda.mem_get_info(device)[0])
        except (RuntimeError, ValueError, TypeError):
            pass
    return {
        "selected_keyframes": len(views),
        "xyz_output_lower_bound_bytes": output_floor,
        "free_vram_bytes": free_vram,
        "xyz_output_exceeds_free_vram": (
            output_floor > free_vram if free_vram is not None else None
        ),
        "scope": "float32 XYZ output only; excludes model weights, activations, other outputs, and allocator overhead",
        "peak_memory_estimate_available": False,
    }


def _array(value: Any) -> np.ndarray | None:
    if value is None:
        return None
    if hasattr(value, "detach"):
        value = value.detach().cpu().numpy()
    return np.asarray(value)


def _single_batch(value: np.ndarray) -> np.ndarray:
    return value[0] if value.ndim >= 1 and value.shape[0] == 1 else value


def _first_matrix(value: np.ndarray | None, shape: tuple[int, int]) -> np.ndarray | None:
    if value is None:
        return None
    while value.ndim > 2 and value.shape[0] == 1:
        value = value[0]
    return value if value.shape == shape else None


def _scalar(value: Any) -> float | None:
    array = _array(value)
    if array is None or not array.size:
        return None
    result = float(array.reshape(-1)[0])
    return result if np.isfinite(result) else None


def _is_oom(exc: Exception, torch: Any) -> bool:
    oom_type = getattr(torch.cuda, "OutOfMemoryError", ()) if torch is not None else ()
    return (bool(oom_type) and isinstance(exc, oom_type)) or "out of memory" in str(exc).lower()


def _available_vram(torch: Any, device: str | None) -> str | None:
    if (
        torch is None
        or not device
        or not device.startswith("cuda")
        or not torch.cuda.is_available()
    ):
        return None
    try:
        free_bytes, _total_bytes = torch.cuda.mem_get_info(device)
        return f"{free_bytes / (1024**3):.1f} GiB"
    except (RuntimeError, ValueError, TypeError):
        return None
