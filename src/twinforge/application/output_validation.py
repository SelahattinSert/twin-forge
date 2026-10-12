"""Production artifact integrity gate. This does not assess physical accuracy."""

import json
import math
from pathlib import Path

import cv2
import numpy as np

from twinforge.scene.reader import SceneReader, sha256_file
from twinforge.viewer.preview import build_preview, encode_bundle


def validate_output(output: Path, job: dict) -> dict:
    root = Path(job["config"]["output"]["root"]).resolve()
    output = output.resolve(strict=True)
    if output == root or not output.is_relative_to(root):
        raise ValueError("Worker output escaped its run directory")
    scene = SceneReader(output).read()
    try:
        manifest = json.loads(scene.manifest_path.read_text())
        run_path = output / "run.json"
        run = json.loads(run_path.read_text())
        backend = job["config"]["backend"]
        if (
            scene.schema_version != "0.2"
            or run.get("status") != "complete"
            or manifest.get("source", {}).get("file") != Path(job["input"]["path"]).name
            or run.get("backend_settings", {}).get("checkpoint") != backend["checkpoint"]
            or run.get("backend_settings", {}).get("checkpoint_revision")
            != backend["checkpoint_revision"]
        ):
            raise ValueError("Output does not match frozen source/checkpoint provenance")
        if not scene.frames or run.get("selected_keyframes") != len(scene.frames):
            raise ValueError("Incomplete selected-frame linkage")
        if run.get("camera_count") != len(scene.cameras):
            raise ValueError("Incomplete camera linkage")
        ids = {frame.frame_id for frame in scene.frames}
        if {item["frame_id"] for item in scene.pixel_transforms} != ids or any(
            item["origin"] != "native" for item in scene.pixel_transforms
        ):
            raise ValueError("Complete native pixel mappings are required")
        for frame, camera in zip(scene.frames, scene.cameras, strict=True):
            if camera.camera_to_world is None or camera.intrinsics is None:
                raise ValueError("Missing camera pose/intrinsics")
            transform = next(
                item for item in scene.pixel_transforms if item["frame_id"] == frame.frame_id
            )
            image = cv2.imread(str(frame.image_path), cv2.IMREAD_COLOR)
            if image is None or image.shape[:2] != (
                transform["source_height"],
                transform["source_width"],
            ):
                raise ValueError("Unreadable frame or raster does not match native pixel mapping")
            del image
        records = scene.point_records
        if not len(records) or not {"source_frame_id", "source_pixel_index", "valid"}.issubset(
            records.dtype.names
        ):
            raise ValueError("Nonempty native point provenance is required")
        valid = 0
        for start in range(0, len(records), 65536):
            block = records[start : start + 65536]
            if not all(np.isfinite(block[name]).all() for name in ("x", "y", "z")):
                raise ValueError("Nonfinite geometry")
            if not np.isin(block["valid"], [0, 1]).all():
                raise ValueError("Invalid point validity values")
            valid += int(block["valid"].sum())
        if valid < 1 or manifest["geometry"].get("valid_point_count") != valid:
            raise ValueError("Invalid valid-point count/ratio")
        scale = scene.scale
        if not {"type", "meters_per_unit", "confidence", "source", "details"}.issubset(scale):
            raise ValueError("Incomplete scale schema")
        if scale["type"] not in {"relative", "estimated_metric"}:
            raise ValueError("Processing cannot claim calibrated or measured scale")
        units, confidence = scale["meters_per_unit"], scale["confidence"]
        if (
            (scale["type"] == "relative" and units is not None)
            or (
                scale["type"] != "relative"
                and (type(units) not in (int, float) or not math.isfinite(units) or units <= 0)
            )
            or (
                confidence is not None
                and (
                    type(confidence) not in (int, float)
                    or not math.isfinite(confidence)
                    or not 0 <= confidence <= 1
                )
            )
            or not isinstance(scale["details"], dict)
        ):
            raise ValueError("Invalid scale values")
        # Built in the supervisor thread, before publication, never the HTTP request loop.
        preview_path = output.parent.parent / "preview.tfp"
        with preview_path.open("wb") as stream:
            stream.write(encode_bundle(build_preview(scene)))
        paths = set(scene.referenced_paths) | {run_path}
        hashes = {str(path.relative_to(output)): sha256_file(path) for path in paths}
        return {
            "source_manifest": str(scene.manifest_path),
            "source_root": str(output),
            "hashes": hashes,
            "thumbnail": str(scene.frames[0].image_path),
            "source_label": "Processed local video",
            "scale_label": "Estimated scale",
            "selected_images": len(scene.frames),
            "point_count": len(records),
            "valid_point_ratio": valid / len(records),
            "actual_device": run.get("device"),
            "resource_adjustment": run.get("memory_adjustment"),
            "preview_path": str(preview_path),
            "preview_sha256": sha256_file(preview_path),
        }
    finally:
        mapping = getattr(scene.point_records, "_mmap", None)
        if mapping is not None:
            mapping.close()
