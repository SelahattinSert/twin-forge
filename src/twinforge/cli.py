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

from twinforge.backends.mapanything import MapAnythingBackend
from twinforge.config import (
    BackendConfig,
    KeyframeConfig,
    OutputConfig,
    TwinForgeConfig,
    VideoConfig,
)
from twinforge.exceptions import TwinForgeError
from twinforge.ingest.video import VideoIngestor
from twinforge.logging import configure_logging
from twinforge.reconstruction.orchestrator import ReconstructionOrchestrator

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
    reconstruct = commands.add_parser(
        "reconstruct", help="select keyframes and reconstruct a point cloud"
    )
    reconstruct.add_argument("video", type=Path)
    reconstruct.add_argument("--output", type=Path, default=Path("output"))
    reconstruct.add_argument("--max-keyframes", type=int, default=80)
    reconstruct.add_argument("--candidate-interval", type=float, default=0.5)
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
        if args.command == "inspect":
            metadata = VideoIngestor().inspect(args.video)
            _print_inspection(metadata, args.candidate_interval)
            return 0
        keyframes = replace(KeyframeConfig(), maximum_keyframes=args.max_keyframes)
        config = TwinForgeConfig(
            video=VideoConfig(candidate_interval_seconds=args.candidate_interval),
            keyframes=keyframes,
            backend=BackendConfig(
                device=args.device,
                checkpoint=args.checkpoint,
                checkpoint_revision=args.checkpoint_revision,
                maximum_keyframes=args.max_keyframes,
            ),
            output=OutputConfig(root=args.output, preview_glb=not args.no_glb),
        )
        backend = MapAnythingBackend(
            checkpoint=args.checkpoint, checkpoint_revision=args.checkpoint_revision
        )
        ReconstructionOrchestrator(backend, config).run(
            args.video, args.output, args.device, args.verbose
        )
        return 0
    except (TwinForgeError, ValueError) as exc:
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
