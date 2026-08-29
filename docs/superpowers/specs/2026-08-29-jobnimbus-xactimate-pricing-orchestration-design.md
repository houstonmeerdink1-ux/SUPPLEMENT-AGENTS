# JobNimbus to Xactimate Pricing Orchestration

Purpose: define the approved local workflow that resolves an MCO customer to one exact JobNimbus job, retrieves the correct Xactimate pricing basis through Parallels, verifies the pricing artifact, and privately files it back to that job for later supplement work.

## Outcome

Houston can begin with a customer name. The orchestrator uses that name only as a search term, resolves one exact property address and JobNimbus job ID, obtains the correct ZIP and pricing basis, controls Parallels/Xactimate to retrieve requested pricing, creates a compact verified pricing snapshot, and—when the current request authorizes that exact upload—files it privately to the resolved JobNimbus job and reads it back.

The workflow does not create supplement scope, decide coverage, alter a carrier source estimate, contact a carrier, or upload an unrestricted Xactimate regional database.

## Existing components

- `mco-jobnimbus-read` owns JobNimbus searching, downloads, uploads, and post-write verification.
- `mco-xactimate-pricing` owns Parallels/Windows operation, exact price-list selection, requested line-item capture, export, and pricing provenance.
- `mco-insurance-supplement` consumes the verified pricing artifact when building an authorized supplement.
- Codex Computer Use supplies attended visual control of Parallels, Windows, browser, and Xactimate surfaces.

The orchestration layer coordinates these components. It does not duplicate their connectors or weaken their authorization boundaries.

## Identity contract

A customer name is a search key, never the final job identity. Before Xactimate or any JobNimbus write, the run record must contain:

- source spelling of the customer name;
- exact property address;
- five-digit ZIP;
- JobNimbus contact ID and job ID;
- carrier and claim/estimate identity when available;
- source timestamps for the facts used.

If multiple jobs plausibly match, the workflow stops before Xactimate and asks Houston to select the exact address. Similar names, nearby addresses, claim numbers, folders, or filenames are never silently joined.

## Pricing-basis contract

The run preserves two different concepts:

- `CARRIER_BASELINE`: the price-list code and month documented in the carrier estimate, when present;
- `TARGET`: the exact ZIP-assigned price list requested for the pricing run.

Target-month precedence is:

1. a month Houston explicitly states in the current request;
2. the carrier estimate's documented price-list month for a name-only request;
3. stop for Houston when the carrier month is absent, conflicting, or unreadable.

The workflow never silently substitutes date of loss, current month, latest available list, a nearby ZIP, or another market. `LATEST_AVAILABLE` is used only when Houston explicitly requests it.

## Run sequence

### 1. JobNimbus intake

1. Search contacts and jobs using the supplied name.
2. Follow pagination and reconcile candidate records.
3. Resolve the exact address and JobNimbus job ID.
4. Inventory the exact job's files. When completeness matters, reconcile API results against the authenticated JobNimbus UI.
5. Select and verify the carrier estimate or scope by metadata, exact-address content, usable bytes, page inspection, and SHA-256.
6. Extract the ZIP, carrier baseline list/month, and requested pricing context.

This phase is read-only.

### 2. Xactimate preflight and access

1. Run the Parallels compatibility and runtime preflights.
2. Record the initial VM lifecycle state.
3. Treat the Apple-silicon/Windows ARM environment as `COMPATIBILITY_TRIAL`, even when Xactimate launches.
4. Stop for Houston at authentication, MFA, activation, license, EULA, payment, update/restart, or security-permission screens.
5. Complete the first end-to-end trial only against unmistakably synthetic `TEST_PROJ`.
6. For later customer work, run the project gate with the exact address, ZIP, and current authorization before selecting a visible project.

### 3. Price lookup

1. Confirm the exact project/address/ZIP inside Xactimate.
2. Preserve the carrier baseline; do not reprice or modify the source estimate.
3. Find the exact ZIP-assigned target list for the verified month.
4. Read back market, list code, and publication month before and after selection/download.
5. Capture only the requested line items or an authorized compact pricing report.

For each captured line, retain selector, category, item, activity, exact description, unit, unit price, visible components when relevant, and screenshot/report evidence.

### 4. Export and verification

1. Export first to a unique Windows source folder.
2. Preserve the Windows source.
3. Copy it to a new empty Mac verification folder.
4. Confirm stable byte size and calculate SHA-256.
5. Parse and render the artifact as appropriate.
6. Verify exact address, ZIP, project identity, selected list code/month, and requested lines.
7. Validate the pricing manifest.

Evidence states remain distinct:

- `SCREEN_CAPTURE_ONLY`
- `EXPORT_VERIFIED`
- `READY_FOR_PRICING`

Only `READY_FOR_PRICING` may be offered for JobNimbus filing or supplement consumption.

### 5. Private JobNimbus filing

An upload requires the current request to authorize the exact job and artifact. Immediately before uploading, the workflow states the exact address, JobNimbus job ID, filenames, and private-attachment effect.

The default attachment set is:

- a compact PDF named `Xactimate Pricing Snapshot - <exact address> - <list code> - <YYYY-MM>.pdf`;
- a small machine-readable pricing manifest when JobNimbus accepts the format and private visibility can be verified.

The compact snapshot may include the list identity and requested line items. It must not be an unrestricted copy of the proprietary regional price database.

After upload, the workflow reopens the exact job and verifies filename, uploader, upload time, usable bytes, exact-job association, and private status. Submitted, uploaded, and verified are separate states. If private status or readback cannot be proved, the run is not complete.

### 6. Supplement consumption

The supplement workflow may use only the newest attachment that independently passes:

- exact address and JobNimbus job ID match;
- target list code/month match the intended run;
- `READY_FOR_PRICING` manifest state;
- stable bytes and matching SHA-256;
- no later verified snapshot supersedes it.

The pricing attachment supplies rates and provenance only. It does not establish damage, quantity, scope entitlement, code applicability, O&P, or carrier coverage.

## Remote-control model

This Codex task can provide attended remote control of Parallels, Windows, JobNimbus, and Xactimate. It takes a fresh UI state after every navigation or modal change and does not reuse stale coordinates.

Houston retains control of:

- passwords and MFA;
- license activation and payments;
- EULA acceptance when judgment is required;
- security-critical permissions;
- destructive VM actions;
- carrier communication;
- any live upload not authorized for the exact artifact and job.

The workflow does not enable a new remote desktop service, create persistent remote-access credentials, or widen network exposure.

## Failure and recovery

- Ambiguous name or address: stop before Xactimate and request the exact address.
- Missing/conflicting price month: stop before list selection and request the month.
- ARM instability: preserve evidence and move the run to a supported x64 Windows environment.
- Authentication/MFA: Houston takes over, then control returns to Codex after successful authentication.
- Xactimate source mutation required: stop; never mutate the carrier source.
- Export verification failure: retain `SCREEN_CAPTURE_ONLY` or failed state; do not upload.
- JobNimbus private-status/readback failure: report uploaded-but-unverified or failed; do not call it filed.
- Existing owner or active unsaved work: do not open a competing context or interrupt it.

## Validation plan

### Synthetic trial

Use `TEST_PROJ` with synthetic identity and pricing inputs. Prove:

- Parallels and Xactimate access after Houston authentication;
- exact ZIP/month selection;
- requested line capture;
- Windows export and Mac verification;
- manifest validation;
- no customer project access and no live JobNimbus upload.

### Controlled live trial

After the synthetic trial passes, Houston supplies one customer name and authorizes one exact private filing. Prove:

- name-to-address/job resolution;
- carrier baseline and target separation;
- exact requested pricing;
- verified export;
- exact private upload and readback;
- later retrieval by the supplement workflow.

### Regression checks

Automated checks cover identity ambiguity, pricing-month precedence, forbidden source mutation, manifest readiness, upload authorization, private-status verification, and active-snapshot selection. UI automation remains visually verified because Xactimate screens can change.

## Completion definition

The capability is complete only after both the synthetic trial and one controlled live trial pass. A configured connector, running VM, successful export, submitted upload request, or executor report alone is not completion.
