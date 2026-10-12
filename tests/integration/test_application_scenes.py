"""Two independent HTTP tabs, public metadata and explicit linked-import policy."""

import http.client
import json
import threading
from concurrent.futures import ThreadPoolExecutor

import cv2
import numpy as np
import pytest
from test_library import make_mapping, make_scene

from twinforge.application.config import ApplicationConfig
from twinforge.application.server import ApplicationServer
from twinforge.core.types import PointCloud
from twinforge.export.ply import write_ply
from twinforge.scene.provenance import PixelTransform


@pytest.fixture
def application(tmp_path):
    imports = tmp_path / "imports"
    for index in range(3):
        make_scene(imports / str(index) / "same-name", index * 10)
    server = ApplicationServer(
        ApplicationConfig(tmp_path / "library", (imports,), service_cache_size=1)
    )
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    yield server
    server.shutdown()
    server.server_close()
    worker.join(timeout=2)


def request(server, path, method="GET", value=None, token=True, origin=True):
    connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=10)
    headers = {"Content-Type": "application/json"}
    if token:
        headers["X-TwinForge-Token"] = server.request_token
    if origin:
        headers["Origin"] = server.url.rstrip("/")
    try:
        connection.request(method, path, json.dumps(value) if value is not None else None, headers)
        response = connection.getresponse()
        data = response.read()
        return response.status, json.loads(data) if "application/json" in response.getheader(
            "Content-Type", ""
        ) else data
    finally:
        connection.close()


def imported(server):
    status, choices = request(server, "/api/library/imports")
    assert status == 200
    records = []
    for item in choices["scenes"]:
        status, record = request(
            server,
            "/api/library/scenes",
            "POST",
            {"choice_id": item["choice_id"], "name": "Same name"},
        )
        assert status == 201
        records.append(record)
    return records


def prefix(record):
    return f"/api/scenes/{record['scene_id']}/runs/{record['default_run_id']}/sessions/{record['default_session_id']}"


def test_landing_and_import_tokens_and_lazy_cards(application, monkeypatch):
    server = application
    assert b"Your spatial library" in request(server, "/")[1]
    assert request(server, "/api/scene")[0] == 404
    assert request(server, "/api/library/scenes", "POST", {}, token=False)[0] == 403
    assert request(server, "/api/library/scenes", "POST", {}, origin=False)[0] == 403
    records = imported(server)
    assert not server.cache.entries
    assert len(request(server, "/api/library/scenes")[1]["scenes"]) == 3
    assert not server.cache.entries
    assert str(server.library.root) not in json.dumps(records)
    assert request(server, records[0]["thumbnail_url"])[0] == 200
    assert not server.cache.entries


def test_source_thumbnails_are_scoped_to_each_scene_and_survive_cache_eviction(application):
    for i, path in enumerate(sorted(application.library.config.import_roots[0].rglob("photo.jpg"))):
        assert cv2.imwrite(str(path), np.full((400, 600, 3), 50 + i * 60, dtype=np.uint8))
    records = imported(application)
    thumbnails = []
    for record in records:
        status, metadata = request(application, prefix(record) + "/scene")
        assert status == 200
        frame = metadata["frames"][0]
        assert frame["thumbnail_url"].startswith(prefix(record) + "/frames/")
        status, data = request(application, frame["thumbnail_url"])
        assert status == 200
        decoded = cv2.imdecode(np.frombuffer(data, dtype=np.uint8), cv2.IMREAD_COLOR)
        assert decoded.shape[:2] == (213, 320)
        thumbnails.append(data)
    assert len(set(thumbnails)) == 3
    assert request(application, prefix(records[0]) + "/frames/3/thumbnail")[1] == thumbnails[0]


def test_identical_reference_names_and_concurrent_tabs_are_isolated(application):
    server = application
    records = imported(server)
    a, b, c = records
    value = {
        "reference_id": "same-reference",
        "quantity": "width",
        "point_indices": [0, 1],
        "correspondence_state": "identified",
    }
    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(
            pool.map(
                lambda record: request(server, prefix(record) + "/measurements", "POST", value),
                (a, b),
            )
        )
    assert all(status == 200 for status, _ in responses)
    assert responses[0][1]["record"] != responses[1][1]["record"]
    for record in (a, b):
        status, metadata = request(server, prefix(record) + "/scene")
        assert status == 200 and metadata["name"] == "Same name"
        assert metadata["frames"][0]["image_url"].startswith(prefix(record))
        assert metadata["frames"][0]["points_url"].startswith(prefix(record))
        assert request(server, prefix(record) + "/measurements")[1] == ["same-reference"]
        assert request(server, prefix(record) + "/preview")[0] == 200
    assert request(server, prefix(c) + "/measurements")[1] == []
    assert len(server.cache.entries) == 1
    forged = prefix(a).replace(a["default_session_id"], b["default_session_id"])
    assert request(server, forged + "/scene")[0] == 422
    assert request(server, prefix(a) + "/measurements", "POST", value, token=False)[0] == 403


def test_disabled_source_folder_has_matching_card_and_opening_guidance(application):
    record = imported(application)[0]
    application.library.roots = ()
    status, listing = request(application, "/api/library/scenes")
    assert status == 200
    assert all(not item["ready_available"] for item in listing["scenes"])
    assert all(item["status"] == "source_unavailable" for item in listing["scenes"])
    status, error = request(application, prefix(record) + "/scene")
    assert status == 422
    assert error["error"]["code"] == "source_not_enabled"
    assert "--import-root" in error["error"]["message"]
    assert str(application.library.root.parent) not in json.dumps(error)
    assert not application.cache.entries


def test_source_change_blocks_cached_reads_and_writes(application):
    record = imported(application)[0]
    base = prefix(record)
    assert request(application, base + "/scene")[0] == 200
    run = application.library.run(record["scene_id"], record["default_run_id"])
    from pathlib import Path

    (Path(run["source_root"]) / "photo.jpg").write_bytes(b"changed source")
    assert request(application, base + "/preview")[0] == 422
    assert (
        request(
            application, base + "/visibility", "POST", {"hidden_frame_ids": [], "hidden_rois": []}
        )[0]
        == 422
    )


def test_rename_archive_restart_and_scoped_shell(application):
    record = imported(application)[0]
    status, updated = request(
        application,
        f"/api/library/scenes/{record['scene_id']}",
        "PATCH",
        {"name": "Renamed", "archived": True},
    )
    assert status == 200 and updated["archived"] and updated["name"] == "Renamed"
    assert application.library.get(record["scene_id"])["name"] == "Renamed"
    assert request(application, prefix(record)[4:])[0] == 200
    assert request(application, "/scene-client.js")[0] == 200


def pixel_scene(server, *, masked=False):
    source = server.library.roots[0] / "0/same-name"
    write_ply(
        source / "points.ply",
        PointCloud(
            np.array([[0, 0, 0], [1, 0, 0]], dtype=np.float32),
            source_frame_id=np.array([3, 3], dtype=np.uint32),
            source_pixel_index=np.array([0, 1], dtype=np.uint32),
            valid_mask=np.array([True, not masked]),
        ),
    )
    manifest = json.loads((source / "scene.json").read_text())
    manifest["pixel_transforms"] = [PixelTransform(3, 4, 1, 4, 1, (1, 0, 4, 1), "native").to_dict()]
    (source / "scene.json").write_text(json.dumps(manifest))
    server.library.discover()
    choice = next(
        key for key, path in server.library._choices.items() if path == source / "scene.json"
    )
    return server.library.import_scene(choice, "Pixel support fixture")


@pytest.mark.parametrize(
    "case,code,guidance",
    [
        ("unavailable", "pixel_provenance_unavailable", "Choose points in 3D"),
        ("cropped", "pixel_outside_crop", "Choose points inside"),
        ("missing", "pixel_not_retained", "Choose another supported pixel"),
        ("masked", "masked_endpoints", "Choose valid supported points"),
    ],
)
def test_image_pick_errors_explain_safe_recovery(application, case, code, guidance):
    scene = (
        imported(application)[0]
        if case == "unavailable"
        else pixel_scene(application, masked=case == "masked")
    )
    pixels = (
        [[0, 0], [2, 0]]
        if case == "cropped"
        else [[1, 0], [3, 0]]
        if case == "missing"
        else [[1, 0], [2, 0]]
    )
    status, body = request(
        application,
        prefix(scene) + "/measurements",
        "POST",
        {"reference_id": "support", "quantity": "width", "frame_id": 3, "source_pixels": pixels},
    )
    assert status == 422 and isinstance(body, dict)
    assert body["error"]["code"] == code and guidance in body["error"]["message"]
    assert str(application.library.roots[0]) not in json.dumps(body)


def test_stale_correction_requires_reopen_and_unknown_exception_stays_private(
    application, monkeypatch
):
    scene = pixel_scene(application)
    base = prefix(scene) + "/measurements"
    value = {
        "reference_id": "correct",
        "quantity": "width",
        "frame_id": 3,
        "source_pixels": [[1, 0], [2, 0]],
    }
    status, saved = request(application, base, "POST", value)
    assert status == 200
    observation = saved["record"]["observations"][0]
    correction = value | {
        "correction_id": observation["observation_id"],
        "expected_revision": 1,
        "correction_reason": "Updated selection",
    }
    assert request(application, base, "POST", correction)[0] == 200
    status, body = request(application, base, "POST", correction)
    assert status == 422 and isinstance(body, dict)
    assert body["error"]["code"] == "stale_correction"
    assert "Reopen the observation" in body["error"]["message"]

    def private_error(*args, **kwargs):
        raise ValueError("Private failure at /private/user/video.mp4")

    monkeypatch.setattr("twinforge.viewer.server.resolve_image_pixel", private_error)
    status, body = request(application, base, "POST", value)
    assert status == 422 and body == b"Invalid request or source unavailable"


def test_proof_mutation_invalidates_mapping_without_leaking_paths(application):
    library = application.library
    source = library.roots[0] / "0/same-name"
    proof = make_mapping(library.roots[0] / "mapping", source)
    choices = library.discover()
    choice = next(key for key, path in library._choices.items() if path == source / "scene.json")
    record = library.import_scene(choice, "Mapped", choices["workspaces"][0]["choice_id"])
    status, metadata = request(application, prefix(record) + "/scene")
    assert status == 200 and metadata["pixel_provenance_available"]
    assert "source_path" not in json.dumps(metadata)
    assert str(proof.parent) not in json.dumps(metadata)
    proof.write_text("changed proof")
    assert request(application, prefix(record) + "/scene")[0] == 422
