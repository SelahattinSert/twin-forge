"""Read-only verification of saved run hashes and preview-to-PLY identity.

Usage: python scripts/audit_viewer_artifacts.py path/to/run.json [more run.json ...]
No reconstruction, calibration, geometry edits or artifact writes are performed.
"""

import argparse
import json
import struct
import time
from pathlib import Path

import numpy as np

from twinforge.scene.reader import SceneReader, sha256_file
from twinforge.viewer.preview import build_preview
from twinforge.viewer.thumbnails import ThumbnailCache


def audit(run_path: Path) -> dict:
    run = json.loads(run_path.read_text())
    root = Path(run["source_root"]).resolve()
    mismatches = []
    for relative, digest in run["hashes"].items():
        path = (root / relative).resolve()
        if not path.is_relative_to(root):
            raise ValueError("Run reference escapes source root")
        if not path.is_file() or sha256_file(path) != digest:
            mismatches.append(relative)
    scene = SceneReader(Path(run["source_manifest"])).read()
    try:
        if run.get("preview_path"):
            path = Path(run["preview_path"])
            if sha256_file(path) != run["preview_sha256"]:
                mismatches.append("prepared_preview")
            data = path.read_bytes()
            if data[:4] != b"TFP1":
                raise ValueError("Invalid prepared preview")
            size = struct.unpack("<I", data[4:8])[0]
            header = json.loads(data[8 : 8 + size])

            def column(name):
                info = header["columns"][name]
                return np.frombuffer(
                    data, info["dtype"], int(np.prod(info["shape"])), info["offset"]
                ).reshape(info["shape"])

            xyz, indices = column("xyz"), column("point_indices")
        else:
            bundle = build_preview(scene)
            xyz, indices = bundle.xyz, bundle.point_indices
        raw = np.column_stack([scene.point_records[axis][indices] for axis in ("x", "y", "z")])
        identical = np.array_equal(xyz, raw)
        unique = len(np.unique(indices)) == len(indices)
        cache = ThumbnailCache()
        thumbnail_sizes, source_sizes, cold_ms, warm_ms = [], [], [], []
        for frame in scene.frames:
            source_sizes.append(frame.image_path.stat().st_size)
            start = time.perf_counter()
            thumbnail_sizes.append(len(cache.get(frame.image_path)))
            cold_ms.append((time.perf_counter() - start) * 1000)
            start = time.perf_counter()
            cache.get(frame.image_path)
            warm_ms.append((time.perf_counter() - start) * 1000)
        cache.clear()
        return {
            "run_id": run["run_id"],
            "verified_hash_count": len(run["hashes"]),
            "hash_mismatches": mismatches,
            "raw_point_count": scene.point_count,
            "preview_point_count": len(indices),
            "unique_source_row_indices": unique,
            "preview_xyz_exactly_equal_to_ply_rows": identical,
            "maximum_xyz_difference": float(np.max(np.abs(xyz - raw))) if len(xyz) else 0,
            "source_photos_total_bytes": sum(source_sizes),
            "thumbnail_photos_total_bytes": sum(thumbnail_sizes),
            "thumbnail_cold_median_ms": float(np.median(cold_ms)),
            "thumbnail_cached_median_ms": float(np.median(warm_ms)),
            "limitation": "Artifact and transport identity audit; no semantic sofa correspondence or geometric accuracy claim.",
        }
    finally:
        mapping = getattr(scene.point_records, "_mmap", None)
        if mapping is not None:
            mapping.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("runs", type=Path, nargs="+")
    args = parser.parse_args()
    results = [audit(path) for path in args.runs]
    print(json.dumps(results, indent=2, allow_nan=False))
    if any(
        result["hash_mismatches"]
        or not result["unique_source_row_indices"]
        or not result["preview_xyz_exactly_equal_to_ply_rows"]
        for result in results
    ):
        raise SystemExit(1)
