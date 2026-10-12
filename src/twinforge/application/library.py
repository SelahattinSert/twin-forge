"""Owned, atomic local records and explicitly selected read-only linked imports."""

from __future__ import annotations

import fcntl
import json
import os
import re
import threading
from collections import OrderedDict
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any

type Record = dict[str, Any]

from twinforge.application.config import ApplicationConfig
from twinforge.application.types import (
    SCHEMA_VERSION,
    ManagedMediaRecord,
    ProcessingSettings,
    UploadReceipt,
    display_name,
    new_id,
    timestamp,
    validate_id,
)
from twinforge.scene.provenance import attach_verified_provenance
from twinforge.scene.reader import SceneReader, sha256_file


def _required_text(value: Record, field: str) -> str:
    result = value.get(field)
    if not isinstance(result, str) or not result.strip():
        raise ValueError(f"Invalid application record field: {field}")
    return result


def _validate_scene(value: Record, scene_id: str) -> None:
    """Validate fields consumed by cards and routing; preserve unknown future fields."""
    if value.get("scene_id") != scene_id:
        raise ValueError("Scene record identity does not match its location")
    display_name(value.get("name"))
    for field in ("created_at", "updated_at"):
        text = _required_text(value, field)
        if not re.fullmatch(
            r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}"
            r"(?:\.[0-9]{1,6})?(?:Z|[+-](?:[01][0-9]|2[0-3]):[0-5][0-9])",
            text,
        ):
            raise ValueError("Scene timestamps must use calendar dates with an explicit timezone")
        datetime.fromisoformat(text)  # Reject impossible calendar dates and clock values.
    _required_text(value, "source_kind")
    if type(value.get("archived")) is not bool:
        raise ValueError("Archive state must be boolean")
    if value["source_kind"] == "managed_video":
        validate_id(value.get("media_id"), "media")
        if value.get("default_run_id") is None and (
            any(
                value.get(key) is not None
                for key in ("default_run_id", "default_session_id", "default_version_id")
            )
            or value.get("versions") != []
            or value.get("status") != "ready_to_start"
        ):
            raise ValueError("Managed input has no validated output version")
        if value.get("default_run_id") is None:
            return
    for field, kind in (
        ("default_run_id", "run"),
        ("default_session_id", "session"),
        ("default_version_id", "version"),
    ):
        validate_id(value.get(field), kind)
    versions = value.get("versions")
    if not isinstance(versions, list) or not versions:
        raise ValueError("Scene versions must be a nonempty list")
    seen = set()
    for version in versions:
        if not isinstance(version, dict):
            raise TypeError("Scene versions must contain records")
        for field, kind in (
            ("version_id", "version"),
            ("run_id", "run"),
            ("session_id", "session"),
        ):
            validate_id(version.get(field), kind)
        _required_text(version, "label")
        if version["version_id"] in seen:
            raise ValueError("Scene version identities must be distinct")
        seen.add(version["version_id"])
    selected = next(
        (item for item in versions if item["version_id"] == value["default_version_id"]), None
    )
    if selected is None or (selected["run_id"], selected["session_id"]) != (
        value["default_run_id"],
        value["default_session_id"],
    ):
        raise ValueError("Default version does not match its scene context")


def _validate_run(value: Record, scene_id: str, run_id: str) -> None:
    """Validate the linked-source fields used by current viewer requests."""
    if (value.get("scene_id"), value.get("run_id")) != (scene_id, run_id):
        raise ValueError("Run record identity does not match its location")
    sessions = value.get("session_ids")
    if not isinstance(sessions, list) or not sessions:
        raise ValueError("Run sessions must be a nonempty list")
    for session in sessions:
        validate_id(session, "session")
    if len(set(sessions)) != len(sessions):
        raise ValueError("Run session identities must be distinct")
    paths = {}
    for field in ("source_root", "source_manifest"):
        text = _required_text(value, field)
        if "\0" in text or not Path(text).is_absolute() or ".." in Path(text).parts:
            raise ValueError("Invalid registered source path")
        paths[field] = Path(text)
    root = paths["source_root"]
    hashes = value.get("hashes")
    if not isinstance(hashes, dict) or not hashes:
        raise ValueError("Source hashes must be a nonempty record")
    for name, digest in hashes.items():
        if (
            not isinstance(name, str)
            or not name
            or "\0" in name
            or Path(name).is_absolute()
            or ".." in Path(name).parts
            or not isinstance(digest, str)
            or not re.fullmatch(r"[0-9a-f]{64}", digest)
        ):
            raise ValueError("Invalid source file hash binding")
    if (
        not paths["source_manifest"].is_relative_to(root)
        or str(paths["source_manifest"].relative_to(root)) not in hashes
    ):
        raise ValueError("Source manifest is not bound to its registered hashes")
    for field in ("source_label", "scale_label"):
        _required_text(value, field)
    if "thumbnail" not in value:
        raise ValueError("Missing source thumbnail field")
    thumbnail = value["thumbnail"]
    if thumbnail is not None and (
        not isinstance(thumbnail, str)
        or "\0" in thumbnail
        or not Path(thumbnail).is_absolute()
        or ".." in Path(thumbnail).parts
        or not Path(thumbnail).is_relative_to(root)
        or str(Path(thumbnail).relative_to(root)) not in hashes
    ):
        raise ValueError("Thumbnail is not bound to its registered source hashes")
    if "mapping_sha256" in value and (
        not isinstance(value["mapping_sha256"], str)
        or not re.fullmatch(r"[0-9a-f]{64}", value["mapping_sha256"])
    ):
        raise ValueError("Invalid session mapping digest")


def atomic_json(path: Path, value: Record, *, backup: bool = True) -> None:
    """Publish after fsync; an interrupted candidate cannot become an authoritative record."""
    path.parent.mkdir(parents=True, exist_ok=True)
    candidate = path.with_name(path.name + ".pending")
    data = json.dumps(value, allow_nan=False, indent=2).encode()
    if backup and path.exists():
        atomic_json(path.with_suffix(".previous"), json.loads(path.read_text()), backup=False)
    with candidate.open("wb") as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(candidate, path)
    descriptor = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


class LibraryStore:
    def __init__(self, config: ApplicationConfig):
        self.config = config
        self.root = config.library.resolve()
        self.roots = tuple(path.resolve(strict=True) for path in config.import_roots)
        self.root.mkdir(parents=True, exist_ok=True)
        (self.root / "runtime").mkdir(exist_ok=True)
        self._owner = (self.root / "runtime/owner.lock").open("a+b")
        try:
            fcntl.flock(self._owner, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            self._owner.close()
            raise ValueError("This library already has an application owner") from None
        self._lock = threading.RLock()
        self._choices: dict[str, Path] = {}
        self._validated = OrderedDict()
        self.recovery: list[str] = []
        try:
            path = self.root / "library.json"
            if path.exists():
                self._read(path)
            else:
                atomic_json(path, {"schema_version": SCHEMA_VERSION, "created_at": timestamp()})
            (self.root / "scenes").mkdir(exist_ok=True)
        except Exception:
            self.close()
            raise

    def close(self) -> None:
        if not self._owner.closed:
            fcntl.flock(self._owner, fcntl.LOCK_UN)
            self._owner.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    def _read(self, path: Path, validator: Callable[[Record], None] | None = None) -> Record:
        def read_valid(candidate: Path) -> Record:
            value = json.loads(candidate.read_text())
            if not isinstance(value, dict) or value.get("schema_version") != SCHEMA_VERSION:
                raise ValueError("Unsupported application record schema")
            if validator is not None:
                validator(value)
            return value

        with self._lock:
            try:
                return read_valid(path)
            except (OSError, ValueError, TypeError):
                try:
                    value = read_valid(path.with_suffix(".previous"))
                except (OSError, ValueError, TypeError) as exc:
                    raise ValueError(
                        "Application record and recovery copy are unavailable"
                    ) from exc
                atomic_json(path, value, backup=False)
                self.recovery.append(path.parent.name)
                return value

    def _scene_path(self, scene_id: str) -> Path:
        return self.root / "scenes" / validate_id(scene_id, "scene") / "scene-record.json"

    def get(self, scene_id: str) -> Record:
        return self._read(
            self._scene_path(scene_id), lambda value: _validate_scene(value, scene_id)
        )

    def run(self, scene_id: str, run_id: str) -> Record:
        self.get(scene_id)
        base = self._scene_path(scene_id).parent / "runs" / validate_id(run_id, "run")
        run = self._read(
            base / "run.json",
            lambda value: _validate_run(value, scene_id, run_id),
        )
        if run.get("managed_output"):
            job = json.loads((base / "job.json").read_text())
            if (
                job.get("state") != "ready"
                or job.get("run_id") != run_id
                or job.get("scene_id") != scene_id
            ):
                raise ValueError("Managed output is not a ready application run")
        return run

    def workspace(self, scene_id: str, run_id: str, session_id: str) -> Path:
        run = self.run(scene_id, run_id)
        validate_id(session_id, "session")
        if session_id not in run["session_ids"]:
            raise ValueError("Session does not belong to this run")
        return self._scene_path(scene_id).parent / "runs" / run_id / "workspaces" / session_id

    def summary(self, record: Record) -> Record:
        if record["source_kind"] == "managed_video" and record["default_run_id"] is None:
            media = self.media(record["scene_id"], record["media_id"])
            path = self.media_path(record["scene_id"], record["media_id"]) / media["original_name"]
            available = path.is_file() and path.stat().st_size == media["expected_bytes"]
            return {
                key: record[key]
                for key in (
                    "scene_id",
                    "name",
                    "created_at",
                    "updated_at",
                    "archived",
                    "default_run_id",
                    "default_session_id",
                    "default_version_id",
                    "versions",
                    "source_kind",
                )
            } | {
                "status": "ready_to_start" if available else "source_unavailable",
                "scale_label": "No reconstruction yet",
                "source_label": "Managed local video",
                "media": media,
                "thumbnail_url": f"/api/library/scenes/{record['scene_id']}/thumbnail",
            }
        run = self.run(record["scene_id"], record["default_run_id"])
        if record["default_session_id"] not in run["session_ids"]:
            raise ValueError("Default session does not belong to its run")
        availability_code, availability_message = self.source_availability(run)
        available = availability_code == "available"
        result = {
            key: record[key]
            for key in (
                "scene_id",
                "name",
                "created_at",
                "updated_at",
                "archived",
                "default_run_id",
                "default_session_id",
                "default_version_id",
                "versions",
                "source_kind",
            )
        } | {
            "status": "ready" if available else "source_unavailable",
            "scale_label": run["scale_label"],
            "source_label": run["source_label"],
            "availability_code": availability_code,
            "availability_message": availability_message,
            "thumbnail_url": f"/api/library/scenes/{record['scene_id']}/thumbnail",
        }
        if record["source_kind"] == "managed_video":
            result["media"] = self.media(record["scene_id"], record["media_id"])
        return result

    def list(self, job_summaries: dict | None = None) -> Record:
        records, issues = [], []
        for path in sorted((self.root / "scenes").glob("*/scene-record.json")):
            try:
                summary = self.summary(self.get(path.parent.name))
                summary["ready_available"] = summary["status"] == "ready"
                latest = (job_summaries or {}).get(summary["scene_id"])
                if latest:
                    summary["latest_job"] = latest
                    if latest["state"] != "ready":
                        summary["status"] = latest["state"]
                records.append(summary)
            except (OSError, ValueError, TypeError, KeyError):
                issues.append({"scene_id": path.parent.name, "status": "record_unavailable"})
        return {"scenes": records, "issues": issues, "recovered_records": list(self.recovery)}

    def storage(self) -> Record:
        """Account only for configured linked artifacts and this owned library."""
        sizes = {
            "linked_original_bytes": 0,
            "managed_video_bytes": 0,
            "retained_export_bytes": 0,
            "disposable_cache_bytes": 0,
            "retained_scene_workspace_bytes": 0,
            "incomplete_upload_bytes": 0,
            "archive_frees_bytes": 0,
        }
        linked = set()
        for record in self.list()["scenes"]:
            if record["source_kind"] == "linked":
                for version in record["versions"]:
                    run = self.run(record["scene_id"], version["run_id"])
                    linked.update(Path(run["source_root"]) / name for name in run["hashes"])
        sizes["linked_original_bytes"] = sum(p.stat().st_size for p in linked if p.is_file())
        for directory, directories, files in os.walk(self.root, followlinks=False):
            directories[:] = [d for d in directories if not (Path(directory) / d).is_symlink()]
            for filename in files:
                path = Path(directory) / filename
                if path.is_symlink():
                    continue
                relative = path.relative_to(self.root).parts
                if relative[0] == "exports":
                    category = "retained_export_bytes"
                elif relative[0] == "uploads":
                    category = "incomplete_upload_bytes"
                elif "media" in relative and filename.startswith("original."):
                    category = "managed_video_bytes"
                elif filename in ("preview.tfp", "candidate_000001.jpg"):
                    category = "disposable_cache_bytes"
                else:
                    category = "retained_scene_workspace_bytes"
                sizes[category] += path.stat().st_size
        return sizes

    def media_path(self, scene_id: str, media_id: str) -> Path:
        path = self._scene_path(scene_id).parent / "media" / validate_id(media_id, "media")
        if not path.resolve().is_relative_to(self.root):
            raise ValueError("Managed media escaped the library")
        return path

    def media(self, scene_id: str, media_id: str) -> ManagedMediaRecord:
        record = self.get(scene_id)
        if record.get("media_id") != media_id or record["source_kind"] != "managed_video":
            raise ValueError("Media does not belong to this scene")

        def validate(value):
            if (
                (value.get("scene_id"), value.get("media_id")) != (scene_id, media_id)
                or value.get("state") != "ready_to_start"
                or value.get("original_name")
                not in {"original.mp4", "original.mov", "original.mkv"}
                or value.get("preview_name") != "candidate_000001.jpg"
                or type(value.get("expected_bytes")) is not int
                or value["expected_bytes"] < 1
                or not isinstance(value.get("sha256"), str)
                or not re.fullmatch(r"[0-9a-f]{64}", value["sha256"])
                or not isinstance(value.get("inspection"), dict)
                or value["inspection"].get("decode_ready") is not True
            ):
                raise ValueError("Invalid managed media record")

        return self._read(self.media_path(scene_id, media_id) / "inspection.json", validate)

    def register_media(
        self,
        receipt: UploadReceipt,
        original: Path,
        inspection: Record,
        name: str,
        settings: ProcessingSettings,
    ) -> Record:
        """Publish ready input only after managed original, preview, and inspection are durable."""
        with self._lock:
            scene_id, media_id = receipt["scene_id"], receipt["media_id"]
            destination = self.media_path(scene_id, media_id)
            destination.mkdir(parents=True, exist_ok=True)
            original_name = "original" + receipt["extension"]
            preview_name = "candidate_000001.jpg"
            if inspection["preview"] != preview_name or not original.resolve().is_relative_to(
                self.root / "uploads"
            ):
                raise ValueError("Invalid managed inspection path")
            os.replace(original, destination / original_name)
            os.replace(original.parent / preview_name, destination / preview_name)
            media = {
                "schema_version": SCHEMA_VERSION,
                "scene_id": scene_id,
                "media_id": media_id,
                "state": "ready_to_start",
                "client_name": receipt["client_name"],
                "expected_bytes": receipt["expected_bytes"],
                "sha256": receipt["sha256"],
                "original_name": original_name,
                "preview_name": preview_name,
                "inspection": inspection,
                "review_settings": settings,
                "created_at": timestamp(),
            }
            atomic_json(destination / "inspection.json", media)
            record = {
                "schema_version": SCHEMA_VERSION,
                "scene_id": scene_id,
                "name": display_name(name),
                "archived": False,
                "created_at": timestamp(),
                "updated_at": timestamp(),
                "source_kind": "managed_video",
                "status": "ready_to_start",
                "media_id": media_id,
                "default_run_id": None,
                "default_session_id": None,
                "default_version_id": None,
                "versions": [],
            }
            atomic_json(self._scene_path(scene_id), record)
            return self.summary(record)

    def thumbnail(self, scene_id: str) -> Path:
        record = self.get(scene_id)
        if record["source_kind"] == "managed_video":
            media = self.media(scene_id, record["media_id"])
            image = self.media_path(scene_id, media["media_id"]) / media["preview_name"]
            if not image.resolve(strict=True).is_relative_to(self.root):
                raise ValueError("Managed thumbnail escaped the library")
            return image
        run = self.run(scene_id, record["default_run_id"])
        self.validate_source(run)
        image = Path(run["thumbnail"]).resolve(strict=True)
        if sha256_file(image) != run["hashes"][str(image.relative_to(Path(run["source_root"])))]:
            raise ValueError("Source image changed")
        return image

    def review_media(self, scene_id: str, name: str, profile: str, device: str | None) -> Record:
        from twinforge.application.readiness import profile_settings

        with self._lock:
            settings = profile_settings(profile, device)
            name = display_name(name)
            record = self.get(scene_id)
            media = self.media(scene_id, record["media_id"])
            media["review_settings"] = settings
            atomic_json(self.media_path(scene_id, media["media_id"]) / "inspection.json", media)
            return self.patch(scene_id, {"name": name})

    def patch(self, scene_id: str, value: Record) -> Record:
        if not isinstance(value, dict) or set(value) - {"name", "archived", "default_version_id"}:
            raise ValueError("Unsupported scene metadata change")
        with self._lock:
            record = self.get(scene_id)
            if "name" in value:
                record["name"] = display_name(value["name"])
            if "archived" in value:
                if type(value["archived"]) is not bool:
                    raise ValueError("Archive state must be boolean")
                record["archived"] = value["archived"]
            if "default_version_id" in value:
                version = next(
                    (
                        v
                        for v in record["versions"]
                        if v["version_id"] == value["default_version_id"]
                    ),
                    None,
                )
                if version is None:
                    raise ValueError("Unknown scene version")
                record.update(
                    default_version_id=version["version_id"],
                    default_run_id=version["run_id"],
                    default_session_id=version["session_id"],
                )
            record["updated_at"] = timestamp()
            atomic_json(self._scene_path(scene_id), record)
            return self.summary(record)

    def _confined(self, path: Path) -> Path:
        path = path.resolve(strict=True)
        if not any(path.is_relative_to(root) for root in self.roots):
            raise ValueError("Import is outside configured roots")
        if path.is_relative_to(self.root):
            raise ValueError("The library cannot import its own managed workspaces")
        return path

    def discover(self) -> Record:
        choices = {}
        result = {"scenes": [], "workspaces": [], "truncated": False}
        visited = 0
        for root in self.roots:
            for directory, directories, files in os.walk(root, followlinks=False):
                directories[:] = sorted(
                    d
                    for d in directories
                    if not (Path(directory) / d).is_symlink()
                    and not (Path(directory) / d).resolve().is_relative_to(self.root)
                )
                visited += 1
                if visited > self.config.discovery_limit:
                    result["truncated"] = True
                    break
                for filename, kind in (
                    ("scene.json", "scenes"),
                    ("pixel-provenance.json", "workspaces"),
                ):
                    if filename not in files:
                        continue
                    try:
                        path = self._confined(Path(directory) / filename)
                    except (OSError, ValueError):
                        continue
                    # IDs are opaque and retained for the process, never arbitrary posted paths.
                    key = next((k for k, p in self._choices.items() if p == path), new_id("choice"))
                    choices[key] = path
                    result[kind].append({"choice_id": key, "label": path.parent.name})
        with self._lock:
            self._choices = choices
        return result

    def _choice(self, choice_id: str, filename: str) -> Path:
        path = self._choices.get(choice_id)
        if path is None or path.name != filename:
            raise ValueError("Select a discovered import choice")
        return self._confined(path)

    def _source(self, path: Path):
        scene = SceneReader(self._confined(path)).read()
        if self.root.is_relative_to(scene.source_root) or scene.source_root.is_relative_to(
            self.root
        ):
            raise ValueError("The library and linked source must be separate directories")
        paths = set(scene.referenced_paths) | {f.image_path for f in scene.frames}
        for source in paths:
            self._confined(source)
        hashes = {
            str(source.relative_to(scene.source_root)): sha256_file(source) for source in paths
        }
        return scene, hashes

    def import_scene(
        self, choice_id: str, name: str, workspace_choice_id: str | None = None
    ) -> Record:
        scene, hashes = self._source(self._choice(choice_id, "scene.json"))
        mapping = None
        if workspace_choice_id is not None:
            mapping = json.loads(
                self._choice(workspace_choice_id, "pixel-provenance.json").read_text()
            )
            for proof in mapping.get("evidence_files", []):
                self._confined(Path(proof["source_path"]))
            attach_verified_provenance(scene, mapping)
        scene_id, run_id, session_id, version_id = (
            new_id(kind) for kind in ("scene", "run", "session", "version")
        )
        record = {
            "schema_version": SCHEMA_VERSION,
            "scene_id": scene_id,
            "name": display_name(name),
            "created_at": timestamp(),
            "updated_at": timestamp(),
            "archived": False,
            "source_kind": "linked",
            "default_run_id": run_id,
            "default_session_id": session_id,
            "default_version_id": version_id,
            "versions": [
                {
                    "version_id": version_id,
                    "run_id": run_id,
                    "session_id": session_id,
                    "label": "Source scene",
                }
            ],
        }
        run = {
            "schema_version": SCHEMA_VERSION,
            "scene_id": scene_id,
            "run_id": run_id,
            "session_ids": [session_id],
            "source_manifest": str(scene.manifest_path),
            "source_root": str(scene.source_root),
            "hashes": hashes,
            "source_label": scene.manifest_path.parent.name,
            "scale_label": "Estimated scale",
            "thumbnail": str(scene.frames[0].image_path) if scene.frames else None,
        }
        with self._lock:
            base = self._scene_path(scene_id).parent / "runs" / run_id
            workspace = base / "workspaces" / session_id
            workspace.mkdir(parents=True)
            if mapping is not None:
                atomic_json(workspace / "pixel-provenance.json", mapping)
                run["mapping_sha256"] = sha256_file(workspace / "pixel-provenance.json")
            atomic_json(base / "run.json", run)
            # Publish the scene last: incomplete preparation is never listed as a scene.
            atomic_json(self._scene_path(scene_id), record)
        return self.summary(record)

    def _confined_run_source(self, run: Record, path: Path) -> Path:
        if not run.get("managed_output") and not run.get("owned_package"):
            return self._confined(path)
        resolved = path.resolve(strict=True)
        owned = (
            self.root
            / "scenes"
            / run["scene_id"]
            / "runs"
            / run["run_id"]
            / ("package" if run.get("owned_package") else "engine-output")
        ).resolve()
        if not resolved.is_relative_to(owned):
            raise ValueError("Managed output escaped its run directory")
        return resolved

    def source_availability(self, run: Record) -> tuple[str, str]:
        """Cheap card preflight using the same confinement as opening a scene.

        Content hashes are still verified on access; listing never claims that
        existence or folder permission proves artifact integrity.
        """
        try:
            root = self._confined_run_source(run, Path(run["source_root"]))
            for name in run["hashes"]:
                path = self._confined_run_source(run, root / name)
                if not path.is_relative_to(root):
                    raise ValueError("Source escapes its registered root")
                if not path.is_file():
                    raise FileNotFoundError("Registered source file is missing")
        except FileNotFoundError:
            return (
                "source_missing",
                "Source files are missing. Reconnect the original folder or restore a complete saved package.",
            )
        except (OSError, ValueError):
            return (
                "source_not_enabled",
                "The source folder is not enabled or accessible. Restart with its --import-root, then reconnect the source; or restore a saved package.",
            )
        return (
            "available",
            "Source files are accessible. Their integrity is checked when the scene opens.",
        )

    def validate_source(self, run: Record, *, force: bool = False) -> None:
        def confine(path):
            return self._confined_run_source(run, path)

        root = confine(Path(run["source_root"]))
        signature = []
        for name, digest in run["hashes"].items():
            path = confine(root / name)
            if not path.is_relative_to(root):
                raise ValueError("Source escapes its registered root")
            stat = path.stat()
            signature.append(
                (
                    str(path),
                    stat.st_dev,
                    stat.st_ino,
                    stat.st_size,
                    stat.st_mtime_ns,
                    stat.st_ctime_ns,
                    digest,
                )
            )
        key = (run["scene_id"], run["run_id"])
        if not force and self._validated.get(key) == signature:
            self._validated.move_to_end(key)
            return
        for name, digest in run["hashes"].items():
            if sha256_file(root / name) != digest:
                raise ValueError("Source changed; locate a matching source before opening")
        self._validated[key] = signature
        self._validated.move_to_end(key)
        while len(self._validated) > self.config.service_cache_size:
            self._validated.popitem(last=False)

    def publish_job(self, job: Record, result: Record) -> None:
        """Register only a supervisor-validated output; preserve older successful versions."""
        with self._lock:
            record = self.get(job["scene_id"])
            session_id, version_id = new_id("session"), new_id("version")
            base = self.root / "scenes" / job["scene_id"] / "runs" / job["run_id"]
            (base / "workspaces" / session_id).mkdir(parents=True)
            run = {
                "schema_version": SCHEMA_VERSION,
                "scene_id": job["scene_id"],
                "run_id": job["run_id"],
                "session_ids": [session_id],
                "managed_output": True,
                **result,
            }
            atomic_json(base / "run.json", run)
            record["versions"].append(
                {
                    "version_id": version_id,
                    "run_id": job["run_id"],
                    "session_id": session_id,
                    "label": "Processed scene",
                }
            )
            record.update(
                default_run_id=job["run_id"],
                default_session_id=session_id,
                default_version_id=version_id,
                status="ready",
                updated_at=timestamp(),
            )
            atomic_json(self._scene_path(job["scene_id"]), record)

    def rollback_job_publication(self, job: Record) -> None:
        """Recover an uncommitted Ready transition without changing scene edits or older runs."""
        previous = job.get("publication_previous")
        if previous is None:
            return
        with self._lock:
            record = self.get(job["scene_id"])
            if record["default_run_id"] == job["run_id"]:
                record.update(previous)
            record["versions"] = [
                item for item in record["versions"] if item["run_id"] != job["run_id"]
            ]
            record["updated_at"] = timestamp()
            atomic_json(self._scene_path(job["scene_id"]), record)

    def prepared_preview(self, run: Record) -> bytes | None:
        if not run.get("managed_output"):
            return None
        expected = self.root / "scenes" / run["scene_id"] / "runs" / run["run_id"] / "preview.tfp"
        path = Path(run["preview_path"])
        if path.resolve(strict=True) != expected or sha256_file(path) != run["preview_sha256"]:
            raise ValueError("Managed preview integrity changed")
        return path.read_bytes()

    def locate(self, scene_id: str, choice_id: str) -> Record:
        scene, hashes = self._source(self._choice(choice_id, "scene.json"))
        with self._lock:
            record = self.get(scene_id)
            run = self.run(scene_id, record["default_run_id"])
            if hashes != run["hashes"]:
                raise ValueError("Located source does not match the registered source hashes")
            run.update(
                source_manifest=str(scene.manifest_path),
                source_root=str(scene.source_root),
                thumbnail=str(scene.frames[0].image_path) if scene.frames else None,
            )
            atomic_json(
                self._scene_path(scene_id).parent / "runs" / run["run_id"] / "run.json", run
            )
            return self.summary(record)

    @contextmanager
    def request_context(
        self, scene_id: str, run_id: str, session_id: str, *, mutation: bool = False
    ) -> Iterator[tuple[Record, Path]]:
        # The binding cannot move between source validation and the end of a request.
        with self._lock:
            run = self.run(scene_id, run_id)
            workspace = self.workspace(scene_id, run_id, session_id)
            self.validate_source(run, force=mutation)
            mapping = workspace / "pixel-provenance.json"
            digest = sha256_file(mapping) if mapping.exists() else None
            if digest != run.get("mapping_sha256"):
                raise ValueError("Session mapping differs from the verified import")
            yield run, workspace
