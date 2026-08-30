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

    index = subparsers.add_parser("index", help="Build the approved local mirror job index")
    index.add_argument("--mirror-root", type=Path, default=DEFAULT_MIRROR_ROOT)
    index.add_argument("--write", action="store_true", help="Persist generated root index files")

    for command, help_text in (
        ("resolve", "Resolve one job name to exact locked identity"),
        ("prepare", "Prepare or reuse one job's local fast-lane cache"),
        ("status", "Read one resolved job's current fast-lane state"),
    ):
        command_parser = subparsers.add_parser(command, help=help_text)
        command_parser.add_argument("job_name")
        command_parser.add_argument("--mirror-root", type=Path, default=DEFAULT_MIRROR_ROOT)

    live = subparsers.add_parser("live-check", help="Resolve one name and compare exact live JobNimbus metadata")
    live.add_argument("job_name")
    live.add_argument("--mirror-root", type=Path, default=DEFAULT_MIRROR_ROOT)
    live.add_argument("--jobnimbus-script", type=Path, default=DEFAULT_JOBNIMBUS_SCRIPT)

    audited = subparsers.add_parser("mark-audited", help="Persist a source-backed unpriced scope-gap audit")
    audited.add_argument("job_name")
    audited.add_argument("--mirror-root", type=Path, default=DEFAULT_MIRROR_ROOT)
    audited.add_argument("--scope-gap", type=Path, required=True)

    approval = subparsers.add_parser("approve-scope", help="Gate approved scope into an unpriced Xactimate manifest")
    approval.add_argument("job_name")
    approval.add_argument("--mirror-root", type=Path, default=DEFAULT_MIRROR_ROOT)
    approval.add_argument("--scope-gap", type=Path, required=True)
    approval.add_argument("--approved-by", required=True)
    approval.add_argument("--approved-at", required=True)
    approval.add_argument("--baseline-code", required=True)
    approval.add_argument("--baseline-month", required=True)
    approval.add_argument("--target-code", required=True)
    approval.add_argument("--target-month", required=True)
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


def _load_json_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise core.ScopeValidationError(f"JSON input is unavailable: {path}") from exc
    except json.JSONDecodeError as exc:
        raise core.ScopeValidationError(f"JSON input is invalid: {path}") from exc
    if not isinstance(value, dict):
        raise core.ScopeValidationError(f"JSON input must be an object: {path}")
    return value


def _resolved_job(job_name: str, mirror_root: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    index = core.build_index(mirror_root)
    return index, core.resolve_job(index, job_name)


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "index":
            index = core.build_index(args.mirror_root)
            if args.write:
                core.write_index(index, args.mirror_root)
            print(json.dumps(index, indent=2, sort_keys=True))
            return 0

        if args.command == "resolve":
            _index, job = _resolved_job(args.job_name, args.mirror_root)
            print(json.dumps(job, indent=2, sort_keys=True))
            return 0

        if args.command == "prepare":
            _index, job = _resolved_job(args.job_name, args.mirror_root)
            state = core.prepare_job(job)
            payload = {
                "job_name": job["job_name"],
                "job_number": job["job_number"],
                "job_id": job["job_id"],
                "contact_id": job["contact_id"],
                "exact_address": job["exact_address"],
                "zip": job["zip"],
                **state,
            }
            print(json.dumps(payload, indent=2, sort_keys=True))
            return 0 if state["state"] == "LOCAL_READY" else 4

        if args.command == "status":
            _index, job = _resolved_job(args.job_name, args.mirror_root)
            state = core.read_run_state(job)
            payload = {
                "job_name": job["job_name"],
                "job_number": job["job_number"],
                "job_id": job["job_id"],
                "exact_address": job["exact_address"],
                **state,
            }
            print(json.dumps(payload, indent=2, sort_keys=True))
            return 0

        if args.command == "live-check":
            _index, job = _resolved_job(args.job_name, args.mirror_root)
            core.prepare_job(job)
            live_records = run_jobnimbus_find(args.job_name, args.jobnimbus_script)
            delta = core.compare_live_job(job, live_records)
            state = core.record_live_delta(job, delta)
            payload = dict(delta)
            payload["state"] = state["state"]
            payload["blockers"] = state.get("blockers", [])
            print(json.dumps(payload, indent=2, sort_keys=True))
            return 0 if state["state"] == "DELTA_CHECKED" else 4

        if args.command == "mark-audited":
            _index, job = _resolved_job(args.job_name, args.mirror_root)
            scope_gap = _load_json_object(args.scope_gap)
            state = core.record_scope_audit(job, scope_gap)
            print(json.dumps(state, indent=2, sort_keys=True))
            return 0

        if args.command == "approve-scope":
            _index, job = _resolved_job(args.job_name, args.mirror_root)
            scope_gap = _load_json_object(args.scope_gap)
            manifest = core.approve_scope(
                scope_gap,
                job,
                approved_by=args.approved_by,
                approved_at=args.approved_at,
                baseline={"code": args.baseline_code, "month": args.baseline_month},
                target={"code": args.target_code, "month": args.target_month},
            )
            state = core.persist_pricing_manifest(job, manifest, now=args.approved_at)
            payload = {
                "job_id": job["job_id"],
                "state": state["state"],
                "xactimate_entry_manifest": state["xactimate_entry_manifest"],
                "requested_item_count": len(manifest["requested_items"]),
            }
            print(json.dumps(payload, indent=2, sort_keys=True))
            return 0
        raise JobNimbusBridgeError(f"Unsupported command: {args.command}")
    except (core.FastLaneError, OSError) as exc:
        payload, exit_code = _error_payload(exc)
        print(json.dumps(payload, indent=2, sort_keys=True))
        return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
