"""Persistent identities and durability without touching any real source artifacts."""

import json
import shutil
from pathlib import Path

import numpy as np
import pytest

from twinforge.application.config import ApplicationConfig
from twinforge.application.library import LibraryStore
from twinforge.application.server import ServiceCache
from twinforge.core.types import PointCloud
from twinforge.export.ply import write_ply
from twinforge.scene.provenance import PixelTransform
from twinforge.scene.reader import SceneReader, sha256_file


def make_scene(root: Path, offset=0):
    root.mkdir(parents=True)
    write_ply(
        root / "points.ply",
        PointCloud(
            np.array([[offset, 0, 0], [offset + 1, 0, 0]], dtype=np.float32),
            source_frame_id=np.array([3, 3], dtype=np.uint32),
        ),
    )
    (root / "photo.jpg").write_bytes(b"synthetic-test-photo")
    (root / "scene.json").write_text(
        json.dumps(
            {
                "schema_version": "0.1",
                "geometry": {"point_cloud": "points.ply"},
                "scale": {"type": "relative"},
                "cameras": "cameras.json",
                "keyframes": "keyframes.json",
            }
        )
    )
    (root / "cameras.json").write_text(
        json.dumps(
            {
                "cameras": [
                    {
                        "frame_id": 3,
                        "timestamp_seconds": 1,
                        "intrinsics": None,
                        "camera_to_world": np.eye(4).tolist(),
                    }
                ]
            }
        )
    )
    (root / "keyframes.json").write_text(
        json.dumps({"frames": [{"frame_id": 3, "timestamp_seconds": 1, "image_path": "photo.jpg"}]})
    )
    return root


@pytest.fixture
def library(tmp_path):
    imports = tmp_path / "imports"
    for index in range(3):
        make_scene(imports / str(index) / "same-name", index * 10)
    config = ApplicationConfig(tmp_path / "library", (imports,))
    with LibraryStore(config) as store:
        yield store


def register_three(store):
    return [
        store.import_scene(item["choice_id"], "Same display name")
        for item in store.discover()["scenes"]
    ]


def test_linked_card_requires_enabled_source_folder_after_restart(tmp_path):
    imports = tmp_path / "imports"
    make_scene(imports / "example")
    root = tmp_path / "library"
    with LibraryStore(ApplicationConfig(root, (imports,))) as store:
        record = store.import_scene(store.discover()["scenes"][0]["choice_id"], "Example")
        assert store.list()["scenes"][0]["ready_available"]
    with LibraryStore(ApplicationConfig(root)) as store:
        summary = store.list()["scenes"][0]
        assert summary["status"] == "source_unavailable"
        assert not summary["ready_available"]
        assert summary["availability_code"] == "source_not_enabled"
        assert "--import-root" in summary["availability_message"]
        assert str(imports) not in json.dumps(summary)
        run = store.run(record["scene_id"], record["default_run_id"])
        with pytest.raises(ValueError):
            store.validate_source(run)
    with LibraryStore(ApplicationConfig(root, (imports,))) as store:
        assert store.list()["scenes"][0]["ready_available"]


def test_linked_card_detects_missing_or_escaped_source_files(library, tmp_path):
    record = register_three(library)[0]
    run = library.run(record["scene_id"], record["default_run_id"])
    photo = Path(run["source_root"]) / "photo.jpg"
    photo.unlink()
    summary = library.summary(library.get(record["scene_id"]))
    assert summary["status"] == "source_unavailable"
    assert summary["availability_code"] == "source_missing"
    external = tmp_path / "outside.jpg"
    external.write_bytes(b"outside import roots")
    photo.symlink_to(external)
    summary = library.summary(library.get(record["scene_id"]))
    assert summary["status"] == "source_unavailable"
    assert summary["availability_code"] == "source_not_enabled"


def test_three_distinct_scenes_survive_restart_rename_archive_and_recovery(library):
    records = register_three(library)
    assert len({r["scene_id"] for r in records}) == 3
    assert len({r["default_session_id"] for r in records}) == 3
    scene_id = records[0]["scene_id"]
    library.patch(scene_id, {"name": "Renamed", "archived": True})
    library.close()
    with LibraryStore(library.config) as restarted:
        assert len(restarted.list()["scenes"]) == 3
        assert restarted.get(scene_id)["name"] == "Renamed"
        assert restarted.get(scene_id)["archived"]
        restarted.patch(scene_id, {"archived": False})
        # A damaged last replacement recovers the complete previous record.
        restarted._scene_path(scene_id).write_text("{")
        assert restarted.get(scene_id)["archived"]
        assert restarted.recovery
        other = records[1]["scene_id"]
        restarted._scene_path(other).write_text("bad")
        result = restarted.list()
        assert len(result["scenes"]) == 2 and len(result["issues"]) == 1


@pytest.mark.parametrize(
    "change",
    [
        {"name": None},
        {"created_at": "invalid-date"},
        {"created_at": "2026-W40-6T00:00:00+00:00"},
        {"created_at": "20261003T00:00:00+00:00"},
        {"updated_at": "2026-W40-6T00:00:00+00:00"},
        {"updated_at": "20261003T00:00:00+00:00"},
        {"updated_at": None},
        {"archived": "false"},
        {"versions": None},
        {"versions": [None]},
        {"default_run_id": "../foreign"},
        {"default_session_id": None},
        {"source_kind": []},
    ],
)
def test_invalid_scene_fields_are_isolated_from_healthy_cards(library, change):
    records = register_three(library)
    scene_id = records[0]["scene_id"]
    path = library._scene_path(scene_id)
    value = json.loads(path.read_text()) | change
    path.write_text(json.dumps(value))
    with pytest.raises(ValueError):
        library.get(scene_id)
    result = library.list()
    assert {item["scene_id"] for item in result["scenes"]} == {
        record["scene_id"] for record in records[1:]
    }
    assert result["issues"] == [{"scene_id": scene_id, "status": "record_unavailable"}]


@pytest.mark.parametrize(
    "date",
    [
        "2026-10-03T00:00:00+00:00",
        "2026-10-03T00:00:00Z",
        "2026-10-03T03:00:00.123456+03:00",
        "2026-10-02T19:30:00.123-04:30",
    ],
)
def test_calendar_timestamps_with_timezones_remain_usable(library, date):
    record = register_three(library)[0]
    path = library._scene_path(record["scene_id"])
    value = json.loads(path.read_text())
    # Keep the actual timestamp() output for created_at while varying the timezone shape.
    value["updated_at"] = date
    path.write_text(json.dumps(value))
    recovered = library.get(record["scene_id"])
    assert recovered["created_at"] == value["created_at"]
    assert recovered["updated_at"] == date
    result = library.list()
    assert len(result["scenes"]) == 3 and result["issues"] == []


@pytest.mark.parametrize("previous", [[], None, {"schema_version": "0.1", "name": None}])
def test_invalid_recovery_copy_is_never_published(library, previous):
    records = register_three(library)
    path = library._scene_path(records[0]["scene_id"])
    path.write_text("{")
    path.with_suffix(".previous").write_text(json.dumps(previous))
    with pytest.raises(ValueError):
        library.get(records[0]["scene_id"])
    assert path.read_text() == "{"
    assert library.recovery == []
    assert len(library.list()["scenes"]) == 2


def test_semantically_invalid_current_record_recovers_valid_backup(library):
    record = register_three(library)[0]
    scene_id = record["scene_id"]
    library.patch(scene_id, {"name": "New name"})
    path = library._scene_path(scene_id)
    current = json.loads(path.read_text()) | {"name": None}
    path.write_text(json.dumps(current))
    recovered = library.get(scene_id)
    assert recovered["name"] == "Same display name"
    assert json.loads(path.read_text()) == recovered
    assert library.recovery == [scene_id]


@pytest.mark.parametrize(
    "change",
    [
        {"session_ids": None},
        {"session_ids": [{}]},
        {"hashes": []},
        {"hashes": {"scene.json": None}},
        {"source_root": None},
        {"source_manifest": "relative.json"},
        {"source_label": None},
        {"scale_label": []},
        {"thumbnail": []},
        {"run_id": "run_invalid"},
    ],
)
def test_invalid_run_structures_and_backups_are_isolated(library, change):
    records = register_three(library)
    record = records[0]
    run = library.run(record["scene_id"], record["default_run_id"])
    path = (
        library._scene_path(record["scene_id"]).parent
        / "runs"
        / record["default_run_id"]
        / "run.json"
    )
    path.write_text(json.dumps(run | change))
    path.with_suffix(".previous").write_text("[]")
    with pytest.raises(ValueError):
        library.run(record["scene_id"], record["default_run_id"])
    assert json.loads(path.read_text()) == run | change
    assert len(library.list()["scenes"]) == 2
    # A complete valid backup remains usable even when the current JSON is well formed.
    path.with_suffix(".previous").write_text(json.dumps(run))
    assert library.run(record["scene_id"], record["default_run_id"]) == run
    assert len(library.list()["scenes"]) == 3


def test_record_validation_preserves_unknown_future_fields(library):
    record = register_three(library)[0]
    path = library._scene_path(record["scene_id"])
    value = json.loads(path.read_text()) | {"future_upload": {"unimplemented": None}}
    path.write_text(json.dumps(value))
    assert library.get(record["scene_id"])["future_upload"] == {"unimplemented": None}
    assert len(library.list()["scenes"]) == 3


def test_owner_and_path_and_session_boundaries(library):
    with pytest.raises(ValueError, match="owner"):
        LibraryStore(library.config)
    records = register_three(library)
    a, b = records[:2]
    with pytest.raises(ValueError):
        library.get("../outside")
    with pytest.raises((ValueError, OSError)):
        library.workspace(a["scene_id"], b["default_run_id"], b["default_session_id"])
    with pytest.raises(ValueError, match="Session"):
        library.workspace(a["scene_id"], a["default_run_id"], b["default_session_id"])
    with pytest.raises(ValueError):
        library.import_scene("/etc/passwd", "Invalid")


def test_source_move_locate_hashes_and_read_only_originals(library):
    record = register_three(library)[0]
    run = library.run(record["scene_id"], record["default_run_id"])
    original = Path(run["source_root"])
    snapshot = {p.name: p.read_bytes() for p in original.iterdir()}
    library.patch(record["scene_id"], {"name": "New name"})
    assert snapshot == {p.name: p.read_bytes() for p in original.iterdir()}
    moved = original.with_name("moved")
    shutil.move(original, moved)
    assert library.list()["scenes"][0]["status"] in {"ready", "source_unavailable"}
    assert library.summary(library.get(record["scene_id"]))["status"] == "source_unavailable"
    choices = library.discover()["scenes"]
    wrong = next(c for c in choices if c["label"] != "moved")
    with pytest.raises(ValueError, match="hashes"):
        library.locate(record["scene_id"], wrong["choice_id"])
    choice = next(c for c in choices if c["label"] == "moved")
    assert library.locate(record["scene_id"], choice["choice_id"])["status"] == "ready"
    run = library.run(record["scene_id"], record["default_run_id"])
    library.validate_source(run)
    (moved / "photo.jpg").write_bytes(b"changed photo")
    with pytest.raises(ValueError, match="changed"):
        library.validate_source(run)


def test_default_version_rejects_foreign_identity_and_discovery_confinement(library, tmp_path):
    records = register_three(library)
    with pytest.raises(ValueError, match="version"):
        library.patch(
            records[0]["scene_id"], {"default_version_id": records[1]["default_version_id"]}
        )
    outside = make_scene(tmp_path / "outside")
    (library.roots[0] / "escape").symlink_to(outside, target_is_directory=True)
    assert len(library.discover()["scenes"]) == 3
    assert "source_root" not in json.dumps(library.list())


def test_service_cache_preserves_leases_and_bounds():
    class FakeService:
        closed = False

        def close(self):
            self.closed = True

    cache = ServiceCache(1)
    with cache.acquire("first", FakeService) as first:
        with pytest.raises(ValueError, match="busy"), cache.acquire("second", FakeService):
            pass
        assert not first.closed
    with cache.acquire("second", FakeService):
        assert first.closed
        assert len(cache.entries) == 1
    cache.close()


def test_forged_mapping_is_rejected_without_importing_measurements(library):
    workspace = library.roots[0] / "old-workspace"
    workspace.mkdir()
    (workspace / "pixel-provenance.json").write_text(json.dumps({"schema_version": "0.1"}))
    (workspace / "measurements.json").write_text('{"old": true}')
    choices = library.discover()
    with pytest.raises(ValueError, match="hashes"):
        library.import_scene(
            choices["scenes"][0]["choice_id"],
            "Invalid mapping",
            choices["workspaces"][0]["choice_id"],
        )
    assert library.list()["scenes"] == []


def make_mapping(root, source):
    root.mkdir()
    proof = root / "ordering-proof.txt"
    proof.write_text("Synthetic test fixture: two points in row-major grid order")
    scene = SceneReader(source).read()
    mapping = {
        "schema_version": "0.1",
        "manifest_sha256": scene.manifest_sha256,
        "point_cloud_sha256": scene.point_cloud_sha256,
        "grid_width": 2,
        "grid_height": 1,
        "point_stride": 1,
        "ordering": "frame_then_row_major",
        "ordering_verification": "raw_grid_comparison",
        "evidence_files": [{"source_path": str(proof), "source_sha256": sha256_file(proof)}],
        "pixel_transforms": [PixelTransform(3, 2, 1, 2, 1, (0, 0, 2, 1), "derived").to_dict()],
    }
    (root / "pixel-provenance.json").write_text(json.dumps(mapping))
    (root / "measurements.json").write_text('{"historical": true}')
    return proof


def test_verified_mapping_only_enters_fresh_session(library):
    source = library.roots[0] / "0/same-name"
    make_mapping(library.roots[0] / "old-workspace", source)
    choices = library.discover()
    choice = next(key for key, path in library._choices.items() if path == source / "scene.json")
    record = library.import_scene(choice, "Mapped synthetic", choices["workspaces"][0]["choice_id"])
    workspace = library.workspace(
        record["scene_id"], record["default_run_id"], record["default_session_id"]
    )
    assert {p.name for p in workspace.iterdir()} == {"pixel-provenance.json"}
    from twinforge.viewer.service import SceneService

    service = SceneService(SceneReader(source).read(), workspace)
    assert service.metadata()["pixel_provenance_available"]
    assert service.measurements.list_ids() == []
    service.close()
