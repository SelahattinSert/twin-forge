from __future__ import annotations

import struct

import numpy as np
import pytest

from twinforge.backends.mapanything import (
    _memory_preflight,
    estimate_minimum_xyz_output_bytes,
)
from twinforge.config import KeyframeConfig, TwinForgeConfig
from twinforge.core.coordinates import (
    convert_points_opencv_world_to_twinforge,
    convert_pose_opencv_world_to_twinforge,
)
from twinforge.core.types import (
    Camera,
    ConfidenceSummary,
    DepthMap,
    PointCloud,
    ReconstructionResult,
    ScaleEstimate,
)
from twinforge.export.glb import write_point_glb
from twinforge.export.ply import write_ply
from twinforge.keyframes.quality import (
    hamming_distance,
    measure_exposure,
    measure_sharpness,
    perceptual_hash,
)


def test_config_validation_rejects_invalid_keyframe_bounds():
    config = TwinForgeConfig(keyframes=KeyframeConfig(minimum_keyframes=9, maximum_keyframes=8))
    with pytest.raises(ValueError, match="cannot exceed"):
        config.validate()


def test_config_validation_rejects_unbounded_metrics():
    config = TwinForgeConfig(keyframes=KeyframeConfig(minimum_exposure_score=1.1))
    with pytest.raises(ValueError, match="between 0 and 1"):
        config.validate()


def test_mapanything_memory_preflight_uses_pixel_count_not_generic_frame_guess():
    views = [
        {"img": np.empty((1, 3, 50, 100), dtype=np.float32)},
        {"img": np.empty((1, 3, 100, 200), dtype=np.float32)},
    ]
    # The adapter must use post-load_images inference dimensions, not source JPEG dimensions.
    assert estimate_minimum_xyz_output_bytes(views) == 25000 * 3 * 4


def test_mapanything_memory_preflight_compares_output_floor_with_live_vram():
    from types import SimpleNamespace

    view = {"img": np.empty((1, 3, 50, 100), dtype=np.float32)}
    torch = SimpleNamespace(
        cuda=SimpleNamespace(
            is_available=lambda: True,
            mem_get_info=lambda _device: (1000, 2000),
        )
    )
    report = _memory_preflight([view], torch, "cuda:0")
    assert report["free_vram_bytes"] == 1000
    assert report["xyz_output_exceeds_free_vram"] is True
    assert report["peak_memory_estimate_available"] is False


def test_coordinate_conversion_is_proper_right_handed_rotation():
    source = np.asarray([[1.0, 2.0, 3.0]])
    converted = convert_points_opencv_world_to_twinforge(source)
    np.testing.assert_allclose(converted, [[1, 3, -2]])
    pose = np.eye(4)
    converted_pose = convert_pose_opencv_world_to_twinforge(pose)
    assert np.linalg.det(converted_pose[:3, :3]) == pytest.approx(1.0)
    assert converted_pose[2, 1] == -1


def test_quality_metrics_distinguish_sharp_blurred_and_clipped_images():
    rng = np.random.default_rng(5)
    sharp = rng.integers(0, 256, (128, 160, 3), dtype=np.uint8)
    blurred = __import__("cv2").GaussianBlur(sharp, (21, 21), 8)
    dark = np.full((128, 160, 3), 2, dtype=np.uint8)
    assert measure_sharpness(sharp) > measure_sharpness(blurred)
    assert measure_exposure(dark) < measure_exposure(sharp)
    assert hamming_distance(perceptual_hash(sharp), perceptual_hash(sharp.copy())) == 0


def test_ply_and_glb_export_preserve_point_geometry(tmp_path):
    cloud = PointCloud(
        xyz=np.asarray([[1, 2, 3], [4, 5, 6]], dtype=np.float32),
        rgb=np.asarray([[255, 0, 1], [1, 2, 3]], dtype=np.uint8),
        confidence=np.asarray([0.8, 0.4], dtype=np.float32),
        source_frame_id=np.asarray([1, 2], dtype=np.uint32),
        valid_mask=np.asarray([True, False]),
    )
    ply, glb = tmp_path / "cloud.ply", tmp_path / "cloud.glb"
    write_ply(ply, cloud)
    write_point_glb(glb, cloud)
    ply_content = ply.read_bytes()
    header, first_record = ply_content.split(b"end_header\n", maxsplit=1)
    assert b"format binary_little_endian 1.0" in header
    assert b"element vertex 2" in header
    assert b"property uchar red" in header
    assert b"property float confidence" in header
    assert b"property uint source_frame_id" in header
    assert b"property uchar valid" in header
    assert struct.unpack("<fffBBBfIB", first_record[:24]) == pytest.approx(
        (1.0, 2.0, 3.0, 255, 0, 1, 0.8, 1, 1)
    )
    content = glb.read_bytes()
    assert content[:4] == b"glTF"
    assert int.from_bytes(content[8:12], "little") == len(content)
    json_size = int.from_bytes(content[12:16], "little")
    gltf = __import__("json").loads(content[20 : 20 + json_size])
    assert gltf["accessors"][0]["count"] == 1
    assert gltf["meshes"][0]["primitives"][0]["mode"] == 0
    assert "indices" not in gltf["meshes"][0]["primitives"][0]
    binary_header = 20 + json_size
    assert content[binary_header + 4 : binary_header + 8] == b"BIN\0"
    binary_offset = binary_header + 8
    assert struct.unpack_from("<fff", content, binary_offset) == (1.0, 2.0, 3.0)


def test_result_supports_absent_confidence_and_pose():
    result = ReconstructionResult(
        points=PointCloud(np.empty((0, 3), dtype=np.float32)),
        cameras=[Camera(1, 0.0, None, None)],
        scale=ScaleEstimate("relative", None, None, None),
        confidence=ConfidenceSummary(False),
        backend="fake",
        backend_version=None,
        checkpoint=None,
    )
    assert result.confidence.available is False
    assert result.cameras[0].camera_to_world is None


def test_depth_map_enforces_per_pixel_metadata_shapes():
    values = np.ones((4, 5), dtype=np.float32)
    with pytest.raises(ValueError, match=r"same \(H, W\) shape"):
        DepthMap(1, 0.0, values, valid_mask=np.ones((5, 4), dtype=bool))
