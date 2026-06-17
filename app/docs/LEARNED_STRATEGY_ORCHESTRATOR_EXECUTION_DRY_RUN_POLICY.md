# Learned Strategy Orchestrator Execution Dry-Run Policy

Patch 13B adds one explicit opt-in orchestrator mode:

```bash
--learned-execution-dry-run --learned-execution-limit 1
```

This mode is diagnostic-only. It automatically performs active learned strategy discovery for the current residual rules, then runs at most the configured number of discovered active runtime-eligible candidates through the Patch 12B isolated execution harness.

## Defaults

Default remediation remains unchanged:

- no learned discovery by default unless `--learned-discovery` is supplied by an earlier patch;
- no learned execution by default;
- no `learned_strategy_execution` execution-log records by default;
- no `learned_strategy_execution_diagnostics.json` by default.

## Input PDF selection

The orchestrator passes the current post-known-repair working PDF (`FINAL_PDF`) as the diagnostic input. If that path is unavailable, the dry-run fails closed in diagnostics with:

```text
learned_execution_input_pdf_unavailable
```

The learned strategy never chooses the input or output path.

## Isolation and output

Execution is delegated to:

```text
app/tools/audit/learned_strategy_execution.py
```

That harness validates the active discovery candidate, verifies the staged path and SHA-256 hash, performs static checks, creates an isolated attempt directory under:

```text
JOB/audit/learned_strategy_execution/<attempt_id>/
```

and writes `execution_result.json`, stdout/stderr sidecars, and the controlled output PDF only under the attempt directory.

## Diagnostic artifact

The orchestrator writes:

```text
JOB/audit/learned_strategy_execution_diagnostics.json
```

The artifact records candidate counts, executed/skipped/failed/blocked counts, selected input PDF and hash, execution summaries, skipped candidates, and policy flags.

## Non-adoption boundary

Patch 13B does not:

- adopt learned output PDFs;
- soften PASS/FAIL/ESCALATION verdicts;
- change `STATUS.json` or `orchestrator_outcome.json` verdict semantics;
- replace built-in repairs;
- mutate `app/tools/audit/rule_repair_map.json`;
- mutate `app/tools/repair/*`;
- import staged learned scripts directly from `remediate.py`.

Learned execution success is evidence only. Learned execution failure is diagnostic only unless the orchestration code itself crashes unexpectedly.

## Next step

The next step after Patch 13B is compare/validation hardening: compare learned outputs against normal-path artifacts, record objective validator deltas, and only then discuss any separate future production adoption design.

## Active-candidate smoke validation

Patch 13C adds a development/test smoke fixture that proves the opt-in orchestrator learned execution path can execute one active learned candidate diagnostically while preserving the Patch 13B non-adoption boundary.

The helper is:

```bash
PYTHONPATH=app python3 app/tools/dev/setup_learned_execution_smoke_candidate.py \
  --job-dir /app/workspace/jobs/MM-17179_ROI4987_English_1-26_rev_Fillable \
  --rule-id "PDF/UA-1/7.21.7" \
  --candidate-id "smoke-active-candidate" \
  --setup
```

In the Hermes container, run it from `/app` with `PYTHONPATH=/app` and `tools/dev/setup_learned_execution_smoke_candidate.py`; the helper writes rule-map metadata using the `app/tools/repair_staging/learned/...` path expected by the orchestrator dry-run discovery call.

Setup creates a safe staged script under the learned staging directory, computes its SHA-256 hash, backs up `rule_repair_map.json` under `JOB/audit/learned_execution_smoke_rule_map_backup.json`, and writes `JOB/audit/learned_execution_smoke_setup.json`. The smoke rule-map entry is temporary and must not be committed as canonical knowledge.

The active-candidate smoke command remains the normal orchestrator command plus the explicit diagnostic flags:

```bash
PYTHONPATH=/app python3 tools/orchestrate/remediate.py \
  /app/workspace \
  MM-17179 \
  "ROI4987_English_1-26_rev_Fillable" \
  --title "ROI4987 English 1-26 Rev Fillable" \
  --subject "Release of information form" \
  --keywords "release of information, ROI, authorization, Montefiore" \
  --learned-execution-dry-run \
  --learned-execution-limit 1
```

Expected `JOB/audit/learned_strategy_execution_diagnostics.json` values for the active smoke are:

```json
{
  "mode": "learned_execution_dry_run",
  "enabled": true,
  "candidate_count": 1,
  "executed_count": 1,
  "failed_count": 0,
  "blocked_count": 0,
  "execution_performed": true,
  "final_pdf_adoption_performed": false,
  "verdict_softening_performed": false,
  "rule_map_mutation_performed": false,
  "app_tools_repair_mutation_performed": false,
  "production_repair_replacement_performed": false
}
```

Each execution summary must include the `rule_id`, `candidate_id`, `strategy_id`, `attempt_id`, `execution_result_path`, `result: PASS`, `exit_code: 0`, `output_pdf`, `output_pdf_sha256`, and `final_pdf_adoption_performed: false`. The learned output PDF is evidence only and must remain under `JOB/audit/learned_strategy_execution/<attempt_id>/output.pdf`.

`JOB/audit/execution_log.json` should include one `record_type: learned_strategy_execution` record for the smoke candidate, with `final_pdf_adoption_performed: false` and `orchestrator_integration_performed: false`. This record is diagnostic evidence only; it is not a production repair step and does not replace built-in repair ordering.

For `MM-17179`, the final orchestrator result must remain `ESCALATION`. Hermes reconciliation must remain unchanged: `active_actionable_count: 3`, `suppressed_zero_count: 1`, active actionable rules `PDF/UA-1/7.18.4`, `PDF/UA-1/7.21.7`, `PDF/UA-1/7.21.4.1`, and suppressed zero-count rule `PDF/UA-1/7.18.1`.

Cleanup is mandatory immediately after the smoke:

```bash
PYTHONPATH=app python3 app/tools/dev/setup_learned_execution_smoke_candidate.py \
  --job-dir /app/workspace/jobs/MM-17179_ROI4987_English_1-26_rev_Fillable \
  --cleanup
```

After cleanup, these protected mutation checks must be clean:

```bash
git status --short
git diff -- app/tools/audit/rule_repair_map.json app/tools/repair
find app/tools/repair_staging/learned -maxdepth 1 -type f \( -name "smoke_*" -o -name "*.tmp" -o -name "manifest.json" \) -print
```

The only expected smoke artifacts are job-local audit evidence under `workspace/jobs/.../audit/`. The canonical rule map must be restored, `app/tools/repair/*` must remain untouched, and no smoke staged script may remain in `app/tools/repair_staging/learned/`.

This smoke is still not final adoption because the orchestrator passes the learned candidate through the isolated Patch 12B harness only, records the result as diagnostics, leaves the final PDF path untouched, and preserves normal PASS/FAIL/ESCALATION semantics. It is still not production replacement because learned execution remains opt-in, limited, audit-only, and disabled by default.

## Patch 14A output comparison sidecar hotfix note

Patch 14A adds learned output comparison as a diagnostic sidecar after learned execution dry-run records are produced. The integration is intentionally wrapped around the existing dry-run runner rather than changing verdict, status, package, rule-map, or production-repair behavior.

The wrapper writes or updates `JOB/audit/learned_strategy_execution_diagnostics.json` with:

```json
{
  "output_comparison_performed": true,
  "output_comparison_artifact": "JOB/audit/learned_strategy_output_comparisons.json",
  "output_comparison_count": 1,
  "output_comparison_summary": {"no_effect": 1}
}
```

The sidecar artifact remains diagnostic-only. It does not make learned output adoptable, does not soften PASS/FAIL/ESCALATION, and does not mutate `app/tools/audit/rule_repair_map.json` or `app/tools/repair/*`.

## Patch 14B candidate quality reference

When learned execution dry-run produces output comparisons, the orchestrator
also writes `JOB/audit/learned_strategy_candidate_quality_report.json` and
records `candidate_quality_performed`, `candidate_quality_artifact`, and
`candidate_quality_summary` in
`JOB/audit/learned_strategy_execution_diagnostics.json`.

The quality gate is diagnostic-only. It must not change the final PDF path,
normal verdict, STATUS/package behavior, Hermes reconciliation, canonical rule
map, or `app/tools/repair/*`.

<!-- PATCH16A_DEEPER_VALIDATION_POLICY_UPDATE -->

## Patch 16A — deeper validation gate

Patch 16A adds a diagnostic-only deeper validation layer after learned output comparison and candidate quality. The gate is eligible only for `candidate_valid_changed` and `needs_deeper_validation` decisions. Rejected decisions such as `rejected_no_effect`, `rejected_invalid`, and `rejected_execution_failed` are recorded as `skipped_not_eligible`.

The artifact is written to:

```text
JOB/audit/learned_strategy_deeper_validation_report.json
```

This gate may produce `deeper_validation_passed`, but that is not adoption approval. Required policy flags remain false: `candidate_is_adoptable`, `final_pdf_adoption_performed`, `verdict_softening_performed`, `rule_map_mutation_performed`, `app_tools_repair_mutation_performed`, and `production_repair_replacement_performed`.

The next possible phase after this patch is an isolated replacement trial, still opt-in and still without final package adoption.
## Patch 16B changed-valid smoke mode

The smoke setup helper now accepts:

```bash
--script-mode copy
--script-mode changed-valid
```

`copy` preserves the existing no-op smoke behavior and should continue to classify as `no_effect`, map to `rejected_no_effect`, and skip deeper validation as `skipped_not_eligible`.

`changed-valid` creates a synthetic diagnostic candidate that changes only the isolated learned harness output. It is expected to classify as `changed_valid_pdf` when qpdf/header checks pass, then map to `candidate_valid_changed`, then enter deeper validation. This mode is only a pre-production diagnostic bridge. It must not replace the final PDF, soften the orchestrator verdict, mutate `app/tools/repair/*`, promote the learned script, or mark the candidate adoptable/approved/production-ready.

The setup artifact records `script_mode`, `expected_comparison_classification`, `final_pdf_adoption_performed=false`, and `verdict_softening_performed=false` so smoke diagnostics can reconcile intent with observed artifacts.

## Patch 17A replacement trial flags

The learned execution dry-run can optionally run the isolated replacement trial with `--learned-replacement-trial`. This flag is valid only with `--learned-execution-dry-run`; otherwise the orchestrator fails closed with `requires_learned_execution_dry_run`. The smoke-only `--learned-replacement-trial-allow-manual-review` flag permits `needs_manual_review` candidates to exercise the isolated trial path without changing final PDF authority, status, package routing, verdict semantics, rule-map state, or `app/tools/repair/*`.
