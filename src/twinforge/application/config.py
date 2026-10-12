"""Explicit local application roots and finite resource policy."""

import math
import os
import re
from dataclasses import dataclass, field
from pathlib import Path


def _hf_home() -> Path:
    return Path(os.environ.get("HF_HOME", ".model-cache/huggingface")).expanduser().resolve()


def _torch_home() -> Path:
    return Path(os.environ.get("TORCH_HOME", ".model-cache/torch")).expanduser().resolve()


@dataclass(frozen=True)
class ApplicationConfig:
    library: Path = Path("output/phase2/library")
    import_roots: tuple[Path, ...] = ()
    service_cache_size: int = 2
    request_limit: int = 8
    discovery_limit: int = 1000
    upload_limit: int = 8 * 1024**3
    upload_quota_bytes: int = 16 * 1024**3
    pending_upload_limit: int = 8
    disk_reserve_bytes: int = 512 * 1024**2
    transfer_chunk_bytes: int = 1024**2
    transfer_timeout_seconds: float = 300
    probe_timeout_seconds: float = 20
    decode_timeout_seconds: float = 45
    subprocess_output_bytes: int = 1024**2
    maximum_video_dimension: int = 8192
    maximum_video_pixels: int = 40_000_000
    maximum_video_seconds: float = 4 * 60 * 60
    preview_width: int = 960
    hf_home: Path = field(default_factory=_hf_home)
    torch_home: Path = field(default_factory=_torch_home)
    hf_hub_cache: Path | None = None
    checkpoint: str = "facebook/map-anything-apache"
    checkpoint_revision: str = "00f9c245bbcb60522d1ed7f9e9d88462c6e3f38a"
    setup_timeout_seconds: float = 3600

    @property
    def hf_cache(self) -> Path:
        return self.hf_hub_cache or self.hf_home / "hub"

    def worker_environment(self, *, offline: bool = True) -> dict[str, str]:
        """Shared setup/processing environment; Torch Hub also needs worker network denial."""
        return dict(os.environ) | {
            "HF_HOME": str(self.hf_home),
            "HF_HUB_CACHE": str(self.hf_cache),
            "HUGGINGFACE_HUB_CACHE": str(self.hf_cache),
            "TORCH_HOME": str(self.torch_home),
            "HF_HUB_OFFLINE": "1" if offline else "0",
            "TRANSFORMERS_OFFLINE": "1" if offline else "0",
            "HF_HUB_DISABLE_TELEMETRY": "1",
        }

    def __post_init__(self):
        if self.hf_hub_cache is None:
            explicit = os.environ.get("HF_HUB_CACHE") or os.environ.get("HUGGINGFACE_HUB_CACHE")
            if explicit:
                object.__setattr__(self, "hf_hub_cache", Path(explicit).expanduser().resolve())
        for value in (
            self.service_cache_size,
            self.request_limit,
            self.discovery_limit,
            self.upload_limit,
            self.upload_quota_bytes,
            self.pending_upload_limit,
            self.disk_reserve_bytes,
            self.transfer_chunk_bytes,
            self.subprocess_output_bytes,
            self.maximum_video_dimension,
            self.maximum_video_pixels,
            self.preview_width,
        ):
            if type(value) is not int or value < 1:
                raise ValueError("Application resource limits must be positive integers")
        for value in (
            self.transfer_timeout_seconds,
            self.probe_timeout_seconds,
            self.decode_timeout_seconds,
            self.maximum_video_seconds,
            self.setup_timeout_seconds,
        ):
            if isinstance(value, bool) or not math.isfinite(value) or value <= 0:
                raise ValueError("Application time limits must be finite and positive")
        if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", self.checkpoint):
            raise ValueError("A repository checkpoint identity is required")
        if not re.fullmatch(r"[0-9a-f]{40}", self.checkpoint_revision):
            raise ValueError("An immutable checkpoint revision is required")
