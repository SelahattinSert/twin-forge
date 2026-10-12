"""Synthetic test fixtures. Never imported by application production code."""

import hashlib
import time
from pathlib import Path

import cv2
import numpy as np

from twinforge.application.library import atomic_json
from twinforge.application.readiness import profile_settings
from twinforge.application.types import new_id

WORKER = Path(__file__).parent / "fixtures/job_worker.py"


def managed_scene(library):
    upload = library.root / "uploads" / new_id("upload")
    upload.mkdir(parents=True)
    video = upload / "original.mp4"
    video.write_bytes(b"synthetic managed original; not a video or neural reconstruction")
    assert cv2.imwrite(
        str(upload / "candidate_000001.jpg"), np.full((2, 2, 3), (0, 0, 255), dtype=np.uint8)
    )
    receipt = {
        "scene_id": new_id("scene"),
        "media_id": new_id("media"),
        "extension": ".mp4",
        "client_name": "Test only.mp4",
        "expected_bytes": video.stat().st_size,
        "sha256": hashlib.sha256(video.read_bytes()).hexdigest(),
    }
    return library.register_media(
        receipt,
        video,
        {"decode_ready": True, "preview": "candidate_000001.jpg"},
        "Synthetic fixture",
        profile_settings(),
    )


def cached_source(config):
    repo = config.torch_home / "hub/facebookresearch_dinov2_main"
    repo.mkdir(parents=True, exist_ok=True)
    (repo / "hubconf.py").write_text("# Dependency double only\n")


def wait_for(manager, job_id, states, timeout=10):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        result = manager.get(job_id)
        if result["state"] in states:
            return result
        time.sleep(0.02)
    raise AssertionError(manager.get(job_id))


def successful_output(job, *, invalid=None):
    from twinforge.core.types import PointCloud
    from twinforge.export.ply import write_ply
    from twinforge.scene.provenance import PixelTransform

    output = Path(job["config"]["output"]["root"]) / "actual-engine-return"
    output.mkdir(parents=True)
    assert cv2.imwrite(
        str(output / "frame.jpg"), np.full((2, 2, 3), (130, 120, 100), dtype=np.uint8)
    )
    points = PointCloud(
        xyz=np.array([[0, 0, 0], [1, 2, 3]], dtype=np.float32),
        rgb=np.array([[100, 120, 130]] * 2, dtype=np.uint8),
        source_frame_id=np.array([1, 1], dtype=np.uint32),
        source_pixel_index=np.array([0, 1], dtype=np.uint32),
        valid_mask=np.array([True, True]),
    )
    if invalid == "finite":
        points.xyz[0, 0] = np.nan
    if invalid == "pixels":
        points.source_pixel_index[0] = 100
    write_ply(output / "pointcloud.ply", points)
    atomic_json(
        output / "cameras.json",
        {
            "cameras": [
                {
                    "frame_id": 99 if invalid == "camera" else 1,
                    "timestamp_seconds": 0.0,
                    "intrinsics": np.eye(3).tolist(),
                    "camera_to_world": np.eye(4).tolist(),
                    "image_width": 2,
                    "image_height": 2,
                }
            ]
        },
    )
    atomic_json(
        output / "keyframes.json",
        {
            "frames": [
                {
                    "frame_id": 1,
                    "timestamp_seconds": 0.0,
                    "image_path": "frame.jpg",
                    "width": 2,
                    "height": 2,
                }
            ]
        },
    )
    atomic_json(output / "quality.json", {"warnings": []})
    atomic_json(
        output / "run.json",
        {
            "status": "complete",
            "selected_keyframes": 1,
            "camera_count": 1,
            "backend_settings": job["config"]["backend"],
            "device": "cpu",
            "memory_adjustment": {"reason": None, "used_keyframes": 1},
        },
    )
    manifest = {
        "schema_version": "0.2",
        "source": {"file": Path(job["input"]["path"]).name},
        "geometry": {"point_cloud": "pointcloud.ply", "point_count": 2, "valid_point_count": 2},
        "cameras": "cameras.json",
        "keyframes": "keyframes.json",
        "quality": "quality.json",
        "scale": {
            "type": "relative",
            "meters_per_unit": None,
            "confidence": None,
            "source": None,
            "details": {},
        },
        "pixel_transforms": [PixelTransform(1, 2, 2, 2, 2, (0, 0, 2, 2), "native").to_dict()],
    }
    if invalid == "count":
        manifest["geometry"]["valid_point_count"] = 3
    if invalid == "mapping":
        manifest["pixel_transforms"] = []
    if invalid == "scale":
        manifest["scale"].update(type="estimated_metric", meters_per_unit=-1)
    atomic_json(output / "scene.json", manifest)
    return output
