"""Thumbnail generation is bounded, thread-safe and never edits source images."""

import hashlib
from concurrent.futures import ThreadPoolExecutor

import cv2
import numpy as np
import pytest

from twinforge.viewer.thumbnails import ThumbnailCache


def test_thumbnail_size_cache_invalidation_and_source_preservation(tmp_path):
    path = tmp_path / "source.jpg"
    assert cv2.imwrite(str(path), np.full((800, 400, 3), 120, dtype=np.uint8))
    original = hashlib.sha256(path.read_bytes()).hexdigest()
    cache = ThumbnailCache()
    first = cache.get(path)
    assert cache.get(path) is first
    decoded = cv2.imdecode(np.frombuffer(first, dtype=np.uint8), cv2.IMREAD_COLOR)
    assert decoded.shape[:2] == (320, 160)
    assert hashlib.sha256(path.read_bytes()).hexdigest() == original
    assert cv2.imwrite(str(path), np.full((800, 400, 3), 200, dtype=np.uint8))
    assert cache.get(path) != first
    cache.clear()
    assert cache._bytes == 0 and not cache._items


def test_cache_is_bounded_and_parallel_requests_decode_once(tmp_path, monkeypatch):
    path = tmp_path / "source.jpg"
    assert cv2.imwrite(str(path), np.zeros((20, 30, 3), dtype=np.uint8))
    original_read = cv2.imread
    calls = []

    def read(*args):
        calls.append(args)
        return original_read(*args)

    monkeypatch.setattr(cv2, "imread", read)
    cache = ThumbnailCache(max_entries=2)
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda _: cache.get(path), range(16)))
    assert len(calls) == 1 and all(data is results[0] for data in results)
    decoded = cv2.imdecode(np.frombuffer(results[0], dtype=np.uint8), cv2.IMREAD_COLOR)
    assert decoded.shape[:2] == (20, 30)  # Do not upscale small images.
    for i in range(4):
        other = tmp_path / f"{i}.jpg"
        other.write_bytes(path.read_bytes())
        cache.get(other)
    assert len(cache._items) == 2 and cache._bytes <= cache.max_bytes
    tiny = ThumbnailCache(max_bytes=1)
    tiny.get(path)
    assert tiny._bytes == 0 and not tiny._items


def test_invalid_image_is_not_cached(tmp_path):
    path = tmp_path / "broken.jpg"
    path.write_bytes(b"not an image")
    cache = ThumbnailCache()
    with pytest.raises(ValueError, match="could not be decoded"):
        cache.get(path)
    assert not cache._items
