# H13S WebUI Self-Extension Smoke Boundary

## Baseline commit

```text
0437c89 Mirror self-extension pass override in status
```

The required bounded retry-loop baseline remains present in history:

```text
8e66f2c Use bounded self-extension retry loop
```

## Terminal state

```text
WEBUI_SELF_EXTENSION_SMOKE_BOUNDARY_HARDENED
```

## Proof level

```text
CLI_ONLY
```

This patch hardens the code and runbook boundary. It does not rerun the live Open WebUI smoke. `WEBUI_PATH` proof is not claimed.

## H13R cleanup

The failed H13R smoke produced local runtime/source mutations in the operator checkout:

```text
M app/tools/audit/rule_repair_map.json
?? app/tools/repair/fix_embed_nonsymbolic_fonts.py
?? workspace/extract_text.py
```

Those were not committed. H13S does not add a target-rule repair and does not add a rule-map entry.

## What H13S adds

H13S adds an explicit evidence-only smoke boundary wrapper:

```text
app/tools/orchestrate/self_extension_smoke_boundary.py
```

The wrapper is for H13/H13S/H13T WebUI self-extension smoke validation only. It configures self-extension, runs the orchestrator, detects prohibited source-path mutations, and surfaces smoke-boundary evidence into:

```text
STATUS.json
audit/orchestrator_outcome.json
```

## Smoke boundary contract

When evidence-only smoke mode is active, the boundary records:

```json
{
  "smoke_boundary": {
    "evidence_only": true,
    "source_repair_creation_allowed": false,
    "rule_map_mutation_allowed": false,
    "adoption_allowed": false,
    "final_pdf_update_from_failed_candidate_allowed": false,
    "blocked_actions": [],
    "boundary_result": "PASS|BLOCKED",
    "boundary_reason": "..."
  }
}
```

The prohibited source paths include:

```text
app/tools/repair/*.py
app/tools/audit/rule_repair_map.json
workspace/extract_text.py
```

Runtime candidate files remain allowed only under job/workspace quarantine. Source repair scripts and rule-map edits remain forbidden during evidence-only smoke.

## Self-extension NOT_RUN specificity

H13S distinguishes NOT_RUN reasons instead of collapsing them into the former generic value.

Supported blocker reasons include:

```text
self_extension_not_enabled
self_extension_enabled_but_no_target_rule
self_extension_enabled_but_no_residual_gap
self_extension_enabled_but_policy_blocked
self_extension_enabled_but_transport_unavailable
self_extension_enabled_but_target_rule_mismatch
self_extension_enabled_but_unexpectedly_not_run
```

If self-extension is configured for the smoke but does not run, the wrapper records `self_extension_not_run_blocker` and prevents the smoke from being treated as successful WebUI retry-loop proof.

## Target-rule verification

H13S adds target-rule verification for evidence-only smoke. Example mismatch payload:

```json
{
  "target_rule_check": {
    "expected_target_rule_id": "PDF/UA-1/7.21.7",
    "actual_target_rule_id": "PDF/UA-1/7.21.5",
    "actual_rule_ids": ["PDF/UA-1/7.21.5"],
    "result": "MISMATCH",
    "reason": "actual_residual_did_not_match_expected_self_extension_target"
  }
}
```

A mismatch is surfaced as a blocked smoke action. It must not be reported as successful H13 WebUI retry-loop proof.

## Runbook/Hermes hardening

The Hermes PDF remediation runbook now has a distinct evidence-only self-extension smoke section. It instructs the agent to invoke:

```bash
python3 /app/tools/orchestrate/self_extension_smoke_boundary.py \
  /app/workspace {TICKET} "{basename}" \
  --title "..." --subject "..." --keywords "..." \
  --expected-target-rule "PDF/UA-1/7.21.7" \
  --max-attempts 2
```

During this mode, the runbook forbids:

```text
source repair script creation
repair script registration
rule_repair_map.json edits
generated candidate adoption
promotion of generated code to source
final-PDF update from failed candidates
claiming self-extension ran without attempt evidence
switching to a different target rule silently
```

The V6 skill and V6 runbook carry the same guardrail.

## Tests added or updated

H13S adds:

```text
app/tools/tests/test_self_extension_smoke_boundary.py
```

It also updates:

```text
app/tools/tests/test_self_extension_remediate_hook.py
```

The tests prove:

```text
source repair paths are prohibited
rule-map mutation is prohibited
adoption is disabled in evidence-only smoke boundary summaries
final-PDF update from failed candidates is disabled
blocked actions are surfaced
target-rule mismatch is explicit
enabled-but-not-run self-extension receives a specific reason
STATUS.json and orchestrator_outcome.json receive smoke_boundary, target_rule_check, and self_extension_not_run_blocker fields
runbook policy text forbids write/register drift
```

## Tests run

Not run in this ChatGPT/GitHub-connector environment. The connector can write repository files, but it does not provide a live local checkout with Docker/Hermes/Open WebUI. The operator should run:

```bash
PYTHONPATH=app python3 -m unittest \
  app/tools/tests/test_self_extension_remediate_hook.py \
  app/tools/tests/test_self_extension_executor.py \
  app/tools/tests/test_self_extension_support.py \
  app/tools/tests/test_self_extension_run_state.py \
  app/tools/tests/test_self_extension_smoke_boundary.py \
  app/tools/tests/test_guarded_acceptance_status_package_policy.py
```

## What passed

Code and policy changes were committed through the GitHub connector.

The boundary is now represented in source and tests.

The WebUI/Hermes runbook now has an explicit evidence-only smoke path that supersedes the normal write/register repair loop.

## What failed

No live WebUI smoke was run in H13S.

No local unit tests were run in this environment.

## What was not attempted

H13S did not attempt:

```text
generated repair success
candidate adoption
rule-map adoption
second-document reuse
production readiness
beta readiness
```

## What must not be claimed

Do not claim:

```text
WEBUI_PATH proof
WEBUI_SELF_EXTENSION_RETRY_LOOP_VALIDATED_FAIL_CLOSED
successful self-extension
candidate adoption
rule-map adoption
production readiness
beta readiness
second-PDF reuse
```

## Exact next step

```text
H13T — Rerun WebUI Self-Extension Retry Loop Smoke with Hardened Boundary
```

H13T should use the wrapper path and should fail closed if the bounded retry-loop does not run, if the target rule mismatches, or if any source/rule-map/adoption drift is attempted.
