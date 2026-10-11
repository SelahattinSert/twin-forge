"""Real FFmpeg color gradients and display rotation, without neural inference."""

import shutil
import subprocess

import cv2
import numpy as np
import pytest

from twinforge.core.types import VideoMetadata
from twinforge.ingest.color import build_color_policy
from twinforge.ingest.video import VideoIngestor

pytestmark = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="FFmpeg required")


@pytest.mark.parametrize("transfer", ["arib-std-b67", "smpte2084"])
def test_declared_hdr_gradient_is_nonblack_monotone_srgb(transfer):
    metadata = VideoMetadata(
        "fixture",
        "raw",
        "raw",
        256,
        16,
        1,
        1,
        0,
        1,
        256,
        16,
        "bt2020",
        transfer,
        "bt2020nc",
        "tv",
        "yuv420p10le",
    )
    policy = build_color_policy(metadata)
    gradient = np.tile(np.linspace(64, 940, 256, dtype=np.uint16), (16, 1))
    chroma = np.full((8, 128), 512, dtype=np.uint16)
    source = gradient.tobytes() + chroma.tobytes() * 2
    output = subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-f",
            "rawvideo",
            "-pixel_format",
            "yuv420p10le",
            "-video_size",
            "256x16",
            "-i",
            "pipe:0",
            "-vf",
            policy["filter"],
            "-frames:v",
            "1",
            "-f",
            "rawvideo",
            "-pix_fmt",
            "rgb24",
            "pipe:1",
        ],
        input=source,
        capture_output=True,
        check=True,
    ).stdout
    values = np.frombuffer(output, dtype=np.uint8).reshape(16, 256, 3)[8, :, 0].astype(int)
    assert values[-1] > 100
    assert values[0] < 5
    assert np.diff(values).min() >= -1


def test_portrait_rotation_keeps_dimensions_and_corner_mapping(tmp_path):
    source = tmp_path / "source.png"
    image = np.zeros((48, 64, 3), dtype=np.uint8)
    image[:24, :32] = (0, 0, 255)
    image[:24, 32:] = (0, 255, 0)
    image[24:, :32] = (255, 0, 0)
    image[24:, 32:] = (255, 255, 255)
    cv2.imwrite(str(source), image)
    movie = tmp_path / "unrotated.mp4"
    rotated = tmp_path / "rotated.mov"
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-loop",
            "1",
            "-i",
            str(source),
            "-t",
            "1",
            "-r",
            "2",
            "-pix_fmt",
            "yuv420p",
            str(movie),
        ],
        check=True,
    )
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-display_rotation",
            "90",
            "-i",
            str(movie),
            "-c",
            "copy",
            str(rotated),
        ],
        check=True,
    )
    ingestor = VideoIngestor()
    metadata = ingestor.inspect(rotated)
    candidates = ingestor.decode_candidates(metadata, 0.5, 1920, tmp_path / "frames")
    decoded = cv2.imread(str(candidates[0].image_path))
    assert (candidates[0].width, candidates[0].height) == (48, 64)
    # FFmpeg display matrix 90 degrees rotates counterclockwise: top right -> top left.
    assert decoded[8, 8, 1] > 200
    assert decoded[55, 8, 2] > 200
    assert ingestor.preprocessing["crop"] is None
    assert ingestor.preprocessing["color"]["filter"] == ""


@pytest.mark.parametrize("u,v", [(600, 450), (650, 600), (450, 650), (400, 480)])
def test_hdr_jpeg_decodes_to_intended_srgb_chromatic_patch(u, v):
    metadata = VideoMetadata(
        "fixture",
        "raw",
        "raw",
        32,
        32,
        1,
        1,
        0,
        1,
        32,
        32,
        "bt2020",
        "arib-std-b67",
        "bt2020nc",
        "tv",
        "yuv420p10le",
    )
    policy = build_color_policy(metadata)
    source = (
        np.full((32, 32), 512, dtype=np.uint16).tobytes()
        + np.full((16, 16), u, dtype=np.uint16).tobytes()
        + np.full((16, 16), v, dtype=np.uint16).tobytes()
    )
    base = [
        "ffmpeg",
        "-v",
        "error",
        "-f",
        "rawvideo",
        "-pixel_format",
        "yuv420p10le",
        "-video_size",
        "32x32",
        "-i",
        "pipe:0",
        "-vf",
        policy["filter"],
        "-frames:v",
        "1",
    ]
    reference = base.copy()
    reference[reference.index("-vf") + 1] = (
        policy["filter"].rsplit(",zscale=", 1)[0]
        + ",zscale=transfer=iec61966-2-1:matrix=gbr:range=full,format=rgb24"
    )
    rgb = subprocess.run(
        reference + ["-f", "rawvideo", "-pix_fmt", "rgb24", "pipe:1"],
        input=source,
        check=True,
        capture_output=True,
    ).stdout
    jpeg = subprocess.run(
        base + ["-q:v", "2", "-f", "image2pipe", "-c:v", "mjpeg", "pipe:1"],
        input=source,
        check=True,
        capture_output=True,
    ).stdout
    expected = np.frombuffer(rgb, dtype=np.uint8).reshape(32, 32, 3)[16, 16].astype(int)
    decoded = cv2.imdecode(np.frombuffer(jpeg, dtype=np.uint8), cv2.IMREAD_COLOR)[
        16, 16, ::-1
    ].astype(int)
    assert np.max(np.abs(expected - decoded)) <= 5
