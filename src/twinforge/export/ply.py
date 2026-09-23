"""Binary little-endian PLY point cloud export."""

from __future__ import annotations

from pathlib import Path

import numpy as np

from twinforge.core.types import PointCloud
from twinforge.exceptions import ExportError


def write_ply(path: Path, cloud: PointCloud) -> None:
    """Write geometry, RGB, and optional confidence/source frame scalar properties."""
    path.parent.mkdir(parents=True, exist_ok=True)
    has_rgb = cloud.rgb is not None
    has_confidence = cloud.confidence is not None
    has_source = cloud.source_frame_id is not None
    has_validity = cloud.valid_mask is not None
    properties = ["property float x", "property float y", "property float z"]
    dtype_fields: list[tuple] = [("x", "<f4"), ("y", "<f4"), ("z", "<f4")]
    if has_rgb:
        properties.extend(["property uchar red", "property uchar green", "property uchar blue"])
        dtype_fields.extend([("red", "u1"), ("green", "u1"), ("blue", "u1")])
    if has_confidence:
        properties.append("property float confidence")
        dtype_fields.append(("confidence", "<f4"))
    if has_source:
        properties.append("property uint source_frame_id")
        dtype_fields.append(("source_frame_id", "<u4"))
    if has_validity:
        properties.append("property uchar valid")
        dtype_fields.append(("valid", "u1"))
    header = "\n".join(
        [
            "ply",
            "format binary_little_endian 1.0",
            f"element vertex {len(cloud.xyz)}",
            *properties,
            "end_header",
            "",
        ]
    ).encode("ascii")
    try:
        with path.open("wb") as stream:
            stream.write(header)
            record = np.empty(len(cloud.xyz), dtype=np.dtype(dtype_fields))
            for axis, name in enumerate(("x", "y", "z")):
                record[name] = cloud.xyz[:, axis]
            if has_rgb:
                colors = np.clip(cloud.rgb, 0, 255).astype(np.uint8, copy=False)
                for axis, name in enumerate(("red", "green", "blue")):
                    record[name] = colors[:, axis]
            if has_confidence:
                record["confidence"] = cloud.confidence
            if has_source:
                record["source_frame_id"] = cloud.source_frame_id
            if has_validity:
                record["valid"] = np.asarray(cloud.valid_mask, dtype=np.uint8)
            stream.write(record.tobytes())
    except OSError as exc:
        raise ExportError(f"Could not write point cloud {path}: {exc}") from exc
