# PDF/UA-1/7.18.4 Form-Widget Repair Design Evidence

Patch: H7 - PDF/UA-1/7.18.4 Form-Widget Repair Design Evidence

Baseline: `f71e6b7 Update H6 blocker selection with matrix evidence`

## Scope

H7 adds read-only diagnostic and design evidence for the `PDF/UA-1/7.18.4` blocker family:

```text
Widget annotation not nested within a Form tag in the structure tree
```

H7 is design-first. It collects object-level evidence needed to decide whether a later deterministic repair can be designed safely.

## Non-scope

H7 does not:

- implement a `PDF/UA-1/7.18.4` repair;
- mutate `app/tools/repair/`;
- mutate `app/tools/audit/rule_repair_map.json`;
- change orchestrator behavior;
- change packaging/status behavior;
- adopt a final PDF;
- weaken validators;
- commit private PDFs, workspace artifacts, generated PDFs, or validator outputs;
- claim production readiness.

## Why H7 is design-first

A form-widget nesting repair touches interactive form annotations and the logical structure tree. A safe future repair must preserve field behavior, annotation identity, page membership, field values, tab order, page boxes, rendering, and validator semantics. Rule IDs alone are not enough evidence to synthesize `/Form` structure edits.

H7 therefore records whether the PDF exposes the object model needed for a future implementation, while keeping `repair_implementation_safe_now=false`.

## H6 evidence summary

H6 selected `PDF/UA-1/7.18.4` as the recommended H7 design target because:

- it is a `P1_single_production_blocker` on the representative production escalation row `MM-17179_ROI4987_English_1-26_rev_Fillable`;
- it has `T1_active_hermes_required` evidence;
- it is supported by `active_hermes_required_signals` and `residual_targetable_rules`;
- the active signal reports 204 failures for widget annotations not nested within a `/Form` structure element;
- it is not a P0 systemic blocker because recurrence across multiple production rows was not shown.

## Object model background

### Widget annotations

Widget annotations are annotation dictionaries with `/Subtype /Widget`. They represent the page-visible interactive components of form fields. A single AcroForm field can have one or more widget annotations, and a widget normally appears in a page `/Annots` array.

### AcroForm fields

The document catalog may contain `/AcroForm`, whose `/Fields` array stores form field dictionaries. Field dictionaries can have `/T` field names, `/FT` field types, `/V` values, and `/Kids` pointing to widgets or child field nodes. H7 diagnostics report value presence and value type, not sensitive field values.

### `/StructParent`

A widget annotation can have a `/StructParent` integer. That integer is the bridge from the annotation object into the logical structure tree through the `/ParentTree` number tree. Without stable `/StructParent` evidence, a structure-tree repair is unsafe.

### `/StructTreeRoot`

The document catalog's `/StructTreeRoot` is the root of tagged PDF logical structure. If it is missing, H7 must block implementation because there is no reliable target structure tree to extend.

### `/ParentTree`

The `/ParentTree` under `/StructTreeRoot` maps structure parent keys to structure elements or marked-content references. A future repair may need to read or update this tree. H7 reports whether `/Nums` or `/Kids` are present, whether entries are countable, and whether widget `/StructParent` values map through the tree.

### `/Form` structure elements

A `/Form` structure element is the expected logical tag family for form widgets. A widget may already map to a `/Form` element, map to a non-Form element, or fail to map at all. H7 reports existing `/Form` element count and bounded object identifiers.

## H7 diagnostic

H7 adds:

```text
app/tools/audit/form_widget_structure_inspection.py
```

The diagnostic is read-only and emits:

```text
schema
version
created_at
result
target_rule
pdf_path
job_dir
read_only: true
repair_performed: false
rule_map_mutation_performed: false
workspace_artifacts_mutated: false
safe_to_claim_production_ready: false
pdf_object_evidence
decision
```

The object evidence includes:

```text
page_count
page_boxes
acroform_present
acroform_field_count
acroform_fields
struct_tree_root_present
parent_tree_present
parent_tree_type
parent_tree_has_nums
parent_tree_has_kids
parent_tree_entry_count
parent_tree_next_key
struct_element_count
form_struct_element_count
widget_annotation_count
widgets_missing_struct_parent_count
widgets_with_struct_parent_count
widgets_with_parent_tree_mapping_count
widgets_without_parent_tree_mapping_count
widgets_already_nested_in_form_count
widgets_referenced_from_non_form_count
adding_form_elements_would_require_parent_tree_mutation
adding_form_elements_would_require_k_array_mutation
sensitive_field_values_redacted
```

For each widget, the diagnostic reports a bounded list, defaulting to the first 100 widgets:

```text
page_index
annotation_objgen
field_name
field_type
field_value_present
field_value_type
rect
struct_parent
parent_tree_mapping_present
mapped_struct_element_type
mapped_struct_element_objgen
mapped_struct_ancestor_types
already_nested_in_form
referenced_from_form_element
referenced_from_non_form_element
parent_field_objgen
page_annotation_membership
```

It does not dump private field values.

## Decision output

The diagnostic emits:

```text
decision:
  chosen_option: A | B | C
  repair_implementation_safe_now: false
  design_ready_for_future_patch: true | false
  reason: ...
  blockers: [...]
  required_next_evidence: [...]
```

Meanings:

- Option A: object-level evidence suggests a deterministic repair may be designable in a later patch. H7 still does not implement it.
- Option B: partial evidence exists, but more diagnostics or a controlled fixture are required.
- Option C: evidence is insufficient or unsafe; keep escalation.

`repair_implementation_safe_now` remains `false` for all options in H7.

## Required safety preconditions for future repair

A future implementation patch must prove all of the following before mutating a PDF:

1. Widget annotations are present and countable.
2. Widget annotations have stable `/StructParent` values, or a deterministic and validator-supported assignment plan exists.
3. `/StructTreeRoot` exists.
4. `/ParentTree` exists, is readable, and can be updated safely if needed.
5. Each widget's `/StructParent` maps to an expected structure-tree target or a safe new target can be created.
6. Existing `/Form` structure elements are present, or safe insertion points are proven.
7. Existing structure children can be preserved.
8. AcroForm field objects, field names, field types, field value presence, widget relationships, and page annotation membership can be preserved.
9. Annotation object identity can be preserved.
10. Page count, page boxes, rendering, and field behavior can be preserved.

## Proposed future repair algorithm - not implemented in H7

A later H8-style implementation, if authorized, should be guarded and dry-run first:

1. Open the PDF with an object-preserving library such as pikepdf.
2. Enumerate page widget annotations from page `/Annots` arrays.
3. For each widget, record annotation object id, page index, `/StructParent`, field relationship, and field value presence.
4. Read `/StructTreeRoot` and `/ParentTree`.
5. Resolve each widget `/StructParent` through the ParentTree.
6. Determine whether the mapped structure element is already `/Form`, has a `/Form` ancestor, or is incorrectly mapped to a non-Form element.
7. For widgets lacking `/Form` structure, create or identify a safe `/Form` structure element without disrupting existing structure children.
8. Update only the minimal necessary `/K` arrays and ParentTree entries.
9. Preserve AcroForm field dictionaries, widget annotation dictionaries, object identities, page `/Annots`, page boxes, and field values.
10. Write to a new output PDF only.
11. Run qpdf, veraPDF PDF/UA delta, form preservation checks, render/visual QA, residual analysis, STATUS/orchestrator consistency checks, and package-route validation.

This algorithm is design guidance only. H7 does not implement it.

## Required before/after validation for future implementation

A future implementation patch must collect:

- qpdf success;
- veraPDF PDF/UA before/after delta for `PDF/UA-1/7.18.4`;
- evidence that AcroForm fields and field value presence were preserved;
- evidence that widget annotation object identities were preserved;
- evidence that page count and page boxes were preserved;
- render comparison or visual QA;
- consistency between `STATUS.json` and `audit/orchestrator_outcome.json`;
- proof that no successful PDF deliverable is copied if outcome remains `FAIL` or `ESCALATION`.

External validators such as PAC or axesCheck must not be claimed unless actually run.

## Reasons future repair remains blocked

Keep escalation and do not implement repair if any of these are true:

- the PDF cannot be inspected;
- widget annotations are absent;
- widgets lack `/StructParent` values and no safe assignment plan exists;
- `/StructTreeRoot` is missing;
- `/ParentTree` is missing or unreadable;
- widget `/StructParent` values do not map through the ParentTree;
- existing structure relationships cannot be preserved;
- AcroForm field relationships or value presence cannot be preserved;
- annotation identity cannot be preserved;
- page boxes or visual rendering cannot be preserved;
- validator deltas cannot prove the targeted rule improved without introducing worse regressions.

## Pipeline non-regression

H7 diagnostics do not alter the orchestrator, repair scripts, packaging, status authority, or workspace behavior. The required post-patch local gate must still run the WebUI E2E smoke fixture generation, font inventory, direct orchestrator smoke, fixture-profile matrix inspection, and guardrail checks described in the H7 handoff.

Do not commit the generated fixture PDF, job artifacts, output packages, `/tmp` matrix outputs, or validator artifacts.

## Production readiness statement

H7 does not claim production readiness. It only adds read-only evidence collection and design guidance for a future guarded `PDF/UA-1/7.18.4` repair investigation.
