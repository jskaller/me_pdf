# H10D Form-Widget ISO Side-Effect Repair

## Terminal state

```text
ISO_SIDE_EFFECT_NOT_FIXED_REPAIR_BLOCKED
```

## Scope

H10D attempted a focused repair adjustment for the H10C ISO tagged-profile structural side effect introduced by the form-widget structure-construction trial.

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

H10D does not change that production path.

## H10C blocker being addressed

H10C found:

```text
before_iso_result: PASS
after_iso_result: FAIL
classification: STRUCTURAL_SIDE_EFFECT
blocks_metadata_adoption: true
blocks_runtime_activation: true
new ISO rule: ISO 19005-2:2011/Annex_L
```

H10C correlations:

```text
correlation_to_form_widget_objects: true
correlation_to_struct_tree_root: true
correlation_to_parent_tree: true
correlation_to_objr: false
correlation_to_struct_parent: false
```

## Repair change attempted

H10D changes only the form-widget structure construction logic in:

```text
app/tools/repair/repair_form_widget_structure.py
```

Focused changes:

```text
Move /ParentTreeNextKey placement from /ParentTree to /StructTreeRoot.
Remove any misplaced /ParentTreeNextKey from /ParentTree when constructing repaired output.
Sort /ParentTree /Nums integer/object pairs before saving.
Record mutation summary fields for parent_tree_next_key_location and parent_tree_nums_sorted.
```

Reasoning:

```text
/ParentTreeNextKey is a /StructTreeRoot key, not a key on the ParentTree number-tree dictionary.
The H10C ISO review correlated the regression with /StructTreeRoot and /ParentTree.
Moving the key to the correct structure root location and sorting /Nums was the smallest safe structure-tree correction to attempt before considering broader repair changes.
```

## Fixture coverage added

H10D updates:

```text
app/tools/tests/test_form_widget_structure_repair_policy.py
```

The new fixture test proves:

```text
/ParentTreeNextKey is not present on /ParentTree.
/ParentTreeNextKey is present on /StructTreeRoot.
/ParentTree /Nums keys are sorted.
/ParentTreeNextKey equals max(/Nums keys) + 1.
/ParentTree /Nums is made of integer/object pairs.
Each mapped value is a /StructElem.
Each mapped /StructElem has /S /Form.
Each mapped /StructElem has /P pointing to /StructTreeRoot.
Each mapped /StructElem has a /Pg reference.
Each mapped /StructElem has /K as an /OBJR.
Each /OBJR references a /Widget annotation.
```

Existing tests continue to cover:

```text
field count/name/type/value-presence preservation
widget count preservation
widget page-membership preservation
page count and page-box preservation
field values not dumped
source overwrite refusal
workspace job/final/status path refusal
non-fixture apply guard
lookup safety via rule-map policy tests
```

## Runtime validation result

H10D reran the isolated MM-17179 apply to `/tmp` only.

Repair apply result:

```text
repair_performed: true
terminal_state: MM17179_REPAIR_VALIDATED
assigned_struct_parent_count: 102
created_form_struct_elements_count: 102
parent_tree_entries_created: 102
parent_tree_next_key_location: StructTreeRoot
parent_tree_nums_sorted: true
rule_map_mutation_performed: false
workspace_artifacts_mutated: false
safe_to_claim_production_ready: false
```

qpdf result:

```text
PASS
```

Preservation summary:

```text
field_count_preserved: true
field_names_preserved: true
field_types_preserved: true
field_value_presence_preserved: true
field_values_not_dumped: true
page_boxes_preserved: true
page_count_preserved: true
semantic_widget_identity_preserved: true
widget_count_preserved: true
widget_page_membership_preserved: true
```

Profile accounting result:

```text
terminal_state: VERAPDF_DELTA_VALIDATED
verdict_candidate: VALIDATED_FOR_ADOPTION_CONSIDERATION
target_rule_before_count: 204
target_rule_after_count: 0
target_rule_status: CLEARED
pdfua1_profile_result_before: FAIL
pdfua1_profile_result_after: FAIL
wcag_profile_result_before: FAIL
wcag_profile_result_after: FAIL
iso_profile_result_before: PASS
iso_profile_result_after: FAIL
new_rule_ids: []
increased_rule_ids: []
accounting_blockers: []
```

ISO review result:

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

## H10D interpretation

H10D preserved the target-rule clearance:

```text
PDF/UA-1/7.18.4: 204 → 0
```

H10D did not introduce new or increased authoritative PDF/UA-1/WCAG rule IDs:

```text
new_rule_ids: []
increased_rule_ids: []
```

However, H10D did not fix the ISO tagged-profile side effect:

```text
ISO-32000-1-Tagged: PASS → FAIL
ISO classification: STRUCTURAL_SIDE_EFFECT
```

Therefore H10D remains blocked for metadata adoption and runtime activation.

## Rule-map status

H10D does not change:

```text
app/tools/audit/rule_repair_map.json
```

No guarded metadata is adopted in H10D.

No active executable strategy is added.

`PDF/UA-1/7.18.4` remains non-runtime-active unless a later patch explicitly implements guarded runtime integration after the ISO side effect is fixed or a different safe path is selected.

## Lookup status

H10D does not change:

```text
app/tools/audit/lookup_repair_plan.py
```

The lookup safety check must still prove that `lookup_repair_plan.py` does not emit:

```text
tools/repair/repair_form_widget_structure.py
```

## Production path status

H10D does not change:

```text
app/tools/orchestrate/remediate.py
app/tools/packaging/status_json_writer.py
app/tools/packaging/package_deliverables.py
```

H10D does not claim production readiness.

H10D does not activate runtime form-widget repair.

H10D does not commit private PDFs, generated PDFs, workspace artifacts, validator XML outputs, parsed-failure JSON, profile-accounting JSON, delta JSON, or ISO review JSON.

## Required next action

The next patch must continue repair adjustment or choose a different blocker-family path only if this form-widget repair path is proven unsafe.

The next form-widget repair investigation should focus on structure-tree construction beyond the H10D key-placement hygiene fix, especially:

```text
root /K structure shape and whether direct Form children are sufficient
whether a Document or other grouping StructElem is required
OBJR placement and /K shape under Form elements
ParentTree value shape for annotation StructParent entries
whether /StructParent or /StructParents handling needs a different object/page relationship
validator-specific details behind ISO 19005-2:2011/Annex_L
```

A future patch may only reconsider guarded metadata adoption after ISO no longer regresses or the side effect is otherwise proved benign under the project’s profile-accounting policy.
