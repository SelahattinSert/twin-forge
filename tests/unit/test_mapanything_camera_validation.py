import numpy as np
import pytest
from test_mapanything_outputs import normalize, prediction

from twinforge.exceptions import ReconstructionFailedError


@pytest.mark.parametrize(
    "field,value",
    [
        ("intrinsics", np.full((1, 3, 3), np.inf)),
        ("intrinsics", np.zeros((1, 3, 3))),
        ("camera_poses", np.full((1, 4, 4), np.nan)),
        ("camera_poses", np.zeros((1, 4, 4))),
        ("camera_poses", np.diag([2, 1, 1, 1])[None]),
        ("metric_scaling_factor", np.array([-1.0])),
    ],
)
def test_invalid_camera_and_metric_fields_fail_before_export(field, value):
    data = prediction()
    data[field] = value
    with pytest.raises(ReconstructionFailedError, match=field):
        normalize([data])


def test_real_backend_scale_shape_batch_one_channel_one():
    data = prediction()
    data["metric_scaling_factor"] = np.array([[5.0]], dtype=np.float32)
    result = normalize([data])
    assert result.scale.details["metric_scaling_factor_values"] == [5.0]
    np.testing.assert_allclose(result.points.xyz[0], [1, 3, -2])
