# Production Remediation Status

## Current production goal

Build a production-ready PDF remediation system that works through the intended production path:

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

## Current branch

```text
master
```

## H10E baseline commit

```text
8cd7bbb
Document unresolved form-widget ISO side effect
```

## Current final commit after H10E

```text
PENDING_RUNTIME_VALIDATION
```

Update this field when H10E is finalized.

## Last completed patch before H10E

```text
H10D — Repair Form-Widget Structure Construction ISO Side Effect
```

H10D terminal state:

```text
ISO_SIDE_EFFECT_NOT_FIXED_REPAIR_BLOCKED
```

## Current active blocker

The current active blocker remains the form-widget repair for:

```text
PDF/UA-1/7.18.4
```

The repair clears the target rule but introduces an ISO tagged-profile structural side effect.

## Current repair under investigation

```text
app/tools/repair/repair_form_widget_structure.py
```

H10D tried:

```text
/ParentTreeNextKey moved from /ParentTree to /StructTreeRoot.
/ParentTree /Nums integer/object pairs sorted before saving.
Misplaced /ParentTreeNextKey removed from /ParentTree.
```

H10E is testing whether generated /Form structure elements must sit under a top-level /Document StructElem instead of being attached directly under /StructTreeRoot.

## H10D target-rule status

```text
PDF/UA-1/7.18.4 before: 204
PDF/UA-1/7.18.4 after: 0
status: CLEARED
```

## H10D ISO side-effect status

```text
ISO-32000-1-Tagged before: PASS
ISO-32000-1-Tagged after: FAIL
new ISO rule: ISO 19005-2:2011/Annex_L
classification: STRUCTURAL_SIDE_EFFECT
```

H10D ISO correlations:

```text
correlation_to_form_widget_objects: true
correlation_to_struct_tree_root: true
correlation_to_parent_tree: true
correlation_to_objr: false
correlation_to_struct_parent: false
```

## Metadata adoption status

```text
rule_map metadata adopted: false
guarded metadata adopted: false
runtime activation enabled: false
```

## Production path evidence status

```text
WebUI production-path evidence collected: false
orchestrator end-to-end evidence collected: false
STATUS.json production truthfulness verified end-to-end: false
orchestrator_outcome.json production truthfulness verified end-to-end: false
deliverables package production evidence collected: false
```

## Files that must not be mutated by H10E

```text
app/tools/audit/rule_repair_map.json
app/tools/audit/lookup_repair_plan.py
app/tools/orchestrate/remediate.py
app/tools/packaging/status_json_writer.py
app/tools/packaging/package_deliverables.py
workspace/
private PDFs
generated PDFs
validator XML artifacts
parsed_failures.json
profile_accounting.json
h10e-verapdf-delta.json
iso-regression-review.json
```

## H10E allowed code focus

H10E may modify the guarded form-widget repair implementation and tests:

```text
app/tools/repair/repair_form_widget_structure.py
app/tools/tests/test_form_widget_structure_repair_policy.py
```

H10E may add or update documentation:

```text
docs/H10E_FORM_WIDGET_ISO_SIDE_EFFECT_RESOLUTION.md
docs/PRODUCTION_REMEDIATION_STATUS.md
```

## Remaining planned patches

If H10E fixes the ISO side effect while preserving target-rule clearance:

```text
H10F — Guarded non-runtime metadata adoption for PDF/UA-1/7.18.4
H10G — Guarded runtime integration for the form-widget repair
H10H — WebUI PDF: production-path evidence pass
```

If H10E does not fix the ISO side effect:

```text
Continue focused repair only if the next change is precise and evidence-backed.
If unsafe or rejected, park the form-widget repair and move to WebUI production-path baseline plus the next active blocker family.
```

## Next recommended patch

Pending H10E runtime result.

If H10E succeeds:

```text
Guarded metadata adoption and immediate guarded runtime integration.
```

If H10E fails but remains repairable:

```text
Continue focused form-widget structural repair with exact ISO failed-check evidence.
```

If H10E proves the path unsafe or unsuitable:

```text
Park form-widget repair and move to WebUI production-path baseline plus next active blocker family.
```

## Production-readiness statement

Production readiness is not claimed.

The current system has not yet proven the full intended production path from WebUI `PDF:` prompt through Hermes, orchestrator, deterministic repair, validation, truthful status, and deliverables packaging.
