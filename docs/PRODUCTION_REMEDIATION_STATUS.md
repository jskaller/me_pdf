# Production Remediation Status

## Current production goal

Build a production-ready PDF remediation system that works through the intended production path:

```text
Open WebUI prompt beginning with PDF:
-> Hermes loads the pdf-remediation runbook
-> /app/tools/orchestrate/remediate.py or a production-approved wrapper creates and executes the job
-> known deterministic repairs run only when safe
-> validation determines remaining blockers
-> unsupported/remediable blockers produce quarantined self-extension candidates
-> failed candidates fail closed and cannot update final PDFs or mutate the rule map
-> successful candidates require governed adoption and later second-document reuse proof
-> STATUS.json and orchestrator_outcome.json truthfully report PASS, REVIEW_REQUIRED, FAIL, or ESCALATION
-> deliverables package reflects the authoritative outcome
```

## Current branch

```text
master
```

## Last completed patch

```text
H13S - Harden WebUI Self-Extension Smoke Boundary
```

H13S terminal state:

```text
WEBUI_SELF_EXTENSION_SMOKE_BOUNDARY_HARDENED
```

H13S proof level:

```text
CLI_ONLY
```

H13S hardens the WebUI/Hermes evidence-only smoke boundary. It does not rerun the live Open WebUI smoke and does not claim `WEBUI_PATH` proof.

## Historical terminal states preserved

```text
ISO_SIDE_EFFECT_FIXED_TARGET_RULE_STILL_CLEARS
GUARDED_METADATA_ADOPTED_RUNTIME_NOT_ACTIVE
LOOKUP_GATING_IMPLEMENTED_ORCHESTRATOR_DEFERRED
ORCHESTRATOR_RUNTIME_BLOCKED_BY_STATUS_PACKAGE_CONTRACT
GUARDED_ACCEPTANCE_STATUS_PACKAGE_CONTRACT_READY
GUARDED_ORCHESTRATOR_RUNTIME_INTEGRATED_NOT_DEFAULT
GUARDED_FORM_WIDGET_RUNTIME_DOCKER_SMOKE_VALIDATED
WEBUI_PDF_PRODUCTION_PATH_BLOCKED_BY_COMMAND_ENVIRONMENT
WEBUI_PDF_PRODUCTION_PATH_PROVEN
UNSUPPORTED_RULE_PIPELINE_ACTIONABLE
AGENT_CANDIDATE_REPAIR_BLOCKED_BY_MISSING_EVIDENCE
SELF_EXTENDING_LOOP_VALIDATED_AND_REUSED_ON_SECOND_FIXTURE
ORCHESTRATOR_SELF_EXTENSION_RETRY_LOOP_VALIDATED_FAIL_CLOSED
WEBUI_SELF_EXTENSION_BLOCKED_BY_COMMAND_ENVIRONMENT
WEBUI_SELF_EXTENSION_UNSAFE_REVERTED
WEBUI_SELF_EXTENSION_SMOKE_BOUNDARY_HARDENED
```

## Production-readiness statement

Production readiness is not claimed.

H10K proved that the intended Open WebUI `PDF:` production intake path can reach Hermes, invoke the orchestrator, produce terminal artifacts, and route failed/escalation deliverables truthfully. H11 proved unsupported-rule actionability: unresolved blockers produced HERMES_REQUIRED / strategy-request artifacts and escalated truthfully instead of claiming remediation success. H12 added a guarded self-extension candidate loop and a target-specific safety gate for the preferred missing-ToUnicode blocker, but did not validate a new repair. H12R proved a controlled self-extension lifecycle on two synthetic fixtures, including second-fixture reuse, but did not enable generated strategies as production defaults. H13 made failed or blocked bounded self-extension attempts first-class in status/outcome. H13R failed as a WebUI smoke because the path drifted into source/rule-map mutation and self-extension did not run. H13S hardens that smoke boundary. None of H12/H12R/H13/H13R/H13S proves production adoption or beta readiness.

## H13R negative evidence

H13R reached the WebUI/orchestrator path and produced `STATUS.json` and `orchestrator_outcome.json`, but it did not validate the bounded self-extension retry-loop. The run reported self-extension as NOT_RUN and did not produce:

```text
audit/self_extension_run_attempts_result.json
audit/self_extension_residual_result.json
```

The run also drifted into prohibited source work in the local checkout:

```text
M app/tools/audit/rule_repair_map.json
?? app/tools/repair/fix_embed_nonsymbolic_fonts.py
?? workspace/extract_text.py
```

Those mutations were not valid evidence and must not be committed.

## Current H13S behavior

H13S adds an evidence-only smoke boundary wrapper:

```text
app/tools/orchestrate/self_extension_smoke_boundary.py
```

The wrapper is a production-approved smoke wrapper for H13/H13S/H13T evidence-only runs. It configures self-extension, runs the orchestrator, detects prohibited source-path mutation, and surfaces smoke-boundary evidence into:

```text
STATUS.json
audit/orchestrator_outcome.json
```

The smoke boundary records:

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

It forbids evidence-only smoke writes to:

```text
app/tools/repair/*.py
app/tools/audit/rule_repair_map.json
workspace/extract_text.py
```

## Self-extension NOT_RUN specificity

H13 status/outcome surfacing previously collapsed missing self-extension evidence into:

```text
self_extension_not_enabled_or_no_residual_gap
```

H13S smoke-boundary post-processing distinguishes evidence-only smoke blockers, including:

```text
self_extension_not_enabled
self_extension_enabled_but_no_target_rule
self_extension_enabled_but_no_residual_gap
self_extension_enabled_but_policy_blocked
self_extension_enabled_but_transport_unavailable
self_extension_enabled_but_target_rule_mismatch
self_extension_enabled_but_unexpectedly_not_run
```

If self-extension is configured for the smoke but does not run, the wrapper writes `self_extension_not_run_blocker` into `STATUS.json` and `audit/orchestrator_outcome.json`.

## Target-rule verification

Evidence-only smoke now supports an expected target rule. A mismatch is explicit:

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

A mismatch must not be reported as successful H13 WebUI retry-loop proof.

## Current H12R target rule

```text
PDF/UA-1/7.21.7
```

Description:

```text
Font dictionary missing ToUnicode map; character codes cannot be mapped to Unicode values.
```

Target-selection basis:

```text
app/tools/audit/rule_repair_map.json marks PDF/UA-1/7.21.7 as HERMES_REQUIRED and repairable_unbuilt with no active deterministic strategy.
```

## Artifact and safety policy

Failed generated candidates must not:

```text
update the final PDF
mutate the rule map
produce PASS
produce adoption
escape quarantine
overwrite source repair scripts
```

Evidence-only smoke mode additionally forbids:

```text
source repair script creation
repair script registration
rule-map mutation
generated candidate adoption
promotion of generated code to source
final-PDF update from failed candidates
silent target-rule switching
claiming self-extension ran without attempt evidence
```

Runtime artifacts remain forbidden in source control:

```text
workspace/
runtime candidate scripts
generated PDFs
private PDFs
validator XML sidecars
STATUS.json
orchestrator_outcome.json
candidate_result.json
package ZIPs
```

## Validation status

H13S code and regression tests were committed through the GitHub connector. Tests were not executed in this environment because the connector provides repository write access but not a live local checkout with Docker/Hermes/Open WebUI.

Required local validation after pulling H13S:

```bash
PYTHONPATH=app python3 -m unittest \
  app/tools/tests/test_self_extension_remediate_hook.py \
  app/tools/tests/test_self_extension_executor.py \
  app/tools/tests/test_self_extension_support.py \
  app/tools/tests/test_self_extension_run_state.py \
  app/tools/tests/test_self_extension_smoke_boundary.py \
  app/tools/tests/test_guarded_acceptance_status_package_policy.py
```

## Current status

```text
WEBUI_SELF_EXTENSION_SMOKE_BOUNDARY_HARDENED
```

The next WebUI proof has not yet been rerun after H13S hardening.

## Exact next step

```text
H13T — Rerun WebUI Self-Extension Retry Loop Smoke with Hardened Boundary
```
