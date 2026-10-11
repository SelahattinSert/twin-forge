"""Executable synthetic worker for lifecycle tests; no production import or selectable mode."""

import argparse
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

# This fixture script is executed by an explicitly patched test argument builder only.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tests.job_support import successful_output
from twinforge.application.library import atomic_json
from twinforge.application.types import timestamp

parser = argparse.ArgumentParser()
parser.add_argument("--job", type=Path)
parser.add_argument("--nonce")
parser.add_argument("--slot-fd", type=int)
parser.add_argument("--mode", default="success")
args = parser.parse_args()
os.fstat(args.slot_fd)
job = json.loads(args.job.read_text())
base = args.job.parent
events = []
for stage in ("inspecting", "selecting_images", "loading_model", "reconstructing", "exporting"):
    events.append(
        {
            "sequence": len(events) + 1,
            "timestamp": timestamp(),
            "stage": stage,
            "message_code": stage,
            "details": {"selected_images": 1},
        }
    )
atomic_json(base / "progress.json", {"events": events}, backup=False)
if args.mode == "fast_events":
    events = [
        {
            "sequence": index + 1,
            "timestamp": timestamp(),
            "stage": "reconstructing",
            "message_code": "known_work",
            "completed": index + 1,
            "total": 400,
            "details": {},
        }
        for index in range(400)
    ]
    atomic_json(base / "progress.json", {"events": events[-128:]}, backup=False)
if args.mode in {"slow", "crash_child"}:
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
    child = subprocess.Popen(
        [
            sys.executable,
            "-c",
            "import signal,time; signal.signal(signal.SIGTERM,signal.SIG_IGN); time.sleep(60)",
        ]
    )
    atomic_json(base / "child.json", {"pid": child.pid})
    if args.mode == "crash_child":
        raise SystemExit(19)
    time.sleep(60)
if args.mode == "crash":
    raise SystemExit(19)
receipt = {key: job[key] for key in ("job_id", "run_id", "nonce", "config_sha256")}
if args.mode in {"oom", "decode_failure", "export_failure"}:
    receipt.update(state="failed", failure_type=args.mode, stage=args.mode)
    atomic_json(base / "receipt.json", receipt, backup=False)
    raise SystemExit(1)
output = successful_output(job, invalid="mapping" if args.mode == "invalid" else None)
receipt.update(state="complete", output_path=str(output))
if args.mode == "stale_receipt":
    receipt["nonce"] = "wrong nonce"
atomic_json(base / "receipt.json", receipt, backup=False)
