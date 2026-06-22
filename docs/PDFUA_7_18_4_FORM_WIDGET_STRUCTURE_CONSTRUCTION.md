# PDF/UA-1/7.18.4 Form-Widget Structure Construction

Patch: H9 - Controlled Form-Widget Structure Construction Capability

Baseline: `8f20f6f`

## Why H9 Exists

H8 proved that MM-17179 contains real AcroForm/widget evidence but lacks the tagged-PDF substrate required for a narrow repair:

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

That evidence means the next production-readiness step cannot be another standalone diagnostic and cannot safely apply directly to MM-17179. The system needs a controlled, synthetic, non-private fixture that models this blocker shape and proves whether a structure-construction capability is viable.

H9 therefore adds a guarded fixture-scoped capability for PDF/UA-1/7.18.4-style form-widget structure construction.

## Fixture Shape

H9 adds:

```text
app/tools/dev/generate_form_widget_structure_fixture.py
```

The generator creates a small synthetic PDF with:

```text
one or more AcroForm text fields
one widget annotation per field
page /Annots membership
synthetic field names and synthetic values only
widgets initially lacking /StructParent
no /StructTreeRoot
no /ParentTree
no /Form structure elements
```

The fixture is generated during tests or manual runs. H9 does not require committing generated PDFs.

Example command:

```bash
PYTHONPATH=app python3 app/tools/dev/generate_form_widget_structure_fixture.py \
  --out /tmp/h9-form-widget-fixture/input.pdf \
  --report /tmp/h9-form-widget-fixture/generation.json
```

## Guarded Repair Tool

H9 adds:

```text
app/tools/repair/repair_form_widget_structure.py
```

The tool is explicitly guarded:

```text
fixture-mode apply path: supported
non-fixture mode: refused
source overwrite: refused
rule-map mutation: never performed
workspace artifact mutation: never performed
production readiness claim: never made
```

Dry-run command:

```bash
PYTHONPATH=app python3 app/tools/repair/repair_form_widget_structure.py \
  --input /tmp/h9-form-widget-fixture/input.pdf \
  --dry-run-report /tmp/h9-form-widget-fixture/dry-run.json \
  --fixture-mode
```

Apply command:

```bash
PYTHONPATH=app python3 app/tools/repair/repair_form_widget_structure.py \
  --input /tmp/h9-form-widget-fixture/input.pdf \
  --output /tmp/h9-form-widget-fixture/output.pdf \
  --dry-run-report /tmp/h9-form-widget-fixture/apply-report.json \
  --apply \
  --fixture-mode
```

The apply mode writes only to the explicit output path and refuses to overwrite the source PDF.

## Implemented Algorithm

For controlled fixtures, the repair tool:

1. opens the PDF with pikepdf;
2. enumerates page widget annotations from page `/Annots`;
3. preserves AcroForm fields, field names, field types, field value presence, widget relationships, page membership, page count, and page boxes;
4. creates `/StructTreeRoot` when missing;
5. creates `/ParentTree` when missing;
6. assigns stable integer `/StructParent` values to widgets that lack them;
7. creates one `/Form` structure element per widget;
8. links each `/Form` element to its widget annotation through an `/OBJR` object reference;
9. appends each `/Form` element to the structure root `/K` array;
10. maps each widget `/StructParent` key through the `/ParentTree /Nums` array;
11. writes a new output PDF only;
12. emits a bounded JSON report with before/after diagnostics, planned changes, preservation checks, qpdf result when available, and an adoption decision.

## Report Fields

The repair report includes:

```text
schema
version
created_at
result
mode
fixture_mode
input_pdf
output_pdf
target_rule
read_only
repair_performed
rule_map_mutation_performed
workspace_artifacts_mutated
safe_to_claim_production_ready
before
planned_changes
after
preservation
validation
decision
```

The report does not dump field values. It records field-value presence and value type only through the existing form-widget diagnostic.

## Validation and Preservation

The repair tool runs the existing H7/H8 diagnostic before apply and after apply. After a successful fixture apply, the after diagnostic should prove:

```text
widget annotation count preserved
widgets missing /StructParent reduced to 0
widgets with /StructParent increased to expected count
/StructTreeRoot present
/ParentTree present
/Form structure element count increased
widgets with ParentTree mapping increased to expected count
widgets already nested in Form increased to expected count
```

The preservation summary checks:

```text
field count preserved
field names preserved
field types preserved
field value presence preserved
widget count preserved
widget page membership preserved
page count preserved
page boxes preserved
field values not dumped
```

The tool also attempts:

```text
qpdf --check output.pdf
```

If qpdf is unavailable, the report records:

```text
NOT_RUN_ENVIRONMENT_LIMITED
```

veraPDF is not run by the tool itself in H9. Manual H9 validation may run veraPDF if available. If unavailable, record:

```text
veraPDF: NOT_RUN_ENVIRONMENT_LIMITED
```

## Production Guardrails

H9 does not integrate this repair into production orchestration.

The following files are intentionally not changed by H9 unless a later adoption gate justifies it:

```text
app/tools/audit/rule_repair_map.json
app/tools/orchestrate/remediate.py
app/tools/packaging/
```

The repair remains isolated and guarded. It does not silently run for production PDFs.

For MM-17179 or other non-fixture inputs, the H9 tool refuses with a blocker such as:

```text
non-fixture mode is not enabled for H9 structure construction
```

This is intentional. MM-17179 is private production evidence and should not be mutated by H9 unless a later explicit production trial patch authorizes it with stronger gates.

## Rule-Map Adoption

H9 does not require rule-map adoption. Rule-map adoption is allowed only if all gates pass:

```text
controlled fixture repair implemented
controlled fixture qpdf passes
controlled fixture after diagnostic proves widgets are mapped to /Form
preservation checks pass
veraPDF either passes/improves for the target rule or is truthfully marked unavailable
unit tests pass
repair remains guarded and does not silently activate unsafe production behavior
```

If any condition is not satisfied, do not modify `app/tools/audit/rule_repair_map.json`.

## Expected Terminal States

H9 uses these terminal states:

```text
IMPLEMENTED_AND_VALIDATED_ON_FIXTURE
IMPLEMENTED_BUT_BLOCKED_FOR_PRODUCTION
BLOCKED_BEFORE_IMPLEMENTATION
```

Meanings:

```text
IMPLEMENTED_AND_VALIDATED_ON_FIXTURE:
  fixture repair ran, after-object evidence passed, preservation passed, and qpdf passed.
  Production default activation remains false.

IMPLEMENTED_BUT_BLOCKED_FOR_PRODUCTION:
  fixture repair was implemented or attempted, but one or more gates failed or were unavailable.
  Keep the repair guarded and do not adopt as production-ready.

BLOCKED_BEFORE_IMPLEMENTATION:
  input could not be inspected, non-fixture mode was requested, apply lacked an explicit output path,
  or another pre-implementation safety guard blocked mutation.
```

## Required Commands

```bash
python3 -m py_compile \
  app/tools/dev/generate_form_widget_structure_fixture.py \
  app/tools/repair/repair_form_widget_structure.py \
  app/tools/audit/form_widget_structure_inspection.py

PYTHONPATH=app python3 -m unittest \
  app/tools/tests/test_form_widget_structure_inspection_policy.py \
  app/tools/tests/test_form_widget_structure_repair_policy.py \
  app/tools/tests/test_mm17179_blocker_inspection_policy.py \
  app/tools/tests/test_production_readiness_matrix_policy.py
```

Manual fixture capability run:

```bash
rm -rf /tmp/h9-form-widget-fixture
mkdir -p /tmp/h9-form-widget-fixture

PYTHONPATH=app python3 app/tools/dev/generate_form_widget_structure_fixture.py \
  --out /tmp/h9-form-widget-fixture/input.pdf \
  --report /tmp/h9-form-widget-fixture/generation.json

PYTHONPATH=app python3 app/tools/audit/form_widget_structure_inspection.py \
  /tmp/h9-form-widget-fixture/input.pdf \
  --out /tmp/h9-form-widget-fixture/before-inspection.json

PYTHONPATH=app python3 app/tools/repair/repair_form_widget_structure.py \
  --input /tmp/h9-form-widget-fixture/input.pdf \
  --dry-run-report /tmp/h9-form-widget-fixture/dry-run.json \
  --fixture-mode

test ! -f /tmp/h9-form-widget-fixture/output.pdf

PYTHONPATH=app python3 app/tools/repair/repair_form_widget_structure.py \
  --input /tmp/h9-form-widget-fixture/input.pdf \
  --output /tmp/h9-form-widget-fixture/output.pdf \
  --dry-run-report /tmp/h9-form-widget-fixture/apply-report.json \
  --apply \
  --fixture-mode

test -f /tmp/h9-form-widget-fixture/output.pdf
qpdf --check /tmp/h9-form-widget-fixture/output.pdf

PYTHONPATH=app python3 app/tools/audit/form_widget_structure_inspection.py \
  /tmp/h9-form-widget-fixture/output.pdf \
  --out /tmp/h9-form-widget-fixture/after-inspection.json
```

Optional MM-17179 dry-run only:

```bash
PYTHONPATH=app python3 app/tools/repair/repair_form_widget_structure.py \
  --input workspace/input/MM-17179/ROI4987_English_1-26_rev_Fillable.pdf \
  --dry-run-report /tmp/h9-mm17179-form-widget-dry-run.json
```

Expected H9 result for non-fixture MM-17179 dry-run is a truthful block, not repair.

## Production Readiness Statement

H9 does not claim production readiness. It adds a controlled, fixture-scoped construction capability and a validation framework for future guarded adoption. Production integration, rule-map activation, and MM-17179 apply remain future gated work.
