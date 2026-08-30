#!/usr/bin/env python3
"""Deterministic identity and state helpers for the MCO supplement fast lane."""

from __future__ import annotations

import csv
import hashlib
import json
import os
import re
import tempfile
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SCHEMA_VERSION = "1.0"
ROOT_CONTROL = "_MIRROR CONTROL"
JOB_CONTROL = "00 MIRROR CONTROL"
JOB_SOURCE = "01 JOBNIMBUS SOURCE"
JOB_WORKING = "02 LOCAL WORKING FILES"


class FastLaneError(RuntimeError):
    """Base error for deterministic fast-lane operations."""


class DriveUnavailableError(FastLaneError):
    """Raised when the mirror root is missing or structurally unavailable."""


class IdentityConflictError(FastLaneError):
    """Raised when source and control identity evidence disagree."""


class JobNotFoundError(FastLaneError):
    """Raised when a name query matches no approved local job."""


class AmbiguousIdentityError(FastLaneError):
    """Raised when a name query leaves more than one exact job candidate."""

    def __init__(self, query: str, candidates: list[dict[str, Any]]) -> None:
        self.query = query
        self.candidates = candidates
        rendered = "; ".join(
            f"#{item['job_number']} {item['job_name']} — {item['exact_address']}"
            for item in candidates
        )
        super().__init__(f"Ambiguous job name {query!r}: {rendered}")


class StateTransitionError(FastLaneError):
    """Raised when a caller attempts to skip a required fast-lane phase."""


TRANSITIONS = {
    "NAME_RECEIVED": {"IDENTITY_LOCKED", "AMBIGUOUS_IDENTITY"},
    "IDENTITY_LOCKED": {"LOCAL_READY", "SOURCE_INCOMPLETE"},
    "LOCAL_READY": {"DELTA_CHECKED", "SOURCE_CHANGED"},
    "DELTA_CHECKED": {"SCOPE_AUDITED", "SOURCE_CHANGED"},
    "SCOPE_AUDITED": {"SCOPE_APPROVED", "ACTION_NEEDED_FROM_HOUSTON"},
    "SCOPE_APPROVED": {"PRICING_READY"},
    "PRICING_READY": {"XACTIMATE_EXPORTED", "XACTIMATE_BLOCKED"},
    "XACTIMATE_EXPORTED": {"VERIFIED"},
    "SOURCE_INCOMPLETE": {"LOCAL_READY"},
    "SOURCE_CHANGED": {"LOCAL_READY"},
    "ACTION_NEEDED_FROM_HOUSTON": {"SCOPE_AUDITED"},
    "XACTIMATE_BLOCKED": {"PRICING_READY"},
}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise IdentityConflictError(f"Required source record is missing: {path}") from exc
    except json.JSONDecodeError as exc:
        raise IdentityConflictError(f"Required source record is invalid JSON: {path}") from exc
    if not isinstance(value, dict):
        raise IdentityConflictError(f"Required source record is not a JSON object: {path}")
    return value


def _read_optional_json(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _atomic_json_write(path: Path, value: Any) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = (json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n").encode("utf-8")
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()
    return path


def normalize_name(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value or "")
    ascii_text = "".join(character for character in decomposed if not unicodedata.combining(character))
    return " ".join(re.findall(r"[a-z0-9]+", ascii_text.casefold()))


def _normalize_street(value: str) -> str:
    first_segment = (value or "").split(",", 1)[0]
    return normalize_name(first_segment)


def _five_digit_zip(value: Any) -> str:
    match = re.search(r"\b(\d{5})\b", str(value or ""))
    return match.group(1) if match else ""


def _source_address(record: dict[str, Any]) -> tuple[str, str]:
    street = str(record.get("address_line1") or "").strip()
    unit = str(record.get("address_line2") or "").strip()
    city = str(record.get("city") or "").strip()
    state = str(record.get("state_text") or "").strip()
    zip_code = _five_digit_zip(record.get("zip"))
    street_with_unit = ", ".join(part for part in (street, unit) if part)
    locality = " ".join(part for part in (state, zip_code) if part)
    address = ", ".join(part for part in (street_with_unit, city, locality) if part)
    return address, zip_code


def _verification_state(path: Path) -> tuple[str, bool]:
    if not path.is_file():
        return "MISSING", False
    text = path.read_text(encoding="utf-8", errors="replace")
    match = re.search(r"\*\*Status:\*\*\s*([^\n]+)", text, flags=re.IGNORECASE)
    label = match.group(1).strip() if match else "UNKNOWN"
    normalized = label.casefold()
    fully_verified = "verified" in normalized and "pending" not in normalized
    return label, fully_verified


def _approved_roster(root: Path) -> dict[str, dict[str, str]]:
    path = root / ROOT_CONTROL / "approved-jobs.csv"
    if not path.is_file():
        raise DriveUnavailableError(f"Mirror roster is missing: {path}")
    with path.open("r", encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    approved: dict[str, dict[str, str]] = {}
    for row in rows:
        if (row.get("decision") or "").strip().casefold() != "approved":
            continue
        number = (row.get("job_number") or "").strip()
        if not number:
            raise IdentityConflictError(f"Approved roster row lacks a job number in {path}")
        if number in approved:
            raise IdentityConflictError(f"Approved roster repeats job number {number}")
        approved[number] = row
    return approved


def _aliases(job: dict[str, Any], contact: dict[str, Any], roster: dict[str, str]) -> list[str]:
    values = {
        str(job.get("name") or ""),
        str(contact.get("display_name") or ""),
        " ".join(
            part for part in (
                str(contact.get("first_name") or "").strip(),
                str(contact.get("last_name") or "").strip(),
            )
            if part
        ),
        str(roster.get("job_name") or ""),
    }
    return sorted({normalized for value in values if (normalized := normalize_name(value))})


def build_index(mirror_root: Path) -> dict[str, Any]:
    root = Path(mirror_root).expanduser()
    if not root.is_dir():
        raise DriveUnavailableError(f"Mirror root is unavailable: {root}")
    if not (root / ROOT_CONTROL).is_dir():
        raise DriveUnavailableError(f"Mirror control directory is unavailable: {root / ROOT_CONTROL}")

    roster = _approved_roster(root)
    indexed: dict[str, dict[str, Any]] = {}
    for folder in sorted(root.iterdir(), key=lambda item: item.name.casefold()):
        if not folder.is_dir() or folder.name.startswith("_"):
            continue
        record_dir = folder / JOB_SOURCE / "Record"
        job_path = record_dir / "jobnimbus-job.json"
        contact_path = record_dir / "jobnimbus-contact.json"
        if not job_path.is_file():
            continue
        job = _read_json(job_path)
        number = str(job.get("number") or "").strip()
        if number not in roster:
            continue
        if number in indexed:
            raise IdentityConflictError(f"Multiple mirror folders claim approved job number {number}")
        contact = _read_json(contact_path)
        job_id = str(job.get("jnid") or "").strip()
        contact_id = str(contact.get("jnid") or "").strip()
        if not job_id or not contact_id:
            raise IdentityConflictError(f"Job #{number} lacks immutable job/contact identity")

        job_address, job_zip = _source_address(job)
        contact_address, contact_zip = _source_address(contact)
        if str(job.get("address_line1") or "").strip():
            exact_address, zip_code, address_authority = job_address, job_zip, "job-source"
        else:
            exact_address, zip_code, address_authority = contact_address, contact_zip, "contact-derived"

        roster_row = roster[number]
        roster_address = str(roster_row.get("exact_address") or "").strip()
        roster_street = _normalize_street(roster_address)
        source_street = _normalize_street(exact_address)
        missing_roster_address = "missing" in roster_address.casefold()
        if roster_street and source_street and not missing_roster_address and roster_street != source_street:
            raise IdentityConflictError(
                f"Job #{number} street conflicts: roster={roster_address!r}, source={exact_address!r}"
            )
        roster_zip = _five_digit_zip(roster_address)
        if roster_zip and zip_code and roster_zip != zip_code:
            raise IdentityConflictError(
                f"Job #{number} ZIP conflicts: roster={roster_zip}, source={zip_code}"
            )

        verification_path = folder / JOB_CONTROL / "verification.md"
        verification_label, fully_verified = _verification_state(verification_path)
        job_name = str(job.get("name") or roster_row.get("job_name") or contact.get("display_name") or "").strip()
        if not job_name:
            raise IdentityConflictError(f"Job #{number} lacks an approved display name")

        indexed[number] = {
            "job_name": job_name,
            "job_number": number,
            "job_id": job_id,
            "contact_id": contact_id,
            "exact_address": exact_address,
            "zip": zip_code,
            "address_authority": address_authority,
            "pricing_identity_ready": bool(exact_address and zip_code),
            "normalized_aliases": _aliases(job, contact, roster_row),
            "folder_path": str(folder.resolve()),
            "job_source_path": str(job_path.resolve()),
            "contact_source_path": str(contact_path.resolve()),
            "source_manifest_path": str((folder / JOB_CONTROL / "source-manifest.csv").resolve()),
            "verification_path": str(verification_path.resolve()),
            "verification_state": verification_label,
            "fully_verified": fully_verified,
            "captured_remote_metadata": {
                "date_updated": job.get("date_updated"),
                "attachment_count": job.get("attachment_count"),
                "status_name": job.get("status_name"),
                "claim_number": job.get("Claim #"),
                "insurance_company": job.get("Insurance Company"),
            },
        }

    missing_numbers = sorted(set(roster) - set(indexed), key=lambda value: int(value))
    if missing_numbers:
        raise IdentityConflictError(
            "Approved job(s) missing or conflicting in mirror: " + ", ".join(missing_numbers)
        )

    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": _utc_now(),
        "mirror_root": str(root.resolve()),
        "job_count": len(indexed),
        "jobs": [indexed[number] for number in sorted(indexed, key=lambda value: int(value))],
    }


def resolve_job(index: dict[str, Any], query: str) -> dict[str, Any]:
    needle = normalize_name(query)
    if not needle:
        raise JobNotFoundError("Job name is blank")
    jobs = [item for item in index.get("jobs", []) if isinstance(item, dict)]
    exact = [item for item in jobs if needle in item.get("normalized_aliases", [])]
    if exact:
        candidates = exact
    else:
        tokens = set(needle.split())
        candidates = [
            item
            for item in jobs
            if any(tokens.issubset(set(alias.split())) for alias in item.get("normalized_aliases", []))
        ]
    if not candidates:
        raise JobNotFoundError(f"No approved mirror job matches {query!r}")
    if len(candidates) != 1:
        raise AmbiguousIdentityError(query, candidates)
    return candidates[0]


def write_index(index: dict[str, Any], mirror_root: Path) -> Path:
    root = Path(mirror_root).expanduser()
    control = root / ROOT_CONTROL
    if not control.is_dir():
        raise DriveUnavailableError(f"Mirror control directory is unavailable: {control}")
    output = control / "fast-job-index.json"
    _atomic_json_write(output, index)
    index_bytes = output.read_bytes()
    state = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": index.get("generated_at"),
        "job_count": index.get("job_count"),
        "index_sha256": hashlib.sha256(index_bytes).hexdigest(),
        "index_path": str(output.resolve()),
    }
    _atomic_json_write(control / "fast-job-index-state.json", state)
    return output


def fingerprint_job(job: dict[str, Any]) -> dict[str, Any]:
    input_paths = {
        "job_source": Path(str(job["job_source_path"])),
        "contact_source": Path(str(job["contact_source_path"])),
        "source_manifest": Path(str(job["source_manifest_path"])),
        "verification": Path(str(job["verification_path"])),
    }
    inputs: dict[str, dict[str, Any]] = {}
    combined = hashlib.sha256()
    combined.update(f"mco-supplement-fast-lane:{SCHEMA_VERSION}\n".encode("utf-8"))
    for label in sorted(input_paths):
        path = input_paths[label]
        if not path.is_file():
            raise IdentityConflictError(f"Fingerprint input is missing: {path}")
        digest = _sha256_file(path)
        size = path.stat().st_size
        inputs[label] = {
            "path": str(path.resolve()),
            "byte_size": size,
            "sha256": digest,
        }
        combined.update(f"{label}\0{digest}\0{size}\n".encode("utf-8"))
    return {
        "schema_version": SCHEMA_VERSION,
        "job_id": job["job_id"],
        "inputs": inputs,
        "source_fingerprint": combined.hexdigest(),
    }


def transition_state(
    run_state: dict[str, Any],
    target: str,
    *,
    reason: str,
    now: str | None = None,
) -> dict[str, Any]:
    current = str(run_state.get("state") or "")
    if target not in TRANSITIONS.get(current, set()):
        raise StateTransitionError(f"Fast-lane state cannot move from {current!r} to {target!r}")
    moved = json.loads(json.dumps(run_state))
    moved.setdefault("history", []).append(
        {
            "from": current,
            "to": target,
            "reason": reason,
            "at": now or _utc_now(),
        }
    )
    moved["state"] = target
    moved["updated_at"] = now or _utc_now()
    return moved


def _job_context(job: dict[str, Any], prepared_at: str) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "prepared_at": prepared_at,
        "job_name": job["job_name"],
        "job_number": job["job_number"],
        "job_id": job["job_id"],
        "contact_id": job["contact_id"],
        "exact_address": job["exact_address"],
        "zip": job["zip"],
        "address_authority": job["address_authority"],
        "pricing_identity_ready": job["pricing_identity_ready"],
        "folder_path": job["folder_path"],
        "verification_state": job["verification_state"],
        "fully_verified": job["fully_verified"],
        "captured_remote_metadata": job["captured_remote_metadata"],
        "authority": {
            "identity": "JobNimbus source JSON plus mirror control",
            "source": "01 JOBNIMBUS SOURCE",
            "generated_work": "02 LOCAL WORKING FILES/00 FAST LANE",
        },
    }


def prepare_job(
    job: dict[str, Any],
    *,
    now: str | None = None,
) -> dict[str, Any]:
    prepared_at = now or _utc_now()
    working = Path(str(job["folder_path"])) / JOB_WORKING / "00 FAST LANE"
    fingerprint_path = working / "source-fingerprint.json"
    run_state_path = working / "run-state.json"
    existing_fingerprint = _read_optional_json(fingerprint_path)
    existing_state = _read_optional_json(run_state_path)
    current_fingerprint = fingerprint_job(job)
    cache_hit = bool(
        existing_fingerprint
        and existing_fingerprint.get("source_fingerprint")
        == current_fingerprint["source_fingerprint"]
    )

    stale_candidates = (
        "evidence-index.json",
        "carrier-scope.json",
        "scope-gap.json",
        "xactimate-entry-manifest.json",
    )
    stale_artifacts = [name for name in stale_candidates if (working / name).exists()]
    blockers: list[str] = []
    if not job.get("fully_verified"):
        state = "SOURCE_INCOMPLETE"
        blockers.append("mirror verification is incomplete")
    elif existing_fingerprint and not cache_hit:
        state = "SOURCE_CHANGED"
        blockers.append("authoritative local source fingerprint changed")
    elif cache_hit and existing_state and existing_state.get("state"):
        state = str(existing_state["state"])
        blockers = list(existing_state.get("blockers") or [])
        stale_artifacts = list(existing_state.get("stale_artifacts") or [])
    else:
        state = "LOCAL_READY"

    history = list((existing_state or {}).get("history") or [])
    previous_state = (existing_state or {}).get("state")
    if previous_state and previous_state != state:
        history.append(
            {
                "from": previous_state,
                "to": state,
                "reason": "prepare recalculated source and verification state",
                "at": prepared_at,
            }
        )
    run_state = {
        "schema_version": SCHEMA_VERSION,
        "job_id": job["job_id"],
        "source_fingerprint": current_fingerprint["source_fingerprint"],
        "state": state,
        "cache_hit": cache_hit,
        "blockers": blockers,
        "stale_artifacts": stale_artifacts if state == "SOURCE_CHANGED" else [],
        "updated_at": prepared_at,
        "history": history,
    }

    _atomic_json_write(working / "job-context.json", _job_context(job, prepared_at))
    _atomic_json_write(fingerprint_path, current_fingerprint)
    _atomic_json_write(run_state_path, run_state)
    return run_state
