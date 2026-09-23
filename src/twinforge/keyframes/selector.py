"""Quality and visual novelty based keyframe selection."""

from __future__ import annotations

import logging
import shutil
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

from twinforge.config import KeyframeConfig
from twinforge.core.types import FrameObservation
from twinforge.exceptions import NoUsableFramesError
from twinforge.ingest.video import CandidateFrame
from twinforge.keyframes.quality import (
    hamming_distance,
    measure_exposure,
    measure_sharpness,
    perceptual_hash,
)

logger = logging.getLogger(__name__)
type ScoredCandidate = tuple[
    CandidateFrame, float, float, int, list[cv2.KeyPoint], np.ndarray | None
]
type SelectedCandidate = tuple[
    CandidateFrame,
    float,
    float,
    int,
    list[cv2.KeyPoint],
    np.ndarray | None,
    float,
    float | None,
]


@dataclass
class SelectionStats:
    candidate_count: int = 0
    rejected_blur: int = 0
    rejected_exposure: int = 0
    rejected_duplicate: int = 0
    rejected_temporal: int = 0
    rejected_overlap: int = 0
    selected_count: int = 0
    selected_start_seconds: float | None = None
    selected_end_seconds: float | None = None
    selected_low_overlap_transition_count: int = 0


class KeyframeSelector:
    def __init__(self, config: KeyframeConfig):
        self.config = config
        self.stats = SelectionStats()

    def select(self, candidates: list[CandidateFrame], output_dir: Path) -> list[FrameObservation]:
        self.stats = SelectionStats(candidate_count=len(candidates))
        scored: list[ScoredCandidate] = []
        for candidate in candidates:
            image = candidate.image
            sharpness, exposure = measure_sharpness(image), measure_exposure(image)
            if sharpness < self.config.minimum_sharpness:
                self.stats.rejected_blur += 1
                continue
            if exposure < self.config.minimum_exposure_score:
                self.stats.rejected_exposure += 1
                continue
            gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
            keypoints, descriptors = cv2.ORB_create(nfeatures=1200).detectAndCompute(gray, None)
            scored.append(
                (candidate, sharpness, exposure, perceptual_hash(image), keypoints, descriptors)
            )
        if not scored:
            raise NoUsableFramesError(
                "All sampled frames were rejected for blur or exposure. Try a clearer video."
            )

        chosen: list[SelectedCandidate] = []
        matcher = cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=True)
        for item in scored:
            candidate, sharpness, exposure, phash, keypoints, descriptors = item
            if (
                chosen
                and candidate.timestamp_seconds - chosen[-1][0].timestamp_seconds
                < self.config.minimum_separation_seconds
            ):
                self.stats.rejected_temporal += 1
                continue
            previous = chosen[-1] if chosen else None
            if previous is None:
                novelty, overlap = 1.0, None
            else:
                if hamming_distance(phash, previous[3]) <= self.config.duplicate_hamming_distance:
                    self.stats.rejected_duplicate += 1
                    continue
                overlap, novelty = self._visual_change(
                    matcher, keypoints, descriptors, previous[4], previous[5], image.shape[:2]
                )
                if (
                    overlap < self.config.minimum_feature_overlap
                    or novelty < self.config.minimum_novelty
                ):
                    self.stats.rejected_overlap += 1
                    continue
                # Very low overlap makes the transition hard to relate; require a visual bridge candidate.
                if (
                    overlap > self.config.maximum_feature_overlap
                    and novelty < self.config.minimum_novelty * 2
                ):
                    self.stats.rejected_overlap += 1
                    continue
            chosen.append((*item, novelty, overlap))

        if len(chosen) < min(self.config.minimum_keyframes, len(scored)):
            # Keep the best quality frames when motion evidence is too sparse to meet the configured floor.
            logger.warning(
                "Visual continuity filters yielded only %d frames; filling from quality-ranked candidates",
                len(chosen),
            )
            existing = {entry[0].timestamp_seconds for entry in chosen}
            remaining = sorted(scored, key=lambda entry: entry[1] * entry[2], reverse=True)
            for item in remaining:
                candidate = item[0]
                if candidate.timestamp_seconds in existing:
                    continue
                if (
                    chosen
                    and min(
                        abs(candidate.timestamp_seconds - entry[0].timestamp_seconds)
                        for entry in chosen
                    )
                    < self.config.minimum_separation_seconds
                ):
                    continue
                chosen.append((*item, 0.0, None))
                existing.add(candidate.timestamp_seconds)
                if len(chosen) >= min(self.config.minimum_keyframes, self.config.maximum_keyframes):
                    break
            chosen.sort(key=lambda entry: entry[0].timestamp_seconds)
        if not chosen:
            raise NoUsableFramesError(
                "No usable keyframes were selected from the decoded candidates."
            )

        if len(chosen) > self.config.maximum_keyframes:
            chosen = self._spread_over_timeline(chosen, self.config.maximum_keyframes)
        chosen = self._recompute_transitions(chosen)

        output_dir.mkdir(parents=True, exist_ok=True)
        observations: list[FrameObservation] = []
        for frame_id, entry in enumerate(chosen, start=1):
            candidate, sharpness, exposure, _phash, _points, _desc, novelty, overlap = entry
            destination = output_dir / f"frame_{frame_id:04d}.jpg"
            shutil.copyfile(candidate.image_path, destination)
            height, width = candidate.image.shape[:2]
            observations.append(
                FrameObservation(
                    frame_id=frame_id,
                    source_frame_index=candidate.source_frame_index,
                    timestamp_seconds=candidate.timestamp_seconds,
                    image_path=str(destination),
                    width=width,
                    height=height,
                    sharpness=sharpness,
                    exposure=exposure,
                    novelty=novelty,
                    feature_overlap=overlap,
                )
            )
        self.stats.selected_count = len(observations)
        self.stats.selected_start_seconds = observations[0].timestamp_seconds
        self.stats.selected_end_seconds = observations[-1].timestamp_seconds
        return observations

    @staticmethod
    def _spread_over_timeline(
        chosen: list[SelectedCandidate], limit: int
    ) -> list[SelectedCandidate]:
        """Keep a deterministic timestamp-spread subset instead of only early views."""
        timestamps = [entry[0].timestamp_seconds for entry in chosen]
        targets = np.linspace(timestamps[0], timestamps[-1], num=limit)
        available = set(range(len(chosen)))
        selected_indices: list[int] = []
        for target in targets:
            selected_index = min(
                available,
                key=lambda index: (abs(timestamps[index] - target), index),
            )
            selected_indices.append(selected_index)
            available.remove(selected_index)
        return [chosen[index] for index in sorted(selected_indices)]

    def _recompute_transitions(
        self, chosen: list[SelectedCandidate]
    ) -> list[SelectedCandidate]:
        """Make novelty/overlap metadata describe adjacent final keyframes."""
        matcher = cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=True)
        recomputed: list[SelectedCandidate] = []
        self.stats.selected_low_overlap_transition_count = 0
        for index, entry in enumerate(chosen):
            if index == 0:
                recomputed.append((*entry[:6], 1.0, None))
                continue
            previous = recomputed[-1]
            overlap, novelty = self._visual_change(
                matcher,
                entry[4],
                entry[5],
                previous[4],
                previous[5],
                entry[0].image.shape[:2],
            )
            recomputed.append((*entry[:6], novelty, overlap))
            if overlap < self.config.minimum_feature_overlap:
                self.stats.selected_low_overlap_transition_count += 1
        return recomputed

    @staticmethod
    def _visual_change(
        matcher: cv2.BFMatcher,
        current_points: list[cv2.KeyPoint],
        current_descriptors: np.ndarray | None,
        previous_points: list[cv2.KeyPoint],
        previous_descriptors: np.ndarray | None,
        image_shape: tuple[int, int],
    ) -> tuple[float, float]:
        if (
            current_descriptors is None
            or previous_descriptors is None
            or not current_points
            or not previous_points
        ):
            return 0.0, 1.0
        matches = matcher.match(current_descriptors, previous_descriptors)
        good = [match for match in matches if match.distance <= 64]
        overlap = len(good) / max(1, min(len(current_points), len(previous_points)))
        displacement = [
            np.linalg.norm(
                np.asarray(current_points[match.queryIdx].pt)
                - np.asarray(previous_points[match.trainIdx].pt)
            )
            for match in good
        ]
        diagonal = max(1.0, float(np.hypot(image_shape[1], image_shape[0])))
        normalized_displacement = float(np.median(displacement) / diagonal) if displacement else 0.0
        novelty = min(1.0, max(0.0, normalized_displacement + (1.0 - min(overlap, 1.0))))
        return min(overlap, 1.0), novelty
