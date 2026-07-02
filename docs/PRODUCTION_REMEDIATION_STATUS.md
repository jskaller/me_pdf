# Production Remediation Status

## Current production goal

Build a production-ready PDF remediation system that works through the intended production path:

```text
Open WebUI prompt beginning with PDF:
-> Hermes loads the pdf-remediation runbook
-> /app/tools/orchestrate/remediate.py creates and executes the job
-> veraPDF-driven failures produce repair plans
-> deterministic repairs run only when safe
-> Hermes/LLM handles unsupported or unknown issues
-> post-repair veraPDF/qpdf/QA gates run
-> STATUS.json and orchestrator_outcome.json truthfully report PASS, REVIEW_REQUIRED, FAIL, or ESCALATION
-> deliverables package reflects the authoritative outcome
```

## Current branch

```text
master
```

## Last completed patch

```text
H12R - Self-Extending Remediation Loop with Two Synthetic Fixtures
```

H12R terminal state:

```text
SELF_EXTENDING_LOOP_VALIDATED_AND_REUSED_ON_SECOND_FIXTURE
```

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
```

## Production-readiness statement

Production readiness is not claimed.

H10K proved that the intended Open WebUI `PDF:` production intake path can reach Hermes, invoke the orchestrator, produce terminal artifacts, and route failed/escalation deliverables truthfully. H11 proved unsupported-rule actionability: unresolved blockers produced HERMES_REQUIRED / strategy-request artifacts and escalated truthfully instead of claiming remediation success. H12 added a guarded self-extension candidate loop and a target-specific safety gate for the preferred missing-ToUnicode blocker, but did not validate a new repair.

H12R proves the self-extension lifecycle on two controlled synthetic fixtures with the same unsupported-but-remediable target class:

```text
unsupported synthetic PDF/UA-1/7.21.7 failure
-> strategy request emitted
-> candidate workbench consumes request
-> runtime candidate implementation generated under workspace/candidate_repairs
-> sandbox apply uses copied Fixture A PDF only
-> controlled validation clears target marker
-> candidate_result.json and adoption_proposal.json are produced
-> distinct Fixture B reuses Fixture A capability
-> Fixture B does not generate another candidate
-> STATUS.json and orchestrator_outcome.json report the controlled reuse result truthfully
```

H12R uses controlled equivalents for qpdf, veraPDF PDF/UA-1, pinned WCAG, ISO, profile accounting, and preservation because the synthetic fixtures are harness fixtures, not real production PDFs. H12R does not claim full validator authority and does not enable any generated strategy as a production default.

## Current H12R target rule

```text
PDF/UA-1/7.21.7
```

Description:

```text
Font dictionary missing ToUnicode map; character codes cannot be mapped to Unicode values.
```

Target-selection result:

```json
{
  "selected_target_rule": "PDF/UA-1/7.21.7",
  "existing_active_strategy": false,
  "existing_guarded_strategy_sufficient": false,
  "remediable_in_principle": true,
  "fixture_generation_feasible": true,
  "validation_feasible": true
}
```

Selection basis:

```text
app/tools/audit/rule_repair_map.json marks PDF/UA-1/7.21.7 as HERMES_REQUIRED and repairable_unbuilt with no active deterministic strategy.
```

## H12R implemented source

```text
app/tools/agent/create_candidate_repair.py
app/tools/tests/generate_h12r_fixtures.py
app/tools/tests/test_self_extending_candidate_workbench_policy.py
docs/H12R_SELF_EXTENDING_REMEDIATION_LOOP.md
```

## H12R synthetic fixture behavior

Fixture A:

```text
<workspace>/fixtures/h12r_fixture_a_missing_tounicode.pdf
fixture=A
object-seed=1201
H12R_TARGET_FAIL: PDF/UA-1/7.21.7
```

Fixture B:

```text
<workspace>/fixtures/h12r_fixture_b_missing_tounicode_distinct.pdf
fixture=B
object-seed=2209
H12R_TARGET_FAIL: PDF/UA-1/7.21.7
```

The fixtures are generated at runtime by `app/tools/tests/generate_h12r_fixtures.py`; they are not committed as binary PDFs. Fixture B differs from Fixture A by fixture marker, object seed, and visible text.

## H12R candidate workbench status

```text
strategy request consumed: true
candidate attempt directory: workspace/candidate_repairs/H12R-SYNTHETIC-A/pdf_ua_1_7_21_7/attempt-001/
candidate implementation generated at runtime: true
candidate generated under app/tools/repair: false
manual target repair committed: false
sandbox copied input used: true
candidate_result.json written: true
adoption_proposal.json written after validation: true
production_default: false
requires_real_verapdf_before_production: true
```

Fixture A controlled result:

```json
{
  "decision": "CANDIDATE_VALIDATED",
  "target_rule_before_count": 1,
  "target_rule_after_count": 0,
  "new_authoritative_failures": [],
  "increased_authoritative_failures": []
}
```

Fixture B controlled reuse result:

```json
{
  "decision": "REUSE_VALIDATED",
  "reused_strategy_from_fixture_a": true,
  "new_candidate_generation_attempted": false,
  "normal_pipeline_used": true,
  "status_json_result": "PASS",
  "orchestrator_outcome_result": "PASS",
  "target_rule_before_count": 1,
  "target_rule_after_count": 0
}
```

## Validation status

Focused validation run in the patch authoring environment:

```bash
cd /mnt/data/h12r
PYTHONPATH=app python3 -m unittest app/tools/tests/test_self_extending_candidate_workbench_policy.py
python3 -m py_compile app/tools/agent/create_candidate_repair.py app/tools/tests/generate_h12r_fixtures.py
```

Result:

```text
2 tests passed
py_compile passed
```

Full local validation still needs to be run after pulling because the GitHub connector environment cannot run Docker/WebUI/veraPDF against the repository checkout.

## Prior production path evidence status

```text
WebUI production-path evidence collected: true
WebUI production-path terminal state: WEBUI_PDF_PRODUCTION_PATH_PROVEN
Docker CLI guarded-runtime evidence collected: true
orchestrator end-to-end guarded-runtime evidence collected in Docker: true
STATUS/package behavior validated end-to-end in Docker CLI smoke: true
STATUS/package behavior validated by H10I/H10J policy tests: true
STATUS.json guarded truthfulness verified in Docker CLI smoke: true
orchestrator_outcome.json guarded truthfulness verified in Docker CLI smoke: true
deliverables package guarded report-only behavior verified in Docker CLI smoke: true
Open WebUI PDF intake path evidence collected in H10K: true
Open WebUI PDF intake path result: ESCALATION
Open WebUI PDF intake path unsupported PASS claim observed: false
Open WebUI PDF intake path production-readiness claim observed: false
```

## Current production readiness assessment

```text
Production-ready system: false
Open WebUI PDF path proven: true
Truthful terminal artifacts proven through WebUI: true
Truthful failed/escalation package routing proven through WebUI: true
Self-extending synthetic loop proven: true
Second-fixture reuse proven: true
Full validator-backed production repair for MM-17179 active blockers: false
Remaining work required before production readiness: true
```

## Next patch

Apply the workbench to a real active blocker from MM-17179, preferably `PDF/UA-1/7.21.7` or `PDF/UA-1/7.21.4.1`, and prove that the generated candidate improves the WebUI production-path outcome with authoritative qpdf, veraPDF PDF/UA-1, pinned WCAG, ISO, profile accounting, text/render/preservation, STATUS, and package evidence.
