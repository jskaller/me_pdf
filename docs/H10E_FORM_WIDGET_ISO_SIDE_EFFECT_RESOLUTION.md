# H10E Form-Widget ISO Side-Effect Resolution

## Terminal state

```text
PENDING_RUNTIME_VALIDATION
```

H10E must be finalized as exactly one of:

```text
ISO_SIDE_EFFECT_FIXED_TARGET_RULE_STILL_CLEARS
ISO_SIDE_EFFECT_PARTIALLY_FIXED_ADOPTION_BLOCKED
ISO_SIDE_EFFECT_NOT_FIXED_REPAIR_BLOCKED
ISO_SIDE_EFFECT_FIX_UNSAFE
FORM_WIDGET_REPAIR_PATH_REJECTED_WITH_EVIDENCE
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

H10E should extract more detailed ISO XML failed-check context during runtime validation if the regression remains.

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
The remaining likely hierarchy issue is direct /Form children under /StructTreeRoot.
H10E tests the smallest hierarchy change: add a /Document container while keeping annotation ParentTree mapping to /Form elements.
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

## Runtime validation required

Runtime validation must be run against MM-17179 in Hermes, using `/tmp` output only.

Success requires:

```text
qpdf passes.
Object diagnostics pass.
Preservation passes.
PDF/UA-1/7.18.4 remains cleared: before 204, after 0.
Required PDF/UA-1 and pinned WCAG profiles run and parse.
No new authoritative PDF/UA-1/WCAG regression appears.
ISO-32000-1-Tagged does not regress PASS → FAIL.
ISO regression review is BENIGN_INFORMATIONAL or no-regression equivalent.
lookup_repair_plan.py does not emit repair_form_widget_structure.py.
rule_repair_map.json is unchanged.
orchestrator is unchanged.
packaging/status is unchanged.
docs/PRODUCTION_REMEDIATION_STATUS.md is updated.
No private/generated/workspace artifacts are committed.
```

## Pending decision

If runtime validation proves the ISO side effect is fixed while `PDF/UA-1/7.18.4` still clears, finalize H10E as:

```text
ISO_SIDE_EFFECT_FIXED_TARGET_RULE_STILL_CLEARS
```

If the ISO side effect remains after the /Document hierarchy correction, finalize H10E as:

```text
ISO_SIDE_EFFECT_NOT_FIXED_REPAIR_BLOCKED
```

If the ISO evidence improves but still blocks adoption, finalize H10E as:

```text
ISO_SIDE_EFFECT_PARTIALLY_FIXED_ADOPTION_BLOCKED
```

If evidence shows a safe focused fix is not realistic, finalize H10E as:

```text
ISO_SIDE_EFFECT_FIX_UNSAFE
```

If evidence proves the form-widget repair approach is unsuitable for production adoption, finalize H10E as:

```text
FORM_WIDGET_REPAIR_PATH_REJECTED_WITH_EVIDENCE
```
