"""Versioned, fixed FFmpeg input-color policy; no geometry-dependent tuning."""

from __future__ import annotations

from typing import Any, Literal

from twinforge.core.types import VideoMetadata
from twinforge.exceptions import VideoDecodeError

type ColorPolicyName = Literal["auto", "sdr", "hlg", "pq"]


def build_color_policy(
    metadata: VideoMetadata, override: ColorPolicyName = "auto"
) -> dict[str, Any]:
    """Declare SDR bypass or a single HDR path and its display assumptions."""
    if override not in ("auto", "sdr", "hlg", "pq"):
        raise ValueError("color_policy must be auto, sdr, hlg, or pq")
    warnings: list[str] = []
    tags = {
        name: getattr(metadata, name)
        for name in (
            "color_primaries",
            "color_transfer",
            "color_space",
            "color_range",
            "pixel_format",
        )
    }
    missing = [name for name, value in tags.items() if value in (None, "unknown", "unspecified")]
    if missing:
        warnings.append("Missing metadata: " + ", ".join(missing))
    detected = {"arib-std-b67": "hlg", "smpte2084": "pq"}.get(metadata.color_transfer, "sdr")
    policy = detected if override == "auto" else override
    if detected != "sdr" and (
        metadata.color_primaries not in (None, "unknown", "unspecified", "bt2020")
        or metadata.color_space not in (None, "unknown", "unspecified", "bt2020nc")
    ):
        warnings.append("HDR transfer conflicts with primaries or matrix metadata")
        if override == "auto":
            raise VideoDecodeError(
                "Conflicting HDR metadata: specify --color-policy hlg, pq, or sdr."
            )
    if policy != "sdr" and missing:
        warnings.append("HDR missing fields assume BT.2020 nonconstant matrix and limited range")
    if (
        metadata.color_transfer
        not in (
            None,
            "unknown",
            "unspecified",
            "bt709",
            "smpte170m",
            "iec61966-2-1",
            "bt2020-10",
            "bt2020-12",
            "arib-std-b67",
            "smpte2084",
        )
        and override == "auto"
    ):
        raise VideoDecodeError("Unsupported transfer metadata: specify --color-policy explicitly.")
    transfer = "arib-std-b67" if policy == "hlg" else "smpte2084"
    source_range = metadata.color_range if metadata.color_range in ("tv", "pc") else "tv"
    filters = (
        ""
        if policy == "sdr"
        else (
            f"zscale=transferin={transfer}:primariesin=bt2020:matrixin=bt2020nc:"
            f"rangein={source_range}:transfer=linear:primaries=bt2020:matrix=gbr:range=full:"
            "npl=100,format=gbrpf32le,"
            "zscale=primaries=bt709,tonemap=hable:peak=10:desat=2,"
            "zscale=transfer=iec61966-2-1:matrix=170m:range=full,format=yuvj420p"
        )
    )
    return {
        "schema_version": "0.2",
        "version": "phone-hable-srgb-v1",
        "policy": policy,
        "user_override": override != "auto",
        "source_metadata": tags,
        "warnings": warnings,
        "filter": filters,
        "output_bit_depth": 8,
        "output_transfer": "source SDR bypass" if policy == "sdr" else "sRGB",
        "output_rgb_primaries": "source SDR bypass" if policy == "sdr" else "bt709",
        "jpeg_ycbcr_matrix": "FFmpeg SDR default" if policy == "sdr" else "BT.601 (JFIF)",
        "reference_white_nits": None if policy == "sdr" else 100,
        "assumed_display_peak_nits": None if policy == "sdr" else 1000,
        "tonemap_peak_relative_to_white": None if policy == "sdr" else 10,
        "linearization_assumption": None
        if policy == "sdr"
        else "zscale npl=100; fixed linear-signal peak=10; no mastering-metadata fit",
        "limitations": "HLG display assumptions are not physical camera calibration.",
    }
