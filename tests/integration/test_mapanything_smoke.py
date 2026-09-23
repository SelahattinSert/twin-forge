"""Opt-in integration check; never downloads weights during the default test run."""

from __future__ import annotations

import os
from pathlib import Path

import pytest


def test_real_mapanything_video_reconstruction(tmp_path):
    if os.getenv("TWINFORGE_RUN_MODEL_SMOKE") != "1":
        pytest.skip("set TWINFORGE_RUN_MODEL_SMOKE=1 to opt into the real model smoke test")
    video_value = os.getenv("TWINFORGE_SMOKE_VIDEO")
    if not video_value or not Path(video_value).is_file():
        pytest.skip("set TWINFORGE_SMOKE_VIDEO to a local test video")
    torch = pytest.importorskip("torch")
    hub = pytest.importorskip("huggingface_hub")
    hub_errors = pytest.importorskip("huggingface_hub.errors")
    checkpoint = os.getenv("TWINFORGE_CHECKPOINT", "facebook/map-anything-apache")
    revision = os.getenv(
        "TWINFORGE_CHECKPOINT_REVISION", "00f9c245bbcb60522d1ed7f9e9d88462c6e3f38a"
    )
    if os.getenv("TWINFORGE_REQUIRE_CUDA", "0") == "1" and not torch.cuda.is_available():
        pytest.skip("the configured model smoke test requires CUDA, which is unavailable")
    try:
        hub.snapshot_download(checkpoint, revision=revision, local_files_only=True)
    except (OSError, ValueError, hub_errors.LocalEntryNotFoundError) as exc:
        pytest.skip(
            f"checkpoint {checkpoint} is not available in the local Hugging Face cache: {exc}"
        )

    from twinforge.backends.mapanything import MapAnythingBackend
    from twinforge.config import BackendConfig, OutputConfig, TwinForgeConfig
    from twinforge.reconstruction.orchestrator import ReconstructionOrchestrator

    config = TwinForgeConfig(
        backend=BackendConfig(
            device="auto",
            checkpoint=checkpoint,
            checkpoint_revision=revision,
            maximum_keyframes=12,
        ),
        output=OutputConfig(root=tmp_path / "output", preview_glb=True),
    )
    backend = MapAnythingBackend(checkpoint, checkpoint_revision=revision)
    output = ReconstructionOrchestrator(backend, config).run(Path(video_value), device="auto")
    assert (output / "pointcloud.ply").is_file()
    assert (output / "cameras.json").is_file()
    assert (output / "quality.json").is_file()
