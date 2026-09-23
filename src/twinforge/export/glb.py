"""Minimal standards-compliant glTF 2.0 GLB point primitive exporter."""

from __future__ import annotations

import json
import struct
from pathlib import Path

import numpy as np

from twinforge.core.types import PointCloud
from twinforge.exceptions import ExportError


def write_point_glb(path: Path, cloud: PointCloud) -> None:
    """Write a GLB with glTF primitive mode POINTS (not a generated surface)."""
    if not len(cloud.xyz):
        raise ExportError("Cannot create a GLB point preview from an empty point cloud.")
    selected = (
        np.asarray(cloud.valid_mask, dtype=bool)
        if cloud.valid_mask is not None
        else np.ones(len(cloud.xyz), dtype=bool)
    )
    positions = np.asarray(cloud.xyz[selected], dtype="<f4")
    if not len(positions):
        raise ExportError("Cannot create a GLB preview: no points are marked valid.")
    colors = np.asarray(
        cloud.rgb[selected]
        if cloud.rgb is not None
        else np.full_like(positions, 190),
        dtype=np.uint8,
    )
    position_bytes, color_bytes = positions.tobytes(), colors.tobytes()
    binary = position_bytes + color_bytes
    binary += b"\0" * ((4 - len(binary) % 4) % 4)
    document = {
        "asset": {"version": "2.0", "generator": "TwinForge 0.1.0 point preview"},
        "scene": 0,
        "scenes": [{"nodes": [0]}],
        "nodes": [{"mesh": 0}],
        "meshes": [{"primitives": [{"attributes": {"POSITION": 0, "COLOR_0": 1}, "mode": 0}]}],
        "buffers": [{"byteLength": len(position_bytes) + len(color_bytes)}],
        "bufferViews": [
            {"buffer": 0, "byteOffset": 0, "byteLength": len(position_bytes), "target": 34962},
            {
                "buffer": 0,
                "byteOffset": len(position_bytes),
                "byteLength": len(color_bytes),
                "target": 34962,
            },
        ],
        "accessors": [
            {
                "bufferView": 0,
                "componentType": 5126,
                "count": len(positions),
                "type": "VEC3",
                "min": positions.min(axis=0).tolist(),
                "max": positions.max(axis=0).tolist(),
            },
            {
                "bufferView": 1,
                "componentType": 5121,
                "count": len(colors),
                "type": "VEC3",
                "normalized": True,
            },
        ],
    }
    json_chunk = json.dumps(document, separators=(",", ":")).encode("utf-8")
    json_chunk += b" " * ((4 - len(json_chunk) % 4) % 4)
    total_length = 12 + 8 + len(json_chunk) + 8 + len(binary)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("wb") as stream:
            stream.write(struct.pack("<4sII", b"glTF", 2, total_length))
            stream.write(struct.pack("<I4s", len(json_chunk), b"JSON"))
            stream.write(json_chunk)
            stream.write(struct.pack("<I4s", len(binary), b"BIN\0"))
            stream.write(binary)
    except OSError as exc:
        raise ExportError(f"Could not write GLB preview {path}: {exc}") from exc
