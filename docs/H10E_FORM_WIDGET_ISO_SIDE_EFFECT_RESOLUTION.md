# H10E Form-Widget ISO Side-Effect Resolution

## Terminal state

```text
ISO_SIDE_EFFECT_FIXED_TARGET_RULE_STILL_CLEARS
```

## Baseline

```text
8cd7bbb
Document unresolved form-widget ISO side effect
```

## H10D blocker carried into H10E

H10D terminal state:

```text
ISO_SIDE_EFFECT_NOT_FIXED_REPAIR_BLOCKED
```

H10D proved the target rule still clears:

```text
PDF/UA-1/7.18.4 before: 204
PDF/UA-1/7.18.4 after: 0
```

H10D also proved the ISO side effect remains:

```text
ISO-32000-1-Tagged before: PASS
ISO-32000-1-Tagged after: FAIL
new ISO rule: ISO 19005-2:2011/Annex_L
classification: STRUCTURAL_SIDE_EFFECT
```

No metadata was adopted in H10D. No runtime activation was enabled.

## ISO failed-check evidence carried forward

H10D compact ISO review evidence:

```text
before_iso_result: PASS
after_iso_result: FAIL
new_iso_rule_ids: ['ISO 19005-2:2011/Annex_L']
increased_iso_rule_ids: []
new_or_increased_iso_checks: [{'after_failed_checks': 1, 'before_failed_checks': 0, 'delta': 1, 'rule_id': 'ISO 19005-2:2011/Annex_L'}]
correlation_to_form_widget_objects: True
correlation_to_struct_tree_root: True
correlation_to_parent_tree: True
correlation_to_objr: False
correlation_to_struct_parent: False
classification: STRUCTURAL_SIDE_EFFECT
blocks_metadata_adoption: True
blocks_runtime_activation: True
recommendation: New or increased ISO checks correlate with form-widget or structure-construction evidence.
```

## Repair change attempted in H10E

H10E changes only:

```text
app/tools/repair/repair_form_widget_structure.py
```

Focused H10E change:

```text
Create or reuse one top-level /Document StructElem under /StructTreeRoot /K.
Append generated /Form StructElem children under that /Document element.
Set each generated /Form /P to the /Document element instead of /StructTreeRoot.
Keep ParentTree entries mapped to the /Form StructElem objects for widget annotations.
Preserve H10D's /ParentTreeNextKey placement on /StructTreeRoot.
Preserve H10D's sorted /ParentTree /Nums behavior.
```

Reasoning:

```text
H10D fixed key placement and number-tree ordering but ISO Annex_L still failed.
The remaining likely hierarchy issue was direct /Form children under /StructTreeRoot.
H10E tested the smallest hierarchy change: add a /Document container while keeping annotation ParentTree mapping to /Form elements.
```

## Fixture coverage added or updated

H10E updates:

```text
app/tools/tests/test_form_widget_structure_repair_policy.py
```

The H10E fixture test proves:

```text
/StructTreeRoot /K is a /Document StructElem.
/Document /P points to /StructTreeRoot.
/Document /K contains generated /Form StructElem children.
Each generated /Form /P points to /Document.
Each generated /Form has /Pg.
Each generated /Form /K is an /OBJR.
Each /OBJR references a /Widget annotation.
ParentTree entries still map to /Form StructElem values.
```

Existing H10D fixture coverage still proves:

```text
/ParentTreeNextKey is on /StructTreeRoot, not /ParentTree.
/ParentTree /Nums keys are sorted.
/ParentTreeNextKey equals max(/Nums keys) + 1.
```

## Runtime validation result

H10E runtime validation was run against MM-17179 in Hermes, using `/tmp` output only.

Apply result:

```text
result: APPLIED
terminal_state: MM17179_REPAIR_VALIDATED
repair_performed: True
```

Mutation summary:

```text
assigned_struct_parent_count: 102
created_document_struct_element: True
created_form_struct_elements_count: 102
form_struct_parent_type: Document
parent_tree_entries_created: 102
parent_tree_next_key_location: StructTreeRoot
parent_tree_nums_sorted: True
top_level_structure_type: Document
```

Preservation summary:

```text
field_count_preserved: True
field_names_preserved: True
field_types_preserved: True
field_value_presence_preserved: True
field_values_not_dumped: True
page_boxes_preserved: True
page_count_preserved: True
semantic_widget_identity_preserved: True
widget_count_preserved: True
widget_page_membership_preserved: True
exact_object_identity_claimed: False
```

qpdf result:

```text
PASS
```

veraPDF profile result:

```text
before PDF/UA-1: FAIL
after PDF/UA-1: FAIL
before WCAG-2-2-Machine pinned: FAIL
after WCAG-2-2-Machine pinned: FAIL
before ISO-32000-1-Tagged: PASS
after ISO-32000-1-Tagged: PASS
```

Profile accounting result:

```text
schema: montefiore.verapdf_delta
terminal_state: VERAPDF_DELTA_VALIDATED
verdict_candidate: VALIDATED_FOR_ADOPTION_CONSIDERATION
target_rule: PDF/UA-1/7.18.4
target_rule_before_count: 204
target_rule_after_count: 0
target_rule_delta: -204
target_rule_status: CLEARED
total_failures_before: 3656
total_failures_after: 3450
pdfua1_profile_result_before: FAIL
pdfua1_profile_result_after: FAIL
wcag_profile_result_before: FAIL
wcag_profile_result_after: FAIL
iso_profile_result_before: PASS
iso_profile_result_after: PASS
new_rule_ids: []
increased_rule_ids: []
accounting_blockers: []
```

ISO regression review result:

```text
before_iso_result: PASS
after_iso_result: PASS
new_iso_rule_ids: []
increased_iso_rule_ids: []
new_or_increased_iso_checks: []
classification: BENIGN_INFORMATIONAL
blocks_metadata_adoption: False
blocks_runtime_activation: True
recommendation: ISO sidecars show no new or increased failed checks.
```

## Rule map and production path status

H10E does not change:

```text
app/tools/audit/rule_repair_map.json
app/tools/audit/lookup_repair_plan.py
app/tools/orchestrate/remediate.py
app/tools/packaging/status_json_writer.py
app/tools/packaging/package_deliverables.py
```

H10E does not adopt metadata.

H10E does not activate runtime repair.

H10E does not claim production readiness.

## H10E conclusion

H10E fixed the H10D ISO side effect while preserving target-rule clearance:

```text
PDF/UA-1/7.18.4: 204 -> 0
ISO-32000-1-Tagged: PASS -> PASS
```

The correct H10E terminal state is:

```text
ISO_SIDE_EFFECT_FIXED_TARGET_RULE_STILL_CLEARS
```

## Required next action

The next patch may proceed to guarded non-runtime metadata adoption for `PDF/UA-1/7.18.4`, followed immediately by guarded runtime integration only after the metadata gate is proven safe.

Production readiness is still not claimed until the full WebUI `PDF:` production path through Hermes, orchestrator, validation, status, and deliverables is proven.
