"""Linux session ownership checks; stale PIDs are never sufficient to signal a worker."""

import os
import signal
import time
from pathlib import Path


def process_info(pid: int) -> dict | None:
    if type(pid) is not int or pid <= 0:
        return None
    try:
        fields = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()
        if fields[0] == "Z":
            return None
        return {"pid": pid, "group": int(fields[2]), "session": int(fields[3]), "birth": fields[19]}
    except (OSError, ValueError, IndexError):
        return None


def group_alive(group: int) -> bool:
    for path in Path("/proc").iterdir():
        if path.name.isdecimal():
            info = process_info(int(path.name))
            if info and info["group"] == group and info["session"] == group:
                return True
    return False


def verified_owner(owner: dict, arguments: list[str]) -> bool:
    info = process_info(owner.get("pid"))
    if info != owner.get("process") or not info:
        return False
    if info["group"] != info["pid"] or info["session"] != info["pid"]:
        return False
    try:
        command = Path(f"/proc/{info['pid']}/cmdline").read_bytes().split(b"\0")[:-1]
        return command == [os.fsencode(value) for value in arguments]
    except OSError:
        return False


def terminate_group(group: int, process=None) -> None:
    """Caller must hold live Popen ownership or have just verified the full orphan identity."""
    for sig, seconds in ((signal.SIGTERM, 1.0), (signal.SIGKILL, 2.0)):
        if not group_alive(group):
            break
        try:
            os.killpg(group, sig)
        except ProcessLookupError:
            break
        deadline = time.monotonic() + seconds
        while group_alive(group) and time.monotonic() < deadline:
            time.sleep(0.02)
    if process is not None:
        process.wait(timeout=2)
    if group_alive(group):
        raise RuntimeError("Owned worker descendants have not stopped")
