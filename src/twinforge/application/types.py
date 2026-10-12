"""Versioned application identities, independent of legacy scene schemas."""

import re
from datetime import UTC, datetime
from typing import Any, Literal, TypedDict
from uuid import uuid4

SCHEMA_VERSION = "0.1"

JobState = Literal[
    "queued",
    "running",
    "validating_output",
    "ready",
    "cancelling",
    "cancelled",
    "failed",
    "interrupted",
]


class JobEvent(TypedDict):
    sequence: int
    timestamp: str
    stage: str
    message_code: str
    details: dict[str, Any]
    completed: int | None
    total: int | None


class JobRecord(TypedDict):
    schema_version: str
    job_id: str
    scene_id: str
    run_id: str
    media_id: str
    state: JobState
    config: dict[str, Any]
    config_sha256: str
    nonce: str
    events: list[JobEvent]


class ProcessingSettings(TypedDict):
    profile: Literal["standard", "quick_preview"]
    device: Literal["cpu", "cuda", "auto"]
    maximum_keyframes: int | None
    auto_budget: bool
    maximum_oom_retries: int
    color_policy: str
    candidate_interval_seconds: float
    label: str
    resource_note: str


class UploadReceipt(TypedDict):
    schema_version: str
    upload_id: str
    scene_id: str
    media_id: str
    client_name: str
    extension: str
    expected_bytes: int
    received_bytes: int
    state: str
    created_at: str
    updated_at: str
    destination_policy: str
    sha256: str | None


class InspectionRecord(TypedDict):
    container: str | None
    codec: str | None
    width: int
    height: int
    display_width: int
    display_height: int
    duration_seconds: float
    rotation_degrees: int
    decode_ready: bool
    preview: str
    preprocessing: dict[str, Any]
    browser_playback: str
    playback_fallback: str


class ManagedMediaRecord(TypedDict):
    schema_version: str
    scene_id: str
    media_id: str
    state: Literal["ready_to_start"]
    client_name: str
    expected_bytes: int
    sha256: str
    original_name: str
    preview_name: str
    inspection: InspectionRecord
    review_settings: ProcessingSettings
    created_at: str


def new_id(kind: str) -> str:
    return f"{kind}_{uuid4().hex}"


def validate_id(value: str, kind: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(rf"{kind}_[0-9a-f]{{32}}", value):
        raise ValueError(f"Invalid {kind} identity")
    return value


def timestamp() -> str:
    return datetime.now(UTC).isoformat()


def display_name(value: str) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > 500:
        raise ValueError("A scene name of 1–500 characters is required")
    return value.strip()
