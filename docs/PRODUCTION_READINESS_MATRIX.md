# Production Readiness Matrix Harness

The production-readiness matrix exists to compare multiple PDF remediation jobs using the same evidence fields. It is not a new repair strategy, not a packaging authority, and not a visual QA signoff. Its purpose is to show what the current system can actually prove across controlled fixtures, synthetic fixtures, representative local PDFs, and private/local-only PDFs.

## How this differs from WebUI E2E proof

`docs/WEBUI_PDF_E2E_VERIFICATION.md` proves a user-facing path for one submitted PDF:

```text
Open WebUI -> first message begins with PDF: -> Hermes runbook -> orchestrator -> STATUS/package artifacts
```

The matrix harness is broader and more conservative. It inspects existing `workspace/jobs` and `workspace/output` artifacts, or optionally runs explicitly listed local inputs through the orchestrator, then records comparable outcomes. A single controlled smoke fixture can be useful evidence, but it is not representative production coverage by itself.

## Component classification

| Component | Classification | Patch H2 behavior |
|---|---|---|
| `app/tools/audit/production_readiness_matrix.py` | audit/diagnostic code | Read-only artifact inspector with basename-scoped package attribution. |
| `scripts/run-production-readiness-matrix.sh` | test/smoke verification | CLI wrapper for inspection/run modes. |
| `docs/PRODUCTION_READINESS_MATRIX.md` | documentation-only behavior | Documents usage, evidence, attribution, and limitations. |
| `workspace/jobs/*` and `workspace/output/*` | workspace artifact | Inspected only in artifact-inspection mode; never committed. |
| `app/tools/orchestrate/remediate.py` | production path code, read-only | Optional run mode invokes it but does not modify it. |
| `app/tools/packaging/package_deliverables.py` | packaging authority, read-only | Defines deliverable routing; the matrix only inspects its output artifacts. |
| `app/tools/packaging/status_json_writer.py` | packaging/status authority, read-only | Defines STATUS evidence; the matrix only compares it to orchestrator outcome. |
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

## Shared ticket-level output directories

The packaging flow writes final deliverables under ticket-level directories such as:

```text
workspace/output/<ticket>_remediated/
```

A ticket can have multiple job directories when a document is rerun with a timestamped or alternate basename. This means one ticket output directory can contain artifacts from a sibling or stale run. Patch H2 makes matrix package attribution basename-scoped so a job is not credited or blamed for every PDF in the shared ticket output directory.

## Matched versus unmatched output artifacts

Each row includes `matched_output_artifacts`:

```text
expected_basename
output_dir
matched_pdfs
matched_reports
matched_checksums
matched_top_level_pdfs
matched_review_pdfs
matched_failed_pdfs
matched_top_level_reports
matched_review_reports
matched_failed_reports
unmatched_pdfs_in_output_dir
unmatched_reports_in_output_dir
shared_output_dir
stale_or_shared_output_risk
confirmed_false_success_pdf
no_false_success_evidence
```

For a job with basename `<basename>`, the matrix prefers exact artifact names:

```text
<basename>_remediated.pdf
<basename>_AUDIT_REPORT.md
SHA256SUMS.txt
```

It checks the top-level output directory plus `review/` and `failed/` subdirectories. Unmatched PDFs and reports are still reported, but they are not counted as evidence for the current job's PASS or REVIEW_REQUIRED outcome.

## False-success and stale/shared-output distinctions

The matrix distinguishes three cases for `FAIL` and `ESCALATION` rows:

| Field / risk | Meaning |
|---|---|
| `confirmed_false_success_pdf` | The same basename has a matched PDF in a success-like location, such as the top-level output directory or `review/`. This is treated as a confirmed package risk for that row. |
| `stale_or_shared_output_risk` | The ticket output directory contains PDFs, but they do not match the row's basename. This indicates likely sibling/stale output ambiguity, not a confirmed packaging defect for the row. |
| `no_false_success_evidence` | No matched success-like PDF exists for the row. |

A matched PDF under `failed/` is reported as a risk but is not counted as a successful deliverable. FAIL and ESCALATION should remain report-only unless packaging authority explicitly changes in a separate approved patch.

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
- package location, checksums presence, review package presence, PASS package presence, and basename-scoped false-success or stale/shared-output risks;
- external validators as `NOT_RUN` unless real evidence exists;
- final classification.

## Final classifications

| Classification | Evidence standard |
|---|---|
| `PASS` | Authoritative status/outcome says `PASS`, required artifacts are present, and a matched top-level `<basename>_remediated.pdf` exists for the same job basename. |
| `REVIEW_REQUIRED` | Authoritative status/outcome says `REVIEW_REQUIRED` and matched review/package evidence exists for the same job basename. |
| `FAIL` | Authoritative status/outcome says `FAIL`; same-basename success-like PDFs are flagged as confirmed false-success risks, while sibling PDFs are flagged only as stale/shared-output risks. |
| `ESCALATION` | Authoritative status/outcome says `ESCALATION`; active `HERMES_REQUIRED` signals and residual strategy gaps are recorded; package PDF risks are basename-scoped. |
| `BLOCKED` | Optional run mode did not produce a job directory or the orchestrator path was blocked. |
| `INCOMPLETE_ARTIFACTS` | Required artifacts are missing, no jobs exist, PASS lacks matched deliverable evidence, REVIEW_REQUIRED lacks matched review/package evidence, or inputs are missing. |
| `MISMATCH` | `STATUS.json` and `orchestrator_outcome.json` disagree on the final outcome. |

## Repair evidence guardrail

A rule-map entry is not proof of a working production repair. A row may list planned strategies, but a repair is only matrix-proven when the artifacts show both:

1. a mapped or applicable script actually executed, and
2. validator/residual evidence demonstrates the relevant rule cleared or improved.

This preserves the production-readiness handoff guardrail: wiring alone is not remediation proof.

## External validators

axesCheck and PAC 2024 are not run by this harness. They remain `NOT_RUN` unless a future explicit workflow supplies real evidence artifacts. The matrix must not treat veraPDF-only success as final external signoff.

## Executive reporting hygiene

Old workspace artifacts should be filtered, archived, or cleaned before executive production-readiness reporting. Development probes, pre-patch smoke runs, timestamped reruns, and intentionally incomplete fixtures can be useful diagnostics, but they can distort coverage counts and stale/shared-output risk summaries.

For executive reporting, prefer one of these approaches:

1. run the matrix in a clean workspace;
2. pass explicit local PDFs through optional run mode;
3. archive old `SMOKE_*`, `PROBE_*`, or pre-patch job directories before generating the report; or
4. document that the matrix includes historical/probe artifacts.

## Limitations

The matrix is only as strong as the artifacts it inspects. If it only finds the WebUI smoke fixture, the report should say synthetic/fixture coverage is one and representative real-PDF coverage is zero. It does not claim 10/10 production readiness, does not mutate final PDFs, does not modify packaging behavior, and does not change package routing.

## Patch H4 corpus profiles and blocker prioritization

Patch H4 adds corpus-profile metadata and blocker prioritization to the matrix without changing repair behavior, package routing, rule-map authority, learned-strategy adoption, or final PDFs.

Use `--profile` to select evidence scope:

```bash
bash scripts/run-production-readiness-matrix.sh --inspect-existing --profile all
bash scripts/run-production-readiness-matrix.sh --inspect-existing --profile production
bash scripts/run-production-readiness-matrix.sh --inspect-existing --profile fixtures
bash scripts/run-production-readiness-matrix.sh --inspect-existing --profile historical
bash scripts/run-production-readiness-matrix.sh --inspect-existing --profile actionable
```

Each row includes `corpus_profile` with `primary_profile`, `included_in_profiles`, `excluded_from_production_reason`, `manifest_source`, and `profile_reason`. Matrix output also includes `corpus_summary` and `blocker_priority_summary`.

For detailed corpus-selection policy, manifest usage, blocker priority buckets, MM-17179/H3 interpretation, and executive reporting guidance, see `docs/PRODUCTION_CORPUS_SELECTION.md`.


## Patch H5 active blocker evidence-source audit

Patch H5 tightens `blocker_priority_summary` so P0/P1 priority requires current active production blocker evidence. Pre-repair-only failures, repair-plan-only rules, and execution history remain visible as contextual evidence, but they do not independently create production-blocker priority.

The strongest current-active sources are active `HERMES_REQUIRED` signals, post-repair rule failures, residual targetable rules, and residual non-targetable rules. PASS rows with contradictory current-active evidence are reported as risk records instead of being treated as normal production blockers.
