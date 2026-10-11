"""Optional official preprocessing check: no weights, downloads, or inference."""

import pytest

from twinforge.backends.mapanything import load_images_with_provenance
from twinforge.scene.provenance import PixelTransform


def test_official_preprocessing_capture_records_actual_resize_and_crop(tmp_path):
    pytest.importorskip("mapanything", reason="Optional MapAnything package is not installed")
    from PIL import Image

    path = tmp_path / "source.png"
    Image.new("RGB", (464, 832), (70, 80, 90)).save(path)
    views, mappings = load_images_with_provenance([str(path)], [17])
    mapping = PixelTransform(**{**mappings[0], "crop_bbox": tuple(mappings[0]["crop_bbox"])})
    assert views[0]["img"].shape[-2:] == (518, 294)
    assert (mapping.resized_width, mapping.resized_height) == (294, 527)
    assert mapping.crop_bbox == (0, 4, 294, 522)
    assert mapping.official_intrinsics_scale == pytest.approx(294 / 464 + 1e-8)
    assert mapping.origin == "native"
