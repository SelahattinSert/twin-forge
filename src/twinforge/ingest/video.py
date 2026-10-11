"""FFmpeg based probing and display-oriented candidate extraction."""

from __future__ import annotations

import json
import logging
import math
import shutil
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import cv2

from twinforge.core.types import VideoMetadata
from twinforge.exceptions import InvalidVideoError, VideoDecodeError
from twinforge.ingest.color import ColorPolicyName, build_color_policy

logger = logging.getLogger(__name__)


@dataclass
class CandidateFrame:
    source_frame_index: int
    timestamp_seconds: float
    image_path: Path
    width: int
    height: int


def _ratio(value: str | None) -> float | None:
    if not value or value == "0/0":
        return None
    try:
        numerator, denominator = value.split("/", 1)
        denominator_value = float(denominator)
        return float(numerator) / denominator_value if denominator_value else None
    except (ValueError, ZeroDivisionError):
        return None


class VideoIngestor:
    """Inspect ordinary video files and decode a low-rate candidate stream."""

    def __init__(
        self,
        color_policy: ColorPolicyName = "auto",
        *,
        command_runner: Callable | None = None,
        local_only: bool = False,
    ) -> None:
        self.color_policy = color_policy
        self._command_runner = command_runner
        self.local_only = local_only
        self.preprocessing: dict[str, Any] = {}

    def _run(self, *args, **kwargs):
        runner = self._command_runner if self._command_runner is not None else subprocess.run
        return runner(*args, **kwargs)

    def inspect(self, path: Path) -> VideoMetadata:
        path = path.expanduser().resolve()
        if not path.is_file():
            raise InvalidVideoError(f"Input video does not exist: {path}")
        ffprobe = shutil.which("ffprobe")
        if not ffprobe:
            raise VideoDecodeError(
                "ffprobe was not found. Install FFmpeg and ensure ffprobe is on PATH."
            )
        command = [
            ffprobe,
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "format=format_name,duration:stream=codec_name,width,height,r_frame_rate,avg_frame_rate,nb_frames,color_primaries,color_transfer,color_space,color_range,pix_fmt:stream_tags=rotate:stream_side_data=rotation",
            "-of",
            "json",
            str(path),
        ]
        if self.local_only:
            command[-1:-1] = [
                "-protocol_whitelist",
                "file",
                "-format_whitelist",
                "mov,matroska,webm",
            ]
        try:
            completed = self._run(command, check=True, capture_output=True, text=True)
            data = json.loads(completed.stdout)
        except FileNotFoundError as exc:
            raise VideoDecodeError("ffprobe could not be started. Install FFmpeg.") from exc
        except subprocess.CalledProcessError as exc:
            message = exc.stderr.strip() or "ffprobe rejected the video stream"
            raise InvalidVideoError(f"Cannot inspect video: {message}") from exc
        except json.JSONDecodeError as exc:
            raise VideoDecodeError("ffprobe returned invalid metadata for the video.") from exc
        streams = data.get("streams") or []
        if not streams:
            raise InvalidVideoError("No readable video stream was found in the input file.")
        stream = streams[0]
        fmt = data.get("format", {})
        duration = _float(fmt.get("duration"), 0.0)
        if not math.isfinite(duration) or duration <= 0:
            raise InvalidVideoError("The video has zero or unknown duration.")
        rotation = _rotation(stream)
        width, height = int(stream.get("width", 0)), int(stream.get("height", 0))
        if width <= 0 or height <= 0:
            raise InvalidVideoError("The video stream reports invalid dimensions.")
        display_width, display_height = (
            (height, width) if rotation in (90, 270) else (width, height)
        )
        fps = _ratio(stream.get("avg_frame_rate")) or _ratio(stream.get("r_frame_rate"))
        frame_count = _optional_int(stream.get("nb_frames"))
        if frame_count is None and fps:
            frame_count = round(fps * duration)
        return VideoMetadata(
            path=str(path),
            container=fmt.get("format_name"),
            codec=stream.get("codec_name"),
            width=width,
            height=height,
            fps=fps,
            duration_seconds=duration,
            rotation_degrees=rotation,
            frame_count=frame_count,
            display_width=display_width,
            display_height=display_height,
            color_primaries=stream.get("color_primaries"),
            color_transfer=stream.get("color_transfer"),
            color_space=stream.get("color_space"),
            color_range=stream.get("color_range"),
            pixel_format=stream.get("pix_fmt"),
        )

    def decode_candidates(
        self,
        metadata: VideoMetadata,
        interval_seconds: float,
        max_width: int,
        work_dir: Path,
        *,
        maximum_frames: int | None = None,
    ) -> list[CandidateFrame]:
        ffmpeg = shutil.which("ffmpeg")
        if not ffmpeg:
            raise VideoDecodeError(
                "ffmpeg was not found. Install FFmpeg and ensure ffmpeg is on PATH."
            )
        if interval_seconds <= 0:
            raise ValueError("interval_seconds must be positive")
        if max_width <= 0:
            raise ValueError("max_width must be positive")
        policy = build_color_policy(metadata, self.color_policy)
        if policy["filter"]:
            try:
                available = self._run(
                    [ffmpeg, "-hide_banner", "-filters"], check=True, capture_output=True, text=True
                ).stdout
            except (OSError, subprocess.CalledProcessError) as exc:
                raise VideoDecodeError(
                    "FFmpeg filter probe failed. Install FFmpeg with libzimg and verify PATH."
                ) from exc
            names = {
                parts[1]
                for line in available.splitlines()
                if len(parts := line.split()) >= 3 and "->" in parts[2]
            }
            if not {"zscale", "tonemap"} <= names:
                raise VideoDecodeError(
                    "HDR input requires FFmpeg zscale and tonemap filters. "
                    "Install FFmpeg with libzimg or provide an SDR input."
                )
        work_dir.mkdir(parents=True, exist_ok=True)
        output_pattern = work_dir / "candidate_%06d.jpg"
        # FFmpeg autorotates by default; fps sampling retains display orientation and source timing.
        filters = f"fps=1/{interval_seconds},scale='min({max_width},iw)':-2"
        if policy["filter"]:
            filters += "," + policy["filter"]
        try:
            version = self._run(
                [ffmpeg, "-version"], check=True, capture_output=True, text=True
            ).stdout
        except (OSError, subprocess.CalledProcessError) as exc:
            raise VideoDecodeError(
                "FFmpeg version probe failed. Install FFmpeg and verify PATH."
            ) from exc
        self.preprocessing = {
            "schema_version": "0.2",
            "color": policy,
            "ffmpeg_version": version.splitlines()[0] if version else None,
            "exact_filter": filters,
            "rotation": "FFmpeg autorotate once",
            "source_dimensions": [metadata.width, metadata.height],
            "display_dimensions": [metadata.display_width, metadata.display_height],
            "crop": None,
            "resize": "display width bounded; aspect preserved; even height",
            "jpeg_dimensions": [],
            "analysis_longest_edge": 512,
            "timestamp_semantics": "nominal fps-filter sample grid; source indices estimated",
        }
        command = [
            ffmpeg,
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            metadata.path,
            "-vf",
            filters,
            "-q:v",
            "2",
            "-vsync",
            "0",
            str(output_pattern),
        ]
        if self.local_only:
            index = command.index("-i")
            command[index:index] = [
                "-protocol_whitelist",
                "file",
                "-format_whitelist",
                "mov,matroska,webm",
                "-threads",
                "1",
            ]
        if maximum_frames is not None:
            if type(maximum_frames) is not int or maximum_frames < 1:
                raise ValueError("maximum_frames must be a positive integer")
            command[-1:-1] = ["-frames:v", str(maximum_frames)]
        try:
            self._run(command, check=True, capture_output=True, text=True)
        except FileNotFoundError as exc:
            raise VideoDecodeError("ffmpeg could not be started. Install FFmpeg.") from exc
        except subprocess.CalledProcessError as exc:
            message = exc.stderr.strip() or "FFmpeg could not decode the video"
            raise VideoDecodeError(f"Video decode failed: {message}") from exc
        paths = sorted(work_dir.glob("candidate_*.jpg"))
        candidates: list[CandidateFrame] = []
        for sequence_index, image_path in enumerate(paths):
            image = cv2.imread(str(image_path), cv2.IMREAD_COLOR)
            if image is None:
                continue
            timestamp = min(sequence_index * interval_seconds, metadata.duration_seconds)
            source_index = round(timestamp * metadata.fps) if metadata.fps else sequence_index
            height, width = image.shape[:2]
            candidates.append(CandidateFrame(source_index, timestamp, image_path, width, height))
            del image
        if not candidates:
            raise VideoDecodeError(
                "No decodable frames were found. Check that FFmpeg can read this file."
            )
        self.preprocessing["jpeg_dimensions"] = sorted({(c.width, c.height) for c in candidates})
        self.preprocessing["pixel_transforms"] = [
            pixel_transform_record(metadata, width, height)
            for width, height in self.preprocessing["jpeg_dimensions"]
        ]
        logger.info(
            "Decoded %d candidate frames at %.3f-second intervals",
            len(candidates),
            interval_seconds,
        )
        return candidates


def pixel_transform_record(metadata: VideoMetadata, width: int, height: int) -> dict[str, Any]:
    """Integer pixel centers: source rotation followed by display-to-JPEG scaling."""
    rotations = {
        0: [[1, 0, 0], [0, 1, 0], [0, 0, 1]],
        90: [[0, 1, 0], [-1, 0, metadata.width - 1], [0, 0, 1]],
        180: [[-1, 0, metadata.width - 1], [0, -1, metadata.height - 1], [0, 0, 1]],
        270: [[0, -1, metadata.height - 1], [1, 0, 0], [0, 0, 1]],
    }
    sx, sy = width / metadata.display_width, height / metadata.display_height
    return {
        "source_dimensions": [metadata.width, metadata.height],
        "display_dimensions": [metadata.display_width, metadata.display_height],
        "jpeg_dimensions": [width, height],
        "crop": None,
        "pixel_convention": "integer centers; resize x_out=(x_in+0.5)*scale-0.5",
        "source_to_display": rotations.get(metadata.rotation_degrees),
        "display_to_jpeg": [[sx, 0, (sx - 1) / 2], [0, sy, (sy - 1) / 2], [0, 0, 1]],
        "mapping_limit": "Only quarter-turn rotations have an explicit source matrix",
    }


def _float(value: object, default: float) -> float:
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default


def _optional_int(value: object) -> int | None:
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def _rotation(stream: dict) -> int:
    rotation = _float((stream.get("tags") or {}).get("rotate"), math.nan)
    for side_data in stream.get("side_data_list", []):
        rotation = _float(side_data.get("rotation"), rotation)
        if not math.isnan(rotation):
            break
    if math.isnan(rotation):
        return 0
    return round(rotation) % 360
