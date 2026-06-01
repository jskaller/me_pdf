# Alt Text Rule

Alt text remediation is triggered only by veraPDF failure. If veraPDF's
initial PDF/UA audit finds no Figure element failures, the alt text gate
passes and the entire alt text remediation path is skipped. No vision model
calls, no report generation, no additional cycles.

## Gate position

Alt text audit is part of the initial veraPDF gate, not a separate step.
veraPDF reports "Figure structure element neither has an alternate description
nor a replacement text" as a PDF/UA-1 failure. This failure triggers the
alt text remediation path. All other veraPDF failures are addressed in
parallel per normal repair sequencing.

## Remediation path — four steps

### Step 1 — Auto-placeholder (fix_figure_alt_text.py, auto mode)
Sets `[Figure N — alt text required]` on all Figure elements with missing
or empty Alt attributes. This makes veraPDF pass structurally so subsequent
gates can run. The placeholder is not meaningful alt text and must not
remain in the final document.

Output: `fix_figure_alt_text_auto.json` containing `needs_review` list.

### Step 2 — Vision model draft (generate_alt_text_drafts.py)
Renders each figure in `needs_review` as a thumbnail and sends it to the
configured vision model for a draft alt text description. Writes
`alt_map_draft.json`.

If `alt_map_instructions.json` is provided (from a previous review cycle),
those instructions override the default prompt for flagged figures.

Output: `alt_map_draft.json` — draft only, not applied to document.

### Step 3 — Human review (generate_alt_text_review_report.py)
Generates a self-contained HTML report showing each figure thumbnail
alongside its draft alt text. Reviewer opens the report in a browser.

The pre-generated `alt_map_approved.json` written alongside the report
represents the accepted state. If the reviewer takes no action (closes
the browser without clicking), `alt_map_approved.json` stands as-is.
This is intentional — no action means the drafts are accepted.

Reviewer actions:
- **Flag + instruction** — check the flag box and type an instruction
  (e.g. "replace with: Bar chart showing Q1–Q4 adherence rates" or
  "not decorative"). Typing in the instruction field auto-checks the flag.
- **Resubmit flagged** — downloads `alt_map_instructions.json` for flagged
  figures only. Agent re-runs Step 2 with instructions, generates new report.
  Unflagged figures are not re-processed.
- **Accept all** — downloads updated `alt_map_approved.json`. Done.

Output: `alt_text_review.html` + `alt_map_approved.json`

### Step 4 — Apply approved text (fix_figure_alt_text.py, manual mode)
Applies `alt_map_approved.json` to the document. Figures marked decorative
are artifacted. Figures with approved alt text receive that text.

Run veraPDF after this step to confirm all Figure failures are resolved.

Output: `fix_figure_alt_text_approved.json`

## Image classification

| Type | Treatment |
|------|-----------|
| Charts, graphs, clinical diagrams | Vision draft → human review → alt text |
| Logos, letterheads | Vision draft → human review → short standard description |
| Photographs | Vision draft → human review. Never identify patients. Describe image content without personal identification. |
| Decorative dividers, rules, backgrounds | Mark decorative → artifact |
| Scanned tables | Not in this path — handled by OCR + table tagging pipeline |

## Vision model prompt guidance

The vision model is instructed to:
- Describe what the image shows (chart type, subject, key values if readable)
- Keep descriptions under 150 characters where possible
- Not describe style or decorative elements
- Not identify any people
- Return `DECORATIVE` exactly if the image is purely ornamental

Model output tagged DECORATIVE is pre-checked as decorative in the review
report. Reviewer can override by flagging with instruction "not decorative".

## Gate 9 pass condition

Gate 9 passes when:
1. veraPDF reports zero Figure alt text failures on the final output, AND
2. `alt_map_approved.json` exists with reviewer name and timestamp
   (or was pre-generated and no resubmit was requested), AND
3. No `[Figure N — alt text required]` placeholder strings remain in
   the document (verified by fix_figure_alt_text.py manual mode output)

A document with placeholder alt text that passes veraPDF structurally
does NOT satisfy Gate 9. Placeholders must be replaced.

## STATUS.json fields

```json
"alt_text": {
  "verapdf_figure_failures_initial": 4,
  "remediation_path_triggered": true,
  "vision_model": "nvidia/nemotron-3-nano-omni-reasoning-30b-a3b",
  "figures_drafted": 4,
  "review_report": "alt_text_review.html",
  "reviewer": "JSkaller",
  "reviewed_at": "2026-05-22T...",
  "resubmit_cycles": 0,
  "figures_approved": 3,
  "figures_artifacted": 1,
  "result": "PASS"
}
```

If veraPDF found no Figure failures: `"alt_text": {"result": "PASS", "remediation_path_triggered": false}`
