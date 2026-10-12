"""Disk-backed allowlisted exports and independently validated portable packages."""

from __future__ import annotations

import json
import os
import re
import shutil
import struct
import tempfile
import time
import zipfile
from pathlib import Path, PurePosixPath

from twinforge.application.library import atomic_json
from twinforge.application.types import SCHEMA_VERSION, display_name, new_id, timestamp, validate_id
from twinforge.application.versions import frozen_hashes, validate_version
from twinforge.scene.reader import SceneReader, sha256_file
from twinforge.viewer.archive import read_archive
from twinforge.viewer.service import SceneService, workspace_provenance

SESSION_FILES = (
    "session.json",
    "measurements.json",
    "geometry-evidence.json",
    "visibility.json",
    "calibration.json",
    "check-report.json",
    "pixel-provenance.json",
    "version.json",
)
FROZEN_FILES = ("calibration.json", "check-report.json", "measurements.json")
METADATA_LIMIT = 64 * 1024**2
DESCRIPTOR_LIMIT = 4 * 1024**2
MEMBER_LIMIT = 100000
CENTRAL_DIRECTORY_LIMIT = 32 * 1024**2


class PackagePolicyError(ValueError):
    """The complete package cannot be restored under the application policy."""


def package_limit(reason):
    return PackagePolicyError(
        f"Full package exceeds the {reason} limit. Increase the application package "
        "limits or use a PLY/GLB export."
    )


def check_central_directory(path):
    """Bound ZIP allocation before ZipFile eagerly reads metadata and creates members."""
    size = path.stat().st_size
    with path.open("rb") as stream:
        tail_start = max(0, size - (65535 + 22))
        stream.seek(tail_start)
        tail = stream.read(65535 + 22)
        end = tail.rfind(b"PK\x05\x06")
        if end < 0 or len(tail) - end < 22:
            raise ValueError("Invalid ZIP central directory trailer")
        _, disk, cd_disk, disk_count, count, cd_size, cd_offset, comment = struct.unpack(
            "<4s4H2LH", tail[end : end + 22]
        )
        if end + 22 + comment != len(tail) or disk or cd_disk or disk_count != count:
            raise ValueError("Invalid ZIP central directory trailer")
        cd_end = tail_start + end
        if cd_end >= 20:
            stream.seek(cd_end - 20)
            locator = stream.read(20)
            if locator[:4] == b"PK\x06\x07":
                _, disk, record_offset, disks = struct.unpack("<4sLQL", locator)
                # Match the fixed ZIP64 record supported by Python's parser. Reject
                # extensions/multiple disks instead of interpreting a different directory.
                if disk or disks != 1 or record_offset != cd_end - 76 or record_offset < 0:
                    raise ValueError("Invalid ZIP64 central directory locator")
                stream.seek(record_offset)
                record = stream.read(56)
                (
                    signature,
                    record_size,
                    _,
                    _,
                    disk,
                    cd_disk,
                    disk_count,
                    count,
                    cd_size,
                    cd_offset,
                ) = struct.unpack("<4sQ2H2L4Q", record)
                if (
                    signature != b"PK\x06\x06"
                    or record_size != 44
                    or disk
                    or cd_disk
                    or disk_count != count
                ):
                    raise ValueError("Invalid ZIP64 central directory record")
                cd_end = record_offset
        if cd_size > CENTRAL_DIRECTORY_LIMIT:
            raise package_limit("central directory")
        if count > MEMBER_LIMIT:
            raise package_limit("member count")
        if cd_offset + cd_size != cd_end:
            raise ValueError("Invalid ZIP central directory bounds")
        stream.seek(cd_offset)
        seen = 0
        while stream.tell() < cd_end:
            header = stream.read(46)
            if len(header) != 46 or header[:4] != b"PK\x01\x02":
                raise ValueError("Invalid ZIP central directory member")
            name, extra, comment = struct.unpack_from("<3H", header, 28)
            if stream.tell() + name + extra + comment > cd_end:
                raise ValueError("Invalid ZIP central directory member size")
            stream.seek(name + extra + comment, os.SEEK_CUR)
            seen += 1
            if seen > MEMBER_LIMIT:
                raise package_limit("member count")
        if seen != count:
            raise ValueError("Invalid ZIP central directory member count")


def safe_member(name):
    path = PurePosixPath(name)
    if (
        not isinstance(name, str)
        or not name
        or "\\" in name
        or "\0" in name
        or path.is_absolute()
        or any(p in (".", "..") for p in path.parts)
        or path.as_posix() != name
    ):
        raise ValueError("Invalid portable artifact path")
    return path


class ExportStore:
    def __init__(self, library):
        self.library = library
        self.config = library.config
        self.root = library.root / "exports"
        self.root.mkdir(exist_ok=True)

    def _space(self, required=0):
        if shutil.disk_usage(self.root).free < required + self.config.disk_reserve_bytes:
            raise ValueError("Insufficient disk space for portable artifacts")

    def _check_members(self, members):
        if len(members) > MEMBER_LIMIT:
            raise package_limit("member count")
        total = 0
        for name, size in members:
            if size > self.config.upload_limit:
                raise package_limit("member transfer")
            if name.endswith(".json") and size > METADATA_LIMIT:
                raise package_limit("metadata")
            if name == "package.json" and size > DESCRIPTOR_LIMIT:
                raise package_limit("descriptor")
            total += size
        if total > self.config.upload_quota_bytes:
            raise package_limit("expanded storage")
        if sum(46 + len(name.encode("utf-8")) for name, _ in members) > CENTRAL_DIRECTORY_LIMIT:
            raise package_limit("central directory")
        return total

    def _copy(self, source, destination, maximum, *, set_read_timeout=None):
        """Bound every copy including decompressed ZIP members and HTTP bodies."""
        written = 0
        deadline = time.monotonic() + self.config.transfer_timeout_seconds
        with destination.open("xb") as output:
            while written < maximum:
                remaining_seconds = deadline - time.monotonic()
                if remaining_seconds <= 0:
                    raise ValueError("Artifact transfer timed out")
                self._space()
                if set_read_timeout is not None:
                    set_read_timeout(min(15, remaining_seconds))
                # One underlying receive lets every body chunk use the remaining deadline.
                read = getattr(source, "read1", source.read)
                block = read(min(self.config.transfer_chunk_bytes, maximum - written))
                if time.monotonic() >= deadline:
                    raise ValueError("Artifact transfer timed out")
                if not block:
                    raise ValueError("Truncated artifact transfer")
                if len(block) > maximum - written:
                    raise ValueError("Artifact transfer exceeds declared size")
                output.write(block)
                written += len(block)
            output.flush()
            os.fsync(output.fileno())

    def create(self, scene_id, version_id, kind):
        if kind not in ("ply", "glb", "package"):
            raise ValueError("Unknown export format")
        record = self.library.get(scene_id)
        version = next((v for v in record["versions"] if v["version_id"] == version_id), None)
        if version is None:
            raise ValueError("Unknown version")
        with self.library.request_context(
            scene_id, version["run_id"], version["session_id"], mutation=True
        ) as (run, workspace):
            service = SceneService(SceneReader(run["source_manifest"]).read(), workspace)
            try:
                service.validate_provenance(force=True)
                validate_version(service, version)
                scene = service.derived if version.get("frozen") else service.scene
                if scene is None:
                    raise ValueError("Saved version is unavailable")
                if kind == "glb":
                    path = next((p for p in scene.referenced_paths if p.suffix == ".glb"), None)
                    if path is None:
                        return {
                            "status": "unavailable",
                            "kind": kind,
                            "message": "This version has no point-based GLB export.",
                        }
                else:
                    path = scene.point_cloud_path
                export_id = new_id("export")
                folder = self.root / export_id
                folder.mkdir()
                filename = {"ply": "pointcloud.ply", "glb": "preview.glb", "package": "scene.zip"}[
                    kind
                ]
                candidate = folder / (filename + ".partial")
                if kind == "package":
                    try:
                        self._package(candidate, record, version, run, service)
                    except PackagePolicyError as exc:
                        shutil.rmtree(folder)
                        return {"status": "unavailable", "kind": kind, "message": str(exc)}
                else:
                    self._space(path.stat().st_size)
                    with path.open("rb") as source:
                        self._copy(source, candidate, path.stat().st_size)
                candidate.rename(folder / filename)
                result = {
                    "schema_version": SCHEMA_VERSION,
                    "export_id": export_id,
                    "status": "ready",
                    "kind": kind,
                    "filename": filename,
                    "scene_id": scene_id,
                    "version_id": version_id,
                    "sha256": sha256_file(folder / filename),
                    "bytes": (folder / filename).stat().st_size,
                    "created_at": timestamp(),
                    "contains_source_images": kind == "package",
                    "download_url": f"/api/exports/{export_id}",
                }
                atomic_json(folder / "export.json", result)
                return result
            finally:
                service.close()

    def _package(self, target, record, version, run, service):
        source = service.scene
        paths = {"scene/" + name: Path(run["source_root"]) / name for name in run["hashes"]}
        # The engine's optional run record is provenance, not an arbitrary directory copy.
        engine_record = source.manifest_path.parent / "run.json"
        if engine_record.is_file():
            if not engine_record.resolve().is_relative_to(source.source_root):
                raise ValueError("Engine provenance escapes source")
            if engine_record.stat().st_size > 64 * 1024**2:
                raise ValueError("Engine provenance exceeds metadata limit")
            if not isinstance(json.loads(engine_record.read_text()), dict):
                raise ValueError("Invalid engine provenance record")
            paths["scene/" + str(engine_record.relative_to(source.source_root))] = engine_record
        source_archive = read_archive(source)
        if source_archive["status"] == "unavailable":
            raise ValueError("Source derivation archive is incomplete")
        if source_archive["status"] == "available":
            for name in FROZEN_FILES:
                path = source.manifest_path.parent / name
                paths["scene/" + str(path.relative_to(source.source_root))] = path
        workspace = service.workspace.root
        for name in (*SESSION_FILES, *(i + ".json" for i in service.measurements.list_ids())):
            path = workspace / name
            if path.exists():
                paths["workspace/" + name] = path
        if service.derived:
            if read_archive(service.derived)["status"] != "available":
                raise ValueError("Frozen derived reports are unavailable")
            for path in service.derived.referenced_paths:
                paths["workspace/derived/" + str(path.relative_to(service.derived.source_root))] = (
                    path
                )
            for name in FROZEN_FILES:
                paths["workspace/derived/" + name] = workspace / "derived" / name
        self._space(sum(p.stat().st_size for p in paths.values()))
        with tempfile.TemporaryDirectory(prefix="proofs-", dir=target.parent) as temporary:
            temporary = Path(temporary)
            mapping = workspace_provenance(workspace)
            if mapping is not None:
                for index, proof in enumerate(mapping["evidence_files"]):
                    proof_path = Path(proof["source_path"])
                    local = temporary / f"proof-{index}"
                    if "archive_entry" in proof:
                        with zipfile.ZipFile(proof_path) as archive:
                            item = archive.getinfo(proof["archive_entry"])
                            if item.file_size > self.config.upload_limit:
                                raise ValueError("Proof exceeds package limit")
                            with archive.open(item) as stream:
                                self._copy(stream, local, item.file_size)
                    else:
                        with proof_path.open("rb") as stream:
                            self._copy(stream, local, proof_path.stat().st_size)
                    if sha256_file(local) != proof["source_sha256"]:
                        raise ValueError("Portable proof hash changed")
                    proof.pop("archive_entry", None)
                    proof["source_path"] = f"proofs/{index}.bin"
                    paths[f"workspace/proofs/{index}.bin"] = local
                atomic_json(temporary / "pixel-provenance.json", mapping)
                paths["workspace/pixel-provenance.json"] = temporary / "pixel-provenance.json"
            descriptor = {
                "schema_version": SCHEMA_VERSION,
                "format": "twinforge-scene-package",
                "name": record["name"],
                "contains_source_images": True,
                "scene_manifest": "scene/"
                + str(source.manifest_path.relative_to(source.source_root)),
                "version": version,
                "exported_at": timestamp(),
                "files": {
                    name: {"sha256": sha256_file(path), "bytes": path.stat().st_size}
                    for name, path in paths.items()
                },
            }
            descriptor_bytes = json.dumps(descriptor, allow_nan=False).encode("utf-8")
            self._check_members(
                [("package.json", len(descriptor_bytes))]
                + [(name, path.stat().st_size) for name, path in paths.items()]
            )
            with zipfile.ZipFile(
                target, "w", compression=zipfile.ZIP_STORED, allowZip64=True
            ) as archive:
                archive.writestr("package.json", descriptor_bytes)
                for name, path in paths.items():
                    self._space(path.stat().st_size)
                    archive.write(path, name)
            # The actual ZIP includes local headers, the central directory, and ZIP64 overhead.
            if target.stat().st_size > self.config.upload_limit:
                raise package_limit("archive transfer")
            check_central_directory(target)

    def artifact(self, export_id):
        folder = self.root / validate_id(export_id, "export")
        record = json.loads((folder / "export.json").read_text())
        if record.get("status") != "ready" or record.get("filename") not in {
            "pointcloud.ply",
            "preview.glb",
            "scene.zip",
        }:
            raise ValueError("Unavailable export artifact")
        path = (folder / record["filename"]).resolve(strict=True)
        if not path.is_relative_to(folder) or sha256_file(path) != record["sha256"]:
            raise ValueError("Export artifact changed")
        return path

    def open_package(self, stream, length, *, set_read_timeout=None):
        if type(length) is not int or not 0 < length <= self.config.upload_limit:
            raise ValueError("Package size exceeds transfer policy")
        self._space(length * 2)
        with tempfile.TemporaryDirectory(prefix="open-", dir=self.root) as temporary:
            temporary = Path(temporary)
            upload = temporary / "package.zip"
            self._copy(stream, upload, length, set_read_timeout=set_read_timeout)
            check_central_directory(upload)
            extracted = temporary / "content"
            extracted.mkdir()
            with zipfile.ZipFile(upload) as archive:
                items = archive.infolist()
                total = self._check_members([(i.filename, i.file_size) for i in items])
                if len({i.filename for i in items}) != len(items):
                    raise ValueError("Invalid archive member count")
                for item in items:
                    safe_member(item.filename)
                    if item.is_dir() or (item.external_attr >> 16) & 0o170000 == 0o120000:
                        raise ValueError("Only regular package files are accepted")
                    if item.flag_bits & 1:
                        raise ValueError("Encrypted package members are not supported")
                info = archive.getinfo("package.json")
                with archive.open(info) as source:
                    package = json.loads(source.read(DESCRIPTOR_LIMIT + 1))
                if (
                    package.get("format") != "twinforge-scene-package"
                    or package.get("schema_version") != SCHEMA_VERSION
                ):
                    raise ValueError("Unsupported scene package")
                files = package["files"]
                if set(files) | {"package.json"} != {i.filename for i in items}:
                    raise ValueError("Package contains unlisted or missing files")
                self._space(total)
                for name, binding in files.items():
                    safe_member(name)
                    if not name.startswith(("scene/", "workspace/")) or not re.fullmatch(
                        r"[0-9a-f]{64}", binding["sha256"]
                    ):
                        raise ValueError("Invalid artifact binding")
                    info = archive.getinfo(name)
                    if type(binding["bytes"]) is not int or binding["bytes"] != info.file_size:
                        raise ValueError("Package byte count disagrees")
                    path = extracted / name
                    path.parent.mkdir(parents=True, exist_ok=True)
                    with archive.open(info) as source:
                        self._copy(source, path, info.file_size)
                    if sha256_file(path) != binding["sha256"]:
                        raise ValueError("Package artifact hash disagrees")
            return self._publish(extracted, package)

    def _publish(self, extracted, package):
        safe_member(package["scene_manifest"])
        if not package["scene_manifest"].startswith("scene/"):
            raise ValueError("Scene manifest must belong to the source package")
        scene = SceneReader(extracted / package["scene_manifest"]).read()
        if not scene.source_root.is_relative_to(extracted / "scene"):
            raise ValueError("Package source root escaped")
        workspace = extracted / "workspace"
        # Packages may resolve proof paths only within their own workspace.
        mapping = workspace_provenance(workspace, portable_only=True)
        service = SceneService(scene, workspace)
        try:
            service.validate_provenance(force=True)
            for reference in service.measurements.list_ids():
                service.measurements.load(reference)
            frozen = package["version"].get("frozen", False)
            if frozen:
                if (
                    service.derived is None
                    or read_archive(service.derived)["status"] != "available"
                ):
                    raise ValueError("Portable frozen version is incomplete")
                archived = read_archive(service.derived)
                active_records = [
                    service.measurements.load(i).to_dict() for i in service.measurements.list_ids()
                ]
                archived_records = [item["record"] for item in archived["measurements"]]
                if sorted(active_records, key=lambda r: r["reference_id"]) != sorted(
                    archived_records, key=lambda r: r["reference_id"]
                ):
                    raise ValueError("Frozen observations disagree with the saved derivation")
                for name in ("calibration.json", "check-report.json"):
                    if json.loads((workspace / name).read_text()) != json.loads(
                        (workspace / "derived" / name).read_text()
                    ):
                        raise ValueError("Portable reports disagree with immutable derivation")
        finally:
            service.close()
        scene_id, run_id, session_id, version_id = (
            new_id(k) for k in ("scene", "run", "session", "version")
        )
        base = self.library.root / "scenes" / scene_id / "runs" / run_id
        base.mkdir(parents=True)
        destination = base / "package"
        (base / "workspaces").mkdir()
        shutil.move(str(workspace), base / "workspaces" / session_id)
        shutil.move(str(extracted / "scene"), destination)
        manifest = destination / Path(package["scene_manifest"]).relative_to("scene")
        restored = SceneReader(manifest).read()
        version = {
            "version_id": version_id,
            "run_id": run_id,
            "session_id": session_id,
            "label": display_name(package["version"]["label"]),
            "frozen": frozen,
            "imported_lineage": package["version"],
        }
        if frozen:
            version["frozen_files"] = frozen_hashes(base / "workspaces" / session_id)
        run = {
            "schema_version": SCHEMA_VERSION,
            "scene_id": scene_id,
            "run_id": run_id,
            "session_ids": [session_id],
            "owned_package": True,
            "source_root": str(restored.source_root),
            "source_manifest": str(manifest),
            "hashes": {
                str(p.relative_to(restored.source_root)): sha256_file(p)
                for p in restored.referenced_paths
            },
            "source_label": "Restored local package",
            "scale_label": "Saved version",
            "thumbnail": str(restored.frames[0].image_path) if restored.frames else None,
        }
        if mapping is not None:
            run["mapping_sha256"] = sha256_file(
                base / "workspaces" / session_id / "pixel-provenance.json"
            )
        record = {
            "schema_version": SCHEMA_VERSION,
            "scene_id": scene_id,
            "name": display_name(package["name"]),
            "created_at": timestamp(),
            "updated_at": timestamp(),
            "archived": False,
            "source_kind": "package",
            "default_run_id": run_id,
            "default_session_id": session_id,
            "default_version_id": version_id,
            "versions": [version],
        }
        atomic_json(base / "run.json", run)
        atomic_json(self.library._scene_path(scene_id), record)
        return self.library.summary(record)
