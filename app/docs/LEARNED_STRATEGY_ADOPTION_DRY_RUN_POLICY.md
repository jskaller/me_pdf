# Learned Strategy Adoption Dry-Run Policy

Patch 20B adds a non-mutating adoption dry-run planner only.

The planner reads `JOB/audit/learned_strategy_adoption_policy_design.json` from Patch 20A and writes `JOB/audit/learned_strategy_adoption_dry_run_plan.json`. The plan records what a future adoption apply might require, but it is not executable adoption approval and does not authorize apply.

## Hard boundaries

Patch 20B does not implement adoption apply, rollback execution, candidate approval, production repair replacement, final PDF adoption, package/status mutation, verdict softening, rule-map mutation, or `app/tools/repair/*` mutation.

The normal final PDF remains authoritative. The existing package/status/verdict flow remains authoritative.

## Allowed dry-run outcomes

Only these non-operative dry-run outcomes are allowed:

- `adoption_dry_run_plan_recorded`
- `adoption_dry_run_incomplete`
- `adoption_dry_run_blocked`

The planner must reject forbidden terminal states such as `approved`, `adoptable`, `production_ready`, `ready_for_adoption`, `adoption_unblocked`, `apply_ready`, and `approved_for_apply` when those states appear as operative outcomes.

## Required safety flags

Every dry-run artifact must include these values:

```json
{
  "adoption_dry_run_only": true,
  "adoption_plan_created": true,
  "adoption_apply_performed": false,
  "backup_created": false,
  "rollback_execution_performed": false,
  "candidate_is_adoptable": false,
  "candidate_approved": false,
  "candidate_production_ready": false,
  "final_pdf_adoption_performed": false,
  "production_repair_replacement_performed": false,
  "verdict_softening_performed": false,
  "package_status_mutation_performed": false,
  "normal_final_pdf_remains_authoritative": true,
  "rule_map_mutation_performed": false,
  "app_tools_repair_mutation_performed": false,
  "plan_is_non_executable_without_future_patch": true,
  "future_apply_not_implemented": true
}
```

`adoption_plan_created: true` means only that a dry-run planning artifact was recorded. It does not mean apply is allowed or unblocked.

## Required dry-run plan content

The plan records:

- candidate id
- rule id
- operator/reviewer identity
- policy design artifact path and hash
- production readiness report path and hash
- production test report path and hash
- production test review report path and hash
- normal final PDF path and hash
- learned trial/test PDF path and hash
- files that would need backups in a future apply
- files that would be allowed to change in a future apply
- files that must never change during dry-run planning
- rollback steps required for a future apply
- manual evidence required before any future apply
- explicit future `--apply` requirement
- explicit future rollback command requirement

The artifact must include a blocker such as `blocked_pending_explicit_future_apply` or `dry_run_only_no_apply_performed`.

## CLI

```bash
PYTHONPATH=app python3 app/tools/audit/learned_strategy_adoption_dry_run.py \
  --job-dir /app/workspace/jobs/MM-17179_ROI4987_English_1-26_rev_Fillable \
  --operator "reviewer-name" \
  --repo-root /app
```

Optional flags:

- `--policy-design-artifact PATH`
- `--output PATH`
- `--reviewer NAME`
- `--candidate-id ID`
- `--rule-id ID`

Candidate and rule IDs default to the Patch 20A policy design artifact values. Passing explicit IDs is allowed for cross-checking/reporting, but the command remains dry-run only.

## Mutation policy

The dry-run planner writes only the dry-run plan artifact. It snapshots protected files before and after the write and records `protected_mutation_count`. A non-zero protected mutation count blocks the dry-run artifact.

Protected files include:

- authoritative `STATUS.json`
- package deliverables
- `app/tools/repair/*`
- `app/tools/audit/rule_repair_map.json`

Patch 20B creates no backups and no rollback files because those are future apply concerns, not dry-run planner actions.
