# H10G Guarded Form-Widget Runtime Integration

## Baseline

```text
36ce575
Finalize H10F commit references
```

Implementation baseline from H10F:

```text
ae30944
Adopt guarded form-widget metadata
```

## Commits in this patch

```text
75f33f0 Add guarded form-widget lookup gating
90163d8 Add guarded form-widget lookup gating tests
```

This document is part of the H10G documentation/status finalization layer. The repository's final H10G commit should be read from `docs/PRODUCTION_REMEDIATION_STATUS.md` and `git log` after the terminal status commit lands.

## Terminal state

```text
LOOKUP_GATING_IMPLEMENTED_ORCHESTRATOR_DEFERRED
```

## Summary

H10G implements explicit fail-closed lookup gating for the guarded PDF/UA-1/7.18.4 form-widget repair candidate. It does not activate the repair by default, does not move the candidate into active `strategies[]`, and does not make a production-readiness claim.

The guarded candidate remains metadata-only in `rule_repair_map.json` unless the lookup caller opts in and supplies a valid precondition report.

## Lookup gating status

```text
implemented: true
default-on: false
required flag: --enable-guarded-candidates
required precondition input: --precondition-report <path>
```

Default lookup behavior remains unchanged for PDF/UA-1/7.18.4:

```text
result: ALL_MANUAL
repair_steps: []
repair_form_widget_structure.py emitted: false
guarded candidates evaluated: false
```

Guarded lookup behavior:

```text
--enable-guarded-candidates absent: guarded candidates ignored
--enable-guarded-candidates present without --precondition-report: blocked
missing report path: blocked
malformed report: blocked
failed precondition: blocked
valid preconditions: guarded repair step may be emitted
```

## Guarded repair step shape

When all guarded preconditions pass, lookup may emit a repair step with the following distinguishing properties:

```json
{
  "rule_id": "PDF/UA-1/7.18.4",
  "strategy_id": "form_widget_structure_construction_v1",
  "repair_script": "tools/repair/repair_form_widget_structure.py",
  "repair_version": "1.4.0",
  "guarded": true,
  "runtime_active": false,
  "production_default": false,
  "requires_post_validation": true,
  "required_terminal_behavior": "REVIEW_REQUIRED_IF_RESIDUAL_FAILURES_REMAIN"
}
```

The step is intentionally distinguishable from ordinary active strategy output.

## Required preconditions

The lookup gate requires all of the following before emitting the guarded repair:

```text
rule_id is PDF/UA-1/7.18.4
guarded candidate metadata exists
strategy_id is form_widget_structure_construction_v1
repair_script is tools/repair/repair_form_widget_structure.py
repair_version is 1.4.0
runtime_active is false
production_default is false
activation_status is guarded_metadata_only
requires_runtime_gating_implementation is true
requires_explicit_activation_patch is true
precondition report exists and is parseable JSON
precondition report schema is montefiore.form_widget_structure_inspection when present
precondition target_rule matches PDF/UA-1/7.18.4 when present
precondition report is read-only evidence
precondition report includes PDF path or job context
AcroForm is present
widget_annotation_count > 0
widgets_bounded_count == widget_annotation_count
widget_evidence_complete is true
widgets_truncated is false
widgets_missing_struct_parent_count > 0 OR target failure evidence is present
planned_struct_tree_root_creation is true when no StructTreeRoot exists
planned_parent_tree_creation is true when no ParentTree exists
planned_struct_parent_assignments > 0
planned_form_struct_elements > 0
field values are not dumped or sensitive values are redacted
source overwrite is not allowed
output path discipline is explicit_safe_intermediate_required, lookup_does_not_write_outputs, or explicit_output_path true
```

## Required post-validations

Any guarded runtime caller must still run the post-validation gate set recorded in the emitted step:

```text
qpdf
verapdf_pdfua1
verapdf_pinned_wcag
verapdf_iso_no_regression
profile_accounting
form_widget_structure_inspection
preservation
```

Residual failures after the guarded repair must produce REVIEW_REQUIRED rather than a false PASS.

## Orchestrator integration status

```text
implemented: false
deferred: true
```

The orchestrator was not wired to invoke the guarded form-widget repair in H10G.

Reason for deferral:

```text
lookup can now fail closed and emit a guarded step, but full orchestrator runtime still needs a separate patch to wire safe intermediate output paths, run the complete post-validation bundle, preserve STATUS.json/orchestrator_outcome.json truthfulness, and ensure deliverables packaging cannot route a false-success PDF.
```

Additional precondition-contract issue:

```text
form_widget_structure_inspection.py currently supplies object evidence such as widget counts, truncation status, AcroForm presence, StructTreeRoot/ParentTree presence, and redaction status. It does not itself produce every runtime planning assertion required by H10G, including planned_struct_parent_assignments and planned_form_struct_elements. The guarded lookup therefore requires those fields from a precondition report or guarded runtime wrapper before emission.
```

## Rule-map and runtime safety

```text
rule_repair_map.json changed: false
active strategies[] changed: false
repair_form_widget_structure.py changed: false
packaging/status scripts changed: false
default lookup emits repair_form_widget_structure.py: false
guarded lookup can emit repair_form_widget_structure.py only with explicit flags and valid preconditions: true
runtime activation default-on: false
```

## Production-path evidence

```text
WebUI PDF: production-path evidence collected: false
orchestrator end-to-end guarded-runtime evidence collected: false
STATUS.json production truthfulness verified end-to-end: false
orchestrator_outcome.json production truthfulness verified end-to-end: false
deliverables package production evidence collected: false
```

## Production-readiness statement

Production readiness is not claimed.

H10G adds a guarded lookup gate, not a full production-path repair activation. The production system still needs orchestrator guarded-runtime integration and WebUI `PDF:` production-path evidence before this repair can be considered production-ready.

## Next recommended patch

```text
H10H - Orchestrator guarded-runtime integration for PDF/UA-1/7.18.4
```

H10H should wire the existing lookup gate into `app/tools/orchestrate/remediate.py` behind an explicit opt-in flag, generate or load the required precondition report, run the repair only to a safe intermediate output path, execute qpdf/veraPDF/profile-accounting/preservation/post-inspection gates, and preserve REVIEW_REQUIRED/status/package truthfulness when residual failures remain.
