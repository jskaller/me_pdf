# PDF/UA-1/7.18.4 Form-Widget Structure Construction

## Purpose

This document tracks the controlled form-widget structure-construction capability for `PDF/UA-1/7.18.4`. The capability is intended to move the remediation system toward production readiness, not to create a one-off PDF fix and not to bypass the orchestrator-first production workflow.

The production user-facing workflow remains:

```text
Open WebUI prompt beginning with PDF:
Hermes loads the pdf-remediation runbook
/app/tools/orchestrate/remediate.py runs the job
STATUS/package artifacts truthfully report the terminal outcome
```

Standalone repair scripts may be used here only as controlled development validation. They do not replace orchestrator production flow.

## H9 controlled fixture capability

H9 added a guarded fixture-scoped capability for AcroForm widget annotations that lack `/StructParent` and are not represented by `/Form` structure elements.

The synthetic fixture shape is:

```text
one or more AcroForm fields
one widget annotation per field
page /Annots membership
synthetic field names and synthetic values only
widgets initially lacking /StructParent
no /StructTreeRoot
no /ParentTree
no /Form structure elements
```

The guarded repair algorithm:

1. opens the PDF with pikepdf;
2. enumerates widget annotations from page `/Annots`;
3. preserves AcroForm fields, field names, field types, field-value presence, widget relationships, page membership, page count, and page boxes;
4. creates `/StructTreeRoot` when missing;
5. creates `/ParentTree` when missing;
6. assigns stable integer `/StructParent` values to widgets that lack them;
7. creates one `/Form` structure element per widget;
8. links each `/Form` element to its widget annotation through an `/OBJR` object reference;
9. appends each `/Form` element to the structure root `/K` array;
10. maps each widget `/StructParent` key through `/ParentTree /Nums`;
11. writes only to an explicit output path;
12. emits before/after diagnostics and preservation evidence.

## Guardrails

The repair tool remains guarded:

```text
source overwrite refused
workspace job/final/status paths refused for trial apply
rule-map mutation never performed by the repair tool
workspace artifact mutation never performed by the repair tool
production readiness claim never made by the repair tool
field values not dumped
```

For non-fixture inputs, apply requires an explicit `--allow-structure-construction-trial` flag and an explicit output path. H10A uses this only for an isolated `/tmp` MM-17179 trial.

## H10/H10A MM-17179 evidence

MM-17179 exhibits the target blocker shape:

```text
AcroForm present: true
AcroForm field count: 24
Widget annotation count: 102
Widgets with /StructParent: 0
Widgets missing /StructParent: 102
/StructTreeRoot present: false
/ParentTree present: false
Structure element count: 0
Form structure element count: 0
```

H10A added explicit widget-evidence completeness accounting so the 102-widget MM-17179 source is not blocked by the default bounded report of 100 records. Complete evidence requires:

```text
widgets_truncated: false
bounded_widget_records_count == widget_annotation_count
widget_evidence_complete: true
```

Object-level after diagnostics for the isolated trial must prove:

```text
widget annotation count preserved
widgets missing /StructParent reduced to 0
widgets with /StructParent increased to 102
/StructTreeRoot present
/ParentTree present
/Form structure element count increased to 102
widgets with ParentTree mapping increased to 102
widgets already nested in Form increased to 102
```

The preservation summary must prove:

```text
field count preserved
field names preserved
field types preserved
field value presence preserved
widget count preserved
widget page membership preserved
page count preserved
page boxes preserved
semantic widget identity preserved
exact object identity not falsely claimed
field values not dumped
```

## qpdf and veraPDF validation

qpdf must pass on any isolated output before adoption is considered.

For this repository, veraPDF validation for H10A/H10A-V must use the orchestrator-approved binary, profile root, runner, XML sidecars, parser, and profile accounting. The old H9/H10A wording that allowed `command -v verapdf` and `veraPDF: NOT_RUN_ENVIRONMENT_LIMITED` as an acceptable validation path is superseded.

Approved paths:

```text
/opt/verapdf-greenfield/verapdf
/opt/veraPDF-validation-profiles-integration
/app/tools/audit/run_verapdf_profiles.sh
/app/tools/audit/parse_verapdf_summary.py
```

If the approved binary/profile root is genuinely absent, the terminal state is:

```text
VERAPDF_RUN_FAILED
```

not an adoption-ready environment-limited pass.

## Profile accounting

For PDF/UA-1 output, required authoritative profiles are:

```text
PDF_UA/PDFUA-1.xml
PDF_UA/WCAG-2-2-Machine.xml
```

The pinned WCAG profile must be exactly:

```text
PDF_UA/WCAG-2-2-Machine.xml
```

The ISO profile is informational unless a separate policy marks it authoritative:

```text
PDF_UA/ISO-32000-1-Tagged.xml
```

PDF/UA-2 is skipped unless explicitly requested:

```text
PDF_UA/PDFUA-2.xml
```

The PDF 2.0 WCAG machine profile must not be used for PDF/UA-1 verdicts:

```text
PDF_UA/WCAG-2-2-Machine-PDF20.xml
```

Experimental/custom XML profiles must be listed, hashed, classified, and preserved as diagnostic evidence. They are non-authoritative by default and must not silently pass or fail the H10A-V verdict.

`verapdf_summary.json` is diagnostic-only. Compliance/verdict interpretation must come from per-profile XML sidecars, parser output, and profile accounting.

## H10A-V accounting helper

H10A-V adds:

```text
app/tools/audit/verapdf_profile_accounting.py
app/tools/tests/test_verapdf_profile_accounting_policy.py
```

The helper records, for each relevant profile:

```text
profile_id
profile_path
profile_sha256
profile_name_or_filename
classification
required
run_by_default
was_run
was_skipped
skip_reason
verdict_authoritative
parse_for_rule_map
command
output_xml
stderr_sidecar
exit_code
result
failed_rules
failed_checks
passed_rules
passed_checks
```

It writes runtime-only artifacts when run in Docker:

```text
/tmp/h10av-verapdf-before/profile_accounting.json
/tmp/h10av-verapdf-after/profile_accounting.json
/tmp/h10av-verapdf-delta.json
```

Do not commit these generated artifacts.

## H10A-V terminal states

```text
VERAPDF_DELTA_VALIDATED
VERAPDF_DELTA_FAILED
VERAPDF_PROFILE_ACCOUNTING_FAILED
VERAPDF_RUN_FAILED
```

`VERAPDF_DELTA_VALIDATED` is allowed only when required profiles exist, required profile XML sidecars are present and parseable, `PDF/UA-1/7.18.4` cleared or improved, no unacceptable new authoritative failures were introduced, and experimental/custom profiles were accounted without becoming authoritative by default.

`VERAPDF_DELTA_FAILED` means the target rule was unchanged/regressed or authoritative failures worsened.

`VERAPDF_PROFILE_ACCOUNTING_FAILED` means profile selection/classification/hash/path/command/result accounting is incomplete or the wrong PDF/UA-1/WCAG profile is used.

`VERAPDF_RUN_FAILED` means the approved validator runtime, required profile, before PDF, after PDF, XML sidecar, or parser execution is missing or failed.

## Rule-map and production integration

Do not modify `app/tools/audit/rule_repair_map.json`, `app/tools/orchestrate/remediate.py`, or `app/tools/packaging/` as part of H10A-V.

Guarded strategy adoption may be reconsidered only after H10A-V reaches `VERAPDF_DELTA_VALIDATED`, and even then it must be a separate non-default, precondition-gated patch with no false production-readiness claim.

## Production-readiness statement

This capability is not production-ready merely because object diagnostics, qpdf, or preservation pass. H10A-V is required validator/profile-accounting evidence before adoption can be reconsidered. Production readiness still requires orchestrator integration, rule-map governance, truthful STATUS/outcome packaging, and end-to-end validation in a later patch.
