"""Bounded local transfer, durable receipts, and lightweight setup checks."""

import io
import json

import pytest

from twinforge.application.config import ApplicationConfig
from twinforge.application.library import LibraryStore


@pytest.fixture
def uploads(tmp_path):
    from twinforge.application.uploads import UploadStore

    with LibraryStore(
        ApplicationConfig(
            library=tmp_path / "library",
            upload_limit=1024,
            disk_reserve_bytes=1,
            upload_quota_bytes=2048,
        )
    ) as library:
        yield UploadStore(library)


def test_receipts_use_generated_paths_and_distinct_unicode_names(uploads):
    first = uploads.create("../../Reference 🧭.MP4", 4)
    second = uploads.create("../../Reference 🧭.MP4", 4)
    assert first["upload_id"] != second["upload_id"]
    assert first["client_name"] == "../../Reference 🧭.MP4"
    uploads.transfer(first["upload_id"], io.BytesIO(b"data"), 4)
    receipt = uploads.get(first["upload_id"])
    assert receipt["state"] == "transferred" and receipt["received_bytes"] == 4
    assert len(receipt["sha256"]) == 64
    assert not (uploads.library.root / "Reference 🧭.MP4").exists()
    assert not uploads.library.list()["scenes"]


@pytest.mark.parametrize(
    "name,size,code",
    [
        ("a.txt", 1, "invalid_extension"),
        ("a.mp4", 0, "invalid_size"),
        ("a.mp4", 1025, "size_limit"),
        ("a.mp4", True, "invalid_size"),
    ],
)
def test_declaration_rejected_before_read(uploads, name, size, code):
    from twinforge.application.uploads import UploadError

    with pytest.raises(UploadError) as error:
        uploads.create(name, size)
    assert error.value.code == code


def test_short_and_long_transfers_never_become_ready(uploads):
    from twinforge.application.uploads import UploadError

    first = uploads.create("a.mov", 8)
    with pytest.raises(UploadError, match="incomplete_transfer"):
        uploads.transfer(first["upload_id"], io.BytesIO(b"abc"), 8)
    assert uploads.get(first["upload_id"])["state"] == "failed"
    with pytest.raises(UploadError, match="incomplete_transfer"):
        uploads.complete(first["upload_id"], "Scene")
    second = uploads.create("a.mov", 8)
    with pytest.raises(UploadError, match="length_mismatch"):
        uploads.transfer(second["upload_id"], io.BytesIO(b"abcdefghi"), 9)
    assert not uploads.library.list()["scenes"]


def test_reservations_bound_concurrent_pending_bytes(uploads):
    from twinforge.application.uploads import UploadError

    uploads.create("a.mp4", 1024)
    uploads.create("b.mp4", 1024)
    with pytest.raises(UploadError, match="upload_quota"):
        uploads.create("c.mp4", 1)


def test_disk_reserve_checked_before_and_during_transfer(uploads, monkeypatch):
    from twinforge.application.uploads import UploadError

    receipt = uploads.create("a.mp4", 10)
    monkeypatch.setattr(
        "twinforge.application.uploads.shutil.disk_usage",
        lambda _: type("Usage", (), {"free": 0})(),
    )
    with pytest.raises(UploadError, match="insufficient_storage"):
        uploads.create("b.mp4", 10)
    with pytest.raises(UploadError, match="insufficient_storage"):
        uploads.transfer(receipt["upload_id"], io.BytesIO(b"x" * 10), 10)
    assert uploads.get(receipt["upload_id"])["state"] == "failed"


def test_disk_full_write_has_actionable_storage_code(uploads, monkeypatch):
    import errno
    from pathlib import Path

    from twinforge.application.uploads import UploadError

    receipt = uploads.create("a.mp4", 10)
    original_open = Path.open

    class FullDisk:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def write(self, data):
            raise OSError(errno.ENOSPC, "Private disk path")

    monkeypatch.setattr(
        Path,
        "open",
        lambda path, *args, **kwargs: (
            FullDisk() if path.name == "original.partial" else original_open(path, *args, **kwargs)
        ),
    )
    with pytest.raises(UploadError, match="insufficient_storage"):
        uploads.transfer(receipt["upload_id"], io.BytesIO(b"x" * 10), 10)
    assert uploads.get(receipt["upload_id"])["error_code"] == "insufficient_storage"


def test_incomplete_receipts_remain_nonrunnable_after_restart(uploads):
    from twinforge.application.uploads import UploadStore

    receipt = uploads.create("a.mp4", 10)
    restarted = UploadStore(uploads.library)
    assert restarted.get(receipt["upload_id"])["state"] == "created"
    assert not restarted.library.list()["scenes"]


@pytest.mark.parametrize("state", ["created", "transferred", "failed"])
def test_incomplete_listing_survives_restart_and_discard_recovers_admission(tmp_path, state):
    from twinforge.application.uploads import UploadError, UploadStore

    config = ApplicationConfig(
        library=tmp_path / "library", pending_upload_limit=1, disk_reserve_bytes=1
    )
    with LibraryStore(config) as library:
        store = UploadStore(library)
        receipt = store.create("Recovery.mp4", 4)
        if state == "transferred":
            store.transfer(receipt["upload_id"], io.BytesIO(b"data"), 4)
        elif state == "failed":
            with pytest.raises(UploadError):
                store.transfer(receipt["upload_id"], io.BytesIO(b"d"), 4)
        if state != "failed":
            with pytest.raises(UploadError, match="upload_quota"):
                store.create("Blocked.mp4", 4)
    with LibraryStore(config) as library:
        restarted = UploadStore(library)
        page = restarted.list()
        assert len(page["uploads"]) == 1
        item = page["uploads"][0]
        assert item["upload_id"] == receipt["upload_id"] and item["state"] == state
        assert str(tmp_path) not in json.dumps(page)
        restarted.discard(item["upload_id"])
        assert restarted.list()["uploads"] == []
        assert restarted.create("Restart.mp4", 4)["state"] == "created"
        assert not (restarted._directory(item["upload_id"]) / "original.partial").exists()


def test_upload_listing_is_bounded_and_pages_past_retained_receipts(uploads):
    receipts = [uploads.create("Page.mp4", 1) for _ in range(4)]
    uploads.discard(receipts[0]["upload_id"])
    cursor, discovered = None, []
    while True:
        page = uploads.list(limit=2, after=cursor)
        assert len(page["uploads"]) <= 2
        discovered.extend(item["upload_id"] for item in page["uploads"])
        cursor = page["next_cursor"]
        if cursor is None:
            break
    assert set(discovered) == {item["upload_id"] for item in receipts[1:]}
    assert len(discovered) == len(set(discovered))


def test_upload_listing_never_returns_invalid_directory_cursor(uploads):
    from twinforge.application.library import atomic_json

    for name in ("upload_bad", "upload_broken"):
        atomic_json(uploads.root / name / "receipt.json", {"private_path": "/private/video"})
    receipt = uploads.create("Available.mp4", 1)
    page = uploads.list(limit=1)
    assert page["next_cursor"] is None
    assert [item["upload_id"] for item in page["uploads"]] == [receipt["upload_id"]]


@pytest.mark.parametrize("decoder_available", [True, False])
def test_readiness_checks_caches_without_importing_heavy_packages(
    tmp_path, monkeypatch, decoder_available
):
    from twinforge.application.readiness import check_readiness

    config = ApplicationConfig(
        library=tmp_path / "library",
        hf_home=tmp_path / "hf",
        torch_home=tmp_path / "torch",
        disk_reserve_bytes=1,
    )
    config.library.mkdir()
    monkeypatch.setattr("twinforge.application.readiness.package_available", lambda _: True)
    monkeypatch.setattr(
        "twinforge.application.readiness.shutil.which",
        lambda name: f"/test/bin/{name}" if decoder_available else None,
    )
    value = check_readiness(config, {"cpu": True, "cuda": False})
    assert value["viewing_available"] and not value["processing_ready"]
    assert value["checkpoint"]["state"] == "missing"
    snapshot = (
        config.hf_cache
        / "models--facebook--map-anything-apache/snapshots"
        / config.checkpoint_revision
    )
    snapshot.mkdir(parents=True)
    (snapshot / "config.json").write_text(json.dumps({"encoder_config": {"encoder_str": "dinov2"}}))
    (snapshot / "model.safetensors").write_bytes(b"cached-test-weights")
    repo = config.torch_home / "hub/facebookresearch_dinov2_main"
    repo.mkdir(parents=True)
    (repo / "hubconf.py").write_text("# cached repository")
    value = check_readiness(config, {"cpu": True, "cuda": False})
    assert value["checkpoint"]["state"] == "cached"
    assert value["torch_repository"]["state"] == "cached"
    assert value["profiles"]["standard"]["device"] == "cpu"
    assert value["profiles"]["standard"]["maximum_keyframes"] == 32
    assert value["profiles"]["standard"]["maximum_oom_retries"] == 0
    assert value["processing_ready"] is decoder_available
    assert value["decoder"] == {"ffmpeg": decoder_available, "ffprobe": decoder_available}
    assert [reason["code"] for reason in value["reasons"]] == (
        [] if decoder_available else ["missing_decoder"]
    )


def test_explicit_cache_environment_and_offline_worker_contract(tmp_path, monkeypatch):
    monkeypatch.setenv("HF_HOME", str(tmp_path / "hf"))
    monkeypatch.setenv("HF_HUB_CACHE", str(tmp_path / "hub"))
    monkeypatch.setenv("TORCH_HOME", str(tmp_path / "torch"))
    config = ApplicationConfig()
    assert config.hf_home == tmp_path / "hf"
    assert config.hf_cache == tmp_path / "hub"
    assert config.torch_home == tmp_path / "torch"
    env = config.worker_environment()
    assert env["HF_HUB_OFFLINE"] == "1" and env["TORCH_HOME"] == str(config.torch_home)


def test_probe_output_and_runtime_are_bounded(tmp_path):
    import subprocess
    import sys

    from twinforge.application.inspection import bounded_command

    with pytest.raises(subprocess.SubprocessError):
        bounded_command([sys.executable, "-c", "print('x' * 200000)"], timeout=5, output_limit=1024)
    with pytest.raises(subprocess.SubprocessError):
        bounded_command(
            [sys.executable, "-c", "import time; time.sleep(2)"], timeout=0.05, output_limit=1024
        )


def test_nonfinite_video_duration_is_rejected_before_preview(tmp_path, monkeypatch):
    import subprocess

    from twinforge.application.inspection import inspect_video
    from twinforge.application.uploads import UploadError

    original = tmp_path / "original.mp4"
    original.write_bytes(b"synthetic metadata probe")
    metadata = {
        "format": {"format_name": "mov,mp4", "duration": "nan"},
        "streams": [{"width": 64, "height": 48, "avg_frame_rate": "2/1"}],
    }
    monkeypatch.setattr("twinforge.application.inspection.shutil.which", lambda _: "/decoder")
    monkeypatch.setattr(
        "twinforge.application.inspection.bounded_command",
        lambda command, **kwargs: subprocess.CompletedProcess(command, 0, json.dumps(metadata), ""),
    )
    with pytest.raises(UploadError, match="invalid_video"):
        inspect_video(original, tmp_path, ApplicationConfig(library=tmp_path, disk_reserve_bytes=1))


def test_prepare_is_explicit_single_and_failure_is_durable(tmp_path, monkeypatch):
    from twinforge.application.readiness import ReadinessManager

    monkeypatch.setattr("twinforge.application.readiness.package_available", lambda _: False)
    config = ApplicationConfig(library=tmp_path / "library", disk_reserve_bytes=1)
    (config.library / "runtime").mkdir(parents=True)
    manager = ReadinessManager(config)
    assert manager.status()["preparation"]["state"] == "idle"
    assert manager._process is None
    monkeypatch.setattr("twinforge.application.readiness.package_available", lambda _: True)
    started = []

    class Child:
        pid = 987654321
        returncode = None

        def __init__(self, args, **kwargs):
            started.append((args, kwargs))

        def poll(self):
            return self.returncode

        def wait(self, timeout=None):
            return self.returncode

    monkeypatch.setattr("twinforge.application.readiness.subprocess.Popen", Child)
    monkeypatch.setattr("twinforge.application.readiness.threading.Thread.start", lambda _: None)
    monkeypatch.setattr(
        "twinforge.application.readiness.process_start_identity", lambda _: "test-start"
    )
    manager.prepare()
    from twinforge.application.uploads import UploadError

    with pytest.raises(UploadError, match="setup_busy"):
        manager.prepare()
    assert len(started) == 1 and started[0][1]["env"]["HF_HUB_OFFLINE"] == "0"
    assert manager.status()["preparation"]["state"] == "preparing"
    manager._process.returncode = 1
    monkeypatch.setattr(manager, "_check_devices", lambda: None)
    manager._supervise()
    assert manager.status()["preparation"]["state"] == "failed"
    assert manager._process is None


def test_previous_live_setup_owner_blocks_duplicate_prepare(tmp_path, monkeypatch):
    from twinforge.application.library import atomic_json
    from twinforge.application.readiness import ReadinessManager
    from twinforge.application.uploads import UploadError

    monkeypatch.setattr("twinforge.application.readiness.package_available", lambda _: False)
    monkeypatch.setattr(
        "twinforge.application.readiness.process_start_identity", lambda _: "same-start"
    )
    config = ApplicationConfig(library=tmp_path / "library", disk_reserve_bytes=1)
    runtime = config.library / "runtime"
    runtime.mkdir(parents=True)
    atomic_json(
        runtime / "model-setup-owner.json",
        {"pid": 123, "start_identity": "same-start", "instance_nonce": "previous"},
    )
    atomic_json(
        runtime / "model-setup.json",
        {"state": "downloading", "message": "Preparing cached artifacts", "download_bytes": 42},
    )
    manager = ReadinessManager(config)
    assert manager.status()["preparation"]["state"] == "downloading"
    with pytest.raises(UploadError, match="setup_busy"):
        manager.prepare()
    manager.close()


def test_setup_shutdown_terminates_owned_group_and_reaps(tmp_path, monkeypatch):
    from twinforge.application.readiness import ReadinessManager

    monkeypatch.setattr("twinforge.application.readiness.package_available", lambda _: False)
    config = ApplicationConfig(library=tmp_path / "library", disk_reserve_bytes=1)
    (config.library / "runtime").mkdir(parents=True)
    manager = ReadinessManager(config)
    killed, waited = [], []

    class Child:
        pid = 987654321
        returncode = None

        def poll(self):
            return self.returncode

        def wait(self, timeout=None):
            waited.append(timeout)
            self.returncode = -15
            return self.returncode

    manager._process = Child()
    manager._stop.set()
    monkeypatch.setattr(
        "twinforge.application.readiness.os.killpg", lambda pid, sig: killed.append((pid, sig))
    )
    manager._supervise()
    assert killed and waited and manager._process is None
    assert manager.status()["preparation"]["state"] == "failed"


def test_browser_playback_failure_preserves_decode_readiness():
    import shutil
    import subprocess

    if not shutil.which("node"):
        pytest.skip("Node required")
    script = r"""import {readFileSync} from 'node:fs';
import assert from 'node:assert/strict';
const {playbackState,reviewState}=await import('data:text/javascript;base64,'+Buffer.from(readFileSync('src/twinforge/viewer/static/upload-review.js')).toString('base64'));
const scene={status:'ready_to_start',media:{inspection:{decode_ready:true}}};
assert.equal(playbackState(true,scene.media.inspection).showStill,true);
assert.match(playbackState(true,scene.media.inspection).message,/can still be processed/);
const state=reviewState(scene,{processing_ready:true,job_launch_available:false});
assert.equal(state.inputReady,true);assert.equal(state.canStart,false);
assert.equal(reviewState({...scene,status:'source_unavailable'},{processing_ready:true,job_launch_available:true}).canStart,false);
assert.equal(reviewState(scene,{processing_ready:false,job_launch_available:true}).canStart,false);
"""
    subprocess.run(["node", "--input-type=module", "-e", script], check=True, capture_output=True)


def test_late_final_read_cannot_complete_transfer(uploads, monkeypatch):
    from dataclasses import replace

    from twinforge.application.uploads import UploadError

    uploads.config = replace(uploads.config, transfer_timeout_seconds=0.01)
    now = [0.0]
    monkeypatch.setattr("twinforge.application.uploads.time.monotonic", lambda: now[0])

    class LateRead:
        def read(self, size):
            now[0] = 0.02
            return b"data"

    receipt = uploads.create("late.mp4", 4)
    with pytest.raises(UploadError, match="transfer_failed"):
        uploads.transfer(receipt["upload_id"], LateRead(), 4)
    receipt = uploads.get(receipt["upload_id"])
    assert receipt["state"] == "failed" and receipt["sha256"] is None
    assert not uploads.library.list()["scenes"]


def test_owner_publication_failure_reaps_spawned_prepare_child(tmp_path, monkeypatch):
    import errno
    import signal

    from twinforge.application.readiness import ReadinessManager
    from twinforge.application.uploads import UploadError

    monkeypatch.setattr("twinforge.application.readiness.package_available", lambda _: False)
    config = ApplicationConfig(library=tmp_path / "library", disk_reserve_bytes=1)
    (config.library / "runtime").mkdir(parents=True)
    manager = ReadinessManager(config)
    monkeypatch.setattr("twinforge.application.readiness.package_available", lambda _: True)
    from twinforge.application import readiness

    original_atomic = readiness.atomic_json
    calls = []

    def publish(path, value):
        if path == manager.owner_path:
            raise OSError(errno.ENOSPC, "Private owner path")
        original_atomic(path, value)

    class Child:
        pid = 987654321
        returncode = None

        def __init__(self, *args, **kwargs):
            calls.append("spawn")

        def poll(self):
            return self.returncode

        def wait(self, timeout=None):
            calls.append("wait")
            self.returncode = -15
            return self.returncode

    monkeypatch.setattr(readiness, "atomic_json", publish)
    monkeypatch.setattr(readiness.subprocess, "Popen", Child)
    monkeypatch.setattr(readiness, "process_start_identity", lambda _: "start")
    monkeypatch.setattr(readiness.os, "killpg", lambda pid, sig: calls.append((pid, sig)))
    with pytest.raises(UploadError, match="model_not_prepared"):
        manager.prepare()
    assert (987654321, signal.SIGTERM) in calls and "wait" in calls
    assert manager._process is None and not manager.is_preparing()
    assert manager.status()["preparation"]["state"] == "failed"
    manager.close()


def test_close_reaps_owned_child_without_supervisor(tmp_path, monkeypatch):
    from twinforge.application.readiness import ReadinessManager

    monkeypatch.setattr("twinforge.application.readiness.package_available", lambda _: False)
    config = ApplicationConfig(library=tmp_path / "library", disk_reserve_bytes=1)
    (config.library / "runtime").mkdir(parents=True)
    manager = ReadinessManager(config)
    calls = []

    class Child:
        pid = 987654321
        returncode = None

        def poll(self):
            return self.returncode

        def wait(self, timeout=None):
            calls.append("wait")
            self.returncode = -15
            return self.returncode

    manager._process = Child()
    monkeypatch.setattr(
        "twinforge.application.readiness.os.killpg", lambda pid, sig: calls.append("kill")
    )
    manager.close()
    assert calls == ["kill", "wait"] and manager._process is None


def test_cached_checkpoint_preparation_requires_no_download_headroom(tmp_path, monkeypatch):
    import sys
    from types import SimpleNamespace

    from twinforge.application.setup_worker import prepare

    hf_cache = tmp_path / "hf"
    revision = "a" * 40
    snapshot = hf_cache / "models--facebook--map-anything-apache/snapshots" / revision
    snapshot.mkdir(parents=True)
    for name in ("config.json", "model.safetensors"):
        (snapshot / name).write_bytes(b"cached")

    # Any remote checkpoint call is a test failure; only repository preparation is needed.
    def unexpected_download(*args, **kwargs):
        pytest.fail("Cached checkpoint must not request metadata or a download")

    monkeypatch.setitem(
        sys.modules,
        "huggingface_hub",
        SimpleNamespace(HfApi=unexpected_download, hf_hub_download=unexpected_download),
    )
    monkeypatch.setattr(
        "twinforge.application.setup_worker.shutil.disk_usage",
        lambda _: SimpleNamespace(free=2 * 1024**3),
    )
    repository_calls = []
    monkeypatch.setattr(
        "twinforge.application.setup_worker._prepare_repository",
        lambda root, reserve: repository_calls.append((root, reserve)),
    )
    args = SimpleNamespace(
        hf_cache=hf_cache,
        torch_home=tmp_path / "torch",
        checkpoint="facebook/map-anything-apache",
        revision=revision,
        reserve=512 * 1024**2,
        state=tmp_path / "setup.json",
    )
    prepare(args)
    assert repository_calls == [(args.torch_home, args.reserve)]
    assert json.loads(args.state.read_text())["download_bytes"] == 0
    assert json.loads(args.state.read_text())["state"] == "complete"


def test_profile_change_submits_profile_default_device():
    import shutil
    import subprocess

    if not shutil.which("node"):
        pytest.skip("Node required")
    script = r"""import {readFileSync} from 'node:fs';
import assert from 'node:assert/strict';
const {mountUploadReview}=await import('data:text/javascript;base64,'+Buffer.from(readFileSync('src/twinforge/viewer/static/upload-review.js')).toString('base64'));
const nodes=new Map();
globalThis.document={getElementById(id){if(!nodes.has(id))nodes.set(id,{value:'',hidden:false,focus(){},pause(){}});return nodes.get(id);}};
globalThis.addEventListener=()=>{};
const readiness={processing_ready:true,backend:{installed:true},devices:{cpu:true},checkpoint:{state:'cached',cached_bytes:1},torch_repository:{state:'cached'},preparation:{state:'idle'},profiles:{standard:{device:'cpu'},quick_preview:{device:'auto'}}};
const submitted=[];
const scene={scene_id:'scene_example',name:'Test',status:'ready_to_start',media:{inspection:{duration_seconds:1,width:64,height:48,display_width:64,display_height:48,codec:'mpeg4',decode_ready:true,preprocessing:{color:{policy:'sdr'}}},review_settings:{profile:'standard',device:'cpu'}}};
const request=async(url,method,value)=>{if(method==='POST'){submitted.push(value);return scene;}return readiness;};
const view=mountUploadReview({request,refresh:async()=>{},report:()=>{}});await Promise.resolve();
view.review(scene);
nodes.get('video-profile').value='quick_preview';nodes.get('video-profile').onchange();
assert.equal(nodes.get('video-device').value,'');
await nodes.get('video-review').onsubmit({preventDefault(){}});
assert.equal(submitted[0].profile,'quick_preview');assert.equal(submitted[0].device,null);
"""
    subprocess.run(["node", "--input-type=module", "-e", script], check=True, capture_output=True)
