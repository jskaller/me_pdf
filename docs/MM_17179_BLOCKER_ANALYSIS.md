# MM-17179 blocker analysis: form-widget and font residuals

Patch H3 is scoped to the representative real-PDF escalation:

```text
workspace/jobs/MM-17179_ROI4987_English_1-26_rev_Fillable
workspace/input/MM-17179/ROI4987_English_1-26_rev_Fillable.pdf
```

The current active blocker cluster is:

- `PDF/UA-1/7.18.4` - widget annotation not nested within a `/Form` structure element.
- `PDF/UA-1/7.21.7` - font dictionary missing `/ToUnicode` map.
- `PDF/UA-1/7.21.4.1` - font embedding failure currently treated as an unknown rule if it remains absent from `rule_repair_map.json`.

## Evidence-first decision

A production repair is not safe from rule IDs alone. Before implementing or mapping a repair, collect object-level evidence from the actual local job PDF:

```bash
PYTHONPATH=app python3 app/tools/audit/mm17179_blocker_inspection.py \
  --job-dir workspace/jobs/MM-17179_ROI4987_English_1-26_rev_Fillable \
  --pdf workspace/input/MM-17179/ROI4987_English_1-26_rev_Fillable.pdf \
  --rule-map app/tools/audit/rule_repair_map.json \
  --out /tmp/mm17179_blocker_inspection.json
```

This diagnostic is read-only. It does not mutate PDFs, workspace artifacts, status files, packaging outputs, or the rule map.

## Rule-specific strategy notes

### PDF/UA-1/7.18.4

This is the best candidate for a future narrow deterministic repair only if inspection proves all of the following:

1. widget annotations are present and countable;
2. widgets have stable `/StructParent` entries or there is a safe way to assign them;
3. `/StructTreeRoot` and `/ParentTree` are present and usable;
4. existing `/Form` structure elements are present or can be added without disrupting existing structure children;
5. AcroForm fields, annotation object identity, tab order, page boxes, and field values can be preserved.

If those preconditions are not met, keep escalation and do not synthesize structure-tree edits.

### PDF/UA-1/7.21.7

Missing `/ToUnicode` is higher risk than form-widget nesting because reconstruction may require reliable character-code-to-Unicode evidence from embedded font programs, encodings, or known glyph maps. Do not add generated CMaps unless the source mapping is deterministic and validator/preservation evidence proves no text extraction regression.

### PDF/UA-1/7.21.4.1

If this rule is absent from the rule map, it remains an `unknown_rule` strategy gap. Object inspection must identify the exact font dictionaries/xrefs, whether the font is Base-14, subset embedded, or otherwise unembedded, and whether embedding/substitution can preserve visual geometry and text extraction. Do not mark this as repairable based only on PyMuPDF `extension` labels.

## Required post-repair evidence for any future Option A implementation

A repair patch for any of these blockers must include:

- before/after veraPDF PDF/UA delta for the targeted rule;
- qpdf success;
- form field preservation evidence for fillable forms;
- page count and page box preservation;
- render comparison or visual QA evidence;
- clear `execution_log.json`, `residual_analysis.json`, `orchestrator_outcome.json`, and `STATUS.json` consistency;
- no successful package copy if the job remains `ESCALATION`.

## Current recommendation

Until the real MM-17179 workspace artifacts and PDF object structures are inspected, choose Option C: keep escalation but improve diagnostics. A future Option A repair for `PDF/UA-1/7.18.4` should be considered only after the diagnostic output proves a safe ParentTree/Form-tagging transformation.
