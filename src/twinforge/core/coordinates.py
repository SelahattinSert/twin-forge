"""Coordinate transforms for the canonical right-handed Z-up world frame."""

from __future__ import annotations

import numpy as np

# MapAnything returns OpenCV world coordinates: +X right, +Y down, +Z forward.
# This proper rotation maps those world axes to TwinForge: +X right, +Y forward, +Z up.
OPENCV_WORLD_TO_TWINFORGE = np.asarray(
    [[1.0, 0.0, 0.0, 0.0], [0.0, 0.0, 1.0, 0.0], [0.0, -1.0, 0.0, 0.0], [0, 0, 0, 1]],
    dtype=np.float64,
)


def convert_points_opencv_world_to_twinforge(points: np.ndarray) -> np.ndarray:
    if points.shape[-1] != 3:
        raise ValueError("points must have a final dimension of 3")
    return np.asarray(points) @ OPENCV_WORLD_TO_TWINFORGE[:3, :3].T


def convert_pose_opencv_world_to_twinforge(camera_to_world: np.ndarray) -> np.ndarray:
    pose = np.asarray(camera_to_world)
    if pose.shape != (4, 4):
        raise ValueError("camera_to_world must have shape (4, 4)")
    return OPENCV_WORLD_TO_TWINFORGE @ pose
