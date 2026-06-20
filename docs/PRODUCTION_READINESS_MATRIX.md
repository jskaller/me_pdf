# Production Readiness Matrix Harness

The production-readiness matrix exists to compare multiple PDF remediation jobs using the same evidence fields. It is not a new repair strategy, not a packaging authority, and not a visual QA signoff. Its purpose is to show what the current system can actually prove across controlled fixtures, synthetic fixtures, representative local PDFs, and private/local-only PDFs.

## How this differs from WebUI E2E proof

`docs/WEBUI_PDF_E2E_VERIFICATION.md` proves a user-facing path for one submitted PDF:

```text
Open WebUI -> first message begins with PDF: -> Hermes runbook -> orchestrator -> STATUS/package artifacts
```

The matrix harness is broader and more conservative. It inspects existing `workspace/jobs` and `workspace/output` artifacts, or optionally runs explicitly listed local inputs through the orchestrator, then records comparable outcomes. A single controlled smoke fixture can be useful evidence, but it is not representative production coverage by itself.

## Component classification

| Component | Classification | Patch H1 behavior |
|---|---|---|
| `app/tools/audit/production_readiness_matrix.py` | audit/diagnostic code | New read-only artifact inspector plus optional explicit orchestrator-run wrapper. |
| `scripts/run-production-readiness-matrix.sh` | test/smoke verification | New CLI wrapper for inspection/run modes. |
| `docs/PRODUCTION_READINESS_MATRIX.md` | documentation-only behavior | Documents usage, evidence, and limitations. |
| `workspace/jobs/*` and `workspace/output/*` | workspace artifact | Inspected only in artifact-inspection mode; never committed. |
| `app/tools/orchestrate/remediate.py` | production path code | Read-only; optional run mode invokes it but does not modify it. |
| `app/tools/audit/rule_repair_map.json` | production path config/rule map | Read-only; rule-map entries are not counted as proven repairs without execution and validator evidence. |
| Repair scripts under `app/tools/repair/` | production path code | Not modified by this patch. |
| Learned-strategy files | risky/unknown behavior for this scope | Out of scope. |
| axesCheck and PAC 2024 | missing external validator evidence unless supplied manually | Always reported as `NOT_RUN` unless real evidence is added in a future explicit workflow. |

## Artifact-inspection mode

From the repository root:

```bash
bash scripts/run-production-readiness-matrix.sh --inspect-existing
```

To write JSON:

```bash
bash scripts/run-production-readiness-matrix.sh \
  --inspect-existing \
  --out workspace/production_readiness_matrix.json
```

If no workspace artifacts exist, the harness emits an `INCOMPLETE_ARTIFACTS` matrix row. It must not claim `PASS` from an empty workspace.

## Optional orchestrator-run mode

Optional run mode is explicit and local-only:

```bash
bash scripts/run-production-readiness-matrix.sh \
  --run \
  --pdf WEBUI-E2E-001:e2e-smoke:workspace/input/WEBUI-E2E-001/e2e-smoke.pdf:controlled_fixture \
  --out workspace/production_readiness_matrix.json
```

The source PDF must already be staged at the orchestrator's expected path:

```text
workspace/input/<ticket>/<basename>.pdf
```

If the path is missing, the row is marked `skipped_missing_input` and `INCOMPLETE_ARTIFACTS`; the harness does not invent a job or claim a production result.

## Adding a local/private PDF without committing it

1. Put the PDF under `workspace/input/<ticket>/<basename>.pdf`.
2. Do not add the PDF to git.
3. Run optional mode with an explicit source-kind tag:

```bash
bash scripts/run-production-readiness-matrix.sh \
  --run \
  --pdf TICKET-123:source-name:workspace/input/TICKET-123/source-name.pdf:private_local_or_representative_pdf
```

The source-kind tag is reporting metadata only. It prevents one controlled fixture from being mistaken for representative real-PDF coverage.

## Matrix evidence fields

Each row records:

- ticket, basename, source PDF path, job directory, and output directory;
- run mode: `inspected_existing`, `orchestrator_run`, or `skipped_missing_input`;
- pre-repair validator failures when available;
- repair plan rules and strategies when available;
- repair scripts executed when `execution_log.json` or compatible artifacts exist;
- post-repair outcomes for qpdf, veraPDF PDF/UA, veraPDF WCAG, veraPDF ISO, metadata/XMP parity, preservation, table semantics, contrast, OCR pre-flight, render compare, and visual QA;
- residual targetable and non-targetable rules;
- active `HERMES_REQUIRED` signals;
- `orchestrator_outcome.json` and `STATUS.json` overall results;
- status/outcome consistency;
- package location, checksums presence, review package presence, PASS package presence, and false-success packaging risk;
- external validators as `NOT_RUN` unless real evidence exists;
- final classification.

## Final classifications

| Classification | Evidence standard |
|---|---|
| `PASS` | Authoritative status/outcome says `PASS`, artifacts are present, and a top-level remediated PDF package exists. |
| `REVIEW_REQUIRED` | Authoritative status/outcome says `REVIEW_REQUIRED` and package/review evidence exists. |
| `FAIL` | Authoritative status/outcome says `FAIL`; any copied PDF in output is flagged as a false-success risk. |
| `ESCALATION` | Authoritative status/outcome says `ESCALATION`; active `HERMES_REQUIRED` signals and residual strategy gaps are recorded. |
| `BLOCKED` | Optional run mode did not produce a job directory or the orchestrator path was blocked. |
| `INCOMPLETE_ARTIFACTS` | Required artifacts are missing, no jobs exist, PASS lacks deliverable evidence, or inputs are missing. |
| `MISMATCH` | `STATUS.json` and `orchestrator_outcome.json` disagree on the final outcome. |

## Repair evidence guardrail

A rule-map entry is not proof of a working production repair. A row may list planned strategies, but a repair is only matrix-proven when the artifacts show both:

1. a mapped or applicable script actually executed, and
2. validator/residual evidence demonstrates the relevant rule cleared or improved.

This preserves the production-readiness handoff guardrail: wiring alone is not remediation proof.

## External validators

axesCheck and PAC 2024 are not run by this harness. They remain `NOT_RUN` unless a future explicit workflow supplies real evidence artifacts. The matrix must not treat veraPDF-only success as final external signoff.

## Limitations

The matrix is only as strong as the artifacts it inspects. If it only finds the WebUI smoke fixture, the report should say synthetic/fixture coverage is one and representative real-PDF coverage is zero. It does not claim 10/10 production readiness, does not mutate final PDFs, and does not change package routing.
