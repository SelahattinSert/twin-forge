# room2-video2 Local-Pair Camera Control Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Run one isolated RGB-only camera-control experiment that changes only the verified-pair graph's maximum timestamp separation from unrestricted to three seconds, then apply the already frozen camera gate.

**Architecture:** Build an auditable copy of the completed 65-image COLMAP database. Delete only verified `two_view_geometries` rows farther apart than three seconds; leave images, features, raw matches, camera/rig/frame metadata, and all prior artifacts untouched. Reuse the completed bridge experiment's three mapping arms, measurements, and gate through a small isolated runner. Stop before MapAnything M1/M2 if the gate fails.

**Tech Stack:** Python 3.12, SQLite, PyCOLMAP 4.2.0, NumPy, pytest, Ruff. Scripts and generated models live only under gitignored `output/camera-local-pairs-20260930/`.

## Global Constraints

- Primary scene `room2-video2`; the original 32 target JPEGs and order and 33 approved auxiliary JPEGs remain byte-identical.
- Source camera-bridge database SHA-256: `45f6c8fe785b2506a5d47d90e5cdf3f887f082485da3efe40f6df0b5b419e4ae`.
- Expected verified edges: 374 input, 172 retained (timestamp gap ≤3 seconds), 202 excluded (>3 seconds); the retained 65-image graph must be connected.
- Camera model `SIMPLE_RADIAL`; use the exact prior mapper and bundle-adjustment options and the exact `full`, `drop_mod0`, `drop_mod2` arms.
- Gate source `output/camera-conditioning-20260927/protocol.json:camera_solution_gate` stays unchanged. No post-result threshold, frame, seed, or camera-model tuning.
- No physical benchmark distance, MapAnything output, SkyeBrowse output, or metric scale enters the camera solution. No production TwinForge source or historical reconstruction may be changed.
- If the camera gate fails, report `camera_solution_insufficient` and do not run M1/M2 or DA3. If it passes, run already-approved fresh M0/M1/M2 on original 32 target JPEGs only; never silently lower 32 views due to OOM.

---

### Task 1: Isolated database filter and integrity tests

**Files:**
- Create: `output/camera-local-pairs-20260930/local_pairs.py`
- Create: `output/camera-local-pairs-20260930/test_local_pairs.py`

**Interfaces:**
- Consumes: `output/camera-bridge-20260929/database.db` and `images.json`.
- Produces: `filter_verified_pairs(source: Path, destination: Path, timestamps: dict[str, float]) -> dict[str, int]` and `load_timestamps(manifest: Path) -> dict[str, float]`.

- [ ] **Step 1: Write failing tests.** Test missing/duplicate timestamp names, the real input's 374→172/202 edge counts and 65-image connectivity on a temporary copy, preserved source SHA, and unchanged `cameras`, `rigs`, `frames`, `frame_data`, `images`, `keypoints`, and raw `matches` rows. Use an immutable SQLite URI for all source reads.

```python
from pathlib import Path

import pytest
from local_pairs import filter_verified_pairs, load_timestamps, sha256, table_rows


def test_real_graph_filter_preserves_source_and_non_geometry_rows(tmp_path):
    source = Path("output/camera-bridge-20260929/database.db")
    before = sha256(source)
    copied = tmp_path / "filtered.db"
    summary = filter_verified_pairs(
        source,
        copied,
        load_timestamps(Path("output/camera-bridge-20260929/images.json")),
    )
    assert summary == {"input_edges": 374, "kept_edges": 172, "removed_edges": 202,
                       "connected_images": 65, "components": 1}
    assert sha256(source) == before
    for table in ("cameras", "rigs", "frames", "frame_data", "images", "keypoints", "matches"):
        assert table_rows(source, table) == table_rows(copied, table)


def test_timestamp_manifest_rejects_duplicate_names(tmp_path):
    manifest = tmp_path / "images.json"
    manifest.write_text('{"target_images":[{"name":"a","timestamp_seconds":0}],'
                        '"auxiliary_images":[{"name":"a","second":1}]}')
    with pytest.raises(ValueError, match="unique"):
        load_timestamps(manifest)


def test_timestamp_manifest_rejects_duplicate_times(tmp_path):
    source = Path("output/camera-bridge-20260929/images.json")
    import json
    data = json.loads(source.read_text())
    data["auxiliary_images"][0]["second"] = data["target_images"][0]["timestamp_seconds"]
    manifest = tmp_path / "images.json"
    manifest.write_text(json.dumps(data))
    with pytest.raises(ValueError, match="unique"):
        load_timestamps(manifest)
```

- [ ] **Step 2: Run the tests red.**

```bash
PYTHONPATH=output/camera-local-pairs-20260930 .venv/bin/python -m pytest -q output/camera-local-pairs-20260930/test_local_pairs.py
```

Expected: collection fails because `local_pairs` does not yet exist.

- [ ] **Step 3: Implement the minimal filter.** Copy only to a non-existing destination. Decode COLMAP's `pair_id` using divisor `2147483647`. Require all 65 database image names have distinct finite timestamps; reject unexpected edge counts or disconnected local graph. Delete only >3-second rows in the copy; compare non-geometry SQLite row values before/after; check source digest again.

```python
from __future__ import annotations

import hashlib
import json
import math
import shutil
import sqlite3
from pathlib import Path

MAX_IMAGE_ID = 2147483647
SOURCE_SHA = "45f6c8fe785b2506a5d47d90e5cdf3f887f082485da3efe40f6df0b5b419e4ae"
PRESERVED_TABLES = ("cameras", "rigs", "frames", "frame_data", "images", "keypoints", "matches")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def table_rows(path: Path, table: str) -> list[tuple]:
    if table not in PRESERVED_TABLES:
        raise ValueError("Unapproved table")
    with sqlite3.connect(f"file:{path}?immutable=1", uri=True) as db:
        return db.execute(f"SELECT * FROM {table} ORDER BY 1").fetchall()


def load_timestamps(manifest: Path) -> dict[str, float]:
    data = json.loads(manifest.read_text())
    rows = [(row["name"], float(row["timestamp_seconds"])) for row in data["target_images"]]
    rows.extend((row["name"], float(row["second"])) for row in data["auxiliary_images"])
    if len(rows) != 65 or len({name for name, _ in rows}) != 65 or len({t for _, t in rows}) != 65:
        raise ValueError("Expected 65 unique image timestamps")
    if not all(math.isfinite(t) for _, t in rows):
        raise ValueError("Non-finite timestamp")
    return dict(rows)


def filter_verified_pairs(source: Path, destination: Path, timestamps: dict[str, float]) -> dict[str, int]:
    if destination.exists():
        raise FileExistsError(destination)
    if sha256(source) != SOURCE_SHA:
        raise RuntimeError("Frozen source DB digest differs")
    before = {table: table_rows(source, table) for table in PRESERVED_TABLES}
    shutil.copyfile(source, destination)
    with sqlite3.connect(destination) as db:
        images = dict(db.execute("SELECT image_id, name FROM images"))
        if len(images) != 65 or set(images.values()) != set(timestamps):
            raise ValueError("Timestamp list does not match the 65 database images")
        pairs = [(int(pair_id), int(count)) for pair_id, count in
                 db.execute("SELECT pair_id, rows FROM two_view_geometries")]
        if len(pairs) != 374:
            raise ValueError("Unexpected input verified-pair count")
        parents = {name: name for name in timestamps}

        def root(name: str) -> str:
            while parents[name] != name:
                name = parents[name]
            return name

        removed = []
        for pair_id, count in pairs:
            first_id, second_id = divmod(pair_id, MAX_IMAGE_ID)
            first, second = images[first_id], images[second_id]
            if abs(timestamps[first] - timestamps[second]) > 3:
                removed.append((pair_id,))
            elif count >= 15:
                parents[root(first)] = root(second)
        summary = {"input_edges": len(pairs), "kept_edges": len(pairs) - len(removed),
                   "removed_edges": len(removed), "connected_images": len(images),
                   "components": len({root(name) for name in timestamps})}
        if summary != {"input_edges": 374, "kept_edges": 172, "removed_edges": 202,
                       "connected_images": 65, "components": 1}:
            raise RuntimeError(f"Local graph differs from preregistered facts: {summary}")
        db.executemany("DELETE FROM two_view_geometries WHERE pair_id=?", removed)
    for table in PRESERVED_TABLES:
        if table_rows(destination, table) != before[table]:
            raise RuntimeError(f"Protected non-geometry table changed: {table}")
    if sha256(source) != SOURCE_SHA:
        raise RuntimeError("Frozen source DB changed")
    return summary
```

- [ ] **Step 4: Run tests green and format.**

```bash
PYTHONPATH=output/camera-local-pairs-20260930 .venv/bin/python -m pytest -q output/camera-local-pairs-20260930/test_local_pairs.py
.venv/bin/ruff check output/camera-local-pairs-20260930
.venv/bin/ruff format --check output/camera-local-pairs-20260930
```

Expected: all tests and style checks pass. Because this task's scripts live in `output/`, retain code and test results as local experimental provenance; do not stage ignored outputs.

### Task 2: Frozen protocol, isolated mapping, and decision

**Files:**
- Create: `output/camera-local-pairs-20260930/protocol.json`
- Create: `output/camera-local-pairs-20260930/prepare.py`
- Create: `output/camera-local-pairs-20260930/run_mapping.py`
- Generate: isolated copied images, database, three mapping arms, `result.json`, and `report.md` under the same ignored directory.

**Interfaces:**
- Consumes: Task 1's filter; `output/camera-bridge-20260929/map_bridge.py` for the identical mapper, metrics, two controls, and gate.
- Produces: new `result.json` with the unchanged gate and source hashes.

- [ ] **Step 1: Write the fixed protocol before preparation.** Create `protocol.json` with the approved three-second rule, hashes and expected counts. The source hash values below are frozen. The existing camera gate is referenced, not copied and edited.

```json
{
  "schema_version": "local-pair-control-0.1",
  "primary_scene": "room2-video2",
  "source_camera_bridge_database_sha256": "45f6c8fe785b2506a5d47d90e5cdf3f887f082485da3efe40f6df0b5b419e4ae",
  "source_video_sha256": "174016a54d71fd0127c4904e5498d3e66a5adf9b3b17cae16833fe3b9ebc5bc5",
  "frozen_target_manifest_sha256": "46d045b0b49c242a16bad914fb3263e7f01482fa23bd4d0f902cfe86337281e5",
  "original_32_database_sha256": "43ee49aa8a77f3d21fd41f8a5a20cb83524e9c47c649b9a4737f184d8c5bd4a9",
  "unchanged_gate_protocol_sha256": "ca59aba2fa64b55e774cc2c326eb49a3c4a088aeb12097572f5eb5bcd1eeb862",
  "changed_variable": "delete only two_view_geometries rows with absolute image timestamp difference >3 seconds in a new database copy",
  "expected_input_verified_pairs": 374,
  "expected_retained_verified_pairs": 172,
  "expected_excluded_verified_pairs": 202,
  "arms": ["full", "drop_mod0", "drop_mod2"],
  "camera_model": "SIMPLE_RADIAL",
  "mapper_settings": "reuse output/camera-bridge-20260929/map_bridge.py mapping_options and BA settings without changes",
  "gate_source": "output/camera-conditioning-20260927/protocol.json:camera_solution_gate",
  "stop_if_gate_fails": true,
  "physical_ground_truth_used": false,
  "mapanything_used_in_camera_solution": false,
  "scale_type": "relative"
}
```

- [ ] **Step 2: Prepare isolated copies.** Implement `prepare.py` as below. It refuses pre-existing products, verifies all protected input hashes, copies the original JPEGs and manifest, filters only the copied verified-geometry table, and records the new digest. Do not extract new features or new frames.

```python
from __future__ import annotations

import json
import shutil
from pathlib import Path

from local_pairs import filter_verified_pairs, sha256

HERE = Path(__file__).resolve().parent
BRIDGE = HERE.parent / "camera-bridge-20260929"
PRIOR = HERE.parent / "camera-conditioning-20260927"
ROOT = HERE.parent.parent


def main() -> None:
    protocol_path = HERE / "protocol.json"
    protocol = json.loads(protocol_path.read_text())
    protected = (
        (BRIDGE / "database.db", protocol["source_camera_bridge_database_sha256"]),
        (ROOT / "samples/room2-video2.mp4", protocol["source_video_sha256"]),
        (PRIOR / "frozen/room2-video2/keyframes.json", protocol["frozen_target_manifest_sha256"]),
        (PRIOR / "colmap-rescue/room2-video2/aliked_lightglue/database.db",
         protocol["original_32_database_sha256"]),
        (PRIOR / "protocol.json", protocol["unchanged_gate_protocol_sha256"]),
    )
    for path, digest in protected:
        if sha256(path) != digest:
            raise RuntimeError(f"Protected input changed: {path}")
    for name in ("database.db", "images", "images.json", "match-execution.json", "filter-audit.json"):
        if (HERE / name).exists():
            raise FileExistsError(HERE / name)
    shutil.copytree(BRIDGE / "images", HERE / "images")
    shutil.copyfile(BRIDGE / "images.json", HERE / "images.json")
    manifest = json.loads((HERE / "images.json").read_text())
    for row in manifest["target_images"] + manifest["auxiliary_images"]:
        if sha256(HERE / "images" / row["name"]) != row["sha256"]:
            raise RuntimeError(f"Copied JPEG changed: {row['name']}")
    source_match_path = BRIDGE / "match-execution.json"
    shutil.copyfile(source_match_path, HERE / "match-execution-before-local-filter.json")
    from local_pairs import load_timestamps
    summary = filter_verified_pairs(BRIDGE / "database.db", HERE / "database.db",
                                    load_timestamps(HERE / "images.json"))
    match = json.loads(source_match_path.read_text())
    match["extended_database_sha256"] = sha256(HERE / "database.db")
    match["local_pair_filter"] = summary
    (HERE / "match-execution.json").write_text(json.dumps(match, indent=2) + "\n")
    audit = {"protocol_sha256": sha256(protocol_path),
             "source_database_sha256": sha256(BRIDGE / "database.db"),
             "filtered_database_sha256": sha256(HERE / "database.db"),
             **summary}
    (HERE / "filter-audit.json").write_text(json.dumps(audit, indent=2) + "\n")
    for path, digest in protected:
        if sha256(path) != digest:
            raise RuntimeError(f"Protected input changed after preparation: {path}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 3: Run the existing mapper's functions via an isolated wrapper.** The completed bridge's `main()` cannot be called because its original-record audit intentionally requires all original verified pair rows, including the 202 this control deletes. Reuse its actual `map_variant`, `evaluate_components`, `gate_result` and the unchanged gate, but perform a local source/hash audit in this wrapper. This is experimental code only; do not modify `map_bridge.py`.

```python
from __future__ import annotations

import json
import resource
from pathlib import Path
import sys
import time

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "camera-bridge-20260929"))
import map_bridge  # noqa: E402
from local_pairs import load_timestamps, sha256, table_rows  # noqa: E402

BRIDGE = HERE.parent / "camera-bridge-20260929"
PRIOR = HERE.parent / "camera-conditioning-20260927"


def main() -> None:
    protocol = json.loads((HERE / "protocol.json").read_text())
    audit = json.loads((HERE / "filter-audit.json").read_text())
    images = json.loads((HERE / "images.json").read_text())
    match = json.loads((HERE / "match-execution.json").read_text())
    if (HERE / "result.json").exists():
        raise FileExistsError("Refusing to overwrite camera-control result")
    if sha256(HERE / "protocol.json") != audit["protocol_sha256"]:
        raise RuntimeError("Experimental protocol changed")
    if sha256(BRIDGE / "database.db") != protocol["source_camera_bridge_database_sha256"]:
        raise RuntimeError("Protected bridge database changed")
    if sha256(HERE / "database.db") != audit["filtered_database_sha256"]:
        raise RuntimeError("Filtered database changed")
    if match["extended_database_sha256"] != audit["filtered_database_sha256"]:
        raise RuntimeError("Mapper database digest differs from filtered audit")
    for table in ("cameras", "rigs", "frames", "frame_data", "images", "keypoints", "matches"):
        if table_rows(BRIDGE / "database.db", table) != table_rows(HERE / "database.db", table):
            raise RuntimeError(f"Non-geometry table changed: {table}")
    if len(load_timestamps(HERE / "images.json")) != 65:
        raise RuntimeError("Image manifest changed")
    for row in images["target_images"] + images["auxiliary_images"]:
        if sha256(HERE / "images" / row["name"]) != row["sha256"]:
            raise RuntimeError("Experimental image changed")
    map_bridge.HERE = HERE
    gate = json.loads((PRIOR / "protocol.json").read_text())["camera_solution_gate"]
    targets = {row["name"] for row in images["target_images"]}
    started = time.monotonic()
    variants = {}
    for variant in ("full", "drop_mod0", "drop_mod2"):
        execution = map_bridge.map_variant(variant, images, match["extended_database_sha256"])
        variants[variant] = {
            "execution": execution,
            "components": map_bridge.evaluate_components(variant, execution, targets),
        }
    camera_gate = map_bridge.gate_result(variants, gate, targets)
    if sha256(HERE / "protocol.json") != audit["protocol_sha256"]:
        raise RuntimeError("Protocol changed during mapping")
    if sha256(BRIDGE / "database.db") != protocol["source_camera_bridge_database_sha256"]:
        raise RuntimeError("Protected bridge database changed during mapping")
    result = {"schema_version": "local-pair-control-result-0.1", "scene": "room2-video2",
              "single_changed_variable": protocol["changed_variable"],
              "filter_audit": audit, "variants": variants, "gate": camera_gate,
              "runtime_seconds": time.monotonic() - started,
              "peak_host_rss_bytes": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024,
              "gpu_used": False,
              "physical_ground_truth_used": False, "mapanything_used": False,
              "scale_type": "relative", "meters_per_unit": None}
    (HERE / "result.json").write_text(json.dumps(result, indent=2, allow_nan=False) + "\n")
    print("GATE", camera_gate, flush=True)


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Verify and apply the unchanged gate.**

```bash
PYTHONPATH=output/camera-conditioning-20260927:output/camera-conditioning-20260927/deps:output/camera-local-graph-20260928:output/camera-bridge-20260929:output/camera-local-pairs-20260930 .venv/bin/python -u output/camera-local-pairs-20260930/run_mapping.py
PYTHONPATH=output/camera-conditioning-20260927:output/camera-conditioning-20260927/deps:output/camera-bridge-20260929:output/camera-local-pairs-20260930 .venv/bin/python -m pytest -q output/camera-local-pairs-20260930/test_local_pairs.py output/camera-bridge-20260929/test_bridge_database.py output/camera-bridge-20260929/test_bridge_selection.py output/camera-bridge-20260929/test_bridge_quality.py output/camera-conditioning-20260927/verify_experiment.py
```

Expected: `result.json` contains all three arms and `gate.passed` is either true or false, determined by the unchanged gate. The tests and protected-file verifier pass. If a setup or integrity check fails, preserve the partial arm, diagnose it, and do not count that as a camera-result pass or failure.

- [ ] **Step 5: Report actual measurements and stop at the gate.** Write `report.md` in the isolated output directory with per-arm registration, points, track/angle metrics, door/floor/ceiling support, held-out target P90, both subset center/rotation/focal P90 values, runtimes, peak RSS/VRAM, and the list of failed gate predicates. Explicitly state that RGB-only SfM is relative. If `gate.passed=false`, write `camera_solution_insufficient`, do not run M1/M2, and end this experiment. If true, proceed to the already-approved fresh M0/M1/M2 stage on the unchanged original 32 targets, with its own raw provenance and post-inference physical benchmark; no extra COLMAP retuning.

## Plan self-review

- The single changed variable is an edge deletion rule in a new copied database; graph connectivity was checked read-only before design approval.
- Existing mapping, subset controls, camera gate, images, features, and physical benchmark handling are reused without production-code changes.
- The plan contains no adaptive search over thresholds or hidden metric calibration. A failed gate ends the experiment.
