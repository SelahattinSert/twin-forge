import importlib.util
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).parents[1] / "unit"))
from dataclasses import replace

from test_calibration import control
from test_scene_reader import scene_files as imported_scene_files

from twinforge.core.types import PointCloud
from twinforge.export.ply import write_ply
from twinforge.measurements.calibration import fit_uniform_scale
from twinforge.measurements.observations import measure_segment
from twinforge.measurements.types import MeasurementRecord
from twinforge.scene.provenance import PixelTransform
from twinforge.scene.reader import SceneReader, sha256_file


@pytest.fixture
def scene_files(tmp_path):
    root = imported_scene_files.__wrapped__(tmp_path)
    pixels = np.array([41, 49, *[i for i in range(91) if i not in (41, 49)]], dtype=np.uint32)
    xyz = np.array([[0 if i % 13 < 6 else 2, 0, 1] for i in pixels], dtype=np.float32)
    write_ply(
        root / "pointcloud.ply",
        PointCloud(
            xyz=np.tile(xyz, (2, 1)),
            source_frame_id=np.repeat([3, 17], 91).astype(np.uint32),
            source_pixel_index=np.tile(pixels, 2),
            confidence=np.arange(182, dtype=np.float32),
            valid_mask=np.ones(182, dtype=bool),
        ),
    )
    import json

    manifest = json.loads((root / "scene.json").read_text())
    manifest["geometry"]["point_count"] = 182
    manifest["schema_version"] = "0.2"
    manifest["pixel_transforms"] = [
        PixelTransform(i, 13, 7, 13, 7, (0, 0, 13, 7), "native").to_dict() for i in (3, 17)
    ]
    (root / "scene.json").write_text(json.dumps(manifest))
    for i in (3, 17):
        (root / f"frame_{i}.jpg").write_bytes(f"frame {i}".encode())
    return root


def fit_scene(source):
    observations = tuple(
        measure_segment(
            source,
            pair,
            reference_id="door-width",
            selection_origin="3d_pick",
            correspondence_state="identified",
        )
        for pair in ((0, 1), (91, 92))
    )
    return fit_uniform_scale(
        MeasurementRecord("door-width", "width", observations),
        0.82,
        "m",
        original_scale=source.scale,
    )


def test_derive_rejects_invented_native_qualification_without_source_provenance(
    scene_files, tmp_path
):
    source = SceneReader(scene_files).read()
    fitted = fit_scene(source)
    source = replace(source, pixel_transforms=())
    destination = tmp_path / "not-created" / "derived"
    with pytest.raises(ValueError, match="provenance"):
        derive_module().derive_scene(source, fitted, destination)
    assert not destination.parent.exists()


def derive_module():
    assert importlib.util.find_spec("twinforge.scene.derive"), "derived export missing"
    from twinforge.scene import derive

    return derive


@pytest.mark.parametrize(
    "attack",
    [
        "validity",
        "masked",
        "frame",
        "pixel",
        "source_pixel",
        "sensitivity",
        "complete",
        "confidence",
        "timestamp",
    ],
)
def test_derive_rejects_forged_source_fields_before_destination(scene_files, tmp_path, attack):
    source = SceneReader(scene_files).read()
    fitted = fit_scene(source)
    first = fitted.observations[0]
    changes = {
        "validity": {"valid": False},
        "frame": {"frame_id": 17, "source_view_sha256": sha256_file(source.frames[1].image_path)},
        "pixel": {"model_pixels": ((3, 3), (10, 3))},
        "source_pixel": {"source_pixels": ((3, 3), (10, 3))},
        "sensitivity": {"sensitivity_span_ratio": 0.01},
        "complete": {"sensitivity_complete": False},
        "confidence": {"raw_confidence": (1000.0, 1000.0)},
        "timestamp": {"timestamp_seconds": 1000.0},
    }
    if attack == "masked":
        rows = source.point_records.copy()
        rows["valid"][0] = False
        source = replace(source, point_records=rows)
    else:
        fitted = replace(
            fitted, observations=(replace(first, **changes[attack]), *fitted.observations[1:])
        )
    destination = tmp_path / "not-created" / "derived"
    with pytest.raises(ValueError):
        derive_module().derive_scene(source, fitted, destination)
    assert not destination.parent.exists()


def test_derive_revalidates_retained_check_observations(scene_files, tmp_path):
    source = SceneReader(scene_files).read()
    fitted = fit_scene(source)
    observation = replace(fitted.observations[0], reference_id="check", sensitivity_span_ratio=0.01)
    record = MeasurementRecord("check", "width", (observation,))
    destination = tmp_path / "not-created" / "derived"
    with pytest.raises(ValueError, match="provenance"):
        derive_module().derive_scene(source, fitted, destination, records=(record,))
    assert not destination.parent.exists()


def test_uniform_xyz_and_camera_translation_preserve_projection():
    mod = derive_module()
    rng = np.random.default_rng(3)
    xyz = rng.normal(size=(20, 3))
    pose = np.eye(4)
    pose[:3, 3] = [1, 2, 3]
    scaled, camera = mod.scale_geometry(xyz, pose, 0.41)
    np.testing.assert_allclose(scaled, xyz * 0.41)
    np.testing.assert_array_equal(camera[:3, :3], pose[:3, :3])
    np.testing.assert_allclose(camera[:3, 3], pose[:3, 3] * 0.41)
    before = xyz - pose[:3, 3]
    after = scaled - camera[:3, 3]
    np.testing.assert_allclose(before[:, :2] / before[:, 2:], after[:, :2] / after[:, 2:])
    np.testing.assert_allclose(
        np.linalg.norm(np.diff(scaled, axis=0), axis=1),
        0.41 * np.linalg.norm(np.diff(xyz, axis=0), axis=1),
    )


def test_checks_exclude_control_and_do_not_invent_boundaries():
    mod = derive_module()
    fitted = fit_uniform_scale(control(), 0.82, "m")
    from dataclasses import replace

    height = replace(
        control(),
        reference_id="height",
        observations=tuple(replace(o, reference_id="height") for o in control().observations),
        physical_value=2,
        physical_unit="m",
    )
    report = mod.check_report((control(), height), fitted)
    assert report["excluded_control_id"] == "door-width"
    assert len(report["checks"]) == 1
    assert report["checks"][0]["scaled_median_m"] == pytest.approx(0.82)


def test_frozen_historical_check_keeps_method_and_uncertainty():
    from twinforge.measurements.types import MeasurementRecord

    fitted = fit_uniform_scale(control(), 0.82, "m")
    imported = MeasurementRecord(
        "ceiling",
        "plane separation",
        (),
        2.3,
        "m",
        reference_import={
            "frozen_check": {
                "reconstructed_distance_m": 2.98,
                "correspondence_status": "reliable_correspondence",
                "measurement_method": "plane_to_plane",
                "local_regions": {
                    "middle": {
                        "correspondence_status": "observed_patch_overlap",
                        "reconstructed_distance_m": 2.96,
                    }
                },
            },
            "point_cloud_sha256": fitted.point_cloud_sha256,
        },
    )
    check = derive_module().check_report((imported,), fitted)["checks"][0]
    assert check["scaled_median_m"] == pytest.approx(2.98 * 0.41)
    assert check["status"] == "frozen_historical_check"
    assert check["evidence"]["state"] == "insufficient_evidence"
    assert check["local_regions"]["middle"]["scaled_length_m"] == pytest.approx(2.96 * 0.41)


def test_separate_reopenable_export_preserves_columns_and_rejects_repeat(scene_files, tmp_path):
    mod = derive_module()
    source = SceneReader(scene_files).read()
    pixels = source.point_records["source_pixel_index"].copy()
    write_ply(
        source.point_cloud_path,
        PointCloud(
            xyz=np.column_stack([source.point_records[name] for name in ("x", "y", "z")]),
            source_frame_id=source.point_records["source_frame_id"].copy(),
            confidence=source.point_records["confidence"].copy(),
            valid_mask=source.point_records["valid"].astype(bool),
        ),
    )
    source = replace(SceneReader(scene_files).read(), derived_pixel_indices=pixels)
    fitted = fit_scene(source)
    before = {p: sha256_file(p) for p in source.referenced_paths}
    derived = mod.derive_scene(source, fitted, tmp_path / "derived")
    assert derived.schema_version == "0.2"
    assert derived.scale["meters_per_unit"] == 1
    assert derived.usage_status == "partially_checked"
    np.testing.assert_array_equal(derived.point_records["source_pixel_index"], pixels)
    for name in source.point_records.dtype.names:
        if name in ("x", "y", "z"):
            np.testing.assert_allclose(
                derived.point_records[name], source.point_records[name] * 0.41
            )
        else:
            np.testing.assert_array_equal(derived.point_records[name], source.point_records[name])
    assert {p: sha256_file(p) for p in source.referenced_paths} == before
    for destination in (tmp_path / "derived", scene_files / "bad", scene_files):
        with pytest.raises(ValueError):
            mod.derive_scene(source, fitted, destination)
    with pytest.raises(ValueError, match="already"):
        mod.derive_scene(derived, fitted, tmp_path / "double")
    alias = tmp_path / "alias"
    alias.symlink_to(scene_files, target_is_directory=True)
    with pytest.raises(ValueError):
        mod.derive_scene(source, fitted, alias / "bad")


def test_derive_rejects_forged_scalar_and_stale_control_endpoints(scene_files, tmp_path):
    source = SceneReader(scene_files).read()
    fitted = fit_scene(source)
    with pytest.raises(ValueError, match="scalar"):
        derive_module().derive_scene(source, replace(fitted, scalar=3), tmp_path / "bad")
    stale = replace(fitted.observations[0], xyz=((1.0, 0.0, 1.0), (3.0, 0.0, 1.0)))
    with pytest.raises(ValueError, match="endpoints"):
        derive_module().derive_scene(
            source,
            replace(fitted, observations=(stale, *fitted.observations[1:])),
            tmp_path / "stale",
        )


@pytest.mark.parametrize(
    "attack",
    [
        "median_scalar",
        "empty",
        "single",
        "unreviewed",
        "conflicting",
        "reference",
        "original_scale",
        "physical_zero",
        "physical_negative",
        "physical_nan",
        "physical_bool",
    ],
)
def test_derive_revalidates_frozen_control_before_creating_output(scene_files, tmp_path, attack):
    source = SceneReader(scene_files).read()
    fitted = fit_scene(source)
    changes = {
        "median_scalar": {"reconstructed_median": 1.0, "scalar": 0.82},
        "empty": {"observations": ()},
        "single": {"observations": fitted.observations[:1]},
        "unreviewed": {
            "observations": tuple(
                replace(o, correspondence_state="unreviewed") for o in fitted.observations
            )
        },
        "conflicting": {
            "observations": tuple(
                replace(o, sensitivity_span_ratio=0.5) for o in fitted.observations
            )
        },
        "reference": {"control_id": "other-control"},
        "original_scale": {"original_scale": {"type": "estimated_metric", "meters_per_unit": 2}},
        "physical_zero": {"physical_length_m": 0},
        "physical_negative": {"physical_length_m": -1},
        "physical_nan": {"physical_length_m": float("nan")},
        "physical_bool": {"physical_length_m": True, "scalar": 0.5},
    }[attack]
    destination = tmp_path / "not-created" / "derived"
    with pytest.raises(ValueError):
        derive_module().derive_scene(source, replace(fitted, **changes), destination)
    assert not destination.parent.exists()


def test_derive_preserves_explicit_qualification_policy(scene_files, tmp_path):
    from twinforge.measurements.consistency import ConsistencyPolicy

    source = SceneReader(scene_files).read()
    observations = fit_scene(source).observations
    policy = ConsistencyPolicy(maximum_sensitivity_span_ratio=0.2)
    fitted = fit_uniform_scale(
        MeasurementRecord("door-width", "width", observations),
        0.82,
        "m",
        original_scale=source.scale,
        policy=policy,
    )
    assert fitted.to_dict()["qualification_policy"]["maximum_sensitivity_span_ratio"] == 0.2
    derived = derive_module().derive_scene(source, fitted, tmp_path / "policy-derived")
    assert derived.scale["type"] == "calibrated_metric"


def test_known_camera_z_depth_scales_once_without_confidence_change(scene_files, tmp_path):
    import json

    path = scene_files / "scene.json"
    manifest = json.loads(path.read_text())
    manifest["geometry"]["depth_maps"] = "depthmaps.npz"
    manifest["scale"] = {"type": "estimated_metric", "meters_per_unit": 1}
    path.write_text(json.dumps(manifest))
    arrays = {
        "frame_ids": np.array([3, 17]),
        "depth_convention": np.asarray("OpenCV camera +Z forward"),
        "unit_note": np.asarray("meters when scene scale is metric"),
        "depth_z_0003": np.array([[1.0, 2.0]], dtype=np.float32),
        "depth_z_0017": np.array([[3.0, 4.0]], dtype=np.float32),
        "confidence_0003": np.array([[0.3, 0.5]], dtype=np.float32),
        "valid_0003": np.array([[True, False]]),
    }
    np.savez_compressed(scene_files / "depthmaps.npz", **arrays)
    source = SceneReader(scene_files).read()
    derived = derive_module().derive_scene(source, fit_scene(source), tmp_path / "depth-derived")
    assert "depth_maps" in json.loads(derived.manifest_path.read_text())["geometry"]
    with np.load(derived.source_root / "depthmaps.npz") as scaled:
        np.testing.assert_allclose(scaled["depth_z_0003"], arrays["depth_z_0003"] * 0.41)
        np.testing.assert_array_equal(scaled["confidence_0003"], arrays["confidence_0003"])
        np.testing.assert_array_equal(scaled["valid_0003"], arrays["valid_0003"])
