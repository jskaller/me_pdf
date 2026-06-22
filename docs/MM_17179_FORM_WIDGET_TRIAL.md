# MM-17179 Form-Widget Structure Trial (H10)

## Why H10 exists after H9

H9 proved a controlled, fixture-scoped structure-construction capability for `PDF/UA-1/7.18.4` on a synthetic, non-private AcroForm fixture. H10 exists to move that capability toward production operation without silently enabling production behavior.

The system goal remains a production-ready remediation workflow, not a one-off PDF fix. H10 therefore keeps the repair isolated, guarded, and non-default while preparing the MM-17179 trial path.

## H9 fixture capability summary

H9 demonstrated that the repair tool can:

- generate a synthetic fixture with AcroForm widgets lacking `/StructParent`;
- create `/StructTreeRoot`;
- create `/ParentTree`;
- assign stable `/StructParent` values to widgets;
- create `/Form` structure elements;
- map widgets through ParentTree;
- preserve AcroForm field count, names, types, and value-presence indicators;
- preserve widget count and page membership;
- preserve page count and page boxes;
- avoid dumping field values in diagnostics.

H9 did not apply the repair to MM-17179, update `rule_repair_map.json`, activate production default behavior, or modify orchestrator/packaging/status authority.

## H10 implementation summary

H10 updates `app/tools/repair/repair_form_widget_structure.py` so that:

- non-fixture dry-run is allowed and remains non-mutating;
- dry-run emits preconditions, blockers, planned structure construction, and before-object evidence;
- non-fixture apply is refused unless `--allow-structure-construction-trial` is explicitly supplied;
- apply still requires an explicit output PDF path;
- source overwrite is refused;
- workspace job/final package/status output paths are refused for trial apply;
- rule-map mutation, workspace artifact mutation, production-readiness claims, and production default activation remain false;
- H10 terminal states are represented as `MM17179_DRY_RUN_BLOCKED`, `MM17179_REPAIR_ATTEMPTED_NOT_ADOPTED`, or `MM17179_REPAIR_VALIDATED` when the guarded trial path runs.

## MM-17179 dry-run result

This repository-side H10 patch did not include or commit the private MM-17179 source PDF or workspace artifacts. In the execution environment used for this patch, the Docker/runtime path below was not available for validation:

```text
/app/workspace/input/MM-17179/ROI4987_English_1-26_rev_Fillable.pdf
```

Because local MM-17179 evidence was unavailable in this execution environment, no private evidence was faked. The required runtime terminal state for this execution is:

```text
MM17179_DRY_RUN_BLOCKED
```

Reason:

```text
LOCAL_EVIDENCE_MISSING
```

## Isolated apply result

Isolated apply was not attempted in this execution environment because the source PDF evidence was not available. H10 policy requires dry-run first and forbids apply when dry-run/local evidence is unavailable.

When the runtime evidence exists, the intended isolated apply command remains:

```bash
cd /app &&
mkdir -p /tmp/h10-mm17179-form-widget-trial &&
PYTHONPATH=/app /usr/bin/python3 /app/tools/repair/repair_form_widget_structure.py \
  --input /app/workspace/input/MM-17179/ROI4987_English_1-26_rev_Fillable.pdf \
  --output /tmp/h10-mm17179-form-widget-trial/output.pdf \
  --dry-run-report /tmp/h10-mm17179-form-widget-trial/apply-report.json \
  --apply \
  --allow-structure-construction-trial
```

## Before/after diagnostic summary

Before/after diagnostics were not run on MM-17179 in this execution environment because the private source PDF and job directory were unavailable. The tool and tests now preserve the required before/after fields for runtime validation.

Expected runtime commands:

```bash
cd /app &&
PYTHONPATH=/app /usr/bin/python3 /app/tools/audit/form_widget_structure_inspection.py \
  /app/workspace/input/MM-17179/ROI4987_English_1-26_rev_Fillable.pdf \
  --job-dir /app/workspace/jobs/MM-17179_ROI4987_English_1-26_rev_Fillable \
  --out /tmp/h10-mm17179-before-inspection.json
```

```bash
cd /app &&
test -f /tmp/h10-mm17179-form-widget-trial/output.pdf &&
PYTHONPATH=/app /usr/bin/python3 /app/tools/audit/form_widget_structure_inspection.py \
  /tmp/h10-mm17179-form-widget-trial/output.pdf \
  --out /tmp/h10-mm17179-after-inspection.json
```

## qpdf result

`qpdf` was not run against an MM-17179 trial output because no output PDF was produced in this execution environment.

## veraPDF result

`veraPDF` was not run against MM-17179 in this execution environment. Runtime validation must report either actual before/after veraPDF results or:

```text
veraPDF: NOT_RUN_ENVIRONMENT_LIMITED
```

## Preservation summary

The repair report continues to check:

- page count preservation;
- page MediaBox/CropBox preservation;
- AcroForm field count preservation;
- field names preservation;
- field types preservation;
- field value-presence preservation;
- widget annotation count preservation;
- widget page annotation membership preservation;
- semantic widget identity preservation;
- field values not dumped unredacted.

If preservation fails after isolated apply, the terminal state must be:

```text
MM17179_REPAIR_ATTEMPTED_NOT_ADOPTED
```

## Rule-map adoption

Rule-map adoption was not performed in H10. `app/tools/audit/rule_repair_map.json` was intentionally unchanged because the private MM-17179 dry-run/apply/qpdf/veraPDF gates were not completed in this execution environment.

## Orchestrator, packaging, and status behavior

H10 intentionally did not modify:

- `app/tools/orchestrate/remediate.py`;
- `app/tools/packaging/status_json_writer.py`;
- `app/tools/packaging/package_deliverables.py`.

No production default behavior was enabled. No deliverable-package or terminal-state authority was changed.

## H10 terminal state

```text
MM17179_DRY_RUN_BLOCKED
```

Reason:

```text
LOCAL_EVIDENCE_MISSING
```

## Production-readiness statement

H10 does not claim production readiness. It adds guarded non-fixture dry-run and explicit trial-apply controls so MM-17179 can be tested truthfully in the Docker/runtime environment where the private source PDF and job artifacts exist.
