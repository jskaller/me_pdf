# Learned Strategy Apply Sandbox Policy

Patch 23A adds an isolated backup/rollback sandbox for learned-strategy adoption
apply diagnostics.

The sandbox is audit-only. It may create backup-like copies, rollback-like
manifests, and rollback verification artifacts only under:

```text
JOB/audit/learned_strategy_apply_sandbox/
```

It must not create production backups, execute rollback against authoritative
files, perform adoption apply, replace production repair files, mutate the rule
map, mutate `app/tools/repair`, mutate package/status outputs, soften verdicts,
or adopt a final PDF.

## Inputs

The sandbox reads:

- `JOB/audit/learned_strategy_evidence_hashes.json`
- `JOB/audit/learned_strategy_adoption_apply_dry_run.json`
- `JOB/audit/learned_strategy_adoption_apply_dry_run_review.json`

It requires:

- operator identity
- candidate id
- rule id
- evidence hash artifact
- apply dry-run artifact
- apply dry-run review artifact

## Outputs

The sandbox may write only within the isolated diagnostic directory:

- `sandbox_manifest.json`
- `backup_manifest.json`
- `rollback_manifest.json`
- `rollback_verification.json`
- sandbox copy files under sandbox subdirectories

## Allowed outcomes

- `apply_sandbox_recorded`
- `apply_sandbox_incomplete`
- `apply_sandbox_blocked`

## Forbidden states

The sandbox must reject or preserve as non-terminal all apply/adoption language:

- `approved`
- `adoptable`
- `production_ready`
- `ready_for_adoption`
- `adoption_unblocked`
- `apply_ready`
- `approved_for_apply`
- `frozen_for_apply`
- `apply_unblocked`
- `rollback_ready`
- `apply_performed`
- `rollback_performed`
- `production_backup_created`
- `production_rollback_performed`

`sandbox_backup_created: true` is allowed only for isolated diagnostic copies
created under `JOB/audit/learned_strategy_apply_sandbox/`.

## Required safety state

Every sandbox artifact must preserve:

```json
{
  "apply_sandbox_only": true,
  "sandbox_backup_created": true,
  "production_backup_created": false,
  "adoption_apply_performed": false,
  "rollback_execution_performed": false,
  "production_rollback_performed": false,
  "candidate_is_adoptable": false,
  "candidate_approved": false,
  "candidate_production_ready": false,
  "candidate_apply_ready": false,
  "final_pdf_adoption_performed": false,
  "production_repair_replacement_performed": false,
  "verdict_softening_performed": false,
  "package_status_mutation_performed": false,
  "normal_final_pdf_remains_authoritative": true,
  "rule_map_mutation_performed": false,
  "app_tools_repair_mutation_performed": false,
  "future_apply_not_implemented": true
}
```

Rollback verification must be explicitly sandbox-only:

```json
{
  "rollback_verification_scope": "sandbox_only",
  "rollback_execution_against_authoritative_files": false,
  "sandbox_rollback_verified": true,
  "production_rollback_performed": false
}
```

## Interpretation

A successful sandbox run means only that backup and rollback manifests can be
constructed and verified against isolated copies. It is not approval, adoption,
production readiness, apply readiness, rollback readiness, or apply unblocking.
