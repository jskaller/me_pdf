# Learned Rule-Map Adoption Policy

Patch 10 adds a reviewed rule-map adoption workflow for learned strategies. It is intentionally staged-script-only and review-only by default.

## Boundary

The permitted flow is:

```text
clean learned strategy
-> strategy_promotion_review.json
-> reviewed script staging
-> script_promotion_result.json
-> rule-map adoption dry-run
-> optional explicit reviewed rule-map apply
```

Patch 10 does **not**:

- adopt final PDFs
- copy learned scripts into `app/tools/repair/*`
- run remediation
- activate staged scripts as production defaults
- change verdict/status behavior
- make escalation jobs mandatory adoption jobs

## Prerequisites

Rule-map dry-run and apply require:

- a clean learned strategy candidate in `strategy_promotion_review.json`
- `--candidate-id`
- a prior `script_promotion_result.json`
- a staged script under `tools/repair_staging/learned/`
- matching staged script hash
- no quarantine path references in the rule-map metadata
- no dirty, failed, refusal, introduced-rule, or worsened-rule blockers

Apply additionally requires `--reviewed-by`.

## Commands

Create the promotion review packet:

```bash
PYTHONPATH=app python3 app/tools/audit/promote_learned_strategy.py \
  --job-dir /app/workspace/jobs/SMOKE_SELF_EXTENSION_CLEAN \
  --dry-run
```

Stage the already-reviewed script into the non-production staging area:

```bash
PYTHONPATH=app python3 app/tools/audit/promote_learned_strategy.py \
  --job-dir /app/workspace/jobs/SMOKE_SELF_EXTENSION_CLEAN \
  --candidate-id "$CID" \
  --stage-script \
  --reviewed-by "operator"
```

Preview the rule-map adoption without mutation:

```bash
PYTHONPATH=app python3 app/tools/audit/promote_learned_strategy.py \
  --job-dir /app/workspace/jobs/SMOKE_SELF_EXTENSION_CLEAN \
  --candidate-id "$CID" \
  --rule-map-dry-run
```

Apply reviewed, non-active staged metadata:

```bash
PYTHONPATH=app python3 app/tools/audit/promote_learned_strategy.py \
  --job-dir /app/workspace/jobs/SMOKE_SELF_EXTENSION_CLEAN \
  --candidate-id "$CID" \
  --apply-rule-map \
  --reviewed-by "operator"
```

## Artifacts

Dry-run writes:

```text
JOB/audit/rule_map_adoption_review.json
```

Apply writes:

```text
JOB/audit/rule_map_apply_result.json
```

Apply also creates a timestamped backup under:

```text
app/tools/audit/backups/rule_repair_map.<timestamp>.json
```

Backup files are intentionally ignored by git.

## Non-active semantics

Patch 10 writes learned rule-map metadata only under:

```json
"reviewed_learned_strategies": []
```

Each staged entry is marked:

```json
{
  "source": "learned_strategy_staged",
  "production_active": false,
  "activation_status": "staged_review",
  "review_required": true
}
```

The active `strategies` array is preserved. Existing effective primary strategies are not overwritten. Existing `repairable_unbuilt` and `repairable_review` entries preserve review-required semantics.

## Quarantine boundary

Canonical rule-map metadata must reference the staged script path, for example:

```text
tools/repair_staging/learned/<safe_name>.py
```

It must never reference job quarantine paths such as:

```text
audit/self_extension/quarantine/...
/app/workspace/jobs/...
```

## Rollback

Use the backup path recorded in `rule_map_apply_result.json`:

```bash
cp app/tools/audit/backups/rule_repair_map.<timestamp>.json app/tools/audit/rule_repair_map.json
python3 -m json.tool app/tools/audit/rule_repair_map.json >/dev/null
git diff -- app/tools/audit/rule_repair_map.json app/tools/repair
```

## Out of scope

Future patches may define a separate, explicit production activation workflow. Patch 10 only records reviewed staged strategy metadata and does not make it executable by the production repair runtime.


## Patch 11 activation policy cross-reference

Reviewed staged learned strategies are not runtime-active merely because they are present in the canonical rule map. Patch 11 adds a separate dry-run/apply/deactivate activation policy documented in `app/docs/LEARNED_STRATEGY_ACTIVATION_POLICY.md`. Activation requires explicit `--rule-id`, `--candidate-id`, and `--reviewed-by`, verifies the staged script path and SHA-256, backs up the rule map before mutation, never moves scripts into `app/tools/repair/*`, and never adopts final PDFs.
