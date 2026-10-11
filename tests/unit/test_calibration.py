import importlib.util
from dataclasses import replace

import pytest

from twinforge.measurements.types import MeasurementObservation, MeasurementRecord


def control():
    items = tuple(
        MeasurementObservation(
            "door-width",
            "a" * 64,
            "b" * 64,
            i,
            str(i) * 64,
            (0, 1),
            ((0.0, 0.0, 0.0), (2.0, 0.0, 0.0)),
            True,
            "image_pick",
            "frozen",
            correspondence_state="identified",
            model_pixels=((0, 0), (2, 0)),
            pixel_provenance="native",
            sensitivity_span_ratio=0.01,
            sensitivity_complete=True,
        )
        for i in (1, 2)
    )
    return MeasurementRecord("door-width", "width", items)


def module():
    assert importlib.util.find_spec("twinforge.measurements.calibration"), "calibration missing"
    from twinforge.measurements import calibration

    return calibration


def test_freezes_control_and_converts_explicit_centimeters():
    fitted = module().fit_uniform_scale(control(), 82, "cm", original_scale={"type": "relative"})
    assert fitted.scalar == pytest.approx(0.41)
    assert fitted.physical_length_m == pytest.approx(0.82)
    assert fitted.measurement_tolerance_m is None
    assert fitted.observations == control().observations


def test_legacy_record_defaults_to_original_qualification_policy():
    from twinforge.measurements.consistency import DEFAULT_POLICY

    fitted = module().fit_uniform_scale(control(), 0.82, "m")
    payload = fitted.to_dict()
    payload.pop("qualification_policy", None)
    legacy = module().CalibrationRecord(**payload)
    assert legacy.qualification_policy == DEFAULT_POLICY


@pytest.mark.parametrize("value,unit", [(0, "m"), (-1, "m"), (float("nan"), "m"), (82, "mm")])
def test_invalid_physical_length(value, unit):
    with pytest.raises(ValueError):
        module().fit_uniform_scale(control(), value, unit)


def test_rejects_conflicting_control_before_fitting():
    record = control()
    other = replace(record.observations[1], xyz=((0.0, 0.0, 0.0), (3.0, 0.0, 0.0)))
    with pytest.raises(ValueError, match="qualified"):
        module().fit_uniform_scale(
            replace(record, observations=(record.observations[0], other)), 0.82, "m"
        )


def test_control_reference_binding_is_required():
    with pytest.raises(ValueError, match="reference"):
        module().fit_uniform_scale(replace(control(), reference_id="different"), 0.82, "m")


def test_store_calibration_requires_workspace_binding(tmp_path):
    from test_preview import artifact

    from twinforge.measurements.storage import MeasurementStore

    store = MeasurementStore(tmp_path / "workspace", artifact())
    fitted = module().fit_uniform_scale(control(), 0.82, "m")
    assert hasattr(store, "save_calibration"), "calibration persistence missing"
    store.save_calibration(fitted)
    import json

    assert json.loads((store.root / "calibration.json").read_text())["scalar"] == 0.41


def test_viewer_has_bounded_calibration_interface():
    from twinforge.viewer.server import ViewerServer

    assert hasattr(ViewerServer, "calibrate"), "viewer calibration interface missing"


def test_viewer_exposes_source_derived_and_control_excluded_checks():
    from twinforge.viewer.server import STATIC_ROOT

    html = (STATIC_ROOT / "index.html").read_text()
    script = (STATIC_ROOT / "app.js").read_text()
    presentation = (STATIC_ROOT / "workspace-ui.js").read_text()
    assert 'id="scene-variant"' in html, "source/derived toggle missing"
    assert 'id="calibrate"' in html, "calibration input missing"
    assert "/api/calibration" in script
    assert "/api/check-report" in script
    assert "formatCalibrationReport" in script
    assert "excluded_control_id" in presentation
