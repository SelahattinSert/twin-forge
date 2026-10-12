"""Exercise the smoke validator with small synthetic exports."""

import json

import artifact_validation
import numpy as np
import pytest
import test_mapanything_smoke

from twinforge.core.types import PointCloud
from twinforge.export.ply import write_ply


def validate(path):
    function = getattr(artifact_validation, "validate_artifacts", None)
    assert callable(function), "artifact validator must be implemented"
    return function(path)


@pytest.fixture
def artifacts(tmp_path):
    write_ply(
        tmp_path / "pointcloud.ply",
        PointCloud(
            xyz=np.array([[1, 2, 3], [4, 5, 6]], dtype=np.float32),
            rgb=np.array([[4, 5, 6], [7, 8, 9]], dtype=np.uint8),
            confidence=np.array([0.8, 0.9], dtype=np.float32),
            source_frame_id=np.array([3, 17], dtype=np.uint32),
            valid_mask=np.array([True, False]),
        ),
    )
    values = {
        "scene": {
            "geometry": {"point_count": 2, "valid_point_count": 1},
            "scale": {
                "type": "estimated_metric",
                "meters_per_unit": 1.0,
                "confidence": None,
                "source": "synthetic",
                "details": {},
            },
        },
        "keyframes": {"frames": [{"frame_id": 3}, {"frame_id": 17}]},
        "cameras": {
            "cameras": [{"frame_id": i, "camera_to_world": np.eye(4).tolist()} for i in [3, 17]]
        },
        "run": {"selected_keyframes": 2, "status": "complete"},
        "quality": {"warnings": []},
    }
    for name, value in values.items():
        (tmp_path / f"{name}.json").write_text(json.dumps(value))
    return tmp_path


def mutate(path, name, callback):
    target = path / f"{name}.json"
    document = json.loads(target.read_text())
    callback(document)
    target.write_text(json.dumps(document))


def test_accepts_noncontiguous_source_ids_and_actual_ply_dtype(artifacts):
    result = validate(artifacts)
    assert result["point_count"] == 2
    assert result["selected_keyframes"] == 2


@pytest.mark.parametrize(
    "xyz", [np.empty((0, 3)), np.array([[1, np.nan, 3]]), np.array([[1, 2, np.inf]])]
)
def test_rejects_empty_or_nonfinite_xyz(artifacts, xyz):
    write_ply(artifacts / "pointcloud.ply", PointCloud(xyz=xyz))
    with pytest.raises(AssertionError, match="XYZ"):
        validate(artifacts)


@pytest.mark.parametrize("pose", [None, [[1, 2, 3]], np.full((4, 4), np.nan).tolist()])
def test_rejects_absent_or_nonfinite_poses(artifacts, pose):
    mutate(artifacts, "cameras", lambda d: d["cameras"][0].update(camera_to_world=pose))
    with pytest.raises(AssertionError, match="pose"):
        validate(artifacts)


def test_rejects_missing_pose_field(artifacts):
    mutate(artifacts, "cameras", lambda d: d["cameras"][0].pop("camera_to_world"))
    with pytest.raises(AssertionError, match="pose"):
        validate(artifacts)


def test_rejects_zero_valid_points(artifacts):
    mutate(artifacts, "scene", lambda d: d["geometry"].update(valid_point_count=0))
    with pytest.raises(AssertionError, match="valid_point_count"):
        validate(artifacts)


@pytest.mark.parametrize(
    "scale",
    [
        {},
        {"type": "invented", "meters_per_unit": 1},
        {"type": "estimated_metric", "meters_per_unit": None},
        {"type": "estimated_metric", "meters_per_unit": -1},
        {"type": "estimated_metric", "meters_per_unit": float("nan")},
        {"type": "relative", "meters_per_unit": 1},
    ],
)
def test_rejects_invalid_scale_schema(artifacts, scale):
    if scale:
        scale = {"confidence": None, "source": "synthetic", "details": {}, **scale}
    mutate(artifacts, "scene", lambda d: d.update(scale=scale))
    with pytest.raises(AssertionError, match="scale"):
        validate(artifacts)


@pytest.mark.parametrize(
    "name,change",
    [
        ("cameras", lambda d: d["cameras"][0].update(frame_id=1)),
        ("keyframes", lambda d: d["frames"][0].update(frame_id=1)),
        ("cameras", lambda d: d["cameras"].pop()),
        ("run", lambda d: d.update(selected_keyframes=3)),
    ],
)
def test_rejects_inconsistent_selected_frame_ids(artifacts, name, change):
    mutate(artifacts, name, change)
    with pytest.raises(AssertionError, match="frame|camera|keyframe"):
        validate(artifacts)


def test_rejects_unselected_point_source_id(artifacts):
    write_ply(
        artifacts / "pointcloud.ply",
        PointCloud(xyz=np.array([[1, 2, 3], [4, 5, 6]]), source_frame_id=np.array([3, 99])),
    )
    with pytest.raises(AssertionError, match="source_frame_id"):
        validate(artifacts)


@pytest.mark.parametrize(
    "device,require,expected",
    [
        ("auto", "0", "auto"),
        ("cpu", "0", "cpu"),
        ("cuda", "0", "cuda"),
        ("auto", "1", "cuda"),
        ("cuda", "1", "cuda"),
    ],
)
def test_smoke_settings_honor_device_and_small_default_cap(monkeypatch, device, require, expected):
    monkeypatch.delenv("TWINFORGE_SMOKE_MAX_KEYFRAMES", raising=False)
    monkeypatch.setenv("TWINFORGE_SMOKE_DEVICE", device)
    monkeypatch.setenv("TWINFORGE_REQUIRE_CUDA", require)
    function = getattr(test_mapanything_smoke, "smoke_settings", None)
    assert callable(function), "smoke settings helper must be implemented"
    assert function() == (4, expected)


def test_smoke_settings_accept_explicit_cap(monkeypatch):
    monkeypatch.setenv("TWINFORGE_SMOKE_MAX_KEYFRAMES", "3")
    monkeypatch.setenv("TWINFORGE_SMOKE_DEVICE", "cpu")
    monkeypatch.setenv("TWINFORGE_REQUIRE_CUDA", "0")
    function = getattr(test_mapanything_smoke, "smoke_settings", None)
    assert callable(function), "smoke settings helper must be implemented"
    assert function() == (3, "cpu")


@pytest.mark.parametrize(
    "cap,device,require",
    [("2", "cpu", "0"), ("four", "auto", "0"), ("4", "mps", "0"), ("4", "cpu", "1")],
)
def test_smoke_settings_reject_invalid_configuration(monkeypatch, cap, device, require):
    monkeypatch.setenv("TWINFORGE_SMOKE_MAX_KEYFRAMES", cap)
    monkeypatch.setenv("TWINFORGE_SMOKE_DEVICE", device)
    monkeypatch.setenv("TWINFORGE_REQUIRE_CUDA", require)
    function = getattr(test_mapanything_smoke, "smoke_settings", None)
    assert callable(function), "smoke settings helper must be implemented"
    with pytest.raises(ValueError, match="TWINFORGE"):
        function()
