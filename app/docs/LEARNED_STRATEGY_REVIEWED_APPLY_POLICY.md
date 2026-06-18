# Patch 25A — Reviewed Learned Apply Policy

Patch 25A introduces the first narrow, explicit, job-scoped reviewed apply command for a learned strategy output.

The reviewed apply tool may copy one locked learned trial/test PDF to a job-local adopted output path:

```text
JOB/audit/learned_strategy_reviewed_apply/adopted_final.pdf
```

It must not enable default learned execution, mutate `app/tools/repair`, mutate `app/tools/audit/rule_repair_map.json`, soften verdicts, rewrite package/status outputs, or mark a candidate globally approved, adoptable, production-ready, or apply-ready.

## Required identities and locks

A reviewed apply must require:

- explicit `--apply`
- operator identity
- reviewer identity
- separate approver identity
- candidate id
- rule id
- expected current normal final PDF hash
- expected learned trial/test PDF hash
- expected evidence hash artifact hash
- expected simulation artifact hash

Reviewer and approver identities must be different.

## Required upstream evidence

The reviewed apply command must read and validate the existing sidecar chain:

```text
JOB/audit/learned_strategy_evidence_hashes.json
JOB/audit/learned_strategy_adoption_apply_dry_run.json
JOB/audit/learned_strategy_adoption_apply_dry_run_review.json
JOB/audit/learned_strategy_apply_sandbox/sandbox_manifest.json
JOB/audit/learned_strategy_apply_sandbox/rollback_verification.json
JOB/audit/learned_strategy_apply_simulation/simulation_manifest.json
JOB/audit/learned_strategy_apply_simulation/simulated_validation_report.json
JOB/audit/learned_strategy_apply_simulation/simulated_rollback_verification.json
```

All candidate ids, rule ids, locked hashes, simulation validation, and rollback verification must match before any adopted output is written.

## Write order

The apply command must fail closed unless this order is achieved:

1. Create a backup of the current normal final PDF under `JOB/audit/learned_strategy_reviewed_apply/backups/`.
2. Create a rollback manifest before adoption.
3. Copy the learned trial/test PDF to `adopted_final.pdf`.
4. Validate the adopted output with qpdf or a safe PDF fallback.
5. Record the apply manifest, backup manifest, rollback manifest, post-apply validation, and audit record.

## Allowed outcomes

```text
reviewed_apply_performed
reviewed_apply_blocked
reviewed_apply_incomplete
reviewed_apply_failed_closed
```

## Required safety flags

Successful reviewed apply artifacts must include:

```json
{
  "reviewed_apply_only": true,
  "explicit_apply_requested": true,
  "reviewer_identity_recorded": true,
  "approver_identity_recorded": true,
  "separate_reviewer_and_approver": true,
  "production_backup_created": true,
  "rollback_manifest_created": true,
  "adoption_apply_performed": true,
  "job_scoped_apply_only": true,
  "candidate_is_adoptable": false,
  "candidate_approved": false,
  "candidate_production_ready": false,
  "candidate_apply_ready": false,
  "default_learned_execution_enabled": false,
  "rule_map_mutation_performed": false,
  "app_tools_repair_mutation_performed": false,
  "production_repair_replacement_performed": false,
  "verdict_softening_performed": false,
  "package_status_mutation_performed": false
}
```

`adoption_apply_performed: true` is allowed only for this explicit job-scoped reviewed apply artifact. It does not imply global production readiness.
