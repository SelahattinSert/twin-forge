"""Resolve picks against original PLY rows, never display coordinates."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime

import numpy as np

from twinforge.measurements.errors import MeasurementValidationError
from twinforge.measurements.types import MeasurementObservation
from twinforge.scene.provenance import PixelTransform, point_pixel_indices
from twinforge.scene.reader import sha256_file
from twinforge.scene.types import SceneArtifact


def _mapping(scene, frame_id):
    data = next((item for item in scene.pixel_transforms if item["frame_id"] == frame_id), None)
    return PixelTransform(**{**data, "crop_bbox": tuple(data["crop_bbox"])}) if data else None


def resolve_observation(
    scene: SceneArtifact, item: MeasurementObservation
) -> MeasurementObservation:
    """Recompute a frozen observation and reject any source-derived field mismatch."""
    resolved = measure_segment(
        scene,
        item.point_indices,
        reference_id=item.reference_id,
        selection_origin=item.selection_origin,
        correspondence_state=item.correspondence_state,
        selected_at=item.selected_at,
        source_pixels=item.source_pixels,
    )
    resolved = replace(
        resolved,
        observation_id=item.observation_id,
        revision=item.revision,
        correction_reason=item.correction_reason,
        submission_key=item.submission_key,
        submission_fingerprint=item.submission_fingerprint,
    )
    if (resolved.xyz, resolved.frame_id, resolved.source_view_sha256) != (
        item.xyz,
        item.frame_id,
        item.source_view_sha256,
    ):
        raise ValueError("Saved endpoints disagree with original PLY or source image")
    if resolved != item:
        raise ValueError("Saved endpoint provenance disagrees with original PLY or source image")
    return resolved


def resolve_image_pixel(scene: SceneArtifact, frame_id: int, source_pixel) -> int:
    mapping = _mapping(scene, frame_id)
    pixels = point_pixel_indices(scene)
    if mapping is None or pixels is None:
        raise MeasurementValidationError("pixel_provenance_unavailable")
    u, v = np.rint(mapping.source_to_model(source_pixel)).astype(int)
    if not (0 <= u < mapping.model_width and 0 <= v < mapping.model_height):
        raise MeasurementValidationError("pixel_outside_crop")
    matches = np.flatnonzero(
        (scene.point_records["source_frame_id"] == frame_id)
        & (pixels == v * mapping.model_width + u)
    )
    if len(matches) != 1:
        raise MeasurementValidationError("pixel_not_retained")
    return int(matches[0])


def measure_segment(
    scene: SceneArtifact,
    point_indices,
    *,
    reference_id: str,
    selection_origin: str,
    correspondence_state: str = "unreviewed",
    selected_at: str | None = None,
    source_pixels=None,
) -> MeasurementObservation:
    indices = tuple(point_indices)
    if (
        len(indices) != 2
        or any(type(index) is not int or not 0 <= index < scene.point_count for index in indices)
        or indices[0] == indices[1]
    ):
        raise ValueError("Two distinct in-range original PLY indices are required")
    rows = scene.point_records[list(indices)]
    xyz = np.column_stack([rows[name] for name in ("x", "y", "z")]).astype(float)
    if not np.isfinite(xyz).all() or ("valid" in rows.dtype.names and not rows["valid"].all()):
        raise MeasurementValidationError("masked_endpoints")
    if (
        "source_frame_id" not in rows.dtype.names
        or rows["source_frame_id"][0] != rows["source_frame_id"][1]
    ):
        raise ValueError("Both physical endpoints must be observed in one source frame")
    if (
        not reference_id
        or correspondence_state not in ("unreviewed", "identified")
        or selection_origin not in ("3d_pick", "image_pick", "frozen_rgb")
    ):
        raise ValueError("Invalid reference, selection origin or correspondence state")
    frame_id = int(rows["source_frame_id"][0])
    frame = next(item for item in scene.frames if item.frame_id == frame_id)
    mapping = _mapping(scene, frame_id)
    pixels = point_pixel_indices(scene)
    if source_pixels is not None:
        source_array = np.asarray(source_pixels, dtype=float)
        if source_array.shape != (2, 2) or not np.isfinite(source_array).all():
            raise ValueError("Two finite source pixels are required")
        if mapping is None or pixels is None:
            raise ValueError("Saved source pixels require justified pixel provenance")
        # Historical frozen RGB endpoints retain their original sampling convention.
        # New image and 3D picks use the recorded raster-center transform.
        if (
            selection_origin != "frozen_rgb"
            and tuple(resolve_image_pixel(scene, frame_id, pixel) for pixel in source_array)
            != indices
        ):
            raise ValueError("Saved source pixels do not resolve to the chosen original PLY rows")
    model_pixels, span, complete = None, None, False
    span_scene_units = None
    if mapping is not None and pixels is not None:
        model_pixels = tuple(
            (int(pixels[index]) % mapping.model_width, int(pixels[index]) // mapping.model_width)
            for index in indices
        )
        frame_indices = np.flatnonzero(scene.point_records["source_frame_id"] == frame_id)
        lookup = {int(pixels[index]): int(index) for index in frame_indices}
        neighborhoods = []
        complete = True
        for u, v in model_pixels:
            neighbors = []
            for y in range(v - 2, v + 3):
                for x in range(u - 2, u + 3):
                    index = (
                        lookup.get(y * mapping.model_width + x)
                        if 0 <= x < mapping.model_width and 0 <= y < mapping.model_height
                        else None
                    )
                    if index is None:
                        complete = False
                        continue
                    row = scene.point_records[index]
                    point = np.array([row[name] for name in ("x", "y", "z")], dtype=float)
                    if not np.isfinite(point).all() or (
                        "valid" in row.dtype.names and not row["valid"]
                    ):
                        complete = False
                        continue
                    neighbors.append(point)
            neighborhoods.append(np.asarray(neighbors))
        if all(len(item) for item in neighborhoods):
            distances = np.linalg.norm(
                neighborhoods[0][:, None] - neighborhoods[1][None, :], axis=-1
            )
            length = float(np.linalg.norm(xyz[0] - xyz[1]))
            span_scene_units = float(np.percentile(distances, 95) - np.percentile(distances, 5))
            if length > 0:
                span = span_scene_units / length
        if source_pixels is None:
            source_pixels = tuple(tuple(mapping.model_to_source(pixel)) for pixel in model_pixels)
    if selection_origin == "image_pick" and model_pixels is None:
        raise ValueError("Image endpoint picking requires justified pixel provenance")
    confidence = (
        tuple(float(value) if np.isfinite(value) else None for value in rows["confidence"])
        if "confidence" in rows.dtype.names
        else (None, None)
    )
    return MeasurementObservation(
        reference_id,
        scene.manifest_sha256,
        scene.point_cloud_sha256,
        frame_id,
        sha256_file(frame.image_path) if frame.image_path.is_file() else "unavailable",
        indices,
        tuple(map(tuple, xyz)),
        True,
        selection_origin,
        selected_at or datetime.now(UTC).isoformat(),
        correspondence_state,
        tuple(map(tuple, source_pixels)) if source_pixels is not None else None,
        model_pixels,
        mapping.origin if model_pixels is not None else "unavailable",
        span,
        complete,
        confidence,
        frame.timestamp_seconds,
        span_scene_units,
    )
