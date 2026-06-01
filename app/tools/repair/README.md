# tools/repair — PDF/UA Repair Helpers

These scripts replace the stub placeholders from `_02_scripts/repair_helpers/`.
All scripts use PyMuPDF (`fitz`) and output structured JSON for pipeline integration.

## Usage pattern

All scripts follow the same conventions:
- **Input/output**: `script.py <input.pdf> <output.pdf>` (audit-only scripts take only `<input.pdf>`)
- **JSON stdout**: structured result with `result`, `changes`, and diagnostic fields
- **Exit codes**: `0` = pass/fixed, `1` = fail/needs attention, `2` = error/missing dependency

---

## Scripts

### fix_pdfua_identifier.py
Injects or corrects `pdfuaid:part=1` and `pdfuaid:amd=2005` in XMP metadata.
**Hard requirement** for veraPDF PDF/UA-1 pass.

### fix_metadata_xmp_parity.py
Synchronises PDF Info dictionary ↔ XMP metadata fields.
Resolves mismatches in Title, Author, Subject, Creator, Producer.
XMP values win on conflict.

### fix_figure_alt_text.py
Adds Alt text to Figure structure elements missing it.
- **Auto mode** (default): sets placeholder text, flags for human review
- **Manual mode**: `--alt-map alt_map.json` applies exact alt strings per figure index
**All auto-placeholders must be replaced before final handoff.**

### fix_table_headers.py
Sets `Scope` attribute on TH cells (defaults to `Column`) and adds placeholder
`Summary` to Table elements. Review ordered/complex tables manually.

### fix_link_annotation_descriptions.py
Sets `Contents` (tooltip description) on Link annotations missing it.
Derives text from visible link text or URI. Flags links where no text was found.

### fix_list_numbering.py
Sets `ListNumbering` attribute on `L` (list) structure elements.
Defaults to `Unordered` — review and correct ordered lists manually.

### fix_notdef_glyphs.py *(audit only)*
Reports .notdef glyph occurrences. Cannot auto-repair — requires font
substitution via `font_replacement_report.py` + `font_geometry_matcher.py`.

### fix_parent_tree_mcids.py
Audits ParentTree for MCIDs referenced in content streams but missing from
the number tree. Reports unresolvable orphans for manual intervention.

### fix_contrast_color_runs.py *(audit only)*
Reports text runs failing WCAG 1.4.3 contrast thresholds (4.5:1 normal, 3:1 large).
Cannot auto-recolor — background detection is approximate; human review required.

### font_replacement_report.py *(audit only)*
Reports non-embedded fonts, missing ToUnicode streams, and proprietary fonts.
Feed output into `font_geometry_matcher.py` to find compatible open replacements.

---

## Dependency

All scripts require:
```
pip install pymupdf
```

veraPDF must be re-run after applying any repair script to confirm the fix resolves
the targeted rule violation without introducing new ones.
