"""Typed pipeline settings and validation."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from twinforge.ingest.color import ColorPolicyName


@dataclass(frozen=True)
class VideoConfig:
    candidate_interval_seconds: float = 0.5
    max_decode_width: int = 1920
    color_policy: ColorPolicyName = "auto"


@dataclass(frozen=True)
class KeyframeConfig:
    minimum_separation_seconds: float = 0.6
    maximum_keyframes: int | None = None
    minimum_keyframes: int = 3
    minimum_sharpness: float = 0.0015
    minimum_exposure_score: float = 0.30
    duplicate_hamming_distance: int = 5
    minimum_feature_overlap: float = 0.12
    maximum_feature_overlap: float = 0.98
    minimum_novelty: float = 0.015


@dataclass(frozen=True)
class BackendConfig:
    device: str = "auto"
    checkpoint: str = "facebook/map-anything-apache"
    checkpoint_revision: str = "00f9c245bbcb60522d1ed7f9e9d88462c6e3f38a"
    maximum_keyframes: int | None = None


@dataclass(frozen=True)
class MemoryConfig:
    """Conservative planning heuristics, not measured peak-memory requirements."""

    auto_budget: bool = True
    maximum_oom_retries: int = 3
    cuda_free_memory_fraction: float = 0.75
    cuda_bytes_per_frame: int = 192 * 1024**2
    fallback_maximum_keyframes: int = 32


@dataclass(frozen=True)
class OutputConfig:
    root: Path = Path("output")
    preview_glb: bool = True


@dataclass(frozen=True)
class TwinForgeConfig:
    video: VideoConfig = VideoConfig()
    keyframes: KeyframeConfig = KeyframeConfig()
    backend: BackendConfig = BackendConfig()
    output: OutputConfig = OutputConfig()
    memory: MemoryConfig = MemoryConfig()

    def validate(self) -> None:
        if self.video.color_policy not in ("auto", "sdr", "hlg", "pq"):
            raise ValueError("color_policy must be auto, sdr, hlg, or pq")
        if self.video.candidate_interval_seconds <= 0:
            raise ValueError("candidate_interval_seconds must be positive")
        if self.video.max_decode_width <= 0:
            raise ValueError("max_decode_width must be positive")
        if self.keyframes.maximum_keyframes is not None and self.keyframes.maximum_keyframes < 1:
            raise ValueError("maximum_keyframes must be at least 1")
        if self.keyframes.minimum_keyframes < 1:
            raise ValueError("minimum_keyframes must be at least 1")
        if (
            self.keyframes.maximum_keyframes is not None
            and self.keyframes.minimum_keyframes > self.keyframes.maximum_keyframes
        ):
            raise ValueError("minimum_keyframes cannot exceed maximum_keyframes")
        if (
            self.backend.maximum_keyframes is not None
            and self.backend.maximum_keyframes < self.keyframes.minimum_keyframes
        ):
            raise ValueError("backend maximum_keyframes cannot be below minimum_keyframes")
        if self.memory.maximum_oom_retries < 0:
            raise ValueError("maximum_oom_retries cannot be negative")
        if not 0 < self.memory.cuda_free_memory_fraction <= 1:
            raise ValueError("cuda_free_memory_fraction must be in (0, 1]")
        if self.memory.cuda_bytes_per_frame <= 0 or self.memory.fallback_maximum_keyframes < 1:
            raise ValueError("memory planning limits must be positive")
        if not 0 <= self.keyframes.minimum_exposure_score <= 1:
            raise ValueError("minimum_exposure_score must be between 0 and 1")
        if self.keyframes.duplicate_hamming_distance < 0:
            raise ValueError("duplicate_hamming_distance cannot be negative")
        if not 0 <= self.keyframes.minimum_feature_overlap <= 1:
            raise ValueError("minimum_feature_overlap must be between 0 and 1")
        if not 0 <= self.keyframes.maximum_feature_overlap <= 1:
            raise ValueError("maximum_feature_overlap must be between 0 and 1")
        if self.keyframes.minimum_feature_overlap > self.keyframes.maximum_feature_overlap:
            raise ValueError("minimum_feature_overlap cannot exceed maximum_feature_overlap")
        if not 0 <= self.keyframes.minimum_novelty <= 1:
            raise ValueError("minimum_novelty must be between 0 and 1")
