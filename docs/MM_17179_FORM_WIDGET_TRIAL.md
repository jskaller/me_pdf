# MM-17179 Form-Widget Structure Trial (H10/H10A/H10A-V)

## Production-readiness goal

The system goal is a production-ready PDF remediation workflow, not a one-off PDF fix. The production path remains:

```text
Open WebUI prompt beginning with PDF:
Hermes loads the pdf-remediation runbook
/app/tools/orchestrate/remediate.py creates and executes the job
STATUS/package artifacts truthfully reflect PASS, REVIEW_REQUIRED, FAIL, or ESCALATION
```

H10, H10A, and H10A-V are controlled development validations. They do not activate a production repair, do not update the rule map, and do not replace the orchestrator-first production path.

## H10A evidence-bound correction

H10 found the MM-17179 form-widget blocker shape:

```text
AcroForm present: true
AcroForm field count: 24
Widget annotation count: 102
Widgets missing /StructParent: 102
Widgets with /StructParent: 0
/StructTreeRoot present: false
/ParentTree present: false
Form structure element count: 0
```

H10 was blocked because the diagnostic evidence was bounded at 100 widget records while the PDF contained 102 widgets:

```text
widget_annotation_count: 102
widgets_bounded_count: 100
widgets_truncated: true
```

H10A corrected the confusing blocker wording from `widget evidence is not truncated` to the failed precondition:

```text
widget evidence is truncated
```

and the positive precondition:

```text
widget evidence is complete
```

The H10A diagnostic/repair path now exposes:

```text
widgets_bounded_count
bounded_widget_records_count
widgets_truncated
widget_evidence_complete
max_widgets_requested
```

A dry-run is complete only when:

```text
widgets_truncated: false
bounded_widget_records_count == widget_annotation_count
widget_evidence_complete: true
```

## H10A isolated trial status before H10A-V

The local H10A isolated trial showed promising object-level evidence:

```text
widget_annotation_count: 102
widgets_with_struct_parent_count: 102
widgets_missing_struct_parent_count: 0
widgets_with_parent_tree_mapping_count: 102
widgets_already_nested_in_form_count: 102
form_struct_element_count: 102
struct_tree_root_present: true
parent_tree_present: true
parent_tree_entry_count: 102
widgets_truncated: false
widget_evidence_complete: true
```

qpdf and preservation are necessary, but they are not sufficient for adoption. H10A object diagnostics plus qpdf plus preservation must now be treated as:

```text
MM17179_REPAIR_VALIDATION_INCOMPLETE
```

until repo-approved veraPDF before/after delta evidence is available.

## H10A-V veraPDF validation correction

The H10A documentation previously described this as an acceptable manual validation pattern:

```text
command -v verapdf
veraPDF: NOT_RUN_ENVIRONMENT_LIMITED
```

That is superseded for this repository. H10A-V validation must use the orchestrator-approved veraPDF binary and profile runner unless the binary or profile root is genuinely absent. If that runtime is missing, the correct terminal state is:

```text
VERAPDF_RUN_FAILED
```

not a successful or environment-limited validation.

The approved runtime paths are:

```text
/opt/verapdf-greenfield/verapdf
/opt/veraPDF-validation-profiles-integration
/app/tools/audit/run_verapdf_profiles.sh
/app/tools/audit/parse_verapdf_summary.py
```

The runner writes per-profile XML sidecars and keeps stderr in separate sidecars. `audit/verapdf_summary.json` is diagnostic-only. Canonical H10A-V interpretation must derive from per-profile XML sidecars, parser output, and profile accounting.

## Profile accounting policy

For PDF/UA-1 validation, the authoritative required profiles are:

```text
PDF_UA/PDFUA-1.xml
PDF_UA/WCAG-2-2-Machine.xml
```

The pinned WCAG profile must be exactly:

```text
PDF_UA/WCAG-2-2-Machine.xml
```

The following profile is informational unless a later policy explicitly marks it authoritative:

```text
PDF_UA/ISO-32000-1-Tagged.xml
```

PDF/UA-2 is skipped unless explicitly requested:

```text
PDF_UA/PDFUA-2.xml
```

The following profile must not be used for a PDF/UA-1 verdict:

```text
PDF_UA/WCAG-2-2-Machine-PDF20.xml
```

Any PDF/UA-2 or PDF 2.0 namespace-specific profile is prohibited for PDF/UA-1 verdict use unless explicitly requested by policy. Experimental/custom XML profiles must be listed, hashed, classified, and preserved as diagnostic evidence; they must not silently hard-fail or pass the job.

## H10A-V commands

Verify the approved runtime and inputs:

```bash
docker compose exec -T hermes bash -lc '
set -e
test -x /opt/verapdf-greenfield/verapdf
test -d /opt/veraPDF-validation-profiles-integration
test -f /app/tools/audit/run_verapdf_profiles.sh
test -f /app/tools/audit/parse_verapdf_summary.py
test -f /app/workspace/input/MM-17179/ROI4987_English_1-26_rev_Fillable.pdf
test -f /tmp/h10a-mm17179-form-widget-trial/output.pdf
'
```

Run the before/after profiles with the approved runner:

```bash
docker compose exec -T hermes bash -lc '
cd /app &&
rm -rf /tmp/h10av-verapdf-before /tmp/h10av-verapdf-after &&
mkdir -p /tmp/h10av-verapdf-before /tmp/h10av-verapdf-after &&
bash /app/tools/audit/run_verapdf_profiles.sh \
  /opt/verapdf-greenfield/verapdf \
  /opt/veraPDF-validation-profiles-integration \
  /app/workspace/input/MM-17179/ROI4987_English_1-26_rev_Fillable.pdf \
  /tmp/h10av-verapdf-before || true
bash /app/tools/audit/run_verapdf_profiles.sh \
  /opt/verapdf-greenfield/verapdf \
  /opt/veraPDF-validation-profiles-integration \
  /tmp/h10a-mm17179-form-widget-trial/output.pdf \
  /tmp/h10av-verapdf-after || true
'
```

Parse required profile XML sidecars:

```bash
docker compose exec -T hermes bash -lc '
cd /app &&
PYTHONPATH=/app /usr/bin/python3 /app/tools/audit/parse_verapdf_summary.py \
  /tmp/h10av-verapdf-before/verapdf_pdfua_ua1.xml \
  /tmp/h10av-verapdf-before/verapdf_wcag_2_2_machine.xml \
  > /tmp/h10av-verapdf-before/parsed_failures.json
PYTHONPATH=/app /usr/bin/python3 /app/tools/audit/parse_verapdf_summary.py \
  /tmp/h10av-verapdf-after/verapdf_pdfua_ua1.xml \
  /tmp/h10av-verapdf-after/verapdf_wcag_2_2_machine.xml \
  > /tmp/h10av-verapdf-after/parsed_failures.json
'
```

Run profile accounting and delta analysis:

```bash
docker compose exec -T hermes bash -lc '
cd /app &&
PYTHONPATH=/app /usr/bin/python3 /app/tools/audit/verapdf_profile_accounting.py \
  --profiles-root /opt/veraPDF-validation-profiles-integration \
  --before-dir /tmp/h10av-verapdf-before \
  --after-dir /tmp/h10av-verapdf-after \
  --before-parsed /tmp/h10av-verapdf-before/parsed_failures.json \
  --after-parsed /tmp/h10av-verapdf-after/parsed_failures.json \
  --target-rule PDF/UA-1/7.18.4 \
  --out /tmp/h10av-verapdf-delta.json
'
```

This writes:

```text
/tmp/h10av-verapdf-before/profile_accounting.json
/tmp/h10av-verapdf-after/profile_accounting.json
/tmp/h10av-verapdf-delta.json
```

These files are runtime evidence only. Do not commit generated validator XML, generated JSON evidence, generated PDFs, private PDFs, or workspace artifacts.

## H10A-V terminal states

H10A-V uses these terminal states:

```text
VERAPDF_DELTA_VALIDATED
VERAPDF_DELTA_FAILED
VERAPDF_PROFILE_ACCOUNTING_FAILED
VERAPDF_RUN_FAILED
```

`VERAPDF_DELTA_VALIDATED` is allowed only if required profiles exist, required profiles ran, required profile XMLs are parseable, `PDF/UA-1/7.18.4` cleared or improved, no unacceptable new authoritative profile regression appeared, and experimental/custom profiles were accounted for without silently becoming authoritative.

`VERAPDF_DELTA_FAILED` means the target rule was unchanged or regressed, new authoritative failures were introduced, authoritative failure counts materially worsened, or qpdf/object/preservation evidence conflicts with veraPDF outcome.

`VERAPDF_PROFILE_ACCOUNTING_FAILED` means profile classification, profile hash/path/command/result recording, required profile selection, or XML sidecar interpretation is incomplete. Use this if `verapdf_summary.json` is the only evidence.

`VERAPDF_RUN_FAILED` means the approved binary, profile root, source PDF, after PDF, required XML sidecar, or parser execution is missing or failed.

## Rule-map adoption and production integration

Do not update `app/tools/audit/rule_repair_map.json` during H10A-V. Do not modify orchestrator, packaging, or status behavior during H10A-V.

H10B guarded strategy adoption may be reconsidered only if H10A-V reaches:

```text
VERAPDF_DELTA_VALIDATED
```

Even then, adoption must remain guarded, non-default, and precondition-gated until a separate patch proves orchestrator/package/status behavior.

## H10A-V files

H10A-V is limited to:

```text
app/tools/audit/verapdf_profile_accounting.py
app/tools/tests/test_verapdf_profile_accounting_policy.py
docs/MM_17179_FORM_WIDGET_TRIAL.md
docs/PDFUA_7_18_4_FORM_WIDGET_STRUCTURE_CONSTRUCTION.md
```

No private PDFs, generated PDFs, workspace artifacts, validator XML outputs, parsed failure JSON, profile accounting JSON, or delta JSON should be committed.

## Production-readiness statement

H10A-V does not claim production readiness. It closes the validator/profile-accounting gap required before any guarded form-widget strategy adoption can be reconsidered.
