"""Adapter for the official MapAnything image-only inference API."""

from __future__ import annotations

import gc
import importlib.metadata
import logging
from typing import Any

import numpy as np

from twinforge.backends.base import DeviceMemory, ReconstructionBackend, ReconstructionContext
from twinforge.backends.mapanything_outputs import normalize_predictions
from twinforge.core.types import ReconstructionResult
from twinforge.exceptions import (
    BackendUnavailableError,
    ModelLoadError,
    OutOfMemoryReconstructionError,
    ReconstructionFailedError,
)

logger = logging.getLogger(__name__)


def load_images_with_provenance(paths: list[str], frame_ids: list[int]):
    """Execute official raster helpers and verify against the official loader.

    Record integer raster sizes and crop bounds separately from the scalar used
    by its intrinsics helper. This repeats preprocessing, never inference, and
    does not replace any official function or mutate module globals.
    """
    from mapanything.utils import cropping, image
    from PIL import Image, ImageOps

    from twinforge.scene.provenance import PixelTransform

    if len(paths) != len(frame_ids):
        raise ValueError("Source paths and frame IDs must have identical lengths")
    views = image.load_images(paths)
    if len(views) != len(paths):
        raise ValueError("Official loader omitted source images; provenance order unavailable")
    records = []
    for path, frame_id, view in zip(paths, frame_ids, views, strict=True):
        with Image.open(path) as source:
            raster = ImageOps.exif_transpose(source).convert("RGB")
        source_width, source_height = raster.size
        target_height, target_width = map(int, view["img"].shape[-2:])
        resized = cropping.rescale_image_and_other_optional_info(
            raster, np.array([target_width, target_height])
        )[0]
        resized_width, resized_height = resized.size
        left = (resized_width - target_width) // 2
        top = (resized_height - target_height) // 2
        bbox = (left, top, left + target_width, top + target_height)
        cropped = cropping.crop_image_and_other_optional_info(resized, bbox)[0]
        normalization = image.IMAGE_NORMALIZATION_DICT[view["data_norm_type"][0]]
        normalize = image.tvf.Compose(
            [
                image.tvf.ToTensor(),
                image.tvf.Normalize(mean=normalization.mean, std=normalization.std),
            ]
        )
        repeated = normalize(cropped)[None]
        if not np.array_equal(repeated.numpy(), view["img"].numpy()):
            raise ValueError("Recorded raster operations disagree with official preprocessing")
        scalar = float(max(target_width / source_width, target_height / source_height) + 1e-8)
        records.append(
            PixelTransform(
                frame_id,
                source_width,
                source_height,
                resized_width,
                resized_height,
                bbox,
                "native",
                scalar,
            ).to_dict()
        )
    return views, records


class MapAnythingBackend(ReconstructionBackend):
    """Runs ``MapAnything.from_pretrained`` / ``model.infer`` and normalizes its outputs."""

    def __init__(
        self,
        checkpoint: str = "facebook/map-anything-apache",
        checkpoint_revision: str | None = "00f9c245bbcb60522d1ed7f9e9d88462c6e3f38a",
        point_stride: int = 1,
    ):
        self.checkpoint = checkpoint
        self.checkpoint_revision = checkpoint_revision
        self.point_stride = max(1, point_stride)
        self._model: Any = None
        self._torch: Any = None
        self.device: str | None = None

    def _load(self, requested_device: str) -> None:
        try:
            import torch
            from mapanything.models import MapAnything
        except ImportError as exc:
            raise BackendUnavailableError(
                "MapAnything is not installed. Use Python 3.12 and install TwinForge with `pip install -e '.[mapanything]'`, then install a PyTorch build for this machine."
            ) from exc
        device = requested_device
        if device == "auto":
            device = "cuda" if torch.cuda.is_available() else "cpu"
        if device.startswith("cuda") and not torch.cuda.is_available():
            raise BackendUnavailableError(
                "CUDA was requested but this PyTorch build has no available CUDA device."
            )
        if device not in ("cpu", "cuda") and not device.startswith("cuda:"):
            raise BackendUnavailableError(
                f"MapAnything documentation currently supports CPU or CUDA, not {device!r}."
            )
        self._torch, self.device = torch, device
        try:
            self._model = MapAnything.from_pretrained(
                self.checkpoint, revision=self.checkpoint_revision
            )
            self._model = self._model.to(device).eval()
        except Exception as exc:
            if _is_oom(exc, torch):
                raise ModelLoadError(
                    "MapAnything model weights do not fit on the requested device. "
                    "Reducing keyframes cannot fix model-load OOM; use more memory or --device cpu."
                ) from exc
            raise ModelLoadError(
                f"Could not load MapAnything checkpoint {self.checkpoint!r}: {exc}"
            ) from exc

    def prepare(self, context: ReconstructionContext) -> None:
        self._load(context.device)

    def close(self) -> None:
        if self._model is not None:
            del self._model
            self._model = None
        gc.collect()
        if self._torch is not None and self.device and self.device.startswith("cuda"):
            self._torch.cuda.empty_cache()
        self._torch = None
        self.device = None

    def memory_info(self) -> DeviceMemory:
        if self._torch is None or not self.device:
            return DeviceMemory("unknown")
        if not self.device.startswith("cuda"):
            return DeviceMemory(self.device)
        try:
            free, total = self._torch.cuda.mem_get_info(self.device)
        except (RuntimeError, ValueError, TypeError):
            logger.warning(
                "CUDA memory measurement unavailable; using conservative fallback frame cap"
            )
            return DeviceMemory(self.device)
        return DeviceMemory(self.device, int(free), int(total))

    def reconstruct(
        self,
        frames,
        context: ReconstructionContext,
    ) -> ReconstructionResult:
        if self._model is None:
            self._load(context.device)
        torch = self._torch
        try:
            views, pixel_transforms = load_images_with_provenance(
                [frame.image_path for frame in frames], [frame.frame_id for frame in frames]
            )
            from mapanything.utils.device import get_amp_dtype

            effective_amp_dtype = str(get_amp_dtype(self.device, "bf16"))
            memory_preflight = _memory_preflight(views, torch, self.device)
            if memory_preflight["xyz_output_exceeds_free_vram"] is True:
                logger.warning(
                    "The float32 XYZ outputs alone have a lower-bound size of %.2f GiB, "
                    "larger than currently free VRAM (%.2f GiB). Peak inference memory "
                    "cannot be reliably predicted; consider --max-keyframes.",
                    memory_preflight["xyz_output_lower_bound_bytes"] / 1024**3,
                    memory_preflight["free_vram_bytes"] / 1024**3,
                )
            else:
                logger.info(
                    "Memory preflight: float32 XYZ output lower bound %.2f GiB; free VRAM %s. "
                    "This is not a peak-memory prediction.",
                    memory_preflight["xyz_output_lower_bound_bytes"] / 1024**3,
                    (
                        f"{memory_preflight['free_vram_bytes'] / 1024**3:.2f} GiB"
                        if memory_preflight["free_vram_bytes"] is not None
                        else "unavailable"
                    ),
                )
            with torch.inference_mode():
                predictions = self._model.infer(
                    views,
                    memory_efficient_inference=True,
                    minibatch_size=1,
                    use_amp=True,
                    # Retain raw prediction geometry; store validity separately.
                    apply_mask=False,
                    mask_edges=False,
                    apply_confidence_mask=False,
                )
            del views
        except Exception as exc:
            if _is_oom(exc, torch):
                vram = _available_vram(torch, self.device)
                raise OutOfMemoryReconstructionError(
                    f"MapAnything ran out of memory with {len(frames)} selected frames. "
                    f"Available VRAM: {vram or 'unavailable'}. Try --max-keyframes {max(3, len(frames) // 2)}."
                ) from exc
            if context.debug:
                logger.exception("MapAnything inference failed")
            raise ReconstructionFailedError(f"MapAnything inference failed: {exc}") from exc
        try:
            version = importlib.metadata.version("mapanything")
        except importlib.metadata.PackageNotFoundError:
            version = None
        return normalize_predictions(
            predictions,
            frames,
            point_stride=self.point_stride,
            checkpoint=self.checkpoint,
            backend_version=version,
            pixel_transforms=pixel_transforms,
            backend_metadata={
                "device": self.device,
                "checkpoint_revision": self.checkpoint_revision,
                "point_stride": self.point_stride,
                "source_coordinate_convention": "OpenCV world coordinates; +X right, +Y down, +Z forward",
                "memory_preflight": memory_preflight,
                "precision": {
                    "use_amp": True,
                    "input_dtype": "float32",
                    "geometry_export_dtype": "float32",
                    "requested_amp_dtype": "bf16",
                    "effective_autocast_dtype": effective_amp_dtype,
                },
            },
        )


def estimate_minimum_xyz_output_bytes(views: list[dict[str, Any]]) -> int:
    """Return dense float32 XYZ payload size, not total inference memory.

    MapAnything documents one (B, H, W, 3) point prediction per input view.
    Use the image dimensions after ``load_images`` resizes source frames. This
    excludes activations, other outputs, allocator overhead, and host copies.
    """
    bytes_per_xyz = 3 * np.dtype(np.float32).itemsize
    return sum(
        int(view["img"].shape[0])
        * int(view["img"].shape[2])
        * int(view["img"].shape[3])
        * bytes_per_xyz
        for view in views
    )


def _memory_preflight(
    views: list[dict[str, Any]], torch: Any, device: str | None
) -> dict[str, Any]:
    output_floor = estimate_minimum_xyz_output_bytes(views)
    free_vram = None
    if torch is not None and device and device.startswith("cuda") and torch.cuda.is_available():
        try:
            free_vram = int(torch.cuda.mem_get_info(device)[0])
        except (RuntimeError, ValueError, TypeError):
            pass
    return {
        "selected_keyframes": len(views),
        "xyz_output_lower_bound_bytes": output_floor,
        "free_vram_bytes": free_vram,
        "xyz_output_exceeds_free_vram": (
            output_floor > free_vram if free_vram is not None else None
        ),
        "scope": "float32 XYZ output only; excludes model weights, activations, other outputs, and allocator overhead",
        "peak_memory_estimate_available": False,
    }


def _is_oom(exc: Exception, torch: Any) -> bool:
    oom_type = getattr(torch.cuda, "OutOfMemoryError", ()) if torch is not None else ()
    return (bool(oom_type) and isinstance(exc, oom_type)) or "out of memory" in str(exc).lower()


def _available_vram(torch: Any, device: str | None) -> str | None:
    if (
        torch is None
        or not device
        or not device.startswith("cuda")
        or not torch.cuda.is_available()
    ):
        return None
    try:
        free_bytes, _total_bytes = torch.cuda.mem_get_info(device)
        return f"{free_bytes / (1024**3):.1f} GiB"
    except (RuntimeError, ValueError, TypeError):
        return None
