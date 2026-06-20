# Font Embedding Strategy for PDF/UA-1/7.21.4.1

Patch E classification: **Option D — diagnostic classification only**.

This document records the current strategy for the WebUI E2E residual blocker:

```text
Rule: PDF/UA-1/7.21.4.1
veraPDF context: PDFont
Observed font: Helvetica
Observed failure: The font program is not embedded
```

## Decision

Do **not** add a production repair script or rule-map repair strategy for `PDF/UA-1/7.21.4.1` yet.

The current repository contains font inventory and font replacement diagnostics, but it does not contain a deterministic, validator-proven repair that embeds or safely substitutes unembedded Base-14 fonts while preserving PDF/UA structure, visual layout, annotations, forms, MCIDs, and text extraction.

Until local E2E artifacts and before/after validator evidence prove a safe repair path, the correct production behavior is a truthful HERMES_REQUIRED / escalation path, not rule suppression and not fake rule-map wiring.

## Component classification

| Component | Classification | Patch E action |
|---|---|---|
| `app/tools/orchestrate/remediate.py` | production path code | Read only; no routing, packaging, or final-PDF authority changes. |
| `app/tools/audit/rule_repair_map.json` | rule map | Read only for this patch; exact rule is absent, and no unproven strategy is added. |
| `app/tools/audit/lookup_repair_plan.py` | repair-plan generation | Read only; missing rules already become `hermes_required` with `reason=unknown_rule`. |
| `app/tools/audit/residual_analysis.py` | validator residual classification | Read only; missing map entries normalize to `repairable_unbuilt`. |
| `app/tools/audit/font_inventory.py` | font audit/diagnostic code | Existing diagnostic; reports non-embedded fonts and missing ToUnicode. |
| `app/tools/audit/font_geometry_matcher.py` | font audit/diagnostic code | Existing diagnostic; ranks candidate replacement font geometry and coverage. |
| `app/tools/repair/font_replacement_report.py` | diagnostic-only repair-adjacent script | Existing diagnostic; explicitly does not modify PDFs. |
| `app/tools/repair/fix_notdef_glyphs.py` | diagnostic-only repair-adjacent script | Existing diagnostic; explicitly says font substitution/re-encoding is required and cannot be automatic. |
| `app/tools/repair/fix_cidset.py` | repair script for a different font rule | Existing repair for CIDSet, not for unembedded Base-14 font programs. |
| `app/tools/qa/preservation_audit.py`, `render_compare.py`, `visual_qa.py` | visual/preservation QA | Required before any future font substitution is considered production-safe. |
| `workspace/jobs/...` artifacts | workspace artifact | Must be inspected locally; do not commit generated PDFs or job outputs. |
| Base-14 font embedding/substitution | missing behavior | Not implemented. |
| arbitrary font rewrite via PyMuPDF | risky/unknown behavior | Not adopted without validator and visual/preservation proof. |

## Investigation answers

1. **Is `PDF/UA-1/7.21.4.1` absent from `rule_repair_map.json`?**
   Yes. The map has nearby font rules such as `PDF/UA-1/7.21.3-1`, `PDF/UA-1/7.21.4.2`, `PDF/UA-1/7.21.4.2-1`, `PDF/UA-1/7.21.6-1`, and `PDF/UA-1/7.21.7`, but not this exact rule.

2. **Does any existing script actually embed or substitute unembedded Base-14 fonts?**
   No. Existing font-related scripts are diagnostic or address other font rules. `font_replacement_report.py` says it does not modify the PDF. `fix_notdef_glyphs.py` says automatic repair is not supported and that font substitution or re-encoding is required.

3. **Is the failing Helvetica used in visible page text, annotation appearance, form appearance, or generated smoke text?**
   Not proven from repository evidence alone. This must be answered from the local E2E PDF, font inventory, page text spans, annotations, widgets, and veraPDF XML context.

4. **Is the PDF tagged, and would reconstructing page content damage structure tagging or MCIDs?**
   Not proven from repository evidence alone. Any repair that reconstructs page content is risky until structure tree, MCID, and ParentTree preservation are audited before and after.

5. **Can PyMuPDF save/rewrite the page with an embedded substitute font while preserving layout closely enough?**
   Not proven. A future experiment must compare page count, dimensions, text extraction, link/annotation inventories, structure references, and render output before adoption.

6. **Is an open font available in the runtime image for safe substitution?**
   Not proven. The project policy lists candidate open families, but explicitly says the runtime inventory is not guaranteed and fonts must not be bundled casually.

7. **Does the project already have font replacement geometry rules or expected open-font policy?**
   Yes. The font policy requires inventory, geometry matching, 100% glyph coverage, and visual QA before claiming equivalence.

8. **Would replacing Helvetica with an embedded substitute affect visual QA or render compare?**
   Potentially yes. Even Helvetica-like substitutes can change metrics, line breaks, text extents, and annotation/form appearances. Render compare and preservation audit are required.

9. **Can the repair be restricted to generated/simple PDFs only, or generalized?**
   Not proven. A fixture-generation fix may be appropriate if the E2E smoke PDF is generated by the test harness, but arbitrary production PDFs should not be rewritten without stronger safety gates.

10. **What exact test would fail before the fix and pass after?**
    For this diagnostic patch, the added test proves missing `PDF/UA-1/7.21.4.1` is routed to `hermes_required` rather than disappearing from action handling. A future repair patch needs a fixture with an unembedded Base-14 font where pre-repair font inventory/veraPDF fails and post-repair font inventory/veraPDF passes.

11. **What validator evidence proves the rule clears?**
    None yet. A future repair must show `verapdf_post_pdfua1.xml` no longer reports `PDF/UA-1/7.21.4.1`, and the font inventory must show the affected replacement font is embedded.

12. **What preservation/visual evidence proves the repair did not damage the document?**
    None yet. A future repair must include preservation audit, page count/dimensions checks, annotation/form inventory checks, text extraction equivalence, and render comparison.

## Required future evidence before Option C

A guarded Base-14 repair script may only be proposed after collecting all of the following locally:

```bash
PYTHONPATH=app python3 app/tools/audit/font_inventory.py \
  --pdf workspace/input/WEBUI-E2E-001/e2e-smoke.pdf \
  --out /tmp/e2e-smoke-font-inventory-input.json

PYTHONPATH=app python3 app/tools/audit/font_inventory.py \
  --pdf workspace/jobs/WEBUI-E2E-001_e2e-smoke/final.pdf \
  --out /tmp/e2e-smoke-font-inventory-final.json

grep -n -A8 -B8 "7.21.4.1" \
  workspace/jobs/WEBUI-E2E-001_e2e-smoke/audit/verapdf_post_pdfua1.xml || true

grep -n -A8 -B8 "font program is not embedded" \
  workspace/jobs/WEBUI-E2E-001_e2e-smoke/audit/verapdf_post_pdfua1.xml || true

grep -n -A8 -B8 "Helvetica" \
  workspace/jobs/WEBUI-E2E-001_e2e-smoke/audit/verapdf_post_pdfua1.xml || true
```

Then run any candidate repair only in an isolated copy and collect:

- pre/post veraPDF PDF/UA XML and parsed summaries;
- pre/post font inventory;
- page count and page dimension comparison;
- text extraction comparison;
- annotation and form-field inventory comparison;
- structure tree / MCID / ParentTree preservation evidence;
- render comparison or visual QA artifact.

## Non-negotiable guardrails

- Do not suppress or downgrade `PDF/UA-1/7.21.4.1`.
- Do not add `rule_repair_map.json` wiring unless the mapped script actually embeds/substitutes the font and validator evidence proves improvement.
- Do not claim PASS unless `STATUS.json` or `orchestrator_outcome.json` says PASS.
- Do not commit local PDFs, workspace job outputs, or generated E2E artifacts.
- Keep WebUI routing, packaging/final PDF authority, metadata repair, learned-strategy adoption, and unrelated repair scripts out of scope.

## Production impact

Production behavior remains truthful: the unresolved font embedding rule continues through HERMES_REQUIRED / escalation rather than being hidden. This patch improves strategy clarity and test coverage without changing remediation authority or final PDF packaging behavior.
