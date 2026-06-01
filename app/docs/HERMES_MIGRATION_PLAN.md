# Hermes Migration Plan

## Goal

Replace the OpenClaw runtime dependency with Hermes while preserving the PDF/UA remediation workflow, contracts, tools, and orchestrator-first operating model.

## Current baseline

Status: Phase 0 complete.

Validated:

- Hermes dashboard works at `http://127.0.0.1:9119`.
- Hermes gateway TCP port is open at `127.0.0.1:8642`.
- NVIDIA text model works: `stepfun-ai/step-3.7-flash`.
- NVIDIA vision model works: `meta/llama-4-maverick-17b-128e-instruct`.
- Clean baseline commit is tagged `phase-0-hermes-nim-baseline`.

## Completed migration work

### Phase 1A — Runtime signal rename

Status: complete.

Active runtime files now use:

- `HERMES_REQUIRED`
- `hermes_signals.json`
- `hermes_required`
- `hermes_signals`

instead of the OpenClaw-specific names.

Commit/tag:

- Commit: `115a525 Rename OpenClaw runtime signals to Hermes`
- Tag: `phase-1-hermes-signal-rename`

Historical docs may still mention OpenClaw because they are source-context documents from the old system.

## Next implementation target

### Milestone 1A — Canonical gate-name registry

Purpose:

Stop outcome/verdict drift by making scaffold, orchestrator, status writer, and packaging agree on the same gate names.

Why this is next:

`ORCHESTRATOR_REVIEW.md` identifies outcome-integrity bugs as the highest-risk issue. The system can produce misleading PASS/FAIL/REVIEW results if gate names differ between the files that produce audits and the files that compute final status.

Expected work:

- Add a single canonical gate registry.
- Update orchestrator references to use canonical names.
- Update status JSON writer to use canonical names.
- Update package routing to use canonical final outcome.
- Ensure post-repair veraPDF PDF/UA result is never excluded from the final verdict.
- Add a small test or smoke check proving canonical names are present.

Acceptance criteria:

- No duplicated ad hoc gate-name lists in active runtime files.
- `orchestrator_outcome.json` remains the authoritative final outcome.
- `STATUS.json` does not re-derive a contradictory result.
- Failed PDF/UA post-repair validation cannot be packaged as a passing remediated deliverable.

## Later milestones

### Milestone 1B — Verdict and package routing repair

Fix final result calculation, status writer behavior, and output package routing.

### Milestone 2 — Repair/audit taxonomy cleanup

Separate audit-only scripts from true repair scripts and fix misclassified strategies.

### Milestone 3 — Residual analysis contract

Implement `JOB/audit/residual_analysis.json` per `RESIDUAL_AND_CAPTURE_CONTRACT.md`.

### Milestone 4 — Hermes skill conversion

Convert `OPENCLAW_PROMPT_TEMPLATES.md` into Hermes-facing skills/tasks.

### Milestone 5 — Resume and learning loop

Implement durable job state, resume behavior, learned strategies, and safe retry caps.

### Milestone 6 — End-to-end job validation

Run a representative PDF job through orchestrator, residual analysis, repair, QA, packaging, and final `STATUS.json`.
