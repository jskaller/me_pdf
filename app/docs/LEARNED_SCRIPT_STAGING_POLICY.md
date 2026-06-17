# Learned Script Staging Policy

Patch 9 adds a reviewed path for moving a quarantined learned script into a canonical non-production staging area. It is a staging boundary only; it is not rule-map adoption and it is not production activation.

## Workflow

```text
promotion review packet
-> reviewed script promotion request
-> static safety checks
-> canonical staging copy
-> manifest + checksum
-> no rule-map mutation
-> no production activation
-> no final PDF adoption
```

## Staging directory

Reviewed scripts are staged under:

```text
app/tools/repair_staging/learned/
```

This directory is intentionally outside `app/tools/repair/`. The remediation pipeline must not import or execute scripts from staging automatically.

## CLI

Dry-run staging checks:

```bash
PYTHONPATH=app python3 app/tools/audit/promote_learned_strategy.py \
  --job-dir /app/workspace/jobs/SMOKE_SELF_EXTENSION_CLEAN \
  --candidate-id <candidate_id> \
  --stage-script-dry-run \
  --reviewed-by "operator"
```

Apply to staging only:

```bash
PYTHONPATH=app python3 app/tools/audit/promote_learned_strategy.py \
  --job-dir /app/workspace/jobs/SMOKE_SELF_EXTENSION_CLEAN \
  --candidate-id <candidate_id> \
  --stage-script \
  --reviewed-by "operator"
```

`--stage-script` requires both `--candidate-id` and `--reviewed-by`.

## Static checks

Before staging, the CLI verifies that the source script exists, remains under the job quarantine/self-extension area, matches the review-packet hash, has execution evidence, has no introduced/worsened rules, is review-required, and still has `script_location_status: quarantine_only`.

The script must compile and pass a pragmatic AST safety check. The checker rejects obvious unsafe constructs such as `eval`, `exec`, `compile`, `__import__`, dangerous network/process imports, `os.system`, destructive filesystem calls, and `os.environ` access.

## Artifacts

Every dry-run or apply attempt writes:

```text
JOB/audit/script_promotion_result.json
```

Successful apply also updates:

```text
app/tools/repair_staging/learned/manifest.json
```

Manifest entries are marked `status: staged_reviewed`, `production_active: false`, and `rule_map_applied: false`.

## Idempotency and conflicts

Re-staging the same candidate succeeds if the staged file already exists with the same SHA-256. If the destination exists with different content, the CLI fails closed. Patch 9 intentionally does not add an overwrite flag.

## Rule-map adoption remains separate

`--apply-rule-map` remains fail-closed:

```text
Rule-map apply is not implemented in this patch. Stage the script first; rule-map adoption is a separate reviewed step.
```

A later reviewed patch may adopt staged scripts into the rule map, but Patch 9 never mutates `app/tools/audit/rule_repair_map.json`, never copies to `app/tools/repair/*`, and never changes live Hermes behavior.

## Out of scope

Patch 9 does not implement production repair activation, automatic promotion, final PDF adoption, rule-map apply mode, live orchestrator behavior changes, or new production repair strategies.
## Patch 10 interaction

Script staging and rule-map adoption remain separate reviewed steps. A staged script is only eligible for rule-map dry-run/apply when `script_promotion_result.json` records the staged path, static-check status, reviewer, and staged script SHA-256.

The canonical rule map may reference only the staged path under `tools/repair_staging/learned/`; it must not reference the original job quarantine path. Staging does not imply production activation.
