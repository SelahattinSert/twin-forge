"""Bounded local-only probing and one oriented, color-correct inspection still."""

from __future__ import annotations

import math
import shutil
import subprocess
import tempfile
import time
from dataclasses import asdict
from pathlib import Path

from twinforge.application.config import ApplicationConfig
from twinforge.application.types import InspectionRecord
from twinforge.exceptions import InvalidVideoError, VideoDecodeError
from twinforge.ingest.video import VideoIngestor


def bounded_command(
    command: list[str],
    *,
    timeout: float,
    output_limit: int,
    env: dict[str, str] | None = None,
    **unused,
) -> subprocess.CompletedProcess:
    """Drain to temporary files, enforce elapsed time and output size, reap every child."""
    with tempfile.TemporaryFile() as stdout, tempfile.TemporaryFile() as stderr:
        process = subprocess.Popen(
            command, stdin=subprocess.DEVNULL, stdout=stdout, stderr=stderr, env=env
        )
        deadline = time.monotonic() + timeout
        try:
            while process.poll() is None:
                if time.monotonic() > deadline:
                    raise subprocess.TimeoutExpired(command, timeout)
                if stdout.tell() + stderr.tell() > output_limit:
                    raise subprocess.SubprocessError("Inspection output limit exceeded")
                time.sleep(0.02)
            if stdout.tell() + stderr.tell() > output_limit:
                raise subprocess.SubprocessError("Inspection output limit exceeded")
            stdout.seek(0)
            stderr.seek(0)
            output, error = (
                stdout.read(output_limit).decode(errors="replace"),
                stderr.read(output_limit).decode(errors="replace"),
            )
            if process.returncode:
                raise subprocess.CalledProcessError(process.returncode, command, output, error)
            return subprocess.CompletedProcess(command, process.returncode, output, error)
        finally:
            if process.poll() is None:
                process.kill()
            process.wait()


def inspect_video(path: Path, scratch: Path, config: ApplicationConfig) -> InspectionRecord:
    # Delayed import avoids an application/ingest dependency cycle.
    from twinforge.application.uploads import UploadError

    if not shutil.which("ffprobe") or not shutil.which("ffmpeg"):
        raise UploadError("missing_decoder")

    def run(command, **kwargs):
        timeout = (
            config.probe_timeout_seconds if "-i" not in command else config.decode_timeout_seconds
        )
        return bounded_command(
            command, timeout=timeout, output_limit=config.subprocess_output_bytes, **kwargs
        )

    ingestor = VideoIngestor(command_runner=run, local_only=True)
    try:
        try:
            metadata = ingestor.inspect(path)
        except (ValueError, TypeError, OverflowError):
            raise UploadError("invalid_video") from None
        if (
            not math.isfinite(metadata.duration_seconds)
            or not 0 < metadata.duration_seconds <= config.maximum_video_seconds
        ):
            raise UploadError("inspection_limit")
        if (
            max(metadata.width, metadata.height) > config.maximum_video_dimension
            or metadata.width * metadata.height > config.maximum_video_pixels
        ):
            raise UploadError("inspection_limit")
        if not set((metadata.container or "").split(",")) & {"mov", "mp4", "matroska", "webm"}:
            raise UploadError("invalid_video")
        if (
            shutil.disk_usage(scratch).free
            < config.disk_reserve_bytes + config.preview_width**2 * 8
        ):
            raise UploadError("insufficient_storage")
        candidates = ingestor.decode_candidates(
            metadata,
            min(0.5, metadata.duration_seconds),
            config.preview_width,
            scratch,
            maximum_frames=1,
        )
        value = asdict(metadata)
        value.pop("path")
        return value | {
            "decode_ready": True,
            "preview": candidates[0].image_path.name,
            "preprocessing": ingestor.preprocessing,
            "browser_playback": "browser_dependent",
            "playback_fallback": "Video playback is unavailable in this browser. The file can still be processed.",
        }
    except InvalidVideoError:
        raise UploadError("invalid_video") from None
    except VideoDecodeError:
        raise UploadError("decode_failed") from None
    except (OSError, subprocess.SubprocessError):
        raise UploadError("inspection_failed") from None
