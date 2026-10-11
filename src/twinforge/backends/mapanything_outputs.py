"""Normalize official MapAnything tensors without importing torch or loading weights."""

from typing import Any

import cv2
import numpy as np

from twinforge.core.coordinates import (
    convert_points_opencv_world_to_twinforge,
    convert_pose_opencv_world_to_twinforge,
)
from twinforge.core.types import (
    Camera,
    ConfidenceSummary,
    DepthMap,
    FrameObservation,
    PointCloud,
    ReconstructionResult,
    ScaleEstimate,
)
from twinforge.exceptions import ReconstructionFailedError


def _array(value: Any) -> np.ndarray | None:
    if value is None:
        return None
    if hasattr(value, "detach"):
        value = value.detach().cpu().numpy()
    return np.asarray(value)


def _field(
    prediction: dict[str, Any],
    name: str,
    shape: tuple[int | None, ...],
    frame_id: int,
    *,
    required: bool = False,
    channel: bool = False,
) -> np.ndarray | None:
    """Remove only known batch/channel axes; never squeeze a spatial dimension."""
    value = _array(prediction.get(name))
    if value is None and not required:
        return None
    if value is not None:
        if value.dtype.kind not in "biuf":
            raise ReconstructionFailedError(
                f"MapAnything view {frame_id} field `{name}` expected real numeric values; "
                f"received dtype {value.dtype}."
            )
        candidates = [value]
        if shape == () and value.shape == (1, 1):
            # Runtime 1.1.3 returns B×1 here despite the infer docstring saying B.
            candidates.append(value.reshape(()))
        if value.ndim == len(shape) + 1 and value.shape[0] == 1:
            candidates.append(value[0])
        if channel:
            if value.ndim == len(shape) + 1 and value.shape[-1] == 1:
                candidates.append(value[..., 0])
            if value.ndim == len(shape) + 2 and value.shape[0] == 1 and value.shape[-1] == 1:
                candidates.append(value[0, ..., 0])
        for candidate in candidates:
            if candidate.ndim == len(shape) and all(
                expected is None or actual == expected
                for actual, expected in zip(candidate.shape, shape)
            ):
                return candidate
    actual = None if value is None else value.shape
    raise ReconstructionFailedError(
        f"MapAnything view {frame_id} field `{name}` has shape {actual}; expected "
        f"{shape} or a singleton batch axis"
        + (" and optional final singleton channel." if channel else ".")
    )


def normalize_predictions(
    predictions: list[dict[str, Any]],
    frames: list[FrameObservation],
    *,
    point_stride: int = 1,
    checkpoint: str | None = None,
    backend_version: str | None = None,
    backend_metadata: dict[str, Any] | None = None,
    pixel_transforms: list[dict[str, Any]] | None = None,
) -> ReconstructionResult:
    """Build canonical outputs; official geometry already includes metric scaling.

    Consume tensor bundles one at a time so accelerator references are released
    after copying each view. Missing confidence stays unavailable (NaN per point).
    """
    if len(predictions) != len(frames):
        raise ReconstructionFailedError(
            f"MapAnything returned {len(predictions)} view outputs for {len(frames)} input frames."
        )
    xyz_parts, rgb_parts, confidence_parts, source_parts, validity_parts = [], [], [], [], []
    cameras, depth_maps, scale_factors = [], [], []
    has_confidence = False
    pixel_parts = []
    stride = max(1, point_stride)
    for frame in frames:
        prediction = predictions.pop(0)
        frame_id = frame.frame_id
        points = _field(prediction, "pts3d", (None, None, 3), frame_id, required=True)
        height, width = points.shape[:2]
        shape = (height, width)
        colors = _field(prediction, "img_no_norm", (*shape, 3), frame_id)
        if colors is None:
            image = cv2.imread(frame.image_path, cv2.IMREAD_COLOR)
            if image is None:
                raise ReconstructionFailedError(
                    f"MapAnything view {frame_id}: could not read RGB source {frame.image_path!r}."
                )
            colors = cv2.cvtColor(cv2.resize(image, (width, height)), cv2.COLOR_BGR2RGB)
        else:
            if colors.max(initial=0.0) <= 1.0:
                colors = colors * 255.0
            colors = np.clip(colors, 0, 255).astype(np.uint8)
        confidence = _field(prediction, "conf", shape, frame_id)
        depth_z = _field(prediction, "depth_z", shape, frame_id, channel=True)
        mask_name = (
            "non_ambiguous_mask" if prediction.get("non_ambiguous_mask") is not None else "mask"
        )
        mask = _field(prediction, mask_name, shape, frame_id, channel=True)
        mask = np.ones(shape, dtype=bool) if mask is None else mask.astype(bool)
        if confidence is not None:
            confidence = confidence.astype(np.float32, copy=False)
            has_confidence = True
        if depth_z is not None:
            depth_z = depth_z.astype(np.float32, copy=False)
            depth_maps.append(
                DepthMap(
                    frame_id,
                    frame.timestamp_seconds,
                    depth_z,
                    confidence,
                    mask & np.isfinite(depth_z),
                )
            )
        frame_confidence = None
        if confidence is not None:
            confidence_valid = mask & np.isfinite(confidence)
            if confidence_valid.any():
                frame_confidence = float(np.mean(confidence[confidence_valid]))
        sampled = np.zeros(shape, dtype=bool)
        sampled[::stride, ::stride] = True
        finite = sampled & np.isfinite(points).all(axis=2)
        pixel_parts.append(np.arange(height * width, dtype=np.uint32).reshape(shape)[finite])
        selected = points[finite].astype(np.float32, copy=False)
        xyz_parts.append(convert_points_opencv_world_to_twinforge(selected).astype(np.float32))
        rgb_parts.append(colors[finite])
        source_parts.append(np.full(len(selected), frame_id, dtype=np.uint32))
        validity_parts.append(mask[finite])
        confidence_parts.append(
            confidence[finite]
            if confidence is not None
            else np.full(len(selected), np.nan, dtype=np.float32)
        )
        intrinsics = _field(prediction, "intrinsics", (3, 3), frame_id)
        pose = _field(prediction, "camera_poses", (4, 4), frame_id)
        if intrinsics is not None and (
            not np.isfinite(intrinsics).all()
            or intrinsics[0, 0] <= 0
            or intrinsics[1, 1] <= 0
            or not np.allclose(intrinsics[2], [0, 0, 1], atol=1e-5)
        ):
            raise ReconstructionFailedError(
                f"MapAnything view {frame_id} field `intrinsics` is not a finite valid pinhole matrix."
            )
        if pose is not None:
            rotation = pose[:3, :3]
            # Allow small floating-point drift, not a scaled/reflected camera basis.
            if (
                not np.isfinite(pose).all()
                or not np.allclose(pose[3], [0, 0, 0, 1], atol=1e-5)
                or not np.allclose(rotation.T @ rotation, np.eye(3), atol=1e-3)
                or not np.isclose(np.linalg.det(rotation), 1, atol=1e-3)
            ):
                raise ReconstructionFailedError(
                    f"MapAnything view {frame_id} field `camera_poses` is not a finite rigid camera-to-world matrix."
                )
            pose = convert_pose_opencv_world_to_twinforge(pose)
        cameras.append(
            Camera(
                frame_id,
                frame.timestamp_seconds,
                intrinsics.tolist() if intrinsics is not None else None,
                pose.tolist() if pose is not None else None,
                frame_confidence,
                width,
                height,
            )
        )
        factor = _field(prediction, "metric_scaling_factor", (), frame_id)
        if factor is not None:
            if not np.isfinite(factor) or factor <= 0:
                raise ReconstructionFailedError(
                    f"MapAnything view {frame_id} field `metric_scaling_factor` must be finite and positive."
                )
            scale_factors.append(float(factor))
        del prediction
    xyz = np.concatenate(xyz_parts) if xyz_parts else np.empty((0, 3), dtype=np.float32)
    if not len(xyz):
        raise ReconstructionFailedError("MapAnything returned no finite 3D points after sampling.")
    confidence_values = np.concatenate(confidence_parts) if has_confidence else None
    finite_confidence = (
        confidence_values[np.isfinite(confidence_values)] if has_confidence else np.empty(0)
    )
    if has_confidence:
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
    scale = (
        ScaleEstimate(
            type="estimated_metric",
            meters_per_unit=1.0,
            confidence=None,
            source="MapAnything image-only metric reconstruction",
            details={"metric_scaling_factor_values": scale_factors},
        )
        if scale_factors
        else ScaleEstimate(type="relative", meters_per_unit=None, confidence=None, source=None)
    )
    return ReconstructionResult(
        points=PointCloud(
            xyz=xyz,
            rgb=np.concatenate(rgb_parts),
            confidence=confidence_values,
            source_frame_id=np.concatenate(source_parts),
            valid_mask=np.concatenate(validity_parts),
            source_pixel_index=np.concatenate(pixel_parts),
        ),
        cameras=cameras,
        scale=scale,
        confidence=summary,
        backend="MapAnything",
        backend_version=backend_version,
        checkpoint=checkpoint,
        depth_maps=depth_maps,
        backend_metadata=backend_metadata or {},
        pixel_transforms=pixel_transforms or [],
    )
