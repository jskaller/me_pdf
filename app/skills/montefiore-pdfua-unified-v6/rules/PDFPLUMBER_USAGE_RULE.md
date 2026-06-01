# pdfplumber Usage Rule

pdfplumber analyzes PDF layout geometry — character positions, lines, and
rectangles — to detect visual structure. It and PyMuPDF answer different
questions and are used in sequence, not in competition.

## What each tool is primary for

**pdfplumber is primary for:**
Visual table presence detection. Given a page, does a table exist visually
on it, regardless of whether the structure tree knows about it? pdfplumber
detects this from geometry (borders, aligned text, whitespace patterns).
This is the question pdfplumber was specifically designed to answer, and
it outperforms PyMuPDF's table detection on bordered financial and clinical
document types — exactly the document types in this corpus.

**PyMuPDF is primary for:**
Structure tree compliance. Given tables that exist in the struct tree, are
they correctly tagged with appropriate TH/TD scope, header associations,
and parent-child relationships? This is what veraPDF validates and what
our repair scripts target.

These are sequential, not overlapping. A table pdfplumber finds that is absent
from the struct tree is an **untagged table** — a veraPDF failure that PyMuPDF
struct tree analysis would not discover, because it can only inspect what is
already tagged.

## Recommended audit sequence for tables

1. **pdfplumber** — detect all visually present tables on each page
2. **PyMuPDF / table_semantics_audit.py** — inspect struct tree table tags
3. **Cross-reference** — identify any visual tables missing from struct tree
4. **veraPDF** — validate compliance of tagged tables
5. **Repair** (PyMuPDF or pikepdf) — address struct tree failures

Step 3 is the critical addition. If pdfplumber detects N visual tables on a
page and the struct tree contains fewer than N table elements, the delta
represents untagged tables that must be flagged for manual review or repair.

## pdfplumber is audit-only

pdfplumber cannot write PDFs. It must never be used in any repair path. Its
output is diagnostic information that informs repair decisions made by PyMuPDF
or pikepdf.

## Performance note

pdfplumber is approximately 8-12x slower than PyMuPDF on text extraction.
For table detection specifically the gap is smaller, but it is still
meaningfully slower. Run pdfplumber only on pages where table analysis is
needed, not as a full-document pass on every page.

Do not run pdfplumber on image-only pages — it cannot detect anything without
a native text layer. Check with `detect_image_only_pages.py` first and skip
image-only pages.

## Output

Write pdfplumber findings to:
`<job_dir>/audit/pdfplumber_table_map.json`

Format:
```json
{
  "pages": {
    "1": { "visual_tables_detected": 2, "struct_tree_tables": 1, "delta": 1 },
    "4": { "visual_tables_detected": 1, "struct_tree_tables": 1, "delta": 0 }
  },
  "untagged_table_pages": [1],
  "total_visual_tables": 3,
  "total_tagged_tables": 2
}
```

Note in STATUS.json when pdfplumber was run:
`"pdfplumber_table_audit_run": true`

Flag any page with `delta > 0` as requiring manual review of table tagging.
