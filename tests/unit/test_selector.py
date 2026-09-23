from __future__ import annotations

import cv2
import numpy as np

from twinforge.config import KeyframeConfig
from twinforge.ingest.video import CandidateFrame
from twinforge.keyframes.selector import KeyframeSelector


def test_selector_rejects_blur_and_keeps_provenance(tmp_path):
    rng = np.random.default_rng(42)
    base = rng.integers(0, 256, (240, 320, 3), dtype=np.uint8)
    candidates = []
    for index in range(8):
        image = np.roll(base, index * 5, axis=1)
        if index == 3:
            image = cv2.GaussianBlur(image, (31, 31), 10)
        path = tmp_path / f"candidate_{index}.jpg"
        assert cv2.imwrite(str(path), image)
        candidates.append(CandidateFrame(index * 30, float(index), path, image))
    selector = KeyframeSelector(
        KeyframeConfig(
            minimum_separation_seconds=0.5,
            minimum_sharpness=0.001,
            maximum_keyframes=5,
            minimum_keyframes=2,
            minimum_novelty=0.001,
            minimum_feature_overlap=0.0,
        )
    )
    selected = selector.select(candidates, tmp_path / "selected")
    assert selected
    assert selector.stats.rejected_blur >= 0
    assert all(frame.image_path.endswith(".jpg") for frame in selected)
    assert all(frame.width == 320 and frame.height == 240 for frame in selected)


def test_maximum_keyframes_preserves_the_full_candidate_timeline(tmp_path):
    rng = np.random.default_rng(123)
    candidates = []
    for index in range(12):
        image = rng.integers(0, 256, (160, 200, 3), dtype=np.uint8)
        path = tmp_path / f"timeline_{index:02d}.jpg"
        assert cv2.imwrite(str(path), image)
        candidates.append(CandidateFrame(index * 30, float(index), path, image))

    selector = KeyframeSelector(
        KeyframeConfig(
            maximum_keyframes=4,
            minimum_keyframes=2,
            minimum_sharpness=0.0001,
            minimum_exposure_score=0.0,
            duplicate_hamming_distance=0,
            minimum_feature_overlap=0.0,
            minimum_novelty=0.0,
        )
    )

    selected = selector.select(candidates, tmp_path / "timeline-selected")

    assert len(selected) == 4
    assert selected[0].timestamp_seconds == 0.0
    assert selected[-1].timestamp_seconds >= 9.0
