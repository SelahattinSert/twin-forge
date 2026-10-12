"""Private subprocess entry point; real jobs always invoke the existing MapAnything engine."""

from __future__ import annotations

import argparse
import json
import os
import socket
import traceback
from collections import deque
from contextlib import contextmanager
from dataclasses import asdict
from pathlib import Path

from twinforge.application.job_config import config_digest, thaw_config
from twinforge.application.library import atomic_json
from twinforge.application.types import timestamp
from twinforge.scene.reader import sha256_file


@contextmanager
def offline_network():
    """Deny IP resolution/connections in this worker only, preserving Unix sockets.

    Installed torch.hub._parse_repo_info catches urllib's URLError wrapping
    this OSError and selects the existing main cache. No altered model loader,
    tensors, source files or global application HTTP networking are involved.
    """
    lookup, connect, connect_ex, sendto = (
        socket.getaddrinfo,
        socket.socket.connect,
        socket.socket.connect_ex,
        socket.socket.sendto,
    )

    def denied(*args, **kwargs):
        raise OSError("Application processing is offline; use Prepare model for missing files")

    def guarded(original):
        def call(stream, *args, **kwargs):
            if stream.family in (socket.AF_INET, socket.AF_INET6):
                return denied()
            return original(stream, *args, **kwargs)

        return call

    socket.getaddrinfo = denied
    socket.socket.connect = guarded(connect)
    socket.socket.connect_ex = guarded(connect_ex)
    socket.socket.sendto = guarded(sendto)
    try:
        yield
    finally:
        socket.getaddrinfo, socket.socket.connect = lookup, connect
        socket.socket.connect_ex, socket.socket.sendto = connect_ex, sendto


def verify_input(job: dict) -> Path:
    path = Path(job["input"]["path"])
    expected = Path(job["library"]) / "scenes" / job["scene_id"] / "media" / job["media_id"]
    if (
        not path.resolve(strict=True).is_relative_to(expected.resolve())
        or path.stat().st_size != job["input"]["bytes"]
        or sha256_file(path) != job["input"]["sha256"]
    ):
        raise ValueError("Managed original bytes changed; add the original video again")
    if config_digest(job["config"]) != job["config_sha256"]:
        raise ValueError("Frozen processing settings changed")
    return path


def run_worker(path: Path, nonce: str) -> int:
    job = json.loads(path.read_text())
    if job["nonce"] != nonce:
        raise ValueError("Worker invocation does not own this job")
    stage = "checking_input"
    base = path.parent
    receipt = {key: job[key] for key in ("job_id", "run_id", "nonce", "config_sha256")}
    events = deque(maxlen=128)

    def progress(event):
        nonlocal stage
        stage = event.stage
        events.append(asdict(event))
        atomic_json(base / "progress.json", {"events": list(events)}, backup=False)

    try:
        video = verify_input(job)
        scratch = base / "scratch"
        scratch.mkdir(exist_ok=True)
        repo = Path(job["cache"]["torch_home"]) / "hub/facebookresearch_dinov2_main"
        if sha256_file(repo / "hubconf.py") != job["cache"]["hubconf_sha256"]:
            raise ValueError("Cached Torch source changed; check preparation")
        with offline_network():
            from twinforge.backends.mapanything import MapAnythingBackend
            from twinforge.ingest.video import VideoIngestor
            from twinforge.reconstruction.orchestrator import ReconstructionOrchestrator

            config = thaw_config(job["config"])
            engine = ReconstructionOrchestrator(
                MapAnythingBackend(config.backend.checkpoint, config.backend.checkpoint_revision),
                config,
            )
            engine.ingestor = VideoIngestor(config.video.color_policy, local_only=True)
            output = engine.run(video, scratch_root=scratch, on_progress=progress)
        receipt.update(state="complete", output_path=str(output.resolve()), timestamp=timestamp())
        atomic_json(base / "receipt.json", receipt, backup=False)
        return 0
    except Exception as exc:  # noqa: BLE001 - process boundary records every engine failure
        # Diagnostic text remains private; only fixed public messages are returned by jobs.
        with (base / "failure.log").open("w") as stream:
            stream.write(traceback.format_exc()[-32768:])
        receipt.update(
            state="failed", failure_type=type(exc).__name__, stage=stage, timestamp=timestamp()
        )
        atomic_json(base / "receipt.json", receipt, backup=False)
        return 1


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--job", type=Path, required=True)
    parser.add_argument("--nonce", required=True)
    parser.add_argument("--slot-fd", type=int, required=True)
    args = parser.parse_args()
    # Keep the inherited open file description for the lifetime of all worker work.
    os.fstat(args.slot_fd)
    return run_worker(args.job, args.nonce)


if __name__ == "__main__":
    raise SystemExit(main())
