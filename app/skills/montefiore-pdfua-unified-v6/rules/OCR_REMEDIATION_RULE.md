# OCR Remediation Rule

OCR is a text synthesis operation, not a preservation operation. Text produced
by OCR is a machine estimate of document content. It must be disclosed, audited,
and treated as distinct from native text at every stage of the workflow.

## When OCR is permitted

Run OCRmyPDF only when `detect_image_only_pages.py` confirms that one or more
pages have no native text layer. Do not run OCR on documents where all pages
already have native text.

OCR is a last-resort path. If a document has native text on all pages but those
pages fail veraPDF, the problem is structural — not a missing text layer. Do not
use OCR to work around structural failures.

## Visual layout preservation — non-negotiable

OCRmyPDF operates in two modes. Only Mode A is permitted in this workflow.

**Mode A (permitted):** Adds an invisible text layer beneath the existing page
image. The visual appearance of the document does not change.

**Mode B (prohibited):** `--force-ocr` discards the image and re-renders the
page from OCR output. This changes the visual layout and is prohibited under
the same terms as any other visual alteration.

The following flags are PROHIBITED without exception:
- `--force-ocr` — destroys existing image layer, changes visual output
- `--deskew` — rotates and resamples page images
- `--clean` / `--clean-final` — alters page images before OCR
- `--rotate-pages` — changes page orientation

After OCR, run `render_compare.py` comparing source and OCR output. Any page
that fails `render_compare.py` (pixel diff exceeds threshold) is a visual
change violation. Do not proceed to packaging if `render_compare.py` fails on
any OCR-processed page.

## Language detection — required before OCR

Detect the document language before invoking Tesseract. Use the following
priority order:

1. `/Lang` entry in the PDF Catalog (surfaced by `metadata_xmp_parity_audit.py`)
2. XMP `dc:language` field
3. Unicode character range heuristic on a sample of page text

If language is detected with high confidence by any of the above methods,
proceed with that language without requiring user confirmation. The corpus will
include documents in Spanish and other languages — confident detection is
sufficient authorization.

If no language can be determined with high confidence by any method, fall back
to `eng` AND flag `STATUS.json` with `"ocr_language_confidence": "low"`. In
this case, include a note in `PACKAGE_CONTENTS.md` that the language fallback
was applied and human review of OCR accuracy is required.

Do not prompt for user confirmation when language is confidently detected,
regardless of what that language is.

## Order of operations

OCR must run BEFORE any structural repair scripts. Running repair scripts on an
image-only PDF produces structurally tagged but textually empty output.

The gate sequence when OCR is needed:

1. `detect_image_only_pages.py` — identify which pages need OCR
2. Detect language (see above)
3. `ocrmypdf --skip-text -l <lang> source.pdf ocr_output.pdf`
4. `qpdf --check ocr_output.pdf` — hard stop if this fails
5. `render_compare.py source.pdf ocr_output.pdf` — hard stop if visual diff
6. `preservation_audit.py source.pdf ocr_output.pdf` — expect REVIEW, document
7. Proceed with normal gate sequence using `ocr_output.pdf` as the working file

Always use `--skip-text`. This ensures pages with existing native text are
never touched by OCR.

## Required disclosure

`STATUS.json` must include:

```json
"ocr_applied": true,
"ocr_pages": [1, 3, 7],
"ocr_language": "eng",
"ocr_language_confidence": "high",
"ocr_engine": "tesseract"
```

`PACKAGE_CONTENTS.md` must include the following note whenever OCR was applied:

> Pages [list] received OCR processing. Text on these pages is machine-generated
> and may contain recognition errors. Human review of OCR accuracy on these
> pages is recommended before final sign-off.

## Interpreting preservation_audit.py after OCR

`preservation_audit.py` will return REVIEW (not PASS) after OCR because OCR
adds words the source image contained but the untagged PDF did not encode.
This is expected and acceptable — document it explicitly in STATUS.json with
`"ocr_preservation_audit_result": "REVIEW_EXPECTED"`.

A FAIL result (word count zero or dramatically inconsistent with source)
indicates OCR failed or produced nonsense output. Do not package a document
with a FAIL preservation result after OCR.
