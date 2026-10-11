"""Optional backend-neutral progress; counts describe known work, never inferred percentages."""

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any


@dataclass(frozen=True)
class ProgressEvent:
    stage: str
    sequence: int
    timestamp: str
    message_code: str
    completed: int | None = None
    total: int | None = None
    details: dict[str, Any] = field(default_factory=dict)


class ProgressReporter:
    def __init__(self, callback: Callable[[ProgressEvent], None] | None = None):
        self.callback = callback
        self.sequence = 0
        self.stage = "inspecting"

    def emit(self, stage: str, message_code: str | None = None, **details) -> None:
        self.stage = stage
        self.sequence += 1
        if self.callback is not None:
            self.callback(
                ProgressEvent(
                    stage,
                    self.sequence,
                    datetime.now(UTC).isoformat(),
                    message_code or stage,
                    details=details,
                )
            )
