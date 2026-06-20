#!/usr/bin/env python3
"""Generate the local WebUI E2E smoke PDF with an embedded open font.

This script intentionally creates a small, non-private fixture for the manual
Open WebUI -> Hermes -> orchestrator smoke procedure. It does not implement or
claim any production repair for arbitrary PDFs with unembedded fonts.

The generated PDF is a local workspace input artifact. Do not commit it.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Iterable

try:
    import fitz
except Exception as exc:  # pragma: no cover - exercised only when dependency is absent
    print(json.dumps({"result": "ERROR", "error": f"PyMuPDF unavailable: {exc}"}, indent=2))
    sys.exit(2)

DEFAULT_OUTPUT = Path("workspace/input/WEBUI-E2E-001/e2e-smoke.pdf")
PREFERRED_FONT_NAMES = (
    "Arimo-Regular.ttf",
    "LiberationSans-Regular.ttf",
    "NotoSans-Regular.ttf",
    "OpenSans-Regular.ttf",
    "Roboto-Regular.ttf",
    "DejaVuSans.ttf",
    "FreeSans.ttf",
)
FONT_SEARCH_ROOTS = (
    Path("/usr/share/fonts"),
    Path("/usr/local/share/fonts"),
    Path("/Library/Fonts"),
    Path("/System/Library/Fonts"),
    Path.home() / "Library/Fonts",
)
FONT_EXTENSIONS = {".ttf", ".otf"}


def iter_font_files(root: Path) -> Iterable[Path]:
    if not root.exists():
        return []
    return (path for path in root.rglob("*") if path.is_file() and path.suffix.lower() in FONT_EXTENSIONS)


def discover_font(explicit: str | None = None) -> Path:
    if explicit:
        candidate = Path(explicit).expanduser()
        if not candidate.is_file():
            raise FileNotFoundError(f"explicit font file not found: {candidate}")
        return candidate

    all_fonts: list[Path] = []
    for root in FONT_SEARCH_ROOTS:
        all_fonts.extend(iter_font_files(root))

    by_name = {font.name: font for font in all_fonts}
    for preferred in PREFERRED_FONT_NAMES:
        if preferred in by_name:
            return by_name[preferred]

    if all_fonts:
        return sorted(all_fonts, key=lambda p: str(p).lower())[0]

    raise FileNotFoundError(
        "no usable .ttf or .otf font file found under common system font directories"
    )


def generate_pdf(output: Path, font_path: Path) -> dict:
    output.parent.mkdir(parents=True, exist_ok=True)

    doc = fitz.open()
    page = doc.new_page(width=612, height=792)
    fontname = "WebUIE2ESmokeFont"
    page.insert_font(fontname=fontname, fontfile=str(font_path))

    text = (
        "Montefiore PDF/UA WebUI E2E smoke fixture\n"
        "This local test PDF uses an embedded open font.\n"
        "It exercises the WebUI to Hermes to orchestrator path without relying on Base-14 Helvetica."
    )
    page.insert_textbox(
        fitz.Rect(72, 72, 540, 220),
        text,
        fontname=fontname,
        fontsize=16,
        lineheight=1.25,
    )

    doc.set_metadata(
        {
            "title": "WebUI E2E Smoke Fixture",
            "author": "Montefiore Einstein",
            "subject": "Embedded-font smoke fixture for WebUI PDF remediation E2E verification",
            "keywords": "PDF/UA, WebUI, Hermes, smoke fixture, embedded font",
            "creator": "Montefiore Einstein",
            "producer": "Montefiore Einstein",
        }
    )
    doc.save(output, garbage=4, deflate=True)
    doc.close()

    verify_doc = fitz.open(output)
    fonts = []
    for page_index, verify_page in enumerate(verify_doc):
        for font in verify_page.get_fonts(full=True):
            xref, ext, font_type, basefont, resource_name, encoding, referencer = font
            fonts.append(
                {
                    "page": page_index + 1,
                    "xref": xref,
                    "extension": ext,
                    "type": font_type,
                    "basefont": basefont,
                    "resource_name": resource_name,
                    "encoding": encoding,
                }
            )
    verify_doc.close()

    return {
        "result": "PASS",
        "output": str(output),
        "font_file": str(font_path),
        "fonts_seen_by_pymupdf": fonts,
        "font_inventory_command": (
            "PYTHONPATH=app python3 app/tools/audit/font_inventory.py "
            f"{output} --out /tmp/e2e-smoke-font-inventory.json"
        ),
        "webui_prompt_starts_with": "PDF:",
        "note": "Generated workspace PDF is local test input only; do not commit it.",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--out",
        default=str(DEFAULT_OUTPUT),
        help="Output PDF path. Default: workspace/input/WEBUI-E2E-001/e2e-smoke.pdf",
    )
    parser.add_argument(
        "--font",
        default=None,
        help="Optional explicit .ttf/.otf font file. If omitted, common open-font directories are searched.",
    )
    args = parser.parse_args()

    try:
        font_path = discover_font(args.font)
        payload = generate_pdf(Path(args.out), font_path)
    except Exception as exc:
        print(json.dumps({"result": "ERROR", "error": str(exc)}, indent=2))
        return 2

    print(json.dumps(payload, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
