# H10K - WebUI PDF Production Path Evidence

## Baseline commit

```text
58c42f4 Document H10J guarded runtime completion
```

## Terminal state

```text
WEBUI_PDF_PRODUCTION_PATH_BLOCKED_BY_COMMAND_ENVIRONMENT
```

## Summary

H10K was scoped to prove or truthfully block the intended Open WebUI production path for a prompt beginning with `PDF:`.

This pass did not prove the path. The available execution environment had GitHub repository access only. It did not provide a live local Docker stack, Open WebUI browser session, Hermes runtime, `/app`, `/app/workspace`, source PDFs, command approval visibility, or runtime logs. Therefore the WebUI prompt could not be submitted and runtime artifacts could not be collected.

## Resolved handoff typo

The handoff requested `docs/H10J_GUARDED_ORCHESTRATOR_RUNTIME_INTEGRATION.md`. That file does not exist at the H10J baseline. The actual H10J document is `docs/H10J_GUARDED_FORM_WIDGET_RUNTIME_INTEGRATION.md`. The operator confirmed the typo and approved this substitution.

## Repository evidence reviewed

The following repo contracts were reviewed from the H10J baseline:

```text
docs/PRODUCTION_REMEDIATION_STATUS.md
docs/H10J_GUARDED_FORM_WIDGET_RUNTIME_INTEGRATION.md
docs/H10I_GUARDED_FORM_WIDGET_ACCEPTANCE_STATUS_PACKAGE_CONTRACT.md
docs/H10H_ORCHESTRATOR_GUARDED_FORM_WIDGET_RUNTIME.md
docs/H10G_GUARDED_FORM_WIDGET_RUNTIME_INTEGRATION.md
docs/WEBUI_PDF_E2E_VERIFICATION.md
docs/WEBUI_PDF_RUNTIME_VERIFICATION.md
README.md
app/hermes_skills/pdf-remediation/SKILL.md
app/skills/montefiore-pdfua-unified-v6/SKILL.md
app/skills/montefiore-pdfua-unified-v6/docs/RUNBOOK.md
app/tools/orchestrate/remediate.py
app/tools/orchestrate/guarded_acceptance.py
app/tools/packaging/status_json_writer.py
app/tools/packaging/package_deliverables.py
app/tools/audit/lookup_repair_plan.py
docker-compose.yml
```

Repo-side contracts remain coherent: H10J guarded runtime is opt-in, not default; guarded lookup remains fail-closed; guarded candidates are intermediate unless acceptance allows promotion; `STATUS.json` and package routing have guarded fail-closed overlays; Open WebUI is configured to point to the Hermes gateway in Docker Compose. These facts are necessary but not sufficient WebUI proof.

## Intended H10K runtime input

```text
job_id: MM-17179-H10K-WEBUI2
source_pdf: /app/workspace/input/MM-17179/ROI4987_English_1-26_rev_Fillable.pdf
expected_job_dir: /app/workspace/jobs/MM-17179-H10K-WEBUI2_ROI4987_English_1-26_rev_Fillable
```

The source PDF could not be verified because `/app/workspace` was not available in this execution environment.

## WebUI prompt status

No Open WebUI prompt was submitted. The blocker occurred before WebUI execution.

The next live-runtime attempt should submit a first message beginning exactly with `PDF:` and should instruct Hermes to load the pdf-remediation runbook, use `/app/tools/orchestrate/remediate.py`, use `/app/workspace`, enable guarded form-widget runtime only through the explicit opt-in supported by the current runbook, and report only artifact-supported facts from `STATUS.json`, `orchestrator_outcome.json`, and package outputs.

## Required checks answered

```text
Did WebUI accept the PDF: prompt? NOT TESTED
Did Hermes load the pdf-remediation runbook? NOT TESTED
Did Hermes attempt to invoke /app/tools/orchestrate/remediate.py? NOT TESTED
Did the command use the correct container path and PYTHONPATH wrapper? NOT TESTED
Did terminal approval block execution? UNKNOWN
Did the orchestrator start? NOT TESTED
Did the orchestrator complete to a terminal state? NOT TESTED
Did STATUS.json leave IN_PROGRESS? NOT TESTED
Was orchestrator_outcome.json produced? NOT TESTED
Was guarded_acceptance.json produced when guarded runtime reached acceptance? NOT TESTED
Did package routing match the terminal state? NOT TESTED
Did the final WebUI response match STATUS.json and orchestrator_outcome.json? NOT TESTED
Did any response claim unsupported success? NOT TESTED
```

## Tests and checks

No local test commands were executed because the required local checkout/runtime was not available. Before any H10K proven-state claim, run the H10J/H10K policy checks in the live repo environment, including:

```bash
PYTHONPATH=app python3 -m unittest \
  app/tools/tests/test_orchestrator_guarded_form_widget_policy.py \
  app/tools/tests/test_guarded_acceptance_status_package_policy.py

PYTHONPATH=app python3 app/tools/tests/test_m1_gate_verdict.py
```

## Production-readiness statement

Production readiness is not claimed.

H10J remains Docker CLI guarded-runtime evidence only. The intended Open WebUI `PDF:` production path remains unproven.

## Next patch

Do not move to H11 yet. Repeat H10K in an environment with a live local Docker stack, Open WebUI, Hermes, `/app`, `/app/workspace`, the MM-17179 source PDF, and the ability to collect command/session logs and workspace artifacts.
