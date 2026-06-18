# Learned Strategy Adoption Apply Dry-Run Policy

Patch 21B records a sidecar-only simulation of a future learned-strategy adoption apply transaction.

The simulation reads `JOB/audit/learned_strategy_adoption_apply_policy_design.json` and writes `JOB/audit/learned_strategy_adoption_apply_dry_run.json`.

This artifact is not an apply plan. It is not approval. It is not production readiness. It is not apply readiness. It never creates backups, never executes rollback, never mutates `app/tools/repair`, never mutates `app/tools/audit/rule_repair_map.json`, never mutates authoritative `STATUS.json` or package deliverables, and never adopts a final PDF.

Allowed outcomes are:

- `apply_dry_run_simulation_recorded`
- `apply_dry_run_simulation_incomplete`
- `apply_dry_run_simulation_blocked`

Forbidden terminal states include `approved`, `adoptable`, `production_ready`, `ready_for_adoption`, `adoption_unblocked`, `apply_ready`, `approved_for_apply`, `frozen_for_apply`, `apply_plan_created`, `apply_unblocked`, `rollback_ready`, `apply_performed`, `rollback_performed`, and `backup_created`.

The simulation must include text-only future transaction steps, text-only backup and rollback manifest expectations, text-only allowed and forbidden future mutation lists, text-only post-apply and post-rollback checks, abort conditions, operator prompts, required future approver identity, and immutable evidence hash checks.

Mandatory safety flags must keep every adoption/apply/mutation field false and must keep `normal_final_pdf_remains_authoritative`, `future_apply_not_implemented`, and `future_rollback_not_implemented` true.
