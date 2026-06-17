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
