from __future__ import annotations

import json

import cv2
import numpy as np
import pytest

from twinforge.backends.base import ReconstructionBackend, ReconstructionContext
from twinforge.config import (
    BackendConfig,
    KeyframeConfig,
    OutputConfig,
    TwinForgeConfig,
    VideoConfig,
)
from twinforge.core.types import (
    Camera,
    ConfidenceSummary,
    DepthMap,
    PointCloud,
    ReconstructionResult,
    ScaleEstimate,
    VideoMetadata,
)
from twinforge.exceptions import ExportError
from twinforge.ingest.video import CandidateFrame, VideoIngestor
from twinforge.reconstruction.orchestrator import ReconstructionOrchestrator


class FakeBackend(ReconstructionBackend):
    def reconstruct(self, frames, context: ReconstructionContext) -> ReconstructionResult:
        return ReconstructionResult(
            points=PointCloud(
                xyz=np.asarray([[0, 0, 0], [1, 2, 3]], dtype=np.float32),
                rgb=np.asarray([[20, 30, 40], [50, 60, 70]], dtype=np.uint8),
                confidence=np.asarray([0.75, 0.9], dtype=np.float32),
                source_frame_id=np.asarray([1, frames[-1].frame_id], dtype=np.uint32),
            ),
            cameras=[
                Camera(
                    frame.frame_id,
                    frame.timestamp_seconds,
                    None,
                    np.eye(4).tolist(),
                )
                for frame in frames
            ],
            scale=ScaleEstimate("relative", None, None, None),
            confidence=ConfidenceSummary(True, 0.825, 0.825, 0.765, 0.885, 2, "fake fixture"),
            backend="fake",
            backend_version="test",
            checkpoint=None,
            depth_maps=[DepthMap(frames[0].frame_id, frames[0].timestamp_seconds, np.ones((2, 2), dtype=np.float32))],
        )


def test_existing_run_directory_is_not_overwritten(tmp_path):
    run_dir = tmp_path / "output" / "room"
    run_dir.mkdir(parents=True)
    marker = run_dir / "scene.json"
    marker.write_text("previous reconstruction", encoding="utf-8")
    config = TwinForgeConfig(output=OutputConfig(root=tmp_path / "output"))

    with pytest.raises(ExportError, match="already contains data"):
        ReconstructionOrchestrator(FakeBackend(), config).run(tmp_path / "room.mp4")

    assert marker.read_text(encoding="utf-8") == "previous reconstruction"


def test_fake_backend_produces_traceable_run_artifacts(tmp_path, monkeypatch):
    video_path = tmp_path / "walkthrough.mp4"
    video_path.touch()
    metadata = VideoMetadata(
        path=str(video_path),
        container="mov,mp4",
        codec="h264",
        width=320,
        height=240,
        fps=30.0,
        duration_seconds=3.0,
        rotation_degrees=0,
        frame_count=90,
        display_width=320,
        display_height=240,
    )
    rng = np.random.default_rng(10)
    candidates = []
    candidate_dir = tmp_path / "candidate-images"
    candidate_dir.mkdir()
    base = rng.integers(0, 256, (240, 320, 3), dtype=np.uint8)
    for index in range(3):
        image = np.roll(base, index * 12, axis=1)
        path = candidate_dir / f"candidate_{index}.jpg"
        assert cv2.imwrite(str(path), image)
        candidates.append(CandidateFrame(index * 30, float(index), path, image))
    monkeypatch.setattr(VideoIngestor, "inspect", lambda _self, _path: metadata)
    monkeypatch.setattr(VideoIngestor, "decode_candidates", lambda *_args: candidates)
    config = TwinForgeConfig(
        video=VideoConfig(candidate_interval_seconds=1),
        keyframes=KeyframeConfig(
            minimum_separation_seconds=0.5,
            maximum_keyframes=3,
            minimum_keyframes=2,
            minimum_feature_overlap=0,
            minimum_novelty=0,
        ),
        backend=BackendConfig(device="cpu", maximum_keyframes=3),
        output=OutputConfig(root=tmp_path / "output"),
    )
    result_dir = ReconstructionOrchestrator(FakeBackend(), config).run(video_path)
    assert {path.name for path in result_dir.iterdir()} >= {
        "scene.json",
        "run.json",
        "quality.json",
        "cameras.json",
        "keyframes.json",
        "pointcloud.ply",
        "depthmaps.npz",
        "preview.glb",
        "frames",
    }
    scene = json.loads((result_dir / "scene.json").read_text())
    run = json.loads((result_dir / "run.json").read_text())
    quality = json.loads((result_dir / "quality.json").read_text())
    assert scene["geometry"]["point_count"] == 2
    assert scene["confidence"]["available"] is True
    assert scene["geometry"]["depth_maps"] == "depthmaps.npz"
    with np.load(result_dir / "depthmaps.npz") as depth_archive:
        assert depth_archive["depth_z_0001"].shape == (2, 2)
    assert run["selected_keyframes"] >= 2
    assert "model_loading" in run["timings_seconds"]
    assert quality["percentage_frames_successfully_reconstructed"] == (
        100.0 * 2 / run["selected_keyframes"]
    )
    assert quality["selected_temporal_coverage_fraction"] == 2 / 3
    assert "CAMERA_TRAJECTORY_INCOMPLETE" not in {
        warning["code"] for warning in quality["warnings"]
    }
    keyframes = json.loads((result_dir / "keyframes.json").read_text())
    assert "source_frame_index_note" in keyframes
    assert all(frame["image_path"].startswith("frames/") for frame in keyframes["frames"])
