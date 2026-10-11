"""Deterministic, frame-balanced display sampling and compact binary transport."""

from __future__ import annotations

import json
import struct
from dataclasses import replace

import numpy as np

from twinforge.scene.provenance import point_pixel_indices
from twinforge.scene.types import PreviewBundle, SceneArtifact

MAX_PREVIEW_POINTS = 500_000


def _eligible(scene: SceneArtifact) -> np.ndarray:
    records = scene.point_records
    mask = np.ones(scene.point_count, dtype=bool)
    for name in ("x", "y", "z"):
        mask &= np.isfinite(records[name])
    if "valid" in records.dtype.names:
        mask &= records["valid"].astype(bool)
    return mask


def _bundle(
    scene: SceneArtifact, indices: np.ndarray, eligible_count: int, frame_id: int | None = None
) -> PreviewBundle:
    rows = scene.point_records[indices]
    names = rows.dtype.names
    xyz = np.column_stack([rows[name] for name in ("x", "y", "z")]).astype("<f4")
    rgb = (
        np.column_stack([rows[name] for name in ("red", "green", "blue")])
        if {"red", "green", "blue"}.issubset(names)
        else np.full((len(rows), 3), 190, dtype=np.uint8)
    )
    valid = np.isfinite(xyz).all(axis=1)
    pixels = point_pixel_indices(scene)
    if "valid" in names:
        valid &= rows["valid"].astype(bool)
    return PreviewBundle(
        xyz=xyz,
        rgb=np.clip(rgb, 0, 255).astype("u1"),
        point_indices=indices.astype("<u8"),
        frame_ids=rows["source_frame_id"].copy() if "source_frame_id" in names else None,
        pixel_ids=pixels[indices].copy() if pixels is not None else None,
        confidence=rows["confidence"].copy() if "confidence" in names else None,
        valid=valid,
        original_point_count=scene.point_count,
        eligible_point_count=eligible_count,
        frame_id=frame_id,
    )


def build_preview(scene: SceneArtifact, maximum_points: int = MAX_PREVIEW_POINTS) -> PreviewBundle:
    """Water-fill a deterministic budget across source frames, sampling real rows."""
    if type(maximum_points) is not int or not 1 <= maximum_points <= MAX_PREVIEW_POINTS:
        raise ValueError(f"maximum_points must be between 1 and {MAX_PREVIEW_POINTS}")
    mask = _eligible(scene)
    eligible_count = int(mask.sum())
    if eligible_count <= maximum_points:
        return _bundle(scene, np.flatnonzero(mask), eligible_count)
    records = scene.point_records
    if "source_frame_id" in records.dtype.names:
        groups = [
            np.flatnonzero(mask & (records["source_frame_id"] == frame_id))
            for frame_id in np.unique(records["source_frame_id"])
        ]
        groups = [group for group in groups if len(group)]
    else:
        groups = [np.flatnonzero(mask)]
    quotas = np.zeros(len(groups), dtype=np.int64)
    remaining = maximum_points
    while remaining:
        active = [i for i, group in enumerate(groups) if quotas[i] < len(group)]
        share, extra = divmod(remaining, len(active))
        for rank, index in enumerate(active):
            allocation = min(len(groups[index]) - quotas[index], share + (rank < extra))
            quotas[index] += allocation
            remaining -= allocation
    samples = [
        group[(np.arange(quota, dtype=np.int64) * len(group)) // quota]
        for group, quota in zip(groups, quotas, strict=True)
        if quota
    ]
    return _bundle(scene, np.sort(np.concatenate(samples)), eligible_count)


def build_frame_points(scene: SceneArtifact, frame_id: int) -> PreviewBundle:
    """Return every original row for one frame, including validity/confidence.

    The viewer renders valid finite rows. Callers still receive invalid rows and
    can reject them explicitly when producing future observations.
    """
    if frame_id not in {frame.frame_id for frame in scene.frames}:
        raise ValueError(f"Unknown source frame: {frame_id}")
    if "source_frame_id" not in scene.point_records.dtype.names:
        raise ValueError("This PLY has no source frame provenance")
    indices = np.flatnonzero(scene.point_records["source_frame_id"] == frame_id)
    bundle = _bundle(scene, indices, 0, frame_id)
    return replace(bundle, eligible_point_count=int(bundle.valid.sum()))


def encode_bundle(bundle: PreviewBundle) -> bytes:
    """TFP1: uint32 JSON size, padded JSON header, aligned column arrays.

    Offsets are relative to the start of the whole message. uint64 indices are
    preserved across transport; the browser converts only safely bounded values.
    """
    columns = {
        "xyz": np.asarray(bundle.xyz, dtype="<f4"),
        "rgb": np.asarray(bundle.rgb, dtype="u1"),
        "point_indices": np.asarray(bundle.point_indices, dtype="<u8"),
        "valid": np.asarray(bundle.valid, dtype="u1"),
    }
    for name, dtype in (("frame_ids", "<u4"), ("pixel_ids", "<i8"), ("confidence", "<f4")):
        value = getattr(bundle, name)
        if value is not None:
            columns[name] = np.asarray(value, dtype=dtype)
    header = {
        "schema_version": "0.1",
        "count": bundle.point_count,
        "original_point_count": bundle.original_point_count,
        "eligible_point_count": bundle.eligible_point_count,
        "frame_id": bundle.frame_id,
        "columns": {},
    }
    # Fixed header region makes offsets independent of JSON length.
    offset = 4096
    parts = []
    for name, value in columns.items():
        padding = (-offset) % 8
        parts.append(bytes(padding))
        offset += padding
        data = value.tobytes()
        header["columns"][name] = {
            "offset": offset,
            "dtype": value.dtype.str,
            "shape": list(value.shape),
            "bytes": len(data),
        }
        parts.append(data)
        offset += len(data)
    encoded = json.dumps(header, separators=(",", ":"), allow_nan=False).encode()
    if len(encoded) > 4088:
        raise ValueError("Preview header exceeds reserved region")
    return (
        b"TFP1"
        + struct.pack("<I", len(encoded))
        + encoded
        + bytes(4088 - len(encoded))
        + b"".join(parts)
    )
