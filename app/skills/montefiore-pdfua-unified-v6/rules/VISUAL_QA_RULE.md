# Visual QA Rule

Visual quality assurance using the Nemotron 3 Nano Omni vision model is the
final gate before packaging. It answers a question that no metric-based check
can: does the remediated document look correct to a human-equivalent observer?

## When visual QA is required

Run the visual QA gate after any operation that could affect the rendered
appearance of a page. This is not optional — it is a hard gate for all of:

- Any OCR operation (even Mode A — verify the invisible text layer did not
  alter rasterization)
- Any contrast color adjustment (fix_contrast_color_runs.py)
- Any pikepdf write operation (object-level changes can affect rendering)
- Any font substitution or notdef glyph repair
- Any operation where render_compare.py reports SSIM < 0.98 or pixel diff > 1%

Operations that do NOT require visual QA:
- Metadata-only changes (fix_metadata_xmp_parity.py, fix_pdfua_identifier.py)
- Struct tree changes that do not touch content streams (fix_table_headers.py,
  fix_parent_tree_mcids.py, fix_link_annotation_descriptions.py)
- Annotation description changes with no visual component

If in doubt, run it. The cost of a false negative (shipping a visually broken
document) is higher than the cost of an extra model call.

## What visual QA checks

The Nemotron model receives a pair of rendered page images — source and output
— along with the render_compare.py pixel diff heatmap for any flagged page.
It is asked to make a qualitative judgment that metrics cannot:

1. **Content integrity** — Is all text visible and legible? Are headings,
   body text, and captions rendered at appropriate sizes and weights?
2. **Layout preservation** — Do tables, figures, and columns appear in the
   same positions as the source? Is whitespace and margin consistent?
3. **Color changes** — If contrast was adjusted, does the result look
   intentional and professional rather than visually jarring?
4. **Artifact detection** — Are there rendering artifacts, missing glyphs,
   white boxes where images should be, or garbled characters?
5. **OCR layer transparency** — If OCR was applied, is the invisible text
   layer genuinely invisible (i.e., does the page look identical to source)?

## Output

visual_qa.py produces `visual_qa_report.json` with per-page results:

```json
{
  "page": 3,
  "render_compare_ssim": 0.997,
  "render_compare_pixel_diff_pct": 0.003,
  "visual_qa_result": "PASS",
  "visual_qa_notes": "Minor rendering difference in footer area — within
    acceptable tolerance. All content and layout preserved.",
  "model_used": "nvidia/nemotron-3-nano-omni-reasoning-30b-a3b"
}
```

Results:
- **PASS** — model confirms visual integrity. Safe to package.
- **REVIEW** — model identifies a concern but cannot determine severity.
  Human must inspect before packaging.
- **FAIL** — model identifies a clear visual defect. Do not package.
  Return to repair gate and investigate.

## Pages that require visual QA

Only run visual QA on pages identified by render_compare.py as having
changed (pixel diff > 0%) or on all pages when OCR was applied.
Do not run visual QA on pages confirmed unchanged by render_compare.py —
it wastes model calls and adds no information.

## Model invocation

Visual QA uses the Nemotron 3 Nano Omni model, not the primary reasoning
model. In Hermes, use the configured vision model before invoking visual_qa.py:

Primary model handles all audit, repair, and packaging decisions.
Switch to vision model only for the visual QA gate, then switch back.

The model is invoked via visual_qa.py — do not call the vision model
directly from agent instructions. All vision model calls are routed
through visual_qa.py which handles image encoding, prompt construction,
and result parsing.

## Disclosure

STATUS.json must include:

```json
"visual_qa_run": true,
"visual_qa_model": "nvidia/nemotron-3-nano-omni-reasoning-30b-a3b",
"visual_qa_pages_checked": [3, 7, 12],
"visual_qa_result": "PASS"
```
