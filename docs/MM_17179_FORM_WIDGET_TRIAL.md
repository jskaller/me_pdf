# MM-17179 Form-Widget Structure Trial (H10/H10A)

## Why H10A exists after H10

H9 proved a controlled, fixture-scoped structure-construction capability for `PDF/UA-1/7.18.4` on a synthetic, non-private AcroForm fixture. H10 moved that capability to a guarded MM-17179 dry-run path without silently enabling production behavior.

H10A continues the guarded MM-17179 trial by fixing the concrete evidence-bound issue that stopped H10. H10A is not production activation. It keeps the repair isolated, guarded, non-default, and non-production.

The system goal remains a production-ready remediation workflow, not a one-off PDF fix.

## H10 runtime blocker

After the H10 repository patch, the Docker/runtime MM-17179 dry-run found and inspected:

```text
/app/workspace/input/MM-17179/ROI4987_English_1-26_rev_Fillable.pdf
```

The H10 runtime evidence showed:

```text
AcroForm present: true
AcroForm field count: 24
Widget annotation count: 102
Widgets missing /StructParent: 102
Widgets with /StructParent: 0
/StructTreeRoot present: false
/ParentTree present: false
Form structure element count: 0
Planned StructParent assignments: 102
Planned Form structure elements: 102
Planned ParentTree entries: 102
```

H10 correctly refused to apply because the diagnostic report was bounded at 100 widgets while MM-17179 contains 102 widgets:

```text
widget_annotation_count: 102
widgets_bounded_count: 100
widgets_truncated: true
```

The old blocker wording was confusing:

```text
widget evidence is not truncated
```

H10A corrects this to:

```text
widget evidence is truncated
```

and records the positive precondition as:

```text
widget evidence is complete
```

## H10A implementation summary

Changed files:

```text
app/tools/audit/form_widget_structure_inspection.py
app/tools/repair/repair_form_widget_structure.py
app/tools/tests/test_form_widget_structure_inspection_policy.py
app/tools/tests/test_form_widget_structure_repair_policy.py
docs/MM_17179_FORM_WIDGET_TRIAL.md
```

H10A does not modify:

```text
app/tools/audit/rule_repair_map.json
app/tools/orchestrate/remediate.py
app/tools/packaging/status_json_writer.py
app/tools/packaging/package_deliverables.py
```

## Widget evidence bound behavior

The diagnostic keeps the default bound of 100 widget records for normal bounded reports. H10A adds explicit completeness fields and passes the requested bound through the repair dry-run/apply path.

Diagnostic evidence now includes:

```text
widgets_bounded_count
bounded_widget_records_count
widgets_truncated
widget_evidence_complete
max_widgets_requested
```

Repair reports now include top-level:

```text
max_widgets
widget_annotation_count
widgets_bounded_count
widgets_truncated
widget_evidence_complete
terminal_state
```

The dry-run completeness precondition passes only when:

```text
widgets_truncated: false
bounded_widget_records_count == widget_annotation_count
widget_evidence_complete: true
```

If evidence is still truncated, repair dry-run ends as:

```text
MM17179_DRY_RUN_BLOCKED
```

and no apply is attempted.

## Required H10A dry-run command

Run in the Docker/Hermes runtime that has the private MM-17179 source PDF:

```bash
docker compose exec -T hermes bash -lc '
cd /app &&
PYTHONPATH=/app /usr/bin/python3 /app/tools/repair/repair_form_widget_structure.py \
  --input /app/workspace/input/MM-17179/ROI4987_English_1-26_rev_Fillable.pdf \
  --dry-run-report /tmp/h10a-mm17179-form-widget-dry-run.json \
  --max-widgets 1000
'
```

Expected resolution of the H10 evidence-bound issue:

```text
widget_annotation_count: 102
widgets_bounded_count: 102
bounded_widget_records_count: 102
widgets_truncated: false
widget_evidence_complete: true
```

If the dry-run reports `apply_allowed: false`, do not apply. Report the blocker and keep terminal state:

```text
MM17179_DRY_RUN_BLOCKED
```

## Required isolated apply if dry-run passes

If dry-run reports `apply_allowed: true`, run isolated apply to `/tmp` only:

```bash
docker compose exec -T hermes bash -lc '
cd /app &&
rm -rf /tmp/h10a-mm17179-form-widget-trial &&
mkdir -p /tmp/h10a-mm17179-form-widget-trial &&
PYTHONPATH=/app /usr/bin/python3 /app/tools/repair/repair_form_widget_structure.py \
  --input /app/workspace/input/MM-17179/ROI4987_English_1-26_rev_Fillable.pdf \
  --output /tmp/h10a-mm17179-form-widget-trial/output.pdf \
  --dry-run-report /tmp/h10a-mm17179-form-widget-trial/apply-report.json \
  --apply \
  --allow-structure-construction-trial \
  --max-widgets 1000
'
```

The apply path must not:

```text
overwrite source PDF
write under workspace/output
write under workspace/jobs
write STATUS.json
write orchestrator_outcome.json
update rule_map
activate production behavior
claim production readiness
dump field values
```

## Required before/after diagnostics

Before:

```bash
docker compose exec -T hermes bash -lc '
cd /app &&
PYTHONPATH=/app /usr/bin/python3 /app/tools/audit/form_widget_structure_inspection.py \
  /app/workspace/input/MM-17179/ROI4987_English_1-26_rev_Fillable.pdf \
  --job-dir /app/workspace/jobs/MM-17179_ROI4987_English_1-26_rev_Fillable \
  --out /tmp/h10a-mm17179-before-inspection.json \
  --max-widgets 1000
'
```

After, only if output exists:

```bash
docker compose exec -T hermes bash -lc '
cd /app &&
test -f /tmp/h10a-mm17179-form-widget-trial/output.pdf &&
PYTHONPATH=/app /usr/bin/python3 /app/tools/audit/form_widget_structure_inspection.py \
  /tmp/h10a-mm17179-form-widget-trial/output.pdf \
  --out /tmp/h10a-mm17179-after-inspection.json \
  --max-widgets 1000
'
```

After diagnostics must prove:

```text
widget annotation count preserved
widgets with /StructParent increased to 102
widgets missing /StructParent reduced to 0
/StructTreeRoot present
/ParentTree present
/Form structure elements created
widgets with ParentTree mapping increased to 102
widgets already nested in Form increased to 102
field values redacted
```

If any of these fail, H10A terminal state is:

```text
MM17179_REPAIR_ATTEMPTED_NOT_ADOPTED
```

## qpdf result

If output exists, run:

```bash
docker compose exec -T hermes bash -lc '
test -f /tmp/h10a-mm17179-form-widget-trial/output.pdf &&
qpdf --check /tmp/h10a-mm17179-form-widget-trial/output.pdf
'
```

If qpdf fails, H10A terminal state is:

```text
MM17179_REPAIR_ATTEMPTED_NOT_ADOPTED
```

If qpdf is unavailable, report:

```text
qpdf: NOT_RUN_ENVIRONMENT_LIMITED
```

and do not claim qpdf pass.

## veraPDF result

If veraPDF is available, run before/after:

```bash
docker compose exec -T hermes bash -lc '
if command -v verapdf >/dev/null 2>&1; then
  verapdf --format json /app/workspace/input/MM-17179/ROI4987_English_1-26_rev_Fillable.pdf > /tmp/h10a-mm17179-verapdf-before.json || true
  verapdf --format json /tmp/h10a-mm17179-form-widget-trial/output.pdf > /tmp/h10a-mm17179-verapdf-after.json || true
else
  echo "veraPDF: NOT_RUN_ENVIRONMENT_LIMITED"
fi
'
```

If veraPDF runs, report whether `PDF/UA-1/7.18.4` improved, cleared, remained unchanged, or introduced regressions. Do not fake improvement.

If veraPDF is unavailable, report:

```text
veraPDF: NOT_RUN_ENVIRONMENT_LIMITED
```

## Preservation summary

The repair report checks:

```text
page count preserved
page MediaBox/CropBox preserved
AcroForm field count preserved
field names preserved
field types preserved
field value presence preserved
widget annotation count preserved
widget page annotation membership preserved
semantic widget identity preserved
exact object identity not claimed
field values not dumped unredacted
```

Any failed preservation check means:

```text
MM17179_REPAIR_ATTEMPTED_NOT_ADOPTED
```

## Rule-map adoption

Rule-map adoption was not performed by this repository patch. H10A only prepares and guards the complete-evidence trial path.

Do not update `app/tools/audit/rule_repair_map.json` unless all are true in the local Docker/MM-17179 runtime:

```text
dry-run passed with complete widget evidence
isolated apply passed
qpdf passed
before/after object diagnostics prove expected structure construction
preservation checks passed
veraPDF either proves PDF/UA-1/7.18.4 improved/cleared or is explicitly unavailable and adoption is marked non-default/experimental
repair remains guarded by preconditions
orchestrator default behavior is not silently activated
tests pass
```

If any gate fails or veraPDF is unavailable, prefer no rule-map adoption.

## Orchestrator, packaging, and status behavior

H10A intentionally does not modify:

```text
app/tools/orchestrate/remediate.py
app/tools/packaging/status_json_writer.py
app/tools/packaging/package_deliverables.py
```

No production default behavior is enabled. No deliverable-package or terminal-state authority is changed.

## H10A terminal state

For the repository patch alone, H10A is ready for the local Docker/private-PDF trial. The local runtime must determine the final MM-17179 terminal state as one of:

```text
MM17179_REPAIR_VALIDATED
MM17179_REPAIR_ATTEMPTED_NOT_ADOPTED
MM17179_DRY_RUN_BLOCKED
```

The repository-side patch does not claim production readiness.

## Production-readiness statement

H10A does not claim production readiness. It fixes the complete-widget-evidence path needed to continue a guarded isolated MM-17179 trial and keeps production activation, rule-map adoption, orchestrator integration, and package/status behavior unchanged.
