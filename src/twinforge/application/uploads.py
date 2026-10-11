"""Managed byte transfer with receipts, reservations, and explicit inspection."""

from __future__ import annotations

import errno
import hashlib
import heapq
import os
import re
import shutil
import threading
import time
from collections.abc import Callable
from contextlib import contextmanager
from pathlib import Path
from typing import BinaryIO

from twinforge.application.library import LibraryStore, atomic_json
from twinforge.application.types import UploadReceipt, display_name, new_id, timestamp, validate_id

ERRORS = {
    "invalid_extension": (422, "Choose one .mp4, .mov, or .mkv video file."),
    "invalid_size": (422, "Choose a nonempty file with a valid byte size."),
    "size_limit": (413, "The video exceeds this application's upload size limit."),
    "upload_quota": (
        409,
        "Pending transfers exceed the local transfer quota. Finish or discard an incomplete transfer.",
    ),
    "insufficient_storage": (
        507,
        "There is not enough free disk space for the video and storage reserve. Free space and restart the transfer.",
    ),
    "invalid_length": (
        422,
        "A single Content-Length is required. Chunked transfers are not supported.",
    ),
    "length_mismatch": (
        422,
        "The transfer byte length does not match the declared file size. Restart the transfer.",
    ),
    "incomplete_transfer": (
        422,
        "The transfer is incomplete. Restart Add video with the original file.",
    ),
    "transfer_failed": (
        422,
        "The transfer was interrupted. Restart Add video with the original file.",
    ),
    "invalid_video": (
        422,
        "The file does not contain a valid local video stream. Choose the original video file.",
    ),
    "missing_decoder": (
        422,
        "FFmpeg and ffprobe are required to inspect video. Install FFmpeg, then restart the transfer.",
    ),
    "decode_failed": (
        422,
        "FFmpeg could not decode a preview. Check the codec and HDR zscale/tonemap support, or choose an SDR original.",
    ),
    "inspection_failed": (
        422,
        "Video inspection exceeded its limits or could not complete. Try a shorter supported local video.",
    ),
    "inspection_limit": (
        422,
        "The video's duration or dimensions exceed the configured inspection policy. Choose a smaller video.",
    ),
    "invalid_review": (422, "Review a scene name and a supported processing profile/device."),
    "receipt_unavailable": (404, "The transfer receipt is unavailable. Restart Add video."),
    "setup_busy": (409, "Model preparation is already running."),
    "model_not_prepared": (
        422,
        "Prepare the cached checkpoint and Torch Hub source before processing.",
    ),
}


class UploadError(ValueError):
    def __init__(self, code: str):
        self.code = code
        self.status, self.message = ERRORS[code]
        super().__init__(f"{code}: {self.message}")


class UploadStore:
    def __init__(self, library: LibraryStore):
        self.library = library
        self.config = library.config
        self.root = library.root / "uploads"
        self.root.mkdir(exist_ok=True)
        self._lock = threading.RLock()
        self._active: set[str] = set()
        self._reserved: dict[str, int] = {}
        for path in self.root.glob("upload_*/receipt.json"):
            try:
                receipt = self.get(path.parent.name)
                if receipt["state"] in ("transferring", "inspecting"):
                    self._fail(receipt, "incomplete_transfer")
                elif receipt["state"] in ("created", "transferred"):
                    self._reserved[receipt["upload_id"]] = receipt["expected_bytes"]
            except (OSError, ValueError, KeyError):
                continue  # Isolate malformed receipts; never register media from them.

    def _directory(self, upload_id: str) -> Path:
        path = self.root / validate_id(upload_id, "upload")
        if path.is_symlink() or not path.resolve().is_relative_to(self.root.resolve()):
            raise UploadError("receipt_unavailable")
        return path

    def get(self, upload_id: str) -> UploadReceipt:
        try:
            value = self.library._read(self._directory(upload_id) / "receipt.json")
            if (
                value.get("upload_id") != upload_id
                or value.get("state")
                not in {
                    "created",
                    "transferring",
                    "transferred",
                    "inspecting",
                    "complete",
                    "failed",
                    "discarded",
                }
                or type(value.get("expected_bytes")) is not int
                or not 0 < value["expected_bytes"] <= self.config.upload_limit
                or value.get("extension") not in {".mp4", ".mov", ".mkv"}
            ):
                raise ValueError("Invalid receipt")
            return value
        except (OSError, ValueError, KeyError):
            raise UploadError("receipt_unavailable") from None

    def _save(self, receipt: dict) -> None:
        receipt["updated_at"] = timestamp()
        atomic_json(self._directory(receipt["upload_id"]) / "receipt.json", receipt)

    def list(self, *, limit: int = 50, after: str | None = None) -> dict:
        """Page through owned receipts with bounded reads and public recovery metadata."""
        if type(limit) is not int or not 1 <= limit <= 50:
            raise UploadError("receipt_unavailable")
        if after is not None:
            validate_id(after, "upload")
        candidates = heapq.nsmallest(
            limit + 1,
            (
                path.parent.name
                for path in self.root.glob("upload_*/receipt.json")
                if re.fullmatch(r"upload_[0-9a-f]{32}", path.parent.name)
                and (after is None or path.parent.name > after)
            ),
        )
        uploads = []
        for upload_id in candidates[:limit]:
            try:
                receipt = self.get(upload_id)
            except UploadError:
                continue
            if receipt["state"] in {"complete", "discarded"}:
                continue
            item = {
                key: receipt[key]
                for key in (
                    "upload_id",
                    "client_name",
                    "state",
                    "expected_bytes",
                    "received_bytes",
                    "created_at",
                    "updated_at",
                )
                if key in receipt
            }
            if receipt.get("error_code") in ERRORS:
                code = receipt["error_code"]
                item["error"] = {"code": code, "message": ERRORS[code][1]}
            uploads.append(item)
        return {
            "uploads": uploads,
            "next_cursor": candidates[limit - 1] if len(candidates) > limit else None,
        }

    def _fail(self, receipt: dict, code: str) -> None:
        receipt.update(state="failed", error_code=code)
        self._save(receipt)
        with self._lock:
            self._reserved.pop(receipt["upload_id"], None)

    def create(self, client_name: str, expected_bytes: int) -> UploadReceipt:
        if (
            not isinstance(client_name, str)
            or not client_name.strip()
            or len(client_name) > 500
            or "\0" in client_name
        ):
            raise UploadError("invalid_extension")
        extension = Path(client_name).suffix.lower()
        if extension not in (".mp4", ".mov", ".mkv"):
            raise UploadError("invalid_extension")
        if type(expected_bytes) is not int or expected_bytes < 1:
            raise UploadError("invalid_size")
        if expected_bytes > self.config.upload_limit:
            raise UploadError("size_limit")
        with self._lock:
            reserved = sum(self._reserved.values())
            if (
                reserved + expected_bytes > self.config.upload_quota_bytes
                or len(self._reserved) >= self.config.pending_upload_limit
            ):
                raise UploadError("upload_quota")
            if (
                shutil.disk_usage(self.root).free
                < reserved + expected_bytes + self.config.disk_reserve_bytes
            ):
                raise UploadError("insufficient_storage")
            upload_id = new_id("upload")
            receipt = {
                "schema_version": "0.1",
                "upload_id": upload_id,
                "scene_id": new_id("scene"),
                "media_id": new_id("media"),
                "client_name": client_name,
                "extension": extension,
                "expected_bytes": expected_bytes,
                "received_bytes": 0,
                "state": "created",
                "created_at": timestamp(),
                "destination_policy": "Byte-identical managed local copy in the configured library.",
                "sha256": None,
            }
            try:
                self._save(receipt)
            except OSError:
                raise UploadError("insufficient_storage") from None
            self._reserved[upload_id] = expected_bytes
            return receipt.copy()

    @contextmanager
    def _operation(self, upload_id: str):
        with self._lock:
            if upload_id in self._active:
                raise UploadError("incomplete_transfer")
            self._active.add(upload_id)
        try:
            yield
        finally:
            with self._lock:
                self._active.remove(upload_id)

    def transfer(
        self,
        upload_id: str,
        stream: BinaryIO,
        length: int,
        *,
        set_read_timeout: Callable[[float], None] | None = None,
    ) -> UploadReceipt:
        with self._operation(upload_id):
            receipt = self.get(upload_id)
            if length > self.config.upload_limit:
                raise UploadError("size_limit")
            if length != receipt["expected_bytes"]:
                raise UploadError("length_mismatch")
            if receipt["state"] != "created":
                raise UploadError("incomplete_transfer")
            receipt["state"] = "transferring"
            self._save(receipt)
            digest = hashlib.sha256()
            remaining = length
            deadline = time.monotonic() + self.config.transfer_timeout_seconds
            try:
                with (self._directory(upload_id) / "original.partial").open("xb") as target:
                    while remaining:
                        read_seconds = deadline - time.monotonic()
                        if read_seconds <= 0:
                            raise UploadError("transfer_failed")
                        if set_read_timeout is not None:
                            set_read_timeout(min(15, read_seconds))
                        # Buffered HTTP read(n) may perform many receives while filling n.
                        # read1(n) performs at most one, so each receive gets a new deadline.
                        read = getattr(stream, "read1", stream.read)
                        chunk = read(min(remaining, self.config.transfer_chunk_bytes))
                        if time.monotonic() >= deadline:
                            raise UploadError("transfer_failed")
                        if not chunk:
                            raise UploadError("incomplete_transfer")
                        if len(chunk) > remaining:
                            raise UploadError("length_mismatch")
                        if (
                            shutil.disk_usage(self.root).free
                            < len(chunk) + self.config.disk_reserve_bytes
                        ):
                            raise UploadError("insufficient_storage")
                        target.write(chunk)
                        digest.update(chunk)
                        remaining -= len(chunk)
                        receipt["received_bytes"] += len(chunk)
                    target.flush()
                    os.fsync(target.fileno())
                receipt.update(state="transferred", sha256=digest.hexdigest())
                self._save(receipt)
                return receipt.copy()
            except UploadError as exc:
                self._fail(receipt, exc.code)
                raise
            except OSError as exc:
                code = (
                    "insufficient_storage"
                    if exc.errno in (errno.ENOSPC, errno.EDQUOT)
                    else "transfer_failed"
                )
                self._fail(receipt, code)
                raise UploadError(code) from None

    def complete(
        self, upload_id: str, name: str, profile: str = "standard", device: str | None = None
    ) -> dict:
        from twinforge.application.inspection import inspect_video
        from twinforge.application.readiness import profile_settings

        try:
            name = display_name(name)
            settings = profile_settings(profile, device)
        except (ValueError, TypeError):
            raise UploadError("invalid_review") from None
        with self._operation(upload_id):
            receipt = self.get(upload_id)
            if receipt["state"] == "complete":
                return {
                    "scene": self.library.summary(self.library.get(receipt["scene_id"])),
                    "already_complete": True,
                }
            if (
                receipt["state"] != "transferred"
                or receipt["received_bytes"] != receipt["expected_bytes"]
            ):
                raise UploadError("incomplete_transfer")
            directory = self._directory(upload_id)
            original = directory / ("original" + receipt["extension"])
            partial = directory / "original.partial"
            try:
                if partial.stat().st_size != receipt["expected_bytes"]:
                    raise UploadError("incomplete_transfer")
                from twinforge.scene.reader import sha256_file

                if sha256_file(partial) != receipt["sha256"]:
                    raise UploadError("incomplete_transfer")
                os.replace(partial, original)
                receipt["state"] = "inspecting"
                self._save(receipt)
                inspection = inspect_video(original, directory, self.config)
                scene = self.library.register_media(receipt, original, inspection, name, settings)
                receipt["state"] = "complete"
                self._save(receipt)
                with self._lock:
                    self._reserved.pop(upload_id, None)
                return {"scene": scene, "already_complete": False}
            except UploadError as exc:
                self._fail(receipt, exc.code)
                raise
            except OSError:
                self._fail(receipt, "insufficient_storage")
                raise UploadError("insufficient_storage") from None

    def discard(self, upload_id: str) -> dict:
        """Explicitly remove only an incomplete upload's owned original/preview candidates."""
        with self._operation(upload_id):
            receipt = self.get(upload_id)
            if receipt["state"] == "complete":
                raise UploadError("incomplete_transfer")
            directory = self._directory(upload_id)
            for name in (
                "original.partial",
                "original" + receipt["extension"],
                "candidate_000001.jpg",
            ):
                path = directory / name
                if path.is_file() and not path.is_symlink():
                    path.unlink()
            receipt["state"] = "discarded"
            self._save(receipt)
            with self._lock:
                self._reserved.pop(upload_id, None)
            return receipt
