# Learned Strategy Adoption Apply Policy Design

Patch 21A defines the policy contract for a future reviewed learned-strategy
adoption apply workflow. It is policy/design only. It does not implement adoption
apply, rollback execution, backup creation, candidate approval, candidate
adoptability, production-ready marking, apply-ready marking, default learned
execution, production repair replacement, package/status mutation, verdict
softening, or final PDF adoption.

The normal final PDF remains authoritative. The existing package/status/verdict
flow remains authoritative.

## Command

```bash
PYTHONPATH=app python3 app/tools/audit/learned_strategy_adoption_apply_policy_design.py \
  --job-dir JOB \
  --dry-run-review JOB/audit/learned_strategy_adoption_dry_run_review.json \
  --reviewer "Reviewer Name" \
  --candidate-id CANDIDATE_ID \
  --rule-id RULE_ID
```

The command writes only:

```text
JOB/audit/learned_strategy_adoption_apply_policy_design.json
```

It reads:

```text
JOB/audit/learned_strategy_adoption_dry_run_review.json
```

## Required source artifact

The source dry-run review artifact must exist and must remain non-adoptive. It
must be review-only evidence over a Patch 20B adoption dry-run plan. Patch 21A
must reject or block source artifacts that imply approval, adoptability,
production readiness, apply readiness, adoption unblocking, backup creation,
rollback execution, final PDF adoption, production repair replacement,
package/status mutation, rule-map mutation, or `app/tools/repair/*` mutation.

## Allowed outcomes

Allowed outcomes are design-only and non-operative:

```text
apply_policy_design_recorded
apply_policy_design_incomplete
apply_policy_design_blocked
```

## Forbidden states and outcomes

The artifact must not use or imply any of these states or outcomes:

```text
approved
adoptable
production_ready
ready_for_adoption
adoption_unblocked
apply_ready
approved_for_apply
frozen_for_apply
apply_plan_created
apply_unblocked
rollback_ready
```

## Mandatory safety flags

Every artifact records these safety flags:

```json
{
  "adoption_apply_policy_design_only": true,
  "apply_policy_design_recorded": true,
  "apply_plan_created": false,
  "adoption_apply_performed": false,
  "backup_created": false,
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
  "future_apply_not_implemented": true,
  "future_rollback_not_implemented": true
}
```

## Future apply policy requirements

Patch 21A may define what a future apply policy must require. It must not create
an apply plan or say an apply is ready.

A future apply patch must require, at minimum:

- reviewer identity from the dry-run review evidence
- separate approver identity in the future patch
- candidate id and rule id
- dry-run review artifact path and hash
- dry-run plan artifact path and hash
- this policy design artifact path and hash recorded by the future patch
- production readiness report path and hash
- production test report path and hash
- production test review report path and hash
- normal final PDF path and hash
- learned trial/test PDF path and hash
- future backup manifest before any mutation
- future rollback manifest before any mutation
- future rollback verification requirements
- future allowed mutation list
- future forbidden mutation list
- future apply command family
- future explicit `--apply` requirement
- future explicit `--rollback` requirement
- future post-apply validation requirements
- future post-rollback validation requirements

## Future allowed mutation list policy text only

A future apply patch may define narrowly scoped mutation targets, but Patch 21A
permits no mutation. Any future allowed list must be explicit, reviewed,
backed up by hash, and separately invoked with an explicit `--apply` flag.

## Future forbidden mutation list policy text only

The future contract must continue to protect the normal final PDF authority,
package/status authority, broad `app/tools/repair/*` mutation, broad rule-map
mutation, verdict softening, and unreviewed learned execution.

## Future backup and rollback policy text only

Patch 21A creates no backups and executes no rollback. It only states that a
future patch must create and verify a backup manifest before any apply mutation,
and must define an explicit rollback command and rollback verification manifest.

## Future validation policy text only

A future apply patch must define post-apply and post-rollback validation gates.
Patch 21A records those requirements as policy text only and does not run or
unblock any apply workflow.
