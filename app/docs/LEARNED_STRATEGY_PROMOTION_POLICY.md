# Learned Strategy Promotion Policy

Patch 8 adds a reviewed, dry-run-first promotion workflow for learned strategies.
It is intentionally a review boundary, not an adoption mechanism.

## Workflow

```text
clean learned strategy
-> dry-run indexing proposal
-> strategy_promotion_review.json
-> human review
-> future explicit apply-capable patch, if approved
```

Patch 8 does not automatically promote generated scripts, mutate the canonical
rule map, adopt generated PDFs, or change live Hermes/orchestrator behavior.

## CLI

Create a review packet:

```bash
PYTHONPATH=app python3 app/tools/audit/promote_learned_strategy.py \
  --job-dir /app/workspace/jobs/SMOKE_SELF_EXTENSION_CLEAN \
  --dry-run
```

Optional filters:

```bash
PYTHONPATH=app python3 app/tools/audit/promote_learned_strategy.py \
  --job-dir /app/workspace/jobs/SMOKE_SELF_EXTENSION_CLEAN \
  --rule-id PDF/UA-1/7.18.6.3 \
  --dry-run
```

```bash
PYTHONPATH=app python3 app/tools/audit/promote_learned_strategy.py \
  --job-dir /app/workspace/jobs/SMOKE_SELF_EXTENSION_CLEAN \
  --candidate-id <candidate_id> \
  --dry-run
```

Output defaults to:

```text
JOB/audit/strategy_promotion_review.json
```

## Review packet fields

The packet includes:

- `schema_version`
- `created_at`
- `job_dir`
- `source_strategy_indexing_report`
- `source_learned_strategies`
- `source_residual_analysis`
- `source_execution_log`
- `rule_map_path`
- `mode`
- `promotion_candidates`
- `rejected_candidates`
- `review_required: true`
- `policy`
- `operator_instructions`

Each promotion candidate includes:

- `candidate_id`
- `rule_id`
- `action`
- `proposed_rule_map_patch`
- `current_rule_map_entry`
- `proposed_rule_map_entry`
- `script_path`
- `script_sha256`
- `script_location_status`
- `execution_attempt_id`
- `execution_log_path`
- `stdout_path`
- `stderr_path`
- `learned_strategy_record_id`
- `learned_strategy_record_hash`
- `residual_analysis_path`
- `residual_analysis_sha256`
- `validation_artifacts`
- `gate_results`
- `introduced_rules`
- `worsened_rules`
- `clean_pass_count`
- `fail_count`
- `pass_rate`
- `review_required`
- `review_reasons`
- `promotion_blockers`
- `safe_to_apply_rule_map_patch`

## Candidate actions

Patch 8 normalizes indexer proposal actions into review actions:

- `add_rule`
- `attach_strategy`
- `add_alternate_strategy`
- `preserve_review_strategy`

Existing effective primary strategies are preserved. A clean learned strategy for
an already-effective rule becomes an alternate/edge-case proposal, not an
overwrite.

`repairable_review` rules preserve review-required semantics. A clean candidate
for such a rule remains review-required unless a later explicit, reviewed
operator action changes that policy.

## Rejected candidates

Dirty, failed, partial, transport-blocked, and semantic-refusal records are not
promotion candidates. They appear as `rejected_candidates` with explicit reasons
from the strategy indexer plus promotion blockers.

Rejected experiments are retained as evidence and learning material only.

## No-adoption boundary

Patch 8 policy records and enforces these boundaries:

- canonical rule-map mutation performed: `false`
- generated script promotion performed: `false`
- final PDF adoption performed: `false`
- generated scripts must remain `quarantine_only`
- production runtime must not depend on quarantined scripts

A candidate with a script outside the job quarantine receives a blocker.

## Apply mode

`--apply-rule-map` intentionally fails closed in Patch 8:

```bash
PYTHONPATH=app python3 app/tools/audit/promote_learned_strategy.py \
  --job-dir /app/workspace/jobs/SMOKE_SELF_EXTENSION_CLEAN \
  --candidate-id <candidate_id> \
  --apply-rule-map \
  --reviewed-by operator
```

Expected result: nonzero exit with a message saying apply mode is not
implemented in Patch 8.

A future apply-capable patch must, at minimum:

- require `--apply-rule-map`
- require `--candidate-id`
- require `--reviewed-by`
- create a timestamped backup of `rule_repair_map.json`
- write `JOB/audit/strategy_promotion_apply_result.json`
- apply only reviewed rule-map metadata or strategy references
- never copy generated scripts into `app/tools/repair/*`
- never adopt generated PDFs
- fail closed on dirty candidates, introduced rules, worsened rules, missing
  execution evidence, script hash mismatch, outside-quarantine scripts, schema
  surprises, or attempts to overwrite effective primary strategies

## Smoke-harness workflow

Patch 7 fake-clean smoke can produce source artifacts for the promotion packet:

```bash
docker compose exec hermes bash -lc '
cd /app &&
PYTHONPATH=/app python3 tools/dev/self_extension_smoke.py \
  --job-dir /app/workspace/jobs/SMOKE_SELF_EXTENSION_CLEAN \
  --mode fake-clean
'
```

Then create the Patch 8 review packet:

```bash
docker compose exec hermes bash -lc '
cd /app &&
PYTHONPATH=/app python3 tools/audit/promote_learned_strategy.py \
  --job-dir /app/workspace/jobs/SMOKE_SELF_EXTENSION_CLEAN \
  --dry-run
'
```

Inspect:

```bash
docker compose exec hermes bash -lc '
JOB=/app/workspace/jobs/SMOKE_SELF_EXTENSION_CLEAN
python3 -m json.tool "$JOB/audit/strategy_promotion_review.json" | head -260
'
```

Confirm no canonical mutation:

```bash
git status --short
git diff -- app/tools/audit/rule_repair_map.json app/tools/repair
```

## Rollback

Patch 8 adds only the promotion CLI, tests, and this policy document. It does not
write rule-map backups because apply mode is not implemented. Rollback is a
normal git revert of the Patch 8 commit.
