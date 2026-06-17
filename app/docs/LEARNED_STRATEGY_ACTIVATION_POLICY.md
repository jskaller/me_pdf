# Learned Strategy Activation Policy

Patch 11 adds an explicit activation path for reviewed staged learned strategies already present in `app/tools/audit/rule_repair_map.json` as non-production review metadata.

The policy is intentionally opt-in and fail-closed:

```text
reviewed_learned_strategy in rule map
-> activation dry-run
-> activation checks
-> explicit activation apply with reviewed-by
-> production_active true / activation_status active
-> optional later runtime discovery
-> explicit deactivation / rollback
```

## Scope

Patch 11A implements activation metadata and rollback. It does not move staged scripts into `app/tools/repair/*`, does not adopt final PDFs, does not run remediation, and does not automatically activate anything from self-extension or promotion output.

Runtime discovery of active staged learned strategies is intentionally not enabled in this patch. Existing runtime repair selection continues to use built-in `strategies[]`; inactive `reviewed_learned_strategies` remain ignored because the runtime does not execute that section.

## Activation prerequisites

Activation is permitted only when all of the following pass:

- the `rule_id` exists in the canonical rule map
- the selected `candidate_id` exists in a reviewed learned-strategy section such as `reviewed_learned_strategies`
- the selected strategy has `production_active: false`
- the selected strategy has `activation_status: staged_review`
- review metadata remains present, such as `review_required: true` or `activation_review_required: true`
- the staged script path exists
- the staged script path is under `app/tools/repair_staging/learned/` or `/app/tools/repair_staging/learned/`
- the staged script SHA-256 in the rule map matches the file
- static safety checks pass
- dirty, failed, and refusal metadata are absent
- Patch 10 evidence metadata is present

## Dry-run command

```bash
PYTHONPATH=app python3 app/tools/audit/promote_learned_strategy.py \
  --rule-id "PDF/UA-1/7.21.7" \
  --candidate-id "$CID" \
  --activation-dry-run \
  --job-dir workspace/jobs/SMOKE_SELF_EXTENSION_CLEAN
```

Dry-run writes `activation_review.json` under `JOB/audit/` when `--job-dir` is supplied. Without `--job-dir`, it writes under `app/tools/audit/activation_artifacts/`. Dry-run never mutates the rule map.

## Apply command

```bash
PYTHONPATH=app python3 app/tools/audit/promote_learned_strategy.py \
  --rule-id "PDF/UA-1/7.21.7" \
  --candidate-id "$CID" \
  --activate \
  --reviewed-by "operator" \
  --job-dir workspace/jobs/SMOKE_SELF_EXTENSION_CLEAN
```

Apply requires `--rule-id`, `--candidate-id`, and `--reviewed-by`. It backs up `rule_repair_map.json` before mutation, updates only the selected staged learned strategy, and writes `activation_apply_result.json`.

The selected strategy changes are limited to activation metadata:

- `production_active: true`
- `activation_status: active`
- `activated_by`
- `activated_at`
- `activation_review_required: false`
- `review_required: false` only for the selected strategy if it was previously true

Existing primary `strategies[]` are preserved exactly as-is.

## Deactivation command

```bash
PYTHONPATH=app python3 app/tools/audit/promote_learned_strategy.py \
  --rule-id "PDF/UA-1/7.21.7" \
  --candidate-id "$CID" \
  --deactivate \
  --reviewed-by "operator" \
  --job-dir workspace/jobs/SMOKE_SELF_EXTENSION_CLEAN
```

Deactivation backs up the rule map, marks only the selected strategy inactive, preserves evidence metadata, does not delete the staged script, and writes `activation_deactivate_result.json`.

The selected strategy changes are limited to:

- `production_active: false`
- `activation_status: deactivated`
- `deactivated_by`
- `deactivated_at`

## Backup behavior

Every activation or deactivation apply creates a backup beside the rule map under:

```text
app/tools/audit/rule_map_activation_backups/
```

The result artifact records the exact `backup_path`.

## Fail-closed behavior

If a staged script is missing, outside the approved staging directory, hash-mismatched, unreadable, syntactically invalid, or fails static safety checks, the command writes a blocked artifact and returns a non-zero status. It does not mutate the canonical rule map.

## Runtime discovery behavior

Patch 11A does not add runtime discovery. That is intentionally reserved for a later Patch 11B so activation metadata can be reviewed and tested independently from execution behavior.

When runtime discovery is added later, it must remain fail-closed and may only consider staged learned strategies that are all of:

- `production_active: true`
- `activation_status: active`
- hash-valid
- under the approved staging directory
- free of dirty, failed, or refusal metadata

The safe default ordering for any future runtime discovery is built-in strategies first; active staged learned strategies may be considered only after built-in strategies are absent or exhausted.

## Out of scope

Patch 11 does not implement:

- automatic activation
- automatic final-PDF adoption
- script movement into `app/tools/repair/*`
- automatic promotion from self-extension output
- live Hermes behavior changes
- new unreviewed production repair strategies
- broad verdict/status rewrites
- mandatory activation on escalation jobs
- skipping hash or static safety checks
