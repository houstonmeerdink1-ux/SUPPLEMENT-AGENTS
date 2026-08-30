# Fast-Lane Data Contracts

These JSON files are generated working state. They do not replace JobNimbus source, the carrier PDF, the Xactimate export, or the mirror manifests.

## Authority order

1. Exact JobNimbus job/contact source JSON and job control records establish identity.
2. `01 JOBNIMBUS SOURCE` plus its manifest establishes captured evidence.
3. The qualifying carrier estimate establishes the paid baseline.
4. `scope-gap.json` records source-backed, unpriced supplement judgment.
5. `xactimate-entry-manifest.json` records only Houston-approved pricing inputs.
6. Xactimate and its verified export establish unit prices and priced totals.

All examples below are synthetic.

## `job-context.json`

```json
{
  "schema_version": "1.0",
  "prepared_at": "2026-08-30T12:00:00-05:00",
  "job_name": "Beta Homeowner",
  "job_number": "9003",
  "job_id": "job-beta",
  "contact_id": "contact-beta",
  "exact_address": "300 Main Street, Sample City, KS 66103",
  "zip": "66103",
  "address_authority": "job-source",
  "pricing_identity_ready": true,
  "folder_path": "/synthetic/mirror/Beta Homeowner - 300 Main Street",
  "verification_state": "VERIFIED LOCAL MIRROR",
  "fully_verified": true,
  "captured_remote_metadata": {
    "date_updated": 1788100003,
    "attachment_count": 1,
    "status_name": "Scope Received",
    "claim_number": "SYN-BETA",
    "insurance_company": null
  },
  "authority": {
    "identity": "JobNimbus source JSON plus mirror control",
    "source": "01 JOBNIMBUS SOURCE",
    "generated_work": "02 LOCAL WORKING FILES/00 FAST LANE"
  }
}
```

## `source-fingerprint.json`

The combined fingerprint changes when any compact authoritative input changes. It deliberately hashes the source manifest rather than opening every photo during every run.

```json
{
  "schema_version": "1.0",
  "job_id": "job-beta",
  "source_fingerprint": "64-character-sha256-value",
  "inputs": {
    "job_source": {
      "path": "/synthetic/jobnimbus-job.json",
      "byte_size": 300,
      "sha256": "64-character-sha256-value"
    },
    "contact_source": {
      "path": "/synthetic/jobnimbus-contact.json",
      "byte_size": 200,
      "sha256": "64-character-sha256-value"
    },
    "source_manifest": {
      "path": "/synthetic/source-manifest.csv",
      "byte_size": 500,
      "sha256": "64-character-sha256-value"
    },
    "verification": {
      "path": "/synthetic/verification.md",
      "byte_size": 150,
      "sha256": "64-character-sha256-value"
    }
  }
}
```

## `run-state.json`

```json
{
  "schema_version": "1.0",
  "job_id": "job-beta",
  "source_fingerprint": "64-character-sha256-value",
  "state": "DELTA_CHECKED",
  "cache_hit": true,
  "blockers": [],
  "stale_artifacts": [],
  "updated_at": "2026-08-30T12:01:00-05:00",
  "history": [
    {
      "from": "LOCAL_READY",
      "to": "DELTA_CHECKED",
      "reason": "exact live JobNimbus metadata matched",
      "at": "2026-08-30T12:01:00-05:00"
    }
  ],
  "last_live_delta": {
    "job_id": "job-beta",
    "state": "DELTA_CHECKED",
    "changed_fields": [],
    "snapshot_reusable": true,
    "attachment_completeness_proven": false
  }
}
```

An API aggregate never changes `attachment_completeness_proven` to true. Completeness comes from the individual job's authenticated UI/source reconciliation record.

## `scope-gap.json`

Create this through `mco-insurance-supplement` after reading the current qualifying carrier estimate page by page. Do not include unit prices, RCV, totals or invented quantities.

```json
{
  "schema_version": "1.0",
  "job_identity": {
    "job_id": "job-beta",
    "job_number": "9003",
    "exact_address": "300 Main Street, Sample City, KS 66103",
    "zip": "66103"
  },
  "approval_state": "HOUSTON_APPROVED",
  "approved_item_ids": [
    "ceiling-hall"
  ],
  "items": [
    {
      "item_id": "ceiling-hall",
      "status": "REQUESTED",
      "description": "Remove continuous ceiling finish and replace supported affected plane",
      "quantity": {
        "value": 120.0,
        "unit": "SF",
        "source": "synthetic-measurement#page-1"
      },
      "evidence": [
        {
          "source_id": "synthetic-photo-1",
          "source_path": "01 JOBNIMBUS SOURCE/Attachments/Photos/synthetic-photo-1.jpg",
          "supports": "open ceiling and continuous finish"
        }
      ],
      "carrier_credit": {
        "status": "EXISTING_ALLOWANCE",
        "line_reference": "carrier-line-12",
        "quantity": 10.0,
        "unit": "SF"
      },
      "unresolved_questions": []
    },
    {
      "item_id": "ceiling-bedroom",
      "status": "ACTION_NEEDED",
      "description": "Bedroom ceiling work pending exact dimensions",
      "quantity": null,
      "evidence": [],
      "carrier_credit": {
        "status": "UNKNOWN"
      },
      "unresolved_questions": [
        "Confirm exact affected ceiling area."
      ]
    }
  ]
}
```

Allowed working statuses are `PAID`, `REQUESTED`, `NOT_SUPPORTED`, and `ACTION_NEEDED`. Only `REQUESTED` items that Houston explicitly approved and that have supported quantities, evidence, carrier-credit treatment and no unresolved questions may reach pricing.

## `xactimate-entry-manifest.json`

The gate copies only approved unpriced items. Baseline and target list records remain separate.

```json
{
  "schema_version": "1.0",
  "state": "PRICING_READY",
  "job_identity": {
    "job_name": "Beta Homeowner",
    "job_number": "9003",
    "job_id": "job-beta",
    "contact_id": "contact-beta",
    "exact_address": "300 Main Street, Sample City, KS 66103",
    "zip": "66103"
  },
  "approved_by": "Houston",
  "approved_at": "2026-08-30T12:30:00-05:00",
  "carrier_baseline_price_list": {
    "code": "SYNKC1_JAN26",
    "month": "2026-01"
  },
  "authorized_target_price_list": {
    "code": "SYNKC1_AUG26",
    "month": "2026-08"
  },
  "requested_items": [
    {
      "item_id": "ceiling-hall",
      "status": "REQUESTED",
      "description": "Remove continuous ceiling finish and replace supported affected plane",
      "quantity": {
        "value": 120.0,
        "unit": "SF",
        "source": "synthetic-measurement#page-1"
      },
      "evidence": [
        {
          "source_id": "synthetic-photo-1",
          "source_path": "01 JOBNIMBUS SOURCE/Attachments/Photos/synthetic-photo-1.jpg",
          "supports": "open ceiling and continuous finish"
        }
      ],
      "carrier_credit": {
        "status": "EXISTING_ALLOWANCE",
        "line_reference": "carrier-line-12",
        "quantity": 10.0,
        "unit": "SF"
      },
      "unresolved_questions": []
    }
  ],
  "pricing_authority": "Xactimate; this manifest contains no unit prices",
  "external_action_authorized": false
}
```

## Division of responsibility

- `mco-supplement-fast-lane`: identity, cache, state, delta decision and approved handoff.
- `mco-jobnimbus-read`: authenticated JobNimbus reads and separately authorized mutations.
- `mco-insurance-supplement`: carrier-baseline reconstruction, evidence matrix and unpriced scope-gap judgment.
- `mco-xactimate-pricing`: exact price-list selection, line prices, Parallels operation, export and pricing-manifest verification.

No file in this contract establishes that an email was sent, a supplement was carrier-filed, a carrier approved it, or money was paid.
