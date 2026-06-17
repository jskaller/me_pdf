# Learned Strategy Candidate Quality Policy

Patch 14B adds a diagnostic-only quality gate for learned strategy outputs.
The gate consumes `JOB/audit/learned_strategy_output_comparisons.json` and writes
`JOB/audit/learned_strategy_candidate_quality_report.json`.

The gate answers one narrow question: given execution and comparison evidence,
how should the learned output be treated next? It does not adopt, approve,
promote, activate, install, or replace any production repair.

## Decision values

| Comparison classification | Quality decision | `quality_passed` | Required next step |
|---|---:|---:|---|
| `no_effect` | `rejected_no_effect` | `false` | `no_action` |
| `missing_output` | `rejected_invalid` | `false` | `no_action` |
| `changed_invalid_pdf` | `rejected_invalid` | `false` | `no_action` |
| `execution_failed` | `rejected_execution_failed` | `false` | `inspect_execution_failure` |
| `needs_deeper_validation` | `needs_deeper_validation` | `false` | `deeper_validation_required` |
| `changed_valid_pdf` | `candidate_valid_changed` | `false` | `deeper_validation_required` |

All Patch 14B decisions keep `quality_passed: false`. A qpdf-valid changed PDF
is only evidence that the candidate may be worth deeper validation later. It is
not an approval, not an adoption decision, and not production readiness.

## Why `no_effect` is rejected

A learned output whose hash equals the input did not repair the document. Even if
that output remains a valid PDF, it provides no remediation value and is classified
as `rejected_no_effect`.

## Diagnostic-only boundary

Every quality report includes policy flags proving that Patch 14B remains a
sidecar governance layer:

```json
{
  "diagnostic_sidecar_only": true,
  "final_pdf_adoption_performed": false,
  "verdict_softening_performed": false,
  "rule_map_mutation_performed": false,
  "app_tools_repair_mutation_performed": false,
  "production_repair_replacement_performed": false,
  "candidate_quality_is_not_adoption_approval": true
}
```

Malformed or missing comparison artifacts are handled diagnostically by writing a
quality report with a blocker and `needs_deeper_validation`. They must not alter
normal remediation verdicts, status output, package behavior, or the final PDF.
