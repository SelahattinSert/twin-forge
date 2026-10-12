"""Saved scene imports reject ambiguous schemas and unsafe/malformed references."""

import json

import numpy as np
import pytest

from twinforge.core.types import PointCloud
from twinforge.export.ply import write_ply
from twinforge.scene.reader import SceneReader, SceneReadError, read_point_records


@pytest.fixture
def scene_files(tmp_path):
    root = tmp_path / "run"
    root.mkdir()
    write_ply(
        root / "pointcloud.ply",
        PointCloud(
            np.array([[1, 2, 3], [4, 5, 6]], dtype=np.float32),
            rgb=np.array([[10, 20, 30], [40, 50, 60]], dtype=np.uint8),
            confidence=np.array([1.2, 4.8], dtype=np.float32),
            source_frame_id=np.array([3, 17], dtype=np.uint32),
            valid_mask=np.array([True, False]),
        ),
    )
    frames = []
    cameras = []
    for frame_id in (3, 17):
        image = root / f"frame_{frame_id}.jpg"
        image.write_bytes(b"synthetic image bytes")
        frames.append(
            {"frame_id": frame_id, "timestamp_seconds": float(frame_id), "image_path": image.name}
        )
        cameras.append(
            {
                "frame_id": frame_id,
                "timestamp_seconds": float(frame_id),
                "intrinsics": np.eye(3).tolist(),
                "camera_to_world": np.eye(4).tolist(),
            }
        )
    values = {
        "scene.json": {
            "schema_version": "0.1",
            "geometry": {"point_cloud": "pointcloud.ply", "point_count": 2},
            "cameras": "cameras.json",
            "keyframes": "keyframes.json",
            "scale": {"type": "relative"},
            "coordinate_system": {"up_axis": "Z"},
        },
        "cameras.json": {"cameras": cameras},
        "keyframes.json": {"frames": frames},
    }
    for name, value in values.items():
        (root / name).write_text(json.dumps(value))
    return root


def mutate(root, filename, change):
    path = root / filename
    value = json.loads(path.read_text())
    change(value)
    path.write_text(json.dumps(value))


def test_scene_02_accepts_new_provenance_but_rejects_unknown_transform_frames(scene_files):
    mutate(
        scene_files,
        "scene.json",
        lambda value: value.update(schema_version="0.2", pixel_transforms=[]),
    )
    assert SceneReader(scene_files).read().schema_version == "0.2"
    mutate(
        scene_files, "scene.json", lambda value: value.update(pixel_transforms=[{"frame_id": 999}])
    )
    with pytest.raises(SceneReadError, match="provenance"):
        SceneReader(scene_files).read()


def test_reader_maps_named_fields_readonly_and_links_exact_frames(scene_files):
    scene = SceneReader(scene_files).read()
    assert isinstance(scene.point_records, np.memmap)
    assert scene.point_records.flags.writeable is False
    assert len(scene.manifest_sha256) == len(scene.point_cloud_sha256) == 64
    assert scene.point_records[1]["z"] == 6
    assert scene.point_records[1]["source_frame_id"] == scene.frames[1].frame_id == 17
    assert scene.frames[0].image_path.read_bytes() == b"synthetic image bytes"
    assert scene.usage_status == "visualization_only"
    with pytest.raises(ValueError):
        scene.point_records[0]["x"] = 99


def test_explicit_experiment_import_allows_only_bounded_sibling_frames(scene_files):
    root = scene_files
    directory = root / "scene"
    directory.mkdir()
    (root / "frames").mkdir()
    for frame_id in (3, 17):
        (root / f"frame_{frame_id}.jpg").rename(root / "frames" / f"frame_{frame_id}.jpg")
    for name in ("pointcloud.ply", "scene.json", "cameras.json", "keyframes.json"):
        (root / name).rename(directory / name)
    mutate(
        directory,
        "scene.json",
        lambda value: value.update(
            schema_version="experimental-original-source-0.1",
            point_cloud="pointcloud.ply",
            point_count=2,
        ),
    )
    mutate(
        directory,
        "keyframes.json",
        lambda value: [
            frame.update(image_path="../frames/" + frame["image_path"]) for frame in value["frames"]
        ],
    )
    scene = SceneReader(directory).read()
    assert scene.source_root == root
    assert scene.frames[0].image_path.parent == root / "frames"
    mutate(
        directory,
        "keyframes.json",
        lambda value: value["frames"][0].update(image_path="../../outside.jpg"),
    )
    with pytest.raises(SceneReadError, match="escapes"):
        SceneReader(directory).read()


@pytest.mark.parametrize("version", [None, "0.3", "experimental", "unknown"])
def test_unknown_schema_is_never_guessed(scene_files, version):
    mutate(scene_files, "scene.json", lambda value: value.update(schema_version=version))
    with pytest.raises(SceneReadError, match="Unsupported scene schema"):
        SceneReader(scene_files).read()


@pytest.mark.parametrize(
    "reference, message",
    [
        ("missing.ply", "Missing"),
        ("../outside.ply", "escapes"),
        ("/tmp/outside.ply", "Invalid relative"),
    ],
)
def test_bad_references_fail_clearly(scene_files, reference, message):
    mutate(scene_files, "scene.json", lambda value: value["geometry"].update(point_cloud=reference))
    with pytest.raises(SceneReadError, match=message):
        SceneReader(scene_files).read()


def test_symlink_escape_rejected(scene_files, tmp_path):
    outside = tmp_path / "outside.jpg"
    outside.write_bytes(b"outside")
    image = scene_files / "frame_3.jpg"
    image.unlink()
    image.symlink_to(outside)
    with pytest.raises(SceneReadError, match="escapes"):
        SceneReader(scene_files).read()


def test_named_property_order_and_optional_fields(tmp_path):
    path = tmp_path / "points.ply"
    header = b"ply\nformat binary_little_endian 1.0\nelement vertex 1\nproperty float z\nproperty uchar extra\nproperty double x\nproperty float y\nend_header\n"
    row = np.array(
        [(3, 9, 1, 2)], dtype=[("z", "<f4"), ("extra", "u1"), ("x", "<f8"), ("y", "<f4")]
    )
    path.write_bytes(header + row.tobytes())
    records = read_point_records(path)
    assert [records[name][0] for name in ("x", "y", "z")] == [1, 2, 3]
    assert records["extra"][0] == 9
    path.write_bytes(path.read_bytes()[:-1])
    with pytest.raises(SceneReadError, match="byte length"):
        read_point_records(path)


@pytest.mark.parametrize(
    "update, message",
    [
        (lambda value: value["cameras"][1].update(frame_id=3), "duplicate"),
        (lambda value: value["cameras"][1].update(frame_id=999), "do not match"),
        (lambda value: value["cameras"][1].update(camera_to_world=[[1]]), "camera_to_world"),
    ],
)
def test_camera_frame_contract_validation(scene_files, update, message):
    mutate(scene_files, "cameras.json", update)
    with pytest.raises(SceneReadError, match=message):
        SceneReader(scene_files).read()


def test_missing_optional_referenced_artifact_is_error(scene_files):
    mutate(scene_files, "scene.json", lambda value: value["geometry"].update(preview="missing.glb"))
    with pytest.raises(SceneReadError, match="Missing referenced"):
        SceneReader(scene_files).read()
