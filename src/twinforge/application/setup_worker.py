"""Explicit cache preparation and small device probes in an isolated Python process."""

from __future__ import annotations

import argparse
import fcntl
import json
import os
import shutil
import tempfile
import urllib.request
import zipfile
from pathlib import Path

from twinforge.application.library import atomic_json


def _prepare_repository(torch_home: Path, reserve: int) -> None:
    hub = torch_home / "hub"
    destination = hub / "facebookresearch_dinov2_main"
    if (destination / "hubconf.py").is_file():
        return
    hub.mkdir(parents=True, exist_ok=True)
    # Source only: do not instantiate a Torch Hub model or fetch separate DINO weights.
    with tempfile.TemporaryDirectory(prefix="dinov2-prepare-", dir=hub) as temporary:
        root = Path(temporary)
        archive = root / "repository.zip"
        with (
            urllib.request.urlopen(
                "https://github.com/facebookresearch/dinov2/archive/refs/heads/main.zip", timeout=30
            ) as response,
            archive.open("wb") as target,
        ):
            received = 0
            while chunk := response.read(1024**2):
                received += len(chunk)
                if received > 64 * 1024**2 or shutil.disk_usage(hub).free < reserve + len(chunk):
                    raise ValueError("Repository transfer exceeds storage policy")
                target.write(chunk)
        with zipfile.ZipFile(archive) as bundle:
            if sum(item.file_size for item in bundle.infolist()) > 256 * 1024**2:
                raise ValueError("Repository extraction exceeds policy")
            for item in bundle.infolist():
                path = root / item.filename
                if (
                    not path.resolve().is_relative_to(root)
                    or (item.external_attr >> 16) & 0o170000 == 0o120000
                ):
                    raise ValueError("Invalid repository archive path")
            if shutil.disk_usage(hub).free < reserve + sum(
                item.file_size for item in bundle.infolist()
            ):
                raise ValueError("Insufficient repository extraction storage")
            bundle.extractall(root)
        source = root / "dinov2-main"
        if not (source / "hubconf.py").is_file() or destination.exists():
            raise ValueError("Repository cache requires manual inspection")
        os.replace(source, destination)
        # Match the trusted repository format used by this installed Torch Hub version.
        trusted = hub / "trusted_list"
        entries = trusted.read_text().splitlines() if trusted.exists() else []
        if "facebookresearch_dinov2" not in entries:
            with trusted.open("a") as stream:
                stream.write("facebookresearch_dinov2\n")


def prepare(args) -> None:
    from huggingface_hub import HfApi, hf_hub_download

    snapshot = (
        args.hf_cache
        / ("models--" + args.checkpoint.replace("/", "--"))
        / "snapshots"
        / args.revision
    )
    missing = [
        name for name in ("config.json", "model.safetensors") if not (snapshot / name).is_file()
    ]
    size = 0
    if missing:
        info = HfApi().model_info(args.checkpoint, revision=args.revision, files_metadata=True)
        known = {item.rfilename: item.size for item in info.siblings}
        size = (
            sum(known[name] for name in missing)
            if all(known.get(name) is not None for name in missing)
            else None
        )
    atomic_json(
        args.state,
        {
            "state": "downloading",
            "download_bytes": size,
            "message": "Preparing missing checkpoint files and Torch Hub source. Repository source bytes are additional when missing.",
        },
    )
    args.hf_cache.mkdir(parents=True, exist_ok=True)
    checkpoint_bytes = 8 * 1024**3 if size is None else size
    if missing and shutil.disk_usage(args.hf_cache).free < args.reserve + checkpoint_bytes:
        raise ValueError("Insufficient checkpoint cache storage")
    for name in missing:
        hf_hub_download(args.checkpoint, name, revision=args.revision, cache_dir=args.hf_cache)
    _prepare_repository(args.torch_home, args.reserve)
    atomic_json(
        args.state,
        {
            "state": "complete",
            "download_bytes": size,
            "message": "Checkpoint and Torch Hub source are cached. No model was loaded and no processing was started.",
        },
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("prepare", "check-device"))
    for name in ("hf-home", "hf-cache", "torch-home", "state"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--checkpoint", required=True)
    parser.add_argument("--revision", required=True)
    parser.add_argument("--reserve", type=int, required=True)
    args = parser.parse_args()
    try:
        if args.action == "check-device":
            import torch

            cpu = torch.empty(1).device.type == "cpu"
            cuda = False
            if torch.cuda.is_available():
                try:
                    cuda = torch.empty(1, device="cuda").device.type == "cuda"
                except RuntimeError:
                    pass
            print(json.dumps({"cpu": cpu, "cuda": cuda}))
        else:
            # The lock closes the spawn/ownership-record crash window. A second worker
            # cannot download while a surviving previous-instance worker holds it.
            with args.state.with_name("model-setup-worker.lock").open("a+b") as lock:
                try:
                    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError:
                    return 3
                prepare(args)
        return 0
    except Exception:  # noqa: BLE001 -- isolated worker must publish safe setup failures.
        if args.action == "prepare":
            atomic_json(
                args.state,
                {
                    "state": "failed",
                    "message": "Preparation failed. Check connectivity, cache permissions, backend installation, and free disk space, then retry explicitly.",
                },
            )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
