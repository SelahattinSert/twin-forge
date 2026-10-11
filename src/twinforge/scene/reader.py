"""Strict import of TwinForge 0.1 and the explicit original-source experiment."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np

from twinforge.core.types import Camera
from twinforge.exceptions import TwinForgeError
from twinforge.scene.types import SceneArtifact, SceneFrame


class SceneReadError(TwinForgeError):
    """A saved scene is malformed, unsupported, or escapes its source root."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _reject_nonfinite(value: str) -> None:
    raise ValueError(f"Nonfinite JSON number: {value}")


def _json(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"), parse_constant=_reject_nonfinite)
        if not isinstance(value, dict):
            raise TypeError("expected a JSON object")
        return value
    except (OSError, ValueError, TypeError) as exc:
        raise SceneReadError(f"Could not read {path}: {exc}") from exc


def _reference(directory: Path, reference: str, root: Path) -> Path:
    if not isinstance(reference, str) or not reference or Path(reference).is_absolute():
        raise SceneReadError(f"Invalid relative artifact reference: {reference!r}")
    path = (directory / reference).resolve()
    if not path.is_relative_to(root):
        raise SceneReadError(f"Artifact reference escapes source root: {reference}")
    if not path.is_file():
        raise SceneReadError(f"Missing referenced file: {path}")
    return path


_PLY_TYPES = {
    "char": "i1",
    "int8": "i1",
    "uchar": "u1",
    "uint8": "u1",
    "short": "<i2",
    "int16": "<i2",
    "ushort": "<u2",
    "uint16": "<u2",
    "int": "<i4",
    "int32": "<i4",
    "uint": "<u4",
    "uint32": "<u4",
    "float": "<f4",
    "float32": "<f4",
    "double": "<f8",
    "float64": "<f8",
}


def read_point_records(path: Path) -> np.ndarray:
    """Map a vertex-only binary PLY by property names, including unknown scalars."""
    fields = []
    count = None
    with path.open("rb") as stream:
        if stream.readline() != b"ply\n":
            raise SceneReadError("Expected a PLY header")
        if stream.readline().strip() != b"format binary_little_endian 1.0":
            raise SceneReadError("Only binary_little_endian PLY 1.0 is supported")
        for _ in range(1024):
            raw = stream.readline(4096)
            if not raw or len(raw) >= 4096:
                raise SceneReadError("Invalid or truncated PLY header")
            try:
                line = raw.decode("ascii").strip().split()
            except UnicodeDecodeError as exc:
                raise SceneReadError("PLY header must be ASCII") from exc
            if not line or line[0] in ("comment", "obj_info"):
                continue
            if line[0] == "end_header":
                break
            if line[0] == "element":
                if len(line) != 3 or line[1] != "vertex" or count is not None:
                    raise SceneReadError("Only one vertex element is supported")
                try:
                    count = int(line[2])
                except ValueError as exc:
                    raise SceneReadError("Invalid PLY vertex count") from exc
            elif line[0] == "property":
                if count is None or len(line) != 3 or line[1] not in _PLY_TYPES:
                    raise SceneReadError("Unsupported PLY property (scalar fields required)")
                if line[2] in [name for name, _ in fields]:
                    raise SceneReadError(f"Duplicate PLY property: {line[2]}")
                fields.append((line[2], _PLY_TYPES[line[1]]))
            else:
                raise SceneReadError(f"Unsupported PLY header line: {' '.join(line)}")
        else:
            raise SceneReadError("PLY header is too long")
        offset = stream.tell()
    if count is None or count < 0 or not {"x", "y", "z"}.issubset(dict(fields)):
        raise SceneReadError("PLY requires a nonnegative vertex count and x/y/z properties")
    dtype = np.dtype(fields)
    if path.stat().st_size != offset + count * dtype.itemsize:
        raise SceneReadError("PLY byte length does not match vertex count and properties")
    if count == 0:
        records = np.empty(0, dtype=dtype)
        records.flags.writeable = False
        return records
    return np.memmap(path, dtype=dtype, mode="r", offset=offset, shape=(count,))


class SceneReader:
    def __init__(self, path: Path | str | None = None):
        self.path = Path(path) if path is not None else None

    def read(self, path: Path | str | None = None) -> SceneArtifact:
        selected = Path(path) if path is not None else self.path
        if selected is None:
            raise SceneReadError("A scene directory or scene.json path is required")
        manifest_path = (selected / "scene.json" if selected.is_dir() else selected).resolve()
        manifest = _json(manifest_path)
        version = manifest.get("schema_version")
        if version not in ("0.1", "0.2", "experimental-original-source-0.1"):
            raise SceneReadError(f"Unsupported scene schema: {version!r}")
        directory = manifest_path.parent
        experimental = version == "experimental-original-source-0.1"
        # Explicit historical layout: scene/ with sibling frames/ and a root PLY.
        root = directory.parent if experimental and directory.name == "scene" else directory
        geometry = manifest if experimental else manifest.get("geometry", {})
        if not isinstance(geometry, dict):
            raise SceneReadError("Scene geometry must be an object")
        point_reference = geometry.get("point_cloud")
        point_root = root if experimental and point_reference == "../pointcloud.ply" else directory
        point_path = _reference(directory, point_reference, point_root)
        camera_path = _reference(directory, manifest.get("cameras", "cameras.json"), directory)
        frames_path = _reference(directory, manifest.get("keyframes", "keyframes.json"), directory)
        references = [manifest_path, point_path, camera_path, frames_path]
        for _name, reference in (
            ("preview", geometry.get("preview")),
            ("depth_maps", geometry.get("depth_maps")),
            ("quality", manifest.get("quality")),
        ):
            if reference is not None:
                references.append(_reference(directory, reference, directory))
        camera_data = _json(camera_path)
        frame_data = _json(frames_path)
        convention = camera_data.get("pose_convention")
        if convention is not None and not (
            isinstance(convention, str) and convention.split(";")[0].strip() == "camera_to_world"
        ):
            raise SceneReadError(f"Unsupported camera pose convention: {convention!r}")
        try:
            cameras = tuple(Camera(**item) for item in camera_data["cameras"])
            frames = tuple(
                SceneFrame(
                    frame_id=item["frame_id"],
                    timestamp_seconds=item["timestamp_seconds"],
                    image_path=_reference(directory, item["image_path"], root),
                    source_frame_index=item.get("source_frame_index"),
                    width=item.get("width"),
                    height=item.get("height"),
                )
                for item in frame_data["frames"]
            )
        except (KeyError, TypeError) as exc:
            raise SceneReadError(f"Invalid cameras/keyframes: {exc}") from exc
        for frame in frames:
            if not frame.image_path.is_relative_to(
                directory
            ) and not frame.image_path.is_relative_to(root / "frames"):
                raise SceneReadError(
                    "Experimental image reference must stay inside sibling frames/"
                )
        for label, items in (("camera", cameras), ("frame", frames)):
            ids = [item.frame_id for item in items]
            if any(type(value) is not int or value < 0 for value in ids) or len(set(ids)) != len(
                ids
            ):
                raise SceneReadError(f"Invalid or duplicate {label} IDs")
            try:
                if any(not np.isfinite(item.timestamp_seconds) for item in items):
                    raise SceneReadError(f"Nonfinite {label} timestamp")
            except TypeError as exc:
                raise SceneReadError(f"Invalid {label} timestamp") from exc
        if {c.frame_id for c in cameras} != {f.frame_id for f in frames}:
            raise SceneReadError("Camera and frame IDs do not match")
        for camera in cameras:
            for name, shape in (("intrinsics", (3, 3)), ("camera_to_world", (4, 4))):
                matrix = getattr(camera, name)
                if matrix is not None:
                    try:
                        array = np.asarray(matrix, dtype=float)
                    except (ValueError, TypeError) as exc:
                        raise SceneReadError(f"Invalid camera {name}") from exc
                    if array.shape != shape or not np.isfinite(array).all():
                        raise SceneReadError(f"Invalid camera {name}")
                    if name == "camera_to_world" and not np.allclose(array[3], [0, 0, 0, 1]):
                        raise SceneReadError("Camera pose requires a homogeneous last row")
                    if name == "intrinsics" and (array[0, 0] <= 0 or array[1, 1] <= 0):
                        raise SceneReadError("Camera focal lengths must be positive")
            for name in ("image_width", "image_height"):
                value = getattr(camera, name)
                if value is not None and (type(value) is not int or value <= 0):
                    raise SceneReadError(f"Invalid camera {name}")
        try:
            records = read_point_records(point_path)
        except OSError as exc:
            raise SceneReadError(f"Could not read PLY: {exc}") from exc
        if geometry.get("point_count") is not None and geometry["point_count"] != len(records):
            raise SceneReadError("Manifest point count does not match PLY")
        if "source_frame_id" in records.dtype.names:
            unknown = set(np.unique(records["source_frame_id"]).tolist()) - {
                f.frame_id for f in frames
            }
            if unknown:
                raise SceneReadError(f"PLY references unknown source frame IDs: {sorted(unknown)}")
        references.extend(frame.image_path for frame in frames)
        coordinate = manifest.get("coordinate_system", camera_data.get("coordinate_system", {}))
        if not isinstance(coordinate, (dict, str)) or not isinstance(manifest.get("scale"), dict):
            raise SceneReadError("Scene coordinate system and scale are invalid")
        scene = SceneArtifact(
            manifest_path=manifest_path,
            manifest_sha256=sha256_file(manifest_path),
            schema_version=version,
            source_root=root,
            point_cloud_path=point_path,
            point_cloud_sha256=sha256_file(point_path),
            point_records=records,
            coordinate_system=coordinate,
            scale=manifest["scale"],
            confidence=manifest.get("confidence", {}),
            cameras=cameras,
            frames=frames,
            referenced_paths=tuple(dict.fromkeys(references)),
            usage_status=manifest.get("usage_status", "visualization_only"),
            pixel_transforms=tuple(manifest.get("pixel_transforms", [])),
        )
        from twinforge.scene.provenance import validate_pixel_transforms

        try:
            transforms = validate_pixel_transforms(scene, manifest.get("pixel_transforms", []))
            if "source_pixel_index" in records.dtype.names:
                if (
                    records["source_pixel_index"].dtype.kind not in "iu"
                    or "source_frame_id" not in records.dtype.names
                ):
                    raise ValueError(
                        "Pixel provenance requires integer pixel IDs and source frames"
                    )
                for item in transforms:
                    selected = records["source_pixel_index"][
                        records["source_frame_id"] == item["frame_id"]
                    ]
                    width = item["crop_bbox"][2] - item["crop_bbox"][0]
                    height = item["crop_bbox"][3] - item["crop_bbox"][1]
                    if (
                        (selected < 0).any()
                        or (selected >= width * height).any()
                        or len(np.unique(selected)) != len(selected)
                    ):
                        raise ValueError(
                            "Pixel provenance IDs must be unique and inside the model grid"
                        )
        except (TypeError, KeyError, ValueError) as exc:
            raise SceneReadError(f"Invalid pixel provenance: {exc}") from exc
        from dataclasses import replace

        return replace(scene, pixel_transforms=transforms)
