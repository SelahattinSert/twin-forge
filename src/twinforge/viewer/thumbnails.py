"""Small, read-only source previews with a bounded per-scene memory cache."""

from collections import OrderedDict
from pathlib import Path
from threading import Lock

import cv2


class ThumbnailCache:
    """Serialize decodes to bound peak RAM; never rewrite source images."""

    def __init__(self, max_bytes: int = 4 * 1024 * 1024, max_entries: int = 32):
        self.max_bytes = max_bytes
        self.max_entries = max_entries
        self._items: OrderedDict[tuple, bytes] = OrderedDict()
        self._bytes = 0
        self._lock = Lock()

    def get(self, path: Path) -> bytes:
        with self._lock:
            stat = path.stat()
            key = (path, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns)
            if key in self._items:
                self._items.move_to_end(key)
                return self._items[key]
            image = cv2.imread(str(path), cv2.IMREAD_COLOR)
            if image is None:
                raise ValueError("Source image could not be decoded for preview")
            height, width = image.shape[:2]
            ratio = min(1.0, 320 / max(width, height))
            if ratio < 1:
                image = cv2.resize(
                    image,
                    (max(1, round(width * ratio)), max(1, round(height * ratio))),
                    interpolation=cv2.INTER_AREA,
                )
            success, encoded = cv2.imencode(".jpg", image, [cv2.IMWRITE_JPEG_QUALITY, 78])
            if not success:
                raise ValueError("Source preview could not be encoded")
            data = encoded.tobytes()
            if len(data) <= self.max_bytes and self.max_entries > 0:
                self._items[key] = data
                self._bytes += len(data)
                while len(self._items) > self.max_entries or self._bytes > self.max_bytes:
                    self._bytes -= len(self._items.popitem(last=False)[1])
            return data

    def clear(self) -> None:
        with self._lock:
            self._items.clear()
            self._bytes = 0
