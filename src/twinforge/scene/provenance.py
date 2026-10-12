"""Explicit raster transforms and conservatively verified historical pixel IDs."""

from __future__ import annotations

import hashlib
import zipfile
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Any

import numpy as np

from twinforge.scene.types import SceneArtifact


@dataclass(frozen=True)
class PixelTransform:
    frame_id: int
    source_width: int
    source_height: int
    resized_width: int
    resized_height: int
    crop_bbox: tuple[int, int, int, int]
    origin: str
    official_intrinsics_scale: float | None = None
    pixel_center_convention: str = "integer coordinates denote raster pixel centers"
    source_orientation: str = "EXIF-transposed saved raster"
    schema_version: str = "0.1"

    def __post_init__(self) -> None:
        dimensions = (
            self.source_width,
            self.source_height,
            self.resized_width,
            self.resized_height,
        )
        if any(type(item) is not int or item <= 0 for item in dimensions):
            raise ValueError("Raster dimensions must be positive integers")
        if len(self.crop_bbox) != 4 or any(type(item) is not int for item in self.crop_bbox):
            raise ValueError("Crop bounds must be four integer raster coordinates")
        left, top, right, bottom = self.crop_bbox
        if not (
            0 <= left < right <= self.resized_width and 0 <= top < bottom <= self.resized_height
        ):
            raise ValueError("Crop must lie inside the actual resized raster")
        if self.origin not in ("native", "derived"):
            raise ValueError("Pixel provenance must be native or derived")

    @property
    def model_width(self) -> int:
        return self.crop_bbox[2] - self.crop_bbox[0]

    @property
    def model_height(self) -> int:
        return self.crop_bbox[3] - self.crop_bbox[1]

    def source_to_model(self, pixel):
        pixel = np.asarray(pixel, dtype=float)
        if pixel.shape != (2,) or not np.isfinite(pixel).all():
            raise ValueError("A finite source pixel is required")
        return (
            (pixel + 0.5)
            * np.array(
                [self.resized_width / self.source_width, self.resized_height / self.source_height]
            )
            - 0.5
            - self.crop_bbox[:2]
        )

    def model_to_source(self, pixel):
        return (np.asarray(pixel, dtype=float) + self.crop_bbox[:2] + 0.5) * np.array(
            [self.source_width / self.resized_width, self.source_height / self.resized_height]
        ) - 0.5

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def derive_full_grid_indices(
    scene: SceneArtifact, width: int, height: int, *, point_stride: int, ordering: str
) -> np.ndarray:
    """Only a separately evidenced row-major, stride-one export can use this.

    Counts alone do not prove order. The importer must verify the export procedure
    or compare raw grids first, and record that evidence with source hashes.
    """
    if point_stride != 1 or ordering != "frame_then_row_major" or width <= 0 or height <= 0:
        raise ValueError("Historical pixel derivation requires verified stride-one row-major order")
    records = scene.point_records
    if "source_frame_id" not in records.dtype.names:
        raise ValueError("Historical derivation requires frame IDs")
    size = width * height
    expected = np.repeat([frame.frame_id for frame in scene.frames], size)
    if len(records) != len(expected) or not np.array_equal(records["source_frame_id"], expected):
        raise ValueError("Historical frames must be complete contiguous grids in recorded order")
    if not all(np.isfinite(records[name]).all() for name in ("x", "y", "z")):
        raise ValueError("Historical finite-point selection prevents full-grid derivation")
    result = np.tile(np.arange(size, dtype=np.uint32), len(scene.frames))
    result.flags.writeable = False
    return result


def point_pixel_indices(scene: SceneArtifact) -> np.ndarray | None:
    names = scene.point_records.dtype.names
    if "source_pixel_index" in names:
        return scene.point_records["source_pixel_index"]
    return scene.derived_pixel_indices


def validate_pixel_transforms(
    scene: SceneArtifact, values: list[dict[str, Any]]
) -> tuple[dict[str, Any], ...]:
    """Reject ambiguous or malformed transforms before enabling image picking."""
    if not isinstance(values, list):
        raise TypeError("Pixel provenance must be a list of transforms")
    result = []
    known = {frame.frame_id for frame in scene.frames}
    seen = set()
    for value in values:
        transform = PixelTransform(**{**value, "crop_bbox": tuple(value["crop_bbox"])})
        if transform.frame_id not in known or transform.frame_id in seen:
            raise ValueError("Pixel provenance contains unknown or duplicate frames")
        camera = next((item for item in scene.cameras if item.frame_id == transform.frame_id), None)
        if (
            camera is not None
            and camera.image_width is not None
            and (transform.model_width, transform.model_height)
            != (camera.image_width, camera.image_height)
        ):
            raise ValueError("Pixel provenance model grid disagrees with camera dimensions")
        if (
            transform.schema_version != "0.1"
            or transform.pixel_center_convention
            != "integer coordinates denote raster pixel centers"
        ):
            raise ValueError("Unknown pixel provenance schema or raster-center convention")
        if transform.official_intrinsics_scale is not None and (
            not np.isfinite(transform.official_intrinsics_scale)
            or transform.official_intrinsics_scale <= 0
        ):
            raise ValueError("Invalid official intrinsics scale")
        seen.add(transform.frame_id)
        result.append(transform.to_dict())
    return tuple(result)


def attach_verified_provenance(scene: SceneArtifact, value: dict[str, Any]) -> SceneArtifact:
    """Attach an explicit workspace import; never derive from counts alone."""
    if value.get("schema_version") != "0.1":
        raise ValueError("Unknown workspace pixel provenance schema")
    if (value.get("manifest_sha256"), value.get("point_cloud_sha256")) != (
        scene.manifest_sha256,
        scene.point_cloud_sha256,
    ):
        raise ValueError("Workspace pixel provenance hashes do not match source artifacts")
    if value.get("ordering_verification") not in (
        "raw_grid_comparison",
        "frozen_export_procedure_and_endpoint_comparison",
    ) or not value.get("evidence_files"):
        raise ValueError("Historical row order requires explicit independent export evidence")
    from twinforge.scene.reader import sha256_file

    for proof in value["evidence_files"]:
        try:
            path = Path(proof["source_path"])
            if "archive_entry" in proof:
                with zipfile.ZipFile(path) as archive:
                    digest_state = hashlib.sha256()
                    with archive.open(proof["archive_entry"]) as stream:
                        for block in iter(lambda: stream.read(1024 * 1024), b""):
                            digest_state.update(block)
                    digest = digest_state.hexdigest()
            else:
                digest = sha256_file(path)
            if digest != proof["source_sha256"]:
                raise ValueError("Historical pixel evidence file hash does not match")
        except (OSError, KeyError, zipfile.BadZipFile) as exc:
            raise ValueError("Historical pixel evidence file hash cannot be verified") from exc
    transforms = validate_pixel_transforms(scene, value["pixel_transforms"])
    if any(item["origin"] != "derived" for item in transforms):
        raise ValueError("Historical workspace pixel provenance must be labeled derived")
    indices = derive_full_grid_indices(
        scene,
        value["grid_width"],
        value["grid_height"],
        point_stride=value["point_stride"],
        ordering=value["ordering"],
    )
    return replace(
        scene, pixel_transforms=transforms, derived_pixel_indices=indices, provenance_evidence=value
    )
