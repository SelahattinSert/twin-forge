import json
from dataclasses import replace

import cv2
import numpy as np
import pytest
from test_fake_backend_pipeline import FakeBackend

from twinforge.backends.base import DeviceMemory
from twinforge.config import KeyframeConfig, MemoryConfig, OutputConfig, TwinForgeConfig
from twinforge.core.types import FrameObservation, VideoMetadata
from twinforge.exceptions import OutOfMemoryReconstructionError, ReconstructionFailedError
from twinforge.reconstruction.orchestrator import ReconstructionOrchestrator


class LimitedBackend(FakeBackend):
    def __init__(self, capacity=4, error=OutOfMemoryReconstructionError):
        self.capacity, self.error = capacity, error
        self.counts = []
        self.closed = 0
        self.prepared = 0

    def prepare(self, context):
        self.prepared += 1

    def memory_info(self):
        return DeviceMemory("cuda:0", 800 * 1024**2, 6 * 1024**3)

    def close(self):
        self.closed += 1

    def reconstruct(self, frames, context):
        self.counts.append(len(frames))
        if len(frames) > self.capacity:
            raise self.error("controlled test failure")
        return super().reconstruct(frames, context)


def make_run(tmp_path, backend, memory):
    frames = []
    for i in range(8):
        path = tmp_path / f"view{i}.jpg"
        cv2.imwrite(
            str(path), np.random.default_rng(i).integers(0, 255, (64, 80, 3), dtype=np.uint8)
        )
        frames.append(FrameObservation(i + 1, i * 30, float(i), str(path), 80, 64, 1, 1, 1, None))
    config = TwinForgeConfig(
        memory=memory,
        keyframes=KeyframeConfig(minimum_keyframes=3),
        output=OutputConfig(root=tmp_path / "out"),
    )
    runner = ReconstructionOrchestrator(backend, config)
    runner.ingestor.inspect = lambda _: VideoMetadata(
        str(tmp_path / "room.mp4"), "mp4", "h264", 80, 64, 30, 8, 0, 240, 80, 64
    )
    runner.ingestor.decode_candidates = lambda *_: list(range(8))

    def select(_candidates, _directory):
        runner.selector.stats.candidate_count = 8
        return frames

    runner.selector.select = select
    return runner


def test_oom_retry_halves_across_timeline_and_records_provenance(tmp_path):
    backend = LimitedBackend()
    runner = make_run(tmp_path, backend, MemoryConfig(auto_budget=False))
    result = runner.run(tmp_path / "room.mp4")
    run = json.loads((result / "run.json").read_text())
    manifest = json.loads((result / "keyframes.json").read_text())
    cameras = json.loads((result / "cameras.json").read_text())["cameras"]
    assert backend.counts == [8, 4]
    assert backend.prepared == backend.closed == 2
    assert [frame["timestamp_seconds"] for frame in manifest["frames"]] == [0, 2, 5, 7]
    assert {camera["frame_id"] for camera in cameras} == {
        frame["frame_id"] for frame in manifest["frames"]
    }
    assert run["memory_adjustment"]["requested_keyframes"] == 8
    assert run["memory_adjustment"]["used_keyframes"] == 4
    assert run["memory_adjustment"]["reason"] == "cuda_oom"
    assert [attempt["outcome"] for attempt in run["reconstruction_attempts"]] == [
        "cuda_oom",
        "success",
    ]


@pytest.mark.parametrize(
    "memory,capacity,error,counts",
    [
        (MemoryConfig(auto_budget=False), 0, OutOfMemoryReconstructionError, [8, 4]),
        (
            MemoryConfig(auto_budget=False, maximum_oom_retries=0),
            4,
            OutOfMemoryReconstructionError,
            [8],
        ),
        (MemoryConfig(auto_budget=False), 4, ReconstructionFailedError, [8]),
    ],
)
def test_failed_attempts_do_not_fake_scene_or_retry_other_errors(
    tmp_path, memory, capacity, error, counts
):
    backend = LimitedBackend(capacity, error)
    runner = make_run(tmp_path, backend, memory)
    with pytest.raises(error):
        runner.run(tmp_path / "room.mp4")
    assert backend.counts == counts
    assert backend.closed == len(counts)
    run_dir = tmp_path / "out" / "room"
    assert not (run_dir / "scene.json").exists()
    run = json.loads((run_dir / "run.json").read_text())
    assert run["status"] == "failed"
    assert len(run["reconstruction_attempts"]) == len(counts)


def test_auto_budget_applies_before_first_attempt(tmp_path):
    backend = LimitedBackend()
    runner = make_run(tmp_path, backend, MemoryConfig())
    output = runner.run(tmp_path / "room.mp4")
    assert backend.counts == [3]
    run = json.loads((output / "run.json").read_text())
    assert run["memory_adjustment"]["reason"] == "memory_budget"


def test_export_failure_preserves_successful_inference_attempts(tmp_path, monkeypatch):
    backend = LimitedBackend()
    runner = make_run(tmp_path, backend, MemoryConfig())

    def broken_export(*_):
        raise OSError("controlled disk error")

    monkeypatch.setattr("twinforge.reconstruction.orchestrator.write_ply", broken_export)
    from twinforge.exceptions import ExportError

    with pytest.raises(ExportError, match="export"):
        runner.run(tmp_path / "room.mp4")
    run = json.loads((tmp_path / "out/room/run.json").read_text())
    assert run["status"] == "failed"
    assert run["failure"]["stage"] == "export"
    assert run["reconstruction_attempts"][0]["outcome"] == "success"
    assert run["memory_adjustment"]["used_keyframes"] == 3


def test_cpu_oom_is_not_retried(tmp_path):
    backend = LimitedBackend(capacity=0)
    backend.memory_info = lambda: DeviceMemory("cpu")
    runner = make_run(tmp_path, backend, MemoryConfig(auto_budget=False))
    with pytest.raises(OutOfMemoryReconstructionError):
        runner.run(tmp_path / "room.mp4")
    assert backend.counts == [8]


def test_retry_count_is_bounded_independently_of_minimum(tmp_path):
    backend = LimitedBackend(capacity=0)
    runner = make_run(tmp_path, backend, MemoryConfig(auto_budget=False, maximum_oom_retries=1))
    runner.config = replace(runner.config, keyframes=KeyframeConfig(minimum_keyframes=1))
    with pytest.raises(OutOfMemoryReconstructionError):
        runner.run(tmp_path / "room.mp4")
    assert backend.counts == [8, 4]
    assert backend.prepared == backend.closed == 2


@pytest.mark.parametrize("fail_on_prepare", [1, 2])
def test_model_load_and_reload_failure_retain_prior_attempts(tmp_path, fail_on_prepare):
    from twinforge.exceptions import ModelLoadError

    backend = LimitedBackend()

    def prepare(_):
        backend.prepared += 1
        if backend.prepared == fail_on_prepare:
            raise ModelLoadError("controlled model load failure")

    backend.prepare = prepare
    runner = make_run(tmp_path, backend, MemoryConfig(auto_budget=False))
    with pytest.raises(ModelLoadError):
        runner.run(tmp_path / "room.mp4")
    assert backend.prepared == backend.closed == fail_on_prepare
    run = json.loads((tmp_path / "out/room/run.json").read_text())
    assert len(run["reconstruction_attempts"]) == fail_on_prepare - 1


@pytest.mark.parametrize(
    "capacity,expected", [(8, ReconstructionFailedError), (0, OutOfMemoryReconstructionError)]
)
def test_cleanup_failure_logs_attempts_and_preserves_primary_error(tmp_path, capacity, expected):
    backend = LimitedBackend(capacity=capacity)

    def close():
        raise RuntimeError("controlled cleanup error")

    backend.close = close
    runner = make_run(tmp_path, backend, MemoryConfig(auto_budget=False, maximum_oom_retries=0))
    with pytest.raises(expected):
        runner.run(tmp_path / "room.mp4")
    run = json.loads((tmp_path / "out/room/run.json").read_text())
    assert run["status"] == "failed"
    assert len(run["reconstruction_attempts"]) == 1
    assert run["cleanup_failure"]["type"] == "RuntimeError"
