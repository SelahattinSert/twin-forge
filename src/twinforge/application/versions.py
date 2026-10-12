"""New source-bound sessions for immutable calibrated versions."""

import shutil
from pathlib import Path

from twinforge.application.library import atomic_json
from twinforge.application.types import SCHEMA_VERSION, display_name, new_id, timestamp
from twinforge.scene.reader import SceneReader, sha256_file
from twinforge.viewer.archive import read_archive
from twinforge.viewer.service import SceneService


def frozen_hashes(workspace):
    paths = [
        p
        for p in workspace.glob("*.json")
        if p.name not in ("version.json", "pixel-provenance.json")
    ]
    paths.extend(p for p in (workspace / "derived").rglob("*") if p.is_file())
    return {str(p.relative_to(workspace)): sha256_file(p) for p in paths}


def validate_version(service, version):
    if not version.get("frozen"):
        return
    hashes = version.get("frozen_files")
    if not hashes:
        raise ValueError("Frozen version binding is unavailable")
    signature = []
    for name, digest in hashes.items():
        if Path(name).is_absolute() or ".." in Path(name).parts:
            raise ValueError("Invalid frozen artifact name")
        path = service.workspace.write_path(name)
        stat = path.stat()
        signature.append(
            (name, digest, stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns)
        )
    if getattr(service, "_frozen_signature", None) != signature:
        for name, digest in hashes.items():
            if sha256_file(service.workspace.write_path(name)) != digest:
                raise ValueError("Frozen version artifacts changed")
        service._frozen_signature = signature


def create_version(library, scene_id, run_id, session_id, source_service, value):
    """Caller holds the library context lock and the shared heavy-operation slot."""
    record = library.get(scene_id)
    parent = next(v for v in record["versions"] if v["session_id"] == session_id)
    run = library.run(scene_id, run_id)
    session, version_id = new_id("session"), new_id("version")
    workspace = source_service.workspace.root.parent / session
    workspace.mkdir()
    service = None
    try:
        required = sum(p.stat().st_size for p in source_service.scene.referenced_paths) * 3
        if shutil.disk_usage(workspace).free < required + library.config.disk_reserve_bytes:
            raise ValueError("Insufficient disk space for a calibrated version")
        label = display_name(value.get("label", f"Calibrated version {len(record['versions'])}"))
        for name in ("pixel-provenance.json", "proofs"):
            path = source_service.workspace.root / name
            if path.is_dir():
                shutil.copytree(path, workspace / name)
            elif path.is_file():
                shutil.copyfile(path, workspace / name)
        service = SceneService(SceneReader(run["source_manifest"]).read(), workspace)
        with source_service.measurements._lock:
            for reference in source_service.measurements.list_ids():
                service.measurements.save(source_service.measurements.load(reference))
            visibility = source_service.measurements.load_visibility()
            service.measurements.save_visibility(
                {key: visibility[key] for key in ("hidden_frame_ids", "hidden_rois")}
            )
        result = service.calibrate(value)
        archive = read_archive(service.derived)
        if archive["status"] != "available":
            raise ValueError("Derived frozen archive did not validate")
        version = {
            "version_id": version_id,
            "run_id": run_id,
            "session_id": session,
            "parent_version_id": parent["version_id"],
            "source_version_id": parent.get("source_version_id", parent["version_id"]),
            "label": label,
            "frozen": True,
            "created_at": timestamp(),
            "manifest_sha256": service.derived.manifest_sha256,
            "point_cloud_sha256": service.derived.point_cloud_sha256,
            "frozen_files": frozen_hashes(workspace),
        }
        atomic_json(workspace / "version.json", {"schema_version": SCHEMA_VERSION, **version})
        run["session_ids"].append(session)
        atomic_json(workspace.parent.parent / "run.json", run)
        record["versions"].append(version)
        record["updated_at"] = timestamp()
        atomic_json(library._scene_path(scene_id), record)
        return {**result, "version": version}
    except Exception as exc:
        atomic_json(
            workspace / "version-failure.json",
            {
                "schema_version": SCHEMA_VERSION,
                "state": "failed",
                "created_at": timestamp(),
                "reason": str(exc),
                "parent_version_id": parent["version_id"],
            },
        )
        raise
    finally:
        if service is not None:
            service.close()
