# Learned Strategy Deeper Validation Policy

Patch 16A adds a diagnostic deeper-validation gate for learned strategy outputs that have changed a PDF and have not already been rejected by the candidate-quality gate.

This policy is governance-only. It does not approve candidates, adopt learned PDFs, soften PASS/FAIL/ESCALATION, mutate the rule map, activate strategies, or move scripts into `app/tools/repair/*`.

## Eligibility

Deeper validation runs only for candidate-quality decisions:

- `candidate_valid_changed`
- `needs_deeper_validation`

The following decisions are skipped with `skipped_not_eligible` and reason `quality_decision_not_deeper_validation_eligible`:

- `rejected_no_effect`
- `rejected_invalid`
- `rejected_execution_failed`

## Artifact

The deeper-validation report is written to:

```text
JOB/audit/learned_strategy_deeper_validation_report.json
```

The report schema version is:

```text
learned-strategy-deeper-validation.v1
```

## Checks

Patch 16A records evidence for lightweight and deeper checks where available:

- qpdf validation
- basic PDF header validation
- input/output hash comparison
- normal-final/output hash comparison
- file size comparison
- metadata extraction when available
- form-field preservation when available
- render comparison when available
- veraPDF delta when available

Unavailable or unstable helpers must be represented as:

```json
{
  "performed": false,
  "result": "SKIPPED",
  "reason": "helper_unavailable"
}
```

All external commands must be timeout-bounded and write sidecar logs under the job audit tree.

## Decisions

Deeper validation decisions are conservative:

- `skipped_not_eligible`
- `blocked_missing_artifact`
- `failed_integrity`
- `failed_preservation`
- `failed_render`
- `failed_verapdf_regression`
- `needs_manual_review`
- `deeper_validation_passed`

`deeper_validation_passed` means only that the diagnostic evidence did not find a hard failure. It is not adoption approval.

Required policy fields remain false:

```json
{
  "candidate_is_adoptable": false,
  "final_pdf_adoption_performed": false,
  "verdict_softening_performed": false,
  "rule_map_mutation_performed": false,
  "app_tools_repair_mutation_performed": false,
  "production_repair_replacement_performed": false
}
```

## Next step boundary

A candidate that passes deeper validation may proceed only to a future isolated replacement trial. That future trial must remain opt-in and must still not adopt the learned output into the final package without a separate reviewed policy patch.
## Patch 16B synthetic changed-output diagnostic smoke

Patch 16B adds a smoke-only changed-output path for learned strategy diagnostics. The setup helper supports `--script-mode changed-valid`, which stages a temporary learned script under `app/tools/repair_staging/learned/`. The staged script writes only the learned execution harness output and is expected to produce a hash-different PDF artifact that passes basic PDF header and qpdf checks.

Expected diagnostic flow:

```text
execution dry-run
-> output comparison: changed_valid_pdf, or needs_deeper_validation when checks are unavailable
-> quality gate: candidate_valid_changed, with quality_passed=false
-> deeper validation: deeper_validation_passed or needs_manual_review
-> candidate_is_adoptable=false
```

`deeper_validation_passed` is not production approval. It only means the synthetic sidecar artifact passed the available diagnostic checks and may proceed to later trial review. Patch 16B still forbids final PDF adoption, verdict softening, production repair replacement, learned-script promotion, and persistent rule-map mutation.

Cleanup is mandatory after the smoke run. `setup_learned_execution_smoke_candidate.py --cleanup` restores the backed-up rule map and removes `smoke_*.py` staged scripts.
