# Learned Strategy Execution Harness Policy

Patch 12B adds a controlled execution harness for already-discovered active learned strategies. The harness is a test/audit tool only. It is not orchestrator integration, not normal remediation runtime behavior, and not a final-PDF adoption mechanism.

## Purpose

The harness provides the next non-production step after active learned strategy discovery:

```text
active learned strategy discovery
→ selected discovered strategy
→ hash/static/path recheck
→ controlled input PDF only
→ isolated attempt directory
→ execute staged script
→ execution_log learned_strategy_execution record
→ stdout/stderr sidecars
→ candidate output PDF
→ optional validation placeholders
→ no final PDF adoption
→ no orchestrator integration
```

Discovery remains metadata validation only. Execution harness runs only one explicitly selected discovered strategy against a caller-provided controlled input PDF.

## Boundary

Patch 12B must not:

- import staged scripts as production modules
- integrate learned strategy execution into `remediate.py`
- change normal pipeline behavior
- make learned strategy execution mandatory
- adopt any output as a final PDF
- mutate `app/tools/audit/rule_repair_map.json`
- mutate `app/tools/repair/*`
- move staged scripts into `app/tools/repair/*`
- add new production repair strategies
- change verdict/status behavior

Every result and execution-log record must explicitly state:

```json
{
  "final_pdf_adoption_performed": false,
  "orchestrator_integration_performed": false,
  "rule_map_mutation_performed": false,
  "app_tools_repair_mutation_performed": false
}
```

## Pre-execution checks

Before execution, the harness rechecks the Patch 12A discovery safety conditions. A strategy is executable only when all of the following are true:

- `runtime_eligible: true`
- `production_active: true`
- `activation_status: active`
- `source == "learned_strategy_staged"`
- staged path resolves under `app/tools/repair_staging/learned/`
- staged script exists
- staged script SHA-256 matches `staged_script_sha256`
- static checks pass
- input PDF exists
- output path is controlled by the harness under the attempt directory

If any check fails, the harness returns `result: BLOCKED`, records explicit `execution_blockers`, writes `execution_result.json`, and does not execute the staged script.

## Attempt directory layout

Each run creates an isolated attempt directory:

```text
JOB/audit/learned_strategy_execution/<attempt_id>/
```

The directory contains:

```text
input.pdf
output.pdf
stdout.txt
stderr.txt
execution_result.json
```

Dry-run mode writes `execution_result.json` but does not execute the script and does not create `output.pdf`.

## Invocation contract

Execute mode copies the caller-provided input PDF into the attempt directory and invokes the staged script with controlled arguments:

```text
python staged_script.py input.pdf output.pdf
```

The staged script does not choose the candidate output destination. The only candidate output recognized by the harness is `output.pdf` inside the attempt directory.

## Execution log record

The harness appends a record to:

```text
JOB/audit/execution_log.json
```

The record uses:

```json
{
  "record_type": "learned_strategy_execution"
}
```

The record includes attempt identity, rule/candidate/strategy identifiers, script path and hash, input/output paths and hashes, timestamps, duration, exit code, stdout/stderr sidecars and hashes, result, blockers, static/hash/path verification fields, and the mandatory no-adoption/no-orchestrator/no-mutation booleans.

## CLI

Dry-run example:

```bash
PYTHONPATH=app python3 app/tools/audit/learned_strategy_execution.py \
  --discovery-json JOB/audit/learned_strategy_discovery.json \
  --candidate-id <candidate_id> \
  --input-pdf /path/to/input.pdf \
  --job-dir JOB \
  --dry-run
```

Execute example:

```bash
PYTHONPATH=app python3 app/tools/audit/learned_strategy_execution.py \
  --discovery-json JOB/audit/learned_strategy_discovery.json \
  --candidate-id <candidate_id> \
  --input-pdf /path/to/input.pdf \
  --job-dir JOB \
  --execute
```

The CLI emits JSON to stdout, writes `execution_result.json`, and updates `execution_log.json`. It exits nonzero for `BLOCKED` or `FAIL` unless `--allow-fail-exit-zero` is supplied for inspection workflows.

## Validation placeholder

Patch 12B does not run full veraPDF validation. Results include:

```json
{
  "validation_performed": false,
  "validation_artifacts": {}
}
```

Real validation and any production handoff must be reviewed in a later patch.

## Future integration pause

Patch 12B intentionally stops at harness execution. Before any Patch 12C/13 orchestrator integration, run a thorough end-to-end pipeline validation and separately review ordering, rollback, status/verdict effects, preservation gates, and final-PDF adoption semantics.

## Patch 13B learned execution dry-run boundary

Patch 13B adds `--learned-execution-dry-run`, which automatically performs discovery for residual rules and then delegates diagnostic execution to the Patch 12B harness. This remains opt-in only. It writes `learned_strategy_execution_diagnostics.json` and may append `record_type: learned_strategy_execution` only when a candidate actually runs. It does not adopt learned outputs, soften verdicts, mutate the rule map, mutate `app/tools/repair/*`, or replace built-in repair execution.

