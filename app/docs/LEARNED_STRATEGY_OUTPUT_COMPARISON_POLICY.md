# Learned Strategy Output Comparison Policy

Patch 14A adds a diagnostic sidecar for learned strategy execution outputs. It does not adopt learned outputs, replace production repairs, soften verdicts, promote scripts, activate candidates, or mutate the canonical rule map.

## Purpose

When `--learned-execution-dry-run` executes an active learned candidate through the isolated harness, the orchestrator now records structured evidence about the candidate output:

```text
learned execution dry-run produces output.pdf
→ compare output against the harness input and normal final PDF
→ run basic PDF header and qpdf checks when available
→ write learned_strategy_output_comparisons.json
→ classify evidence only
→ no final adoption
```

This answers whether the learned script produced a PDF-like artifact, whether it changed anything, and whether lightweight integrity checks pass. It is not a quality gate and not a production handoff.

## Artifact path

The job-level artifact is:

```text
JOB/audit/learned_strategy_output_comparisons.json
```

`JOB/audit/learned_strategy_execution_diagnostics.json` also references this artifact using:

```json
{
  "output_comparison_performed": true,
  "output_comparison_artifact": "JOB/audit/learned_strategy_output_comparisons.json"
}
```

## Classification values

Patch 14A classifications are conservative and deterministic:

* `execution_failed` — the harness result was not `PASS`.
* `missing_output` — the candidate output is absent or zero bytes.
* `no_effect` — the output hash equals the controlled harness input hash.
* `changed_valid_pdf` — the output changed and qpdf passed.
* `changed_invalid_pdf` — the output changed and qpdf failed, or both qpdf and basic header checks fail.
* `needs_deeper_validation` — the output changed but lightweight validation is incomplete, skipped, or unavailable.

No classification means `adoptable` in Patch 14A.

## Validation evidence

Each comparison records:

* input/output/final PDF paths and SHA-256 hashes;
* output existence and size;
* input/output and normal-final/output hash equality;
* a basic `%PDF-` header check;
* qpdf check result, stdout/stderr sidecar paths, and exit code when qpdf is available.

If qpdf is unavailable, the qpdf section is marked `SKIPPED`; changed outputs are classified as `needs_deeper_validation` unless another deterministic test injects a passing checker.

## Non-adoption boundary

The comparison artifact repeats the mandatory policy flags:

```json
{
  "diagnostic_sidecar_only": true,
  "final_pdf_adoption_performed": false,
  "verdict_softening_performed": false,
  "rule_map_mutation_performed": false,
  "app_tools_repair_mutation_performed": false,
  "production_repair_replacement_performed": false
}
```

Comparison failure is diagnostic-only. A malformed execution artifact, missing output, qpdf failure, or unavailable qpdf must not change `FINAL_PDF`, `STATUS.json`, `orchestrator_outcome.json`, package routing, Hermes reconciliation, the rule map, or `app/tools/repair/*`.

## Next step

Patch 14B can add deeper validation and candidate quality gates. That future patch must still be separate from final PDF adoption and must define review, rollback, preservation, and verdict semantics before any learned output can replace production repair output.
