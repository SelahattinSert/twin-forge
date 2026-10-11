"""Source-bound immutable versions, repeat calibration, and recovery."""
# ruff: noqa: F811

import json
import sys
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "unit"))

import numpy as np
import pytest
from test_application_scenes import prefix, request
from test_calibrated_scene import scene_files  # noqa: F401

from twinforge.application.config import ApplicationConfig
from twinforge.application.server import ApplicationServer


@pytest.fixture
def version_app(scene_files, tmp_path):
    server = ApplicationServer(ApplicationConfig(tmp_path / "library", (scene_files,)))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    choice = server.library.discover()["scenes"][0]
    record = server.library.import_scene(choice["choice_id"], "Synthetic source")
    for pair in ((0, 1), (91, 92)):
        assert (
            request(
                server,
                prefix(record) + "/measurements",
                "POST",
                {
                    "reference_id": "width",
                    "quantity": "width",
                    "point_indices": pair,
                    "correspondence_state": "identified",
                },
            )[0]
            == 200
        )
    yield server, record
    server.shutdown()
    server.server_close()
    thread.join(2)


def calibrate(server, record, length=0.82):
    status, value = request(
        server,
        prefix(record) + "/calibration",
        "POST",
        {
            "reference_id": "width",
            "physical_value": length,
            "physical_unit": "m",
        },
    )
    assert status == 201
    version = value["version"]
    return record | {
        "default_session_id": version["session_id"],
        "default_version_id": version["version_id"],
    }


def test_versions_are_isolated_repeat_from_original_and_preserve_default(version_app):
    server, source = version_app
    first = calibrate(server, source)
    second = calibrate(server, first, 1.64)
    assert len({r["default_session_id"] for r in (source, first, second)}) == 3
    record = server.library.get(source["scene_id"])
    assert len(record["versions"]) == 3
    assert record["default_version_id"] == source["default_version_id"]
    assert not request(server, prefix(source) + "/scene")[1]["derived_available"]
    for item, scalar in ((first, 0.41), (second, 0.82)):
        assert request(server, prefix(item) + "/calibration")[1]["scalar"] == scalar
        workspace = server.library.workspace(
            item["scene_id"], item["default_run_id"], item["default_session_id"]
        )
        from twinforge.scene.reader import SceneReader

        derived = SceneReader(workspace / "derived").read()
        np.testing.assert_allclose(derived.point_records["x"][[0, 1]], [0, 2 * scalar])
        assert (
            request(
                server,
                prefix(item) + "/visibility",
                "POST",
                {"hidden_frame_ids": [], "hidden_rois": []},
            )[0]
            == 422
        )
    before = request(server, prefix(first) + "/check-report")[1]
    frozen_observation = request(server, prefix(source) + "/measurements/width")[1]["record"][
        "observations"
    ][0]
    assert (
        request(
            server,
            prefix(source) + "/measurements",
            "POST",
            {
                "reference_id": "width",
                "quantity": "width",
                "point_indices": [1, 0],
                "correspondence_state": "identified",
                "correction_id": frozen_observation["observation_id"],
                "expected_revision": frozen_observation["revision"],
                "correction_reason": "Reversed selected endpoints",
            },
        )[0]
        == 200
    )
    assert (
        request(server, prefix(first) + "/measurements/width")[1]["record"]["observations"][0]
        == frozen_observation
    )
    assert (
        request(
            server,
            prefix(source) + "/measurements",
            "POST",
            {
                "action": "rename",
                "reference_id": "width",
                "display_name": "Corrected label",
            },
        )[0]
        == 200
    )
    assert request(server, prefix(first) + "/check-report")[1] == before
    assert (
        request(server, prefix(first) + "/measurements/width")[1]["record"]["display_name"] is None
    )
    patched = server.library.patch(
        source["scene_id"],
        {"default_version_id": second["default_version_id"], "archived": True, "name": "Saved"},
    )
    assert patched["default_session_id"] == second["default_session_id"]
    assert server.library.patch(source["scene_id"], {"archived": False})["name"] == "Saved"


def test_overflow_keeps_working_default_and_failure_diagnostic(version_app):
    server, source = version_app
    status, _ = request(
        server,
        prefix(source) + "/calibration",
        "POST",
        {
            "reference_id": "width",
            "physical_value": 1e300,
            "physical_unit": "m",
        },
    )
    assert status == 422
    record = server.library.get(source["scene_id"])
    assert len(record["versions"]) == 1
    failures = list(server.library.root.glob("scenes/*/runs/*/workspaces/*/version-failure.json"))
    assert len(failures) == 1
    assert json.loads(failures[0].read_text())["state"] == "failed"
    assert not list(server.library.root.glob("scenes/*/runs/*/workspaces/*/derived/scene.json"))


def test_moved_linked_source_rebinds_all_version_sessions(version_app):
    server, source = version_app
    version = calibrate(server, source)
    run = server.library.run(source["scene_id"], source["default_run_id"])
    original = Path(run["source_root"])
    moved = original / "moved"
    moved.mkdir()
    for file in list(original.iterdir()):
        if file != moved:
            file.rename(moved / file.name)
    assert request(server, prefix(version) + "/scene")[0] == 422
    choices = server.library.discover()["scenes"]
    server.library.locate(source["scene_id"], choices[0]["choice_id"])
    assert request(server, prefix(version) + "/calibration")[1]["scalar"] == 0.41


def test_storage_distinguishes_linked_and_retained_bytes(version_app):
    server, _ = version_app
    status, value = request(server, "/api/storage")
    assert status == 200
    assert value["linked_original_bytes"] > 0
    assert value["managed_video_bytes"] == 0
    assert value["retained_export_bytes"] == 0
    assert value["archive_frees_bytes"] == 0


def test_frozen_report_tampering_is_rejected(version_app):
    server, source = version_app
    version = calibrate(server, source)
    workspace = server.library.workspace(
        version["scene_id"], version["default_run_id"], version["default_session_id"]
    )
    report = json.loads((workspace / "check-report.json").read_text())
    report["excluded_control_id"] = "invented"
    (workspace / "check-report.json").write_text(json.dumps(report))
    assert request(server, prefix(version) + "/check-report")[0] == 422


def test_calibration_checks_disk_before_publishing(version_app, monkeypatch):
    import shutil
    from types import SimpleNamespace

    server, source = version_app
    monkeypatch.setattr(shutil, "disk_usage", lambda _: SimpleNamespace(free=1))
    assert (
        request(
            server,
            prefix(source) + "/calibration",
            "POST",
            {"reference_id": "width", "physical_value": 0.82, "physical_unit": "m"},
        )[0]
        == 422
    )
    assert len(server.library.get(source["scene_id"])["versions"]) == 1


def test_version_and_archive_restore_survive_application_restart(scene_files, tmp_path):
    config = ApplicationConfig(tmp_path / "restart-library", (scene_files,))
    with ApplicationServer(config) as server:
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            source = server.library.import_scene(
                server.library.discover()["scenes"][0]["choice_id"], "Restart"
            )
            for pair in ((0, 1), (91, 92)):
                assert (
                    request(
                        server,
                        prefix(source) + "/measurements",
                        "POST",
                        {
                            "reference_id": "width",
                            "quantity": "width",
                            "point_indices": pair,
                            "correspondence_state": "identified",
                        },
                    )[0]
                    == 200
                )
            version = calibrate(server, source)
            server.library.patch(
                source["scene_id"],
                {"archived": True, "default_version_id": version["default_version_id"]},
            )
        finally:
            server.shutdown()
            thread.join(2)
    with ApplicationServer(config) as restarted:
        thread = threading.Thread(target=restarted.serve_forever, daemon=True)
        thread.start()
        try:
            restored = restarted.library.patch(source["scene_id"], {"archived": False})
            assert restored["default_session_id"] == version["default_session_id"]
            assert request(restarted, prefix(restored) + "/calibration")[1]["scalar"] == 0.41
            assert (
                request(restarted, prefix(restored) + "/check-report")[1]["excluded_control_id"]
                == "width"
            )
        finally:
            restarted.shutdown()
            thread.join(2)
