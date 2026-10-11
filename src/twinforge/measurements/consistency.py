"""Bounded internal consistency checks, with no physical-length input."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass

import numpy as np

from twinforge.measurements.types import GeometryEvidence, MeasurementObservation


@dataclass(frozen=True)
class ConsistencyPolicy:
    maximum_length_spread_ratio: float = 0.05
    maximum_endpoint_spread_ratio: float = 0.10
    maximum_sensitivity_span_ratio: float = 0.10
    neighborhood_radius_model_pixels: int = 2

    def __post_init__(self):
        if any(
            not np.isfinite(value) or value < 0
            for value in (
                self.maximum_length_spread_ratio,
                self.maximum_endpoint_spread_ratio,
                self.maximum_sensitivity_span_ratio,
            )
        ):
            raise ValueError("Consistency thresholds must be finite nonnegative ratios")
        if self.neighborhood_radius_model_pixels != 2:
            raise ValueError("This policy implements the fixed ±2-model-pixel neighborhood")


DEFAULT_POLICY = ConsistencyPolicy()


def evaluate_observations(
    observations: tuple[MeasurementObservation, ...],
    policy: ConsistencyPolicy = DEFAULT_POLICY,
) -> GeometryEvidence:
    reasons, conflicts = [], []
    observations = tuple(observations)
    finite = all(
        item.valid and np.isfinite(item.xyz).all() and np.isfinite(item.length) and item.length > 0
        for item in observations
    )
    lengths = tuple(item.length for item in observations) if finite else ()
    median = float(np.median(lengths)) if lengths else None
    length_spread = float((max(lengths) - min(lengths)) / median) if lengths else None
    endpoint_spread = None
    distinct = min(
        len({item.frame_id for item in observations}),
        len({item.source_view_sha256 for item in observations}),
    )
    if not finite:
        reasons.append("invalid_endpoints")
    if distinct < 2:
        reasons.append("at_least_two_nonduplicate_source_views_required")
    if any(not re.fullmatch(r"[0-9a-f]{64}", item.source_view_sha256) for item in observations):
        reasons.append("source_view_hash_unavailable")
    if any(item.correspondence_state != "identified" for item in observations):
        reasons.append("physical_endpoint_correspondence_unreviewed")
    if (
        len(
            {
                (item.reference_id, item.scene_manifest_sha256, item.point_cloud_sha256)
                for item in observations
            }
        )
        > 1
    ):
        reasons.append("mixed_reference_or_scene_artifacts")
    if lengths:
        xyz = np.asarray([item.xyz for item in observations])
        endpoint_spread = float(
            np.max(np.linalg.norm(xyz[:, None] - xyz[None, :], axis=-1)) / median
        )
        if length_spread > policy.maximum_length_spread_ratio:
            conflicts.append("length_spread_exceeds_threshold")
        if endpoint_spread > policy.maximum_endpoint_spread_ratio:
            conflicts.append("endpoint_spread_exceeds_threshold")
    sensitivities = tuple(
        (
            item.sensitivity_span_scene_units / median
            if item.sensitivity_span_scene_units is not None
            else item.sensitivity_span_ratio * item.length / median
        )
        if median is not None and item.sensitivity_span_ratio is not None
        else None
        for item in observations
    )
    sensitivity_available = all(
        item.model_pixels is not None
        and item.pixel_provenance in ("native", "derived")
        and item.sensitivity_complete
        and item.sensitivity_span_ratio is not None
        and np.isfinite(item.sensitivity_span_ratio)
        and item.sensitivity_span_ratio >= 0
        for item in observations
    )
    if not sensitivity_available:
        qualification_reasons = ["pixel_sensitivity_unavailable"]
    else:
        qualification_reasons = []
        if any(value is None or value < 0 or not np.isfinite(value) for value in sensitivities):
            qualification_reasons.append("pixel_sensitivity_unavailable")
            sensitivity_available = False
        elif any(value > policy.maximum_sensitivity_span_ratio for value in sensitivities):
            conflicts.append("pixel_sensitivity_exceeds_threshold")
    state = (
        "insufficient_evidence"
        if reasons
        else ("conflicting_observations" if conflicts else "consistent_observations")
    )
    return GeometryEvidence(
        state,
        len(observations),
        distinct,
        lengths,
        median,
        length_spread,
        endpoint_spread,
        sensitivities,
        state == "consistent_observations" and sensitivity_available,
        tuple(reasons + conflicts + qualification_reasons),
        asdict(policy),
    )
