"""Supervised job contracts use synthetic processes and temporary library data only."""

import ast
import importlib.metadata
import json
import os
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import urlopen

import pytest

from tests.job_support import WORKER, cached_source, managed_scene, successful_output, wait_for
from twinforge.application.config import ApplicationConfig
from twinforge.application.jobs import JobManager
from twinforge.application.library import LibraryStore, atomic_json
from twinforge.application.output_validation import validate_output
from twinforge.application.processes import process_info, terminate_group, verified_owner
from twinforge.application.readiness import ReadinessManager
from twinforge.application.worker import offline_network, run_worker
from twinforge.scene.reader import SceneReadError


@pytest.fixture
def jobs(tmp_path, monkeypatch):
    monkeypatch.setattr("twinforge.application.readiness.package_available", lambda _: False)
    config = ApplicationConfig(
        library=tmp_path / "library", torch_home=tmp_path / "torch", disk_reserve_bytes=1
    )
    library = LibraryStore(config)
    readiness = ReadinessManager(config)
    cached_source(config)
    monkeypatch.setattr(readiness, "status", lambda: {"processing_ready": True})
    readiness.devices = {"cpu": True, "cuda": False}
    manager = JobManager(library, readiness)
    manager.test_mode = "success"
    monkeypatch.setattr(
        manager,
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
            manager.test_mode,
        ],
    )
    yield manager
    manager.close()
    readiness.close()
    library.close()


def submit(jobs, key="first"):
    scene = managed_scene(jobs.library)
    return jobs.create(scene["scene_id"], key)


def test_submission_at_supervisor_retirement_starts_replacement(jobs, monkeypatch):
    original = jobs._drain
    retired, release = threading.Event(), threading.Event()

    def hold_first_thread_after_drain():
        original()
        if not retired.is_set():
            retired.set()
            assert release.wait(5)

    monkeypatch.setattr(jobs, "_drain", hold_first_thread_after_drain)
    first = submit(jobs)
    retiring_thread = jobs._thread
    try:
        assert wait_for(jobs, first["job_id"], {"ready", "failed"})["state"] == "ready"
        assert retired.wait(5) and retiring_thread.is_alive()
        second = submit(jobs, "boundary")
        assert wait_for(jobs, second["job_id"], {"ready", "failed"}, timeout=3)["state"] == "ready"
    finally:
        release.set()
        retiring_thread.join(timeout=2)


def test_close_snapshots_retiring_thread_under_lock_and_joins_outside(jobs, monkeypatch):
    observed, retire, retired = threading.Event(), threading.Event(), threading.Event()
    joined = []
    original_get = JobManager.__getattribute__

    class Supervisor:
        def join(self):
            assert not jobs._lock._is_owned(), (
                "Joining must let the supervisor acquire the queue lock"
            )
            assert retired.wait(2)
            joined.append(self)

    supervisor = Supervisor()
    jobs._thread = supervisor

    def retire_supervisor():
        assert retire.wait(2)
        with jobs._lock:
            jobs._thread = None
        retired.set()

    def observe_first_reference(instance, name):
        value = original_get(instance, name)
        if instance is jobs and name == "_thread" and not observed.is_set():
            observed.set()
            retire.set()
            # Force retirement between an unlocked check and its later reread.
            # A locked snapshot prevents retirement until close releases the lock.
            if not jobs._lock._is_owned():
                assert retired.wait(2)
        return value

    retirement = threading.Thread(target=retire_supervisor)
    retirement.start()
    monkeypatch.setattr(JobManager, "__getattribute__", observe_first_reference)
    try:
        jobs.close()
        assert joined == [supervisor]
    finally:
        observed.set()
        retire.set()
        retirement.join(timeout=2)
        jobs._thread = None


def test_preflight_reserve_failure_has_storage_action_without_worker(jobs, monkeypatch):
    def no_storage():
        raise OSError("Synthetic free-space reserve failure")

    monkeypatch.setattr(jobs, "_storage", no_storage)
    monkeypatch.setattr(
        jobs, "_arguments", lambda *args: pytest.fail("Storage failure must not spawn")
    )
    job = submit(jobs)
    failed = wait_for(jobs, job["job_id"], {"failed"})
    assert failed["failure"]["code"] == "insufficient_storage"
    assert failed["worker_alive"] is False
    assert jobs.library.get(job["scene_id"])["default_run_id"] is None


def test_success_actual_return_path_frozen_settings_events_and_late_cancel(jobs):
    job = submit(jobs)
    duplicate = jobs.create(job["scene_id"], "first")
    assert duplicate["job_id"] == job["job_id"]
    ready = wait_for(jobs, job["job_id"], {"ready", "failed"})
    assert ready["state"] == "ready", jobs._read(job["job_id"])
    saved = jobs._read(job["job_id"])
    assert saved["output_path"].endswith("actual-engine-return")
    assert saved["config"]["backend"]["maximum_keyframes"] == 32
    assert saved["config"]["memory"]["auto_budget"] is False
    assert saved["config"]["memory"]["maximum_oom_retries"] == 0
    codes = [item["message_code"] for item in ready["events"]]
    assert all(
        stage in codes
        for stage in (
            "inspecting",
            "selecting_images",
            "loading_model",
            "reconstructing",
            "exporting",
        )
    )
    assert [item["sequence"] for item in ready["events"]] == list(
        range(1, len(ready["events"]) + 1)
    )
    assert jobs.cancel(job["job_id"])["state"] == "ready"
    scene = jobs.library.get(job["scene_id"])
    run = jobs.library.run(scene["scene_id"], scene["default_run_id"])
    jobs.library.validate_source(run)
    assert jobs.library.prepared_preview(run)[:4] == b"TFP1"


@pytest.mark.parametrize(
    "mode", ["crash", "oom", "decode_failure", "export_failure", "invalid", "stale_receipt"]
)
def test_failure_never_publishes_and_retry_is_new_run(jobs, mode):
    jobs.test_mode = mode
    job = submit(jobs)
    assert wait_for(jobs, job["job_id"], {"failed"})["failure"]
    assert jobs.library.get(job["scene_id"])["default_run_id"] is None
    jobs.test_mode = "success"
    retry = jobs.retry(job["job_id"], "retry")
    assert retry["run_id"] != job["run_id"]
    assert wait_for(jobs, retry["job_id"], {"ready", "failed"})["state"] == "ready"


def test_cancel_children_and_serial_queue(jobs):
    jobs.test_mode = "slow"
    first = submit(jobs)
    child_path = jobs._paths[first["job_id"]].with_name("child.json")
    deadline = time.monotonic() + 8
    while not child_path.exists() and time.monotonic() < deadline:
        time.sleep(0.02)
    child_pid = json.loads(child_path.read_text())["pid"]
    second = submit(jobs, "second")
    assert jobs.get(second["job_id"])["queue_position"] == 1
    assert jobs.get(second["job_id"])["state"] == "queued"
    jobs.test_mode = "success"
    assert jobs.cancel(first["job_id"])["state"] == "cancelling"
    assert wait_for(jobs, first["job_id"], {"cancelled"})["worker_alive"] is False
    assert process_info(child_pid) is None
    assert wait_for(jobs, second["job_id"], {"ready", "failed"})["state"] == "ready"


def test_cancel_during_validation_cannot_publish(jobs, monkeypatch):
    started, finish = threading.Event(), threading.Event()
    original = validate_output

    def slow_validate(*args):
        started.set()
        assert finish.wait(5)
        return original(*args)

    monkeypatch.setattr("twinforge.application.jobs.validate_output", slow_validate)
    job = submit(jobs)
    assert started.wait(8)
    assert jobs.cancel(job["job_id"])["state"] == "cancelling"
    finish.set()
    assert wait_for(jobs, job["job_id"], {"cancelled"})
    assert jobs.library.get(job["scene_id"])["versions"] == []


def test_restart_marks_prior_queue_interrupted_without_launch(jobs, monkeypatch):
    monkeypatch.setattr(jobs, "_drain", lambda: None)
    job = submit(jobs)
    jobs._thread.join()
    restarted = JobManager(jobs.library, jobs.readiness)
    assert restarted.get(job["job_id"])["failure"]["code"] == "interrupted_before_start"
    assert restarted._thread is None
    restarted.close()


def test_original_hash_revalidated_before_spawning(jobs, monkeypatch):
    monkeypatch.setattr(jobs, "_drain", lambda: None)
    job = submit(jobs)
    jobs._thread.join()
    record = jobs._read(job["job_id"])
    source = Path(record["input"]["path"])
    source.write_bytes(b"x" * source.stat().st_size)
    monkeypatch.setattr(
        jobs, "_arguments", lambda *args: pytest.fail("Changed source must not spawn")
    )
    jobs.slot.acquire()
    try:
        jobs._execute(job["job_id"])
    finally:
        jobs.slot.release()
    assert jobs.get(job["job_id"])["failure"]["code"] == "input_changed"


def test_setup_and_jobs_share_atomic_heavy_slot(jobs, monkeypatch):
    monkeypatch.setattr("twinforge.application.readiness.package_available", lambda _: True)
    from twinforge.application.uploads import UploadError

    jobs.slot.acquire()
    with pytest.raises(UploadError, match="running"):
        jobs.readiness.prepare()
    jobs.slot.release()
    monkeypatch.setattr(jobs.readiness, "is_preparing", lambda: True)
    with pytest.raises(ValueError, match="ownership"):
        submit(jobs)


def test_stale_pid_or_nonce_never_signalled(jobs, monkeypatch):
    monkeypatch.setattr(jobs, "_drain", lambda: None)
    job = submit(jobs)
    jobs._thread.join()
    record = jobs._read(job["job_id"])
    record.update(
        state="running",
        owner={
            "pid": os.getpid(),
            "process": process_info(os.getpid()),
            "nonce": "wrong",
            "arguments": [],
        },
    )
    atomic_json(jobs._paths[job["job_id"]], record)
    monkeypatch.setattr(
        "twinforge.application.jobs.terminate_group",
        lambda *_: pytest.fail("Foreign PID must not be signalled"),
    )
    restarted = JobManager(jobs.library, jobs.readiness)
    assert restarted.get(job["job_id"])["failure"]["code"] == "ownership_unresolved"
    assert restarted.list()["ownership_unresolved"]
    restarted.close()


def test_birth_identity_rejects_reused_pid():
    owner = {"pid": os.getpid(), "process": process_info(os.getpid()) | {"birth": "wrong"}}
    assert not verified_owner(owner, [])


def test_fast_history_is_bounded_and_retains_known_counts(jobs):
    jobs.test_mode = "fast_events"
    job = submit(jobs)
    ready = wait_for(jobs, job["job_id"], {"ready", "failed"})
    assert ready["state"] == "ready"
    assert len(ready["events"]) == 128
    history = jobs._paths[job["job_id"]].with_name("events.jsonl").read_text().splitlines()
    assert len(history) == 128
    known = [event for event in ready["events"] if event["message_code"] == "known_work"]
    assert known[-1]["completed"] == known[-1]["total"] == 400
    assert all(a["sequence"] < b["sequence"] for a, b in zip(ready["events"], ready["events"][1:]))


def test_abnormal_leader_exit_reaps_children_and_releases_slot(jobs):
    jobs.test_mode = "crash_child"
    job = submit(jobs)
    assert wait_for(jobs, job["job_id"], {"failed"})["worker_alive"] is False
    child_pid = json.loads(jobs._paths[job["job_id"]].with_name("child.json").read_text())["pid"]
    assert process_info(child_pid) is None
    assert not jobs.slot.busy()


def test_close_interrupts_active_and_queued_jobs(jobs):
    jobs.test_mode = "slow"
    first = submit(jobs)
    wait_for(jobs, first["job_id"], {"running"})
    second = submit(jobs, "second")
    jobs.close()
    assert jobs.get(first["job_id"])["state"] == "interrupted"
    assert jobs.get(first["job_id"])["worker_alive"] is False
    assert jobs.get(second["job_id"])["failure"]["code"] == "interrupted_before_start"
    assert not jobs.slot.busy()


def test_verified_orphan_restart_stops_owned_group_without_compute(jobs, monkeypatch):
    monkeypatch.setattr(jobs, "_drain", lambda: None)
    job = submit(jobs)
    jobs._thread.join()
    path = jobs._paths[job["job_id"]]
    record = jobs._read(job["job_id"])
    fd = jobs.slot.acquire()
    arguments = [
        sys.executable,
        str(WORKER),
        "--job",
        str(path),
        "--nonce",
        record["nonce"],
        "--slot-fd",
        str(fd),
        "--mode",
        "slow",
    ]
    process = subprocess.Popen(arguments, start_new_session=True, pass_fds=(fd,))
    try:
        record.update(
            state="running",
            owner={
                "pid": process.pid,
                "process": process_info(process.pid),
                "nonce": record["nonce"],
                "arguments": arguments,
            },
        )
        atomic_json(path, record)
        jobs.slot.release()  # Simulates owner loss; worker retains the same lock description.
        from twinforge.application.coordination import HeavySlot

        other = HeavySlot(jobs.library.root)
        assert other.busy()
        with pytest.raises(ValueError, match="surviving"):
            other.acquire()
        restarted = JobManager(jobs.library, jobs.readiness)
        assert restarted.get(job["job_id"])["state"] == "interrupted"
        assert process_info(process.pid) is None
        assert not other.busy()
        assert restarted._thread is None
        restarted.close()
    finally:
        terminate_group(process.pid, process)


def test_unresolved_owner_stays_blocked_on_second_restart(jobs, monkeypatch):
    monkeypatch.setattr(jobs, "_drain", lambda: None)
    job = submit(jobs)
    jobs._thread.join()
    record = jobs._read(job["job_id"])
    record.update(
        state="running",
        owner={
            "pid": os.getpid(),
            "process": process_info(os.getpid()),
            "nonce": "foreign",
            "arguments": [],
        },
    )
    atomic_json(jobs._paths[job["job_id"]], record)
    first = JobManager(jobs.library, jobs.readiness)
    second = JobManager(jobs.library, jobs.readiness)
    assert first.list()["ownership_unresolved"]
    assert second.list()["ownership_unresolved"]
    first.close()
    second.close()


def test_worker_offline_cache_initialization_and_early_failure_receipts(jobs, monkeypatch):
    from types import SimpleNamespace

    from twinforge.reconstruction.progress import ProgressReporter

    monkeypatch.setattr(jobs, "_drain", lambda: None)
    job = submit(jobs)
    jobs._thread.join()
    path = jobs._paths[job["job_id"]]
    record = jobs._read(job["job_id"])
    initialized = []

    class Backend:
        def __init__(self, checkpoint, revision):
            initialized.append((checkpoint, revision))
            with pytest.raises(OSError, match="offline"):
                socket.getaddrinfo("example.test", 443)

    class Engine:
        def __init__(self, backend, config):
            assert config.memory.auto_budget is False

        def run(self, video, *, scratch_root, on_progress):
            assert scratch_root == path.parent / "scratch"
            assert self.ingestor.local_only
            reporter = ProgressReporter(on_progress)
            for _ in range(400):
                reporter.emit("loading_model")
            return successful_output(record)

    monkeypatch.setitem(
        sys.modules, "twinforge.backends.mapanything", SimpleNamespace(MapAnythingBackend=Backend)
    )
    monkeypatch.setitem(
        sys.modules,
        "twinforge.reconstruction.orchestrator",
        SimpleNamespace(ReconstructionOrchestrator=Engine),
    )
    assert run_worker(path, record["nonce"]) == 0
    assert initialized == [
        (
            record["config"]["backend"]["checkpoint"],
            record["config"]["backend"]["checkpoint_revision"],
        )
    ]
    receipt = json.loads(path.with_name("receipt.json").read_text())
    assert receipt["state"] == "complete" and receipt["nonce"] == record["nonce"]
    events = json.loads(path.with_name("progress.json").read_text())["events"]
    assert len(events) == 128 and events[-1]["sequence"] == 400
    Path(record["input"]["path"]).write_bytes(b"changed")
    assert run_worker(path, record["nonce"]) == 1
    receipt = json.loads(path.with_name("receipt.json").read_text())
    assert receipt["state"] == "failed" and receipt["stage"] == "checking_input"
    assert path.with_name("failure.log").stat().st_size > 0


def test_publication_metadata_failure_never_leaves_failed_run_default(jobs, monkeypatch):
    write = jobs._write

    def fail_ready_once(record):
        if record["state"] == "ready":
            raise OSError("Synthetic metadata failure")
        return write(record)

    monkeypatch.setattr(jobs, "_write", fail_ready_once)
    job = submit(jobs)
    assert wait_for(jobs, job["job_id"], {"failed"})
    scene = jobs.library.get(job["scene_id"])
    assert scene["default_run_id"] is None and scene["versions"] == []
    with pytest.raises(ValueError, match="ready"):
        jobs.library.run(job["scene_id"], job["run_id"])


def test_restart_rolls_back_uncommitted_publication_preserving_prior_version(jobs, monkeypatch):
    first = submit(jobs)
    assert wait_for(jobs, first["job_id"], {"ready", "failed"})["state"] == "ready"
    before = jobs.library.get(first["scene_id"])
    monkeypatch.setattr(jobs, "_drain", lambda: None)
    second = jobs.create(first["scene_id"], "second")
    jobs._thread.join()
    record = jobs._read(second["job_id"])
    output = successful_output(record)
    result = validate_output(output, record)
    record.update(
        state="validating_output",
        publication_previous={
            key: before.get(key)
            for key in ("default_run_id", "default_session_id", "default_version_id", "status")
        },
    )
    atomic_json(jobs._paths[second["job_id"]], record)
    jobs.library.publish_job(record, result)
    restarted = JobManager(jobs.library, jobs.readiness)
    assert restarted.get(second["job_id"])["state"] == "interrupted"
    after = jobs.library.get(first["scene_id"])
    assert after["default_run_id"] == first["run_id"] and after["versions"] == before["versions"]
    restarted.close()


@pytest.mark.parametrize("invalid", ["count", "mapping", "finite", "camera", "scale", "pixels"])
def test_integrity_rejects_bad_counts_and_missing_native_mapping(jobs, monkeypatch, invalid):
    monkeypatch.setattr(jobs, "_drain", lambda: None)
    job = submit(jobs)
    record = jobs._read(job["job_id"])
    output = successful_output(record, invalid=invalid)
    with pytest.raises((ValueError, SceneReadError)):
        validate_output(output, record)


def test_application_import_does_not_require_pillow_or_neural_stack():
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            """
import importlib.abc
import sys
class NoNeuralExtras(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split(".")[0] in {"PIL", "torch", "mapanything", "uniception"}:
            raise ImportError("Optional dependency deliberately unavailable: " + fullname)
sys.meta_path.insert(0, NoNeuralExtras())
import twinforge.application.server
import tests.job_support
print("application import succeeded")
""",
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    assert result.stdout.strip() == "application import succeeded"


def installed_torch_hub_source():
    try:
        distribution = importlib.metadata.distribution("torch")
        return distribution.locate_file("torch/hub.py").read_text()
    except (importlib.metadata.PackageNotFoundError, OSError):
        return None


def test_installed_torch_source_lookup_is_optional_without_importing_torch(monkeypatch):
    def absent(name):
        raise importlib.metadata.PackageNotFoundError(name)

    monkeypatch.setattr(importlib.metadata, "distribution", absent)
    assert installed_torch_hub_source() is None


def test_offline_installed_torch_branch_fallback_never_resolves_or_connects(tmp_path, monkeypatch):
    # Execute the installed implementation with dependency doubles; do not import/load Torch.
    source = installed_torch_hub_source()
    if source is None:
        pytest.skip(
            "Installed Torch source unavailable; worker offline dependency-double test still runs"
        )
    module = ast.parse(source)
    function = next(
        item
        for item in module.body
        if isinstance(item, ast.FunctionDef) and item.name == "_parse_repo_info"
    )
    cache = tmp_path / "hub"
    (cache / "facebookresearch_dinov2_main").mkdir(parents=True)
    environment = {
        "os": os,
        "urlopen": urlopen,
        "HTTPError": HTTPError,
        "URLError": URLError,
        "get_dir": lambda: str(cache),
    }
    exec(  # noqa: S102 - selected installed Torch function with dependency doubles
        compile(ast.Module(body=[function], type_ignores=[]), "installed-torch-hub", "exec"),
        environment,
    )
    calls = []
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **kw: calls.append("dns"))
    monkeypatch.setattr(socket.socket, "connect", lambda *a, **kw: calls.append("connect"))
    with offline_network():
        assert environment["_parse_repo_info"]("facebookresearch/dinov2") == (
            "facebookresearch",
            "dinov2",
            "main",
        )
        with socket.socket(socket.AF_INET) as stream, pytest.raises(OSError, match="offline"):
            stream.connect(("127.0.0.1", 1))
    assert calls == []
    assert socket.getaddrinfo("example.test", 443) is None  # original double restored
    assert calls == ["dns"]
