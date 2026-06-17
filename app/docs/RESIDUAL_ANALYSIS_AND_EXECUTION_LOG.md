# Residual Analysis and Execution Log

Patch scope: residual analyzer plus execution log only.

This patch does not implement learned-strategy capture, learned strategy
indexing, rule-map promotion, generated-script adoption, new repair strategies,
or a broad verdict rewrite.

## Authoritative inputs

`audit/residual_analysis.json` is computed after post-known-repair veraPDF from:

- `audit/failures.json`
- `audit/failures_post.json`
- `audit/repair_plan.json`
- `audit/execution_log.json`
- `app/tools/audit/rule_repair_map.json`

Raw `failures_post.json` remains a validator artifact, but it is not sufficient
for self-extension routing because it cannot distinguish incidental resolution,
persistent repair attempts, no-effect detector/wiring attempts, introduced
rules, and never-attempted repairable rules.

## `audit/execution_log.json`

The execution log records deterministic facts about known repair steps. The
current orchestrator does not persist per-command stdout/stderr sidecars for
every repair command, so Patch 2 records conservative command/tool identifiers,
rule targets, whether attempt evidence exists, and whether an output PDF was
associated with a successful attempt.

Result categories:

- `ran_success`
- `ran_failed`
- `skipped_no_strategy`
- `skipped_not_auto_fixable`
- `skipped_review_required`
- `skipped_guard_disabled`
- `not_applicable`

## `audit/residual_analysis.json`

Each per-rule record includes:

- `rule_id`
- `baseline_count`
- `post_count`
- `delta`
- baseline/post presence booleans
- repair-plan entries
- execution-log entries
- normalized resolvability
- outcome
- `partially_resolved`
- `targetable_by_self_extension`
- `review_required`
- `pending_review`
- `escalation_required`
- reason

## Outcome precedence

1. `resolved`: baseline failure cleared and a real repair output was recorded.
2. `resolved_incidental`: baseline failure cleared without a matching repair output.
3. `introduced`: absent from baseline and present after known repairs.
4. `escalated`: unresolved and not safely automatable or detector-mislabeled.
5. `attempted_no_effect`: a mapped step ran but produced no repair output, or
   output existed without reducing the failure count.
6. `persistent`: a repair output existed and the rule still appears.
7. `never_attempted`: unresolved, repairable/reviewable, and no repair output
   was recorded.

`partially_resolved` is diagnostic only. It never softens verdict.

## Self-extension routing

Self-extension target selection prefers `targetable_residual_rules` from
`residual_analysis.json`.

Current contract policy:

- targetable: `never_attempted`
- targetable: `introduced`
- targetable resolvability classes: `repairable_unbuilt`, `repairable_review`,
  missing/unknown map entries treated as unbuilt repair gaps
- not targetable: `not_auto_fixable`, `detector_mislabeled`, legacy
  `manual:true` with no strategies

`repairable_review` is targetable, but its successful path must preserve review
semantics through `pending_review`/review-package behavior.

## Mixed rule-map compatibility

The analyzer does not rewrite `rule_repair_map.json`.

Compatibility normalization:

- explicit `resolvability` wins
- legacy `status` or `confidence` of `HERMES_REQUIRED`, `UNKNOWN`, or `UNBUILT`
  becomes `repairable_unbuilt`
- `manual:true` with no strategies becomes `legacy_manual_review`
- non-manual empty strategies become `repairable_unbuilt`
- strategies with repair scripts become `effective`

## Patch 6: execution-log v2 fidelity contract

`audit/execution_log.json` now uses the v2 top-level compatibility shape:

```json
{
  "schema_version": "execution-log.v2",
  "artifact": "execution_log",
  "created_at": "...",
  "updated_at": "...",
  "job_dir": "...",
  "run_id": "...",
  "records": [],
  "repair_steps": []
}
```

`records` is the authoritative ledger. `repair_steps` remains as a derived
compatibility view for older residual-analysis and status consumers.

Record types are:

- `repair_step`
- `validation_step`
- `self_extension_generation`
- `self_extension_candidate`
- `transport_event`
- `semantic_refusal`
- `needs_more_evidence`
- `boundary_violation`

Repair-step records may include: `attempt_id`, `run_id`, `iteration`,
`step_name`, `strategy`, `script`, `callable`, `rules_targeted`, `input_pdf`,
`input_pdf_sha256`, `output_pdf`, `output_pdf_sha256`, `output_exists`,
`output_size`, `started_at`, `finished_at`, `duration_ms`, `exit_code`,
`exception_type`, `exception_message`, `stdout_path`, `stderr_path`,
`stdout_sha256`, `stderr_sha256`, `command`, `argv`, `cwd`,
`environment_summary`, `validation_artifacts`, pre/post rule counts, target-rule
progress fields, QA results, and notes.

Subprocess executions write stdout/stderr sidecars under:

- `JOB/audit/execution/stdout/<attempt_id>.txt`
- `JOB/audit/execution/stderr/<attempt_id>.txt`

The JSON stores paths and SHA-256 hashes only; it does not inline large output.
Callable repair steps use the same record shape but set `callable` rather than
requiring `argv`/`exit_code`.

Failures are persisted as first-class evidence. A failed subprocess or callable
record still includes timestamps, duration, input hash, exception or exit code,
stdout/stderr sidecar paths when applicable, and `result: FAIL`.

Residual analysis now reads both `records` and the compatibility `repair_steps`
view. Per-rule records expose `execution_attempt_ids`, allowing unresolved and
resolved residuals to point back to the concrete attempts that affected them.

Learned-strategy capture preserves execution evidence references when a
self-extension candidate result supplies them: `execution_attempt_id`,
`execution_log_path`, `stdout_path`, `stderr_path`, and validation artifacts.

What may remain inferred: if an old caller only provides `strategy_attempts`,
`build_execution_log_from_repair_steps()` still emits v2 records but marks them
with `inferred: true` and `inferred_from_strategy_attempts: true`. Patch 6 callers
should append real execution records during execution instead.

Patch 6 remains intentionally non-promotional: it does not mutate the canonical
rule map, does not move generated scripts into `app/tools/repair/`, and does not
adopt generated candidate PDFs as final output.

