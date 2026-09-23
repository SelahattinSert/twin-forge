"""FFmpeg based probing and display-oriented candidate extraction."""

from __future__ import annotations

import json
import logging
import math
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

import cv2

from twinforge.core.types import VideoMetadata
from twinforge.exceptions import InvalidVideoError, VideoDecodeError

logger = logging.getLogger(__name__)


@dataclass
class CandidateFrame:
    source_frame_index: int
    timestamp_seconds: float
    image_path: Path
    image: object


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
            "format=format_name,duration:stream=codec_name,width,height,r_frame_rate,avg_frame_rate,nb_frames:stream_tags=rotate:stream_side_data=rotation",
            "-of",
            "json",
            str(path),
        ]
        try:
            completed = subprocess.run(command, check=True, capture_output=True, text=True)
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
        if duration <= 0:
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
        )

    def decode_candidates(
        self,
        metadata: VideoMetadata,
        interval_seconds: float,
        max_width: int,
        work_dir: Path,
    ) -> list[CandidateFrame]:
        ffmpeg = shutil.which("ffmpeg")
        if not ffmpeg:
            raise VideoDecodeError(
                "ffmpeg was not found. Install FFmpeg and ensure ffmpeg is on PATH."
            )
        if interval_seconds <= 0:
            raise ValueError("interval_seconds must be positive")
        work_dir.mkdir(parents=True, exist_ok=True)
        output_pattern = work_dir / "candidate_%06d.jpg"
        # FFmpeg autorotates by default; fps sampling retains display orientation and source timing.
        filters = f"fps=1/{interval_seconds},scale='min({max_width},iw)':-2"
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
        try:
            subprocess.run(command, check=True, capture_output=True, text=True)
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
            candidates.append(CandidateFrame(source_index, timestamp, image_path, image))
        if not candidates:
            raise VideoDecodeError(
                "No decodable frames were found. Check that FFmpeg can read this file."
            )
        logger.info(
            "Decoded %d candidate frames at %.3f-second intervals",
            len(candidates),
            interval_seconds,
        )
        return candidates


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
