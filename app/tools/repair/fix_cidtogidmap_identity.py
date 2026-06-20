#!/usr/bin/env python3
"""
fix_cidtogidmap_identity.py

Conservatively adds /CIDToGIDMap /Identity to safe embedded Type 2 CIDFont
(descendant) dictionaries.

This script targets PDF/UA-1 clause 7.21.3.2 / ISO 32000-1 Table 117 only.
It is intentionally narrower than generic font repair:

  * parent font must be /Subtype /Type0;
  * descendant font must be /Subtype /CIDFontType2;
  * descendant must not already contain /CIDToGIDMap;
  * descendant must have a /FontDescriptor;
  * descriptor must contain /FontFile2, proving an embedded TrueType font;
  * CIDSystemInfo must be Adobe / Identity / 0.

It never overwrites an existing /CIDToGIDMap name or stream.

Runtime note:
  The Hermes venv may not include pikepdf. Normal mapped repair scripts run via
  REMEDIATION_PYTHON, which defaults to /usr/bin/python3 in remediate.py. The
  Dockerfile installs app/requirements.txt, including pikepdf, into that system
  Python. Do not execute this repair through learned-strategy sys.executable
  paths unless that runtime dependency boundary is changed and tested.

Usage:
  fix_cidtogidmap_identity.py <input.pdf> <output.pdf> [--out results.json]

Exit codes:
  0  success (changed or no-op)
  2  error opening/saving/processing the PDF
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

try:
    import pikepdf
except Exception as exc:  # pragma: no cover - exercised only in bad runtime
    print(json.dumps({"result": "ERROR", "error": f"pikepdf unavailable: {exc}"}))
    sys.exit(2)


def name_is(value: Any, expected: str) -> bool:
    return str(value) == expected


def text_is(value: Any, expected: str) -> bool:
    return str(value) == expected


def int_is(value: Any, expected: int) -> bool:
    try:
        return int(value) == expected
    except Exception:
        return False


def object_key(obj: Any) -> str:
    objgen = getattr(obj, "objgen", None)
    if objgen:
        return f"{objgen[0]} {objgen[1]}"
    return str(id(obj))


def page_boxes(pdf: "pikepdf.Pdf") -> list[dict[str, str]]:
    boxes: list[dict[str, str]] = []
    for page in pdf.pages:
        boxes.append(
            {
                "MediaBox": str(page.obj.get("/MediaBox")),
                "CropBox": str(page.obj.get("/CropBox")) if "/CropBox" in page.obj else "",
            }
        )
    return boxes


def is_identity_cidsysteminfo(font: Any) -> bool:
    csi = font.get("/CIDSystemInfo")
    if csi is None:
        return False
    return (
        text_is(csi.get("/Registry"), "Adobe")
        and text_is(csi.get("/Ordering"), "Identity")
        and int_is(csi.get("/Supplement"), 0)
    )


def embedded_fontfile2_keys(font: Any) -> list[str]:
    descriptor = font.get("/FontDescriptor")
    if descriptor is None:
        return []
    return [key for key in ("/FontFile", "/FontFile2", "/FontFile3") if key in descriptor]


def repair_pdf(input_pdf: Path, output_pdf: Path) -> dict[str, Any]:
    report: dict[str, Any] = {
        "input": str(input_pdf),
        "output": str(output_pdf),
        "result": "NOOP",
        "type0_fonts_inspected": 0,
        "descendant_fonts_inspected": 0,
        "changed_count": 0,
        "changed_fonts": [],
        "skipped_existing_cidtogidmap": 0,
        "skipped_not_type0": 0,
        "skipped_not_cidfonttype2": 0,
        "skipped_missing_descendantfonts": 0,
        "skipped_missing_fontdescriptor": 0,
        "skipped_not_embedded_fontfile2": 0,
        "skipped_non_identity_cidsysteminfo": 0,
        "errors": [],
        "page_count_before": 0,
        "page_count_after": 0,
        "page_boxes_preserved": False,
        "runtime_note": (
            "pikepdf is required under REMEDIATION_PYTHON, which defaults to "
            "/usr/bin/python3 for mapped repair scripts."
        ),
    }

    pdf = pikepdf.open(str(input_pdf))
    before_count = len(pdf.pages)
    before_boxes = page_boxes(pdf)
    report["page_count_before"] = before_count

    processed_descendants: set[str] = set()

    for obj in pdf.objects:
        if obj is None:
            continue
        try:
            if not hasattr(obj, "get"):
                continue
            if not name_is(obj.get("/Type"), "/Font"):
                continue
            if not name_is(obj.get("/Subtype"), "/Type0"):
                report["skipped_not_type0"] += 1
                continue

            report["type0_fonts_inspected"] += 1
            basefont = str(obj.get("/BaseFont"))
            descendants = obj.get("/DescendantFonts")
            if not descendants:
                report["skipped_missing_descendantfonts"] += 1
                continue

            for descendant in descendants:
                key = object_key(descendant)
                if key in processed_descendants:
                    continue
                processed_descendants.add(key)
                report["descendant_fonts_inspected"] += 1

                if not name_is(descendant.get("/Subtype"), "/CIDFontType2"):
                    report["skipped_not_cidfonttype2"] += 1
                    continue

                if "/CIDToGIDMap" in descendant:
                    report["skipped_existing_cidtogidmap"] += 1
                    continue

                if descendant.get("/FontDescriptor") is None:
                    report["skipped_missing_fontdescriptor"] += 1
                    continue

                embedded_keys = embedded_fontfile2_keys(descendant)
                if embedded_keys != ["/FontFile2"]:
                    report["skipped_not_embedded_fontfile2"] += 1
                    continue

                if not is_identity_cidsysteminfo(descendant):
                    report["skipped_non_identity_cidsysteminfo"] += 1
                    continue

                descendant["/CIDToGIDMap"] = pikepdf.Name("/Identity")
                report["changed_count"] += 1
                report["changed_fonts"].append(
                    {
                        "parent_basefont": basefont,
                        "descendant_basefont": str(descendant.get("/BaseFont")),
                        "descendant_object": key,
                        "cidtogidmap": "/Identity",
                    }
                )
        except Exception as exc:
            report["errors"].append({"object": object_key(obj), "error": str(exc)})

    output_pdf.parent.mkdir(parents=True, exist_ok=True)
    pdf.save(str(output_pdf))
    pdf.close()

    with pikepdf.open(str(output_pdf)) as after_pdf:
        report["page_count_after"] = len(after_pdf.pages)
        report["page_boxes_preserved"] = (
            report["page_count_before"] == report["page_count_after"]
            and before_boxes == page_boxes(after_pdf)
        )

    if report["errors"]:
        report["result"] = "PARTIAL" if report["changed_count"] else "ERROR"
    elif report["changed_count"]:
        report["result"] = "FIXED"
    else:
        report["result"] = "ALREADY_CORRECT"

    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("input_pdf")
    parser.add_argument("output_pdf")
    parser.add_argument("--out", default=None, help="Write JSON result to this file")
    args = parser.parse_args()

    try:
        report = repair_pdf(Path(args.input_pdf), Path(args.output_pdf))
        output = json.dumps(report, indent=2)
        print(output)
        if args.out:
            Path(args.out).write_text(output)
        return 0 if report["result"] in {"FIXED", "ALREADY_CORRECT"} else 2
    except Exception as exc:
        report = {"result": "ERROR", "error": str(exc), "input": args.input_pdf, "output": args.output_pdf}
        output = json.dumps(report, indent=2)
        print(output)
        if args.out:
            Path(args.out).write_text(output)
        return 2


if __name__ == "__main__":
    sys.exit(main())
