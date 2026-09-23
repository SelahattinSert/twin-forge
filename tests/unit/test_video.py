from __future__ import annotations

import json
from unittest.mock import patch

from twinforge.exceptions import InvalidVideoError
from twinforge.ingest.video import VideoIngestor, _rotation


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
