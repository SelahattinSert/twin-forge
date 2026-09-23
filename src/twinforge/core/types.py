"""Shared data models with no MapAnything-specific tensor conventions."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Literal

import numpy as np


@dataclass(frozen=True)
class VideoMetadata:
    path: str
    container: str | None
    codec: str | None
    width: int
    height: int
    fps: float | None
    duration_seconds: float
    rotation_degrees: int
    frame_count: int | None
    display_width: int
    display_height: int


@dataclass
class FrameObservation:
    frame_id: int
    source_frame_index: int
    timestamp_seconds: float
    image_path: str
    width: int
    height: int
    sharpness: float
    exposure: float
    novelty: float = 0.0
    feature_overlap: float | None = None
    rejection_reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ScaleEstimate:
    type: Literal["relative", "estimated_metric", "calibrated_metric", "measured_metric"]
    meters_per_unit: float | None
    confidence: float | None
    source: str | None
    details: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ConfidenceSummary:
    available: bool
    mean: float | None = None
    median: float | None = None
    p10: float | None = None
    p90: float | None = None
    valid_point_count: int | None = None
    source: str | None = None


@dataclass(frozen=True)
class Camera:
    frame_id: int
    timestamp_seconds: float
    intrinsics: list[list[float]] | None
    camera_to_world: list[list[float]] | None
    confidence: float | None = None
    image_width: int | None = None
    image_height: int | None = None
    coordinate_convention: str = (
        "TwinForge right-handed Z-up; meters when metric scale is available"
    )


@dataclass
class PointCloud:
    """Columnar point data; arrays remain efficient for dense outputs."""

    xyz: np.ndarray
    rgb: np.ndarray | None = None
    confidence: np.ndarray | None = None
    source_frame_id: np.ndarray | None = None
    valid_mask: np.ndarray | None = None

    def __post_init__(self) -> None:
        if self.xyz.ndim != 2 or self.xyz.shape[1] != 3:
            raise ValueError("xyz must have shape (N, 3)")
        point_count = self.xyz.shape[0]
        for name in ("rgb", "confidence", "source_frame_id", "valid_mask"):
            value = getattr(self, name)
            if value is not None and value.shape[0] != point_count:
                raise ValueError(f"{name} must contain one value per point")


@dataclass(frozen=True)
class DepthMap:
    """Camera-frame Z-depth tied to one source observation."""

    frame_id: int
    timestamp_seconds: float
    depth_z: np.ndarray
    confidence: np.ndarray | None = None
    valid_mask: np.ndarray | None = None

    def __post_init__(self) -> None:
        if self.depth_z.ndim != 2:
            raise ValueError("depth_z must have shape (H, W)")
        for name in ("confidence", "valid_mask"):
            value = getattr(self, name)
            if value is not None and value.shape != self.depth_z.shape:
                raise ValueError(f"{name} must have the same (H, W) shape as depth_z")


@dataclass
class ReconstructionResult:
    points: PointCloud
    cameras: list[Camera]
    scale: ScaleEstimate
    confidence: ConfidenceSummary
    backend: str
    backend_version: str | None
    checkpoint: str | None
    depth_maps: list[DepthMap] = field(default_factory=list)
    backend_metadata: dict[str, Any] = field(default_factory=dict)


def json_safe(value: Any) -> Any:
    """Convert nested dataclasses, paths, and NumPy scalars for JSON manifests."""
    if hasattr(value, "__dataclass_fields__"):
        return {key: json_safe(item) for key, item in asdict(value).items()}
    if isinstance(value, dict):
        return {str(key): json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe(item) for item in value]
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, np.ndarray):
        return value.tolist()
    return value
