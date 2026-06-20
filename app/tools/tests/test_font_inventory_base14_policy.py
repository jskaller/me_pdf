#!/usr/bin/env python3
"""Policy tests for Base-14 font embedding detection in font_inventory.py.

veraPDF PDF/UA-1 clause 7.21.4.1 fails Base-14 Helvetica when the PDF font
has no embedded font program. PyMuPDF reports these fonts with extension "n/a";
that value must be treated as not embedded, not as a real embedded font file.
"""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

TEST_FILE = Path(__file__).resolve()
TOOLS_DIR = TEST_FILE.parents[1]
APP_DIR = TOOLS_DIR.parent
AUDIT_DIR = TOOLS_DIR / "audit"

HAS_FITZ = importlib.util.find_spec("fitz") is not None


def make_base14_helvetica_pdf(path: Path) -> None:
    import fitz

    doc = fitz.open()
    page = doc.new_page()
    # PyMuPDF's default inserted text uses Base-14 Helvetica and reports the
    # font extension as "n/a" because no font program is embedded.
    page.insert_text((72, 72), "Base-14 Helvetica should not count as embedded")
    doc.save(path)
    doc.close()


@unittest.skipUnless(HAS_FITZ, "PyMuPDF/fitz is required for font inventory tests")
class FontInventoryBase14PolicyTests(unittest.TestCase):
    def test_base14_helvetica_extension_na_is_not_embedded(self) -> None:
        with tempfile.TemporaryDirectory(prefix="font_inventory_base14_") as td:
            root = Path(td)
            pdf = root / "base14.pdf"
            out_json = root / "inventory.json"
            make_base14_helvetica_pdf(pdf)

            proc = subprocess.run(
                [
                    sys.executable,
                    str(AUDIT_DIR / "font_inventory.py"),
                    str(pdf),
                    "--out",
                    str(out_json),
                ],
                capture_output=True,
                text=True,
                env={**os.environ, "PYTHONPATH": str(APP_DIR)},
            )

            self.assertEqual(proc.returncode, 1, proc.stderr + proc.stdout)
            payload = json.loads(out_json.read_text())
            self.assertEqual(payload["result"], "FAIL")
            self.assertEqual(payload["font_count"], 1)
            font = payload["fonts"][0]
            self.assertEqual(font["basefont"], "Helvetica")
            self.assertEqual(str(font["extension"]).lower(), "n/a")
            self.assertFalse(font["embedded"])
            self.assertIn(
                {"name": font["name"], "page": 1, "issue": "not embedded"},
                payload["issues"],
            )


if __name__ == "__main__":
    unittest.main()
