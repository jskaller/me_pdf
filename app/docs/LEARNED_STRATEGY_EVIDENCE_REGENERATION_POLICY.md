# Learned Strategy Evidence Regeneration Policy

Patch 22B adds a conservative evidence-regeneration sidecar for the learned
strategy adoption dry-run chain.

The helper is diagnostic-only. It may locate and record existing upstream
evidence artifacts, and it may record missing or unverifiable evidence, but it
must not approve, adopt, apply, replace, roll back, soften verdicts, mutate
package/status outputs, mutate `app/tools/repair`, or mutate the authoritative
rule map.

## Evidence covered

Patch 22B focuses on the remaining upstream evidence hash gaps:

- `learned_trial_or_test_pdf_sha256`
- `production_readiness_report_sha256`
- `production_test_report_sha256`

The helper records each target as one of:

- `artifact_reused_existing`
- `artifact_missing`
- `artifact_unverifiable`

`artifact_regenerated` is reserved for a future explicitly reviewed command
runner. This patch does not introduce default learned execution or automatic
production-test execution.

## Required safety state

Every Patch 22B evidence-regeneration artifact must state the mandatory
no-apply/no-adoption/no-mutation flags, including `evidence_regeneration_only:
true`, `adoption_apply_performed: false`, `backup_created: false`,
`rollback_execution_performed: false`, and
`normal_final_pdf_remains_authoritative: true`.

## Outcomes

Allowed helper outcomes are:

- `evidence_regeneration_recorded`
- `evidence_regeneration_incomplete`
- `evidence_regeneration_blocked`

Forbidden terminal states are rejected in candidate/rule inputs and must never be
used as successful outcomes: approved, adoptable, production_ready,
ready_for_adoption, adoption_unblocked, apply_ready, approved_for_apply,
frozen_for_apply, apply_unblocked, rollback_ready, apply_performed,
rollback_performed, and backup_created.

## Relationship to evidence hashing

The existing evidence hashing helper remains the source of normalized hashes for
the apply dry-run chain. Patch 22B narrows its discovery names so the current
producer artifacts are consumed directly:

- `learned_strategy_production_testing_readiness_report.json`
- `learned_strategy_production_test_report.json`
- `learned_strategy_replacement_trial_report.json`

Hash completion is evidence completeness for dry-run simulation only. It is not
approval, adoptability, production readiness, apply readiness, or adoption
unblocking.
