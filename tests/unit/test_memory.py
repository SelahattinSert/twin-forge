import pytest

from twinforge.backends.base import DeviceMemory
from twinforge.cli import build_parser
from twinforge.config import MemoryConfig, TwinForgeConfig
from twinforge.reconstruction.memory import plan_frame_budget


def test_default_cli_is_automatic_not_eighty():
    assert build_parser().parse_args(["reconstruct", "room.mp4"]).max_keyframes is None
    assert TwinForgeConfig().keyframes.maximum_keyframes is None
    assert (
        build_parser()
        .parse_args(["reconstruct", "room.mp4", "--max-keyframes", "80"])
        .max_keyframes
        == 80
    )


def test_cuda_budget_uses_free_memory_and_preserves_minimum():
    info = DeviceMemory("cuda:0", 800 * 1024**2, 6 * 1024**3)
    plan = plan_frame_budget(info, MemoryConfig(), 80, 80, 3)
    assert plan["used_keyframes"] == 3
    assert plan["reason"] == "memory_budget"
    assert plan["policy"]["is_peak_memory_estimate"] is False
    assert (
        plan_frame_budget(DeviceMemory("cuda", 1, 6 * 1024**3), MemoryConfig(), None, 8, 3)[
            "used_keyframes"
        ]
        == 3
    )


def test_cpu_unknown_and_disabled_policy():
    for device in ("cpu", "unknown", "cuda"):
        assert (
            plan_frame_budget(DeviceMemory(device), MemoryConfig(), None, 80, 3)["used_keyframes"]
            == 32
        )
    assert (
        plan_frame_budget(DeviceMemory("cuda", 1), MemoryConfig(auto_budget=False), 8, 8, 3)[
            "used_keyframes"
        ]
        == 8
    )


@pytest.mark.parametrize(
    "settings",
    [
        MemoryConfig(maximum_oom_retries=-1),
        MemoryConfig(cuda_free_memory_fraction=0),
        MemoryConfig(cuda_bytes_per_frame=0),
        MemoryConfig(fallback_maximum_keyframes=0),
    ],
)
def test_invalid_memory_configuration(settings):
    with pytest.raises(ValueError):
        TwinForgeConfig(memory=settings).validate()
