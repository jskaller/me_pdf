#!/usr/bin/env python3
"""form_field_preservation_audit.py

Compare interactive PDF form fields/widgets between a source PDF and an output
PDF. This is intentionally separate from visual and text preservation: a PDF
can render identically and preserve text while losing AcroForm/widget
interactivity.

Result policy:
- PASS if the source has no form fields.
- PASS if source form fields/widgets are preserved by count/name/type/value.
- FAIL if source form fields exist and the output loses fields/widgets,
  changes field names/types, or changes non-empty field values.
"""

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

try:
    import fitz
except Exception as exc:
    print(json.dumps({"result": "ERROR", "error": f"PyMuPDF unavailable: {exc}"}))
    sys.exit(2)


def safe_str(value):
    if value is None:
        return ""
    return " ".join(str(value).split())


def rect_to_list(rect):
    try:
        return [round(float(rect.x0), 3), round(float(rect.y0), 3),
                round(float(rect.x1), 3), round(float(rect.y1), 3)]
    except Exception:
        return []


def acroform_info(path):
    info = {
        "has_acroform": False,
        "acroform_field_count": 0,
        "acroform_error": "",
    }

    try:
        import pikepdf
    except Exception as exc:
        info["acroform_error"] = f"pikepdf unavailable: {type(exc).__name__}: {exc}"
        return info

    def walk_field(field_obj):
        count = 1
        try:
            kids = field_obj.get("/Kids", [])
        except Exception:
            kids = []

        for kid in kids or []:
            try:
                count += walk_field(kid)
            except Exception:
                count += 1
        return count

    try:
        with pikepdf.Pdf.open(str(path)) as pdf:
            acroform = pdf.Root.get("/AcroForm", None)
            if acroform is None:
                return info

            info["has_acroform"] = True
            fields = acroform.get("/Fields", [])
            total = 0
            for field in fields or []:
                try:
                    total += walk_field(field)
                except Exception:
                    total += 1
            info["acroform_field_count"] = total
    except Exception as exc:
        info["acroform_error"] = f"{type(exc).__name__}: {exc}"

    return info


def inspect_pdf(path):
    doc = fitz.open(str(path))
    fields = []
    annot_widget_count = 0

    for page_index, page in enumerate(doc):
        # Primary path: PyMuPDF widgets.
        try:
            widgets = page.widgets()
        except Exception:
            widgets = None

        if widgets:
            for widget in widgets:
                name = safe_str(getattr(widget, "field_name", ""))
                field_type = getattr(widget, "field_type", None)
                field_type_string = safe_str(getattr(widget, "field_type_string", ""))
                value = safe_str(getattr(widget, "field_value", ""))
                label = safe_str(getattr(widget, "field_label", ""))

                fields.append({
                    "page": page_index + 1,
                    "name": name,
                    "type": safe_str(field_type),
                    "type_string": field_type_string,
                    "value": value,
                    "label": label,
                    "rect": rect_to_list(getattr(widget, "rect", None)),
                })

        # Fallback/supporting count: widget annotations are annotation type 19.
        try:
            annots = page.annots()
        except Exception:
            annots = None

        if annots:
            for annot in annots:
                try:
                    annot_type = annot.type[0]
                except Exception:
                    annot_type = None
                if annot_type == 19:
                    annot_widget_count += 1

    doc.close()

    fields = sorted(
        fields,
        key=lambda item: (
            item.get("page", 0),
            item.get("name", ""),
            item.get("type_string", ""),
            item.get("rect", []),
        ),
    )

    names = [f["name"] for f in fields if f.get("name")]
    type_counts = Counter(
        f.get("type_string") or f.get("type") or "unknown"
        for f in fields
    )

    by_name = {}
    for f in fields:
        name = f.get("name")
        if name and name not in by_name:
            by_name[name] = f

    acro = acroform_info(path)

    return {
        "pdf": str(path),
        "pages": len(fitz.open(str(path))),
        "field_count": len(fields),
        "widget_count": len(fields),
        "annot_widget_count": annot_widget_count,
        "named_field_count": len(names),
        "names": sorted(names),
        "type_counts": dict(type_counts),
        "fields": fields,
        "by_name": by_name,
        **acro,
    }


def compare(source, output):
    src = inspect_pdf(source)
    out = inspect_pdf(output)

    source_has_form = (
        src["field_count"] > 0
        or src["annot_widget_count"] > 0
        or src["acroform_field_count"] > 0
    )
    output_has_form = (
        out["field_count"] > 0
        or out["annot_widget_count"] > 0
        or out["acroform_field_count"] > 0
    )

    failures = []
    warnings = []

    if not source_has_form:
        return {
            "result": "PASS",
            "reason": "source_has_no_form_fields",
            "source_has_form": False,
            "output_has_form": output_has_form,
            "source": src,
            "output": out,
            "failures": failures,
            "warnings": warnings,
        }

    if not output_has_form:
        failures.append("source_has_form_fields_but_output_has_none")

    if out["field_count"] < src["field_count"]:
        failures.append(
            f"field_count_decreased: source={src['field_count']} output={out['field_count']}"
        )

    if out["annot_widget_count"] < src["annot_widget_count"]:
        failures.append(
            "widget_annotation_count_decreased: "
            f"source={src['annot_widget_count']} output={out['annot_widget_count']}"
        )

    if out["acroform_field_count"] < src["acroform_field_count"]:
        failures.append(
            "acroform_field_count_decreased: "
            f"source={src['acroform_field_count']} output={out['acroform_field_count']}"
        )

    src_names = set(src["names"])
    out_names = set(out["names"])
    lost_names = sorted(src_names - out_names)
    if lost_names:
        failures.append(f"lost_field_names: {lost_names}")

    type_mismatches = []
    value_mismatches = []

    for name in sorted(src_names & out_names):
        src_field = src["by_name"].get(name, {})
        out_field = out["by_name"].get(name, {})

        src_type = src_field.get("type_string") or src_field.get("type")
        out_type = out_field.get("type_string") or out_field.get("type")
        if src_type != out_type:
            type_mismatches.append({
                "name": name,
                "source_type": src_type,
                "output_type": out_type,
            })

        src_value = src_field.get("value", "")
        out_value = out_field.get("value", "")
        if src_value and src_value != out_value:
            value_mismatches.append({
                "name": name,
                "source_value": src_value,
                "output_value": out_value,
            })

    if type_mismatches:
        failures.append(f"field_type_mismatches: {type_mismatches}")

    if value_mismatches:
        failures.append(f"non_empty_field_value_mismatches: {value_mismatches}")

    result = "FAIL" if failures else "PASS"

    return {
        "result": result,
        "reason": "form_fields_preserved" if result == "PASS" else "form_fields_not_preserved",
        "source_has_form": source_has_form,
        "output_has_form": output_has_form,
        "source_field_count": src["field_count"],
        "output_field_count": out["field_count"],
        "source_widget_annotation_count": src["annot_widget_count"],
        "output_widget_annotation_count": out["annot_widget_count"],
        "source_acroform_field_count": src["acroform_field_count"],
        "output_acroform_field_count": out["acroform_field_count"],
        "lost_field_names": lost_names,
        "type_mismatches": type_mismatches,
        "value_mismatches": value_mismatches,
        "source": src,
        "output": out,
        "failures": failures,
        "warnings": warnings,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("source")
    parser.add_argument("output")
    parser.add_argument("--out", default=None)
    args = parser.parse_args()

    result = compare(Path(args.source), Path(args.output))
    payload = json.dumps(result, indent=2)
    print(payload)

    if args.out:
        Path(args.out).write_text(payload)

    sys.exit(0 if result.get("result") == "PASS" else 1)


if __name__ == "__main__":
    main()
