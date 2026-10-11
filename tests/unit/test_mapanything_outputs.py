"""Synthetic official API outputs; no torch import or checkpoint required."""

from types import SimpleNamespace

import cv2
import numpy as np
import pytest

from twinforge.backends import mapanything
from twinforge.exceptions import ReconstructionFailedError


def normalize(predictions, stride=1, frames=None):
    function = getattr(mapanything, "normalize_predictions", None)
    assert callable(function), "adapter must expose its pure output normalizer"
    if frames is None:
        frames = [
            SimpleNamespace(frame_id=i + 7, timestamp_seconds=i * 0.5, image_path="unused.png")
            for i in range(len(predictions))
        ]
    return function(
        predictions,
        frames,
        point_stride=stride,
        checkpoint="test",
        backend_version="synthetic",
        backend_metadata={"device": "cpu"},
    )


def prediction(h=2, w=3, batched=True):
    p = {
        "pts3d": np.tile([1.0, 2.0, 3.0], (h, w, 1)),
        "img_no_norm": np.tile([0.25, 0.5, 1.0], (h, w, 1)),
        "depth_z": np.full((h, w, 1), 3.0),
        "conf": np.full((h, w), 0.8),
        "non_ambiguous_mask": np.ones((h, w), bool),
        "intrinsics": np.eye(3),
        "camera_poses": np.eye(4),
        "metric_scaling_factor": np.array(5.0),
    }
    p["camera_poses"][:3, 3] = [1.0, 2.0, 3.0]
    return {k: v[None] for k, v in p.items()} if batched else p


@pytest.mark.parametrize("h,w", [(2, 3), (1, 3), (3, 1), (1, 1)])
@pytest.mark.parametrize("batched", [True, False])
def test_preserves_spatial_axes_and_converts_coordinates_once(h, w, batched):
    result = normalize([prediction(h, w, batched)])
    np.testing.assert_allclose(result.points.xyz, np.tile([1.0, 3.0, -2.0], (h * w, 1)))
    np.testing.assert_array_equal(result.points.rgb, np.tile([63, 127, 255], (h * w, 1)))
    np.testing.assert_allclose(
        result.cameras[0].camera_to_world,
        [[1, 0, 0, 1], [0, 0, 1, 3], [0, -1, 0, -2], [0, 0, 0, 1]],
    )
    np.testing.assert_array_equal(result.cameras[0].intrinsics, np.eye(3))
    assert result.depth_maps[0].depth_z.shape == (h, w)
    np.testing.assert_allclose(result.depth_maps[0].depth_z, 3)
    assert result.scale.details == {"metric_scaling_factor_values": [5.0]}
    assert result.scale.meters_per_unit == 1
    assert result.backend_metadata == {"device": "cpu"}
    assert result.backend_version == "synthetic"


def test_raw_geometry_preserved_and_validity_is_separate():
    p = prediction()
    p["non_ambiguous_mask"][0, 0, 0] = False
    p["pts3d"][0, 0, 1] = np.nan
    p["depth_z"][0, 1, 0, 0] = np.inf
    result = normalize([p])
    assert len(result.points.xyz) == 5
    assert not result.points.valid_mask[0]
    assert result.depth_maps[0].depth_z[1, 0] == np.inf
    assert not result.depth_maps[0].valid_mask[1, 0]
    assert not result.depth_maps[0].valid_mask[0, 0]


def test_partial_confidence_is_aligned_with_nan_for_unavailable_view():
    first, second = prediction(), prediction()
    del first["conf"]
    second["conf"][0, 0, 0] = np.nan
    result = normalize([first, second])
    assert result.points.confidence.shape == (12,)
    assert np.isnan(result.points.confidence[:7]).all()
    np.testing.assert_allclose(result.points.confidence[7:], 0.8)
    assert result.depth_maps[0].confidence is None
    assert result.cameras[0].confidence is None
    assert result.confidence.valid_point_count == 5
    assert result.confidence.mean == pytest.approx(0.8)


def test_missing_optional_fields_and_stride():
    p = {"pts3d": prediction()["pts3d"], "img_no_norm": prediction()["img_no_norm"]}
    result = normalize([p], stride=2)
    assert len(result.points.xyz) == 2
    assert result.points.confidence is None
    assert not result.confidence.available
    assert result.points.valid_mask.all()
    assert result.scale.type == "relative"
    assert result.cameras[0].intrinsics is None
    assert result.cameras[0].camera_to_world is None
    assert result.depth_maps == []


def test_fallback_rgb_reads_source_bgr(tmp_path):
    path = tmp_path / "source.png"
    cv2.imwrite(str(path), np.tile([1, 2, 3], (2, 3, 1)).astype(np.uint8))
    p = prediction()
    del p["img_no_norm"]
    result = normalize(
        [p], frames=[SimpleNamespace(frame_id=2, timestamp_seconds=1.0, image_path=str(path))]
    )
    np.testing.assert_array_equal(result.points.rgb, np.tile([3, 2, 1], (6, 1)))


@pytest.mark.parametrize(
    "field,value",
    [
        ("pts3d", np.ones((2, 2, 3, 3))),
        ("pts3d", np.ones((2, 3))),
        ("pts3d", None),
        ("conf", np.ones((1, 4, 3))),
        ("depth_z", np.ones((1, 2, 4, 1))),
        ("non_ambiguous_mask", np.ones((2, 2, 3))),
        ("img_no_norm", np.ones((1, 2, 3, 4))),
        ("intrinsics", np.ones((2, 3, 3))),
        ("camera_poses", np.ones((1, 3, 4))),
        ("metric_scaling_factor", np.ones(2)),
    ],
)
def test_malformed_fields_report_view_field_and_expected_shape(field, value):
    p = prediction()
    p[field] = value
    with pytest.raises(ReconstructionFailedError, match=rf"view 7.*{field}.*expected"):
        normalize([p])


def test_wrong_view_count_is_actionable():
    with pytest.raises(ReconstructionFailedError, match="1 view outputs for 0 input"):
        normalize([prediction()], frames=[])


def test_no_finite_points_is_actionable():
    p = prediction()
    p["pts3d"][:] = np.nan
    with pytest.raises(ReconstructionFailedError, match="no finite 3D points"):
        normalize([p])


@pytest.mark.parametrize(
    "field",
    [
        "pts3d",
        "conf",
        "depth_z",
        "img_no_norm",
        "intrinsics",
        "camera_poses",
        "metric_scaling_factor",
    ],
)
def test_nonnumeric_fields_report_actionable_error(field):
    p = prediction()
    p[field] = np.full(p[field].shape, "broken")
    with pytest.raises(ReconstructionFailedError, match=rf"view 7.*{field}.*numeric"):
        normalize([p])


def test_tensor_like_fields_transfer_via_detach_cpu_numpy():
    calls = []

    class TensorLike:
        def __init__(self, array, name):
            self.array = array
            self.name = name

        def detach(self):
            calls.append((self.name, "detach"))
            return self

        def cpu(self):
            calls.append((self.name, "cpu"))
            return self

        def numpy(self):
            calls.append((self.name, "numpy"))
            return self.array

        def __array__(self, *args, **kwargs):
            raise AssertionError("tensor must detach and transfer to CPU before conversion")

    fields = prediction(h=1, w=1)
    wrapped = {name: TensorLike(array, name) for name, array in fields.items()}
    result = normalize([wrapped])
    np.testing.assert_allclose(result.points.xyz, [[1, 3, -2]])
    assert len(calls) == len(fields) * 3
    for name in fields:
        assert [operation for field, operation in calls if field == name] == [
            "detach",
            "cpu",
            "numpy",
        ]
