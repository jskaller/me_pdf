#!/usr/bin/env python3
"""Generate a synthetic PDF/UA-1/7.18.4 form-widget structure fixture.

The fixture intentionally models the H8 MM-17179 blocker shape without using
private data: AcroForm widgets exist, page /Annots membership exists, widgets
lack /StructParent, and the document has no /StructTreeRoot or /ParentTree.
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCHEMA = "montefiore.form_widget_structure_fixture"
VERSION = "1.0.0"


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_pikepdf() -> Any:
    try:
        import pikepdf  # type: ignore
    except Exception as exc:  # pragma: no cover - exercised by environments without pikepdf
        raise RuntimeError(f"pikepdf unavailable: {type(exc).__name__}: {exc}") from exc
    return pikepdf


def generate_fixture(out_path: Path, *, field_count: int = 2) -> dict[str, Any]:
    """Create a small synthetic AcroForm PDF with untagged widget annotations."""
    if field_count < 1:
        raise ValueError("field_count must be at least 1")

    pikepdf = _load_pikepdf()
    out_path.parent.mkdir(parents=True, exist_ok=True)

    pdf = pikepdf.Pdf.new()
    page = pdf.add_blank_page(page_size=(612, 792))
    page_obj = page.obj
    page_obj["/Annots"] = pikepdf.Array([])

    fields = pikepdf.Array([])
    widget_count = 0
    created_fields: list[dict[str, Any]] = []

    for index in range(field_count):
        field_name = f"SyntheticText{index + 1}"
        rect = pikepdf.Array([72, 700 - (index * 40), 260, 720 - (index * 40)])
        field = pdf.make_indirect(pikepdf.Dictionary({
            "/FT": pikepdf.Name("/Tx"),
            "/T": pikepdf.String(field_name),
            "/V": pikepdf.String(f"fixture-value-{index + 1}"),
        }))
        widget = pdf.make_indirect(pikepdf.Dictionary({
            "/Type": pikepdf.Name("/Annot"),
            "/Subtype": pikepdf.Name("/Widget"),
            "/Rect": rect,
            "/FT": pikepdf.Name("/Tx"),
            "/T": pikepdf.String(field_name),
            "/Parent": field,
            "/P": page_obj,
            "/F": 4,
        }))
        field["/Kids"] = pikepdf.Array([widget])
        page_obj["/Annots"].append(widget)
        fields.append(field)
        widget_count += 1
        created_fields.append({"field_name": field_name, "field_type": "Tx", "field_value_present": True})

    pdf.Root["/AcroForm"] = pikepdf.Dictionary({
        "/Fields": fields,
        "/NeedAppearances": True,
    })

    # Intentionally omit /StructTreeRoot, /ParentTree, and widget /StructParent.
    pdf.save(out_path)

    return {
        "schema": SCHEMA,
        "version": VERSION,
        "created_at": now(),
        "result": "GENERATED",
        "path": str(out_path),
        "synthetic": True,
        "private_data": False,
        "page_count": 1,
        "acroform_field_count": field_count,
        "widget_annotation_count": widget_count,
        "widgets_lack_struct_parent": True,
        "struct_tree_root_present": False,
        "parent_tree_present": False,
        "form_struct_element_count": 0,
        "fields": created_fields,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate synthetic form-widget structure fixture")
    parser.add_argument("--out", required=True, help="Output PDF path")
    parser.add_argument("--field-count", type=int, default=2, help="Number of synthetic text fields/widgets")
    parser.add_argument("--report", default="", help="Optional JSON generation report path")
    args = parser.parse_args(argv)

    report = generate_fixture(Path(args.out), field_count=args.field_count)
    text = json.dumps(report, indent=2, sort_keys=True)
    if args.report:
        report_path = Path(args.report)
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(text)
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
