"""Binary serialization for per-frame camera-space depth maps."""

from __future__ import annotations

from pathlib import Path

import numpy as np

from twinforge.core.types import DepthMap
from twinforge.exceptions import ExportError


def write_depth_maps(path: Path, depth_maps: list[DepthMap]) -> None:
    """Write depth arrays and provenance to a compressed NPZ, never JSON tensors."""
    if not depth_maps:
        raise ExportError("Cannot write an empty depth-map archive.")
    arrays: dict[str, np.ndarray] = {
        "frame_ids": np.asarray([item.frame_id for item in depth_maps], dtype=np.uint32),
        "timestamps_seconds": np.asarray(
            [item.timestamp_seconds for item in depth_maps], dtype=np.float64
        ),
        "depth_convention": np.asarray("OpenCV camera +Z forward"),
        "unit_note": np.asarray("meters when scene scale is metric"),
    }
    for item in depth_maps:
        arrays[f"depth_z_{item.frame_id:04d}"] = np.asarray(item.depth_z, dtype=np.float32)
        if item.confidence is not None:
            arrays[f"confidence_{item.frame_id:04d}"] = np.asarray(
                item.confidence, dtype=np.float32
            )
        if item.valid_mask is not None:
            arrays[f"valid_{item.frame_id:04d}"] = np.asarray(item.valid_mask, dtype=np.bool_)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        np.savez_compressed(path, **arrays)
    except OSError as exc:
        raise ExportError(f"Could not write depth maps {path}: {exc}") from exc
