# H10K - WebUI PDF Production Path Evidence

## Baseline commit

```text
58c42f4 Document H10J guarded runtime completion
```

## Terminal state

```text
WEBUI_PDF_PRODUCTION_PATH_PROVEN
```

## Summary

H10K proves the intended Open WebUI `PDF:` production path can run through Hermes, invoke the orchestrator, create the workspace job, execute the guarded form-widget runtime under explicit opt-in, produce terminal artifacts, route deliverables according to the authoritative outcome, and produce a WebUI response grounded in those artifacts.

This was a truthful terminal `ESCALATION` run, not a PASS remediation and not a production-readiness claim.

## Resolved handoff typo

The handoff requested `docs/H10J_GUARDED_ORCHESTRATOR_RUNTIME_INTEGRATION.md`. That file does not exist at the H10J baseline. The actual H10J document is `docs/H10J_GUARDED_FORM_WIDGET_RUNTIME_INTEGRATION.md`. The operator confirmed the typo and approved this substitution.

## Runtime environment and setup evidence

The local runtime was updated to the H10K documentation baseline:

```text
HEAD before live rerun: 7775616 Record H10K WebUI production path blocker
Source PDF staged for ticket convention: /app/workspace/input/MM-17179-H10K-WEBUI2/ROI4987_English_1-26_rev_Fillable.pdf
Hermes approval mode: auto
```

An initial WebUI attempt reached the orchestrator but blocked at `SETUP/prereq_check` because the source PDF existed under `/app/workspace/input/MM-17179/` while the orchestrator constructs the source path as `/app/workspace/input/<TICKET>/<BASENAME>.pdf`. The source PDF was then copied into the H10K ticket-specific input directory and the WebUI test was rerun.

## Exact runtime input

```text
job_id: MM-17179-H10K-WEBUI2
source_pdf: /app/workspace/input/MM-17179-H10K-WEBUI2/ROI4987_English_1-26_rev_Fillable.pdf
job_dir: /app/workspace/jobs/MM-17179-H10K-WEBUI2_ROI4987_English_1-26_rev_Fillable
```

## Required checks answered

```text
Did WebUI accept the PDF: prompt? YES
Did Hermes load/use the remediation workflow? YES
Did Hermes invoke /app/tools/orchestrate/remediate.py? YES
Did terminal approval block execution? NO; approval mode was auto and Hermes used a temp script to avoid inline -c approval friction
Did the orchestrator start? YES
Did the orchestrator complete to a terminal state? YES
Did STATUS.json leave IN_PROGRESS? YES
Was STATUS.json produced? YES
Was orchestrator_outcome.json produced? YES
Was guarded_acceptance.json produced when guarded runtime reached acceptance? YES
Did package routing match the terminal state? YES
Did final WebUI response avoid unsupported PASS or production-readiness claims? YES
```

## Runtime artifacts produced

```text
/app/workspace/jobs/MM-17179-H10K-WEBUI2_ROI4987_English_1-26_rev_Fillable/STATUS.json
/app/workspace/jobs/MM-17179-H10K-WEBUI2_ROI4987_English_1-26_rev_Fillable/audit/orchestrator_outcome.json
/app/workspace/jobs/MM-17179-H10K-WEBUI2_ROI4987_English_1-26_rev_Fillable/audit/guarded_acceptance.json
/app/workspace/jobs/MM-17179-H10K-WEBUI2_ROI4987_English_1-26_rev_Fillable/audit/hermes_strategy_request.json
/app/workspace/guarded_candidates/MM-17179-H10K-WEBUI2_ROI4987_English_1-26_rev_Fillable/form_widget_structure/output.pdf
/app/workspace/output/MM-17179-H10K-WEBUI2_remediated/failed/ESCALATION_REPORT.md
/app/workspace/output/MM-17179-H10K-WEBUI2_remediated/failed/ROI4987_English_1-26_rev_Fillable_AUDIT_REPORT.md
/app/workspace/output/MM-17179-H10K-WEBUI2_remediated/failed/SHA256SUMS.txt
```

No successful final remediated PDF was copied to deliverables.

## STATUS.json / orchestrator_outcome result

```text
STATUS.json overall_result: ESCALATION
STATUS.json result: ESCALATION
orchestrator_outcome.json overall_result: ESCALATION
orchestrator_outcome escalation_upgrade: true
shared verdict inside orchestrator_outcome: FAIL
critical_fails: verapdf_pdfua1, verapdf_wcag
table_semantics: REVIEW_REQUIRED
```

The terminal outcome is therefore `ESCALATION`, driven by active actionable HERMES signals and unresolved authoritative validator failures.

## Guarded form-widget evidence

```text
target_rule: PDF/UA-1/7.18.4
repair_strategy_id: form_widget_structure_construction_v1
target_rule_before_count: 204
target_rule_after_count: 0
target_rule_status: CLEARED
candidate_pdf: /app/workspace/guarded_candidates/MM-17179-H10K-WEBUI2_ROI4987_English_1-26_rev_Fillable/form_widget_structure/output.pdf
qpdf_result: PASS
profile_accounting_result: PASS
preservation_result: PASS
verapdf_iso_result: PASS
verapdf_pdfua1_result: FAIL
verapdf_wcag_result: FAIL
iso_regression_result: FAIL
post_form_widget_inspection_result: INSPECTED
guarded_acceptance_result: GUARDED_CANDIDATE_REJECTED_STRUCTURE_DIAGNOSTIC
status_result: FAIL
package_policy: REPORT_ONLY
pass_allowed: false
promote_candidate_to_final: false
guarded_candidate_promoted_to_final: false
```

The guarded candidate cleared the target rule count but was correctly rejected as an intermediate candidate. The package remained report-only/failed-output only, which is the expected fail-closed behavior.

## Active actionable HERMES signals

`orchestrator_outcome.json` reported three active actionable rules:

```text
PDF/UA-1/7.18.4 - all_strategies_exhausted
PDF/UA-1/7.21.4.1 - unknown_rule
PDF/UA-1/7.21.7 - all_strategies_exhausted
```

A zero-count `PDF/UA-1/7.18.1` signal was suppressed by reconciliation and was not an active blocker in the artifact summary.

## Final WebUI response comparison

The final WebUI response was grounded in the artifacts: it named the job directory, reported that `STATUS.json`, `orchestrator_outcome.json`, and `guarded_acceptance.json` existed, identified `STATUS.json overall_result: ESCALATION`, reported `GUARDED_CANDIDATE_REJECTED_STRUCTURE_DIAGNOSTIC`, stated `pass_allowed: false`, reported that the guarded candidate was not promoted, and stated that the job is not production-ready and no remediated PDF was packaged.

One response-label mismatch was observed: the response headline said `Job Complete - FAIL`, while `STATUS.json` and `orchestrator_outcome.json` both said `ESCALATION`. Because the response immediately identified the artifact-authoritative `ESCALATION` result and did not claim PASS or production readiness, this is recorded as a minor wording mismatch, not a WebUI production-path failure.

## Tests and checks

The live H10K run itself produced the required runtime evidence. The previously required policy tests should still be run locally before future patch work if not already run after this commit:

```bash
PYTHONPATH=app python3 -m unittest \
  app/tools/tests/test_orchestrator_guarded_form_widget_policy.py \
  app/tools/tests/test_guarded_acceptance_status_package_policy.py

PYTHONPATH=app python3 app/tools/tests/test_m1_gate_verdict.py
```

This documentation update does not require committing runtime workspace artifacts, source PDFs, generated PDFs, validator XML, `STATUS.json`, `orchestrator_outcome.json`, `guarded_acceptance.json`, or package ZIPs.

## Production-readiness statement

Production readiness is not claimed.

H10K proves the Open WebUI `PDF:` production path can reach Hermes, run the orchestrator, produce terminal artifacts, and route a truthful failed/escalation package without a false success claim. The system is still not production-ready because active remediation blockers remain for the current document/rule families.

## Next patch

```text
H11 - Active Blocker-Family Remediation Batch / Production Readiness Candidate
```

H11 should address the active actionable blockers surfaced by the H10K WebUI run before claiming production readiness or expanding to unrelated repair families.
