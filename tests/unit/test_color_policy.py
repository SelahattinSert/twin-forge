from dataclasses import replace

import pytest

from twinforge.core.types import VideoMetadata
from twinforge.exceptions import VideoDecodeError


def metadata(**changes):
    return replace(
        VideoMetadata("fixture.mov", "mov", "hevc", 64, 32, 1, 1, 0, 1, 64, 32), **changes
    )


def test_explicit_metadata_drives_versioned_hdr_policy():
    from twinforge.ingest.color import build_color_policy

    source = metadata(
        color_transfer="arib-std-b67",
        color_primaries="bt2020",
        color_space="bt2020nc",
        color_range="tv",
    )
    policy = build_color_policy(source)
    assert policy["policy"] == "hlg"
    assert "transferin=arib-std-b67" in policy["filter"]
    assert "tonemap=hable:peak=10:desat=2" in policy["filter"]
    assert "transfer=iec61966-2-1" in policy["filter"]


def test_sdr_bypass_and_missing_metadata_are_explicit():
    from twinforge.ingest.color import build_color_policy

    assert build_color_policy(metadata(color_transfer="bt709"))["filter"] == ""
    unknown = build_color_policy(metadata())
    assert unknown["policy"] == "sdr"
    assert unknown["warnings"]


def test_conflicting_hdr_requires_override():
    from twinforge.ingest.color import build_color_policy

    source = metadata(color_transfer="smpte2084", color_primaries="bt709")
    with pytest.raises(VideoDecodeError, match="color-policy"):
        build_color_policy(source)
    assert build_color_policy(source, "pq")["user_override"] is True
