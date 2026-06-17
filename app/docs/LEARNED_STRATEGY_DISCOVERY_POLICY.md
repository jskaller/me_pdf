# Learned Strategy Discovery Policy

Patch 12A adds a discovery-only layer for reviewed learned strategies that have already been explicitly activated in the canonical rule map. Discovery is not execution.

## Boundary

Patch 12A may inspect `reviewed_learned_strategies` metadata, validate staged paths, validate staged script hashes, run static checks, and write an audit artifact. It must not import staged learned scripts, shell out to staged scripts, execute staged scripts, move scripts into `app/tools/repair/*`, mutate the rule map, adopt final PDFs, or change normal remediation behavior.

Activation metadata alone is not enough. A learned strategy is only discoverable when all discovery checks pass.

## Inclusion criteria

A reviewed learned strategy can appear in `discovered_strategies` only when:

* it is under `reviewed_learned_strategies`
* `source == "learned_strategy_staged"`
* `production_active is true`
* `activation_status == "active"`
* `candidate_id` is present
* a staged script path is present
* the staged path resolves under `app/tools/repair_staging/learned/`
* the staged script exists
* the staged script SHA-256 matches rule-map metadata
* static safety checks pass
* no dirty, failed, refusal, blocker, or deactivation markers are present

Discovered candidates are returned as repair-plan candidates only. They are marked `runtime_eligible: true` and `execution_performed: false`.

## Ignored strategy reasons

Any failed check moves the entry to `ignored_strategies` with explicit reasons such as:

* `not_production_active`
* `activation_status_not_active`
* `deactivated`
* `missing_candidate_id`
* `missing_staged_script_path`
* `staged_script_missing`
* `staged_script_hash_mismatch`
* `static_checks_failed`
* `staged_script_path_references_job_quarantine`
* `absolute_staged_script_path_outside_repo`
* `staged_script_path_not_under_approved_staging_dir`
* dirty, failed, refusal, or blocker marker reasons

Ignored entries are always marked `runtime_eligible: false` and `execution_performed: false`.

## CLI usage

```bash
PYTHONPATH=app python3 app/tools/audit/learned_strategy_discovery.py \
  --rule-map app/tools/audit/rule_repair_map.json \
  --rule-id "PDF/UA-1/7.21.7" \
  --audit-dir /app/workspace/jobs/SMOKE_SELF_EXTENSION_CLEAN/audit
```

The CLI exits 0 when discovery succeeds, including when no active learned strategies exist. It emits JSON to stdout and writes `learned_strategy_discovery.json` when `--audit-dir` is supplied.

## Audit artifact

The discovery audit artifact contains:

* `schema_version`
* `created_at`
* `mode: discovery_only`
* `rule_map_path`
* `rule_ids_requested`
* `discovered_strategies`
* `ignored_strategies`
* `warnings`
* `policy`
* `execution_performed: false`
* `final_pdf_adoption_performed: false`
* `production_execution_enabled_by_patch_12a: false`
* `rule_map_mutation_performed: false`
* `app_tools_repair_mutation_performed: false`

## Relationship to Patch 12B

Patch 12A is the discovery contract only. A future Patch 12B may define a separate reviewed execution contract. That future patch must preserve the no-import/no-shell/no-execution boundary until explicit execution policy, ordering, evidence capture, final verdict behavior, and rollback semantics are reviewed and tested.

## Production behavior

Patch 12A does not modify `remediate.py`, does not merge learned strategies into executable built-in `strategies`, and does not change normal smoke outcomes. The existing `app/tools/repair/*` directory remains untouched.
