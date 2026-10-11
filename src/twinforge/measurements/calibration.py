"""One frozen, internally qualified physical control establishes uniform scale."""

from copy import deepcopy
from dataclasses import asdict, dataclass
from math import isfinite
from typing import Any

from twinforge.measurements.consistency import (
    DEFAULT_POLICY,
    ConsistencyPolicy,
    evaluate_observations,
)
from twinforge.measurements.types import MeasurementObservation, MeasurementRecord


@dataclass(frozen=True)
class CalibrationRecord:
    scalar: float
    control_id: str
    physical_length_m: float
    reconstructed_median: float
    observations: tuple[MeasurementObservation, ...]
    original_scale: dict[str, Any]
    manifest_sha256: str
    point_cloud_sha256: str
    source_unit: str = "scene_units"
    physical_unit: str = "m"
    measurement_tolerance_m: float | None = None
    schema_version: str = "0.1"
    qualification_policy: ConsistencyPolicy = DEFAULT_POLICY

    def __post_init__(self) -> None:
        # Older records omit this field and retain the original default policy.
        if isinstance(self.qualification_policy, dict):
            object.__setattr__(
                self, "qualification_policy", ConsistencyPolicy(**self.qualification_policy)
            )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def fit_uniform_scale(
    record: MeasurementRecord,
    physical_value: float,
    physical_unit: str,
    *,
    original_scale: dict[str, Any] | None = None,
    measurement_tolerance: float | None = None,
    policy: ConsistencyPolicy = DEFAULT_POLICY,
) -> CalibrationRecord:
    frozen = deepcopy(tuple(record.observations))
    if any(o.reference_id != record.reference_id for o in frozen):
        raise ValueError("Control observation reference does not match record")
    evidence = evaluate_observations(frozen, policy)
    if not evidence.calibration_qualified:
        raise ValueError("Control is not calibration qualified: " + "; ".join(evidence.reasons))
    if physical_unit not in ("m", "cm"):
        raise ValueError("Physical unit must be explicit m or cm")
    if isinstance(physical_value, bool) or not isfinite(physical_value) or physical_value <= 0:
        raise ValueError("Physical length must be positive and finite")
    factor = 1 if physical_unit == "m" else 0.01
    tolerance = None
    if measurement_tolerance is not None:
        if not isfinite(measurement_tolerance) or measurement_tolerance < 0:
            raise ValueError("Measurement tolerance must be finite and nonnegative")
        tolerance = measurement_tolerance * factor
    length = physical_value * factor
    scalar = length / evidence.median_length
    if not isfinite(scalar) or scalar <= 0:
        raise ValueError("Uniform scalar must be positive and finite")
    return CalibrationRecord(
        scalar,
        record.reference_id,
        length,
        evidence.median_length,
        frozen,
        deepcopy(original_scale or {}),
        frozen[0].scene_manifest_sha256,
        frozen[0].point_cloud_sha256,
        measurement_tolerance_m=tolerance,
        qualification_policy=policy,
    )
