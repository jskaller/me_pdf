#!/usr/bin/env python3
"""Generate deterministic H12R synthetic unsupported-but-remediable fixtures.

The fixtures are real parseable PDFs so they can pass through Open WebUI upload
processing.  They also preserve plain-text H12R markers used by the controlled
H12R validator.
"""

from __future__ import annotations

from pathlib import Path
from typing import Dict

TARGET_RULE = "PDF/UA-1/7.21.7"
FAIL_MARKER_TEMPLATE = "H12R_TARGET_FAIL: {target_rule}"


def _make_fixture(path: Path, fixture: str, object_seed: int, visible_text: str) -> None:
    try:
        import fitz
    except Exception as exc:  # pragma: no cover - environment failure guard
        raise RuntimeError("H12R fixture generation requires PyMuPDF/fitz") from exc

    marker = FAIL_MARKER_TEMPLATE.format(target_rule=TARGET_RULE)
    doc = fitz.open()
    page = doc.new_page(width=612, height=792)
    page.insert_text((72, 72), "H12R synthetic valid PDF fixture", fontsize=12)
    page.insert_text((72, 96), f"fixture={fixture}", fontsize=10)
    page.insert_text((72, 120), f"object-seed={object_seed}", fontsize=10)
    page.insert_text((72, 144), visible_text, fontsize=10)
    page.insert_text((72, 168), marker, fontsize=10)
    doc.set_metadata(
        {
            "title": f"H12R Fixture {fixture}",
            "subject": "Synthetic unsupported-but-remediable PDF/UA marker fixture",
            "keywords": f"H12R, fixture={fixture}, object-seed={object_seed}, {marker}",
            "creator": "H12R fixture generator",
            "producer": "H12R fixture generator",
        }
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    doc.save(str(path), garbage=0, deflate=False, clean=False)
    doc.close()

    data = path.read_text(errors="ignore")
    required = [f"fixture={fixture}", f"object-seed={object_seed}", marker]
    missing = [item for item in required if item not in data]
    if missing:
        raise RuntimeError(f"generated fixture is missing controlled markers: {missing}")


def generate_fixture_pair(output_dir: Path) -> Dict[str, str]:
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    a = output_dir / "h12r_fixture_a_missing_tounicode.pdf"
    b = output_dir / "h12r_fixture_b_missing_tounicode_distinct.pdf"
    _make_fixture(a, "A", 1201, "Alpha synthetic ToUnicode sample")
    _make_fixture(b, "B", 2209, "Beta synthetic ToUnicode sample with different object ids")
    return {"fixture_a": str(a), "fixture_b": str(b), "target_rule": TARGET_RULE}


if __name__ == "__main__":
    import argparse
    import json

    parser = argparse.ArgumentParser()
    parser.add_argument("output_dir")
    args = parser.parse_args()
    print(json.dumps(generate_fixture_pair(Path(args.output_dir)), indent=2, sort_keys=True))
