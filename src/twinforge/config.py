"""Typed pipeline settings and validation."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class VideoConfig:
    candidate_interval_seconds: float = 0.5
    max_decode_width: int = 1920


@dataclass(frozen=True)
class KeyframeConfig:
    minimum_separation_seconds: float = 0.6
    maximum_keyframes: int = 80
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
    maximum_keyframes: int = 80


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

    def validate(self) -> None:
        if self.video.candidate_interval_seconds <= 0:
            raise ValueError("candidate_interval_seconds must be positive")
        if self.video.max_decode_width <= 0:
            raise ValueError("max_decode_width must be positive")
        if self.keyframes.maximum_keyframes < 1:
            raise ValueError("maximum_keyframes must be at least 1")
        if self.keyframes.minimum_keyframes < 1:
            raise ValueError("minimum_keyframes must be at least 1")
        if self.keyframes.minimum_keyframes > self.keyframes.maximum_keyframes:
            raise ValueError("minimum_keyframes cannot exceed maximum_keyframes")
        if self.backend.maximum_keyframes < 1:
            raise ValueError("backend maximum_keyframes must be at least 1")
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
