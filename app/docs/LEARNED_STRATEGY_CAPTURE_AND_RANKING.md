# Learned Strategy Capture and Ranking Contract

Patch 3 adds durable capture for empirical self-extension strategy outcomes. The capture artifact is review evidence only; it does not promote generated scripts, mutate the canonical repair map, adopt candidate PDFs, or replace verdict/status logic.

## Artifact location

For each job that invokes residual self-extension and produces a generation or candidate outcome, the executor writes:

```text
/app/workspace/jobs/<JOB>/audit/learned_strategies.json
```

The artifact is not written when self-extension is disabled and no generation/candidate event occurred.

## Purpose

`learned_strategies.json` records what the system tried, what evidence was available, what the generated candidate did, and why the result is or is not eligible for a later ranking/indexing patch. It preserves clean successes, dirty successes, partial improvements, validation failures, transport-blocked events, semantic refusals, needs-more-evidence responses, and boundary violations.

## Schema

The top-level artifact uses:

```json
{
  "schema_version": "learned-strategies.v1",
  "artifact": "learned_strategies",
  "records": []
}
```

Each record includes:

- `schema_version`
- `created_at`
- `run_id`
- `job_dir`
- `rule_id`
- `script_path`
- `script_sha256`
- `strategy`
- `args_pattern`
- `repair_order`
- `run_last`
- `proposed_resolvability`
- `outcome`
- `clean`
- `review_required`
- `pre_count`
- `post_count`
- `target_rule_strictly_decreased`
- `target_rule_resolved`
- `introduced_rules`
- `worsened_rules`
- `gate_results`
- `isolation_snapshot`
- `stdout_json`
- `generation_request`
- `generation_response`
- `candidate_result`
- `validation_artifacts`
- `attempt_number`
- `transport_attempts_used`
- `repair_attempts_used`
- `semantic_refusal_count`
- `needs_more_evidence_count`
- `failure_summary`
- `indexing_eligible`
- `indexing_blockers`

Missing information is represented as `null`, `{}`, or `[]`; important fields are not silently omitted.

## Outcome semantics

`clean_success` means the target rule resolved to zero or a documented future clean criterion, no new rules were introduced, no non-target rule worsened, the execution contract passed, required gates passed, candidate output exists and is non-empty, the input PDF hash stayed unchanged, and stdout JSON was parsed when the executor contract required it.

`partial_improvement` means the target count strictly decreased but remained nonzero. This is useful feedback for retry and later analysis, but it is not indexing-eligible in Patch 3.

`dirty_success` means the target resolved or improved, but introduced rules, worsened rules, failed gates, execution-contract issues, missing output, input mutation, or stdout-contract problems prevent clean indexing.

`validation_failed` means a candidate existed and ran far enough to produce a candidate result, but it did not improve the target rule.

`generation_failed` means generation did not produce usable `SCRIPT_SOURCE` and was not a more specific transport/refusal/boundary category.

`transport_blocked` means retryable gateway failures such as 429s/timeouts exhausted the transport budget. It must not consume repair attempt count and is never indexing-eligible.

`semantic_refusal` means the model returned `NOT_AUTOMATABLE` or an equivalent refusal instead of executable source. It is retained as evidence but never indexed.

`needs_more_evidence` means the model returned `NEEDS_MORE_EVIDENCE`. It is retained as evidence but never indexed.

`boundary_violation` means the generation response claimed side effects, execution, validation, or repository mutation instead of returning source for the executor to validate.

## Indexing eligibility

Only `clean_success` records are marked `indexing_eligible: true` in Patch 3. Patch 3 does not perform indexing. It only captures enough evidence for a later ranking/indexing patch to decide whether and how a strategy can be promoted.

Common `indexing_blockers` include:

- `target_rule_not_resolved`
- `target_rule_not_decreased`
- `introduced_rules:<rule ids>`
- `worsened_rules:<rule ids>`
- `failed_gates:<gate names>`
- `execution_contract_failed`
- `candidate_output_missing_or_empty`
- `input_pdf_hash_changed`
- `stdout_json_missing_or_unparseable`
- generation/refusal/transport outcome names

## Relationship to other artifacts

`residual_analysis.json` identifies targetable residual failures and the evidence envelope entering self-extension. `learned_strategies.json` records what happened after candidate generation/execution for those residuals.

`execution_log.json` records known-repair and orchestration execution evidence. `learned_strategies.json` is narrower: it captures self-extension candidate experiments and terminal generation events.

Run-state provides `run_id`, transport retry counts, repair attempt counts, semantic refusal counts, and needs-more-evidence counts. The learned-strategy record embeds those counters when available.

Self-extension attempt directories remain the source of detailed artifacts such as `generation_request.json`, `generation_response.json`, `candidate_result.json`, validation XML/JSON, and candidate stdout JSON. The learned-strategy artifact consolidates those references and key normalized fields.

Verdict/status packaging remains intentionally unchanged in Patch 3. A job can still end in `ESCALATION` while preserving useful learned-strategy records.

## Why canonical files are not mutated

Patch 3 does not mutate `app/tools/audit/rule_repair_map.json`, does not write into canonical `app/tools/repair/*` outside the existing quarantine/generated candidate path, and does not adopt generated candidate PDFs as final outputs. This protects production behavior while creating reviewable empirical evidence for future indexing.

## Later ranking/indexing patch

A future patch can consume `learned_strategies.json`, rank clean strategies by rule, inspect blockers and failure patterns, and propose controlled promotion into an index or rule-map workflow. That future patch must still perform its own review, compatibility checks, and canonical mutation controls.

## Patch 4: Learned Strategy Indexing Contract

Patch 4 replaces the old post-job indexing input model with learned-strategy-driven dry-run indexing.

### Inputs

The indexer consumes:

```text
JOB/audit/learned_strategies.json
JOB/audit/residual_analysis.json
app/tools/audit/rule_repair_map.json
```

`learned_strategies.json` is the primary indexing input. `residual_analysis.json` is preserved as evidence context when present. The canonical rule map is read to classify each proposed change, but dry-run mode does not mutate it.

### Output

The indexer writes:

```text
JOB/audit/strategy_indexing_report.json
```

The report includes:

- `schema_version`
- `created_at`
- `job_dir`
- `rule_map_path`
- `learned_strategies_path`
- `residual_analysis_path`
- `mode`
- `eligible_records`
- `indexed_records`
- `rejected_records`
- `proposed_rule_map_changes`
- `rejected_experiments`
- `warnings`
- `policy`

### Dry-run default

Patch 4 is dry-run only. It does not mutate `rule_repair_map.json`. It does not promote generated scripts into canonical repair folders. It does not adopt generated candidate PDFs. It does not rewrite verdict/status behavior.

### Eligibility

A learned strategy can produce a proposed rule-map change only when all of the following are true:

- `outcome == "clean_success"`
- `clean is true`
- `indexing_eligible is true`
- `indexing_blockers` is empty
- `rule_id` is present
- `script_path` is present
- `target_rule_resolved is true`
- `introduced_rules` is empty
- `worsened_rules` is empty
- gate results do not indicate failure

All other records are retained in `rejected_experiments` with explicit rejection reasons.

### Rule absent behavior

When the learned clean rule is absent from the map, the report proposes an `add_rule` change with a v2-shaped entry containing `strategies[]`, evidence counters, and review-required state. The canonical map is not changed in dry-run mode.

### `repairable_unbuilt` behavior

When a rule exists with `resolvability == "repairable_unbuilt"`, the report proposes attaching the clean generated strategy and marks the proposed resolvability as `effective_if_policy_allows`. Dry-run does not promote the rule.

### `repairable_review` behavior

When a rule exists with `resolvability == "repairable_review"`, the report proposes attaching the clean generated strategy while preserving review semantics. It does not silently mark the rule effective.

### Existing effective strategy behavior

When a rule already has an effective primary strategy, the report does not overwrite it. The clean generated strategy is proposed as an alternate, edge-case, or lower-ranked strategy.

### Ranking and evidence fields

Each proposed strategy includes:

- `source: "learned_strategy_capture"`
- `repair_script`
- `script_path`
- `script_sha256`
- `strategy`
- `args_pattern`
- `repair_order`
- `run_last`
- `repair_order_validated_by_isolated_evidence`
- `run_last_validated_by_isolated_evidence`
- `clean_pass_count`
- `pass_count`
- `fail_count`
- `pass_rate`
- `doc_type_stats`
- `introduced_rules`
- `worsened_rules`
- `gate_results`
- `known_failure_modes`
- `review_required`
- `last_observed_at`
- `evidence`

The indexer preserves LLM-proposed `repair_order` and `run_last` as proposed fields only. They are not treated as validated by isolated evidence.

### Rejected experiments

Dirty successes, partial improvements, validation failures, transport-blocked events, semantic refusals, needs-more-evidence events, and malformed/non-eligible records are retained as rejected experiments. They are not proposed as canonical repair strategies.

### Non-goals

Patch 4 does not implement:

- final-PDF adoption of generated candidates
- moving generated scripts into canonical `tools/repair/`
- broad verdict/status rewrite
- Hermes signal reconciliation rewrite
- execution-log subprocess fidelity upgrade
- new PDF repair strategies
- live gateway behavior changes
- mandatory indexing on `ESCALATION` jobs
- automatic rule-map mutation by default
