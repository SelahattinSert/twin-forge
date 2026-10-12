"""Application job HTTP contract with synthetic owned processes, never inference."""

import os
import sys
import threading
import time

import pytest

from tests.integration.test_application_ingest import request
from tests.job_support import WORKER, cached_source, managed_scene, wait_for
from twinforge.application.config import ApplicationConfig
from twinforge.application.jobs import JobManager
from twinforge.application.library import atomic_json
from twinforge.application.processes import process_info
from twinforge.application.server import ApplicationServer


@pytest.fixture
def application(tmp_path, monkeypatch):
    monkeypatch.setattr("twinforge.application.readiness.package_available", lambda _: False)
    server = ApplicationServer(
        ApplicationConfig(
            library=tmp_path / "library", torch_home=tmp_path / "torch", disk_reserve_bytes=1
        )
    )
    cached_source(server.library.config)
    monkeypatch.setattr(server.readiness, "status", lambda: {"processing_ready": True})
    server.readiness.devices = {"cpu": True, "cuda": False}
    server.jobs.test_mode = "success"
    monkeypatch.setattr(
        server.jobs,
        "_arguments",
        lambda path, nonce, fd: [
            sys.executable,
            str(WORKER),
            "--job",
            str(path),
            "--nonce",
            nonce,
            "--slot-fd",
            str(fd),
            "--mode",
            server.jobs.test_mode,
        ],
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield server
    server.shutdown()
    server.server_close()
    thread.join(timeout=2)


def queue(server, scene, key):
    return request(
        server, f"/api/library/scenes/{scene['scene_id']}/runs", "POST", {"idempotency_key": key}
    )


def test_http_poll_queue_cancel_retry_and_open_scene(application):
    application.jobs.test_mode = "slow"
    scene = managed_scene(application.library)
    status, first = queue(application, scene, "first")
    assert status == 202
    assert queue(application, scene, "first")[1]["job_id"] == first["job_id"]
    wait_for(application.jobs, first["job_id"], {"running"})
    child = application.jobs._paths[first["job_id"]].with_name("child.json")
    deadline = time.monotonic() + 5
    while not child.exists() and time.monotonic() < deadline:
        time.sleep(0.02)
    assert child.exists()
    second_scene = managed_scene(application.library)
    status, second = queue(application, second_scene, "second")
    assert status == 202 and second["state"] == "queued"
    started = time.monotonic()
    for path in ("/api/jobs", "/api/library/scenes", "/", "/activity.js"):
        assert request(application, path)[0] == 200
    assert time.monotonic() - started < 2
    polled = request(application, f"/api/jobs/{second['job_id']}")[1]
    assert polled["queue_position"] == 1
    assert "nonce" not in polled and "input" not in polled and "config" not in polled
    assert str(application.library.root) not in str(polled)
    application.jobs.test_mode = "success"
    assert (
        request(application, f"/api/jobs/{first['job_id']}/cancel", "POST", {})[1]["state"]
        == "cancelling"
    )
    wait_for(application.jobs, first["job_id"], {"cancelled"})
    ready = wait_for(application.jobs, second["job_id"], {"ready", "failed"})
    assert ready["state"] == "ready"
    assert request(application, ready["open_url"])[0] == 200
    scene_record = application.library.get(second_scene["scene_id"])
    prefix = (
        f"/api/scenes/{second_scene['scene_id']}/runs/{ready['run_id']}"
        f"/sessions/{scene_record['default_session_id']}"
    )
    assert request(application, prefix + "/scene")[0] == 200
    assert (
        request(application, f"/api/jobs/{second['job_id']}/cancel", "POST", {})[1]["state"]
        == "ready"
    )
    status, retry = request(
        application, f"/api/jobs/{first['job_id']}/retry", "POST", {"idempotency_key": "retry"}
    )
    assert status == 200 and retry["run_id"] != first["run_id"]
    assert wait_for(application.jobs, retry["job_id"], {"ready", "failed"})["state"] == "ready"


def test_job_mutations_require_token_and_allowlisted_settings(application):
    scene = managed_scene(application.library)
    path = f"/api/library/scenes/{scene['scene_id']}/runs"
    assert (
        request(
            application,
            path,
            "POST",
            {"idempotency_key": "bad"},
            extra={"X-TwinForge-Token": "foreign"},
        )[0]
        == 403
    )
    assert (
        request(
            application, path, "POST", {"idempotency_key": "bad", "checkpoint": "/tmp/foreign"}
        )[0]
        == 422
    )
    assert not application.jobs.list()["jobs"]


def test_scene_summaries_connect_two_named_jobs_and_failed_retry(application, monkeypatch):
    monkeypatch.setattr(application.jobs, "_drain", lambda: None)
    first_scene, second_scene = (
        managed_scene(application.library),
        managed_scene(application.library),
    )
    application.library.patch(first_scene["scene_id"], {"name": "Kitchen"})
    application.library.patch(second_scene["scene_id"], {"name": "Hallway"})
    _, first = queue(application, first_scene, "named-first")
    application.jobs._thread.join()
    _, second = queue(application, second_scene, "named-second")
    application.jobs._thread.join()
    record = application.jobs._read(first["job_id"])
    application.jobs._transition(record, "running")
    cards = {
        item["scene_id"]: item for item in request(application, "/api/library/scenes")[1]["scenes"]
    }
    assert cards[first_scene["scene_id"]]["status"] == "running"
    assert cards[second_scene["scene_id"]]["status"] == "queued"
    assert cards[first_scene["scene_id"]]["latest_job"]["job_id"] == first["job_id"]
    jobs = {item["job_id"]: item for item in request(application, "/api/jobs")[1]["jobs"]}
    assert jobs[first["job_id"]]["scene_name"] == "Kitchen"
    assert jobs[second["job_id"]]["scene_name"] == "Hallway"
    application.jobs._transition(record, "failed", "worker_failed")
    failed = {
        item["scene_id"]: item for item in request(application, "/api/library/scenes")[1]["scenes"]
    }
    assert failed[first_scene["scene_id"]]["status"] == "failed"
    _, retry = request(
        application,
        f"/api/jobs/{first['job_id']}/retry",
        "POST",
        {"idempotency_key": "named-retry"},
    )
    application.jobs._thread.join()
    refreshed = {
        item["scene_id"]: item for item in request(application, "/api/library/scenes")[1]["scenes"]
    }
    assert refreshed[first_scene["scene_id"]]["status"] == "queued"
    assert refreshed[first_scene["scene_id"]]["latest_job"]["run_id"] == retry["run_id"]
    application.jobs.cancel(second["job_id"])
    application.jobs.cancel(retry["job_id"])


def test_new_incomplete_job_preserves_openable_older_ready_scene(application, monkeypatch):
    scene = managed_scene(application.library)
    _, first = queue(application, scene, "older-ready")
    ready = wait_for(application.jobs, first["job_id"], {"ready", "failed"})
    assert ready["state"] == "ready"
    if application.jobs._thread is not None:
        application.jobs._thread.join()
    monkeypatch.setattr(application.jobs, "_drain", lambda: None)
    _, newer = queue(application, scene, "newer-incomplete")
    application.jobs._thread.join()
    summary = request(application, "/api/library/scenes")[1]["scenes"][0]
    assert summary["status"] == "queued" and summary["ready_available"] is True
    assert summary["default_run_id"] == ready["run_id"]
    assert summary["latest_job"]["run_id"] == newer["run_id"]
    assert request(application, ready["open_url"])[0] == 200
    application.jobs.cancel(newer["job_id"])


def test_activity_keeps_job_identity_when_its_scene_record_is_unavailable(application, monkeypatch):
    monkeypatch.setattr(application.jobs, "_drain", lambda: None)
    scene = managed_scene(application.library)
    _, job = queue(application, scene, "unavailable-name")
    application.jobs._thread.join()
    path = application.library._scene_path(scene["scene_id"])
    path.write_text("[]")
    path.with_suffix(".previous").write_text("[]")
    status, activity = request(application, "/api/jobs")
    assert status == 200
    assert activity["jobs"][0]["scene_name"] == "Scene unavailable"
    assert activity["jobs"][0]["job_id"] == job["job_id"]
    assert request(application, "/api/library/scenes")[1]["issues"]
    application.jobs.cancel(job["job_id"])


def test_unresolved_owner_with_free_slot_blocks_prepare_endpoint_and_jobs(application, monkeypatch):
    monkeypatch.setattr(application.jobs, "_drain", lambda: None)
    scene = managed_scene(application.library)
    _, job = queue(application, scene, "unresolved")
    application.jobs._thread.join()
    record = application.jobs._read(job["job_id"])
    record.update(
        state="running",
        owner={
            "pid": os.getpid(),
            "process": process_info(os.getpid()),
            "nonce": "unverified",
            "arguments": [],
        },
    )
    atomic_json(application.jobs._paths[job["job_id"]], record)
    previous = application.jobs
    application.jobs = JobManager(application.library, application.readiness)
    previous.close()
    assert application.jobs.list()["ownership_unresolved"]
    assert not application.readiness.slot.busy()
    with pytest.raises(ValueError, match="unresolved"):
        application.readiness.slot.acquire()
    readiness = type(application.readiness).status(application.readiness)
    assert readiness["ownership_unresolved"] and not readiness["job_launch_available"]
    monkeypatch.setattr("twinforge.application.readiness.package_available", lambda _: True)
    monkeypatch.setattr(
        "twinforge.application.readiness.subprocess.Popen",
        lambda *a, **kw: pytest.fail("Unresolved heavy ownership must not launch setup"),
    )
    status, result = request(application, "/api/readiness/prepare", "POST", {})
    assert status == 409 and result["error"]["code"] == "setup_busy"
    assert queue(application, scene, "blocked")[0] == 422
    assert not application.readiness.slot.busy()


def test_http_preview_validation_does_not_block_requests(application, monkeypatch):
    from twinforge.application.output_validation import validate_output

    entered, release = threading.Event(), threading.Event()

    def slow_preview(*args):
        entered.set()
        assert release.wait(5)
        return validate_output(*args)

    monkeypatch.setattr("twinforge.application.jobs.validate_output", slow_preview)
    scene = managed_scene(application.library)
    status, job = queue(application, scene, "preview")
    assert status == 202 and entered.wait(5)
    try:
        started = time.monotonic()
        assert request(application, "/api/library/scenes")[0] == 200
        assert request(application, f"/api/jobs/{job['job_id']}")[1]["state"] == "validating_output"
        assert time.monotonic() - started < 2
    finally:
        release.set()
    assert wait_for(application.jobs, job["job_id"], {"ready", "failed"})["state"] == "ready"
