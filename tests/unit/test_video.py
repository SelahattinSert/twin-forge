from __future__ import annotations

import json
import subprocess
from unittest.mock import patch

import pytest

from twinforge.exceptions import InvalidVideoError
from twinforge.ingest.video import VideoIngestor, _rotation


def test_default_runner_resolves_at_command_time_and_preserves_explicit_runner(tmp_path):
    from twinforge.exceptions import VideoDecodeError

    video = tmp_path / "original.mp4"
    video.write_bytes(b"probe failure fixture")
    default = VideoIngestor()
    with (
        patch("twinforge.ingest.video.shutil.which", return_value="ffprobe"),
        patch("twinforge.ingest.video.subprocess.run", side_effect=FileNotFoundError),
        pytest.raises(VideoDecodeError, match="Install FFmpeg"),
    ):
        default.inspect(video)

    def bounded_runner(*args, **kwargs):
        raise FileNotFoundError("explicit bounded runner")

    with (
        patch("twinforge.ingest.video.shutil.which", return_value="ffprobe"),
        patch("twinforge.ingest.video.subprocess.run", side_effect=AssertionError("default used")),
        pytest.raises(VideoDecodeError, match="Install FFmpeg"),
    ):
        VideoIngestor(command_runner=bounded_runner).inspect(video)


@pytest.mark.parametrize("probe", ["-filters", "-version"])
@pytest.mark.parametrize("failure", ["exit", "missing"])
def test_ffmpeg_setup_probe_failures_have_actionable_decoder_errors(tmp_path, probe, failure):
    from dataclasses import replace

    from twinforge.core.types import VideoMetadata
    from twinforge.exceptions import VideoDecodeError

    metadata = VideoMetadata("fixture.mov", "mov", "hevc", 64, 48, 1, 1, 0, 1, 64, 48)
    if probe == "-filters":
        metadata = replace(
            metadata,
            color_transfer="arib-std-b67",
            color_primaries="bt2020",
            color_space="bt2020nc",
            color_range="tv",
        )
    error = (
        subprocess.CalledProcessError(1, ["ffmpeg", probe], stderr="broken setup")
        if failure == "exit"
        else FileNotFoundError("missing executable")
    )
    with (
        patch("twinforge.ingest.video.shutil.which", return_value="ffmpeg"),
        patch("twinforge.ingest.video.subprocess.run", side_effect=error),
        pytest.raises(VideoDecodeError, match="Install FFmpeg"),
    ):
        VideoIngestor().decode_candidates(metadata, 0.5, 64, tmp_path)


def test_decoded_candidates_keep_paths_not_images_and_timestamps_survive_bad_jpeg(tmp_path):
    import cv2
    import numpy as np

    from twinforge.core.types import VideoMetadata

    work = tmp_path / "candidates"
    work.mkdir()
    for index in (1, 3):
        cv2.imwrite(str(work / f"candidate_{index:06d}.jpg"), np.zeros((20, 30, 3), dtype=np.uint8))
    (work / "candidate_000002.jpg").write_bytes(b"invalid jpeg")
    metadata = VideoMetadata("fixture.mp4", "mp4", "h264", 30, 20, 30, 2, 0, 60, 30, 20)
    with (
        patch("twinforge.ingest.video.shutil.which", return_value="ffmpeg"),
        patch("twinforge.ingest.video.subprocess.run"),
    ):
        candidates = VideoIngestor().decode_candidates(metadata, 0.5, 30, work)
    assert [frame.timestamp_seconds for frame in candidates] == [0, 1]
    assert [frame.source_frame_index for frame in candidates] == [0, 30]
    assert all(frame.width == 30 and frame.height == 20 for frame in candidates)
    assert all(not hasattr(frame, "image") for frame in candidates)


def test_recorded_rotation_and_resize_map_pixel_centers():
    import numpy as np

    from twinforge.core.types import VideoMetadata
    from twinforge.ingest.video import pixel_transform_record

    metadata = VideoMetadata("fixture.mov", "mov", "hevc", 64, 48, 1, 1, 90, 1, 48, 64)
    record = pixel_transform_record(metadata, 24, 32)
    display = np.asarray(record["source_to_display"]) @ [63, 0, 1]
    assert np.array_equal(display, [0, 0, 1])
    jpeg = np.asarray(record["display_to_jpeg"]) @ display
    assert np.allclose(jpeg, [-0.25, -0.25, 1])


def test_hdr_filter_check_does_not_accept_filter_names_only_in_descriptions(tmp_path):
    from dataclasses import replace
    from types import SimpleNamespace

    import pytest

    from twinforge.core.types import VideoMetadata
    from twinforge.exceptions import VideoDecodeError

    metadata = replace(
        VideoMetadata("fixture.mov", "mov", "hevc", 64, 48, 1, 1, 0, 1, 64, 48),
        color_transfer="arib-std-b67",
        color_primaries="bt2020",
        color_space="bt2020nc",
        color_range="tv",
    )
    with (
        patch("twinforge.ingest.video.shutil.which", return_value="ffmpeg"),
        patch(
            "twinforge.ingest.video.subprocess.run",
            return_value=SimpleNamespace(stdout=" ... other V->V uses zscale and tonemap"),
        ),
        pytest.raises(VideoDecodeError, match="Install FFmpeg with libzimg"),
    ):
        VideoIngestor().decode_candidates(metadata, 0.5, 64, tmp_path)


def test_rotation_metadata_supports_tag_and_side_data():
    assert _rotation({"tags": {"rotate": "90"}}) == 90
    assert _rotation({"side_data_list": [{"rotation": -90}]}) == 270
    assert _rotation({}) == 0


def test_inspect_parses_display_orientation_and_fps(tmp_path):
    video = tmp_path / "phone.mov"
    video.touch()
    response = {
        "format": {"format_name": "mov,mp4", "duration": "2.0"},
        "streams": [
            {
                "codec_name": "h264",
                "width": 1920,
                "height": 1080,
                "avg_frame_rate": "30000/1001",
                "nb_frames": "60",
                "side_data_list": [{"rotation": "90"}],
            }
        ],
    }

    class Completed:
        stdout = json.dumps(response)

    with (
        patch("twinforge.ingest.video.shutil.which", return_value="/usr/bin/ffprobe"),
        patch("twinforge.ingest.video.subprocess.run", return_value=Completed()),
    ):
        metadata = VideoIngestor().inspect(video)
    assert metadata.rotation_degrees == 90
    assert (metadata.display_width, metadata.display_height) == (1080, 1920)
    assert metadata.fps == 30000 / 1001


def test_inspect_rejects_missing_video(tmp_path):
    try:
        VideoIngestor().inspect(tmp_path / "missing.mp4")
    except InvalidVideoError as exc:
        assert "does not exist" in str(exc)
    else:
        raise AssertionError("expected InvalidVideoError")
