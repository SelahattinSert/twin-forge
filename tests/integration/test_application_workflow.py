"""Product journeys through real HTTP/storage with synthetic workers, never inference."""
# ruff: noqa: F811

import json
import threading
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import replace

from tests.integration.test_application_exports import export, reopen
from tests.integration.test_application_ingest import movie, request, transfer  # noqa: F401
from tests.integration.test_application_jobs import application, queue  # noqa: F401
from tests.integration.test_application_scenes import prefix
from tests.integration.test_application_versions import calibrate
from tests.integration.test_calibrated_scene import scene_files  # noqa: F401
from tests.job_support import cached_source, managed_scene, wait_for
from twinforge.application.config import ApplicationConfig
from twinforge.application.server import ApplicationServer
from twinforge.scene.reader import sha256_file


def upload_scene(server, movie, name):
    base, receipt = transfer(server, movie.read_bytes())
    status, result = request(server, base + "/complete", "POST", {"name": name})
    assert status == 201, result
    assert request(server, base)[1]["state"] == "complete"
    scene = result["scene"]
    assert scene["status"] == "ready_to_start" and not scene["versions"]
    assert scene["media"]["sha256"] == sha256_file(movie)
    assert receipt["expected_bytes"] == movie.stat().st_size
    return scene


def observe(server, scene, pair, reference="segment", frame_id=None):
    selection = (
        {"point_indices": pair}
        if frame_id is None
        else {"frame_id": frame_id, "source_pixels": pair}
    )
    status, result = request(
        server,
        prefix(scene) + "/measurements",
        "POST",
        {
            "reference_id": reference,
            "quantity": "width",
            **selection,
            "correspondence_state": "identified",
        },
    )
    assert status == 200, result
    return result


@contextmanager
def running_application(config):
    with ApplicationServer(config) as server:
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            yield server
        finally:
            server.shutdown()
            thread.join(timeout=2)


def test_uploaded_video_to_observation_and_independent_reopened_package(application, movie):
    server = application
    scene = upload_scene(server, movie, "First room")
    status, reviewed = request(
        server,
        f"/api/library/scenes/{scene['scene_id']}/media/review",
        "POST",
        {"name": "Saved room", "profile": "standard", "device": "cpu"},
    )
    assert status == 200 and reviewed["name"] == "Saved room"
    settings = reviewed["media"]["review_settings"]
    assert settings["maximum_keyframes"] == 32
    assert not settings["auto_budget"] and settings["maximum_oom_retries"] == 0
    status, job = queue(server, scene, "first-start")
    assert status == 202
    assert queue(server, scene, "first-start")[1]["job_id"] == job["job_id"]
    ready = wait_for(server.jobs, job["job_id"], {"ready", "failed"})
    assert ready["state"] == "ready", ready
    scene = request(server, f"/api/library/scenes/{scene['scene_id']}")[1]
    assert scene["name"] == "Saved room" and len(scene["versions"]) == 1
    assert request(server, ready["open_url"])[0] == 200
    metadata = request(server, prefix(scene) + "/scene")[1]
    assert metadata["pixel_provenance_available"]
    observe(server, scene, [[0, 0], [1, 0]], frame_id=1)
    assert (
        request(
            server,
            prefix(scene) + "/measurements",
            "POST",
            {"action": "rename", "reference_id": "segment", "display_name": "Wall segment"},
        )[0]
        == 200
    )
    saved = request(server, prefix(scene) + "/measurements/segment")[1]
    assert saved["record"]["display_name"] == "Wall segment"
    assert saved["evidence"]["state"] == "insufficient_evidence"
    assert saved["evidence"]["distinct_view_count"] == 1
    assert not saved["evidence"]["calibration_qualified"]
    assert (
        request(
            server,
            prefix(scene) + "/calibration",
            "POST",
            {"reference_id": "segment", "physical_value": 1, "physical_unit": "m"},
        )[0]
        == 422
    )
    assert len(request(server, f"/api/library/scenes/{scene['scene_id']}")[1]["versions"]) == 1
    bundle = export(server, scene)
    status, package = request(server, bundle["download_url"])
    assert status == 200
    status, restored = reopen(server, package)
    assert status == 201 and restored["scene_id"] != scene["scene_id"]
    assert restored["source_kind"] == "package"
    assert request(server, prefix(restored) + "/measurements/segment")[1] == saved
    # Two separately scoped requests share a reference name but no mutable observations.
    with ThreadPoolExecutor(max_workers=2) as tabs:
        responses = list(tabs.map(lambda item: observe(server, item, [1, 0]), (scene, restored)))
    assert len(responses) == 2
    original = request(server, prefix(scene) + "/measurements/segment")[1]["record"]
    copied = request(server, prefix(restored) + "/measurements/segment")[1]["record"]
    assert len(original["observations"]) == len(copied["observations"]) == 2
    assert (
        original["observations"][-1]["observation_id"]
        != copied["observations"][-1]["observation_id"]
    )
    assert len(request(server, "/api/library/scenes")[1]["scenes"]) == 2
    assert request(
        server, f"/api/library/scenes/{scene['scene_id']}/video", extra={"Range": "bytes=0-15"}
    ) == (206, movie.read_bytes()[:16])


def test_cancel_failure_retry_preserves_other_ready_scene_and_original(application):
    server = application
    scene = managed_scene(server.library)
    other = managed_scene(server.library)
    video = (
        server.library.media_path(scene["scene_id"], scene["media"]["media_id"]) / "original.mp4"
    )
    protected = sha256_file(video)
    server.jobs.test_mode = "slow"
    _, first = queue(server, scene, "cancel-me")
    wait_for(server.jobs, first["job_id"], {"running"})
    _, second = queue(server, other, "other-room")
    assert second["state"] == "queued"
    # Fresh HTTP polls emulate refreshing Activity while processing continues.
    assert request(server, f"/api/jobs/{first['job_id']}")[1]["state"] == "running"
    assert request(server, f"/api/jobs/{second['job_id']}")[1]["queue_position"] == 1
    assert len(request(server, "/api/library/scenes")[1]["scenes"]) == 2
    server.jobs.test_mode = "success"
    assert request(server, f"/api/jobs/{first['job_id']}/cancel", "POST", {})[0] == 200
    assert wait_for(server.jobs, first["job_id"], {"cancelled"})["state"] == "cancelled"
    assert wait_for(server.jobs, second["job_id"], {"ready", "failed"})["state"] == "ready"
    other_before = request(server, f"/api/library/scenes/{other['scene_id']}")[1]
    server.jobs.test_mode = "decode_failure"
    status, failed_retry = request(
        server, f"/api/jobs/{first['job_id']}/retry", "POST", {"idempotency_key": "failed-retry"}
    )
    assert status == 200 and failed_retry["run_id"] != first["run_id"]
    failed = wait_for(server.jobs, failed_retry["job_id"], {"ready", "failed"})
    assert failed["state"] == "failed" and failed["failure"]["code"] == "worker_failed"
    assert failed["failure"]["message"]
    assert not request(server, f"/api/library/scenes/{scene['scene_id']}")[1]["versions"]
    server.jobs.test_mode = "success"
    status, retry = request(
        server,
        f"/api/jobs/{failed['job_id']}/retry",
        "POST",
        {"idempotency_key": "successful-retry"},
    )
    assert status == 200 and retry["run_id"] != failed["run_id"]
    assert wait_for(server.jobs, retry["job_id"], {"ready", "failed"})["state"] == "ready"
    assert request(server, f"/api/library/scenes/{other['scene_id']}")[1] == other_before
    assert sha256_file(video) == protected
    history = request(server, "/api/jobs")[1]["jobs"]
    assert len(history) == 4
    assert {job["state"] for job in history} == {"ready", "failed", "cancelled"}


def test_saved_version_and_package_survive_application_restart(scene_files, tmp_path, monkeypatch):
    monkeypatch.setattr("twinforge.application.readiness.package_available", lambda _: False)
    config = ApplicationConfig(
        tmp_path / "restart-library", (scene_files,), torch_home=tmp_path / "torch"
    )
    source_hashes = {path: sha256_file(path) for path in scene_files.iterdir() if path.is_file()}
    with running_application(config) as server:
        choices = request(server, "/api/library/imports")[1]
        status, source = request(
            server,
            "/api/library/scenes",
            "POST",
            {"choice_id": choices["scenes"][0]["choice_id"], "name": "Named source"},
        )
        assert status == 201
        for frame_id in (3, 17):
            observe(server, source, [[2, 3], [10, 3]], "width", frame_id=frame_id)
        qualified = request(server, prefix(source) + "/measurements/width")[1]
        assert qualified["evidence"]["calibration_qualified"]
        version = calibrate(server, source)
        frozen = request(server, prefix(version) + "/measurements/width")[1]
        report = request(server, prefix(version) + "/check-report")[1]
        status, selected = request(
            server,
            f"/api/library/scenes/{source['scene_id']}",
            "PATCH",
            {"name": "Saved calibrated room", "default_version_id": version["default_version_id"]},
        )
        assert status == 200 and selected["default_session_id"] == version["default_session_id"]
        bundle = export(server, version)
        package = request(server, bundle["download_url"])[1]
        token = server.request_token
        # Persist accepted queued work, then close before compute starts.
        cached_source(config)
        monkeypatch.setattr(server.readiness, "status", lambda: {"processing_ready": True})
        server.readiness.devices = {"cpu": True, "cuda": False}
        monkeypatch.setattr(server.jobs, "_drain", lambda: None)
        status, queued = queue(server, managed_scene(server.library), "restart-before-start")
        assert status == 202 and queued["state"] == "queued"
    assert {path: sha256_file(path) for path in source_hashes} == source_hashes
    # The downloaded package must not depend on the linked source or old server cache.
    moved = scene_files.with_name(scene_files.name + "-offline")
    scene_files.rename(moved)
    with running_application(replace(config, import_roots=())) as restarted:
        assert restarted.request_token != token
        assert restarted.jobs._thread is None
        recovered = request(restarted, f"/api/jobs/{queued['job_id']}")[1]
        assert recovered["state"] == "interrupted"
        assert recovered["failure"]["code"] == "interrupted_before_start"
        assert not recovered["worker_alive"]
        listed = request(restarted, "/api/library/scenes")[1]["scenes"]
        assert len(listed) == 2
        assert (
            next(item for item in listed if item["scene_id"] == source["scene_id"])["name"]
            == "Saved calibrated room"
        )
        retained = request(restarted, f"/api/library/scenes/{source['scene_id']}")[1]
        assert retained["default_version_id"] == version["default_version_id"]
        assert len(retained["versions"]) == 2
        assert request(restarted, bundle["download_url"])[1] == package
        status, restored = reopen(restarted, package)
        assert status == 201 and restored["source_kind"] == "package"
        assert (
            request(restarted, prefix(restored) + "/derived/scene")[1]["scale"]["type"]
            == "calibrated_metric"
        )
        assert request(restarted, prefix(restored) + "/measurements/width")[1] == frozen
        assert request(restarted, prefix(restored) + "/check-report")[1] == report
        assert request(restarted, prefix(restored) + "/calibration")[1]["scalar"] == 0.41
        assert request(restarted, prefix(restored) + "/frames/3/image")[0] == 200
        assert str(config.library) not in json.dumps(restored)
