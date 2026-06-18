# Learned Strategy Apply Simulation Policy

Patch 24A adds an isolated reviewed apply simulation. The simulation models a future reviewed adoption apply transaction without performing real adoption apply and without mutating authoritative production files.

## Scope

The tool writes only under:

```text
JOB/audit/learned_strategy_apply_simulation/
```

Expected outputs:

```text
simulation_manifest.json
simulated_apply_report.json
simulated_final.pdf
simulated_validation_report.json
simulated_rollback_verification.json
```

The normal final PDF remains authoritative. The package/status/verdict flow remains authoritative.

## Required inputs

The simulation requires:

- operator identity
- reviewer identity
- candidate id
- rule id
- `JOB/audit/learned_strategy_evidence_hashes.json`
- `JOB/audit/learned_strategy_adoption_apply_dry_run.json`
- `JOB/audit/learned_strategy_adoption_apply_dry_run_review.json`
- `JOB/audit/learned_strategy_apply_sandbox/sandbox_manifest.json`
- `JOB/audit/learned_strategy_apply_sandbox/backup_manifest.json`
- `JOB/audit/learned_strategy_apply_sandbox/rollback_manifest.json`
- `JOB/audit/learned_strategy_apply_sandbox/rollback_verification.json`

Missing required inputs block the simulation. Missing normal or learned PDF hash/path records an incomplete simulation. Stale hashes block the simulation.

## Non-negotiable boundaries

The simulation must not:

- perform real final PDF adoption
- replace production repair output
- create production backups
- execute rollback against authoritative files
- mutate `STATUS.json`
- mutate package deliverables
- mutate `app/tools/repair`
- mutate `app/tools/audit/rule_repair_map.json`
- soften verdicts
- mark a candidate approved, adoptable, production-ready, apply-ready, or adoption-unblocked

## Allowed outcomes

```text
apply_simulation_recorded
apply_simulation_incomplete
apply_simulation_blocked
```

Forbidden terminal states include:

```text
approved
adoptable
production_ready
ready_for_adoption
adoption_unblocked
apply_ready
approved_for_apply
frozen_for_apply
apply_unblocked
rollback_ready
apply_performed
rollback_performed
production_backup_created
production_rollback_performed
final_pdf_adopted
```

`simulated_apply_performed: true` is allowed only when paired with `apply_simulation_only: true` and only means an isolated simulation copy was made under the audit simulation directory.

## Required safety flags

Every simulation manifest and apply report must include:

```json
{
  "apply_simulation_only": true,
  "simulated_apply_performed": true,
  "adoption_apply_performed": false,
  "production_backup_created": false,
  "production_rollback_performed": false,
  "rollback_execution_against_authoritative_files": false,
  "rollback_execution_performed": false,
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

The simulated validation report must be simulation-only and must not validate the authoritative final PDF as the adopted output.

The simulated rollback verification report must be simulation-only and must not execute rollback against authoritative files.

## Validation behavior

The tool copies the learned trial or test PDF to `simulated_final.pdf` and validates the isolated copy. When `qpdf` is available, it runs `qpdf --check` against `simulated_final.pdf`. When `qpdf` is unavailable, it performs a safe local PDF header/trailer check and records qpdf availability in the validation details.

Hash checks compare:

- normal final PDF hash from evidence
- learned trial/test PDF hash from evidence
- simulated final PDF hash

The simulated final PDF must match the learned trial/test PDF hash. No authoritative final PDF is modified.
