from __future__ import annotations

import cv2
import numpy as np

from twinforge.keyframes.quality import analysis_image, measure_sharpness


def test_sharpness_uses_same_analysis_scale_and_rejects_severe_blur():
    rng = np.random.default_rng(19)
    scene = rng.integers(25, 230, (288, 512, 3), dtype=np.uint8)
    large = cv2.resize(scene, (2048, 1152), interpolation=cv2.INTER_NEAREST)
    assert abs(measure_sharpness(scene) - measure_sharpness(large)) < 0.00001
    blurred = cv2.GaussianBlur(large, (0, 0), 32)
    assert measure_sharpness(large) > 0.0015
    assert measure_sharpness(blurred) < 0.0015


def test_analysis_image_preserves_portrait_aspect_and_does_not_upscale():
    small = np.zeros((30, 20, 3), dtype=np.uint8)
    assert analysis_image(small) is small
    assert analysis_image(np.zeros((2048, 1152, 3), dtype=np.uint8)).shape == (512, 288, 3)


from twinforge.core.types import (
    Camera,
    ConfidenceSummary,
    PointCloud,
    ReconstructionResult,
    ScaleEstimate,
    VideoMetadata,
)
from twinforge.keyframes.selector import SelectionStats
from twinforge.quality.analyzer import analyze_quality


def test_quality_report_warns_when_backend_confidence_is_unavailable():
    result = ReconstructionResult(
        points=PointCloud(np.asarray([[0, 0, 0]], dtype=np.float32)),
        cameras=[Camera(1, 0.0, None, None)],
        scale=ScaleEstimate("relative", None, None, None),
        confidence=ConfidenceSummary(available=False),
        backend="fixture",
        backend_version="test",
        checkpoint=None,
    )
    video = VideoMetadata(
        path="fixture.mp4",
        container="mp4",
        codec="h264",
        width=10,
        height=10,
        fps=1.0,
        duration_seconds=1.0,
        rotation_degrees=0,
        frame_count=1,
        display_width=10,
        display_height=10,
    )

    report = analyze_quality(result, SelectionStats(candidate_count=1), video)

    warning_codes = {warning["code"] for warning in report["warnings"]}
    assert "BACKEND_CONFIDENCE_UNAVAILABLE" in warning_codes
    assert report["scope"] == "pipeline_and_input_health"
    assert report["geometry_validation"]["status"] == "not_evaluated"


def test_quality_report_warns_when_selected_views_cover_only_a_short_video_segment():
    pose = np.eye(4).tolist()
    result = ReconstructionResult(
        points=PointCloud(np.asarray([[0, 0, 0]], dtype=np.float32)),
        cameras=[Camera(1, 3.0, None, pose), Camera(2, 4.0, None, pose)],
        scale=ScaleEstimate("estimated_metric", 1.0, None, "fixture"),
        confidence=ConfidenceSummary(available=False),
        backend="fixture",
        backend_version="test",
        checkpoint=None,
    )
    video = VideoMetadata(
        path="fixture.mp4",
        container="mp4",
        codec="h264",
        width=320,
        height=240,
        fps=30.0,
        duration_seconds=22.0,
        rotation_degrees=0,
        frame_count=660,
        display_width=320,
        display_height=240,
    )
    selection = SelectionStats(
        candidate_count=22,
        selected_count=2,
        selected_start_seconds=3.0,
        selected_end_seconds=4.0,
    )

    report = analyze_quality(result, selection, video)

    warning_codes = {warning["code"] for warning in report["warnings"]}
    assert report["selected_temporal_coverage_fraction"] == 1.0 / 22.0
    assert "CAMERA_TRAJECTORY_INCOMPLETE" in warning_codes

    result.cameras = []
    complete_timeline = SelectionStats(
        candidate_count=22,
        selected_count=2,
        selected_start_seconds=0.0,
        selected_end_seconds=21.0,
    )
    missing_poses_report = analyze_quality(result, complete_timeline, video)

    assert "CAMERA_TRAJECTORY_INCOMPLETE" in {
        warning["code"] for warning in missing_poses_report["warnings"]
    }
