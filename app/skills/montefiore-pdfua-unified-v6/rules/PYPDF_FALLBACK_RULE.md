# pypdf Fallback Rule

pypdf (the current maintained successor to the deprecated PyPDF2 — do not use
PyPDF2) is a pure-Python PDF library with no compiled dependencies. It serves
as a fallback parser only.

## When pypdf is permitted

Use pypdf only when PyMuPDF raises an exception opening or processing a
document. pypdf's more permissive pure-Python parser can open some malformed
PDFs that PyMuPDF's strict C-based parser rejects.

Do not use pypdf on documents PyMuPDF can open. PyMuPDF is faster, more
accurate, and has structure tree access that pypdf lacks entirely.

## What pypdf can and cannot do

**pypdf CAN:**
- Open some malformed PDFs that PyMuPDF rejects
- Extract plain text for content verification purposes
- Read basic metadata from the Info dictionary
- Merge and split pages

**pypdf CANNOT:**
- Access the PDF structure tree (no StructTreeRoot support)
- Inspect or repair struct tree elements
- Perform any PDF/UA-relevant structural operations
- Be used as a repair tool — it is a reader and limited writer only

## Fallback procedure

If PyMuPDF raises an exception opening a document:

1. Log the PyMuPDF error in STATUS.json under `"pymupdf_failure_reason"`
2. Attempt to open the document with pypdf
3. If pypdf succeeds, extract plain text for `preservation_audit.py` only
4. Run `qpdf --check` to assess structural damage
5. If `qpdf --check` reports errors, attempt `qpdf --repair` on the source
6. Retry PyMuPDF on the `qpdf`-repaired output
7. If PyMuPDF still fails after qpdf repair, mark the document as
   REVIEW_REQUIRED — do not proceed to full remediation under automation

If pypdf also fails to open the document, mark as REVIEW_REQUIRED with reason
`"parser_failure_both_pymupdf_and_pypdf"`. The document requires manual
inspection before any automated processing can proceed.

## Documentation requirement

Any use of pypdf as a fallback must be noted in STATUS.json:

```json
"pypdf_fallback_used": true,
"pymupdf_failure_reason": "<exception message>",
"pypdf_outcome": "text_extracted" | "also_failed"
```

A pypdf-based result is never equivalent to a PyMuPDF-based result. A document
that required the pypdf fallback path cannot be considered fully remediated
until PyMuPDF can open the qpdf-repaired output and all normal gates pass.
