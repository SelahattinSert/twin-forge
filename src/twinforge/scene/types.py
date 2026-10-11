"""Backend-independent, read-only contracts for saved scene inspection."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from twinforge.core.types import Camera


@dataclass(frozen=True)
class SceneFrame:
    frame_id: int
    timestamp_seconds: float
    image_path: Path
    source_frame_index: int | None = None
    width: int | None = None
    height: int | None = None


@dataclass(frozen=True)
class SceneArtifact:
    """Original PLY rows remain the stable identity for every displayed point.

    No source-to-model pixel correspondence is inferred from row order. A future
    schema must record that mapping before image-based observations can use it.
    """

    manifest_path: Path
    manifest_sha256: str
    schema_version: str
    source_root: Path
    point_cloud_path: Path
    point_cloud_sha256: str
    point_records: np.ndarray
    coordinate_system: dict[str, Any] | str
    scale: dict[str, Any]
    confidence: dict[str, Any]
    cameras: tuple[Camera, ...]
    frames: tuple[SceneFrame, ...]
    referenced_paths: tuple[Path, ...]
    usage_status: str = "visualization_only"
    pixel_transforms: tuple[dict[str, Any], ...] = ()
    derived_pixel_indices: np.ndarray | None = None
    provenance_evidence: dict[str, Any] | None = None

    @property
    def point_count(self) -> int:
        return len(self.point_records)


@dataclass(frozen=True)
class PreviewBundle:
    """Display samples with exact provenance; coordinates are never averaged."""

    xyz: np.ndarray
    rgb: np.ndarray
    point_indices: np.ndarray
    frame_ids: np.ndarray | None
    pixel_ids: np.ndarray | None
    confidence: np.ndarray | None
    valid: np.ndarray
    original_point_count: int
    eligible_point_count: int
    frame_id: int | None = None

    @property
    def point_count(self) -> int:
        return len(self.point_indices)
