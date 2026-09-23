"""Conservative quality report from observed reconstruction outputs."""

from __future__ import annotations

from typing import Any

from twinforge.core.types import ReconstructionResult, VideoMetadata
from twinforge.keyframes.selector import SelectionStats


def analyze_quality(
    result: ReconstructionResult,
    selection: SelectionStats,
    video: VideoMetadata,
) -> dict[str, Any]:
    selected_count = selection.selected_count or len(result.cameras)
    temporal_coverage_seconds = None
    temporal_coverage_fraction = None
    if (
        selection.selected_start_seconds is not None
        and selection.selected_end_seconds is not None
        and video.duration_seconds > 0
    ):
        temporal_coverage_seconds = max(
            0.0, selection.selected_end_seconds - selection.selected_start_seconds
        )
        temporal_coverage_fraction = min(
            1.0, temporal_coverage_seconds / video.duration_seconds
        )
    warnings: list[dict[str, str]] = []
    if selected_count < 3:
        warnings.append(
            _warning(
                "LOW_FRAME_COUNT",
                "Fewer than three views reached the backend; multi-view geometry may be weak.",
            )
        )
    if not result.confidence.available:
        warnings.append(
            _warning(
                "BACKEND_CONFIDENCE_UNAVAILABLE",
                "The backend did not return a usable confidence measure for reconstructed points.",
            )
        )
    if (
        result.points.valid_mask is not None
        and result.points.valid_mask.size
        and not result.points.valid_mask.any()
    ):
        warnings.append(
            _warning(
                "NO_VALID_PREVIEW_POINTS",
                "The backend returned raw points but marked none valid for the filtered preview.",
            )
        )
    if selection.candidate_count and selection.rejected_blur / selection.candidate_count >= 0.5:
        warnings.append(
            _warning(
                "HIGH_BLUR_RATE",
                "At least half of sampled candidate frames failed the blur threshold.",
            )
        )
    if selection.candidate_count and selection.rejected_exposure / selection.candidate_count >= 0.5:
        warnings.append(
            _warning(
                "HIGH_EXPOSURE_REJECTION_RATE",
                "At least half of sampled candidates failed the exposure threshold.",
            )
        )
    missing_camera_poses = len(result.cameras) < selected_count or any(
        camera.camera_to_world is None for camera in result.cameras
    )
    poor_temporal_coverage = (
        selected_count > 1
        and temporal_coverage_fraction is not None
        and temporal_coverage_fraction < 0.5
    )
    if missing_camera_poses or poor_temporal_coverage:
        warnings.append(
            _warning(
                "CAMERA_TRAJECTORY_INCOMPLETE",
                "Camera poses are missing or selected views cover less than half of the video timeline.",
            )
        )
    if result.scale.type in ("relative", "estimated_metric") and result.scale.confidence is None:
        warnings.append(
            _warning(
                "METRIC_SCALE_UNCERTAIN",
                "Scale is not independently calibrated; treat metric dimensions as approximate.",
            )
        )
    if selection.candidate_count and selected_count / selection.candidate_count < 0.1:
        warnings.append(
            _warning("LOW_VISUAL_DIVERSITY", "Few sampled candidates contributed selected views.")
        )
    transition_count = max(0, selected_count - 1)
    if (
        transition_count
        and selection.selected_low_overlap_transition_count / transition_count >= 0.5
    ):
        warnings.append(
            _warning(
                "INSUFFICIENT_VIDEO_OVERLAP",
                "At least half of the final selected keyframe transitions lack the configured visual overlap.",
            )
        )
    if video.fps is None:
        warnings.append(
            _warning(
                "FRAME_TIMESTAMPS_APPROXIMATE",
                "Video frame rate is unavailable; source frame indices are approximate.",
            )
        )
    reconstructed = sum(camera.intrinsics is not None for camera in result.cameras)
    if result.points.source_frame_id is not None and result.points.source_frame_id.size:
        source_ids = result.points.source_frame_id
        if result.points.valid_mask is not None:
            source_ids = source_ids[result.points.valid_mask]
        reconstructed_views = len(set(source_ids.tolist()))
    else:
        reconstructed_views = 0
    return {
        "status": "complete" if len(result.points.xyz) else "incomplete",
        "candidate_frame_count": selection.candidate_count,
        "selected_keyframe_count": selected_count,
        "selected_timeline_start_seconds": selection.selected_start_seconds,
        "selected_timeline_end_seconds": selection.selected_end_seconds,
        "selected_temporal_coverage_seconds": temporal_coverage_seconds,
        "selected_temporal_coverage_fraction": temporal_coverage_fraction,
        "selected_low_overlap_transition_count": selection.selected_low_overlap_transition_count,
        "rejected_blur_count": selection.rejected_blur,
        "rejected_exposure_count": selection.rejected_exposure,
        "rejected_duplicate_count": selection.rejected_duplicate,
        "rejected_temporal_count": selection.rejected_temporal,
        "rejected_overlap_count": selection.rejected_overlap,
        "reconstructed_camera_count": sum(
            camera.camera_to_world is not None for camera in result.cameras
        ),
        "camera_intrinsics_count": reconstructed,
        "frames_with_valid_geometry": reconstructed_views,
        "percentage_frames_successfully_reconstructed": (
            100.0 * reconstructed_views / selected_count if selected_count else 0.0
        ),
        "point_count": len(result.points.xyz),
        "depth_map_count": len(result.depth_maps),
        "valid_point_count": (
            int(result.points.valid_mask.sum())
            if result.points.valid_mask is not None
            else len(result.points.xyz)
        ),
        "confidence": result.confidence.__dict__,
        "scale": result.scale.__dict__,
        "warnings": warnings,
    }


def _warning(code: str, message: str) -> dict[str, str]:
    return {"code": code, "message": message}
