"""Read-only source observations retained by a uniformly scaled export."""

import json
import re
from dataclasses import asdict

import numpy as np

from twinforge.measurements.calibration import CalibrationRecord
from twinforge.measurements.consistency import evaluate_observations
from twinforge.measurements.types import MeasurementObservation, MeasurementRecord
from twinforge.scene.derive import check_report
from twinforge.scene.reader import SceneReadError, _json, _reference, sha256_file


def _observation(value):
    value = dict(value)
    value.pop("length", None)
    if value.get("schema_version") != "0.1":
        raise ValueError("Unsupported frozen observation schema")
    for name in ("xyz", "model_pixels", "source_pixels"):
        if value.get(name) is not None:
            value[name] = tuple(map(tuple, value[name]))
    for name in ("point_indices", "raw_confidence"):
        value[name] = tuple(value[name])
    return MeasurementObservation(**value)


def read_archive(scene):
    """Never import archived identities into the active scaled-scene workspace."""
    try:
        manifest = _json(scene.manifest_path)
        derivation = manifest.get("derivation")
        if derivation is None:
            return {"status": "absent", "read_only": True}
        transform = derivation["transform"]
        scalar = transform["scalar"]
        if (
            transform["type"] != "uniform_scale"
            or transform["applied_once"] is not True
            or isinstance(scalar, bool)
            or not np.isfinite(scalar)
            or scalar <= 0
        ):
            raise ValueError("Unsupported uniform derivation transform")
        root = scene.source_root
        calibration = _json(_reference(root, derivation["calibration"], root))
        measurements = _json(
            _reference(root, derivation.get("measurements", "measurements.json"), root)
        )
        report = _json(_reference(root, derivation.get("check_report", "check-report.json"), root))
        if any(v.get("schema_version") != "0.1" for v in (calibration, measurements, report)):
            raise ValueError("Unsupported archive schema")
        hashes = (derivation["source_manifest_sha256"], derivation["source_point_cloud_sha256"])
        if any(not isinstance(h, str) or not re.fullmatch("[0-9a-f]{64}", h) for h in hashes):
            raise ValueError("Invalid archived source hashes")
        if (calibration["manifest_sha256"], calibration["point_cloud_sha256"]) != hashes:
            raise ValueError("Calibration source hashes disagree with derivation")
        if (
            calibration["scalar"] != scalar
            or calibration["original_scale"] != derivation["original_scale"]
        ):
            raise ValueError("Calibration scalar/original scale disagrees with derivation")
        frames = {f.frame_id: f for f in scene.frames}

        def validate(observation):
            if (observation.scene_manifest_sha256, observation.point_cloud_sha256) != hashes:
                raise ValueError("Frozen observation source hashes disagree with derivation")
            indices = observation.point_indices
            if len(indices) != 2 or any(
                type(i) is not int or not 0 <= i < scene.point_count for i in indices
            ):
                raise ValueError("Frozen endpoint indices outside exported PLY")
            xyz = np.asarray(observation.xyz, dtype=float)
            actual = np.column_stack(
                [scene.point_records[a][list(indices)] for a in ("x", "y", "z")]
            )
            if (
                xyz.shape != (2, 3)
                or not np.isfinite(xyz).all()
                or not np.allclose(actual, xyz * scalar, rtol=1e-6, atol=1e-7)
            ):
                raise ValueError("Frozen source endpoints disagree with scaled exported PLY")
            if "source_frame_id" in scene.point_records.dtype.names and any(
                scene.point_records["source_frame_id"][i] != observation.frame_id for i in indices
            ):
                raise ValueError("Frozen endpoint source frame IDs disagree")
            if (
                "valid" in scene.point_records.dtype.names
                and bool(np.all(scene.point_records["valid"][list(indices)])) != observation.valid
            ):
                raise ValueError("Frozen endpoint validity disagrees")
            mapping = next(
                (m for m in scene.pixel_transforms if m["frame_id"] == observation.frame_id), None
            )
            if (
                mapping
                and observation.model_pixels is not None
                and "source_pixel_index" in scene.point_records.dtype.names
            ):
                width = mapping["crop_bbox"][2] - mapping["crop_bbox"][0]
                pixels = np.asarray(observation.model_pixels)
                if pixels.shape != (2, 2) or not np.array_equal(
                    scene.point_records["source_pixel_index"][list(indices)],
                    pixels[:, 1] * width + pixels[:, 0],
                ):
                    raise ValueError("Frozen endpoint model pixel IDs disagree")
            frame = frames.get(observation.frame_id)
            if frame is None or sha256_file(frame.image_path) != observation.source_view_sha256:
                raise ValueError("Frozen source image hash disagrees")

        control = tuple(_observation(o) for o in calibration["observations"])
        for o in control:
            validate(o)
            if o.reference_id != calibration["control_id"]:
                raise ValueError("Frozen control identity disagrees")
        fitted = CalibrationRecord(**{**calibration, "observations": control})
        evidence = evaluate_observations(control, fitted.qualification_policy)
        if (
            not evidence.calibration_qualified
            or not np.isclose(
                fitted.reconstructed_median, evidence.median_length, rtol=1e-12, atol=0
            )
            or isinstance(fitted.physical_length_m, bool)
            or not np.isfinite(fitted.physical_length_m)
            or fitted.physical_length_m <= 0
            or not np.isclose(
                scalar, fitted.physical_length_m / evidence.median_length, rtol=1e-12, atol=0
            )
        ):
            raise ValueError("Frozen calibration qualification/median/scalar binding is invalid")
        records = []
        for value in measurements["records"]:
            if value.get("schema_version") not in ("0.1", "0.2") or value.get("role") not in (
                "calibration",
                "check_only",
            ):
                raise ValueError("Unsupported frozen measurement schema or role")
            observations = tuple(_observation(o) for o in value["observations"])
            for o in observations:
                validate(o)
                if o.reference_id != value["reference_id"]:
                    raise ValueError("Frozen reference identity disagrees")
            history = tuple(_observation(o) for o in value.get("observation_history", ()))
            for o in history:
                validate(o)
                if o.reference_id != value["reference_id"]:
                    raise ValueError("Frozen history reference identity disagrees")
            record = MeasurementRecord(
                **{**value, "observations": observations, "observation_history": history}
            )
            imported = record.reference_import
            if (
                imported
                and "frozen_check" in imported
                and imported.get("point_cloud_sha256") != hashes[1]
            ):
                raise ValueError("Frozen imported check source hash unavailable or stale")
            for additional in (imported or {}).get("additional_same_reference_checks", []):
                for value in additional.get("observations", []):
                    observation = _observation(value)
                    validate(observation)
                    if observation.reference_id != additional["reference_id"]:
                        raise ValueError("Additional frozen reference identity disagrees")
            records.append(record)
        if len({r.reference_id for r in records}) != len(records):
            raise ValueError("Duplicate frozen reference IDs")
        if json.dumps(check_report(records, fitted), sort_keys=True) != json.dumps(
            report, sort_keys=True
        ):
            raise ValueError("Frozen check report disagrees with retained records/calibration")
        return {
            "status": "available",
            "read_only": True,
            "display_scalar": scalar,
            "source_manifest_sha256": hashes[0],
            "source_point_cloud_sha256": hashes[1],
            "validation_scope": "Source hashes bound to derivation; endpoints verified against scaled PLY and copied source images. Original source files are not reopened.",
            "calibration": calibration,
            "check_report": report,
            "measurements": [
                {"record": r.to_dict(), "evidence": asdict(evaluate_observations(r.observations))}
                for r in records
            ],
        }
    except (ValueError, TypeError, KeyError, OSError, AttributeError, SceneReadError) as exc:
        return {"status": "unavailable", "read_only": True, "reason": str(exc)}
