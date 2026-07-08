# H13 WebUI Self-Extension Retry Loop Evidence

## Baseline commit

```text
8e66f2c Use bounded self-extension retry loop
```

## Final commit

Pending final `master` head after H13 documentation updates.

## Terminal state

```text
WEBUI_SELF_EXTENSION_BLOCKED_BY_COMMAND_ENVIRONMENT
```

## Proof level

```text
CLI_ONLY
```

The GitHub connector had repository write access, but this execution environment did not provide a live Open WebUI session, Hermes container shell, Docker access, or a network-reachable checkout capable of running the WebUI `PDF:` smoke. Therefore H13 cannot claim `WEBUI_PATH` proof.

## Files changed

```text
app/tools/packaging/status_json_writer.py
app/tools/tests/test_guarded_acceptance_status_package_policy.py
docs/H13_WEBUI_SELF_EXTENSION_RETRY_LOOP_EVIDENCE.md
docs/PRODUCTION_REMEDIATION_STATUS.md
```

## WebUI prompt used

Not run from this environment.

The required prompt shape remains:

```text
PDF: /app/workspace/input/MM-17179-H13-WEBUI-SELFEXT1/<file>.pdf

Please remediate this PDF for PDF/UA accessibility and return the remediated output with a status report.
```

## Job path

No live WebUI job was created in this environment.

The intended ticket remains:

```text
MM-17179-H13-WEBUI-SELFEXT1
```

## What changed in H13

H13 makes bounded self-extension retry-loop results first-class during status generation. `status_json_writer.py` now:

1. Loads `audit/self_extension_residual_result.json` or `audit/strategy_gap.json.self_extension`.
2. Builds an explicit `self_extension` summary.
3. Writes that summary into both `STATUS.json` and `audit/orchestrator_outcome.json`.
4. Preserves the required safety fields:
   - `enabled`
   - `result`
   - `reason`
   - `target_rule_id`
   - `attempt_count`
   - `adoption_performed`
   - `final_pdf_updated`
   - `rule_map_mutation_performed`
   - `run_attempts_result`
5. Captures generation/transport diagnostics when available:
   - elapsed seconds
   - prompt chars
   - request chars
   - reported usage
   - model / gateway model
   - gateway URL
   - timeout seconds
   - max tokens
6. Captures retry-diversity feedback from prior-attempt feedback, including repeated strategy-family events that do not reduce the target count.
7. Prevents `STATUS.json` and the enriched `orchestrator_outcome.json` from claiming `PASS` when self-extension was enabled but ended in a non-pass result.

## self_extension_run_attempts_result.json summary

No live H13 WebUI run was executed here, so there is no runtime `self_extension_run_attempts_result.json` from this environment.

The status writer now surfaces the path from either:

```text
self_extension_residual_result.json.artifacts.run_attempts_result
strategy_gap.json.self_extension.artifacts.run_attempts_result
```

or a direct `run_attempts_result` field.

## orchestrator_outcome.json self_extension summary

Expected shape after H13 when the status writer runs:

```json
{
  "self_extension": {
    "enabled": true,
    "result": "FAIL",
    "reason": "max_attempts_exhausted",
    "target_rule_id": "PDF/UA-1/7.21.7",
    "attempt_count": 2,
    "adoption_performed": false,
    "final_pdf_updated": false,
    "rule_map_mutation_performed": false,
    "run_attempts_result": ".../audit/self_extension_run_attempts_result.json"
  }
}
```

If `overall_result` was incorrectly `PASS` while enabled self-extension failed, H13 updates the outcome to:

```json
{
  "overall_result": "ESCALATION",
  "self_extension_overrode_pass": {
    "from": "PASS",
    "to": "ESCALATION",
    "reason": "self_extension_enabled_but_not_successful"
  }
}
```

## STATUS.json result

No live H13 job was produced here.

Expected H13 behavior after a failed bounded self-extension retry loop:

```text
STATUS.json overall_result: ESCALATION or existing non-PASS terminal result
STATUS.json self_extension.result: FAIL / ERROR / TRANSPORT_BLOCKED as applicable
```

## Package result

No package was generated in this environment.

Package routing remains report-only for `FAIL` and `ESCALATION`, and H13 ensures a failed enabled self-extension cannot leave the authoritative outcome at `PASS` before package routing reads it.

## Generation/transport diagnostics

H13 does not expose secrets. It records only non-secret diagnostics when they are present in attempt records:

```text
elapsed_seconds
prompt_chars
request_chars
reported_usage
model
gateway_model
gateway_url
timeout_seconds
max_tokens
candidate_result
```

API keys are not written.

## Retry-diversity behavior

H13 surfaces retry feedback from prior attempts and records whether adjacent strategy families repeated without target-count reduction. A repeated strategy with no target reduction is marked as not justified unless a future attempt explicitly records material justification.

## Artifact hygiene status

No runtime artifacts were committed. H13 only commits source/test/docs files.

Runtime artifacts remain forbidden in source control:

```text
workspace/
generated PDFs
STATUS.json
orchestrator_outcome.json
self_extension_run_attempts_result.json
candidate_result.json
package ZIPs
runtime generated candidate scripts
```

## What passed

- Repository baseline included `8e66f2c Use bounded self-extension retry loop`.
- GitHub connector write access was available.
- Outcome/status surfacing was patched in source.
- Regression test coverage was added for failed self-extension summary surfacing and false-PASS prevention.

## What failed

- The Open WebUI `PDF:` path was not runnable from this execution environment.
- Docker/Hermes/WebUI smoke commands were not available here.
- Unit tests were not run here because there was no reachable checkout/runtime from the GitHub connector environment, and direct container network access to GitHub failed DNS resolution.

## What was not attempted

- No generated repair success attempt.
- No governed adoption proposal.
- No second-document reuse proof.
- No beta or production-readiness proof.

## What must not be claimed

Do not claim:

```text
WEBUI_PATH proof
successful self-extension
adoption
second-document reuse
beta readiness
production readiness
```

## Next patch

Because H13 is blocked before WebUI proof, the exact next step is:

```text
H13R — Run WebUI PDF: Smoke Against Surfaced Self-Extension Outcome
```

H13R should run from the local Docker/Open WebUI environment, pull the final H13 commit, submit the `PDF:` prompt through Open WebUI, and verify that `orchestrator_outcome.json`, `STATUS.json`, package routing, and the final WebUI response all match the surfaced self-extension outcome.
