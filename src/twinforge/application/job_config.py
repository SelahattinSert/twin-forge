"""Allowlisted application profiles freeze every engine option before enqueueing."""

import hashlib
import json
from dataclasses import asdict
from pathlib import Path

from twinforge.application.readiness import profile_settings
from twinforge.config import (
    BackendConfig,
    KeyframeConfig,
    MemoryConfig,
    OutputConfig,
    TwinForgeConfig,
    VideoConfig,
)


def freeze_config(config, settings, output_root: Path) -> dict:
    selected = profile_settings(settings["profile"], settings["device"])
    engine = TwinForgeConfig(
        video=VideoConfig(
            color_policy=selected["color_policy"],
            candidate_interval_seconds=selected["candidate_interval_seconds"],
        ),
        keyframes=KeyframeConfig(maximum_keyframes=selected["maximum_keyframes"]),
        backend=BackendConfig(
            device=selected["device"],
            checkpoint=config.checkpoint,
            checkpoint_revision=config.checkpoint_revision,
            maximum_keyframes=selected["maximum_keyframes"],
        ),
        memory=MemoryConfig(
            auto_budget=selected["auto_budget"], maximum_oom_retries=selected["maximum_oom_retries"]
        ),
        output=OutputConfig(root=output_root),
    )
    engine.validate()
    value = asdict(engine)
    value["output"]["root"] = str(output_root)
    return value


def config_digest(value: dict) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, allow_nan=False).encode()).hexdigest()


def thaw_config(value: dict) -> TwinForgeConfig:
    config = TwinForgeConfig(
        video=VideoConfig(**value["video"]),
        keyframes=KeyframeConfig(**value["keyframes"]),
        backend=BackendConfig(**value["backend"]),
        memory=MemoryConfig(**value["memory"]),
        output=OutputConfig(**(value["output"] | {"root": Path(value["output"]["root"])})),
    )
    config.validate()
    return config
