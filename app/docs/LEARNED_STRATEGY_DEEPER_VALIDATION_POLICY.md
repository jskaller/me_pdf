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
