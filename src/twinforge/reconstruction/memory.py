"""Backend-neutral frame planning. Actual OOM, not this heuristic, is authoritative."""

from dataclasses import asdict
from typing import Any

from twinforge.backends.base import DeviceMemory
from twinforge.config import MemoryConfig


def plan_frame_budget(
    info: DeviceMemory,
    config: MemoryConfig,
    requested: int | None,
    available_count: int,
    minimum: int,
) -> dict[str, Any]:
    limit = min(requested, available_count) if requested is not None else available_count
    basis = "disabled"
    if config.auto_budget:
        if info.device.startswith("cuda") and info.free_bytes is not None:
            budget = int(
                info.free_bytes * config.cuda_free_memory_fraction / config.cuda_bytes_per_frame
            )
            basis = "free_cuda_memory_after_model_load"
        else:
            budget = config.fallback_maximum_keyframes
            basis = "fallback_cap_no_cuda_memory_measurement"
        limit = min(limit, max(minimum, budget))
    return {
        "requested_keyframes": available_count,
        "used_keyframes": limit,
        "reason": "memory_budget" if limit < available_count else None,
        "policy": {
            **asdict(config),
            "requested_upper_limit": requested,
            "basis": basis,
            "device_memory_after_model_load": asdict(info),
            "is_peak_memory_estimate": False,
        },
    }
