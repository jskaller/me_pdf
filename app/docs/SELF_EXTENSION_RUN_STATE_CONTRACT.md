# Self-Extension Run-State Contract

Patch scope: run-state hygiene, stale artifact isolation, and retry/attempt accounting for the PDF/UA residual self-extension loop.

## Authoritative artifact

The current run is defined by:

```text
audit/self_extension_run_state.json
```

This artifact is authoritative for self-extension counters in the current orchestrator invocation. Legacy artifacts such as `self_extension_call_budget.json` are preserved for forensics but are not authoritative for the current run.

## Run identity

Each self-extension run starts with a fresh opaque `run_id`. The run-state artifact records:

- `run_id`
- `started_at`
- `job_dir`
- `source_pdf` and `source_pdf_hash` when available
- `current_pdf` and `current_pdf_hash` when available
- `residual_gap_entry_anchor` when available
- the selected target rule, if any

A copied job directory must not inherit live counters from an older run.

## Stale artifact behavior

If an existing run-state or legacy budget file is present when a new run starts, it is treated as stale evidence. It is copied under:

```text
audit/self_extension_previous_runs/
```

The new run records that stale artifacts existed, where they were archived, that they were superseded by the new `run_id`, and that they were ignored for budget accounting. Evidence is not silently deleted.

## Accounting model

Counters are intentionally separate:

- `generation_call_count`: a gateway generation call was attempted.
- `transport_retries_used`: a retry was reserved after a retryable transport failure.
- `transport_failure_count`: a 429, timeout, or other retryable gateway transport failure was observed and recorded.
- `repair_attempts_used`: an actual generated repair candidate was written/executed/validated.
- `candidate_attempt_count`: same domain as repair attempts, maintained explicitly for reporting.
- `semantic_refusal_count`: LLM returned `NOT_AUTOMATABLE` or `NEEDS_MORE_EVIDENCE` instead of `SCRIPT_SOURCE`.
- `needs_more_evidence_count`: the subset of semantic refusals that specifically requested more evidence.
- `boundary_violation_count`: generation response violated the source-generation boundary.
- `validation_failure_count`: a candidate executed/validated but failed the target validation predicate.

## 429 and timeout handling

HTTP 429 and timeout-like gateway failures are retryable transport failures. They must:

- increment `transport_failure_count`
- preserve a failure artifact under `audit/self_extension_transport_failures/`
- consume `transport_retries_used` only when a retry is actually reserved
- not increment `repair_attempts_used`
- not increment `candidate_attempt_count`

When transport retry budget is exhausted, the outcome is:

```text
TRANSPORT_BLOCKED
```

This is distinct from candidate validation failure, semantic refusal, and not-automatable outcomes.

## Backoff policy

Backoff is deterministic and testable. `Retry-After` is honored when a failure record exposes `retry_after` or `retry_after_seconds`. Otherwise exponential backoff starts from one second and is capped. Tests must inject a no-op sleep function.

TODO: If the gateway wrapper later exposes structured HTTP response headers, thread the raw `Retry-After` header into the failure record.

## No-adoption discipline

This patch does not:

- mutate `app/tools/audit/rule_repair_map.json`
- promote generated scripts
- index learned strategies
- replace canonical repair scripts
- change final packaged PDF paths based on generated candidates
- implement residual analyzer or learned-strategy capture

Generated candidates remain quarantine evidence only.
