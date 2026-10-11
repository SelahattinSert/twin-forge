"""Backend boundary consumed by the reconstruction orchestrator."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

from twinforge.core.types import FrameObservation, ReconstructionResult


@dataclass(frozen=True)
class ReconstructionContext:
    device: str
    debug: bool = False


@dataclass(frozen=True)
class DeviceMemory:
    device: str
    free_bytes: int | None = None
    total_bytes: int | None = None


class ReconstructionBackend(ABC):
    """Interface that keeps backend tensors and conventions out of TwinForge core."""

    def prepare(self, context: ReconstructionContext) -> None:
        """Load models or runtime resources before reconstruction when required."""

    def close(self) -> None:
        """Release backend resources after a run when applicable."""

    def memory_info(self) -> DeviceMemory:
        """Report actual execution device and memory after preparation, if available."""
        return DeviceMemory("unknown")

    @abstractmethod
    def reconstruct(
        self,
        frames: list[FrameObservation],
        context: ReconstructionContext,
    ) -> ReconstructionResult:
        """Reconstruct the selected observations into normalized scene data."""
