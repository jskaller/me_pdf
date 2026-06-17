# Learned Strategy Replacement Trial Policy

Patch 17A adds an explicit, opt-in isolated replacement trial for learned strategy outputs. The trial answers one diagnostic question: if a learned output were considered as a replacement candidate, what evidence would be available? It does not approve, adopt, promote, activate, install, or replace any production repair.

## Invocation boundary

The trial is never default behavior. It is available only through learned execution dry-run diagnostics:

```text
--learned-execution-dry-run --learned-replacement-trial
```

Manual-review candidates may enter the trial only when the smoke-only bypass is explicit:

```text
--learned-replacement-trial-allow-manual-review
```

Using `--learned-replacement-trial` without `--learned-execution-dry-run` fails closed before remediation work begins.

## Eligibility

Without the diagnostic bypass, a candidate is trial-eligible only when all of the following are true:

```text
deeper_validation_decision == deeper_validation_passed
candidate_may_proceed_to_trial == true
candidate_is_adoptable == false
```

With the bypass, `needs_manual_review` candidates may run an isolated trial, but the report must mark:

```json
{
  "trial_forced_for_diagnostics": true,
  "trial_eligible_without_force": false
}
```

The trial does not run for `skipped_not_eligible`, `failed_integrity`, `failed_preservation`, `failed_render`, `failed_verapdf_regression`, or `blocked_missing_artifact` deeper-validation decisions.

## Artifacts

The top-level trial report is written to:

```text
JOB/audit/learned_strategy_replacement_trial_report.json
```

Each attempted trial writes isolated files under:

```text
JOB/audit/learned_strategy_replacement_trial/<attempt_id>/
```

The trial directory contains copies named `normal_final.pdf` and `learned_trial.pdf`; the normal final PDF remains authoritative.

## Checks

Patch 17A records lightweight trial-local evidence: normal/learned SHA-256 hashes, file sizes, whether the learned output differs from the normal final PDF, a basic `%PDF-` header check, and a timeout-bounded qpdf check when qpdf is available. qpdf stdout/stderr sidecars remain inside the isolated trial directory.

## Decisions

Trial decisions are diagnostic evidence only:

```text
trial_skipped_not_eligible
trial_failed_integrity
trial_failed_regression
trial_needs_manual_review
trial_evidence_passed
```

`trial_evidence_passed` still does not mean adoptable. Patch 17A keeps `candidate_is_adoptable: false` for every result.

## Non-adoption policy

Every report must preserve these boundaries:

```json
{
  "diagnostic_sidecar_only": true,
  "isolated_trial_only": true,
  "normal_final_pdf_remains_authoritative": true,
  "candidate_is_adoptable": false,
  "replacement_trial_is_not_adoption_approval": true,
  "final_pdf_adoption_performed": false,
  "verdict_softening_performed": false,
  "rule_map_mutation_performed": false,
  "app_tools_repair_mutation_performed": false,
  "production_repair_replacement_performed": false
}
```

## Next boundary

The next step is a production-testing readiness review or wiring the missing validation helpers. Production replacement, final PDF adoption, verdict softening, learned promotion, and `app/tools/repair/*` mutation remain out of scope.
