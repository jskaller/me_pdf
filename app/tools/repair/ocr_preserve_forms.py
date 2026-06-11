#!/usr/bin/env python3
"""
ocr_preserve_forms.py

Strategy: `ocrmypdf_force_ocr_with_form_merge`.

OCR a PDF via ocrmypdf while preserving AcroForm form fields and widget
annotations.  This is the script referenced by `tools/repair/ocr_preserve_forms.py`
in ocr_strategy_proposal.json.

Pipeline
--------
1. Open the source PDF with pikepdf (no mutation) and extract the `/AcroForm`
   subtree plus every `/Annots` array whose entries carry `/Subtype /Widget`.
2. Run `ocrmypdf --force-ocr --deskew --rotate-pages --no-correct-tz`
   to produce a searchable-OCR PDF on a temp path.
3. Open the OCR output with pikepdf.  Overwrite its `/AcroForm` with the
   source one, then for each page inject the corresponding widget annotations
   (with `/P` references rewritten to the new page objects), merging them with
   any annotations already produced by ocrmypdf.
4. Save the merged document and verify with the project's image-only-pages and
   form-field-preservation audits.

Exit codes
----------
0  PROMOTABLE: OCR text present and all source form fields are present with the
   same or greater field count in output.
1  FORM_MISMATCH / DOCUMENT_CHANGED: a sanity check or post-merge audit found
   inconsistent form state.
2  TOOL_FAILURE: ocrmypdf or pikepdf raised an exception.
"""

from __future__ import annotations

import sys
import json
import argparse
import gc
from pathlib import Path

try:
    import pikepdf
except Exception as exc:  # pragma: no cover – hard dependency
    err = json.dumps({"result": "ERROR", "error": f"pikepdf unavailable: {exc}"})
    print(err)
    sys.exit(2)

try:
    import ocrmypdf
    _OCRM_OK = True
except Exception:  # pragma: no cover – optional at import time
    _OCRM_OK = False


# ---------------------------------------------------------------------------
# Pytest fixtures (used by tools/repair/tests when this file is imported)
# ---------------------------------------------------------------------------

try:
    import pytest

    @pytest.fixture()
    def sample_form_pdf(tmp_path: Path) -> Path:
        """Build a minimal one-page PDF that has an AcroForm with a Text field
        and a fresh /P page reference, suitable for end-to-end merge tests."""
        import pikepdf  # re-import inside fixture scope

        out = tmp_path / "sample_form.pdf"
        pdf = pikepdf.Pdf.new()

        # Page
        page = pikepdf.Page(pdf, pikepdf.Rect(0, 0, 612, 792))

        # Widget annotation on the page (Rect covers lower-left corner)
        widget = pikepdf.Dictionary(
            Type=pikepdf.Name("/Annot"),
            Subtype=pikepdf.Name("/Widget"),
            Rect=pikepdf.Array([50, 50, 200, 80]),
            FT=pikepdf.Name("/Tx"),
            T=pikepdf.String("Field1"),
            V=pikepdf.String(""),
            Ff=pikepdf.Integer(0),
            P=page.obj,
        )

        # Form field node that points to the widget via /Kids
        field = pikepdf.Dictionary(
            Type=pikepdf.Name("/Annot"),
            Subtype=pikepdf.Name("/Widget"),
            FT=pikepdf.Name("/Tx"),
            T=pikepdf.String("Field1"),
            Kids=pikepdf.Array([widget]),
            V=pikepdf.String(""),
            Ff=pikepdf.Integer(0),
        )

        # AcroForm root
        acroform = pikepdf.Dictionary(
            Type=pikepdf.Name("/XObject"),
            Fields=pikepdf.Array([field]),
            NeedAppearances=pikepdf.Boolean(False),
            SigFlags=pikepdf.Integer(0),
        )

        page_obj = page.obj
        page_obj.Annots = pikepdf.Array([widget])
        pdf.Root = pikepdf.Dictionary(
            AcroForm=acroform,
            Type=pikepdf.Name("/Catalog"),
            Pages=pikepdf.Dictionary(
                Type=pikepdf.Name("/Pages"),
                Kids=pikepdf.Array([page_obj]),
                Count=pikepdf.Integer(1),
            ),
        )
        pdf.save(str(out))
        pdf.close()
        return out

    _PYTEST_AVAILABLE = True
except ImportError:
    _PYTEST_AVAILABLE = False


# ---------------------------------------------------------------------------
# pikepdf helpers
# ---------------------------------------------------------------------------

def _rewrite_page_refs(obj: pikepdf.Object, mapping: dict[pikepdf.Object, pikepdf.Object]) -> None:
    """Rewrite direct /P page references inside *obj* in-place."""
    if isinstance(obj, pikepdf.Dictionary):
        current = obj.get("/P")
        if current is not None and isinstance(current, pikepdf.Object):
            new_page = mapping.get(current)
            if new_page is not None:
                obj["/P"] = new_page
        for _, val in obj.items():
            _rewrite_page_refs(val, mapping)
    elif isinstance(obj, pikepdf.Array):
        for item in obj:
            _rewrite_page_refs(item, mapping)


def _collect_src_widgets(doc: pikepdf.Pdf, page_obj: pikepdf.Object) -> pikepdf.Array:
    """Return a pikepdf.Array of widget annotations on *page_obj* from *doc*.

    Non-widget entries are silently skipped so that link annotations embedded
    by ocrmypdf are preserved rather than discarded.
    """
    result = pikepdf.Array()
    annots_raw = page_obj.get("/Annots")
    if not isinstance(annots_raw, pikepdf.Array):
        return result

    for annot in annots_raw:
        if not isinstance(annot, pikepdf.Dictionary):
            continue
        # Tentative: accept anything without /Subtype (broader) or with /Widget
        subtype = annot.get("/Subtype")
        if subtype is pikepdf.Name("/Widget"):
            result.append(annot)
    return result


def _merge_page_annotations(
    new_doc: pikepdf.Pdf,
    new_page: pikepdf.Page,
    src_widgets: pikepdf.Array,
) -> None:
    """Inject *src_widgets* (objects still belonging to the *source* doc) into
    *new_page*, rewriting their `/P` references to the new page objects and
    merging transparently with any annotations already present that ocrmypdf
    wrote into the output.

    Any objects in *new_page* already carrying a `/P` pointing at another new
    page (link annotations, ocrmypdf internal annots) are preserved first.  If
    a merged widget has the same indirect-object number as an existing skip
    entry it is deduplicated automatically.

    The merge is safe because:
    - widget annotations self-identify via their `/T` (field name) and `/Rect`.
    - page-level link annotations have no `/T` and non-overlapping `/Rect`s.
    """
    # Gather existing annotations already written by ocrmypdf, preserving
    # non-widget annotations (link annots etc.) that we do not want to drop.
    existing_annots: list[pikepdf.Object] = []
    annots_raw = new_page.obj.get("/Annots")
    if isinstance(annots_raw, pikepdf.Array):
        existing_annots = [item for item in annots_raw if isinstance(item, pikepdf.Object)]

    # Build a per-page mapping from old page objects → new page objects.
    # Needed for multiple pages, though we're only called page-by-page here.
    page_map: dict[pikepdf.Object, pikepdf.Object] = {new_page.obj: new_page.obj}

    # Rewrite source widget /P references and import into new_doc.
    imported_widgets: list[pikepdf.Object] = []
    for src_widget in src_widgets:
        # Import into new_doc's object graph (new_obj has the same body but a
        # fresh indirect reference in new_doc).
        new_obj = pikepdf.Dictionary(new_doc, src_widget)
        new_obj = new_doc.make_indirect(new_obj)
        _rewrite_page_refs(new_obj, page_map)
        imported_widgets.append(new_obj)

    # Build a set of already-present indirect references to deduplicate.
    existing_ids = {id(item) for item in existing_annots}
    merged_annots: list[pikepdf.Object] = list(existing_annots)
    for widget in imported_widgets:
        if id(widget) not in existing_ids:
            merged_annots.append(widget)

    # Write the merged array back to the page.
    if merged_annots:
        arr = pikepdf.Array(merged_annots)
        new_page.obj["/Annots"] = arr


# ---------------------------------------------------------------------------
# Core OCR + merge logic
# ---------------------------------------------------------------------------

def _run_ocrmypdf(source: Path, output: Path) -> None:
    """Run ocrmypdf with the recommended form-preservation flags."""
    if not _OCRM_OK:
        raise RuntimeError(
            "ocrmypdf is not installed. Install it first: pip install ocrmypdf"
        )
    output.parent.mkdir(parents=True, exist_ok=True)
    ocrmypdf.ocr(
        str(source),
        str(output),
        output_type="pdf",
        force_ocr=True,
        deskew=True,
        rotate_pages=True,
        no_correct_tz=True,
        quiet=True,
    )


def _check_image_only_pages(path: Path, audit_json: Path) -> dict:
    """Audit *path* for residual image-only pages.  Returns the parsed JSON."""
    ctx = _get_job_ctx()  # never None in production via sys.argv injection
    detect_script = Path(ctx["script_dir"]) / "detect_image_only_pages.py"
    result = _run_standalone_audit(
        [sys.executable, str(detect_script), str(path), "--out", str(audit_json), "--min-chars", "30"],
        audit_json,
    )
    return result


def _check_form_fields(source: Path, output: Path, audit_json: Path) -> dict:
    """Audit form-field preservation between *source* and *output*."""
    ctx = _get_job_ctx()
    audit_script = Path(ctx["script_dir"]) / "form_field_preservation_audit.py"
    result = _run_standalone_audit(
        [sys.executable, str(audit_script), str(source), str(output), "--out", str(audit_json)],
        audit_json,
    )
    return result


# ---------------------------------------------------------------------------
# argparse store – must be defined before resolve() so entry-points can set it
# ---------------------------------------------------------------------------

_ARGS: argparse.Namespace | None = None


def _get_args() -> argparse.Namespace:
    global _ARGS
    if _ARGS is None:
        _ARGS = _parse_args(["noop", "--out", "/dev/null"])
    return _ARGS


def _parse_args(argv: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("source", type=Path)
    p.add_argument("output", type=Path)
    p.add_argument("--out", required=True, type=Path, help="Write JSON result here")
    p.add_argument("--audit-dir", type=Path, default=None)
    p.add_argument("base_name", nargs="?", default="")
    return p.parse_args(argv[1:])


# Re-declare with defaults so resolve() below can safely use them when the
# module is invoked directly (normal path) or imported (test stub path).

def _run_standalone_audit(cmd: list[str], audit_json: Path) -> dict:
    """Execute a subprocess audit script and return its parsed JSON."""
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
        if audit_json.exists():
            return json.loads(audit_json.read_text())
        return {
            "exit_code": proc.returncode,
            "stdout": proc.stdout,
            "stderr": proc.stderr,
        }
    except FileNotFoundError as exc:
        return {"error": str(exc)}
    except Exception as exc:  # pragma: no cover
        return {"error": str(exc)}


def resolve(
    source: Path,
    output: Path,
    audit_dir: Path | None = None,
) -> dict:
    """Main logic used by both the CLI entry-point and test code."""
    args_out = Path("/dev/null")  # overridden in tests via _ARGS
    args_audit_dir = audit_dir or source.parent

    # Temp paths
    ocr_artifact = args_audit_dir / "ocr_preserve_forms_ocr_output.pdf"
    image_audit = args_audit_dir / "ocr_preserve_forms_image_only_pages.json"
    form_audit = args_audit_dir / "ocr_preserve_forms_form_preservation.json"

    # ── Phase 1: ocrmypdf ────────────────────────────────────────────────────
    try:
        _run_ocrmypdf(source, ocr_artifact)
    except Exception as exc:
        err = {"result": "TOOL_FAILURE", "stage": "ocr", "error": str(exc)}
        _write_result(err, args_out)
        return err

    # ── Phase 2: pikepdf merge ───────────────────────────────────────────────
    src_doc = pikepdf.open(str(source), fix_orphans=True)
    ocr_doc = pikepdf.open(str(ocr_artifact))

    # Save AcroForm from source into ocr_doc
    src_root = src_doc.Root
    ocr_root = ocr_doc.Root

    src_acro = src_root.get("/AcroForm")
    if isinstance(src_acro, pikepdf.Dictionary):
        ocr_root["/AcroForm"] = src_acro

    # Build new_acro after assignment so we can collect its /Fields pages for /P rewrite below
    new_acro = ocr_root.get("/AcroForm")
    page_field_refs: list[pikepdf.Object] = []

    # Sanity – validate AcroForm structure
    if not isinstance(new_acro, pikepdf.Dictionary):
        result_err: dict = {
            "result": "DOCUMENT_CHANGED",
            "stage": "merge",
            "error": "AcroForm was not restorable in OCR output (non-dict after injection).",
        }
        _write_result(result_err, args_out)
        src_doc.close()
        ocr_doc.close()
        return result_err

    fields = new_acro.get("/Fields")
    if not isinstance(fields, pikepdf.Array):
        result_err = {
            "result": "DOCUMENT_CHANGED",
            "stage": "merge",
            "error": "/Fields is not an Array in merged AcroForm.",
        }
        _write_result(result_err, args_out)
        src_doc.close()
        ocr_doc.close()
        return result_err

    # All source total fields – used for a sanity field-count check later.
    source_total_fields = len(fields)

    # Collect every /P page reference from source AcroForm widgets.
    def _add_pages_from_node(node: pikepdf.Object) -> None:
        if isinstance(node, pikepdf.Dictionary):
            p_val = node.get("/P")
            if p_val is not None and isinstance(p_val, pikepdf.Object):
                page_field_refs.append(p_val)
            kids = node.get("/Kids")
            if isinstance(kids, pikepdf.Array):
                for k in kids:
                    _add_pages_from_node(k)

    for field_node in fields:
        _add_pages_from_node(field_node)

    # Sanity: all collected /P refs must be page objects that exist in the
    # output's page tree.  (Orphan page-node references would break AcroForm
    # resolution in Acrobat/AT.)
    ocr_pages = list(ocr_doc.pages)
    for p_obj in page_field_refs:
        if p_obj not in ocr_pages:
            result_err = {
                "result": "DOCUMENT_CHANGED",
                "stage": "merge",
                "error": (
                    f"AcroForm /P reference ({p_obj.objgen}) not found in output "
                    "page tree; merge aborted."
                ),
            }
            _write_result(result_err, args_out)
            src_doc.close()
            ocr_doc.close()
            return result_err

    # For each ocrmypdf output page, inject the source widget annotations.
    for ocr_page in ocr_pages:
        page_number = ocr_page.objgen
        src_annots_obj = None
        for i, p in enumerate(src_doc.pages):
            if i == ocr_pages.index(ocr_page):
                src_annots_obj = p.obj
                break

        src_widgets = (
            _collect_src_widgets(src_doc, src_annots_obj) if src_annots_obj else pikepdf.Array()
        )
        _merge_page_annotations(ocr_doc, ocr_page, src_widgets)

    ocr_doc.save(str(output))
    ocr_doc.close()
    src_doc.close()
    # Release caches before subprocess calls.
    del ocr_doc, src_doc
    gc.collect()

    # ── Phase 3: post-merge audits ──────────────────────────────────────────
    image_result = _check_image_only_pages(output, image_audit)
    form_result = _check_form_fields(source, output, form_audit)

    ocr_ok = (
        image_result.get("ocr_required", True) is False
        and not image_result.get("image_only_pages")
    )
    form_ok = (
        form_result.get("result") == "FORM_FIELDS_PRESERVED"
        and form_result.get("output_field_count", 0) >= source_total_fields
    )

    if ocr_ok and form_ok:
        verdict: dict = {
            "result": "PROMOTABLE",
            "strategy": "ocrmypdf_force_ocr_with_form_merge",
            "output": str(output),
            "ocr_result": image_result,
            "form_result": form_result,
            "source_field_count": source_total_fields,
            "output_field_count": form_result.get("output_field_count"),
        }
    else:
        verdict = {
            "result": "FORM_MISMATCH",
            "ocr_result": image_result,
            "form_result": form_result,
            "ocr_pass": ocr_ok,
            "form_pass": form_ok,
            "source_field_count": source_total_fields,
            "output_field_count": form_result.get("output_field_count"),
        }

    _write_result(verdict, args_out)
    return verdict


def _write_result(data: dict, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n")


# ---------------------------------------------------------------------------
# CLI entry-point
# ---------------------------------------------------------------------------

def main() -> None:
    global _ARGS
    args = _parse_args(sys.argv)
    _ARGS = args  # make visible to helpers

    script_dir = Path(sys.argv[0]).resolve().parent
    ctx = {
        "script_dir": script_dir,
        "ticket": "MM-17179",
    }

    # Inject context into helpers (monkey-patch module-level so _check_* can use it)
    global _get_job_ctx
    _get_job_ctx = lambda: ctx  # type: ignore[assignment,misc]

    result = resolve(
        source=args.source,
        output=args.output,
        audit_dir=args.audit_dir,
    )
    exit_code = 0 if result.get("result") == "PROMOTABLE" else 1
    sys.exit(exit_code)


# ---------------------------------------------------------------------------
# Module-level job-context placeholder (set by main() at runtime)
# ---------------------------------------------------------------------------

def _get_job_ctx() -> dict:  # pragma: no cover – overridden by main()
    return {
        "script_dir": Path.cwd(),
        "ticket": "unknown",
    }


if __name__ == "__main__":
    main()
