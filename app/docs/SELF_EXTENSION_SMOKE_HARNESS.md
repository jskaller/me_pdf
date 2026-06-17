# Self-Extension Smoke Harness

Patch 7 adds a deterministic smoke harness for the self-extension candidate path. The harness proves the candidate-learning plumbing end to end without calling a live LLM and without adopting generated output.

## Purpose

The harness safely exercises this path:

```text
targetable residual
-> fake self-extension request
-> deterministic generated candidate script
-> quarantine write
-> compile check
-> quarantine execution
-> execution_log.json v2 candidate record
-> learned_strategies.json record
-> strategy_indexing_report.json dry-run proposal or rejection
-> no canonical mutation
```

This is not a production repair strategy. It is a repeatable integration smoke test for the self-extension learning loop.

## How to run

From the repository root:

```bash
PYTHONPATH=app python3 app/tools/dev/self_extension_smoke.py \
  --job-dir /tmp/selfext_smoke_job \
  --mode fake-clean
```

Available fake modes:

| Mode | Behavior | Expected learned outcome | Indexer behavior |
| --- | --- | --- | --- |
| `fake-clean` | Candidate script compiles, copies input PDF to candidate output, and controlled validation treats the target rule as resolved. | `clean_success`, `clean: true`, `indexing_eligible: true` | Dry-run proposal is created. |
| `fake-dirty` | Candidate executes successfully but controlled validation records an introduced rule. | `dirty_success`, `clean: false`, `indexing_eligible: false` | Rejected experiment is retained. |
| `fake-failed` | Candidate script compiles but exits nonzero. | `validation_failed`, `clean: false`, `indexing_eligible: false` | Rejected experiment is retained. |
| `fake-refusal` | Fake provider returns `NEEDS_MORE_EVIDENCE`; no script is written or executed. | `needs_more_evidence`, `clean: false`, `indexing_eligible: false` | Rejected experiment is retained. |

The default target rule is `PDF/UA-1/7.21.7`. Override it with `--rule-id` if a controlled smoke needs a different target.

## Artifacts

The harness writes only under the provided job directory:

```text
JOB/audit/self_extension/run_state.json
JOB/audit/self_extension/quarantine/<mode>/candidate.py
JOB/audit/execution_log.json
JOB/audit/execution/stdout/<attempt>.out
JOB/audit/execution/stderr/<attempt>.err
JOB/audit/residual_analysis.json
JOB/audit/learned_strategies.json
JOB/audit/strategy_indexing_report.json
JOB/audit/self_extension_smoke_summary.json
JOB/input/smoke_input.pdf
JOB/repair/self_extension_candidates/<mode>/candidate_output.pdf
```

`fake-refusal` intentionally skips candidate execution, so it does not require `audit/execution_log.json`.

## Safety boundaries

The harness enforces the Patch 7 no-adoption policy:

- accepts `SCRIPT_SOURCE` only for executable fake-provider candidates;
- never trusts provider-supplied paths for writes;
- writes generated scripts only under `JOB/audit/self_extension/quarantine/`;
- writes candidate PDF output only under `JOB/repair/self_extension_candidates/`;
- never writes generated scripts into `app/tools/repair/`;
- never mutates `app/tools/audit/rule_repair_map.json`;
- never adopts a candidate PDF as the production final PDF;
- compiles candidate source before execution;
- runs candidates with a timeout;
- captures stdout/stderr in sidecars and hashes them;
- records failures instead of swallowing them;
- uses a restricted environment for candidate subprocesses and does not dump secrets to logs.

## How this differs from live Hermes/NIM execution

The smoke harness uses deterministic fake gateway responses. It does not evaluate model quality, live transport retry behavior, or model-specific refusal patterns. Those remain separate live-gateway concerns. Patch 7 acceptance is based on proving that candidate generation, quarantine, execution evidence, learned-strategy capture, and dry-run indexing are all connected safely.

## Docker smoke example

```bash
docker compose exec hermes bash -lc '
cd /app &&
PYTHONPATH=/app python3 tools/dev/self_extension_smoke.py \
  --job-dir /app/workspace/jobs/SMOKE_SELF_EXTENSION_CLEAN \
  --mode fake-clean
'
```

Inspect artifacts:

```bash
docker compose exec hermes bash -lc '
JOB=/app/workspace/jobs/SMOKE_SELF_EXTENSION_CLEAN
find "$JOB/audit" -maxdepth 4 -type f | sort
echo
python3 -m json.tool "$JOB/audit/execution_log.json" | head -220
echo
python3 -m json.tool "$JOB/audit/learned_strategies.json" | head -220
echo
python3 -m json.tool "$JOB/audit/strategy_indexing_report.json" | head -220
'
```

Expected clean-mode highlights:

- `execution_log.json` contains `record_type: self_extension_candidate`;
- `learned_strategies.json` contains `outcome: clean_success`;
- learned strategy references `execution_attempt_id`, `execution_log_path`, stdout, and stderr evidence;
- `strategy_indexing_report.json` contains one dry-run proposal;
- canonical rule map and canonical repair scripts remain unchanged.

## Regression command

```bash
PYTHONPATH=app python3 -m unittest \
  app/tools/tests/test_self_extension_smoke_harness.py \
  app/tools/tests/test_execution_log_fidelity.py \
  app/tools/tests/test_orchestrator_residual_verdict_integration.py \
  app/tools/tests/test_m1_gate_verdict.py \
  app/tools/tests/test_post_job_indexer_learned_strategies.py \
  app/tools/tests/test_learned_strategy_capture.py \
  app/tools/tests/test_residual_analysis.py \
  app/tools/tests/test_residual_analysis_remediate_hook.py \
  app/tools/tests/test_self_extension_run_state.py \
  app/tools/tests/test_self_extension_executor.py \
  app/tools/tests/test_self_extension_remediate_hook.py \
  app/tools/tests/test_self_extension_support.py
```

## Intentionally incomplete

Patch 7 does not implement generated script promotion, canonical rule-map mutation, final-PDF adoption, strategy-indexer apply mode, new production repair scripts, broad verdict/status rewrites, or mandatory live Hermes/NIM execution.
