"""Lightweight cache checks and supervised setup; never load a model in the HTTP process."""

from __future__ import annotations

import fcntl
import importlib.util
import json
import os
import secrets
import shutil
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

from twinforge.application.config import ApplicationConfig
from twinforge.application.coordination import HeavySlot
from twinforge.application.inspection import bounded_command
from twinforge.application.library import atomic_json
from twinforge.application.types import ProcessingSettings
from twinforge.application.uploads import UploadError


def process_start_identity(pid: int) -> str | None:
    """Linux process birth tick, distinct from reusable PID; no signals to foreign workers."""
    if type(pid) is not int or pid < 1:
        return None
    try:
        fields = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()
        return None if fields[0] == "Z" else fields[19]
    except (OSError, IndexError):
        return None


def _worker_lock_busy(path: Path) -> bool:
    with path.open("a+b") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return True
        fcntl.flock(lock, fcntl.LOCK_UN)
        return False


def package_available(name: str) -> bool:
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ValueError):
        return False


def profile_settings(profile: str = "standard", device: str | None = None) -> ProcessingSettings:
    if profile not in {"standard", "quick_preview"} or device not in {None, "cpu", "cuda", "auto"}:
        raise ValueError("Unsupported processing profile/device")
    standard = profile == "standard"
    return {
        "profile": profile,
        "device": device or ("cpu" if standard else "auto"),
        "maximum_keyframes": 32 if standard else None,
        "auto_budget": not standard,
        "maximum_oom_retries": 0 if standard else 3,
        "color_policy": "auto",
        "candidate_interval_seconds": 0.5,
        "label": "Standard scene: up to 32 useful images" if standard else "Quick preview",
        "resource_note": "Quality selection may retain fewer images. Historical CPU runs on this machine took roughly 15–16 minutes; this is an example, not an ETA. A 4K video does not imply a 4K model grid."
        if standard
        else "Automatic GPU budgeting and bounded OOM reduction may retain fewer images and omit coverage.",
    }


def check_readiness(config: ApplicationConfig, devices: dict | None = None) -> dict:
    devices = devices or {"cpu": None, "cuda": None}
    backend = all(
        package_available(name)
        for name in ("torch", "mapanything", "uniception", "huggingface_hub")
    )
    snapshot = (
        config.hf_cache
        / ("models--" + config.checkpoint.replace("/", "--"))
        / "snapshots"
        / config.checkpoint_revision
    )
    cached = False
    sizes = {}
    try:
        if (snapshot / "config.json").stat().st_size > 1024**2:
            raise ValueError("Oversized model configuration")
        cached = isinstance(json.loads((snapshot / "config.json").read_text()), dict)
        for name in ("config.json", "model.safetensors"):
            sizes[name] = (snapshot / name).stat().st_size
            cached = cached and sizes[name] > 0
    except (OSError, ValueError):
        cached = False
    repo = config.torch_home / "hub/facebookresearch_dinov2_main"
    repository = (repo / "hubconf.py").is_file()
    decoders = {name: shutil.which(name) is not None for name in ("ffmpeg", "ffprobe")}
    try:
        writable = (
            os.access(config.library, os.W_OK)
            and shutil.disk_usage(config.library).free >= config.disk_reserve_bytes
        )
    except OSError:
        writable = False
    reasons = []
    if not all(decoders.values()):
        reasons.append(
            {
                "code": "missing_decoder",
                "message": "Install FFmpeg with ffprobe. Existing scenes remain viewable.",
            }
        )
    if not backend:
        reasons.append(
            {
                "code": "missing_backend",
                "message": "Install the documented MapAnything backend in the application environment, then restart the app. Preparation does not install packages.",
            }
        )
    if not cached or not repository:
        reasons.append(
            {
                "code": "model_not_prepared",
                "message": "Prepare the checkpoint and Torch Hub source repository explicitly.",
            }
        )
    if devices.get("cpu") is not True:
        reasons.append(
            {
                "code": "device_unavailable",
                "message": "The worker's CPU device is being checked or is unavailable.",
            }
        )
    if not writable:
        reasons.append(
            {
                "code": "insufficient_storage",
                "message": "Provide writable library storage with the configured free-space reserve.",
            }
        )
    return {
        "viewing_available": True,
        "processing_ready": not reasons,
        "backend": {"installed": backend},
        "decoder": decoders,
        "checkpoint": {
            "state": "cached" if cached else "missing",
            "repository": config.checkpoint,
            "revision": config.checkpoint_revision,
            "cached_bytes": sum(sizes.values()) if cached else None,
        },
        "torch_repository": {
            "state": "cached" if repository else "missing",
            "identity": "facebookresearch/dinov2:main",
            "separate_encoder_weights": False,
        },
        "devices": devices,
        "storage": {"writable": writable, "reserve_bytes": config.disk_reserve_bytes},
        "reasons": reasons,
        "profiles": {name: profile_settings(name) for name in ("standard", "quick_preview")},
        "policy": {
            "upload_limit_bytes": config.upload_limit,
            "maximum_video_seconds": config.maximum_video_seconds,
            "maximum_video_dimension": config.maximum_video_dimension,
            "maximum_video_pixels": config.maximum_video_pixels,
            "destination": "Managed local copy in the configured library",
        },
        "job_launch_available": False,
        "job_launch_message": "Start processing will become available with the processing job package.",
    }


class ReadinessManager:
    """One explicit setup process; device checks run separately without checkpoint loading."""

    def __init__(self, config: ApplicationConfig):
        self.config = config
        self.slot = HeavySlot(config.library.resolve())
        self._lock = self.slot.lock
        self.jobs_available = False
        self._cleanup_lock = threading.Lock()
        self._stop = threading.Event()
        self._process: subprocess.Popen | None = None
        self.devices = {"cpu": None, "cuda": None}
        self.state_path = config.library.resolve() / "runtime/model-setup.json"
        self.owner_path = self.state_path.with_name("model-setup-owner.json")
        self.worker_lock_path = self.state_path.with_name("model-setup-worker.lock")
        self.instance_nonce = secrets.token_hex(16)
        self._threads: list[threading.Thread] = []
        if not self.is_preparing():
            atomic_json(
                self.state_path,
                {
                    "state": "idle",
                    "download_bytes": None,
                    "message": "Model preparation is an explicit action. An interrupted setup may be retried.",
                },
            )
        if package_available("torch"):
            thread = threading.Thread(target=self._check_devices, daemon=True)
            self._threads.append(thread)
            thread.start()

    def is_preparing(self) -> bool:
        """Shared slot gate for the later JobManager, including surviving old-instance workers."""
        if self._process is not None:
            return True
        try:
            owner = json.loads(self.owner_path.read_text())
            identity = process_start_identity(owner.get("pid"))
            if identity is not None and identity == owner.get("start_identity"):
                return True
        except (OSError, ValueError, TypeError):
            pass
        return _worker_lock_busy(self.worker_lock_path)

    def _arguments(self, action: str) -> list[str]:
        return [
            sys.executable,
            "-m",
            "twinforge.application.setup_worker",
            action,
            "--hf-home",
            str(self.config.hf_home),
            "--hf-cache",
            str(self.config.hf_cache),
            "--torch-home",
            str(self.config.torch_home),
            "--checkpoint",
            self.config.checkpoint,
            "--revision",
            self.config.checkpoint_revision,
            "--reserve",
            str(self.config.disk_reserve_bytes),
            "--state",
            str(self.state_path),
        ]

    def _check_devices(self) -> None:
        # Device readiness is measured in the exact interpreter/environment used by setup/jobs.
        try:
            result = bounded_command(
                self._arguments("check-device"),
                timeout=30,
                output_limit=16384,
                env=self.config.worker_environment(),
            )
            devices = json.loads(result.stdout)
            with self._lock:
                self.devices = {key: devices.get(key) is True for key in ("cpu", "cuda")}
        except (OSError, ValueError, subprocess.SubprocessError):
            with self._lock:
                self.devices = {"cpu": False, "cuda": False}

    def status(self) -> dict:
        with self._lock:
            value = check_readiness(self.config, dict(self.devices))
            value["job_launch_available"] = (
                self.jobs_available
                and not self.slot.ownership_unresolved
                and not self.is_preparing()
            )
            value["job_launch_message"] = (
                "Processing runs in a separate worker. You can return to Scenes."
                if self.jobs_available
                else value["job_launch_message"]
            )
            value["heavy_operation_busy"] = self.slot.busy()
            value["ownership_unresolved"] = self.slot.ownership_unresolved
            try:
                setup = json.loads(self.state_path.read_text())
                # The worker is trusted, but only explicitly public setup fields leave the server.
                value["preparation"] = {
                    key: setup.get(key)
                    for key in ("state", "message", "download_bytes", "downloaded_bytes")
                }
            except (OSError, ValueError):
                value["preparation"] = {
                    "state": "failed",
                    "message": "Preparation status is unavailable.",
                }
            return value

    def prepare(self) -> dict:
        with self._lock:
            if (
                self._stop.is_set()
                or self.slot.ownership_unresolved
                or self.is_preparing()
                or self.slot.busy()
            ):
                raise UploadError("setup_busy")
            if not all(
                package_available(name)
                for name in ("torch", "mapanything", "uniception", "huggingface_hub")
            ):
                raise UploadError("model_not_prepared")
            atomic_json(
                self.state_path,
                {
                    "state": "preparing",
                    "download_bytes": None,
                    "message": "Discovering missing cache files and their download sizes.",
                },
            )
            try:
                descriptor = self.slot.acquire()
                self._process = subprocess.Popen(
                    self._arguments("prepare"),
                    env=self.config.worker_environment(offline=False),
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    start_new_session=True,
                    pass_fds=(descriptor,),
                )
                atomic_json(
                    self.owner_path,
                    {
                        "pid": self._process.pid,
                        "start_identity": process_start_identity(self._process.pid),
                        "instance_nonce": self.instance_nonce,
                    },
                )
                thread = threading.Thread(
                    target=self._supervise, args=(self._process,), daemon=True
                )
                thread.start()
                self._threads.append(thread)
            except (OSError, RuntimeError):
                if self._process is not None:
                    process = self._process
                    self._terminate_owned(process)
                    self._release_owned(process)
                else:
                    self.slot.release()
                self._record_failure(
                    "The setup worker could not start or publish ownership. Retry explicitly."
                )
                raise UploadError("model_not_prepared") from None
            return self.status()

    def _record_failure(self, message: str) -> None:
        try:
            atomic_json(self.state_path, {"state": "failed", "message": message})
        except OSError:
            pass  # Disk failure cannot prevent stopping/reaping an already owned child.

    def _terminate_owned(self, process: subprocess.Popen) -> None:
        with self._cleanup_lock:
            if process.poll() is None:
                try:
                    os.killpg(process.pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
                try:
                    process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    try:
                        os.killpg(process.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                    process.wait()
            else:
                process.wait()

    def _release_owned(self, process: subprocess.Popen) -> None:
        with self._lock:
            if self._process is not process or process.poll() is None:
                return
            self._process = None
            self.slot.release()
            try:
                atomic_json(
                    self.owner_path,
                    {"pid": None, "start_identity": None, "instance_nonce": self.instance_nonce},
                )
            except OSError:
                pass  # The dead PID cannot own another slot even if its record remains.

    def _supervise(self, process: subprocess.Popen | None = None) -> None:
        process = process if process is not None else self._process
        if process is None:
            return
        deadline = time.monotonic() + self.config.setup_timeout_seconds
        try:
            while process.poll() is None:
                if self._stop.wait(0.1) or time.monotonic() >= deadline:
                    self._terminate_owned(process)
                    self._record_failure("Preparation was stopped or timed out. Retry explicitly.")
                    break
            process.wait()
            if process.returncode and not self._stop.is_set():
                self._record_failure(
                    "Preparation failed. Check connectivity, backend installation, and free disk space, then retry."
                )
        finally:
            self._release_owned(process)
        if not self._stop.is_set():
            self._check_devices()

    def close(self) -> None:
        self._stop.set()
        for thread in self._threads:
            thread.join(timeout=35)
        with self._lock:
            process = self._process
        if process is not None:
            self._terminate_owned(process)
            self._release_owned(process)
            self._record_failure(
                "Preparation was stopped during application shutdown. Retry explicitly."
            )
