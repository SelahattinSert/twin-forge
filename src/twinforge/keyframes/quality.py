"""Resolution-normalized sharpness and exposure metrics."""

from __future__ import annotations

import cv2
import numpy as np


def measure_sharpness(image: np.ndarray) -> float:
    """Laplacian variance normalized to an 8-bit intensity scale."""
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    return float(cv2.Laplacian(gray, cv2.CV_64F).var() / (255.0**2))


def measure_exposure(image: np.ndarray) -> float:
    """Return 1 for well-distributed exposure, approaching 0 for clipped frames."""
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    clipped = np.mean((gray <= 4) | (gray >= 250))
    dynamic_range = (float(np.percentile(gray, 95)) - float(np.percentile(gray, 5))) / 255.0
    return float(max(0.0, min(1.0, (1.0 - clipped) * min(1.0, dynamic_range / 0.55))))


def perceptual_hash(image: np.ndarray) -> int:
    """Small grayscale DCT hash used only for deterministic duplicate rejection."""
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    reduced = cv2.resize(gray, (32, 32), interpolation=cv2.INTER_AREA).astype(np.float32)
    dct = cv2.dct(reduced)[:8, :8]
    values = dct.flatten()[1:]
    median = float(np.median(values))
    bits = values > median
    return sum(int(bit) << index for index, bit in enumerate(bits))


def hamming_distance(first: int, second: int) -> int:
    return (first ^ second).bit_count()
