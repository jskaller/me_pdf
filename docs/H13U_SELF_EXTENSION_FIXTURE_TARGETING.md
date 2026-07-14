# H13U Self-Extension Fixture Targeting

## Baseline commit

```text
f3302a1 Fix H13T smoke wrapper command environment
```

## Terminal state

```text
WEBUI_SELF_EXTENSION_FIXTURE_BLOCKED_BY_VALIDATION_ENVIRONMENT
```

## Proof level

```text
CLI_ONLY
```

H13U adds fixture target preflight code and runbook policy, but the Docker/Hermes/Open WebUI runtime was not available in this implementation environment. Therefore no live fixture was selected or built in this patch, and WebUI retry-loop proof is not claimed.

## Files changed

```text
app/tools/audit/self_extension_fixture_preflight.py
app/tools/orchestrate/self_extension_smoke_boundary.py
app/tools/tests/test_self_extension_fixture_preflight.py
app/hermes_skills/pdf-remediation/SKILL.md
app/skills/montefiore-pdfua-unified-v6/SKILL.md
app/skills/montefiore-pdfua-unified-v6/docs/RUNBOOK.md
docs/H13U_SELF_EXTENSION_FIXTURE_TARGETING.md
docs/PRODUCTION_REMEDIATION_STATUS.md
```

## Goal

H13U prevents another blind WebUI retry-loop smoke. Before a future H13V run claims that a fixture can exercise the retry loop, the fixture must be preflighted and show that its actual residual target matches the configured expected target.

Preferred target remains:

```text
PDF/UA-1/7.21.7
```

The latest H13T run proved that the previous fixture reached:

```text
PDF/UA-1/7.21.4.1
```

not `PDF/UA-1/7.21.7`, so that fixture must not be reused as proof of a 7.21.7 retry loop.

## Preflight tool

H13U adds:

```text
app/tools/audit/self_extension_fixture_preflight.py
```

The tool answers:

```text
After known repairs and normal validation, what residual rule would be selected for self-extension?
```

It reads job artifacts such as:

```text
audit/strategy_gap.json
audit/orchestrator_outcome.json
STATUS.json
```

and emits:

```json
{
  "result": "MATCH|MISMATCH|NO_TARGET",
  "expected_target_rule_id": "PDF/UA-1/7.21.7",
  "actual_target_rule_id": "...",
  "self_extension_would_run": true,
  "retry_loop_smoke_may_proceed": true,
  "reason": "...",
  "candidate_classification": "MATCHES_EXPECTED_TARGET|MISMATCHES_EXPECTED_TARGET|NO_SELF_EXTENSION_TARGET",
  "residual_rules": []
}
```

It is evidence/reporting only. It does not repair PDFs, write repair scripts, mutate the rule map, adopt generated candidates, or update final PDFs.

## Wrapper integration

The evidence-only wrapper now calls fixture preflight and surfaces the compact result into:

```text
STATUS.json
audit/orchestrator_outcome.json
```

The compact summary is:

```json
{
  "fixture_preflight": {
    "result": "MATCH|MISMATCH|NO_TARGET",
    "expected_target_rule_id": "PDF/UA-1/7.21.7",
    "actual_target_rule_id": "...",
    "self_extension_would_run": true,
    "reason": "...",
    "artifact_path": ".../audit/self_extension_fixture_preflight.json"
  }
}
```

The wrapper returns a failing exit status if `fixture_preflight.self_extension_would_run` is false, preventing target-drift smoke continuation.

## Candidate fixtures inspected

No repository or runtime fixture was conclusively selected in this patch because Docker/Hermes/Open WebUI were shut down and the implementation environment did not have the live runtime.

Known H13T candidate evidence:

```text
fixture: MM-17179-H13T-WEBUI-SELFEXT1/input.pdf
expected_target_rule_id: PDF/UA-1/7.21.7
actual_target_rule_id: PDF/UA-1/7.21.4.1
result: MISMATCH
self_extension_would_run: false
reason: actual_residual_did_not_match_expected_self_extension_target
classification: MISMATCHES_EXPECTED_TARGET
```

## Target decision

Continue targeting `PDF/UA-1/7.21.7` only if H13U/H13V preflight finds or builds a fixture whose actual residual is `PDF/UA-1/7.21.7`.

Re-scope to `PDF/UA-1/7.21.4.1` is not recommended by this patch alone. The previous H13T evidence shows that 7.21.4.1 is the current fixture's actual residual, but H13U did not prove that 7.21.4.1 is unsupported, intentionally self-extension-targetable, and not already handled by known repairs. That requires live preflight evidence before re-scoping.

## Tests

Added:

```text
app/tools/tests/test_self_extension_fixture_preflight.py
```

The tests cover:

```text
MATCH when actual target equals expected target
MISMATCH when actual target differs
NO_TARGET when no residual is selected
self_extension_would_run true only for target match
mismatch/no-target blocking retry-loop smoke continuation
preflight surfacing into STATUS.json and orchestrator_outcome.json
known-repair reporting without rule-map mutation
evidence-only source/rule-map/adoption/final-PDF policies
```

Required local validation after pulling:

```bash
PYTHONPATH=app python3 -m unittest \
  app/tools/tests/test_self_extension_remediate_hook.py \
  app/tools/tests/test_self_extension_executor.py \
  app/tools/tests/test_self_extension_support.py \
  app/tools/tests/test_self_extension_run_state.py \
  app/tools/tests/test_self_extension_smoke_boundary.py \
  app/tools/tests/test_self_extension_fixture_preflight.py \
  app/tools/tests/test_guarded_acceptance_status_package_policy.py
```

## Artifact hygiene

H13U does not commit:

```text
private PDFs
generated PDFs
workspace jobs
STATUS.json runtime files
orchestrator_outcome.json runtime files
validator XML sidecars
package ZIPs
source repair scripts
rule-map changes
```

## What was proven

```text
Fixture target preflight now exists.
Preflight can distinguish MATCH, MISMATCH, and NO_TARGET.
Preflight can be surfaced in STATUS.json and orchestrator_outcome.json.
The smoke wrapper now blocks retry-loop continuation when preflight says the fixture cannot exercise the configured target.
Runbook instructions now require fixture preflight before retry-loop proof.
```

## What failed / remains blocked

```text
No live Docker/Hermes/WebUI fixture selection was run.
No fixture was selected or built for PDF/UA-1/7.21.7.
No re-scope to PDF/UA-1/7.21.4.1 was justified.
```

## What was not attempted

```text
Candidate generation success.
Generated repair adoption.
Rule-map adoption.
Second-document reuse.
Production readiness.
Beta readiness.
```

## What must not be claimed

Do not claim:

```text
WEBUI_SELF_EXTENSION_FIXTURE_SELECTED_FOR_7_21_7
WEBUI_SELF_EXTENSION_FIXTURE_BUILT_FOR_7_21_7
WEBUI_SELF_EXTENSION_FIXTURE_TARGET_RESCOPE_RECOMMENDED_TO_7_21_4_1
WEBUI_SELF_EXTENSION_RETRY_LOOP_VALIDATED_FAIL_CLOSED
production readiness
beta readiness
```

## Exact next step

```text
H13V — Build Minimal Controlled Self-Extension Fixture
```

Before H13V, restart Docker/Hermes/Open WebUI, pull the latest master, run the H13U tests, and use fixture preflight to verify whether a candidate fixture reaches `PDF/UA-1/7.21.7` before running another WebUI retry-loop smoke.
