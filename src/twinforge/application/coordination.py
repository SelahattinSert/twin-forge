"""One inherited heavy-operation lock, shared by setup and reconstruction."""

import fcntl
import threading
from pathlib import Path


class HeavySlot:
    def __init__(self, root: Path):
        self.path = root / "runtime/heavy-operation.lock"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self._file = None
        self.ownership_unresolved = False

    def busy(self) -> bool:
        with self.lock:
            if self._file is not None:
                return True
            stream = self.path.open("a+b")
            try:
                try:
                    fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError:
                    return True
                return False
            finally:
                stream.close()

    def acquire(self) -> int:
        with self.lock:
            if self.ownership_unresolved:
                raise ValueError("Previous heavy worker ownership is unresolved")
            if self._file is not None:
                raise ValueError("Another heavy operation owns the library")
            stream = self.path.open("a+b")
            try:
                fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                stream.close()
                raise ValueError("A surviving heavy worker owns the library") from None
            self._file = stream
            return stream.fileno()

    def release(self) -> None:
        with self.lock:
            if self._file is not None:
                # Never LOCK_UN: a surviving inherited descriptor must keep ownership.
                self._file.close()
                self._file = None
