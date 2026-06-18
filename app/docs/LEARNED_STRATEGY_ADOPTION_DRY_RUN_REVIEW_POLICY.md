# Learned Strategy Adoption Dry-Run Review Policy

Patch 20C adds a review/freeze gate over the Patch 20B adoption dry-run plan.
It is evidence review only. It does not implement adoption apply, rollback,
backup creation, candidate approval, candidate adoptability, production-ready
marking, apply-ready marking, default learned execution, production repair
replacement, package/status mutation, or final PDF adoption.

The normal final PDF remains authoritative. The existing package/status/verdict
flow remains authoritative.

## Command

```bash
PYTHONPATH=app python3 app/tools/audit/learned_strategy_adoption_dry_run_review.py \
  --job-dir JOB \
  --dry-run-plan JOB/audit/learned_strategy_adoption_dry_run_plan.json \
  --dry-run-plan-sha256 SHA256 \
  --reviewer "Reviewer Name" \
  --candidate-id CANDIDATE_ID \
  --rule-id RULE_ID \
  --review-decision dry_run_review_recorded \
  --review-notes "Evidence reviewed; no approval, no adoption, no apply." \
  --known-risks "Known risks recorded for future discussion only."
```

The command writes only:

```text
JOB/audit/learned_strategy_adoption_dry_run_review.json
```

It reads:

```text
JOB/audit/learned_strategy_adoption_dry_run_plan.json
```

## Required inputs

The review command requires:

- reviewer identity
- candidate id
- rule id
- dry-run plan path
- dry-run plan hash
- review notes
- known risks
- review decision

The supplied candidate id, rule id, and dry-run plan hash must match the dry-run
plan artifact.

## Allowed review decisions

Allowed decisions are non-adoptive only:

```text
dry_run_review_recorded
dry_run_review_requires_followup
dry_run_review_rejected
```

## Forbidden states and decisions

The review artifact must not use or imply any of these terminal states:

```text
approved
adoptable
production_ready
ready_for_adoption
adoption_unblocked
apply_ready
approved_for_apply
frozen_for_apply
```

If the artifact uses a freeze concept, it means only:

```text
evidence_snapshot_frozen_for_future_discussion
```

That freeze is not approval, adoptability, production readiness, apply readiness,
or an adoption unblock.

## Mandatory safety flags

Every non-blocked review artifact records:

```json
{
  "adoption_dry_run_review_only": true,
  "dry_run_plan_reviewed": true,
  "dry_run_plan_hash_recorded": true,
  "candidate_is_adoptable": false,
  "candidate_approved": false,
  "candidate_production_ready": false,
  "candidate_apply_ready": false,
  "adoption_apply_performed": false,
  "backup_created": false,
  "rollback_execution_performed": false,
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

## Mutation policy

Patch 20C may create only the dry-run review artifact. It must not create apply
backups, rollback files, replacement repair scripts, package/status rewrites, rule
map edits, or changes under `app/tools/repair/*`.

The command snapshots protected files before and after review artifact creation.
Protected mutation detection blocks the review artifact.

## Future patch boundary

A future adoption apply patch would have to be separately designed, separately
reviewed, and explicitly invoked. Patch 20C does not make the candidate approved,
adoptable, production-ready, ready for adoption, apply-ready, frozen for apply, or
unblocked.
