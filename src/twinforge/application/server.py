"""Loopback library shell and immutable scene/run/session request contexts."""

from __future__ import annotations

import json
import mimetypes
import re
import secrets
import threading
import webbrowser
import zipfile
from collections import OrderedDict
from collections.abc import Callable, Hashable, Iterator
from contextlib import contextmanager
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from twinforge.application.config import ApplicationConfig
from twinforge.application.exports import ExportStore
from twinforge.application.jobs import JobManager
from twinforge.application.library import LibraryStore
from twinforge.application.readiness import ReadinessManager
from twinforge.application.uploads import UploadError, UploadStore
from twinforge.application.versions import create_version, validate_version
from twinforge.exceptions import TwinForgeError
from twinforge.measurements.errors import MESSAGES, MeasurementValidationError
from twinforge.scene.reader import SceneReader
from twinforge.viewer.server import STATIC_ROOT, _Handler
from twinforge.viewer.service import SceneService

SCOPED = re.compile(
    r"^/api/scenes/(scene_[0-9a-f]{32})/runs/(run_[0-9a-f]{32})"
    r"/sessions/(session_[0-9a-f]{32})(/.*)$"
)
WORKSPACE = re.compile(
    r"^/scenes/scene_[0-9a-f]{32}/runs/run_[0-9a-f]{32}"
    r"/sessions/session_[0-9a-f]{32}/?$"
)


class ServiceCache:
    """Bounded LRU; leased services cannot be evicted, including during writes."""

    def __init__(self, limit: int) -> None:
        self.limit = limit
        self.entries = OrderedDict()
        self._lock = threading.RLock()

    @contextmanager
    def acquire(self, key: Hashable, factory: Callable[[], SceneService]) -> Iterator[SceneService]:
        with self._lock:
            if key not in self.entries:
                if len(self.entries) >= self.limit:
                    idle = next((k for k, (_, count) in self.entries.items() if count == 0), None)
                    if idle is None:
                        raise ValueError("All viewer slots are busy; retry this request")
                    service, _ = self.entries.pop(idle)
                    service.close()
                self.entries[key] = [factory(), 0]
            entry = self.entries[key]
            entry[1] += 1
            self.entries.move_to_end(key)
        try:
            yield entry[0]
        finally:
            with self._lock:
                entry[1] -= 1

    def close(self) -> None:
        with self._lock:
            for service, count in self.entries.values():
                if count:
                    raise RuntimeError("Cannot close an active viewer cache")
                service.close()
            self.entries.clear()


class ApplicationServer(ThreadingHTTPServer):
    daemon_threads = False
    block_on_close = True

    def __init__(self, config: ApplicationConfig, port: int = 0):
        if type(port) is not int or not 0 <= port <= 65535:
            raise ValueError("port must be between 0 and 65535")
        self.library = LibraryStore(config)
        self.cache = ServiceCache(config.service_cache_size)
        self.uploads = UploadStore(self.library)
        self.exports = ExportStore(self.library)
        self.readiness = ReadinessManager(config)
        self.jobs = JobManager(self.library, self.readiness)
        self.request_token = secrets.token_urlsafe(32)
        self._slots = threading.BoundedSemaphore(config.request_limit)
        try:
            super().__init__(("127.0.0.1", port), ApplicationHandler)
        except Exception:
            self.jobs.close()
            self.readiness.close()
            self.library.close()
            raise

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.server_port}/"

    def process_request(self, request, client_address):
        if not self._slots.acquire(blocking=False):
            request.sendall(b"HTTP/1.0 503 Service Unavailable\r\nContent-Length: 0\r\n\r\n")
            self.shutdown_request(request)
            return
        request.settimeout(15)
        try:
            super().process_request(request, client_address)
        except Exception:
            self._slots.release()
            raise

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            self._slots.release()

    def server_close(self):
        super().server_close()
        self.cache.close()
        self.jobs.close()
        self.readiness.close()
        self.library.close()


class ApplicationHandler(_Handler):
    server: ApplicationServer

    @property
    def service(self):
        return self._request_service

    def _send(self, status, data, content_type):
        # Library source locations and evidence proof paths stay private to disk.
        if status >= 400:
            data = {
                403: b"Same-origin request token required",
                404: b"Resource unavailable",
                405: b"Unsupported operation",
                422: b"Invalid request or source unavailable",
            }.get(status, b"Request unavailable")
        super()._send(status, data, content_type)

    def _json(self, status, value):
        def public(item):
            if isinstance(item, dict):
                return {
                    key: public(val)
                    for key, val in item.items()
                    if key not in {"source_path", "source_manifest", "source_root", "thumbnail"}
                }
            if isinstance(item, (tuple, list)):
                return [public(val) for val in item]
            return item

        super()._json(status, public(value))

    def _action_error(self, error: UploadError) -> None:
        """Only fixed allowlisted codes/messages bypass generic private-path sanitation."""
        value = json.dumps({"error": {"code": error.code, "message": error.message}}).encode()
        super()._send(error.status, value, "application/json")

    def _measurement_error(self, error: MeasurementValidationError) -> None:
        # Read the fixed table again rather than serializing arbitrary exception attributes.
        value = json.dumps(
            {"error": {"code": error.code, "message": MESSAGES[error.code]}}
        ).encode()
        super()._send(422, value, "application/json")

    def _video(self, record):
        if record["source_kind"] != "managed_video":
            raise ValueError("Managed video required")
        media = self.server.library.media(record["scene_id"], record["media_id"])
        path = (
            self.server.library.media_path(record["scene_id"], media["media_id"])
            / media["original_name"]
        )
        if not path.resolve(strict=True).is_relative_to(self.server.library.root):
            raise ValueError("Invalid managed video path")
        size = path.stat().st_size
        if size != media["expected_bytes"]:
            raise ValueError("Managed video size changed")
        start, end = 0, size - 1
        byte_range = self.headers.get("Range")
        if byte_range:
            match = re.fullmatch(r"bytes=([0-9]+)-([0-9]*)", byte_range)
            if not match:
                raise ValueError("Unsupported video byte range")
            start = int(match[1])
            end = min(size - 1, int(match[2])) if match[2] else size - 1
            if start > end:
                raise ValueError("Invalid video byte range")
        self.send_response(206 if byte_range else 200)
        self.send_header(
            "Content-Type",
            {".mp4": "video/mp4", ".mov": "video/quicktime", ".mkv": "video/x-matroska"}[
                path.suffix
            ],
        )
        self.send_header("Content-Length", str(end - start + 1))
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Cache-Control", "no-store")
        if byte_range:
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        self.end_headers()
        with path.open("rb") as source:
            source.seek(start)
            remaining = end - start + 1
            while remaining:
                chunk = source.read(min(remaining, self.server.library.config.transfer_chunk_bytes))
                if not chunk:
                    break
                self.wfile.write(chunk)
                remaining -= len(chunk)

    def _mutation_allowed(self):
        if not self._allowed_request():
            return False
        if self.headers.get("Origin") is None or not secrets.compare_digest(
            self.headers.get("X-TwinForge-Token", ""), self.server.request_token
        ):
            self._send(403, b"Request token required", "text/plain")
            return False
        return True

    def _body(self):
        if self.headers.get("Content-Type") != "application/json":
            raise ValueError("JSON required")
        if self.headers.get("Transfer-Encoding"):
            raise ValueError("Transfer encoding is not supported")
        size = int(self.headers.get("Content-Length", "0"))
        if not 0 < size <= 16384:
            raise ValueError("Small-record request limit exceeded")
        value = json.loads(self.rfile.read(size))
        if not isinstance(value, dict):
            raise TypeError("An object is required")
        return value

    def _scoped(self, method):
        matched = SCOPED.fullmatch(self.path)
        if matched is None:
            return False
        scene_id, run_id, session_id, suffix = matched.groups()
        prefix = self.path[: -len(suffix)]
        original = self.path
        if method == "GET":
            run = self.server.library.run(scene_id, run_id)
            self.server.library.workspace(scene_id, run_id, session_id)
            code, message = self.server.library.source_availability(run)
            if code != "available":
                # Only fixed preflight guidance is public; arbitrary path-bearing
                # exceptions still go through the generic error sanitizer.
                value = json.dumps({"error": {"code": code, "message": message}}).encode()
                super()._send(422, value, "application/json")
                return True
        with self.server.library.request_context(
            scene_id, run_id, session_id, mutation=method != "GET"
        ) as (run, workspace):
            key = (scene_id, run_id, session_id, run["source_manifest"])
            with self.server.cache.acquire(
                key,
                lambda: SceneService(
                    SceneReader(Path(run["source_manifest"])).read(),
                    workspace,
                    prefix,
                    import_archive=bool(run.get("owned_package")),
                    prepared_preview=self.server.library.prepared_preview(run),
                ),
            ) as service:
                service.validate_provenance(force=method != "GET")
                self._request_service = service
                self.path = "/api" + suffix
                try:
                    record = self.server.library.get(scene_id)
                    version = next(v for v in record["versions"] if v["session_id"] == session_id)
                    validate_version(service, version)
                    if method != "GET" and suffix == "/calibration":
                        value = self._body()
                        self._calibration_result = create_version(
                            self.server.library, scene_id, run_id, session_id, service, value
                        )
                        return True
                    if method != "GET" and version.get("frozen"):
                        raise ValueError("Saved versions are frozen; edit the source session")
                    # Metadata has a public display name and no private proof paths.
                    if method == "GET" and suffix in ("/scene", "/derived/scene"):
                        if suffix == "/derived/scene" and service.derived is None:
                            self._send(404, b"No derived version", "text/plain")
                        else:
                            value = service.metadata(
                                service.derived if suffix.startswith("/derived") else None
                            )
                            value["name"] = self.server.library.get(scene_id)["name"]
                            value["version"] = version
                            value["default_version_id"] = record["default_version_id"]
                            self._json(200, value)
                    elif method == "GET":
                        super().do_GET()
                    else:
                        super().do_POST()
                finally:
                    self.path = original
                    del self._request_service
        return True

    def do_GET(self):
        if not self._allowed_request():
            return
        parsed = urlsplit(self.path)
        upload_page = parsed.path == "/api/uploads" and not parsed.fragment
        if (parsed.query and not upload_page) or parsed.fragment:
            self._send(404, b"Unknown resource", "text/plain")
            return
        try:
            if upload_page:
                query = parse_qs(parsed.query, strict_parsing=True)
                if set(query) - {"after"} or any(len(values) != 1 for values in query.values()):
                    raise ValueError("Invalid transfer page")
                self._json(200, self.server.uploads.list(after=query.get("after", [None])[0]))
            elif self.path == "/api/application":
                self._json(
                    200, {"schema_version": "0.1", "request_token": self.server.request_token}
                )
            elif self.path == "/api/library/scenes":
                self._json(200, self.server.library.list(self.server.jobs.scene_summaries()))
            elif self.path == "/api/storage":
                self._json(200, self.server.library.storage())
            elif re.fullmatch(r"/api/exports/export_[0-9a-f]{32}", self.path):
                path = self.server.exports.artifact(self.path.split("/")[3])
                self.send_response(200)
                self.send_header("Content-Type", "application/octet-stream")
                self.send_header("Content-Length", str(path.stat().st_size))
                self.send_header("Content-Disposition", f'attachment; filename="{path.name}"')
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                with path.open("rb") as source:
                    while chunk := source.read(self.server.library.config.transfer_chunk_bytes):
                        self.wfile.write(chunk)
            elif self.path == "/api/readiness":
                self._json(200, self.server.readiness.status())
            elif self.path == "/api/jobs":
                self._json(200, self.server.jobs.list())
            elif re.fullmatch(r"/api/jobs/job_[0-9a-f]{32}", self.path):
                self._json(200, self.server.jobs.get(self.path.split("/")[3]))
            elif re.fullmatch(r"/api/uploads/upload_[0-9a-f]{32}", self.path):
                self._json(200, self.server.uploads.get(self.path.split("/")[3]))
            elif self.path == "/api/library/imports":
                self._json(200, self.server.library.discover())
            elif self.path.startswith("/api/library/scenes/"):
                parts = self.path.split("/")
                record = self.server.library.get(parts[4])
                if len(parts) == 6 and parts[5] == "thumbnail":
                    # Thumbnail reads only the small image, never constructs a viewer preview.
                    image = self.server.library.thumbnail(record["scene_id"])
                    self._send(
                        200, image.read_bytes(), mimetypes.guess_type(image)[0] or "image/jpeg"
                    )
                elif len(parts) == 6 and parts[5] == "video":
                    self._video(record)
                elif len(parts) == 5:
                    self._json(200, self.server.library.summary(record))
                else:
                    self._send(404, b"Unknown resource", "text/plain")
            elif self._scoped("GET"):
                pass
            elif self.path in ("/", "/index.html") or WORKSPACE.fullmatch(self.path):
                filename = "index.html" if WORKSPACE.fullmatch(self.path) else "library.html"
                self._send(200, (STATIC_ROOT / filename).read_bytes(), "text/html")
            elif self.path.startswith("/api/"):
                self._send(404, b"Scoped scene identity required", "text/plain")
            else:
                super().do_GET()
        except UploadError as exc:
            self._action_error(exc)
        except (ConnectionResetError, BrokenPipeError):
            # A browser may close a video/download after headers were sent.
            self.close_connection = True
        except (OSError, ValueError, TypeError, KeyError, TwinForgeError):
            self._send(422, b"Source unavailable or invalid record", "text/plain")

    def do_POST(self):
        if not self._mutation_allowed():
            return
        try:
            if self.path == "/api/packages/open":
                lengths = self.headers.get_all("Content-Length", [])
                if (
                    self.headers.get("Transfer-Encoding")
                    or len(lengths) != 1
                    or not re.fullmatch(r"[0-9]+", lengths[0])
                    or self.headers.get("Content-Type") != "application/zip"
                ):
                    raise ValueError("Bounded ZIP transfer required")
                slot = self.server.readiness.slot
                slot.acquire()
                try:
                    previous_timeout = self.connection.gettimeout()
                    try:
                        with self.server.library._lock:
                            result = self.server.exports.open_package(
                                self.rfile,
                                int(lengths[0]),
                                set_read_timeout=self.connection.settimeout,
                            )
                    finally:
                        self.connection.settimeout(previous_timeout)
                finally:
                    slot.release()
                self._json(201, result)
                return
            scoped = SCOPED.fullmatch(self.path)
            if scoped and scoped[4] == "/calibration":
                # Match the job manager's lock order: heavy admission before library context.
                slot = self.server.readiness.slot
                slot.acquire()
                try:
                    self._scoped("POST")
                finally:
                    slot.release()
                self._json(201, self._calibration_result)
                return
            if self._scoped("POST"):
                return
            value = self._body()
            if self.path == "/api/exports":
                slot = self.server.readiness.slot
                slot.acquire()
                try:
                    result = self.server.exports.create(
                        value["scene_id"], value["version_id"], value["kind"]
                    )
                finally:
                    slot.release()
                self._json(200 if result["status"] == "unavailable" else 201, result)
            elif self.path == "/api/uploads":
                self._json(
                    201, self.server.uploads.create(value["client_name"], value["expected_bytes"])
                )
            elif re.fullmatch(r"/api/uploads/upload_[0-9a-f]{32}/complete", self.path):
                result = self.server.uploads.complete(
                    self.path.split("/")[3],
                    value["name"],
                    value.get("profile", "standard"),
                    value.get("device"),
                )
                self._json(200 if result["already_complete"] else 201, result)
            elif re.fullmatch(r"/api/uploads/upload_[0-9a-f]{32}/discard", self.path):
                self._json(200, self.server.uploads.discard(self.path.split("/")[3]))
            elif self.path == "/api/readiness/prepare":
                self._json(202, self.server.readiness.prepare())
            elif re.fullmatch(r"/api/library/scenes/scene_[0-9a-f]{32}/runs", self.path):
                if set(value) != {"idempotency_key"}:
                    raise ValueError("Only an idempotency key is accepted; save review first")
                self._json(
                    202, self.server.jobs.create(self.path.split("/")[4], value["idempotency_key"])
                )
            elif re.fullmatch(r"/api/jobs/job_[0-9a-f]{32}/(cancel|retry)", self.path):
                job_id, action = self.path.split("/")[3:5]
                self._json(
                    200,
                    self.server.jobs.cancel(job_id)
                    if action == "cancel"
                    else self.server.jobs.retry(job_id, value["idempotency_key"]),
                )
            elif re.fullmatch(r"/api/library/scenes/scene_[0-9a-f]{32}/media/review", self.path):
                try:
                    result = self.server.library.review_media(
                        self.path.split("/")[4],
                        value["name"],
                        value.get("profile", "standard"),
                        value.get("device"),
                    )
                except (ValueError, TypeError, KeyError):
                    raise UploadError("invalid_review") from None
                self._json(200, result)
            elif self.path == "/api/library/scenes":
                result = self.server.library.import_scene(
                    value["choice_id"], value["name"], value.get("workspace_choice_id")
                )
                self._json(201, result)
            elif re.fullmatch(r"/api/library/scenes/scene_[0-9a-f]{32}/locate", self.path):
                self._json(
                    200, self.server.library.locate(self.path.split("/")[4], value["choice_id"])
                )
            else:
                self._send(405, b"Unsupported operation", "text/plain")
        except UploadError as exc:
            self._action_error(exc)
        except (OSError, ValueError, TypeError, KeyError, TwinForgeError, zipfile.BadZipFile):
            self._send(422, b"Invalid import or source unavailable", "text/plain")

    def do_PUT(self):
        if not self._mutation_allowed():
            return
        try:
            if not re.fullmatch(r"/api/uploads/upload_[0-9a-f]{32}/content", self.path):
                self._send(405, b"Unsupported operation", "text/plain")
                return
            lengths = self.headers.get_all("Content-Length", [])
            if (
                self.headers.get_all("Transfer-Encoding")
                or len(lengths) != 1
                or not re.fullmatch(r"[0-9]+", lengths[0])
            ):
                raise UploadError("invalid_length")
            length = int(lengths[0])
            if length > self.server.library.config.upload_limit:
                raise UploadError("size_limit")
            self.connection.settimeout(min(15, self.server.library.config.transfer_timeout_seconds))
            receipt = self.server.uploads.transfer(
                self.path.split("/")[3],
                self.rfile,
                length,
                set_read_timeout=self.connection.settimeout,
            )
            self._json(200, receipt)
        except UploadError as exc:
            self._action_error(exc)
        except (OSError, ValueError, TypeError, KeyError):
            self._action_error(UploadError("transfer_failed"))

    def do_PATCH(self):
        if not self._mutation_allowed():
            return
        try:
            if not re.fullmatch(r"/api/library/scenes/scene_[0-9a-f]{32}", self.path):
                self._send(405, b"Unsupported operation", "text/plain")
                return
            self._json(200, self.server.library.patch(self.path.split("/")[4], self._body()))
        except (OSError, ValueError, TypeError, KeyError):
            self._send(422, b"Invalid scene change", "text/plain")


def serve_application(config: ApplicationConfig, port: int = 0, open_browser: bool = True) -> None:
    with ApplicationServer(config, port) as server:
        print(f"TwinForge Scenes: {server.url}", flush=True)
        if open_browser:
            try:
                webbrowser.open(server.url)
            except webbrowser.Error:
                pass
        print(
            f"Open this address in your browser: {server.url} · Press Ctrl+C to stop.", flush=True
        )
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
