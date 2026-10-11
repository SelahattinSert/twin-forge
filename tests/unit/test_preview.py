"""Real-point provenance survives frame-balanced sampling and binary transport."""

import json
import struct
from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest

from twinforge.scene.types import SceneArtifact, SceneFrame
from twinforge.viewer.preview import build_frame_points, build_preview, encode_bundle


def artifact(counts=(2, 12, 21), provenance=True):
    count = sum(counts)
    fields = [(name, "<f4") for name in ("x", "y", "z", "confidence")]
    fields += [(name, "u1") for name in ("red", "green", "blue", "valid")]
    if provenance:
        fields += [("source_frame_id", "<u4")]
    records = np.zeros(count, dtype=fields)
    for axis, name in enumerate(("x", "y", "z")):
        records[name] = np.arange(count) + axis / 10
    records["red"] = np.arange(count)
    records["confidence"] = np.arange(count) + 1
    records["valid"] = 1
    if provenance:
        records["source_frame_id"] = np.repeat([3, 17, 21], counts)
    records.flags.writeable = False
    return SceneArtifact(
        Path("scene.json"),
        "a" * 64,
        "0.1",
        Path("source"),
        Path("cloud.ply"),
        "b" * 64,
        records,
        {"up_axis": "Z"},
        {"type": "relative"},
        {},
        (),
        tuple(SceneFrame(i, float(i), Path(f"{i}.jpg")) for i in (3, 17, 21)),
        (),
    )


def test_balanced_samples_are_exact_deterministic_original_points():
    scene = artifact()
    bundle = build_preview(scene, 12)
    other = build_preview(scene, 12)
    np.testing.assert_array_equal(bundle.point_indices, other.point_indices)
    assert len(np.unique(bundle.point_indices)) == 12
    assert dict(zip(*np.unique(bundle.frame_ids, return_counts=True), strict=True)) == {
        3: 2,
        17: 5,
        21: 5,
    }
    assert bundle.original_point_count == 35
    for axis, name in enumerate(("x", "y", "z")):
        np.testing.assert_array_equal(
            bundle.xyz[:, axis], scene.point_records[name][bundle.point_indices]
        )
    np.testing.assert_array_equal(
        bundle.rgb[:, 0], scene.point_records["red"][bundle.point_indices]
    )
    assert bundle.pixel_ids is None


def test_preview_excludes_invalid_but_full_frame_keeps_all_source_rows():
    scene = artifact()
    rows = scene.point_records.copy()
    rows["valid"][2] = 0
    rows["x"][3] = np.nan
    scene = replace(scene, point_records=rows)
    preview = build_preview(scene)
    assert 2 not in preview.point_indices and 3 not in preview.point_indices
    full = build_frame_points(scene, 17)
    np.testing.assert_array_equal(full.point_indices, np.arange(2, 14))
    assert full.point_count == 12 and full.eligible_point_count == 10
    assert not full.valid[0] and not full.valid[1]


def test_preview_without_source_fields_does_not_invent_provenance():
    scene = artifact(provenance=False)
    bundle = build_preview(scene, 7)
    assert bundle.frame_ids is None and bundle.pixel_ids is None
    with pytest.raises(ValueError, match="no source frame"):
        build_frame_points(scene, 3)


def test_empty_cloud_and_empty_frame_are_supported():
    scene = artifact((0, 0, 0))
    bundle = build_preview(scene)
    assert bundle.xyz.shape == (0, 3) and bundle.point_count == 0
    assert build_frame_points(scene, 3).point_count == 0


@pytest.mark.parametrize("limit", [0, -1, 500001, 1.5, True])
def test_preview_budget_is_capped(limit):
    with pytest.raises(ValueError, match="maximum_points"):
        build_preview(artifact(), limit)


def test_binary_transport_preserves_raw_uint64_point_indices_and_rgb():
    bundle = build_preview(artifact(), 9)
    data = encode_bundle(bundle)
    assert data[:4] == b"TFP1"
    length = struct.unpack("<I", data[4:8])[0]
    header = json.loads(data[8 : 8 + length])
    assert header["count"] == 9 and header["original_point_count"] == 35
    assert "pixel_ids" not in header["columns"]
    for name in ("xyz", "rgb", "point_indices", "confidence", "frame_ids", "valid"):
        info = header["columns"][name]
        assert info["offset"] % 8 == 0
        received = np.frombuffer(
            data, dtype=info["dtype"], count=int(np.prod(info["shape"])), offset=info["offset"]
        ).reshape(info["shape"])
        np.testing.assert_array_equal(received, getattr(bundle, name))


def test_budget_smaller_than_frame_count_terminates_deterministically():
    bundle = build_preview(artifact(), 1)
    assert bundle.point_count == 1 and bundle.frame_ids[0] == 3
