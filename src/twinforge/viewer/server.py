"""Loopback-only, allowlisted, read-only HTTP scene viewer."""

from __future__ import annotations

import json
import logging
import mimetypes
import time
import webbrowser
from dataclasses import asdict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

from twinforge.measurements.consistency import evaluate_observations
from twinforge.measurements.errors import MeasurementValidationError
from twinforge.measurements.observations import measure_segment, resolve_image_pixel
from twinforge.scene.reader import SceneReader
from twinforge.scene.types import SceneArtifact
from twinforge.viewer.preview import build_frame_points, encode_bundle
from twinforge.viewer.service import SceneService, ViewerWorkspace  # noqa: F401

logger = logging.getLogger(__name__)
STATIC_ROOT = Path(__file__).parent / "static"
STATIC_FILES = {
    "/": "index.html",
    "/index.html": "index.html",
    "/app.js": "app.js",
    "/camera-path.js": "camera-path.js",
    "/view-state.js": "view-state.js",
    "/scene-exploration.js": "scene-exploration.js",
    "/scene-snapshot.js": "scene-snapshot.js",
    "/exploration-ui.js": "exploration-ui.js",
    "/source-preview.js": "source-preview.js",
    "/hover-index.js": "hover-index.js",
    "/camera-markers.js": "camera-markers.js",
    "/camera-icon.svg": "camera-icon.svg",
    "/scene-client.js": "scene-client.js",
    "/version-actions.js": "version-actions.js",
    "/library.js": "library.js",
    "/upload-review.js": "upload-review.js",
    "/activity.js": "activity.js",
    "/library.css": "library.css",
    "/measurement-state.js": "measurement-state.js",
    "/workspace-ui.js": "workspace-ui.js",
    "/image-selection.js": "image-selection.js",
    "/image-editor.js": "image-editor.js",
    "/result-summary.js": "result-summary.js",
    "/styles.css": "styles.css",
    "/vendor/three.module.min.js": "vendor/three.module.min.js",
    "/vendor/three.core.min.js": "vendor/three.core.min.js",
    "/vendor/OrbitControls.js": "vendor/OrbitControls.js",
    "/vendor/LICENSE": "vendor/LICENSE",
    "/vendor/manrope-latin-wght-normal.woff2": "vendor/manrope-latin-wght-normal.woff2",
    "/vendor/MANROPE-LICENSE": "vendor/MANROPE-LICENSE",
}


class ViewerServer(SceneService, ThreadingHTTPServer):
    """Legacy single-scene HTTP server; public service attributes remain available."""

    daemon_threads = True

    def __init__(self, scene: SceneArtifact, workspace: Path, port: int = 0):
        if type(port) is not int or not 0 <= port <= 65535:
            raise ValueError("port must be between 0 and 65535")
        SceneService.__init__(self, scene, workspace)
        ThreadingHTTPServer.__init__(self, ("127.0.0.1", port), _Handler)

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.server_port}/"


class _Handler(BaseHTTPRequestHandler):
    server: ViewerServer

    @property
    def service(self):
        return self.server

    def log_message(self, format: str, *args) -> None:
        logger.debug(format, *args)

    def _allowed_request(self) -> bool:
        hosts = {f"127.0.0.1:{self.server.server_port}", f"localhost:{self.server.server_port}"}
        if self.headers.get("Host") not in hosts:
            self._send(403, b"Loopback Host required", "text/plain")
            return False
        origin = self.headers.get("Origin")
        if origin is not None and origin not in {f"http://{host}" for host in hosts}:
            self._send(403, b"Cross-origin requests are forbidden", "text/plain")
            return False
        return True

    def _send(self, status: int, data: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; script-src 'self' 'unsafe-inline'; "
            "style-src 'self'; img-src 'self' blob:; connect-src 'self'; "
            "object-src 'none'; base-uri 'none'; frame-ancestors 'none'",
        )
        self.end_headers()
        if self.command != "HEAD":
            try:
                self.wfile.write(data)
            except (BrokenPipeError, ConnectionResetError):
                pass

    def do_GET(self) -> None:
        if not self._allowed_request():
            return
        parsed = urlsplit(self.path)
        path = parsed.path
        if parsed.query or parsed.fragment:
            self._send(404, b"Unknown resource", "text/plain")
            return
        try:
            if path == "/api/scene":
                payload = json.dumps(self.service.metadata(), allow_nan=False).encode()
                self._send(200, payload, "application/json")
                return
            if path == "/api/archive":
                self._json(200, self.service.archive)
                return
            if path == "/api/calibration":
                self._json(
                    200,
                    json.loads(self.service.workspace.write_path("calibration.json").read_text()),
                )
                return
            if path == "/api/check-report":
                self._json(
                    200,
                    json.loads(self.service.workspace.write_path("check-report.json").read_text()),
                )
                return
            if path == "/api/derived/scene" and self.service.derived is not None:
                self._json(200, self.service.metadata(self.service.derived))
                return
            if path == "/api/derived/preview" and self.service.derived is not None:
                self._send(200, self.service.derived_preview_bytes, "application/octet-stream")
                return
            derived_parts = path.split("/")
            if (
                len(derived_parts) == 6
                and derived_parts[1:4] == ["api", "derived", "frames"]
                and derived_parts[4].isdigit()
                and derived_parts[5] == "points"
                and self.service.derived is not None
            ):
                bundle = build_frame_points(self.service.derived, int(derived_parts[4]))
                self._send(200, encode_bundle(bundle), "application/octet-stream")
                return
            if path == "/api/measurements":
                self._json(200, self.service.measurements.list_ids())
                return
            if path == "/api/visibility":
                self._json(200, self.service.measurements.load_visibility())
                return
            if path.startswith("/api/measurements/"):
                record = self.service.measurements.load(path.removeprefix("/api/measurements/"))
                self._json(
                    200,
                    {
                        "record": record.to_dict(),
                        "evidence": asdict(evaluate_observations(record.observations)),
                    },
                )
                return
            if path == "/api/preview":
                self._send(200, self.service.preview_bytes, "application/octet-stream")
                return
            parts = path.split("/")
            if len(parts) == 5 and parts[1:3] == ["api", "frames"] and parts[3].isdigit():
                frame_id = int(parts[3])
                frame = self.service.frames.get(frame_id)
                if frame is not None and parts[4] in {"image", "thumbnail"}:
                    image = frame.image_path.resolve()
                    if not image.is_relative_to(self.service.scene.source_root):
                        self._send(403, b"Image escapes source root", "text/plain")
                        return
                    if parts[4] == "thumbnail":
                        self._send(200, self.service.thumbnails.get(image), "image/jpeg")
                        return
                    self._send(
                        200, image.read_bytes(), mimetypes.guess_type(image)[0] or "image/jpeg"
                    )
                    return
                if frame is not None and parts[4] == "points":
                    try:
                        bundle = build_frame_points(self.service.scene, frame_id)
                    except ValueError as exc:
                        self._send(422, str(exc).encode(), "text/plain")
                        return
                    self._send(200, encode_bundle(bundle), "application/octet-stream")
                    return
            if path in STATIC_FILES:
                static = (STATIC_ROOT / STATIC_FILES[path]).resolve()
                if not static.is_relative_to(STATIC_ROOT.resolve()):
                    self._send(403, b"Invalid static resource", "text/plain")
                    return
                self._send(
                    200, static.read_bytes(), mimetypes.guess_type(static)[0] or "text/plain"
                )
                return
            self._send(404, b"Unknown resource", "text/plain")
        except (ValueError, TypeError, KeyError) as exc:
            self._send(422, str(exc).encode(), "text/plain")
        except OSError:
            self._send(404, b"Resource unavailable", "text/plain")

    def do_HEAD(self) -> None:
        self.do_GET()

    def do_POST(self) -> None:
        if self.path not in ("/api/measurements", "/api/visibility", "/api/calibration"):
            self._send(405, b"Unknown workspace write route", "text/plain")
            return
        if not self._allowed_request():
            return
        if self.headers.get("Origin") is None:
            self._send(403, b"Same-origin workspace writes required", "text/plain")
            return
        if self.headers.get("Content-Type") != "application/json":
            self._send(415, b"JSON content required", "text/plain")
            return
        try:
            size = int(self.headers.get("Content-Length", "0"))
            if not 0 < size <= 16384:
                raise ValueError("Workspace request exceeds the small-record limit")
            value = json.loads(self.rfile.read(size))
            if self.path == "/api/calibration":
                self._json(200, self.service.calibrate(value))
                return
            if self.path == "/api/visibility":
                self.service.measurements.save_visibility(value)
                self._json(200, self.service.measurements.load_visibility())
                return
            reference_id = value["reference_id"]
            if value.get("action") == "rename":
                record = self.service.measurements.rename(reference_id, value["display_name"])
                self._json(
                    200,
                    {
                        "record": record.to_dict(),
                        "evidence": asdict(evaluate_observations(record.observations)),
                    },
                )
                return
            indices = value.get("point_indices")
            origin = "3d_pick"
            source_pixels = value.get("source_pixels")
            if source_pixels is not None:
                indices = [
                    resolve_image_pixel(self.service.scene, value["frame_id"], pixel)
                    for pixel in source_pixels
                ]
                origin = "image_pick"
            observation = measure_segment(
                self.service.scene,
                indices,
                reference_id=reference_id,
                selection_origin=origin,
                correspondence_state=value.get("correspondence_state", "unreviewed"),
                source_pixels=source_pixels,
            )
            record = self.service.measurements.append(
                observation,
                value["quantity"],
                display_name=value.get("display_name"),
                submission_key=value.get("idempotency_key"),
                correction_id=value.get("correction_id"),
                expected_revision=value.get("expected_revision"),
                correction_reason=value.get("correction_reason"),
            )
            self._json(
                200,
                {
                    "record": record.to_dict(),
                    "evidence": asdict(evaluate_observations(record.observations)),
                },
            )
        except MeasurementValidationError as exc:
            self._measurement_error(exc)
        except (ValueError, TypeError, KeyError, OSError) as exc:
            self._send(422, str(exc).encode(), "text/plain")

    def _measurement_error(self, error: MeasurementValidationError) -> None:
        self._send(error.status, error.message.encode(), "text/plain")

    def _json(self, status: int, value: object) -> None:
        self._send(status, json.dumps(value, allow_nan=False).encode(), "application/json")

    def _unsupported_write(self) -> None:
        self._send(405, b"Unsupported write method", "text/plain")

    do_PUT = _unsupported_write
    do_DELETE = _unsupported_write
    do_PATCH = _unsupported_write


def serve_scene(
    path: Path, workspace: Path | None = None, port: int = 0, open_browser: bool = True
) -> None:
    started = time.monotonic()
    scene = SceneReader(path).read()
    workspace = workspace or Path("output/phase1/workspaces") / scene.manifest_sha256[:16]
    with ViewerServer(scene, workspace, port) as server:
        print(f"TwinForge viewer: {server.url}", flush=True)
        print(
            f"{scene.point_count:,} original points; {server.preview.point_count:,} preview points; "
            f"prepared in {time.monotonic() - started:.3f}s. Press Ctrl+C to stop.",
            flush=True,
        )
        if open_browser:
            try:
                if not webbrowser.open(server.url):
                    print(f"Open this address in your browser: {server.url}", flush=True)
            except webbrowser.Error:
                print(f"Open this address in your browser: {server.url}", flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
