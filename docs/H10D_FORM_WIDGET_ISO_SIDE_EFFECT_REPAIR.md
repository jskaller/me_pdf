# H10D Form-Widget ISO Side-Effect Repair

## Terminal state

```text
PENDING_RUNTIME_VALIDATION
```

H10D terminal state must be finalized after the Hermes runtime validation pass as exactly one of:

```text
ISO_SIDE_EFFECT_FIXED_TARGET_RULE_STILL_CLEARS
ISO_SIDE_EFFECT_PARTIALLY_FIXED_ADOPTION_BLOCKED
ISO_SIDE_EFFECT_NOT_FIXED_REPAIR_BLOCKED
ISO_SIDE_EFFECT_FIX_UNSAFE
```

## Scope

H10D attempts a focused repair adjustment for the H10C ISO tagged-profile structural side effect introduced by the form-widget structure-construction trial.

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
Moving the key to the correct structure root location and sorting /Nums is the smallest safe structure-tree correction before considering broader repair changes.
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

## Rule-map status

H10D does not change:

```text
app/tools/audit/rule_repair_map.json
```

No guarded metadata is adopted in H10D.

No active executable strategy is added.

`PDF/UA-1/7.18.4` remains non-runtime-active unless a later patch explicitly implements guarded runtime integration.

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

H10D must not commit private PDFs, generated PDFs, workspace artifacts, validator XML outputs, parsed-failure JSON, profile-accounting JSON, delta JSON, or ISO review JSON.

## Required runtime validation

Run the H10D Hermes runtime validation against MM-17179 using `/tmp` output only.

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
No private/generated/workspace artifacts are committed.
```

## Pending decision

If runtime validation proves the ISO side effect is fixed while `PDF/UA-1/7.18.4` still clears, finalize H10D as:

```text
ISO_SIDE_EFFECT_FIXED_TARGET_RULE_STILL_CLEARS
```

If the ISO side effect remains, finalize H10D as:

```text
ISO_SIDE_EFFECT_NOT_FIXED_REPAIR_BLOCKED
```

If the ISO evidence improves but remains unsafe or target-rule clearance becomes unstable, finalize H10D as:

```text
ISO_SIDE_EFFECT_PARTIALLY_FIXED_ADOPTION_BLOCKED
```

If runtime evidence shows that fixing this safely requires broad structural rewrite or unsafe object surgery, finalize H10D as:

```text
ISO_SIDE_EFFECT_FIX_UNSAFE
```
