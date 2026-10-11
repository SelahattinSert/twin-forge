"""Bounded engineering policy never consumes a physical reference length."""

import importlib
from dataclasses import replace

import numpy as np
import pytest
from test_measurements import measurement_modules


def paired(length=1.0, shift=0.0, pixel=True, frame_id=2):
    types, _, _, _ = measurement_modules()
    return types.MeasurementObservation(
        reference_id="door",
        scene_manifest_sha256="a" * 64,
        point_cloud_sha256="b" * 64,
        frame_id=frame_id,
        source_view_sha256=str(frame_id) * 64,
        point_indices=(frame_id * 2, frame_id * 2 + 1),
        xyz=((shift, 0.0, 0.0), (length + shift, 0.0, 0.0)),
        valid=True,
        selection_origin="frozen_rgb",
        selected_at="2026-10-01T00:00:00+00:00",
        correspondence_state="identified",
        model_pixels=((5, 5), (10, 5)) if pixel else None,
        pixel_provenance="native" if pixel else "unavailable",
        sensitivity_span_ratio=0.01 if pixel else None,
        sensitivity_complete=pixel,
    )


def test_paired_consistent_observations_qualify_and_25_percent_disagreement_conflicts():
    _, _, module, _ = measurement_modules()
    evidence = module.evaluate_observations((paired(frame_id=1), paired(1.01)))
    assert evidence.state == "consistent_observations" and evidence.calibration_qualified
    assert evidence.lengths == pytest.approx((1, 1.01))
    assert evidence.length_spread_ratio == pytest.approx(0.01 / 1.005)
    conflict = module.evaluate_observations((paired(frame_id=1), paired(1.25)))
    assert conflict.state == "conflicting_observations" and not conflict.calibration_qualified
    assert "length_spread_exceeds_threshold" in conflict.reasons


def test_missing_provenance_preserves_3d_agreement_but_blocks_qualification():
    _, _, module, _ = measurement_modules()
    evidence = module.evaluate_observations((paired(pixel=False, frame_id=1), paired(pixel=False)))
    assert evidence.state == "consistent_observations"
    assert not evidence.calibration_qualified
    assert "pixel_sensitivity_unavailable" in evidence.reasons


def test_duplicates_correspondence_and_endpoint_disagreement():
    _, _, module, _ = measurement_modules()
    first = paired(frame_id=1)
    assert module.evaluate_observations((first, first)).state == "insufficient_evidence"
    assert (
        module.evaluate_observations(
            (first, replace(paired(), source_view_sha256=first.source_view_sha256))
        ).state
        == "insufficient_evidence"
    )
    assert (
        module.evaluate_observations(
            (first, replace(paired(), correspondence_state="unreviewed"))
        ).state
        == "insufficient_evidence"
    )
    assert (
        module.evaluate_observations((first, paired(shift=0.2))).state == "conflicting_observations"
    )


def test_rigid_world_transform_preserves_evidence_and_sensitivity_gate():
    _, _, module, _ = measurement_modules()
    observations = (paired(frame_id=1), paired(1.01, shift=0.02))
    rotation = np.array([[0, -1, 0], [1, 0, 0], [0, 0, 1]])
    moved = tuple(
        replace(item, xyz=tuple(map(tuple, np.asarray(item.xyz) @ rotation.T + [10, 20, 30])))
        for item in observations
    )
    original, transformed = map(module.evaluate_observations, (observations, moved))
    assert original.state == transformed.state
    assert original.length_spread_ratio == pytest.approx(transformed.length_spread_ratio)
    assert original.endpoint_spread_ratio == pytest.approx(transformed.endpoint_spread_ratio)
    assert not module.evaluate_observations(
        (observations[0], replace(observations[1], sensitivity_span_ratio=0.11))
    ).calibration_qualified
    assert (
        "physical"
        not in importlib.import_module("inspect").signature(module.evaluate_observations).parameters
    )


@pytest.mark.parametrize("ratio", [-0.01, float("nan"), float("inf")])
def test_invalid_sensitivity_never_qualifies(ratio):
    _, _, module, _ = measurement_modules()
    evidence = module.evaluate_observations(
        (paired(frame_id=1), replace(paired(), sensitivity_span_ratio=ratio))
    )
    assert not evidence.calibration_qualified


def test_missing_or_duplicate_source_hash_never_qualifies():
    _, _, module, _ = measurement_modules()
    evidence = module.evaluate_observations(
        (replace(paired(frame_id=1), source_view_sha256="unavailable"), paired())
    )
    assert not evidence.calibration_qualified
