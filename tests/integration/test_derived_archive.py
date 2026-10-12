import json

import numpy as np
import pytest
from test_calibrated_scene import fit_scene
from test_calibrated_scene import scene_files as calibrated_scene_files

from twinforge.measurements.observations import measure_segment
from twinforge.measurements.storage import MeasurementStore
from twinforge.measurements.types import MeasurementRecord
from twinforge.scene.derive import derive_scene
from twinforge.scene.reader import SceneReader, sha256_file


@pytest.fixture
def scene_files(tmp_path):
    return calibrated_scene_files.__wrapped__(tmp_path)


def exported(scene_files, tmp_path):
    source = SceneReader(scene_files).read()
    calibration = fit_scene(source)
    record = MeasurementRecord("door-width", "width", calibration.observations, role="calibration")
    return derive_scene(source, calibration, tmp_path / "derived", records=(record,))


def test_standalone_archive_preserves_source_identity_and_scales_display_once(
    scene_files, tmp_path
):
    from twinforge.viewer.archive import read_archive

    derived = exported(scene_files, tmp_path)
    before = {p: sha256_file(p) for p in derived.source_root.glob("*.json")}
    archive = read_archive(derived)
    assert archive["status"] == "available"
    assert archive["read_only"] is True
    assert archive["check_report"]["excluded_control_id"] == "door-width"
    record = archive["measurements"][0]["record"]
    assert record["role"] == "calibration"
    observation = record["observations"][0]
    assert observation["scene_manifest_sha256"] != derived.manifest_sha256
    assert observation["point_cloud_sha256"] != derived.point_cloud_sha256
    np.testing.assert_array_equal(observation["xyz"], [[0.0, 0.0, 1.0], [2.0, 0.0, 1.0]])
    np.testing.assert_allclose(
        np.array(observation["xyz"]) * archive["display_scalar"],
        [[0.0, 0.0, 0.41], [0.82, 0.0, 0.41]],
    )
    store = MeasurementStore(tmp_path / "fresh", derived)
    assert store.list_ids() == []
    store.append(
        measure_segment(derived, [0, 1], reference_id="door-width", selection_origin="3d_pick"),
        "width",
    )
    assert len(store.load("door-width").observations) == 1
    assert {p: sha256_file(p) for p in before} == before


@pytest.mark.parametrize(
    "attack", ["escape", "scalar", "hash", "xyz", "image", "control", "schema"]
)
def test_archive_rejects_unsafe_or_stale_records(scene_files, tmp_path, attack):
    from twinforge.viewer.archive import read_archive

    derived = exported(scene_files, tmp_path)
    name = "scene" if attack in ("escape", "scalar") else "calibration"
    path = derived.source_root / f"{name}.json"
    value = json.loads(path.read_text())
    if attack == "escape":
        value["derivation"]["calibration"] = "../calibration.json"
    if attack == "scalar":
        value["derivation"]["transform"]["scalar"] = 2
    if attack == "hash":
        value["manifest_sha256"] = "0" * 64
    if attack == "xyz":
        value["observations"][0]["xyz"][0][0] = 10
    if attack == "image":
        value["observations"][0]["source_view_sha256"] = "0" * 64
    if attack == "control":
        value["control_id"] = "different"
    if attack == "schema":
        value["schema_version"] = "unknown"
    path.write_text(json.dumps(value))
    archive = read_archive(SceneReader(derived.source_root).read())
    assert archive["status"] == "unavailable"
    assert archive["reason"]
    assert "measurements" not in archive


def test_archive_public_http_route_is_read_only(scene_files, tmp_path):
    from types import SimpleNamespace

    from twinforge.viewer.archive import read_archive
    from twinforge.viewer.server import _Handler

    derived = exported(scene_files, tmp_path)
    handler = object.__new__(_Handler)
    handler.server = SimpleNamespace(archive=read_archive(derived))
    handler.path = "/api/archive"
    handler._allowed_request = lambda: True
    replies = []
    handler._json = lambda status, value: replies.append((status, value))
    handler.do_GET()
    assert replies[0][0] == 200
    assert replies[0][1]["calibration"]["control_id"] == "door-width"
    handler._send = lambda status, *args: replies.append((status, args))
    handler.do_POST()
    assert replies[-1][0] == 405
