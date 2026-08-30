#!/usr/bin/env python3
"""Command-line entry point for the MCO supplement fast lane."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import fast_lane_core as core


DEFAULT_MIRROR_ROOT = Path("/Volumes/SONY 2TB/MCO JobNimbus Mirror")
DEFAULT_JOBNIMBUS_SCRIPT = Path(
    "/Users/HoustonMeerdink_1/.codex/skills/mco-jobnimbus-read/scripts/jobnimbus_read.py"
)


class JobNimbusBridgeError(core.FastLaneError):
    """Raised when the existing read-only JobNimbus CLI cannot return JSON."""


def run_jobnimbus_find(job_name: str, script_path: Path) -> list[dict[str, Any]]:
    script = Path(script_path).expanduser()
    if not script.is_file():
        raise JobNimbusBridgeError(f"JobNimbus read script is unavailable: {script}")
    command = [
        sys.executable,
        str(script),
        "find",
        "jobs",
        job_name,
        "--max-scan",
        "500",
    ]
    try:
        completed = subprocess.run(
            command,
            text=True,
            capture_output=True,
            check=False,
            timeout=60,
        )
    except subprocess.TimeoutExpired as exc:
        raise JobNimbusBridgeError("JobNimbus read-only name lookup timed out") from exc
    if completed.returncode != 0:
        detail = completed.stderr.strip().splitlines()[-1] if completed.stderr.strip() else "unknown error"
        raise JobNimbusBridgeError(f"JobNimbus read-only name lookup failed: {detail}")
    try:
        value = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise JobNimbusBridgeError("JobNimbus read-only name lookup returned invalid JSON") from exc
    if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
        raise JobNimbusBridgeError("JobNimbus read-only name lookup returned an unexpected structure")
    return value


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="MCO supplement fast-lane coordinator")
    subparsers = parser.add_subparsers(dest="command", required=True)
    live = subparsers.add_parser("live-check", help="Resolve one name and compare exact live JobNimbus metadata")
    live.add_argument("job_name")
    live.add_argument("--mirror-root", type=Path, default=DEFAULT_MIRROR_ROOT)
    live.add_argument("--jobnimbus-script", type=Path, default=DEFAULT_JOBNIMBUS_SCRIPT)
    return parser


def _error_payload(error: Exception) -> tuple[dict[str, Any], int]:
    if isinstance(error, core.AmbiguousIdentityError):
        return {
            "state": "AMBIGUOUS_IDENTITY",
            "error": str(error),
            "candidates": error.candidates,
        }, 3
    if isinstance(error, core.DriveUnavailableError):
        return {"state": "DRIVE_UNAVAILABLE", "error": str(error)}, 4
    if isinstance(error, (core.IdentityConflictError, core.JobNotFoundError)):
        return {"state": "IDENTITY_BLOCKED", "error": str(error)}, 4
    return {"state": "ERROR", "error": str(error)}, 2


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "live-check":
            index = core.build_index(args.mirror_root)
            job = core.resolve_job(index, args.job_name)
            core.prepare_job(job)
            live_records = run_jobnimbus_find(args.job_name, args.jobnimbus_script)
            delta = core.compare_live_job(job, live_records)
            state = core.record_live_delta(job, delta)
            payload = dict(delta)
            payload["state"] = state["state"]
            payload["blockers"] = state.get("blockers", [])
            print(json.dumps(payload, indent=2, sort_keys=True))
            return 0 if state["state"] == "DELTA_CHECKED" else 4
        raise JobNimbusBridgeError(f"Unsupported command: {args.command}")
    except (core.FastLaneError, OSError) as exc:
        payload, exit_code = _error_payload(exc)
        print(json.dumps(payload, indent=2, sort_keys=True))
        return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
