"""Durable one-worker queue; explicit submissions are the only source of new compute."""

from __future__ import annotations

import json
import secrets
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

from twinforge.application.job_config import config_digest, freeze_config
from twinforge.application.library import atomic_json
from twinforge.application.output_validation import validate_output
from twinforge.application.processes import (
    group_alive,
    process_info,
    terminate_group,
    verified_owner,
)
from twinforge.application.readiness import profile_settings
from twinforge.application.types import SCHEMA_VERSION, new_id, timestamp, validate_id
from twinforge.application.worker import verify_input
from twinforge.scene.reader import sha256_file

TERMINAL = {"ready", "failed", "cancelled", "interrupted"}
FAILURES = {
    "worker_failed": "Processing failed. Check Details, setup and storage, then Retry as a new run.",
    "insufficient_storage": "Free library storage before retrying. Partial output is incomplete.",
    "invalid_output": "Output integrity validation failed. Partial output is incomplete; Retry creates a new run.",
    "interrupted": "The application stopped before completion. Retry creates a new run; inference cannot resume.",
    "interrupted_before_start": "This job did not start before the application stopped. Retry to queue a new run.",
    "ownership_unresolved": "A previous worker may still own resources. Resolve its ownership before starting work.",
    "input_changed": "The original video or frozen settings changed. Add the original video again.",
}


class JobManager:
    def __init__(self, library, readiness):
        self.library, self.readiness = library, readiness
        self.slot = readiness.slot
        self._lock = self.slot.lock
        self._stop = threading.Event()
        self._thread = None
        self._process = None
        self._active = None
        self._paths = {}
        self.instance_nonce = secrets.token_hex(16)
        for path in sorted((library.root / "scenes").glob("*/runs/*/job.json")):
            try:
                record = json.loads(path.read_text())
                validate_id(record["job_id"], "job")
                if path != self._expected_path(record):
                    raise ValueError("Job path identity mismatch")
                self._paths[record["job_id"]] = path
                if (
                    record["state"] not in TERMINAL
                    or record.get("failure", {}).get("code") == "ownership_unresolved"
                ):
                    self._reconcile(record)
            except (OSError, ValueError, KeyError, TypeError):
                self._blocked = True
        readiness.jobs_available = not self._blocked

    @property
    def _blocked(self):
        return self.slot.ownership_unresolved

    @_blocked.setter
    def _blocked(self, value):
        self.slot.ownership_unresolved = value

    def _expected_path(self, record):
        return (
            self.library.root
            / "scenes"
            / validate_id(record["scene_id"], "scene")
            / "runs"
            / validate_id(record["run_id"], "run")
            / "job.json"
        )

    def _read(self, job_id):
        validate_id(job_id, "job")
        if job_id not in self._paths:
            raise ValueError("Unknown job")
        return json.loads(self._paths[job_id].read_text())

    def _write(self, record):
        record["updated_at"] = timestamp()
        atomic_json(self._paths[record["job_id"]], record)

    def _event(self, record, stage, code=None, details=None, completed=None, total=None):
        record["sequence"] += 1
        record["stage"] = stage
        event = {
            "sequence": record["sequence"],
            "timestamp": timestamp(),
            "stage": stage,
            "message_code": code or stage,
            "details": details or {},
            "completed": completed,
            "total": total,
        }
        record["events"] = (record["events"] + [event])[-128:]
        # Bounded durable history; job.json remains authoritative if this derivative is lost.
        self._write(record)
        path = self._paths[record["job_id"]].with_name("events.jsonl")
        with path.open("w") as stream:
            for item in record["events"]:
                stream.write(json.dumps(item, allow_nan=False) + "\n")

    def _transition(self, record, state, failure=None):
        record["state"] = state
        if failure:
            record["failure"] = {"code": failure, "message": FAILURES[failure]}
        if state in TERMINAL:
            record["finished_at"] = timestamp()
        self._event(record, state)

    def _reconcile(self, record):
        self.library.rollback_job_publication(record)
        if record["state"] == "queued":
            self._transition(record, "interrupted", "interrupted_before_start")
            return
        owner = record.get("owner", {})
        live = process_info(owner.get("pid"))
        if live:
            arguments = owner.get("arguments", [])
            path = str(self._paths[record["job_id"]])
            if (
                owner.get("nonce") == record["nonce"]
                and path in arguments
                and record["nonce"] in arguments
                and verified_owner(owner, arguments)
            ):
                terminate_group(owner["pid"])
            else:
                self._blocked = True
                self._transition(record, "interrupted", "ownership_unresolved")
                return
        elif owner.get("pid") and group_alive(owner["pid"]):
            # Leader gone, descendants cannot be authenticated from just a stale PID.
            self._blocked = True
            self._transition(record, "interrupted", "ownership_unresolved")
            return
        self._transition(record, "interrupted", "interrupted")
        record["worker_alive"] = False
        self._write(record)

    def _public(self, record):
        fields = (
            "schema_version",
            "job_id",
            "scene_id",
            "run_id",
            "state",
            "stage",
            "sequence",
            "created_at",
            "updated_at",
            "started_at",
            "finished_at",
            "elapsed_seconds",
            "settings",
            "failure",
            "events",
            "selected_images",
            "actual_device",
            "resource_adjustment",
            "open_url",
            "worker_alive",
        )
        result = {key: record[key] for key in fields if key in record}
        try:
            result["scene_name"] = self.library.get(record["scene_id"])["name"]
        except (OSError, ValueError, TypeError, KeyError):
            result["scene_name"] = "Scene unavailable"
        queued = [item for item in self._records() if item["state"] == "queued"]
        result["queue_position"] = next(
            (i + 1 for i, item in enumerate(queued) if item["job_id"] == record["job_id"]), None
        )
        return result

    def _records(self):
        return sorted((self._read(key) for key in self._paths), key=lambda item: item["created_at"])

    def get(self, job_id):
        with self._lock:
            return self._public(self._read(job_id))

    def list(self):
        with self._lock:
            return {
                "jobs": [self._public(item) for item in self._records()],
                "ownership_unresolved": self._blocked,
                "heavy_operation_busy": self.slot.busy(),
            }

    def scene_summaries(self):
        """Latest durable state per scene; cards never load worker inputs or event history."""
        with self._lock:
            result = {}
            for record in self._records():
                result[record["scene_id"]] = {
                    key: record[key] for key in ("job_id", "run_id", "state", "stage")
                }
            return result

    def create(self, scene_id, idempotency_key):
        if (
            not isinstance(idempotency_key, str)
            or not 1 <= len(idempotency_key) <= 128
            or not idempotency_key.isascii()
        ):
            raise ValueError("A bounded idempotency key is required")
        with self._lock:
            for record in self._records():
                if record["idempotency_key"] == idempotency_key:
                    if record["scene_id"] != scene_id:
                        raise ValueError("Idempotency key is already bound to another scene")
                    return self._public(record)
            if self._stop.is_set() or self._blocked or self.readiness.is_preparing():
                raise ValueError("Processing ownership is unavailable")
            if not self.readiness.status()["processing_ready"]:
                raise ValueError("Prepare model and check processing setup first")
            scene = self.library.get(scene_id)
            media = self.library.media(scene_id, scene["media_id"])
            if media["review_settings"]["device"] == "cuda" and not self.readiness.devices["cuda"]:
                raise ValueError("CUDA is unavailable in the worker environment")
            run_id, job_id = new_id("run"), new_id("job")
            base = self.library.root / "scenes" / scene_id / "runs" / run_id
            settings = profile_settings(
                media["review_settings"]["profile"], media["review_settings"]["device"]
            )
            config = freeze_config(self.library.config, settings, base / "engine-output")
            record = {
                "schema_version": SCHEMA_VERSION,
                "job_id": job_id,
                "scene_id": scene_id,
                "run_id": run_id,
                "media_id": media["media_id"],
                "idempotency_key": idempotency_key,
                "nonce": secrets.token_hex(24),
                "library": str(self.library.root),
                "config": config,
                "config_sha256": config_digest(config),
                "settings": settings,
                "input": {
                    "path": str(
                        self.library.media_path(scene_id, media["media_id"])
                        / media["original_name"]
                    ),
                    "sha256": media["sha256"],
                    "bytes": media["expected_bytes"],
                },
                "cache": {
                    "torch_home": str(self.library.config.torch_home),
                    "repository": "facebookresearch/dinov2:main",
                    "hubconf_sha256": sha256_file(
                        self.library.config.torch_home
                        / "hub/facebookresearch_dinov2_main/hubconf.py"
                    ),
                },
                "created_at": timestamp(),
                "updated_at": timestamp(),
                "state": "queued",
                "stage": "queued",
                "sequence": 0,
                "events": [],
                "elapsed_seconds": 0,
                "worker_alive": False,
            }
            self._paths[job_id] = base / "job.json"
            self._event(record, "queued")
            if self._thread is None or not self._thread.is_alive():
                self._thread = threading.Thread(target=self._drain, daemon=True)
                self._thread.start()
            return self._public(record)

    def cancel(self, job_id):
        with self._lock:
            record = self._read(job_id)
            if record["state"] not in TERMINAL and record["state"] != "cancelling":
                self._transition(
                    record, "cancelled" if record["state"] == "queued" else "cancelling"
                )
            return self._public(record)

    def retry(self, job_id, idempotency_key):
        with self._lock:
            record = self._read(job_id)
            if record["state"] not in {"failed", "cancelled", "interrupted"}:
                raise ValueError("Only an incomplete run can be retried")
            return self.create(record["scene_id"], idempotency_key)

    def _arguments(self, path, nonce, descriptor):
        return [
            sys.executable,
            "-m",
            "twinforge.application.worker",
            "--job",
            str(path),
            "--nonce",
            nonce,
            "--slot-fd",
            str(descriptor),
        ]

    def _storage(self):
        if shutil.disk_usage(self.library.root).free < self.library.config.disk_reserve_bytes:
            raise OSError("Insufficient free storage reserve")

    def _drain(self):
        while not self._stop.is_set():
            with self._lock:
                queued = [record for record in self._records() if record["state"] == "queued"]
                if not queued:
                    # Transfer supervisor ownership before a submitter can observe this exit.
                    self._thread = None
                    return
                if self.readiness.is_preparing() or self.slot.busy():
                    # Queued only by an explicit request in this app instance.
                    blocked = True
                else:
                    blocked = False
                    self._active = queued[0]["job_id"]
                    self.slot.acquire()
            if blocked:
                self._stop.wait(0.1)
                continue
            try:
                self._execute(self._active)
            except Exception:  # noqa: BLE001 - supervisor boundary must reap on all failures
                # Metadata/storage failures still stop and reap every owned child.
                if self._process is not None:
                    try:
                        terminate_group(self._process.pid, self._process)
                    except (OSError, RuntimeError, subprocess.SubprocessError):
                        self._blocked = True
                with self._lock:
                    try:
                        record = self._read(self._active)
                        if record["state"] not in TERMINAL:
                            self.library.rollback_job_publication(record)
                            self._transition(record, "failed", "worker_failed")
                    except OSError:
                        self._blocked = True
            finally:
                with self._lock:
                    self._process = None
                    self._active = None
                    if not self._blocked:
                        self.slot.release()
            if self._blocked:
                return

    def _execute(self, job_id):
        started = time.monotonic()
        path = self._paths[job_id]
        with self._lock:
            record = self._read(job_id)
            if record["state"] != "queued":
                return
            record["started_at"] = timestamp()
            self._transition(record, "running")
        try:
            self._storage()
        except OSError:
            with self._lock:
                self._transition(self._read(job_id), "failed", "insufficient_storage")
            return
        try:
            # Hashing large original bytes runs in this supervisor, outside the request loop.
            verify_input(record)
        except (OSError, ValueError):
            with self._lock:
                self._transition(self._read(job_id), "failed", "input_changed")
            return
        with self._lock:
            record = self._read(job_id)
            if record["state"] == "cancelling" or self._stop.is_set():
                self._transition(record, "interrupted" if self._stop.is_set() else "cancelled")
                return
            arguments = self._arguments(path, record["nonce"], self.slot._file.fileno())
            process = subprocess.Popen(
                arguments,
                env=self.library.config.worker_environment(),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
                pass_fds=(self.slot._file.fileno(),),
            )
            self._process = process
            record["owner"] = {
                "pid": process.pid,
                "process": process_info(process.pid),
                "nonce": record["nonce"],
                "instance_nonce": self.instance_nonce,
                "arguments": arguments,
            }
            record["worker_alive"] = True
            self._write(record)
        failure = None
        while process.poll() is None:
            with self._lock:
                record = self._read(job_id)
                record["elapsed_seconds"] = round(time.monotonic() - started, 2)
                cancel = record["state"] == "cancelling" or self._stop.is_set()
                try:
                    self._storage()
                except OSError:
                    failure, cancel = "insufficient_storage", True
                if not cancel:
                    self._collect_progress(record)
                self._write(record)
            if cancel:
                terminate_group(process.pid, process)
                break
            self._stop.wait(0.15)
        process.wait()
        # Reap/stop inherited FFmpeg or other children even after an abnormal leader exit.
        terminate_group(process.pid, process)
        with self._lock:
            record = self._read(job_id)
            self._collect_progress(record)
            record["worker_alive"] = False
            record["elapsed_seconds"] = round(time.monotonic() - started, 2)
            if record["state"] == "cancelling" or self._stop.is_set() or failure:
                self._transition(
                    record,
                    "interrupted" if self._stop.is_set() else "failed" if failure else "cancelled",
                    "interrupted" if self._stop.is_set() else failure,
                )
                return
            self._transition(record, "validating_output")
        try:
            receipt = json.loads(path.with_name("receipt.json").read_text())
            if any(
                receipt.get(key) != record[key]
                for key in ("job_id", "run_id", "nonce", "config_sha256")
            ):
                raise ValueError("Unbound worker completion receipt")
            if process.returncode != 0 or receipt.get("state") != "complete":
                failure = "worker_failed"
                raise ValueError("Worker failed")
            self._storage()
            result = validate_output(Path(receipt["output_path"]), record)
            self._storage()
        except Exception:  # noqa: BLE001 - malformed artifacts are failed, never published
            with self._lock:
                record = self._read(job_id)
                self._transition(
                    record,
                    "cancelled"
                    if record["state"] == "cancelling"
                    else "interrupted"
                    if self._stop.is_set()
                    else "failed",
                    None if record["state"] == "cancelling" else failure or "invalid_output",
                )
            return
        with self._lock:
            record = self._read(job_id)
            if record["state"] == "cancelling" or self._stop.is_set():
                self._transition(record, "interrupted" if self._stop.is_set() else "cancelled")
                return
            scene = self.library.get(record["scene_id"])
            record["publication_previous"] = {
                key: scene.get(key)
                for key in ("default_run_id", "default_session_id", "default_version_id", "status")
            }
            # Journal before cross-record publication; startup can roll back an interrupted commit.
            self._write(record)
            self.library.publish_job(record, result)
            record.update(
                {
                    key: result[key]
                    for key in ("selected_images", "actual_device", "resource_adjustment")
                }
            )
            scene = self.library.get(record["scene_id"])
            record["output_path"] = result["source_root"]
            record["open_url"] = (
                f"/scenes/{record['scene_id']}/runs/{record['run_id']}"
                f"/sessions/{scene['default_session_id']}/"
            )
            record["elapsed_seconds"] = round(time.monotonic() - started, 2)
            self._transition(record, "ready")

    def _collect_progress(self, record):
        path = self._paths[record["job_id"]].with_name("progress.json")
        if not path.exists() or path.stat().st_size > 262144:
            return
        for progress in json.loads(path.read_text())["events"]:
            if progress["sequence"] <= record.get("engine_sequence", 0):
                continue
            record["engine_sequence"] = progress["sequence"]
            details = progress.get("details", {})
            for key in ("selected_images", "actual_device", "resource_adjustment"):
                if key in details:
                    record[key] = details[key]
            self._event(
                record,
                progress["stage"],
                progress["message_code"],
                details,
                progress.get("completed"),
                progress.get("total"),
            )

    def close(self):
        self._stop.set()
        with self._lock:
            thread = self._thread
        if thread is not None:
            thread.join()
        with self._lock:
            for record in self._records():
                if record["state"] == "queued":
                    self._transition(record, "interrupted", "interrupted_before_start")
