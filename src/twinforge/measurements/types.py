"""Small immutable measurement records; dense geometry remains in the PLY."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from math import dist


@dataclass(frozen=True)
class MeasurementObservation:
    reference_id: str
    scene_manifest_sha256: str
    point_cloud_sha256: str
    frame_id: int
    source_view_sha256: str
    point_indices: tuple[int, int]
    xyz: tuple[tuple[float, float, float], tuple[float, float, float]]
    valid: bool
    selection_origin: str
    selected_at: str
    correspondence_state: str = "unreviewed"
    source_pixels: tuple[tuple[float, float], tuple[float, float]] | None = None
    model_pixels: tuple[tuple[int, int], tuple[int, int]] | None = None
    pixel_provenance: str = "unavailable"
    sensitivity_span_ratio: float | None = None
    sensitivity_complete: bool = False
    raw_confidence: tuple[float | None, float | None] = (None, None)
    timestamp_seconds: float | None = None
    sensitivity_span_scene_units: float | None = None
    schema_version: str = "0.1"
    observation_id: str | None = None
    revision: int = 1
    correction_reason: str | None = None
    submission_key: str | None = None
    submission_fingerprint: str | None = None

    @property
    def length(self) -> float:
        return dist(*self.xyz)

    def to_dict(self) -> dict:
        return {**asdict(self), "length": self.length}


@dataclass(frozen=True)
class MeasurementRecord:
    reference_id: str
    quantity: str
    observations: tuple[MeasurementObservation, ...]
    physical_value: float | None = None
    physical_unit: str | None = None
    role: str = "check_only"
    reference_import: dict | None = None
    schema_version: str = "0.1"
    display_name: str | None = None
    observation_history: tuple[MeasurementObservation, ...] = ()

    def to_dict(self) -> dict:
        return {
            **asdict(self),
            "observations": [item.to_dict() for item in self.observations],
            "observation_history": [item.to_dict() for item in self.observation_history],
        }


@dataclass(frozen=True)
class GeometryEvidence:
    state: str
    observation_count: int
    distinct_view_count: int
    lengths: tuple[float, ...]
    median_length: float | None
    length_spread_ratio: float | None
    endpoint_spread_ratio: float | None
    pixel_sensitivity_span_ratios: tuple[float | None, ...]
    calibration_qualified: bool
    reasons: tuple[str, ...]
    policy: dict
    support_note: str = "Same-model internal consistency only; nearby views provide limited independent support. A segment does not qualify its ROI or scene."
    schema_version: str = "0.1"
