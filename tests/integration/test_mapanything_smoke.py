"""Opt-in integration check; never downloads weights during the default test run."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from artifact_validation import validate_artifacts


def smoke_settings():
    """Keep real-model smoke runs small and explicit about their device."""
    try:
        maximum = int(os.getenv("TWINFORGE_SMOKE_MAX_KEYFRAMES", "4"))
    except ValueError as exc:
        raise ValueError("TWINFORGE_SMOKE_MAX_KEYFRAMES must be an integer at least 3") from exc
    if maximum < 3:
        raise ValueError("TWINFORGE_SMOKE_MAX_KEYFRAMES must be at least 3")
    device = os.getenv("TWINFORGE_SMOKE_DEVICE", "auto")
    if device not in {"auto", "cpu", "cuda"}:
        raise ValueError("TWINFORGE_SMOKE_DEVICE must be auto, cpu, or cuda")
    if os.getenv("TWINFORGE_REQUIRE_CUDA", "0") == "1":
        if device == "cpu":
            raise ValueError("TWINFORGE_REQUIRE_CUDA conflicts with TWINFORGE_SMOKE_DEVICE=cpu")
        device = "cuda"
    return maximum, device


def test_real_mapanything_video_reconstruction(tmp_path, monkeypatch):
    if os.getenv("TWINFORGE_RUN_MODEL_SMOKE") != "1":
        pytest.skip("set TWINFORGE_RUN_MODEL_SMOKE=1 to opt into the real model smoke test")
    video_value = os.getenv("TWINFORGE_SMOKE_VIDEO")
    if not video_value or not Path(video_value).is_file():
        pytest.skip("set TWINFORGE_SMOKE_VIDEO to a local test video")
    maximum, device = smoke_settings()
    monkeypatch.setenv("HF_HUB_OFFLINE", "1")
    monkeypatch.setenv("TRANSFORMERS_OFFLINE", "1")
    torch = pytest.importorskip("torch")
    hub = pytest.importorskip("huggingface_hub")
    hub_errors = pytest.importorskip("huggingface_hub.errors")
    checkpoint = os.getenv("TWINFORGE_CHECKPOINT", "facebook/map-anything-apache")
    revision = os.getenv(
        "TWINFORGE_CHECKPOINT_REVISION", "00f9c245bbcb60522d1ed7f9e9d88462c6e3f38a"
    )
    if device == "cuda" and not torch.cuda.is_available():
        pytest.skip("the configured model smoke test requires CUDA, which is unavailable")
    try:
        hub.snapshot_download(checkpoint, revision=revision, local_files_only=True)
    except (OSError, ValueError, hub_errors.LocalEntryNotFoundError) as exc:
        pytest.skip(
            f"checkpoint {checkpoint} is not available in the local Hugging Face cache: {exc}"
        )

    from twinforge.backends.mapanything import MapAnythingBackend
    from twinforge.config import BackendConfig, KeyframeConfig, OutputConfig, TwinForgeConfig
    from twinforge.reconstruction.orchestrator import ReconstructionOrchestrator

    config = TwinForgeConfig(
        backend=BackendConfig(
            device=device,
            checkpoint=checkpoint,
            checkpoint_revision=revision,
            maximum_keyframes=maximum,
        ),
        keyframes=KeyframeConfig(maximum_keyframes=maximum),
        output=OutputConfig(root=tmp_path / "output", preview_glb=True),
    )
    backend = MapAnythingBackend(checkpoint, checkpoint_revision=revision)
    output = ReconstructionOrchestrator(backend, config).run(Path(video_value), device=device)
    artifacts = validate_artifacts(output)
    assert config.keyframes.minimum_keyframes <= artifacts["selected_keyframes"] <= maximum
