"""Pixel identity follows the same selection as native learned geometry."""

import importlib
from dataclasses import replace

import numpy as np
import pytest
from test_mapanything_outputs import normalize, prediction
from test_preview import artifact

from twinforge.export.ply import write_ply
from twinforge.scene.reader import read_point_records


def provenance():
    assert importlib.util.find_spec("twinforge.scene.provenance"), "provenance module missing"
    return importlib.import_module("twinforge.scene.provenance")


def test_normalizer_preserves_grid_indices_before_finite_and_stride_selection(tmp_path):
    p = prediction(h=3, w=4)
    p["pts3d"][0, 0, 2] = np.nan
    p["non_ambiguous_mask"][0, 2, 2] = False
    result = normalize([p], stride=2)
    assert hasattr(result.points, "source_pixel_index"), "native pixel column missing"
    np.testing.assert_array_equal(result.points.source_pixel_index, [0, 8, 10])
    assert not result.points.valid_mask[-1]
    write_ply(tmp_path / "points.ply", result.points)
    np.testing.assert_array_equal(
        read_point_records(tmp_path / "points.ply")["source_pixel_index"], [0, 8, 10]
    )


def test_raster_center_mapping_uses_actual_integer_resize_and_crop():
    module = provenance()
    mapping = module.PixelTransform(7, 464, 832, 294, 527, (0, 4, 294, 522), "native", 0.634)
    xy = mapping.source_to_model((158.0, 499.0))
    np.testing.assert_allclose(xy, [(158.5) * 294 / 464 - 0.5, (499.5) * 527 / 832 - 0.5 - 4])
    np.testing.assert_allclose(mapping.model_to_source(xy), (158, 499))
    assert (
        mapping.to_dict()["pixel_center_convention"]
        == "integer coordinates denote raster pixel centers"
    )


def test_historical_derivation_requires_complete_finite_contiguous_grids():
    module = provenance()
    scene = artifact((6, 6, 6))
    from twinforge.core.types import Camera

    scene = replace(
        scene,
        cameras=tuple(
            Camera(i, float(i), None, None, image_width=3, image_height=2) for i in (3, 17, 21)
        ),
    )
    indices = module.derive_full_grid_indices(
        scene, 3, 2, point_stride=1, ordering="frame_then_row_major"
    )
    np.testing.assert_array_equal(indices, np.tile(np.arange(6), 3))
    rows = scene.point_records.copy()
    rows["x"][0] = np.nan
    for bad_scene, stride, order in [
        (replace(scene, point_records=rows), 1, "frame_then_row_major"),
        (artifact(), 1, "frame_then_row_major"),
        (scene, 2, "frame_then_row_major"),
        (scene, 1, "unknown"),
    ]:
        with pytest.raises(ValueError):
            module.derive_full_grid_indices(bad_scene, 3, 2, point_stride=stride, ordering=order)


def test_official_preprocessing_capture_records_actual_resize_and_crop(tmp_path):
    from PIL import Image

    from twinforge.backends import mapanything

    function = getattr(mapanything, "load_images_with_provenance", None)
    assert callable(function), "official preprocessing capture missing"
    path = tmp_path / "source.png"
    Image.new("RGB", (464, 832), (70, 80, 90)).save(path)
    views, mappings = function([str(path)], [17])
    mapping = provenance().PixelTransform(
        **{**mappings[0], "crop_bbox": tuple(mappings[0]["crop_bbox"])}
    )
    assert views[0]["img"].shape[-2:] == (518, 294)
    assert (mapping.resized_width, mapping.resized_height) == (294, 527)
    assert mapping.crop_bbox == (0, 4, 294, 522)
    assert mapping.official_intrinsics_scale == pytest.approx(294 / 464 + 1e-8)
    assert mapping.origin == "native"


def test_workspace_derived_provenance_is_bound_to_exact_scene_and_verified_grid(tmp_path):
    module = provenance()
    function = getattr(module, "attach_verified_provenance", None)
    assert callable(function), "workspace provenance import missing"
    scene = artifact((6, 6, 6))
    proof = tmp_path / "grid-proof.json"
    proof.write_text("{}")
    from twinforge.scene.reader import sha256_file

    value = {
        "schema_version": "0.1",
        "manifest_sha256": scene.manifest_sha256,
        "point_cloud_sha256": scene.point_cloud_sha256,
        "grid_width": 3,
        "grid_height": 2,
        "point_stride": 1,
        "ordering": "frame_then_row_major",
        "ordering_verification": "raw_grid_comparison",
        "evidence_files": [
            {
                "source_path": str(proof),
                "source_sha256": sha256_file(proof),
                "reason": "raw grid compared",
            }
        ],
        "pixel_transforms": [
            module.PixelTransform(i, 3, 2, 3, 2, (0, 0, 3, 2), "derived").to_dict()
            for i in (3, 17, 21)
        ],
    }
    linked = function(scene, value)
    assert linked.derived_pixel_indices is not None
    assert linked.pixel_transforms[0]["origin"] == "derived"
    with pytest.raises(ValueError, match="hash"):
        function(scene, {**value, "manifest_sha256": "c" * 64})
    with pytest.raises(ValueError, match="order"):
        function(scene, {**value, "ordering_verification": "count_only"})
    proof.write_text('{"changed": true}')
    with pytest.raises(ValueError, match="evidence.*hash"):
        function(scene, value)


@pytest.mark.parametrize("crop", [(0.5, 0, 3, 2), (False, 0, 3, 2)])
def test_transform_rejects_noninteger_crop_bounds(crop):
    with pytest.raises(ValueError, match="integer"):
        provenance().PixelTransform(17, 3, 2, 3, 2, crop, "native")
