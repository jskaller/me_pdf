#!/usr/bin/env python3
"""Focused tests for missing-XMP repair behavior.

Patch D coverage: PDFs with no existing XMP packet must not leave Info metadata
updated while XMP remains empty. The repair helpers should initialize a minimal
XMP packet before inserting PDF/UA identifier and metadata parity fields.
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
REPAIR_DIR = TOOLS_DIR / "repair"
AUDIT_DIR = TOOLS_DIR / "audit"

HAS_FITZ = importlib.util.find_spec("fitz") is not None
HAS_PIKEPDF = importlib.util.find_spec("pikepdf") is not None


def make_minimal_pdf(path: Path) -> None:
    import fitz

    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), "WebUI E2E Smoke Test PDF")
    doc.save(path)
    doc.close()


def read_xmp(path: Path) -> str:
    import fitz

    doc = fitz.open(path)
    try:
        return doc.get_xml_metadata() or ""
    finally:
        doc.close()


@unittest.skipUnless(HAS_FITZ, "PyMuPDF/fitz is required for PDF fixture tests")
class XMPInitializationRepairTests(unittest.TestCase):
    def run_script(self, script: Path, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(script), *map(str, args)],
            capture_output=True,
            text=True,
            env={**os.environ, "PYTHONPATH": str(APP_DIR)},
        )

    def test_pdfua_identifier_initializes_empty_xmp_packet(self) -> None:
        with tempfile.TemporaryDirectory(prefix="xmp_identifier_") as td:
            td_path = Path(td)
            src = td_path / "source.pdf"
            out = td_path / "identifier.pdf"
            result_json = td_path / "identifier.json"
            make_minimal_pdf(src)

            before = read_xmp(src)
            self.assertEqual(before, "")

            result = self.run_script(
                REPAIR_DIR / "fix_pdfua_identifier.py",
                src,
                out,
                "--out",
                result_json,
            )
            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
            payload = json.loads(result_json.read_text())
            self.assertEqual(payload["result"], "FIXED")

            xmp = read_xmp(out)
            self.assertIn('xmlns:pdfuaid="http://www.aiim.org/pdfua/ns/id/"', xmp)
            self.assertIn("<pdfuaid:part>1</pdfuaid:part>", xmp)
            self.assertIn("<pdfuaid:amd>2005</pdfuaid:amd>", xmp)

    @unittest.skipUnless(HAS_PIKEPDF, "pikepdf is required for metadata repair catalog updates")
    def test_metadata_repair_initializes_xmp_and_passes_metadata_audit(self) -> None:
        with tempfile.TemporaryDirectory(prefix="xmp_metadata_") as td:
            td_path = Path(td)
            src = td_path / "source.pdf"
            out = td_path / "metadata.pdf"
            repair_json = td_path / "metadata_repair.json"
            audit_json = td_path / "metadata_audit.json"
            make_minimal_pdf(src)

            self.assertEqual(read_xmp(src), "")

            repair = self.run_script(
                REPAIR_DIR / "fix_metadata_xmp_parity.py",
                src,
                out,
                "--title",
                "WebUI E2E Smoke Test PDF",
                "--subject",
                "End-to-end smoke test report for the WebUI.",
                "--keywords",
                "webui, e2e, smoke test, pdf, automation, testing",
                "--language",
                "en-US",
                "--out",
                repair_json,
            )
            self.assertEqual(repair.returncode, 0, repair.stderr + repair.stdout)

            xmp = read_xmp(out)
            self.assertIn("<dc:title>", xmp)
            self.assertIn("WebUI E2E Smoke Test PDF", xmp)
            self.assertIn("<dc:creator>", xmp)
            self.assertIn("Montefiore Einstein", xmp)
            self.assertIn("<pdfuaid:part>1</pdfuaid:part>", xmp)

            audit = self.run_script(
                AUDIT_DIR / "metadata_xmp_parity_audit.py",
                out,
                "--out",
                audit_json,
            )
            self.assertEqual(audit.returncode, 0, audit.stderr + audit.stdout)
            audit_payload = json.loads(audit_json.read_text())
            self.assertEqual(audit_payload["result"], "PASS")


if __name__ == "__main__":
    unittest.main()
