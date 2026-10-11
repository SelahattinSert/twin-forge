"""Per-artifact viewer operations independent of HTTP or application routing."""

from __future__ import annotations

import json
import time
from dataclasses import asdict
from pathlib import Path
from types import SimpleNamespace

from twinforge.measurements.calibration import fit_uniform_scale
from twinforge.measurements.storage import MeasurementStore
from twinforge.scene.derive import derive_scene
from twinforge.scene.provenance import attach_verified_provenance
from twinforge.scene.reader import SceneReader, sha256_file
from twinforge.scene.types import SceneArtifact
from twinforge.viewer.archive import read_archive
from twinforge.viewer.preview import build_preview, encode_bundle
from twinforge.viewer.thumbnails import ThumbnailCache


def workspace_provenance(workspace: Path, *, portable_only=False):
    """Resolve portable proof references from their workspace, never process cwd."""
    path = workspace / "pixel-provenance.json"
    if not path.exists():
        return None
    value = json.loads(path.read_text())
    for proof in value["evidence_files"]:
        source = Path(proof["source_path"])
        if source.is_absolute():
            if portable_only:
                raise ValueError("Portable evidence cannot require an external path")
        else:
            source = (workspace / source).resolve(strict=True)
            if not source.is_relative_to(workspace.resolve()):
                raise ValueError("Portable evidence escapes workspace")
        proof["source_path"] = str(source)
    return value


class ViewerWorkspace:
    """Guard future annotation/export paths; Package 1 has no HTTP write route."""

    def __init__(self, path: Path, scene: SceneArtifact):
        self.root = path.resolve()
        self.source_root = scene.source_root.resolve()
        if self.root.is_relative_to(self.source_root) or self.source_root.is_relative_to(self.root):
            raise ValueError("Viewer workspace must be separate from the source scene directory")
        self.root.mkdir(parents=True, exist_ok=True)

    def write_path(self, relative: str) -> Path:
        if not relative or Path(relative).is_absolute():
            raise ValueError("Workspace paths must be relative")
        path = (self.root / relative).resolve()
        if path == self.root or not path.is_relative_to(self.root):
            raise ValueError("Path escapes viewer workspace")
        if path.is_relative_to(self.source_root):
            raise ValueError("Cannot overwrite source scene artifacts")
        return path


class SceneService:
    def __init__(
        self,
        scene: SceneArtifact,
        workspace: Path,
        api_prefix: str = "/api",
        *,
        import_archive: bool = True,
        prepared_preview: bytes | None = None,
    ):
        self.api_prefix = api_prefix
        self.scene = scene
        self.workspace = ViewerWorkspace(workspace, scene)
        provenance_path = self.workspace.write_path("pixel-provenance.json")
        self._provenance_digest = sha256_file(provenance_path) if provenance_path.exists() else None
        self._proof_signature = None
        if provenance_path.exists():
            scene = attach_verified_provenance(scene, workspace_provenance(self.workspace.root))
            self.scene = scene
        self.measurements = MeasurementStore(self.workspace.root, scene)
        self.archive = (
            read_archive(scene)
            if import_archive
            else {
                "status": "not_imported",
                "references": [],
            }
        )
        started = time.monotonic()
        if prepared_preview is None:
            self.preview = build_preview(scene)
            self.preview_bytes = encode_bundle(self.preview)
        else:
            import struct

            if prepared_preview[:4] != b"TFP1":
                raise ValueError("Invalid prepared preview")
            size = struct.unpack("<I", prepared_preview[4:8])[0]
            header = json.loads(prepared_preview[8 : 8 + size])
            self.preview = SimpleNamespace(
                point_count=header["count"], eligible_point_count=header["eligible_point_count"]
            )
            self.preview_bytes = prepared_preview
        self.preview_seconds = time.monotonic() - started
        self.frames = {frame.frame_id: frame for frame in scene.frames}
        self.thumbnails = ThumbnailCache()
        derived_path = self.workspace.write_path("derived/scene.json")
        self.derived = SceneReader(derived_path).read() if derived_path.exists() else None
        self.derived_preview_bytes = (
            encode_bundle(build_preview(self.derived)) if self.derived is not None else None
        )

    def validate_provenance(self, *, force=False):
        path = self.workspace.write_path("pixel-provenance.json")
        digest = sha256_file(path) if path.exists() else None
        if digest != self._provenance_digest:
            raise ValueError("The session pixel mapping changed after opening")
        if digest is None:
            return
        value = workspace_provenance(self.workspace.root)
        signature = []
        for proof in value["evidence_files"]:
            stat = Path(proof["source_path"]).stat()
            signature.append(
                (stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns)
            )
        if force or signature != self._proof_signature:
            attach_verified_provenance(self.scene, value)
            self._proof_signature = signature

    def close(self):
        """Release display buffers and read-only file mappings after the last lease."""
        self.thumbnails.clear()
        for scene in (self.scene, self.derived):
            mapping = getattr(getattr(scene, "point_records", None), "_mmap", None)
            if mapping is not None:
                mapping.close()
        self.preview_bytes = self.derived_preview_bytes = None
        self.preview = self.scene = self.derived = None

    def calibrate(self, value):
        # Freeze and publish under the existing workspace transaction lock.
        with self.measurements._lock:
            record = self.measurements.load(value["reference_id"])
            calibration = fit_uniform_scale(
                record,
                value["physical_value"],
                value["physical_unit"],
                original_scale=self.scene.scale,
                measurement_tolerance=value.get("measurement_tolerance"),
            )
            records = tuple(self.measurements.load(i) for i in self.measurements.list_ids())
            self.derived = derive_scene(
                self.scene, calibration, self.workspace.write_path("derived"), records=records
            )
            self.measurements.save_calibration(calibration)
            report = json.loads(
                (self.derived.manifest_path.parent / "check-report.json").read_text()
            )
            self.measurements._write("check-report", report)
            self.derived_preview_bytes = encode_bundle(build_preview(self.derived))
            return {"calibration": calibration.to_dict(), "check_report": report}

    def metadata(self, scene: SceneArtifact | None = None) -> dict:
        scene = self.scene if scene is None else scene
        is_source = scene is self.scene
        preview = self.preview if is_source else build_preview(scene)
        prefix = self.api_prefix if is_source else f"{self.api_prefix}/derived"
        measurements = self.measurements.summary()
        return {
            "schema_version": "0.1",
            "source_schema_version": scene.schema_version,
            "name": scene.manifest_path.parent.name,
            "manifest_sha256": scene.manifest_sha256,
            "point_cloud_sha256": scene.point_cloud_sha256,
            "coordinate_system": scene.coordinate_system,
            "scale": scene.scale,
            "confidence": scene.confidence,
            "usage_status": "partially_checked"
            if is_source and measurements["reference_count"]
            else scene.usage_status,
            "geometry_evidence": "per_reference",
            "archive_status": self.archive["status"],
            **measurements,
            "original_point_count": scene.point_count,
            "displayed_point_count": preview.point_count,
            "eligible_point_count": preview.eligible_point_count,
            "preview_seconds": self.preview_seconds if is_source else None,
            **(
                {
                    "source_scene": {
                        "manifest_sha256": self.scene.manifest_sha256,
                        "point_cloud_sha256": self.scene.point_cloud_sha256,
                    }
                }
                if not is_source
                else {}
            ),
            "point_provenance_available": "source_frame_id" in scene.point_records.dtype.names,
            "pixel_provenance_available": "source_pixel_index" in scene.point_records.dtype.names
            or scene.derived_pixel_indices is not None,
            "source_to_model_mapping_available": bool(scene.pixel_transforms)
            and (
                "source_pixel_index" in scene.point_records.dtype.names
                or scene.derived_pixel_indices is not None
            ),
            "pixel_transforms": list(scene.pixel_transforms),
            "provenance_evidence": scene.provenance_evidence,
            "derived_available": self.derived is not None,
            "cameras": [asdict(camera) for camera in scene.cameras],
            "frames": [
                {
                    "frame_id": frame.frame_id,
                    "timestamp_seconds": frame.timestamp_seconds,
                    "source_frame_index": frame.source_frame_index,
                    "width": frame.width,
                    "height": frame.height,
                    "image_url": f"{self.api_prefix}/frames/{frame.frame_id}/image",
                    "thumbnail_url": f"{self.api_prefix}/frames/{frame.frame_id}/thumbnail",
                    "points_url": f"{prefix}/frames/{frame.frame_id}/points",
                }
                for frame in scene.frames
            ],
        }
