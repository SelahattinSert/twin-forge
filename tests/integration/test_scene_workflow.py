"""Offline fake-backend acceptance of the persisted measurement/export workflow."""

import cv2
import numpy as np
import pytest
from test_fake_backend_pipeline import FakeBackend

from twinforge.core.types import PointCloud, VideoMetadata
from twinforge.ingest.video import CandidateFrame, VideoIngestor
from twinforge.measurements.calibration import fit_uniform_scale
from twinforge.measurements.consistency import evaluate_observations
from twinforge.measurements.observations import measure_segment, resolve_image_pixel
from twinforge.measurements.storage import MeasurementStore
from twinforge.measurements.types import MeasurementRecord
from twinforge.scene.derive import derive_scene
from twinforge.scene.provenance import PixelTransform
from twinforge.scene.reader import SceneReader, sha256_file


def test_saved_scene_source_pixels_calibration_export_and_reopen(tmp_path, monkeypatch):
    # Reuse the actual orchestrator/selector/serializer fixture, replacing only its backend output.
    original = FakeBackend.reconstruct

    def grid_backend(self, frames, context):
        result = original(self, frames, context)
        xyz = np.array(
            [[0 if x < 6 else 2, 0, 1] for y in range(7) for x in range(13)], dtype=np.float32
        )
        result.points = PointCloud(
            xyz=np.tile(xyz, (len(frames), 1)),
            source_frame_id=np.repeat([f.frame_id for f in frames], len(xyz)).astype(np.uint32),
            source_pixel_index=np.tile(np.arange(len(xyz), dtype=np.uint32), len(frames)),
            valid_mask=np.ones(len(xyz) * len(frames), dtype=bool),
        )
        result.pixel_transforms = [
            PixelTransform(f.frame_id, 320, 240, 13, 7, (0, 0, 13, 7), "native").to_dict()
            for f in frames
        ]
        return result

    monkeypatch.setattr(FakeBackend, "reconstruct", grid_backend)
    from twinforge.config import BackendConfig, KeyframeConfig, OutputConfig, TwinForgeConfig
    from twinforge.reconstruction.orchestrator import ReconstructionOrchestrator

    video = tmp_path / "walkthrough.mp4"
    video.touch()
    metadata = VideoMetadata(str(video), "mp4", "h264", 320, 240, 30, 3, 0, 90, 320, 240)
    base = np.random.default_rng(10).integers(0, 256, (240, 320, 3), dtype=np.uint8)
    candidates = []
    for index in range(3):
        path = tmp_path / f"candidate_{index}.jpg"
        assert cv2.imwrite(str(path), np.roll(base, index * 12, axis=1))
        candidates.append(CandidateFrame(index * 30, float(index), path, 320, 240))
    monkeypatch.setattr(VideoIngestor, "inspect", lambda *_: metadata)
    monkeypatch.setattr(VideoIngestor, "decode_candidates", lambda *_: candidates)
    config = TwinForgeConfig(
        keyframes=KeyframeConfig(
            maximum_keyframes=3, minimum_keyframes=2, minimum_feature_overlap=0, minimum_novelty=0
        ),
        backend=BackendConfig(device="cpu", maximum_keyframes=3),
        output=OutputConfig(root=tmp_path / "workflow-output"),
    )
    root = ReconstructionOrchestrator(FakeBackend(), config).run(video)
    source = SceneReader(root).read()
    protected = {p: sha256_file(p) for p in source.referenced_paths}
    store = MeasurementStore(tmp_path / "workspace", source)
    observations = []
    for frame in source.frames[:2]:
        assert cv2.imread(str(frame.image_path)).shape[:2] == (240, 320)
        transform = PixelTransform(frame.frame_id, 320, 240, 13, 7, (0, 0, 13, 7), "native")
        pixels = tuple(tuple(transform.model_to_source(p)) for p in ((2, 3), (10, 3)))
        indices = tuple(resolve_image_pixel(source, frame.frame_id, p) for p in pixels)
        observation = measure_segment(
            source,
            indices,
            reference_id="door-width",
            selection_origin="image_pick",
            source_pixels=pixels,
            correspondence_state="identified",
        )
        assert observation.length == 2
        assert observation.point_indices == indices
        assert observation.source_view_sha256 == sha256_file(frame.image_path)
        observations.append(observation)
    record = MeasurementRecord("door-width", "width", tuple(observations), role="calibration")
    assert evaluate_observations(record.observations).calibration_qualified
    store.save(record)
    restored = MeasurementStore(store.root, source).load("door-width")
    assert restored == record
    fitted = fit_uniform_scale(restored, 82, "cm", original_scale=source.scale)
    assert fitted.scalar == pytest.approx(0.41)
    store.save_calibration(fitted)
    derived = derive_scene(source, fitted, tmp_path / "derived", records=(restored,))
    reopened = SceneReader(derived.manifest_path).read()
    assert reopened.scale["type"] == "calibrated_metric"
    assert reopened.usage_status == "partially_checked"
    for axis in ("x", "y", "z"):
        np.testing.assert_allclose(reopened.point_records[axis], source.point_records[axis] * 0.41)
    np.testing.assert_array_equal(
        reopened.point_records["source_pixel_index"], source.point_records["source_pixel_index"]
    )
    assert {p: sha256_file(p) for p in source.referenced_paths} == protected
