# pikepdf Usage Rule

pikepdf provides direct Python access to the PDF object model via the qpdf C++
library. It enables operations that PyMuPDF cannot perform, but carries
significant risk: malformed object writes can corrupt documents in ways that
are not immediately visible and may not be caught by `qpdf --check`.

## When pikepdf is permitted

pikepdf is only permitted when BOTH conditions are true:

1. A specific veraPDF failure class has been identified that cannot be resolved
   using PyMuPDF APIs.
2. The repair target is one of the known valid use cases listed below.

Do not use pikepdf opportunistically, speculatively, or as a general-purpose
alternative to PyMuPDF. If PyMuPDF can do it, use PyMuPDF.

## Known valid use cases

- Rebuilding or patching a corrupted or incomplete ParentTree number tree that
  veraPDF flags but PyMuPDF cannot correct
- Repairing broken xref tables or cross-reference streams
- Removing encryption from a document prior to repair (only with explicit user
  confirmation of authorization — see Encrypted PDFs below)
- Object-level inspection and diagnostic reads (reads are always safe and do
  not require the justification above)

Note: a document that passes `qpdf --check` may still require pikepdf. The
most common case is ParentTree gaps — `qpdf` does not check ParentTree
completeness, but veraPDF does. pikepdf is permitted for this repair even on
`qpdf`-passing documents, provided the veraPDF failure is clearly identified.

## Proportional change limit

Before any pikepdf write operation:

1. Count the total number of indirect objects in the document
2. Estimate how many objects the planned repair will write or modify
3. If the planned writes exceed **10% of total document objects**,
   escalate to REVIEW_REQUIRED before proceeding

Document the object count and estimated change scope in STATUS.json:

```json
"pikepdf_repair": {
  "total_objects": 1240,
  "objects_modified": 87,
  "percent_modified": 7.0,
  "repair_class": "ParentTree rebuild"
}
```

Note: structurally bounded repair classes (ParentTree rebuild, xref repair)
may legitimately exceed 10% on small documents. In this case, document the
repair class explicitly and confirm that all writes are scoped to the specific
repair target. General content edits that exceed 10% are not permitted under
automation regardless of justification — escalate to REVIEW_REQUIRED.

## Mandatory checkpoint before any write

Before any pikepdf write operation, copy the current working PDF to:

`<basename>_pre_pikepdf_checkpoint.pdf`

If the pikepdf result is worse than the checkpoint by any measure, restore
from checkpoint immediately and document the failure.

## Mandatory verification after every pikepdf save

Run all three checks. Any failure is a hard stop — restore from checkpoint:

1. `qpdf --check <output>` — structural integrity
2. veraPDF PDF/UA on output — compare failure count to pre-pikepdf baseline;
   increased failures = restore from checkpoint
3. `preservation_audit.py <checkpoint> <output>` — FAIL = restore from
   checkpoint; REVIEW = document and proceed with approval

## Encrypted PDFs

Do not decrypt an encrypted PDF without explicit user confirmation that
decryption is authorized for this specific document. Log the authorization
in STATUS.json as `"decryption_authorized": true` with the date confirmed.
