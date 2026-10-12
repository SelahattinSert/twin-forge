"""TwinForge command line interface."""

from __future__ import annotations

import argparse
import json
import logging
import math
import sys
import traceback
from dataclasses import replace
from pathlib import Path

from twinforge.config import (
    BackendConfig,
    KeyframeConfig,
    MemoryConfig,
    OutputConfig,
    TwinForgeConfig,
    VideoConfig,
)
from twinforge.exceptions import TwinForgeError
from twinforge.ingest.video import VideoIngestor
from twinforge.logging import configure_logging

logger = logging.getLogger("twinforge")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="twinforge", description="Reconstruct spatial geometry from ordinary RGB video"
    )
    parser.add_argument(
        "--verbose", action="store_true", help="show debug logs and full error tracebacks"
    )
    commands = parser.add_subparsers(dest="command", required=True)
    inspect = commands.add_parser("inspect", help="inspect video metadata without loading a model")
    inspect.add_argument("video", type=Path)
    inspect.add_argument("--candidate-interval", type=float, default=0.5)
    app = commands.add_parser("app", help="open the persistent local scene library")
    app.add_argument("--library", type=Path, default=Path("output/phase2/library"))
    app.add_argument(
        "--import-root",
        type=Path,
        action="append",
        default=[],
        help="explicit root for linked scene and provenance discovery; repeatable",
    )
    app.add_argument("--port", type=int, default=0)
    app.add_argument("--no-browser", action="store_true")
    app.add_argument("--hf-home", type=Path, help="Hugging Face cache home for setup and workers")
    app.add_argument("--hf-hub-cache", type=Path, help="explicit Hugging Face Hub cache directory")
    app.add_argument("--torch-home", type=Path, help="Torch cache home for setup and workers")
    app.add_argument(
        "--upload-limit-gib", type=float, default=8, help="finite local transfer cap in GiB"
    )
    view = commands.add_parser(
        "view", help="inspect a saved scene in a local browser without a model"
    )
    view.add_argument("scene", type=Path, help="scene directory or scene.json")
    view.add_argument(
        "--workspace",
        type=Path,
        default=None,
        help="separate annotation workspace (default: output/phase1/workspaces/<hash>)",
    )
    view.add_argument("--port", type=int, default=0, help="loopback port; 0 selects a free port")
    view.add_argument(
        "--no-browser", action="store_true", help="print URL without opening a browser"
    )
    reconstruct = commands.add_parser(
        "reconstruct", help="select keyframes and reconstruct a point cloud"
    )
    reconstruct.add_argument("video", type=Path)
    reconstruct.add_argument("--output", type=Path, default=Path("output"))
    reconstruct.add_argument(
        "--max-keyframes",
        type=int,
        default=None,
        help="optional upper limit; automatic memory budget applies by default",
    )
    reconstruct.add_argument(
        "--no-auto-budget",
        action="store_true",
        help="disable heuristic frame budget (OOM retry remains enabled)",
    )
    reconstruct.add_argument(
        "--no-oom-retry",
        action="store_true",
        help="fail on first inference OOM without reducing frames",
    )
    reconstruct.add_argument("--candidate-interval", type=float, default=0.5)
    reconstruct.add_argument("--color-policy", choices=("auto", "sdr", "hlg", "pq"), default="auto")
    reconstruct.add_argument("--device", choices=("auto", "cpu", "cuda"), default="auto")
    reconstruct.add_argument("--checkpoint", default="facebook/map-anything-apache")
    reconstruct.add_argument(
        "--checkpoint-revision",
        default="00f9c245bbcb60522d1ed7f9e9d88462c6e3f38a",
        help="immutable Hugging Face checkpoint revision (use a revision matching custom checkpoints)",
    )
    reconstruct.add_argument(
        "--no-glb", action="store_true", help="skip point-based GLB preview export"
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    configure_logging(args.verbose)
    try:
        if args.command == "app":
            from twinforge.application.config import ApplicationConfig
            from twinforge.application.server import serve_application

            cache_options = {
                key: value.expanduser().resolve()
                for key, value in (
                    ("hf_home", args.hf_home),
                    ("hf_hub_cache", args.hf_hub_cache),
                    ("torch_home", args.torch_home),
                )
                if value is not None
            }
            if not math.isfinite(args.upload_limit_gib) or args.upload_limit_gib <= 0:
                raise ValueError("Upload limit must be finite and positive")
            serve_application(
                ApplicationConfig(
                    library=args.library,
                    import_roots=tuple(args.import_root),
                    upload_limit=int(args.upload_limit_gib * 1024**3),
                    **cache_options,
                ),
                args.port,
                not args.no_browser,
            )
            return 0
        if args.command == "view":
            from twinforge.viewer.server import serve_scene

            serve_scene(args.scene, args.workspace, args.port, not args.no_browser)
            return 0
        if args.command == "inspect":
            metadata = VideoIngestor().inspect(args.video)
            _print_inspection(metadata, args.candidate_interval)
            return 0
        keyframes = replace(KeyframeConfig(), maximum_keyframes=args.max_keyframes)
        config = TwinForgeConfig(
            video=VideoConfig(
                candidate_interval_seconds=args.candidate_interval, color_policy=args.color_policy
            ),
            keyframes=keyframes,
            backend=BackendConfig(
                device=args.device,
                checkpoint=args.checkpoint,
                checkpoint_revision=args.checkpoint_revision,
                maximum_keyframes=args.max_keyframes,
            ),
            output=OutputConfig(root=args.output, preview_glb=not args.no_glb),
            memory=MemoryConfig(
                auto_budget=not args.no_auto_budget,
                maximum_oom_retries=0 if args.no_oom_retry else 3,
            ),
        )
        from twinforge.backends.mapanything import MapAnythingBackend
        from twinforge.reconstruction.orchestrator import ReconstructionOrchestrator

        backend = MapAnythingBackend(
            checkpoint=args.checkpoint, checkpoint_revision=args.checkpoint_revision
        )
        ReconstructionOrchestrator(backend, config).run(
            args.video, args.output, args.device, args.verbose
        )
        return 0
    except (TwinForgeError, ValueError, OSError) as exc:
        logger.error("%s", exc)
        if args.verbose:
            traceback.print_exc()
        return 2


def _print_inspection(metadata, interval: float) -> None:
    if interval <= 0:
        raise ValueError("candidate interval must be positive")
    candidate_count = max(1, math.ceil(metadata.duration_seconds / interval))
    print(
        json.dumps(
            {
                "file": Path(metadata.path).name,
                "container": metadata.container,
                "codec": metadata.codec,
                "duration_seconds": metadata.duration_seconds,
                "resolution": [metadata.width, metadata.height],
                "display_resolution": [metadata.display_width, metadata.display_height],
                "fps": metadata.fps,
                "rotation_degrees": metadata.rotation_degrees,
                "approximate_frame_count": metadata.frame_count,
                "candidate_interval_seconds": interval,
                "estimated_candidate_frames": candidate_count,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    sys.exit(main())
