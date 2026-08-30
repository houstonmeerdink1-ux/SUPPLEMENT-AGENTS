---
name: mco-supplement-fast-lane
description: Use when Houston identifies an MCO insurance supplement by customer or job name and needs carrier-scope diagnosis, JobNimbus source reconciliation, or an Xactimate pricing handoff.
---

# MCO Supplement Fast Lane

Turn a customer or job name into a locked, source-backed supplement workspace. Explain what the carrier estimate got wrong before asking Houston to approve scope, and do not enter Xactimate until the approved unpriced manifest is `PRICING_READY`.

## Required skills

- Use `mco-jobnimbus-read` for authenticated JobNimbus reads and any separately authorized CRM mutation.
- Use `mco-insurance-supplement` to identify the qualifying carrier estimate, review it page by page, build the evidence matrix, credit existing allowances, and write the unpriced scope-gap analysis.
- Use `mco-xactimate-pricing` only after the gate reports `PRICING_READY`; it owns exact price-list selection, Parallels/Xactimate operation, export, and verification.

Read [references/data-contracts.md](references/data-contracts.md) before creating or interpreting generated JSON.

## Workflow

Set the coordinator path:

```bash
FAST_LANE="${CODEX_HOME}/skills/mco-supplement-fast-lane/scripts/fast_lane.py"
```

1. Resolve the supplied name against the approved SONY mirror roster. Never ask for a job number first and never silently choose among multiple matches.

```bash
python3 "$FAST_LANE" resolve "CUSTOMER OR JOB NAME"
```

Confirm the exact address, five-digit ZIP, JobNimbus job ID, contact ID, and job number from the result. Stop on ambiguity, conflict, missing drive, or missing ZIP.

2. Prepare or reuse the source-aware cache. Generated work belongs under `02 LOCAL WORKING FILES/00 FAST LANE`; never alter `01 JOBNIMBUS SOURCE`.

```bash
python3 "$FAST_LANE" prepare "CUSTOMER OR JOB NAME"
```

3. Compare the locked record with live JobNimbus metadata through the existing read-only bridge.

```bash
python3 "$FAST_LANE" live-check "CUSTOMER OR JOB NAME"
```

An attachment aggregate is only a change signal. It never proves attachment completeness. Stop and reconcile when the state is `SOURCE_CHANGED`, `SOURCE_INCOMPLETE`, or any identity-blocked state.

4. Apply `mco-insurance-supplement`. Select the current qualifying carrier estimate by document date and contents, not filename alone. First deliver a plain-language diagnosis of what was paid, omitted, under-scoped, or left inconsistent. For continuous ceiling texture and paint, evaluate the supported whole affected plane and credit every existing carrier allowance. Keep all pricing out of `scope-gap.json`.

5. After the source-backed scope is `SCOPE_AUDITED`, obtain Houston's explicit approval of the requested items. Record the audit, then build the pricing handoff with separate baseline and target price lists:

```bash
python3 "$FAST_LANE" mark-audited "CUSTOMER OR JOB NAME" --scope-gap /absolute/path/scope-gap.json
python3 "$FAST_LANE" approve-scope "CUSTOMER OR JOB NAME" \
  --scope-gap /absolute/path/scope-gap.json \
  --approved-by Houston --approved-at ISO-8601-TIMESTAMP \
  --baseline-code EXACT_CODE --baseline-month YYYY-MM \
  --target-code EXACT_CODE --target-month YYYY-MM
```

6. Only when the result is `PRICING_READY`, apply `mco-xactimate-pricing`. Use the exact authorized price-list code and month, price only approved supported items, export, and verify the finished Xactimate artifact against the manifest.

## Hard stops

Do not proceed through an ambiguous identity, missing ZIP, changed or incomplete source, unresolved question, missing quantity or evidence pointer, unsupported carrier credit, missing exact price list, Xactimate/runtime/dialog uncertainty, or unverified export. Do not invent prices or quantities. Keep saved, exported, emailed, uploaded, submitted, approved, and paid as separate states; no external action is authorized by this workflow.
