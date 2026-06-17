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
