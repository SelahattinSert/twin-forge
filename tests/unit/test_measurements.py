"""Exact saved-scene endpoint observations and round-trip storage."""

import importlib
import json
from dataclasses import replace

import numpy as np
import pytest
from test_preview import artifact


def measurement_modules():
    assert importlib.util.find_spec("twinforge.measurements"), "measurement package missing"
    return [
        importlib.import_module(f"twinforge.measurements.{name}")
        for name in ("types", "observations", "consistency", "storage")
    ]


def test_segment_resolves_exact_original_rows_and_round_trips(tmp_path):
    types, obs, consistency, storage = measurement_modules()
    scene = artifact()
    observation = obs.measure_segment(
        scene, (2, 3), reference_id="door-width", selection_origin="3d_pick"
    )
    assert observation.point_indices == (2, 3)
    assert observation.frame_id == 17
    assert observation.length == pytest.approx(np.sqrt(3))
    assert observation.model_pixels is None and observation.valid
    record = types.MeasurementRecord("door-width", "width", (observation,))
    store = storage.MeasurementStore(tmp_path / "workspace", scene)
    store.save(record)
    for name in ("session.json", "measurements.json", "geometry-evidence.json"):
        assert (tmp_path / "workspace" / name).is_file(), name
    restored = store.load("door-width")
    assert restored == record
    assert restored.observations[0].point_indices == (2, 3)
    assert consistency.evaluate_observations(restored.observations).state == "insufficient_evidence"


def test_workspace_json_publication_preserves_open_reader_snapshots(tmp_path):
    types, obs, _, storage = measurement_modules()
    scene = artifact()
    store = storage.MeasurementStore(tmp_path / "workspace", scene)
    observation = obs.measure_segment(
        scene, (2, 3), reference_id="door", selection_origin="3d_pick"
    )
    store.save(types.MeasurementRecord("door", "width", (observation,)))
    names = ("door", "session", "measurements", "geometry-evidence")
    readers = {name: (store.root / f"{name}.json").open() for name in names}
    snapshots = {name: json.loads(reader.read()) for name, reader in readers.items()}
    inodes = {name: (store.root / f"{name}.json").stat().st_ino for name in names}
    try:
        store.save(types.MeasurementRecord("door", "width", (observation, observation)))
        for name, reader in readers.items():
            reader.seek(0)
            assert json.loads(reader.read()) == snapshots[name], name
            assert (store.root / f"{name}.json").stat().st_ino != inodes[name], name
        assert len(store.load("door").observations) == 2
    finally:
        for reader in readers.values():
            reader.close()


def test_invalid_masked_mixed_frame_and_out_of_bounds_points_rejected():
    _, obs, _, _ = measurement_modules()
    scene = artifact()
    rows = scene.point_records.copy()
    rows["valid"][2] = 0
    for indices in [(2, 3), (0, 3), (-1, 2), (2, 999), (2, 2)]:
        with pytest.raises(ValueError):
            obs.measure_segment(
                replace(scene, point_records=rows),
                indices,
                reference_id="door",
                selection_origin="3d_pick",
            )


def test_store_rejects_wrong_artifact_and_persists_hidden_regions(tmp_path):
    types, obs, _, storage = measurement_modules()
    scene = artifact()
    store = storage.MeasurementStore(tmp_path / "workspace", scene)
    record = types.MeasurementRecord(
        "door",
        "width",
        (obs.measure_segment(scene, (2, 3), reference_id="door", selection_origin="3d_pick"),),
    )
    store.save(record)
    with pytest.raises(ValueError, match="artifact"):
        storage.MeasurementStore(
            tmp_path / "workspace", replace(scene, point_cloud_sha256="c" * 64)
        ).load("door")
    for bad_id in ("../outside", "/absolute", ""):
        with pytest.raises(ValueError):
            store.load(bad_id)
    state = {"hidden_frame_ids": [17], "hidden_rois": [{"frame_id": 17, "bounds": [0, 0, 10, 20]}]}
    store.save_visibility(state)
    assert store.load_visibility() == {
        "schema_version": "0.1",
        **state,
        "interpretation": "manually hidden; geometry has not been corrected",
    }


def test_image_picks_require_mapping_and_measure_full_pixel_neighborhoods(tmp_path):
    _, obs, _, _ = measurement_modules()
    scene = artifact((49, 49, 49))
    mapping = importlib.import_module("twinforge.scene.provenance").PixelTransform(
        17, 7, 7, 7, 7, (0, 0, 7, 7), "derived"
    )
    pixels = np.tile(np.arange(49), 3)
    scene = replace(scene, pixel_transforms=(mapping.to_dict(),), derived_pixel_indices=pixels)
    index = obs.resolve_image_pixel(scene, 17, (2, 3))
    assert index == 49 + 23
    result = obs.measure_segment(
        scene, (index, index + 2), reference_id="door", selection_origin="image_pick"
    )
    assert result.model_pixels == ((2, 3), (4, 3)) and result.sensitivity_complete
    assert result.sensitivity_span_ratio > 0
    with pytest.raises(ValueError, match="unavailable"):
        obs.resolve_image_pixel(artifact(), 17, (2, 3))
    with pytest.raises(ValueError, match="outside"):
        obs.resolve_image_pixel(scene, 17, (100, 3))


def test_saved_observations_cannot_substitute_xyz_or_endpoint_identity(tmp_path):
    types, obs, _, storage = measurement_modules()
    scene = artifact()
    store = storage.MeasurementStore(tmp_path / "workspace", scene)
    record = types.MeasurementRecord(
        "door",
        "width",
        (obs.measure_segment(scene, (2, 3), reference_id="door", selection_origin="3d_pick"),),
    )
    store.save(record)
    path = tmp_path / "workspace/door.json"
    value = json.loads(path.read_text())
    value["observations"][0]["xyz"][0][0] += 10
    path.write_text(json.dumps(value))
    with pytest.raises(ValueError, match="original PLY"):
        store.load("door")


@pytest.mark.parametrize(
    "field,value",
    [
        ("model_pixels", [[1, 1], [2, 2]]),
        ("pixel_provenance", "native"),
        ("source_pixels", [[1, 1], [2, 2]]),
        ("reference_id", "another-reference"),
    ],
)
def test_saved_observation_rejects_substituted_provenance(tmp_path, field, value):
    types, obs, _, storage = measurement_modules()
    scene = artifact()
    store = storage.MeasurementStore(tmp_path / "workspace", scene)
    record = types.MeasurementRecord(
        "door",
        "width",
        (obs.measure_segment(scene, (2, 3), reference_id="door", selection_origin="3d_pick"),),
    )
    store.save(record)
    path = tmp_path / "workspace/door.json"
    data = json.loads(path.read_text())
    data["observations"][0][field] = value
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError):
        store.load("door")


def test_image_pick_source_pixels_must_resolve_to_chosen_rows():
    _, obs, _, _ = measurement_modules()
    scene = artifact((49, 49, 49))
    mapping = importlib.import_module("twinforge.scene.provenance").PixelTransform(
        17, 7, 7, 7, 7, (0, 0, 7, 7), "derived"
    )
    scene = replace(
        scene,
        pixel_transforms=(mapping.to_dict(),),
        derived_pixel_indices=np.tile(np.arange(49), 3),
    )
    with pytest.raises(ValueError, match="source pixel"):
        obs.measure_segment(
            scene,
            (72, 74),
            reference_id="door",
            selection_origin="image_pick",
            source_pixels=((0, 0), (1, 0)),
        )


@pytest.mark.parametrize(
    "roi",
    [
        {"frame_id": 999, "bounds": [0, 0, 2, 2]},
        {"frame_id": 17, "bounds": [2, 0, 1, 2]},
        {"frame_id": 17, "bounds": [0, 0, float("nan"), 2]},
        {"frame_id": 17.0, "bounds": [0, 0, 2, 2]},
        {"frame_id": 17, "bounds": [0, 0, 2, 2], "corrected": True},
    ],
)
def test_visibility_rejects_invalid_rois(tmp_path, roi):
    _, _, _, storage = measurement_modules()
    with pytest.raises(ValueError):
        storage.MeasurementStore(tmp_path / "workspace", artifact()).save_visibility(
            {"hidden_frame_ids": [], "hidden_rois": [roi]}
        )


def test_visibility_rejects_roi_outside_verified_model_grid(tmp_path):
    _, _, _, storage = measurement_modules()
    mapping = importlib.import_module("twinforge.scene.provenance").PixelTransform(
        17, 7, 7, 7, 7, (0, 0, 7, 7), "derived"
    )
    scene = replace(artifact(), pixel_transforms=(mapping.to_dict(),))
    with pytest.raises(ValueError, match="grid"):
        storage.MeasurementStore(tmp_path / "workspace", scene).save_visibility(
            {"hidden_frame_ids": [], "hidden_rois": [{"frame_id": 17, "bounds": [0, 0, 8, 2]}]}
        )


def test_submission_retry_correction_history_and_legacy_record_identity(tmp_path):
    types, obs, _, storage = measurement_modules()
    scene = artifact()
    store = storage.MeasurementStore(tmp_path / "workspace", scene)
    original = obs.measure_segment(scene, (2, 3), reference_id="old-id", selection_origin="3d_pick")
    store.save(types.MeasurementRecord("old-id", "width", (original,)))
    legacy_bytes = (store.root / "old-id.json").read_bytes()
    assert store.load("old-id").reference_id == "old-id"
    assert (store.root / "old-id.json").read_bytes() == legacy_bytes
    first = store.append(
        original, "width", display_name="Reference <one> 🧭", submission_key="request-1"
    )
    retried = store.append(
        replace(original, selected_at="later"), "width", submission_key="request-1"
    )
    assert first == retried and len(first.observations) == 2
    assert first.display_name == "Reference <one> 🧭"
    with pytest.raises(ValueError, match="idempotency"):
        store.append(
            replace(original, correspondence_state="identified"),
            "width",
            submission_key="request-1",
        )
    fixed = store.append(
        replace(original, correspondence_state="identified"),
        "width",
        submission_key="fix-1",
        correction_id="legacy-1",
        expected_revision=1,
        correction_reason="Reviewed endpoint order",
    )
    assert len(fixed.observations) == 2 and len(fixed.observation_history) == 1
    assert fixed.observations[0].revision == 2
    assert fixed.observation_history[0].point_indices == original.point_indices
    assert fixed.observation_history[0].correspondence_state == "unreviewed"
    assert fixed.observations[0].correction_reason == "Reviewed endpoint order"
    assert store.load("old-id") == fixed
    assert (
        store.append(
            replace(original, correspondence_state="identified"),
            "width",
            submission_key="fix-1",
            correction_id="legacy-1",
            expected_revision=1,
            correction_reason="Reviewed endpoint order",
        )
        == fixed
    )
    with pytest.raises(ValueError, match="revision"):
        store.append(
            original,
            "width",
            submission_key="fix-2",
            correction_id="legacy-1",
            expected_revision=1,
            correction_reason="Stale editor",
        )
    assert store.summary()["observation_count"] == 2
    assert store.rename("old-id", "Renamed").reference_id == "old-id"
