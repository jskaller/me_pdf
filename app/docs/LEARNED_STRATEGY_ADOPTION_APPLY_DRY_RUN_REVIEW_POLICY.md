# Learned Strategy Adoption Apply Dry-Run Review Policy

Patch 21B records a review artifact over the apply dry-run simulation.

The review reads `JOB/audit/learned_strategy_adoption_apply_dry_run.json` and writes `JOB/audit/learned_strategy_adoption_apply_dry_run_review.json`.

The review must require reviewer identity, candidate id, rule id, apply dry-run simulation path, apply dry-run simulation hash, review notes, known risks, and an allowed review decision.

Allowed review decisions are:

- `apply_dry_run_review_recorded`
- `apply_dry_run_review_requires_followup`
- `apply_dry_run_review_rejected`

Forbidden review states include `approved`, `adoptable`, `production_ready`, `ready_for_adoption`, `adoption_unblocked`, `apply_ready`, `approved_for_apply`, `frozen_for_apply`, `apply_unblocked`, and `rollback_ready`.

If the artifact uses a freeze concept, it means only `apply_dry_run_evidence_snapshot_frozen_for_future_discussion`. It must never mean apply-ready.

The review is sidecar-only. It never performs adoption apply, never creates backups, never executes rollback, never mutates production repair, never mutates the rule map, never mutates authoritative status/package artifacts, and never adopts a final PDF.
