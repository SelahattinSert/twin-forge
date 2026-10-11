"""Shared structural checks for exported smoke-test artifacts."""

import json

import numpy as np


def _read_vertices(path):
    """Read the writer's packed little-endian fields, including optional columns."""
    types = {"float": "<f4", "uchar": "u1", "uint": "<u4"}
    with path.open("rb") as stream:
        assert stream.readline() == b"ply\n", "expected a PLY file"
        assert stream.readline() == b"format binary_little_endian 1.0\n", "expected binary PLY"
        fields = []
        count = None
        for _ in range(32):
            line = stream.readline().decode("ascii").strip()
            if line == "end_header":
                break
            parts = line.split()
            if parts[:2] == ["element", "vertex"]:
                count = int(parts[2])
            elif parts[:1] == ["property"]:
                assert len(parts) == 3 and parts[1] in types, "unsupported PLY property"
                fields.append((parts[2], types[parts[1]]))
            else:
                raise AssertionError(f"unexpected PLY header: {line}")
        else:
            raise AssertionError("missing PLY end_header")
        assert count is not None and count >= 0, "missing PLY vertex count"
        dtype = np.dtype(fields)
        data = stream.read()
        assert len(data) == count * dtype.itemsize, "PLY payload does not match vertex count"
        return np.frombuffer(data, dtype=dtype)


def validate_artifacts(output):
    """Check export integrity only; this cannot demonstrate geometric accuracy."""
    vertices = _read_vertices(output / "pointcloud.ply")
    assert len(vertices) > 0, "XYZ point cloud is empty"
    assert {"x", "y", "z"} <= set(vertices.dtype.names), "XYZ properties are absent"
    xyz = np.column_stack([vertices[name] for name in ["x", "y", "z"]])
    assert np.isfinite(xyz).all(), "XYZ coordinates must all be finite"
    documents = {
        name: json.loads((output / f"{name}.json").read_text())
        for name in ["scene", "run", "cameras", "keyframes", "quality"]
    }
    scene, run = documents["scene"], documents["run"]
    assert run["status"] == "complete", "run is not complete"
    assert scene["geometry"]["point_count"] == len(vertices), "point_count disagrees with PLY"
    valid_count = scene["geometry"]["valid_point_count"]
    assert isinstance(valid_count, int) and 0 < valid_count <= len(vertices), (
        "invalid valid_point_count"
    )
    if "valid" in vertices.dtype.names:
        assert np.isin(vertices["valid"], [0, 1]).all(), "invalid PLY validity values"
        assert valid_count == int(vertices["valid"].sum()), "valid_point_count disagrees with PLY"
    scale = scene["scale"]
    assert {"type", "meters_per_unit", "confidence", "source", "details"} <= scale.keys(), (
        "invalid scale schema"
    )
    assert scale["type"] in {
        "relative",
        "estimated_metric",
        "calibrated_metric",
        "measured_metric",
    }, "invalid scale type"
    units = scale["meters_per_unit"]
    if scale["type"] == "relative":
        assert units is None, "relative scale must have null meters_per_unit"
    else:
        assert isinstance(units, (int, float)) and np.isfinite(units) and units > 0, (
            "invalid metric scale"
        )
    assert isinstance(scale["details"], dict), "invalid scale details"
    confidence = scale["confidence"]
    assert confidence is None or (
        isinstance(confidence, (int, float)) and np.isfinite(confidence) and 0 <= confidence <= 1
    ), "invalid scale confidence"
    assert scale["source"] is None or isinstance(scale["source"], str), "invalid scale source"
    frames = documents["keyframes"]["frames"]
    selected_ids = [frame["frame_id"] for frame in frames]
    assert selected_ids and len(set(selected_ids)) == len(selected_ids), (
        "invalid selected frame IDs"
    )
    assert all(isinstance(i, int) and i >= 0 for i in selected_ids), "invalid selected frame ID"
    assert run["selected_keyframes"] == len(frames), (
        "run selected_keyframes disagrees with keyframes"
    )
    cameras = documents["cameras"]["cameras"]
    camera_ids = [camera["frame_id"] for camera in cameras]
    assert len(camera_ids) == len(selected_ids) and set(camera_ids) == set(selected_ids), (
        "camera frame IDs disagree with keyframes"
    )
    for camera in cameras:
        pose = np.asarray(camera.get("camera_to_world"), dtype=float)
        assert pose.shape == (4, 4) and np.isfinite(pose).all(), "camera pose must be finite (4, 4)"
    assert "source_frame_id" in vertices.dtype.names, "PLY source_frame_id is absent"
    assert set(vertices["source_frame_id"].tolist()) <= set(selected_ids), (
        "PLY source_frame_id references an unselected frame"
    )
    return {"point_count": len(vertices), "selected_keyframes": len(frames)}
