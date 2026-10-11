"""Exercise local HTTP transport, source links, package assets and write guards."""

import hashlib
import http.client
import json
import subprocess
import threading
from concurrent.futures import ThreadPoolExecutor

import cv2
import numpy as np
import pytest
from test_calibrated_scene import scene_files as imported_calibrated_scene_files

from twinforge.core.types import PointCloud
from twinforge.export.ply import write_ply
from twinforge.scene.reader import SceneReader
from twinforge.viewer.server import STATIC_FILES, STATIC_ROOT, ViewerServer, ViewerWorkspace


@pytest.fixture
def saved_scene(tmp_path):
    root = tmp_path / "source"
    root.mkdir()
    write_ply(
        root / "points.ply",
        PointCloud(
            np.array([[1, 2, 3], [4, 5, 6]], dtype=np.float32),
            source_frame_id=np.array([17, 3], dtype=np.uint32),
        ),
    )
    for frame_id in (3, 17):
        (root / f"{frame_id}.jpg").write_bytes(bytes([frame_id, 255, 216]))
    (root / "scene.json").write_text(
        json.dumps(
            {
                "schema_version": "0.1",
                "geometry": {"point_cloud": "points.ply"},
                "scale": {"type": "relative"},
                "cameras": "cameras.json",
                "keyframes": "keyframes.json",
            }
        )
    )
    (root / "cameras.json").write_text(
        json.dumps(
            {
                "cameras": [
                    {
                        "frame_id": frame_id,
                        "timestamp_seconds": 1.0,
                        "intrinsics": None,
                        "camera_to_world": np.eye(4).tolist(),
                    }
                    for frame_id in (3, 17)
                ]
            }
        )
    )
    (root / "keyframes.json").write_text(
        json.dumps(
            {
                "frames": [
                    {
                        "frame_id": frame_id,
                        "timestamp_seconds": 1.0,
                        "image_path": f"{frame_id}.jpg",
                    }
                    for frame_id in (3, 17)
                ]
            }
        )
    )
    return SceneReader(root).read()


@pytest.fixture
def server(saved_scene, tmp_path):
    instance = ViewerServer(saved_scene, tmp_path / "workspace")
    thread = threading.Thread(target=instance.serve_forever, daemon=True)
    thread.start()
    try:
        yield instance
    finally:
        instance.shutdown()
        instance.server_close()
        thread.join(timeout=2)


@pytest.fixture
def calibrated_scene_files(tmp_path):
    return imported_calibrated_scene_files.__wrapped__(tmp_path)


@pytest.fixture
def calibrated_server(calibrated_scene_files, tmp_path):
    instance = ViewerServer(SceneReader(calibrated_scene_files).read(), tmp_path / "workspace")
    thread = threading.Thread(target=instance.serve_forever, daemon=True)
    thread.start()
    try:
        yield instance
    finally:
        instance.shutdown()
        instance.server_close()
        thread.join(timeout=2)


@pytest.fixture
def measurement_server(saved_scene, tmp_path):
    write_ply(
        saved_scene.point_cloud_path,
        PointCloud(
            np.array([[0, 0, 0], [1, 0, 0], [0, 0, 0], [1, 0, 0]], dtype=np.float32),
            source_frame_id=np.array([17, 17, 3, 3], dtype=np.uint32),
        ),
    )
    instance = ViewerServer(SceneReader(saved_scene.source_root).read(), tmp_path / "workspace")
    thread = threading.Thread(target=instance.serve_forever, daemon=True)
    thread.start()
    try:
        yield instance
    finally:
        instance.shutdown()
        instance.server_close()
        thread.join(timeout=2)


def post_measurement(server, indices, reference_id="door"):
    connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=5)
    try:
        connection.request(
            "POST",
            "/api/measurements",
            json.dumps(
                {
                    "reference_id": reference_id,
                    "quantity": "width",
                    "point_indices": indices,
                    "correspondence_state": "identified",
                }
            ),
            {"Content-Type": "application/json", "Origin": server.url.rstrip("/")},
        )
        response = connection.getresponse()
        return response.status, json.loads(response.read())
    finally:
        connection.close()


def test_overlapping_successful_appends_preserve_both_observations(measurement_server, monkeypatch):
    import twinforge.viewer.server as server_module

    server = measurement_server
    first_at_save, release_first, second_measured, second_saved = (
        threading.Event() for _ in range(4)
    )
    original_save = server.measurements.save
    original_measure = server_module.measure_segment

    def pause_first_save(record):
        if record.observations[-1].point_indices == (0, 1):
            first_at_save.set()
            assert release_first.wait(3), "First append was not released"
        original_save(record)
        if record.observations[-1].point_indices == (2, 3):
            second_saved.set()

    def track_second_measure(*args, **kwargs):
        observation = original_measure(*args, **kwargs)
        if observation.point_indices == (2, 3):
            second_measured.set()
        return observation

    monkeypatch.setattr(server.measurements, "save", pause_first_save)
    monkeypatch.setattr(server_module, "measure_segment", track_second_measure)
    with ThreadPoolExecutor(max_workers=3) as pool:
        first = pool.submit(post_measurement, server, [0, 1])
        try:
            assert first_at_save.wait(3)
            second = pool.submit(post_measurement, server, [2, 3])
            assert second_measured.wait(3), "Requests did not overlap"
            reader = pool.submit(request, server, "/api/scene")
            # Without transaction serialization the second append publishes first;
            # the paused first append then overwrites it. With the lock it waits.
            second_saved.wait(0.3)
        finally:
            release_first.set()
        first_result, second_result = first.result(), second.result()
        status, metadata_bytes, _ = reader.result()
    assert first_result[0] == second_result[0] == status == 200
    restored = server.measurements.load("door")
    assert {item.point_indices for item in restored.observations} == {(0, 1), (2, 3)}
    assert json.loads(request(server, "/api/measurements")[1]) == ["door"]
    response = json.loads(request(server, "/api/measurements/door")[1])
    assert response["record"] == json.loads(json.dumps(restored.to_dict()))
    assert response["evidence"]["observation_count"] == 2
    assert response["evidence"]["state"] == "consistent_observations"
    evidence = json.loads((server.measurements.root / "geometry-evidence.json").read_text())
    assert evidence["references"]["door"] == response["evidence"]
    metadata = json.loads(metadata_bytes)
    assert metadata["observation_count"] in (1, 2)
    metadata = json.loads(request(server, "/api/scene")[1])
    assert metadata["observation_count"] == 2
    assert metadata["reference_count"] == 1
    assert metadata["geometry_evidence"] == "per_reference"
    assert metadata["usage_status"] == "partially_checked"
    for path in server.measurements.root.glob("*.json"):
        json.loads(path.read_text())


def test_scene_status_counts_saved_observations_and_references(measurement_server):
    server = measurement_server
    assert post_measurement(server, [0, 1])[0] == 200
    assert post_measurement(server, [2, 3])[0] == 200
    assert post_measurement(server, [0, 1], "another-door")[0] == 200
    metadata = json.loads(request(server, "/api/scene")[1])
    assert metadata["observation_count"] == 3
    assert metadata["reference_count"] == 2
    assert metadata["geometry_evidence"] == "per_reference"
    assert metadata["usage_status"] == "partially_checked"


def test_derived_scene_endpoint_binds_metadata_to_reopened_artifacts(calibrated_server):
    from twinforge.measurements.calibration import fit_uniform_scale
    from twinforge.scene.derive import derive_scene
    from twinforge.scene.reader import sha256_file
    from twinforge.viewer.preview import build_preview, encode_bundle

    server = calibrated_server
    assert post_measurement(server, [0, 1])[0] == 200
    assert post_measurement(server, [91, 92])[0] == 200
    record = server.measurements.load("door")
    fitted = fit_uniform_scale(
        record,
        0.82,
        "m",
        original_scale=server.scene.scale,
    )
    server.derived = derive_scene(server.scene, fitted, server.workspace.root / "derived")
    server.derived_preview_bytes = encode_bundle(build_preview(server.derived))
    derived = SceneReader(server.derived.manifest_path).read()
    metadata = json.loads(request(server, "/api/derived/scene")[1])
    assert (
        metadata["manifest_sha256"] == derived.manifest_sha256 == sha256_file(derived.manifest_path)
    )
    assert (
        metadata["point_cloud_sha256"]
        == derived.point_cloud_sha256
        == sha256_file(derived.point_cloud_path)
    )
    assert metadata["source_schema_version"] == derived.schema_version
    assert metadata["confidence"] == derived.confidence
    assert metadata["name"] == derived.source_root.name
    assert metadata["source_scene"] == {
        "manifest_sha256": server.scene.manifest_sha256,
        "point_cloud_sha256": server.scene.point_cloud_sha256,
    }
    assert all(frame["points_url"].startswith("/api/derived/") for frame in metadata["frames"])
    assert request(server, "/api/derived/preview")[1] == server.derived_preview_bytes


def test_derived_scene_route_uses_derived_artifact_metadata_without_transport(
    calibrated_scene_files, tmp_path, monkeypatch
):
    from http.server import ThreadingHTTPServer

    from twinforge.measurements.calibration import fit_uniform_scale
    from twinforge.measurements.observations import measure_segment
    from twinforge.measurements.types import MeasurementRecord
    from twinforge.scene.derive import derive_scene
    from twinforge.viewer.preview import build_preview, encode_bundle
    from twinforge.viewer.server import _Handler

    # Isolate the route logic while socket transport is verified by the endpoint test.
    monkeypatch.setattr(ThreadingHTTPServer, "__init__", lambda *args, **kwargs: None)
    server = ViewerServer(SceneReader(calibrated_scene_files).read(), tmp_path / "workspace")
    observations = tuple(
        measure_segment(
            server.scene,
            pair,
            reference_id="door",
            selection_origin="3d_pick",
            correspondence_state="identified",
        )
        for pair in ((0, 1), (91, 92))
    )
    fitted = fit_uniform_scale(
        MeasurementRecord("door", "width", observations),
        0.82,
        "m",
        original_scale=server.scene.scale,
    )
    server.derived = derive_scene(server.scene, fitted, server.workspace.root / "derived")
    server.derived_preview_bytes = encode_bundle(build_preview(server.derived))
    handler = _Handler.__new__(_Handler)
    handler.server = server
    handler.path = "/api/derived/scene"
    handler._allowed_request = lambda: True
    responses = []
    handler._json = lambda status, value: responses.append((status, value))
    handler.do_GET()
    status, metadata = responses[0]
    assert status == 200
    assert metadata["point_cloud_sha256"] == server.derived.point_cloud_sha256
    assert metadata["manifest_sha256"] == server.derived.manifest_sha256
    assert metadata["source_schema_version"] == server.derived.schema_version
    assert metadata["confidence"] == server.derived.confidence
    assert metadata["name"] == server.derived.source_root.name
    assert metadata["source_scene"] == {
        "manifest_sha256": server.scene.manifest_sha256,
        "point_cloud_sha256": server.scene.point_cloud_sha256,
    }


def test_workspace_readers_wait_for_complete_record_and_evidence_publication(
    measurement_server, monkeypatch
):
    server = measurement_server
    record_published, release_save, reader_started = (threading.Event() for _ in range(3))
    original_write = server.measurements._write
    original_list = server.measurements.list_ids

    def pause_publication(name, value):
        original_write(name, value)
        if name == "door":
            record_published.set()
            assert release_save.wait(3), "Publication was not released"

    def track_reader():
        reader_started.set()
        return original_list()

    monkeypatch.setattr(server.measurements, "_write", pause_publication)
    monkeypatch.setattr(server.measurements, "list_ids", track_reader)
    with ThreadPoolExecutor(max_workers=4) as pool:
        append = pool.submit(post_measurement, server, [0, 1])
        try:
            assert record_published.wait(3)
            reads = [
                pool.submit(request, server, path)
                for path in ("/api/scene", "/api/measurements", "/api/measurements/door")
            ]
            assert reader_started.wait(3)
            threading.Event().wait(0.1)
            returned_before_commit = any(read.done() for read in reads)
        finally:
            release_save.set()
        assert append.result()[0] == 200
        responses = [read.result() for read in reads]
    assert not returned_before_commit, "Reader observed a partially published transaction"
    assert all(response[0] == 200 for response in responses)
    assert json.loads(responses[0][1])["observation_count"] == 1
    assert json.loads(responses[1][1]) == ["door"]
    assert json.loads(responses[2][1])["evidence"]["observation_count"] == 1


def request(server, path, method="GET", headers=None):
    connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=5)
    connection.request(method, path, headers=headers or {})
    response = connection.getresponse()
    result = response.status, response.read(), dict(response.getheaders())
    connection.close()
    return result


def test_http_scene_preview_and_exact_source_frame_link(server):
    assert server.server_address[0] == "127.0.0.1"
    status, data, headers = request(server, "/api/scene")
    assert status == 200 and headers["Content-Type"] == "application/json"
    metadata = json.loads(data)
    assert metadata["original_point_count"] == metadata["displayed_point_count"] == 2
    assert metadata["usage_status"] == "visualization_only"
    assert metadata["observation_count"] == 0
    status, image, _ = request(server, "/api/frames/17/image")
    assert status == 200 and image == bytes([17, 255, 216])
    status, data, _ = request(server, "/api/frames/17/points")
    assert status == 200 and data[:4] == b"TFP1"
    header_size = int.from_bytes(data[4:8], "little")
    header = json.loads(data[8 : 8 + header_size])
    assert header["count"] == 1 and header["frame_id"] == 17
    indices = header["columns"]["point_indices"]
    assert np.frombuffer(data, "<u8", count=1, offset=indices["offset"])[0] == 0
    assert request(server, "/api/preview")[1] == server.preview_bytes


def test_thumbnail_route_preserves_full_image_and_handles_invalid_sources(server):
    path = server.frames[17].image_path
    assert cv2.imwrite(str(path), np.full((600, 1000, 3), 120, dtype=np.uint8))
    original = path.read_bytes()
    metadata = json.loads(request(server, "/api/scene")[1])
    frame = next(frame for frame in metadata["frames"] if frame["frame_id"] == 17)
    status, data, headers = request(server, frame["thumbnail_url"])
    assert status == 200 and headers["Content-Type"] == "image/jpeg"
    image = cv2.imdecode(np.frombuffer(data, dtype=np.uint8), cv2.IMREAD_COLOR)
    assert image.shape[:2] == (192, 320)
    assert request(server, frame["image_url"])[1] == original == path.read_bytes()
    assert request(server, "/api/frames/3/thumbnail")[0] == 422
    assert request(server, "/api/frames/999/thumbnail")[0] == 404


@pytest.mark.parametrize(
    "path",
    [
        "/../scene.json",
        "/%2e%2e/scene.json",
        "/api/file?path=/etc/passwd",
        "/api/frames/999/image",
        "/vendor/../../scene.json",
        "/vendor/not-a-font.woff2",
        "/workspace-ui-private.js",
    ],
)
def test_http_path_allowlist_rejects_unlisted_resources(server, path):
    assert request(server, path)[0] == 404


def test_http_rejects_foreign_host_origin_and_writes(server):
    assert request(server, "/api/scene", headers={"Host": "attacker.example"})[0] == 403
    assert request(server, "/api/scene", headers={"Origin": "https://attacker.example"})[0] == 403
    for method in ("POST", "PUT", "DELETE", "PATCH"):
        assert request(server, "/api/scene", method)[0] == 405


def test_source_hashes_stay_identical_after_requests(server):
    before = {
        path: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in server.scene.referenced_paths
    }
    request(server, "/")
    request(server, "/api/preview")
    request(server, "/api/frames/3/points")
    after = {
        path: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in server.scene.referenced_paths
    }
    assert before == after


def test_workspace_rejects_source_overwrite_traversal_and_symlinks(saved_scene, tmp_path):
    for path in (saved_scene.source_root, saved_scene.source_root / "annotations", tmp_path):
        with pytest.raises(ValueError, match="separate"):
            ViewerWorkspace(path, saved_scene)
    workspace = ViewerWorkspace(tmp_path / "safe", saved_scene)
    assert (
        workspace.write_path("annotations/selection.json")
        == workspace.root / "annotations/selection.json"
    )
    for path in ("../escape.json", str(saved_scene.point_cloud_path), ".", ""):
        with pytest.raises(ValueError):
            workspace.write_path(path)
    (workspace.root / "link").symlink_to(saved_scene.source_root, target_is_directory=True)
    with pytest.raises(ValueError, match="escapes"):
        workspace.write_path("link/scene.json")


def test_all_allowlisted_static_assets_present_and_offline():
    for relative in STATIC_FILES.values():
        assert (STATIC_ROOT / relative).is_file(), relative
    assert "MIT" in (STATIC_ROOT / "vendor/LICENSE").read_text()
    for name in ("index.html", "app.js"):
        text = (STATIC_ROOT / name).read_text()
        assert "https://" not in text and "http://" not in text
    assert "three.core.min.js" in (STATIC_ROOT / "vendor/three.module.min.js").read_text()


def test_workspace_assets_are_explicitly_allowlisted_and_pinned():
    for path in (
        "workspace-ui.js",
        "image-selection.js",
        "image-editor.js",
        "result-summary.js",
        "view-state.js",
        "scene-exploration.js",
        "scene-snapshot.js",
        "exploration-ui.js",
        "source-preview.js",
        "hover-index.js",
        "camera-markers.js",
        "camera-icon.svg",
        "vendor/manrope-latin-wght-normal.woff2",
        "vendor/MANROPE-LICENSE",
    ):
        assert STATIC_FILES.get(f"/{path}") == path
    font = STATIC_ROOT / "vendor/manrope-latin-wght-normal.woff2"
    assert hashlib.sha256(font.read_bytes()).hexdigest() == (
        "a30ddcd349703aff7464c34bef3fffdff405ee50c113440d7c8693c02d210972"
    )
    assert (
        "SIL OPEN FONT LICENSE Version 1.1" in (STATIC_ROOT / "vendor/MANROPE-LICENSE").read_text()
    )


def test_http_workspace_module_font_and_license(server):
    for path, expected_type in (
        ("workspace-ui.js", "javascript"),
        ("hover-index.js", "javascript"),
        ("camera-markers.js", "javascript"),
        ("camera-icon.svg", "image/svg+xml"),
        ("image-selection.js", "javascript"),
        ("image-editor.js", "javascript"),
        ("result-summary.js", "javascript"),
        ("view-state.js", "javascript"),
        ("scene-exploration.js", "javascript"),
        ("scene-snapshot.js", "javascript"),
        ("exploration-ui.js", "javascript"),
        ("source-preview.js", "javascript"),
        ("vendor/manrope-latin-wght-normal.woff2", "font/woff2"),
        ("vendor/MANROPE-LICENSE", "text/plain"),
    ):
        status, data, headers = request(server, f"/{path}")
        assert status == 200
        assert data == (STATIC_ROOT / path).read_bytes()
        assert expected_type in headers["Content-Type"]


def test_view_cli_imports_no_inference_or_torch_modules():
    import sys

    code = "import sys; from twinforge.cli import build_parser; args=build_parser().parse_args(['view','scene','--no-browser']); assert args.command=='view'; assert 'torch' not in sys.modules; assert 'twinforge.backends.mapanything' not in sys.modules; assert 'mapanything' not in sys.modules"
    subprocess.run([sys.executable, "-c", code], check=True, capture_output=True)


def test_measurement_http_round_trip_and_visibility_writes(server):
    connection = http.client.HTTPConnection("127.0.0.1", server.server_port)
    value = {
        "reference_id": "door",
        "quantity": "width",
        "point_indices": [0, 1],
        "correspondence_state": "identified",
    }
    headers = {"Content-Type": "application/json", "Origin": server.url.rstrip("/")}
    connection.request("POST", "/api/measurements", json.dumps(value), headers)
    response = connection.getresponse()
    assert response.status == 422  # Different frames cannot form one observation.
    response.read()
    connection.request(
        "POST",
        "/api/visibility",
        json.dumps({"hidden_frame_ids": [17], "hidden_rois": []}),
        headers,
    )
    response = connection.getresponse()
    assert response.status == 200
    response.read()
    connection.close()
    assert json.loads(request(server, "/api/visibility")[1])["hidden_frame_ids"] == [17]
    assert json.loads(request(server, "/api/measurements")[1]) == []


def test_http_image_retry_correction_history_and_frozen_export(calibrated_server):
    from twinforge.scene.reader import sha256_file
    from twinforge.viewer.archive import read_archive

    server = calibrated_server
    source_hash = sha256_file(server.scene.point_cloud_path)
    headers = {"Content-Type": "application/json", "Origin": server.url.rstrip("/")}

    def post(value, path="/api/measurements"):
        connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=5)
        try:
            connection.request("POST", path, json.dumps(value), headers)
            response = connection.getresponse()
            body = response.read()
            return response.status, json.loads(body) if response.status == 200 else body.decode()
        finally:
            connection.close()

    first = {
        "reference_id": "measurement-example",
        "quantity": "segment",
        "display_name": "Reference <name> 🧭",
        "frame_id": 3,
        "source_pixels": [[2, 3], [10, 3]],
        "correspondence_state": "identified",
        "idempotency_key": "submission-one",
    }
    status, saved = post(first)
    assert status == 200
    assert len(saved["record"]["observations"]) == 1
    assert post(first) == (status, saved)
    assert post({**first, "source_pixels": [[2, 3], [9, 3]]})[0] == 422
    _, compared = post({**first, "frame_id": 17, "idempotency_key": "submission-two"})
    assert compared["evidence"]["calibration_qualified"] is True
    assert compared["evidence"]["distinct_view_count"] == 2
    assert (
        post(
            {"reference_id": first["reference_id"], "physical_value": 0.82, "physical_unit": "m"},
            "/api/calibration",
        )[0]
        == 200
    )
    frozen = {
        path: sha256_file(path) for path in server.derived.source_root.rglob("*") if path.is_file()
    }
    active = compared["record"]["observations"][0]
    correction = {
        **first,
        "source_pixels": [[10, 3], [2, 3]],
        "correction_id": active["observation_id"],
        "expected_revision": 1,
        "correction_reason": "The start and end points were reversed.",
        "idempotency_key": "correction-one",
    }
    status, corrected = post(correction)
    assert status == 200
    assert corrected["record"]["observations"][0]["revision"] == 2
    assert corrected["record"]["observation_history"][0]["source_pixels"] == first["source_pixels"]
    assert corrected["evidence"]["calibration_qualified"] is False
    assert post(correction) == (status, corrected)
    assert post({**correction, "idempotency_key": "stale-correction"})[0] == 422
    assert {path: sha256_file(path) for path in frozen} == frozen
    reopened = read_archive(SceneReader(server.derived.manifest_path).read())
    assert reopened["status"] == "available"
    assert reopened["calibration"]["observations"][0]["source_pixels"] == first["source_pixels"]
    assert reopened["measurements"][0]["record"]["observations"][0]["revision"] == 1
    assert (
        post(
            {
                "action": "rename",
                "reference_id": first["reference_id"],
                "display_name": "Renamed <freely>",
            }
        )[1]["record"]["reference_id"]
        == first["reference_id"]
    )
    assert json.loads(request(server, "/api/scene")[1])["measurement_names"] == {
        first["reference_id"]: "Renamed <freely>"
    }
    assert sha256_file(server.scene.point_cloud_path) == source_hash


def test_workspace_writes_require_same_origin_json(server):
    connection = http.client.HTTPConnection("127.0.0.1", server.server_port)
    connection.request("POST", "/api/visibility", "{}", {"Content-Type": "application/json"})
    response = connection.getresponse()
    assert response.status == 403
    response.read()
    connection.close()
