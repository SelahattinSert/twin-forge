"""Guarded workspace persistence and frozen-reference imports."""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from dataclasses import asdict, replace
from pathlib import Path
from threading import RLock
from uuid import uuid4

import numpy as np

from twinforge.measurements.consistency import evaluate_observations
from twinforge.measurements.errors import MeasurementValidationError
from twinforge.measurements.observations import resolve_observation
from twinforge.measurements.types import MeasurementObservation, MeasurementRecord
from twinforge.scene.provenance import PixelTransform
from twinforge.scene.reader import sha256_file
from twinforge.scene.types import SceneArtifact


class MeasurementStore:
    def __init__(self, workspace: Path, scene: SceneArtifact):
        self.root = Path(workspace).resolve()
        self.scene = scene
        self._lock = RLock()
        source = scene.source_root.resolve()
        if self.root.is_relative_to(source) or source.is_relative_to(self.root):
            raise ValueError("Workspace must be separate from source artifacts")
        self.root.mkdir(parents=True, exist_ok=True)
        session_path = self._path("session")
        binding = {
            "manifest_sha256": scene.manifest_sha256,
            "point_cloud_sha256": scene.point_cloud_sha256,
        }
        if session_path.exists():
            session = json.loads(session_path.read_text())
            if session.get("schema_version") != "0.1" or session.get("source_artifacts") != binding:
                raise ValueError("Workspace session artifact hashes do not match")
        else:
            self._write(
                "session",
                {
                    "schema_version": "0.1",
                    "source_artifacts": binding,
                    "source_manifest": str(scene.manifest_path),
                    "usage_status": "visualization_only",
                    "scale": scene.scale,
                    "measurements": "measurements.json",
                    "geometry_evidence": "geometry-evidence.json",
                    "visibility": "visibility.json",
                },
            )

    def _path(self, name: str) -> Path:
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,99}", name):
            raise ValueError("Invalid workspace record ID")
        path = (self.root / f"{name}.json").resolve()
        if not path.is_relative_to(self.root):
            raise ValueError("Workspace path escapes root")
        return path

    def _write(self, name, value):
        with self._lock:
            self._write_atomic(name, value)

    def _write_atomic(self, name, value):
        path = self._path(name)
        payload = json.dumps(value, indent=2, allow_nan=False) + "\n"
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8", dir=self.root, suffix=".tmp", delete=False
            ) as stream:
                temporary = Path(stream.name)
                stream.write(payload)
            os.replace(temporary, path)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)

    def save(self, record: MeasurementRecord) -> None:
        with self._lock:
            self._save(record)

    def append(
        self,
        observation: MeasurementObservation,
        quantity: str,
        *,
        display_name=None,
        submission_key=None,
        correction_id=None,
        expected_revision=None,
        correction_reason=None,
    ) -> MeasurementRecord:
        """Keep the complete read/append/publish transaction under one lock."""
        with self._lock:
            try:
                previous = self.load(observation.reference_id)
            except FileNotFoundError:
                previous = MeasurementRecord(observation.reference_id, quantity, ())
            if quantity != previous.quantity:
                raise ValueError(
                    "Saved measurement quantity cannot change while adding observations"
                )
            if submission_key is not None and (
                not isinstance(submission_key, str)
                or not re.fullmatch(r"[A-Za-z0-9_.-]{1,128}", submission_key)
            ):
                raise ValueError("Invalid idempotency key")
            payload = observation.to_dict()
            for field in (
                "selected_at",
                "observation_id",
                "revision",
                "correction_reason",
                "submission_key",
                "submission_fingerprint",
            ):
                payload.pop(field, None)
            fingerprint = hashlib.sha256(
                json.dumps(
                    [payload, quantity, correction_id, expected_revision, correction_reason],
                    sort_keys=True,
                    allow_nan=False,
                ).encode()
            ).hexdigest()
            for item in (*previous.observations, *previous.observation_history):
                if submission_key is not None and item.submission_key == submission_key:
                    if item.submission_fingerprint != fingerprint:
                        raise ValueError(
                            "An idempotency key cannot be reused for another selection"
                        )
                    return previous
            observation = replace(
                observation,
                observation_id=str(uuid4()),
                submission_key=submission_key,
                submission_fingerprint=fingerprint,
            )
            active = list(previous.observations)
            history = previous.observation_history
            if correction_id is not None:
                if (
                    not isinstance(correction_reason, str)
                    or not correction_reason.strip()
                    or len(correction_reason) > 1000
                ):
                    raise ValueError(
                        "A correction requires an explicit reason (up to 1000 characters)"
                    )
                index = next(
                    (
                        i
                        for i, item in enumerate(active)
                        if (item.observation_id or f"legacy-{i + 1}") == correction_id
                    ),
                    None,
                )
                if index is None:
                    raise ValueError("Unknown observation to correct")
                old = active[index]
                if type(expected_revision) is not int or old.revision != expected_revision:
                    raise MeasurementValidationError("stale_correction")
                old = replace(old, observation_id=correction_id)
                observation = replace(
                    observation,
                    observation_id=correction_id,
                    revision=old.revision + 1,
                    correction_reason=correction_reason.strip(),
                )
                active[index] = observation
                history = (*history, old)
            else:
                active.append(observation)
            record = replace(
                previous,
                observations=tuple(active),
                observation_history=history,
                display_name=previous.display_name if display_name is None else display_name,
                schema_version="0.2",
            )
            self.save(record)
            return record

    def rename(self, reference_id: str, display_name: str) -> MeasurementRecord:
        with self._lock:
            record = replace(
                self.load(reference_id), display_name=display_name, schema_version="0.2"
            )
            self.save(record)
            return record

    def summary(self) -> dict:
        """Count saved observations and references from one committed snapshot."""
        with self._lock:
            ids = self.list_ids()
            return {
                "reference_count": len(ids),
                "observation_count": sum(len(self.load(item).observations) for item in ids),
                "measurement_names": {item: self.load(item).display_name or item for item in ids},
            }

    def _save(self, record: MeasurementRecord) -> None:
        if record.reference_id in (
            "session",
            "measurements",
            "geometry-evidence",
            "visibility",
            "pixel-provenance",
            "calibration",
            "check-report",
        ):
            raise ValueError("Reserved workspace record ID")
        if record.role not in ("check_only", "calibration") or not record.quantity:
            raise ValueError("Measurement quantity and calibration/check_only role are required")
        if record.display_name is not None and (
            not isinstance(record.display_name, str) or len(record.display_name) > 500
        ):
            raise ValueError("Display name must be text of up to 500 characters")
        for item in (*record.observations, *record.observation_history):
            if item.reference_id != record.reference_id:
                raise ValueError("Observation reference does not match record")
            if (
                item.scene_manifest_sha256 != self.scene.manifest_sha256
                or item.point_cloud_sha256 != self.scene.point_cloud_sha256
            ):
                raise ValueError("Observation artifact hashes do not match")
            resolve_observation(self.scene, item)
        self._write(record.reference_id, record.to_dict())
        ids = self.list_ids()
        self._write(
            "measurements",
            {
                "schema_version": "0.1",
                "records": [{"reference_id": item, "path": f"{item}.json"} for item in ids],
            },
        )
        evidence = {
            item: asdict(evaluate_observations(self.load(item).observations)) for item in ids
        }
        self._write(
            "geometry-evidence",
            {
                "schema_version": "0.1",
                "references": evidence,
                "scope": "Per-reference internal consistency; no whole-scene accuracy claim",
            },
        )
        session = json.loads(self._path("session").read_text())
        session["usage_status"] = "partially_checked"
        self._write("session", session)

    def load(self, reference_id: str) -> MeasurementRecord:
        with self._lock:
            return self._load(reference_id)

    def _load(self, reference_id: str) -> MeasurementRecord:
        value = json.loads(self._path(reference_id).read_text())
        schema = value.pop("schema_version")
        if schema not in ("0.1", "0.2"):
            raise ValueError("Unknown measurement schema")
        if value.get("reference_id") != reference_id:
            raise ValueError("Saved measurement reference does not match record ID")

        def decode(item):
            item.pop("length", None)
            for name in ("xyz", "model_pixels", "source_pixels"):
                if item.get(name) is not None:
                    item[name] = tuple(map(tuple, item[name]))
            for name in ("point_indices", "raw_confidence"):
                item[name] = tuple(item[name])
            observation = MeasurementObservation(**item)
            if observation.reference_id != reference_id:
                raise ValueError("Saved observation reference does not match record")
            if (
                observation.scene_manifest_sha256 != self.scene.manifest_sha256
                or observation.point_cloud_sha256 != self.scene.point_cloud_sha256
            ):
                raise ValueError("Saved measurement artifact hashes do not match")
            return resolve_observation(self.scene, observation)

        observations = tuple(decode(item) for item in value.pop("observations"))
        history = tuple(decode(item) for item in value.pop("observation_history", ()))
        return MeasurementRecord(
            observations=observations, observation_history=history, schema_version=schema, **value
        )

    def list_ids(self) -> list[str]:
        with self._lock:
            return self._list_ids()

    def _list_ids(self) -> list[str]:
        result = []
        for path in sorted(self.root.glob("*.json")):
            value = json.loads(path.read_text())
            if "observations" in value and "quantity" in value:
                result.append(path.stem)
        return result

    def save_visibility(self, value):
        if set(value) != {"hidden_frame_ids", "hidden_rois"}:
            raise ValueError("Visibility requires frame IDs and ROI bounds")
        if any(
            type(item) is not int or item not in {frame.frame_id for frame in self.scene.frames}
            for item in value["hidden_frame_ids"]
        ):
            raise ValueError("Unknown hidden source frame")
        for roi in value["hidden_rois"]:
            if not isinstance(roi, dict) or set(roi) != {"frame_id", "bounds"}:
                raise ValueError("ROI requires only a frame ID and model pixel bounds")
            if type(roi["frame_id"]) is not int or roi["frame_id"] not in {
                frame.frame_id for frame in self.scene.frames
            }:
                raise ValueError("Unknown ROI source frame")
            bounds = np.asarray(roi["bounds"], dtype=float)
            if (
                bounds.shape != (4,)
                or not np.isfinite(bounds).all()
                or (bounds < 0).any()
                or bounds[2] < bounds[0]
                or bounds[3] < bounds[1]
            ):
                raise ValueError("ROI requires finite ordered nonnegative model pixel bounds")
            transform = next(
                (
                    item
                    for item in self.scene.pixel_transforms
                    if item["frame_id"] == roi["frame_id"]
                ),
                None,
            )
            if transform is not None:
                mapping = PixelTransform(
                    **{**transform, "crop_bbox": tuple(transform["crop_bbox"])}
                )
                if bounds[2] >= mapping.model_width or bounds[3] >= mapping.model_height:
                    raise ValueError("ROI bounds lie outside the verified model grid")
        self._write(
            "visibility",
            {
                "schema_version": "0.1",
                **value,
                "interpretation": "manually hidden; geometry has not been corrected",
            },
        )

    def load_visibility(self):
        with self._lock:
            return self._load_visibility()

    def save_calibration(self, record):
        with self._lock:
            if (record.manifest_sha256, record.point_cloud_sha256) != (
                self.scene.manifest_sha256,
                self.scene.point_cloud_sha256,
            ):
                raise ValueError("Calibration artifact hashes do not match workspace")
            self._write("calibration", record.to_dict())

    def _load_visibility(self):
        path = self._path("visibility")
        return (
            json.loads(path.read_text())
            if path.exists()
            else {
                "schema_version": "0.1",
                "hidden_frame_ids": [],
                "hidden_rois": [],
                "interpretation": "manually hidden; geometry has not been corrected",
            }
        )

    def import_reference(self, source: Path, name: str, reason: str):
        payload = source.read_bytes()
        digest = sha256_file(source)
        self._write(
            name,
            {
                "schema_version": "0.1",
                "source_path": str(source),
                "source_sha256": digest,
                "reason": reason,
                "frozen_reference": json.loads(payload),
            },
        )
        return {
            "source_path": str(source),
            "source_sha256": digest,
            "workspace_record": f"{name}.json",
            "reason": reason,
        }
