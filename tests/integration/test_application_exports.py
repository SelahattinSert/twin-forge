"""Allowlisted streamed bundles reopen independently with their saved evidence."""
# ruff: noqa: F811

import http.client
import io
import json
import struct
import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "unit"))

import pytest
from test_application_scenes import prefix, request
from test_application_versions import calibrate, version_app  # noqa: F401
from test_calibrated_scene import scene_files  # noqa: F401


def export(server, record, kind="package"):
    status, value = request(
        server,
        "/api/exports",
        "POST",
        {
            "scene_id": record["scene_id"],
            "version_id": record["default_version_id"],
            "kind": kind,
        },
    )
    assert status == 201
    return value


def reopen(server, data):
    connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=10)
    connection.request(
        "POST",
        "/api/packages/open",
        data,
        {
            "Origin": server.url.rstrip("/"),
            "X-TwinForge-Token": server.request_token,
            "Content-Type": "application/zip",
        },
    )
    response = connection.getresponse()
    body = response.read()
    connection.close()
    return response.status, json.loads(body) if response.status == 201 else body


def test_package_retains_frozen_version_without_original_workspace(version_app):
    server, source = version_app
    version = calibrate(server, source)
    run = server.library.run(source["scene_id"], source["default_run_id"])
    (Path(run["source_root"]) / "private-original.MOV").write_bytes(b"must not be exported")
    result = export(server, version)
    status, data = request(server, result["download_url"])
    assert status == 200
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        assert not any(name.endswith(".MOV") for name in archive.namelist())
        package = json.loads(archive.read("package.json"))
        assert package["contains_source_images"] is True
    workspace = server.library.workspace(
        source["scene_id"], source["default_run_id"], version["default_session_id"]
    )
    workspace.rename(workspace.with_name(workspace.name + "-unavailable"))
    original = Path(run["source_root"])
    original.rename(original.with_name(original.name + "-unavailable"))
    status, restored = reopen(server, data)
    assert status == 201
    assert restored["source_kind"] == "package"
    assert request(server, prefix(restored) + "/calibration")[1]["scalar"] == 0.41
    assert request(server, prefix(restored) + "/scene")[1]["derived_available"]
    assert request(server, prefix(restored) + "/measurements/width")[0] == 200
    assert request(server, prefix(restored) + "/check-report")[1]["excluded_control_id"] == "width"
    assert request(server, prefix(restored) + "/frames/3/image")[0] == 200


def test_download_is_streamed_and_unknown_artifacts_rejected(version_app, monkeypatch):
    server, source = version_app
    result = export(server, source, "ply")
    # Exercise a transfer spanning multiple bounded chunks, independent of geometry size.
    artifact = server.exports.artifact(result["export_id"])
    with artifact.open("ab") as output:
        for _ in range(4):
            output.write(b"x" * server.library.config.transfer_chunk_bytes)
    from twinforge.application.library import atomic_json
    from twinforge.scene.reader import sha256_file

    result.update(sha256=sha256_file(artifact), bytes=artifact.stat().st_size)
    atomic_json(artifact.parent / "export.json", result)
    original = Path.read_bytes

    def reject_large_read(path):
        if path.suffix in (".ply", ".zip", ".glb"):
            raise AssertionError("Artifact must stream")
        return original(path)

    monkeypatch.setattr(Path, "read_bytes", reject_large_read)
    assert request(server, result["download_url"])[0] == 200
    assert request(server, result["download_url"] + "/../../library.json")[0] != 200
    status, unavailable = request(
        server,
        "/api/exports",
        "POST",
        {
            "scene_id": source["scene_id"],
            "version_id": source["default_version_id"],
            "kind": "glb",
        },
    )
    assert status == 200 and unavailable["status"] == "unavailable"


@pytest.mark.parametrize(
    "attack", ["traversal", "hash", "unlisted", "duplicate", "symlink", "expanded"]
)
def test_reopen_rejects_invalid_package_without_publishing(version_app, attack):
    server, source = version_app
    result = export(server, source)
    data = request(server, result["download_url"])[1]
    if attack == "expanded":
        object.__setattr__(server.library.config, "upload_quota_bytes", 1)
    output = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(data)) as old, zipfile.ZipFile(output, "w") as new:
        for item in old.infolist():
            content = old.read(item)
            if attack == "hash" and item.filename.endswith(".ply"):
                content += b"changed"
            if attack == "symlink" and item.filename.endswith(".ply"):
                item.external_attr = 0o120777 << 16
            new.writestr(item, content)
        if attack == "duplicate":
            with pytest.warns(UserWarning, match="Duplicate"):
                new.writestr("package.json", old.read("package.json"))
        if attack in ("traversal", "unlisted"):
            new.writestr("../escape" if attack == "traversal" else "unlisted.txt", b"bad")
    assert reopen(server, output.getvalue())[0] == 422
    assert len(server.library.list()["scenes"]) == 1


@pytest.mark.parametrize("error", [ConnectionResetError, BrokenPipeError])
def test_stream_peer_disconnect_does_not_send_second_response(error):
    from types import SimpleNamespace

    from twinforge.application.server import ApplicationHandler

    handler = ApplicationHandler.__new__(ApplicationHandler)
    handler.path = "/api/library/scenes/scene_example/video"
    handler.server = SimpleNamespace(library=SimpleNamespace(get=lambda _: {}))
    handler._allowed_request = lambda: True

    def disconnected(_):
        raise error("Browser closed playback after response headers")

    handler._video = disconnected
    errors = []
    handler._send = lambda *args: errors.append(args)
    handler.do_GET()
    assert errors == []


def test_legacy_layout_and_zip_pixel_proofs_reopen_without_machine_paths(
    scene_files, tmp_path, monkeypatch
):
    import threading

    import numpy as np

    from twinforge.application.config import ApplicationConfig
    from twinforge.application.server import ApplicationServer
    from twinforge.core.types import PointCloud
    from twinforge.export.ply import write_ply
    from twinforge.scene.provenance import PixelTransform
    from twinforge.scene.reader import SceneReader, sha256_file

    # Explicit legacy schema alone may refer to its bounded experimental root.
    root = scene_files
    directory = root / "scene"
    directory.mkdir()
    (root / "frames").mkdir()
    for frame in (3, 17):
        (root / f"frame_{frame}.jpg").rename(root / "frames" / f"frame_{frame}.jpg")
    for name in ("scene.json", "keyframes.json", "cameras.json"):
        (root / name).rename(directory / name)
    manifest = json.loads((directory / "scene.json").read_text())
    manifest.update(
        schema_version="experimental-original-source-0.1",
        point_cloud="../pointcloud.ply",
        point_count=182,
    )
    manifest.pop("pixel_transforms")
    (directory / "scene.json").write_text(json.dumps(manifest))
    frames = json.loads((directory / "keyframes.json").read_text())
    for frame in frames["frames"]:
        frame["image_path"] = "../frames/" + frame["image_path"]
    (directory / "keyframes.json").write_text(json.dumps(frames))
    xyz = np.array([[0 if i % 13 < 6 else 2, 0, 1] for i in range(91)], dtype=np.float32)
    write_ply(
        root / "pointcloud.ply",
        PointCloud(
            xyz=np.tile(xyz, (2, 1)),
            source_frame_id=np.repeat([3, 17], 91).astype(np.uint32),
            valid_mask=np.ones(182, dtype=bool),
        ),
    )
    proof = root / "old-proof.zip"
    with zipfile.ZipFile(proof, "w") as archive:
        archive.writestr("evidence.txt", b"independently verified ordering")
        archive.writestr("private.mov", b"never export entire proof archive")
    import hashlib

    mapping = {
        "schema_version": "0.1",
        "manifest_sha256": sha256_file(directory / "scene.json"),
        "point_cloud_sha256": sha256_file(root / "pointcloud.ply"),
        "grid_width": 13,
        "grid_height": 7,
        "point_stride": 1,
        "ordering": "frame_then_row_major",
        "ordering_verification": "raw_grid_comparison",
        "evidence_files": [
            {
                "source_path": str(proof),
                "archive_entry": "evidence.txt",
                "source_sha256": hashlib.sha256(b"independently verified ordering").hexdigest(),
                "reason": "independent ordering proof",
            }
        ],
        "pixel_transforms": [
            PixelTransform(i, 13, 7, 13, 7, (0, 0, 13, 7), "derived").to_dict() for i in (3, 17)
        ],
    }
    legacy = root / "legacy-workspace"
    legacy.mkdir()
    (legacy / "pixel-provenance.json").write_text(json.dumps(mapping))
    # This must not admit traversal beyond the experimental root.
    assert SceneReader(directory).read().source_root == root
    original_read = zipfile.ZipFile.read

    def bounded_read(archive, name, *args, **kwargs):
        if name == "evidence.txt":
            raise AssertionError("Proof entries must stream")
        return original_read(archive, name, *args, **kwargs)

    monkeypatch.setattr(zipfile.ZipFile, "read", bounded_read)
    server = ApplicationServer(ApplicationConfig(tmp_path / "portable-library", (root,)))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        choices = server.library.discover()
        record = server.library.import_scene(
            choices["scenes"][0]["choice_id"], "Legacy", choices["workspaces"][0]["choice_id"]
        )
        for pair in ((41, 49), (132, 140)):
            assert (
                request(
                    server,
                    prefix(record) + "/measurements",
                    "POST",
                    {
                        "reference_id": "width",
                        "quantity": "width",
                        "point_indices": pair,
                        "correspondence_state": "identified",
                    },
                )[0]
                == 200
            )
        version = calibrate(server, record)
        package = request(server, export(server, version)["download_url"])[1]
        with zipfile.ZipFile(io.BytesIO(package)) as archive:
            assert "scene/scene/scene.json" in archive.namelist()
            assert "scene/pointcloud.ply" in archive.namelist()
            assert archive.read("scene/scene/scene.json") == (directory / "scene.json").read_bytes()
            assert not any(n.endswith((".mov", "old-proof.zip")) for n in archive.namelist())
        root.rename(root.with_name("missing-original"))
        restored = reopen(server, package)
        assert restored[0] == 201
        metadata = request(server, prefix(restored[1]) + "/scene")[1]
        assert metadata["pixel_transforms"][0]["origin"] == "derived"
        assert request(server, prefix(restored[1]) + "/measurements/width")[0] == 200
        assert (
            request(server, prefix(restored[1]) + "/check-report")[1]["excluded_control_id"]
            == "width"
        )
    finally:
        server.shutdown()
        server.server_close()
        thread.join(2)


def test_package_transfer_cap_and_heavy_slot(version_app):
    server, source = version_app
    server.readiness.slot.acquire()
    try:
        assert (
            request(
                server,
                "/api/exports",
                "POST",
                {
                    "scene_id": source["scene_id"],
                    "version_id": source["default_version_id"],
                    "kind": "package",
                },
            )[0]
            == 422
        )
    finally:
        server.readiness.slot.release()
    connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=10)
    connection.request(
        "POST",
        "/api/packages/open",
        headers={
            "Origin": server.url.rstrip("/"),
            "X-TwinForge-Token": server.request_token,
            "Content-Type": "application/zip",
            "Content-Length": str(server.library.config.upload_limit + 1),
        },
    )
    response = connection.getresponse()
    assert response.status == 422
    response.read()
    connection.close()


def test_package_preserves_known_engine_provenance_only(version_app):
    server, source = version_app
    run = server.library.run(source["scene_id"], source["default_run_id"])
    root = Path(run["source_manifest"]).parent
    (root / "run.json").write_text('{"status":"complete","engine":"synthetic"}')
    (root / "unreferenced.json").write_text('{"private":"unrelated"}')
    package = request(server, export(server, source)["download_url"])[1]
    with zipfile.ZipFile(io.BytesIO(package)) as archive:
        assert archive.read("scene/run.json") == (root / "run.json").read_bytes()
        assert "scene/unreferenced.json" not in archive.namelist()


def test_package_rejects_changed_frozen_annotations_even_with_rehashed_manifest(version_app):
    import hashlib

    server, source = version_app
    version = calibrate(server, source)
    package = request(server, export(server, version)["download_url"])[1]
    output = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(package)) as old, zipfile.ZipFile(output, "w") as archive:
        descriptor = json.loads(old.read("package.json"))
        for info in old.infolist():
            if info.filename == "package.json":
                continue
            data = old.read(info)
            if info.filename == "workspace/width.json":
                value = json.loads(data)
                value["display_name"] = "Changed after freezing"
                data = json.dumps(value).encode()
                descriptor["files"][info.filename] = {
                    "sha256": hashlib.sha256(data).hexdigest(),
                    "bytes": len(data),
                }
            archive.writestr(info.filename, data)
        archive.writestr("package.json", json.dumps(descriptor))
    assert reopen(server, output.getvalue())[0] == 422


def test_package_metadata_is_bounded_before_loading(version_app, monkeypatch):
    from twinforge.application import exports

    server, source = version_app
    data = request(server, export(server, source)["download_url"])[1]
    monkeypatch.setattr(exports, "METADATA_LIMIT", 1024, raising=False)
    with pytest.raises(ValueError, match="metadata"):
        server.exports.open_package(io.BytesIO(data), len(data))


def test_restored_package_exposes_existing_source_derivation_archive(version_app):
    import shutil

    server, source = version_app
    version = calibrate(server, source)
    run = server.library.run(source["scene_id"], source["default_run_id"])
    workspace = server.library.workspace(
        source["scene_id"], version["default_run_id"], version["default_session_id"]
    )
    destination = Path(run["source_root"]) / "older-derived"
    shutil.copytree(workspace / "derived", destination)
    choice = next(c for c in server.library.discover()["scenes"] if c["label"] == "older-derived")
    linked = server.library.import_scene(choice["choice_id"], "Older derived source")
    assert request(server, prefix(linked) + "/archive")[1]["status"] == "not_imported"
    package = request(server, export(server, linked)["download_url"])[1]
    status, restored = reopen(server, package)
    assert status == 201
    assert request(server, prefix(restored) + "/archive")[1]["status"] == "available"


@pytest.mark.parametrize(
    "limit", ["transfer", "expanded", "member", "metadata", "descriptor", "count", "directory"]
)
def test_export_policy_rejects_unrestorable_package_before_ready(version_app, monkeypatch, limit):
    from twinforge.application import exports

    server, source = version_app
    baseline = export(server, source)
    data = request(server, baseline["download_url"])[1]
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        sizes = [item.file_size for item in archive.infolist()]
    if limit == "transfer":
        # Every payload fits, but the complete archive including ZIP headers does not.
        object.__setattr__(server.library.config, "upload_limit", sum(sizes))
    elif limit == "expanded":
        object.__setattr__(server.library.config, "upload_quota_bytes", sum(sizes) - 1)
    elif limit == "member":
        object.__setattr__(server.library.config, "upload_limit", max(sizes) - 1)
    else:
        constant = {
            "metadata": "METADATA_LIMIT",
            "descriptor": "DESCRIPTOR_LIMIT",
            "count": "MEMBER_LIMIT",
            "directory": "CENTRAL_DIRECTORY_LIMIT",
        }[limit]
        monkeypatch.setattr(exports, constant, 1, raising=False)
    status, result = request(
        server,
        "/api/exports",
        "POST",
        {
            "scene_id": source["scene_id"],
            "version_id": source["default_version_id"],
            "kind": "package",
        },
    )
    assert status == 200
    assert result["status"] == "unavailable"
    assert "limit" in result["message"].lower()
    assert "PLY" in result["message"]
    assert sorted(server.exports.root.iterdir()) == [server.exports.root / baseline["export_id"]]


def zip64_directory(data):
    """Promote a small fixture to a real ZIP64 end record without a huge payload."""
    end = len(data) - 22
    _, _, _, count, _, size, offset, _ = struct.unpack("<4s4H2LH", data[end:])
    record = struct.pack("<4sQ2H2L4Q", b"PK\x06\x06", 44, 45, 45, 0, 0, count, count, size, offset)
    locator = struct.pack("<4sLQL", b"PK\x06\x07", 0, end, 1)
    trailer = struct.pack("<4s4H2LH", b"PK\x05\x06", 0, 0, 65535, 65535, 0xFFFFFFFF, 0xFFFFFFFF, 0)
    return data[:end] + record + locator + trailer


@pytest.mark.parametrize("use_zip64", [False, True])
@pytest.mark.parametrize("limit", ["bytes", "count", "forged_count"])
def test_package_directory_rejected_before_eager_zip_parser(
    tmp_path, monkeypatch, limit, use_zip64
):
    from types import SimpleNamespace

    from twinforge.application import exports
    from twinforge.application.config import ApplicationConfig

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for index in range(3):
            archive.writestr(f"member-{index}", b"small")
    data = buffer.getvalue()
    if limit == "forged_count":
        data = data[:-14] + struct.pack("<2H", 1, 1) + data[-10:]
    if use_zip64:
        data = zip64_directory(data)
    monkeypatch.setattr(
        exports, "CENTRAL_DIRECTORY_LIMIT", 1 if limit == "bytes" else 4096, raising=False
    )
    monkeypatch.setattr(exports, "MEMBER_LIMIT", 2, raising=False)

    def eager_parser_must_not_run(*args, **kwargs):
        pytest.fail("Untrusted central directory reached the eager ZIP parser")

    monkeypatch.setattr(exports.zipfile, "ZipFile", eager_parser_must_not_run)
    store = exports.ExportStore(SimpleNamespace(root=tmp_path, config=ApplicationConfig(tmp_path)))
    with pytest.raises(ValueError, match="central directory|member count"):
        store.open_package(io.BytesIO(data), len(data))
    assert list(store.root.iterdir()) == []


def test_small_zip64_package_reopens(version_app):
    server, source = version_app
    data = request(server, export(server, source)["download_url"])[1]
    assert reopen(server, zip64_directory(data))[0] == 201


@pytest.mark.parametrize("late_final_byte", [False, True])
def test_package_body_deadline_releases_heavy_slot_and_library_lock(
    version_app, monkeypatch, late_final_byte
):
    import threading
    from email.message import Message
    from types import SimpleNamespace

    from twinforge.application import exports
    from twinforge.application.server import ApplicationHandler

    server, _ = version_app
    object.__setattr__(server.library.config, "transfer_timeout_seconds", 1.0)
    clock = SimpleNamespace(now=0.0)
    monkeypatch.setattr(exports, "time", SimpleNamespace(monotonic=lambda: clock.now))
    connection = SimpleNamespace(timeout=15.0, updates=[])

    def settimeout(value):
        connection.timeout = value
        connection.updates.append(value)

    connection.settimeout = settimeout
    connection.gettimeout = lambda: connection.timeout

    class SlowSocket(io.RawIOBase):
        reads = 0

        def readable(self):
            return True

        def readinto(self, target):
            self.reads += 1
            assert self.reads <= 3, "Buffered read escaped the overall package deadline"
            if late_final_byte:
                # A receive can return just after its timeout budget; completion must check too.
                clock.now += 1.1
            else:
                elapsed = min(0.4, connection.timeout)
                clock.now += elapsed
                if elapsed < 0.4:
                    raise TimeoutError("Simulated receive exceeded remaining deadline")
            target[0] = ord("x")
            return 1

    raw = SlowSocket()
    handler = ApplicationHandler.__new__(ApplicationHandler)
    handler.server = server
    handler.path = "/api/packages/open"
    handler.connection = connection
    handler.rfile = io.BufferedReader(raw)
    handler.headers = Message()
    handler.headers["Content-Type"] = "application/zip"
    handler.headers["Content-Length"] = "1" if late_final_byte else "100"
    handler._mutation_allowed = lambda: True
    responses = []
    handler._send = lambda status, *args: responses.append(status)
    handler._json = lambda status, *args: responses.append(status)
    handler.do_POST()
    assert responses == [422]
    assert connection.updates[0] == 1.0
    if not late_final_byte:
        assert connection.updates[1:3] == pytest.approx([0.6, 0.2])
        assert clock.now == pytest.approx(1.0)
    assert connection.timeout == 15.0
    assert not server.readiness.slot.busy()
    acquired = []

    def acquire_from_other_thread():
        held = server.library._lock.acquire(timeout=0.2)
        acquired.append(held)
        if held:
            server.library._lock.release()

    thread = threading.Thread(target=acquire_from_other_thread)
    thread.start()
    thread.join(1)
    assert acquired == [True]
    assert list(server.exports.root.iterdir()) == []
