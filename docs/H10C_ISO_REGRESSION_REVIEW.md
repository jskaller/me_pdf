# H10C ISO Regression Review

## Terminal state

```text
ISO_REGRESSION_REQUIRES_REPAIR_CHANGE
```

## Scope

H10C adds a testable ISO regression review helper for the H10A-V informational ISO profile regression associated with the `PDF/UA-1/7.18.4` form-widget repair trial.

The production-readiness goal remains the orchestrator-first workflow:

```text
Open WebUI prompt beginning with PDF:
→ Hermes loads the pdf-remediation runbook
→ /app/tools/orchestrate/remediate.py creates and executes the job
→ veraPDF-driven failures produce repair plans
→ deterministic repairs run only when safe
→ Hermes/LLM handles unsupported or unknown issues
→ post-repair veraPDF/qpdf/QA gates run
→ STATUS.json and orchestrator_outcome.json truthfully report PASS, REVIEW_REQUIRED, FAIL, or ESCALATION
→ deliverables package reflects the authoritative outcome
```

H10C does not change that production path.

## Why metadata remains deferred

H10A-V recorded strong target-rule evidence:

```text
target rule: PDF/UA-1/7.18.4
before count: 204
after count: 0
target status: CLEARED
required PDF/UA-1 and pinned WCAG profiles: ran and parsed
qpdf: PASS
object diagnostics: PASS
preservation: PASS
experimental/custom profiles: accounted and non-authoritative by default
PDF20 profiles: prohibited for PDF/UA-1 verdict
```

H10B deferred metadata adoption because H10A-V also recorded:

```text
PDF_UA/ISO-32000-1-Tagged.xml
before: PASS
after: FAIL
classification: informational
```

H10C reproduced and reviewed that ISO PASS→FAIL regression with runtime sidecar evidence. The review classified the regression as:

```text
STRUCTURAL_SIDE_EFFECT
```

Therefore guarded metadata adoption remains blocked, and the form-widget repair needs a targeted structural adjustment before any metadata adoption or runtime integration can proceed.

## Runtime ISO evidence reviewed

The runtime evidence used the uncommitted `/tmp` sidecars generated inside the Hermes container:

```text
/tmp/h10c-verapdf-before/verapdf_iso_32000_1_tagged.xml
/tmp/h10c-verapdf-after/verapdf_iso_32000_1_tagged.xml
/tmp/h10c-verapdf-before/profile_accounting.json
/tmp/h10c-verapdf-after/profile_accounting.json
/tmp/h10c-verapdf-delta.json
/tmp/h10c-iso-regression-review.json
```

These generated validator and review artifacts are runtime evidence only and must not be committed.

The ISO review recorded:

```text
before_iso_result: PASS
after_iso_result: FAIL
classification: STRUCTURAL_SIDE_EFFECT
blocks_metadata_adoption: true
blocks_runtime_activation: true
```

The new ISO rule ID was:

```text
ISO 19005-2:2011/Annex_L
```

The changed check was:

```text
before_failed_checks: 0
after_failed_checks: 1
delta: 1
```

The helper found these correlations:

```text
correlation_to_form_widget_objects: true
correlation_to_struct_tree_root: true
correlation_to_parent_tree: true
correlation_to_objr: false
correlation_to_struct_parent: false
```

Recommendation from the runtime ISO review:

```text
New or increased ISO checks correlate with form-widget or structure-construction evidence.
```

## Added helper

H10C adds:

```text
app/tools/audit/verapdf_iso_regression_review.py
```

The helper compares before/after ISO XML sidecars and optional profile-accounting and repair-report evidence. It writes a runtime-only review JSON when invoked with `--out`.

Required runtime command shape:

```bash
PYTHONPATH=/app /usr/bin/python3 /app/tools/audit/verapdf_iso_regression_review.py \
  --before-xml /tmp/h10c-verapdf-before/verapdf_iso_32000_1_tagged.xml \
  --after-xml /tmp/h10c-verapdf-after/verapdf_iso_32000_1_tagged.xml \
  --before-accounting /tmp/h10c-verapdf-before/profile_accounting.json \
  --after-accounting /tmp/h10c-verapdf-after/profile_accounting.json \
  --repair-report /tmp/h10a-mm17179-form-widget-trial/apply-report.json \
  --out /tmp/h10c-iso-regression-review.json
```

Do not commit `/tmp/h10c-iso-regression-review.json`.

## Helper output

The helper records:

```text
schema
created_at
before_iso_xml
after_iso_xml
before_iso_result
after_iso_result
before_failed_rules
after_failed_rules
new_iso_rule_ids
increased_iso_rule_ids
new_or_increased_iso_checks
affected_objects_or_contexts_if_extractable
correlation_to_form_widget_objects
correlation_to_struct_tree_root
correlation_to_parent_tree
correlation_to_objr
correlation_to_struct_parent
classification
blocks_metadata_adoption
blocks_runtime_activation
recommendation
```

Allowed classifications are:

```text
BENIGN_INFORMATIONAL
PROFILE_ACCOUNTING_ARTIFACT
VALIDATOR_INTERPRETATION_ONLY
STRUCTURAL_SIDE_EFFECT
INCONCLUSIVE
```

The helper is intentionally conservative. It does not classify a PASS→FAIL regression as benign without XML evidence showing no new or increased failed checks. If new or increased ISO failures correlate with form-widget objects, `/StructTreeRoot`, `/ParentTree`, `/OBJR`, or `/StructParent`, it classifies the regression as `STRUCTURAL_SIDE_EFFECT` and blocks metadata adoption.

## Rule-map status

H10C does not change:

```text
app/tools/audit/rule_repair_map.json
```

No guarded metadata is adopted in this commit.

No active executable strategy is added.

`PDF/UA-1/7.18.4` remains non-runtime-active.

## Lookup safety

H10C preserves the H10B lookup safety rule:

```text
lookup_repair_plan.py must not emit tools/repair/repair_form_widget_structure.py as an executable production repair step.
```

The helper and tests do not modify `lookup_repair_plan.py`.

## Production path status

H10C does not change:

```text
app/tools/orchestrate/remediate.py
app/tools/packaging/status_json_writer.py
app/tools/packaging/package_deliverables.py
```

H10C does not claim production readiness.

H10C does not activate runtime form-widget repair.

H10C does not commit private PDFs, generated PDFs, workspace artifacts, validator XML outputs, parsed-failure JSON, profile-accounting JSON, delta JSON, or ISO review JSON.

## Required next action

The next patch must inspect and adjust the form-widget repair structure construction so it clears `PDF/UA-1/7.18.4` without introducing the ISO profile regression.

The next patch must rerun:

```text
H10A isolated apply
qpdf
before/after object diagnostics
preservation
repo-approved veraPDF profiles
profile accounting
ISO regression review
lookup safety
```

Required target:

```text
PDF/UA-1/7.18.4: 204 → 0
ISO-32000-1-Tagged: no PASS→FAIL regression
no authoritative PDF/UA-1/WCAG regression
lookup still does not emit repair_form_widget_structure.py as executable production strategy
```

## Recommended next patch

```text
H10D — Repair Form-Widget Structure Construction ISO Side Effect
```

H10D should fix the structural side effect before reconsidering guarded metadata adoption. If H10D fixes the ISO regression and preserves target-rule clearance, a later guarded metadata patch may add non-runtime strategy metadata while keeping active `strategies[]` unchanged.
