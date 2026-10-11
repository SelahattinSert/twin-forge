"""HTTP transfer and real FFmpeg inspection without model loading or inference."""

import hashlib
import http.client
import json
import shutil
import subprocess
import threading

import cv2
import pytest

from twinforge.application.config import ApplicationConfig
from twinforge.application.server import ApplicationServer


@pytest.fixture
def application(tmp_path, monkeypatch):
    # Missing setup must leave uploads/browsing usable; no real Torch device probes in tests.
    monkeypatch.setattr("twinforge.application.readiness.package_available", lambda _: False)
    server = ApplicationServer(
        ApplicationConfig(
            library=tmp_path / "library", upload_limit=2 * 1024**2, disk_reserve_bytes=1
        )
    )
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    yield server
    server.shutdown()
    server.server_close()
    worker.join(timeout=2)


def request(server, path, method="GET", value=None, data=None, extra=None):
    connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=20)
    headers = {"Origin": server.url.rstrip("/"), "X-TwinForge-Token": server.request_token}
    if value is not None:
        data = json.dumps(value).encode()
        headers["Content-Type"] = "application/json"
    headers.update(extra or {})
    try:
        connection.request(method, path, data, headers)
        response = connection.getresponse()
        body = response.read()
        return response.status, json.loads(body) if "application/json" in response.getheader(
            "Content-Type", ""
        ) else body
    finally:
        connection.close()


def transfer(server, data, name="video.mp4"):
    status, receipt = request(
        server,
        "/api/uploads",
        "POST",
        {"client_name": name, "expected_bytes": len(data), "mime": "arbitrary/hint"},
    )
    assert status == 201, receipt
    base = "/api/uploads/" + receipt["upload_id"]
    assert request(server, base + "/content", "PUT", data=data)[0] == 200
    return base, receipt


@pytest.fixture
def movie(tmp_path):
    if not shutil.which("ffmpeg"):
        pytest.skip("FFmpeg required")
    path = tmp_path / "fixture.mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "testsrc2=size=96x64:rate=2",
            "-t",
            "1",
            "-c:v",
            "mpeg4",
            str(path),
        ],
        check=True,
    )
    return path


def test_valid_unicode_duplicates_durable_without_open_scene(application, movie):
    data = movie.read_bytes()
    scenes = []
    for _ in range(2):
        base, _ = transfer(application, data, "../Café.MP4")
        status, result = request(
            application, base + "/complete", "POST", {"name": "Café room", "profile": "standard"}
        )
        assert status == 201, result
        scene = result["scene"]
        assert scene["status"] == "ready_to_start" and scene["default_run_id"] is None
        assert scene["versions"] == [] and scene["default_session_id"] is None
        assert scene["media"]["sha256"] == hashlib.sha256(data).hexdigest()
        assert scene["media"]["inspection"]["display_width"] == 96
        assert str(application.library.root) not in json.dumps(result)
        assert request(application, scene["thumbnail_url"])[0] == 200
        assert request(application, base + "/complete", "POST", {"name": "Café room"})[0] == 200
        scenes.append(scene)
    assert scenes[0]["scene_id"] != scenes[1]["scene_id"]
    assert scenes[0]["media"]["media_id"] != scenes[1]["media"]["media_id"]
    assert len(request(application, "/api/library/scenes")[1]["scenes"]) == 2
    assert not application.cache.entries
    for scene in scenes:
        source = (
            application.library.media_path(scene["scene_id"], scene["media"]["media_id"])
            / "original.mp4"
        )
        assert source.read_bytes() == data
    assert request(application, "/api/readiness")[1]["viewing_available"]
    scene = scenes[0]
    status, review = request(
        application,
        f"/api/library/scenes/{scene['scene_id']}/media/review",
        "POST",
        {"name": "Reviewed", "profile": "quick_preview", "device": "cpu"},
    )
    assert status == 200 and review["name"] == "Reviewed"
    assert review["media"]["review_settings"]["profile"] == "quick_preview"
    assert review["media"]["review_settings"]["auto_budget"]
    assert request(
        application, f"/api/library/scenes/{scene['scene_id']}/video", extra={"Range": "bytes=0-15"}
    ) == (206, data[:16])
    from twinforge.application.library import LibraryStore

    application.library.close()
    with LibraryStore(application.library.config) as restarted:
        assert len(restarted.list()["scenes"]) == 2
        assert (
            restarted.summary(restarted.get(scene["scene_id"]))["media"]["review_settings"][
                "profile"
            ]
            == "quick_preview"
        )


def test_invalid_content_is_actionable_and_private(application):
    base, _ = transfer(application, b"private /some/path is not video")
    status, result = request(application, base + "/complete", "POST", {"name": "Invalid"})
    assert status == 422 and result["error"]["code"] == "invalid_video"
    assert b"/some/path" not in json.dumps(result).encode()
    assert not request(application, "/api/library/scenes")[1]["scenes"]


def test_reload_discovers_created_and_transferred_uploads_for_recovery(application, movie):
    _, created = request(
        application,
        "/api/uploads",
        "POST",
        {"client_name": "Before transfer.mp4", "expected_bytes": 4},
    )
    base, transferred = transfer(application, movie.read_bytes(), "After transfer.mp4")
    status, page = request(application, "/api/uploads")
    assert status == 200
    assert {item["upload_id"] for item in page["uploads"]} == {
        created["upload_id"],
        transferred["upload_id"],
    }
    assert str(application.library.root) not in json.dumps(page)
    assert (
        request(application, f"/api/uploads/{created['upload_id']}/discard", "POST", {})[0] == 200
    )
    status, result = request(application, base + "/complete", "POST", {"name": "Recovered"})
    assert status == 201 and result["scene"]["name"] == "Recovered"
    assert request(application, "/api/uploads")[1]["uploads"] == []


def test_audio_only_is_not_a_video(application, tmp_path):
    if not shutil.which("ffmpeg"):
        pytest.skip("FFmpeg required")
    path = tmp_path / "audio.mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=1000",
            "-t",
            "0.2",
            str(path),
        ],
        check=True,
    )
    base, _ = transfer(application, path.read_bytes())
    status, result = request(application, base + "/complete", "POST", {"name": "Audio"})
    assert status == 422 and result["error"]["code"] == "invalid_video"


@pytest.mark.parametrize(
    "name,size,code",
    [
        ("a.exe", 10, "invalid_extension"),
        ("a.mp4", 0, "invalid_size"),
        ("a.mp4", 2 * 1024**2 + 1, "size_limit"),
    ],
)
def test_http_declaration_rejections(application, name, size, code):
    status, result = request(
        application, "/api/uploads", "POST", {"client_name": name, "expected_bytes": size}
    )
    assert status in (413, 422) and result["error"]["code"] == code


def test_content_lengths_and_chunked_encoding_are_rejected(application):
    _, receipt = request(
        application, "/api/uploads", "POST", {"client_name": "a.mp4", "expected_bytes": 4}
    )
    path = "/api/uploads/" + receipt["upload_id"] + "/content"
    status, result = request(application, path, "PUT", data=b"abcde")
    assert status == 422 and result["error"]["code"] == "length_mismatch"
    status, result = request(
        application, path, "PUT", data=b"abc", extra={"Transfer-Encoding": "chunked"}
    )
    assert status == 422 and result["error"]["code"] == "invalid_length"
    connection = http.client.HTTPConnection("127.0.0.1", application.server_port, timeout=10)
    connection.putrequest("PUT", path)
    for name, value in [
        ("Origin", application.url.rstrip("/")),
        ("X-TwinForge-Token", application.request_token),
        ("Content-Length", "4"),
        ("Content-Length", "4"),
    ]:
        connection.putheader(name, value)
    connection.endheaders(b"data")
    response = connection.getresponse()
    assert (
        response.status == 422 and json.loads(response.read())["error"]["code"] == "invalid_length"
    )
    connection.close()


def test_disconnect_and_oversize_header_do_not_read_or_register_media(application):
    import socket

    _, receipt = request(
        application, "/api/uploads", "POST", {"client_name": "a.mp4", "expected_bytes": 4}
    )
    path = "/api/uploads/" + receipt["upload_id"] + "/content"
    connection = http.client.HTTPConnection("127.0.0.1", application.server_port, timeout=10)
    connection.putrequest("PUT", path)
    for name, value in [
        ("Origin", application.url.rstrip("/")),
        ("X-TwinForge-Token", application.request_token),
        ("Content-Length", str(application.library.config.upload_limit + 1)),
    ]:
        connection.putheader(name, value)
    connection.endheaders()
    response = connection.getresponse()
    assert response.status == 413 and json.loads(response.read())["error"]["code"] == "size_limit"
    connection.close()
    connection = http.client.HTTPConnection("127.0.0.1", application.server_port, timeout=10)
    connection.putrequest("PUT", path)
    for name, value in [
        ("Origin", application.url.rstrip("/")),
        ("X-TwinForge-Token", application.request_token),
        ("Content-Length", "4"),
    ]:
        connection.putheader(name, value)
    connection.endheaders(b"ab")
    connection.sock.shutdown(socket.SHUT_WR)
    response = connection.getresponse()
    assert (
        response.status == 422
        and json.loads(response.read())["error"]["code"] == "incomplete_transfer"
    )
    connection.close()
    assert request(application, path.rsplit("/", 1)[0])[1]["state"] == "failed"
    assert not request(application, "/api/library/scenes")[1]["scenes"]


def test_drip_transfer_deadline_bounds_server_shutdown(application):
    import time
    from dataclasses import replace

    application.uploads.config = replace(application.uploads.config, transfer_timeout_seconds=0.15)
    _, receipt = request(
        application, "/api/uploads", "POST", {"client_name": "slow.mp4", "expected_bytes": 64}
    )
    path = "/api/uploads/" + receipt["upload_id"] + "/content"
    connection = http.client.HTTPConnection("127.0.0.1", application.server_port, timeout=2)
    connection.putrequest("PUT", path)
    for name, value in [
        ("Origin", application.url.rstrip("/")),
        ("X-TwinForge-Token", application.request_token),
        ("Content-Length", "64"),
    ]:
        connection.putheader(name, value)
    connection.endheaders()
    sock = connection.sock
    stop = threading.Event()

    def drip():
        try:
            while not stop.wait(0.02):
                sock.sendall(b"x")
        except OSError:
            pass

    writer = threading.Thread(target=drip, daemon=True)
    writer.start()
    deadline = time.monotonic() + 1
    while (
        application.uploads.get(receipt["upload_id"])["state"] == "created"
        and time.monotonic() < deadline
    ):
        time.sleep(0.005)
    started = time.monotonic()

    def shutdown():
        application.shutdown()
        application.server_close()

    closer = threading.Thread(target=shutdown, daemon=True)
    closer.start()
    try:
        response = connection.getresponse()
        assert (
            response.status == 422
            and json.loads(response.read())["error"]["code"] == "transfer_failed"
        )
        closer.join(timeout=1)
        assert not closer.is_alive() and time.monotonic() - started < 1
        receipt = application.uploads.get(receipt["upload_id"])
        assert receipt["state"] == "failed" and receipt["received_bytes"] < 64
        assert not application.library.list()["scenes"]
    finally:
        stop.set()
        connection.close()
        writer.join(timeout=1)
        closer.join(timeout=2)


def test_missing_decoder_is_actionable_and_does_not_block_library(application, movie, monkeypatch):
    base, _ = transfer(application, movie.read_bytes())
    monkeypatch.setattr("twinforge.application.inspection.shutil.which", lambda _: None)
    status, result = request(application, base + "/complete", "POST", {"name": "Missing decoder"})
    assert status == 422 and result["error"]["code"] == "missing_decoder"
    assert request(application, "/api/library/scenes")[0] == 200


def test_hlg_portrait_preview_preserves_color_policy_and_source(application, tmp_path):
    if not shutil.which("ffmpeg"):
        pytest.skip("FFmpeg required")
    movie = tmp_path / "hlg.mp4"
    rotated = tmp_path / "rotated.mov"
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "testsrc2=size=96x64:rate=2",
            "-t",
            "1",
            "-c:v",
            "libx265",
            "-x265-params",
            "log-level=error:pools=1:colorprim=9:transfer=18:colormatrix=9",
            "-pix_fmt",
            "yuv420p10le",
            "-color_primaries",
            "bt2020",
            "-color_trc",
            "arib-std-b67",
            "-colorspace",
            "bt2020nc",
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
    data = rotated.read_bytes()
    base, _ = transfer(application, data, "portrait.mov")
    status, result = request(application, base + "/complete", "POST", {"name": "Portrait"})
    assert status == 201, result
    scene = result["scene"]
    inspection = scene["media"]["inspection"]
    assert [inspection["display_width"], inspection["display_height"]] == [64, 96]
    assert inspection["preprocessing"]["color"]["policy"] == "hlg"
    assert inspection["preprocessing"]["rotation"] == "FFmpeg autorotate once"
    preview = application.library.thumbnail(scene["scene_id"])
    image = cv2.imread(str(preview))
    assert image.shape[:2] == (96, 64) and image.max() > 80
    assert scene["media"]["sha256"] == hashlib.sha256(data).hexdigest()
    assert inspection["decode_ready"]


def test_disguised_playlist_is_rejected_before_opening_external_files(application, tmp_path):
    outside = tmp_path / "private.txt"
    outside.write_text("Private source must not be inspected")
    playlist = f"#EXTM3U\n#EXTINF:1,\n{outside}\n".encode()
    base, _ = transfer(application, playlist)
    status, result = request(application, base + "/complete", "POST", {"name": "Playlist"})
    assert status == 422 and result["error"]["code"] == "invalid_video"
    assert outside.read_text() == "Private source must not be inspected"
    assert str(outside) not in json.dumps(result)
