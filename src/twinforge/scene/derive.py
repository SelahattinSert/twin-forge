"""Separate, source-linked uniform exports. No shape correction is performed."""

import json
import shutil
from collections.abc import Sequence
from dataclasses import asdict
from pathlib import Path
from typing import Any
from uuid import uuid4

import numpy as np
from numpy.typing import ArrayLike

from twinforge.core.types import PointCloud
from twinforge.export.glb import write_point_glb
from twinforge.measurements.calibration import CalibrationRecord
from twinforge.measurements.consistency import evaluate_observations
from twinforge.measurements.observations import resolve_observation
from twinforge.measurements.types import MeasurementRecord
from twinforge.scene.reader import SceneReader, sha256_file
from twinforge.scene.types import SceneArtifact


def scale_geometry(
    xyz: ArrayLike, camera_to_world: ArrayLike, scalar: float
) -> tuple[np.ndarray, np.ndarray]:
    if not np.isfinite(scalar) or scalar <= 0:
        raise ValueError("Uniform scalar must be positive and finite")
    pose = np.array(camera_to_world, dtype=float, copy=True)
    pose[:3, 3] *= scalar
    return np.asarray(xyz) * scalar, pose


def check_report(
    records: Sequence[MeasurementRecord], calibration: CalibrationRecord
) -> dict[str, Any]:
    checks = []
    for record in records:
        if record.reference_id == calibration.control_id:
            continue
        evidence = evaluate_observations(record.observations)
        adequate = evidence.state == "consistent_observations" and all(
            o.correspondence_state == "identified" for o in record.observations
        )
        value = evidence.median_length * calibration.scalar if adequate else None
        status = "observed_check" if value is not None else "unmeasured_or_provisional"
        imported = record.reference_import or {}
        frozen = imported.get("frozen_check", {})
        if (
            value is None
            and not record.observations
            and imported.get("point_cloud_sha256") == calibration.point_cloud_sha256
            and frozen.get("correspondence_status") == "reliable_correspondence"
            and frozen.get("reconstructed_distance_m") is not None
        ):
            distance = frozen["reconstructed_distance_m"]
            source_meters = calibration.original_scale.get("meters_per_unit", 1)
            if not np.isfinite(distance) or distance <= 0 or not source_meters:
                raise ValueError("Frozen check must have a finite positive source length")
            value = distance / source_meters * calibration.scalar
            status = "frozen_historical_check"
        physical = record.physical_value
        if physical is not None:
            if record.physical_unit not in ("m", "cm"):
                raise ValueError("Check physical units must be explicit m or cm")
            physical *= 1 if record.physical_unit == "m" else 0.01
        local_regions = {}
        if imported.get("point_cloud_sha256") == calibration.point_cloud_sha256:
            for name, region in frozen.get("local_regions", {}).items():
                distance = region.get("reconstructed_distance_m")
                observed = region.get("correspondence_status") == "observed_patch_overlap"
                scaled = (
                    distance
                    * calibration.scalar
                    / calibration.original_scale.get("meters_per_unit", 1)
                    if observed and distance is not None
                    else None
                )
                local_regions[name] = {
                    **region,
                    "scaled_length_m": scaled,
                    "error_m": scaled - physical if scaled is not None and physical else None,
                    "independence": "Same physical reference; patches are not independent references",
                }
        checks.append(
            {
                "reference_id": record.reference_id,
                "role": "check_only",
                "evidence": asdict(evidence),
                "scaled_median_m": value,
                "physical_length_m": physical,
                "error_m": value - physical if value is not None and physical else None,
                "status": status,
                "local_regions": local_regions,
                "reference_import": record.reference_import,
            }
        )
    return {
        "schema_version": "0.1",
        "excluded_control_id": calibration.control_id,
        "checks": checks,
        "coverage": "Examined references only; no whole-scene accuracy",
        "limitation": "Previously inspected references are not a blind test set",
    }


def derive_scene(
    scene: SceneArtifact,
    calibration: CalibrationRecord,
    destination: str | Path,
    *,
    records: Sequence[MeasurementRecord] = (),
) -> SceneArtifact:
    """Publish a new directory once; reject source overlap and repeated calibration."""
    target = Path(destination).resolve()
    source = scene.source_root.resolve()
    if target.is_relative_to(source) or source.is_relative_to(target):
        raise ValueError("Derived destination must be separate from source")
    if target.exists():
        raise ValueError("Derived destination already exists; choose a new derivation")
    if scene.scale.get("type") == "calibrated_metric":
        raise ValueError("Scale has already been applied")
    if (calibration.manifest_sha256, calibration.point_cloud_sha256) != (
        scene.manifest_sha256,
        scene.point_cloud_sha256,
    ):
        raise ValueError("Calibration artifact hashes do not match source")
    if (
        sha256_file(scene.manifest_path) != scene.manifest_sha256
        or sha256_file(scene.point_cloud_path) != scene.point_cloud_sha256
    ):
        raise ValueError("Source artifacts changed")
    if not np.isfinite(calibration.scalar) or calibration.scalar <= 0:
        raise ValueError("Invalid scalar")
    if (
        isinstance(calibration.physical_length_m, bool)
        or not np.isfinite(calibration.physical_length_m)
        or calibration.physical_length_m <= 0
    ):
        raise ValueError("Physical length must be positive and finite")
    if calibration.original_scale != scene.scale:
        raise ValueError("Calibration original scale does not match source")
    if any(o.reference_id != calibration.control_id for o in calibration.observations):
        raise ValueError("Calibration control reference does not match observations")
    for observation in calibration.observations:
        resolve_observation(scene, observation)
    for record in records:
        for observation in record.observations:
            if observation.reference_id != record.reference_id:
                raise ValueError("Observation reference does not match record")
            resolve_observation(scene, observation)
    evidence = evaluate_observations(calibration.observations, calibration.qualification_policy)
    if not evidence.calibration_qualified:
        raise ValueError("Control is not calibration qualified: " + "; ".join(evidence.reasons))
    if not np.isclose(calibration.reconstructed_median, evidence.median_length, rtol=1e-12, atol=0):
        raise ValueError("Calibration median disagrees with frozen control")
    if not np.isclose(
        calibration.scalar,
        calibration.physical_length_m / evidence.median_length,
        rtol=1e-12,
        atol=0,
    ):
        raise ValueError("Calibration scalar disagrees with frozen control")
    target.parent.mkdir(parents=True, exist_ok=True)
    stage = target.parent / (".derivation-" + uuid4().hex)
    stage.mkdir()
    try:
        rows = scene.point_records.copy()
        materialize_pixels = (
            scene.derived_pixel_indices is not None and "source_pixel_index" not in rows.dtype.names
        )
        if materialize_pixels:
            original = rows
            rows = np.empty(
                len(original), dtype=original.dtype.descr + [("source_pixel_index", "<u4")]
            )
            for name in original.dtype.names:
                rows[name] = original[name]
            rows["source_pixel_index"] = scene.derived_pixel_indices
        for axis in ("x", "y", "z"):
            with np.errstate(over="ignore", invalid="ignore"):
                scaled = rows[axis].astype(np.float64) * calibration.scalar
            if not np.isfinite(scaled).all() or (np.abs(scaled) > np.finfo(np.float32).max).any():
                raise ValueError("Uniform scale exceeds finite float32 geometry")
            rows[axis] = scaled
        with scene.point_cloud_path.open("rb") as stream:
            header = bytearray()
            while True:
                line = stream.readline()
                if not line:
                    raise ValueError("Invalid PLY header")
                header.extend(line)
                if line.strip() == b"end_header":
                    break
        if materialize_pixels:
            header = header.replace(
                b"end_header\n", b"property uint source_pixel_index\nend_header\n"
            )
        with (stage / "pointcloud.ply").open("wb") as stream:
            stream.write(header)
            rows.tofile(stream)
        xyz = np.column_stack([rows[a] for a in ("x", "y", "z")])
        # The GLB is only a bounded regenerable display preview.
        selected = np.flatnonzero(np.isfinite(xyz).all(axis=1))
        if "valid" in rows.dtype.names:
            selected = selected[rows["valid"][selected].astype(bool)]
        selected = selected[:: max(1, int(np.ceil(len(selected) / 100000)))]
        rgb = (
            np.column_stack([rows[a][selected] for a in ("red", "green", "blue")])
            if "red" in rows.dtype.names
            else None
        )
        write_point_glb(stage / "preview.glb", PointCloud(xyz=xyz[selected], rgb=rgb))
        source_manifest = json.loads(scene.manifest_path.read_text())
        camera_data = json.loads(
            (
                scene.manifest_path.parent / source_manifest.get("cameras", "cameras.json")
            ).read_text()
        )
        camera_data["cameras"] = [asdict(c) for c in scene.cameras]
        for camera in camera_data["cameras"]:
            if camera["camera_to_world"] is not None:
                _, pose = scale_geometry([], camera["camera_to_world"], calibration.scalar)
                camera["camera_to_world"] = pose.tolist()
        frames = []
        (stage / "frames").mkdir()
        for frame in scene.frames:
            name = f"frames/{frame.frame_id}{frame.image_path.suffix}"
            shutil.copyfile(frame.image_path, stage / name)
            frames.append({**asdict(frame), "image_path": name})
        manifest = json.loads(scene.manifest_path.read_text())
        depth_reference = manifest.get("geometry", {}).get("depth_maps")
        depth_included = False
        if (
            depth_reference is not None
            and scene.scale.get("type") == "estimated_metric"
            and scene.scale.get("meters_per_unit") == 1
        ):
            with np.load(
                scene.manifest_path.parent / depth_reference, allow_pickle=False
            ) as archive:
                if (
                    str(archive.get("depth_convention", "")) == "OpenCV camera +Z forward"
                    and str(archive.get("unit_note", "")) == "meters when scene scale is metric"
                    and set(archive.get("frame_ids", [])) == {f.frame_id for f in scene.frames}
                    and all(f"depth_z_{f.frame_id:04d}" in archive for f in scene.frames)
                ):
                    arrays = {key: archive[key] for key in archive.files}
                    for key, value in arrays.items():
                        if key.startswith("depth_z_"):
                            arrays[key] = value * calibration.scalar
                    arrays["unit_note"] = np.asarray(
                        "meters; uniform physical calibration applied once"
                    )
                    np.savez_compressed(stage / "depthmaps.npz", **arrays)
                    depth_included = True
        manifest.update(schema_version="0.2", cameras="cameras.json", keyframes="keyframes.json")
        manifest.pop("quality", None)
        manifest["geometry"] = {
            "point_cloud": "pointcloud.ply",
            "preview": "preview.glb",
            "point_count": len(rows),
        }
        if depth_included:
            manifest["geometry"]["depth_maps"] = "depthmaps.npz"
        manifest["scale"] = {
            "type": "calibrated_metric",
            "meters_per_unit": 1,
            "confidence": None,
            "source": "one qualified physical control",
        }
        manifest["derivation"] = {
            "id": uuid4().hex,
            "source_manifest": str(scene.manifest_path),
            "source_manifest_sha256": scene.manifest_sha256,
            "source_point_cloud_sha256": scene.point_cloud_sha256,
            "transform": {
                "type": "uniform_scale",
                "scalar": calibration.scalar,
                "applied_once": True,
            },
            "original_scale": scene.scale,
            "calibration": "calibration.json",
            "depth_status": (
                "camera-Z depth uniformly scaled once; confidence and validity preserved"
                if depth_included
                else "omitted: source depth units/convention unresolved"
            ),
        }
        manifest["usage_status"] = "partially_checked"
        if isinstance(manifest.get("coordinate_system"), dict):
            manifest["coordinate_system"]["units"] = "meters"
        manifest["pixel_transforms"] = list(scene.pixel_transforms)
        payloads = {
            "scene": manifest,
            "cameras": camera_data,
            "keyframes": {"frames": frames},
            "calibration": calibration.to_dict(),
            "check-report": check_report(records, calibration),
            "measurements": {"schema_version": "0.1", "records": [r.to_dict() for r in records]},
        }
        for name, value in payloads.items():
            (stage / f"{name}.json").write_text(json.dumps(value, indent=2, allow_nan=False) + "\n")
        SceneReader(stage).read()
        stage.rename(target)
    except BaseException:
        shutil.rmtree(stage)
        raise
    return SceneReader(target).read()
