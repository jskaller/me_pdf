#!/usr/bin/env python3
"""Policy tests for the PDF/UA-1 7.21.3.2 CIDToGIDMap repair.

Patch G is intentionally narrow. The repair may add /CIDToGIDMap /Identity
only for embedded Adobe-Identity-0 Type 2 CIDFont descendants that are missing
the key. It must not overwrite existing maps or touch unsafe font structures.
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
SCRIPT = TOOLS_DIR / "repair" / "fix_cidtogidmap_identity.py"
RULE_ID = "PDF/UA-1/7.21.3.2"
HAS_PIKEPDF = importlib.util.find_spec("pikepdf") is not None

if HAS_PIKEPDF:
    import pikepdf


def minimal_verapdf_summary(rule_id: str = RULE_ID) -> dict:
    return {
        "result": "FAIL",
        "total_failures": 1,
        "failures_by_rule": [
            {
                "rule_id": rule_id,
                "description": "Embedded Type 2 CIDFont missing CIDToGIDMap entry",
                "failures": 1,
                "objects": [
                    {
                        "context": "PDCIDFont",
                        "font": "ArialUnicodeMS",
                    }
                ],
            }
        ],
    }


@unittest.skipUnless(HAS_PIKEPDF, "pikepdf is required for CIDToGIDMap repair tests")
class CIDToGIDMapIdentityRepairPolicyTests(unittest.TestCase):
    def make_pdf(
        self,
        path: Path,
        *,
        cidfont_subtype: str = "/CIDFontType2",
        embedded_key: str | None = "/FontFile2",
        cidsystem_ordering: str = "Identity",
        existing_cidtogidmap: str | None = None,
    ) -> None:
        pdf = pikepdf.Pdf.new()
        page = pdf.add_blank_page(page_size=(200, 300))

        descriptor = pikepdf.Dictionary(
            {
                "/Type": pikepdf.Name("/FontDescriptor"),
                "/FontName": pikepdf.Name("/ArialUnicodeMS"),
                "/Flags": 4,
                "/Ascent": 1000,
                "/Descent": -200,
                "/CapHeight": 700,
                "/ItalicAngle": 0,
                "/StemV": 80,
                "/FontBBox": pikepdf.Array([0, -200, 1000, 1000]),
            }
        )
        if embedded_key is not None:
            descriptor[embedded_key] = pdf.make_stream(b"minimal test font program bytes")
        descriptor = pdf.make_indirect(descriptor)

        descendant = pikepdf.Dictionary(
            {
                "/Type": pikepdf.Name("/Font"),
                "/Subtype": pikepdf.Name(cidfont_subtype),
                "/BaseFont": pikepdf.Name("/ArialUnicodeMS"),
                "/CIDSystemInfo": pikepdf.Dictionary(
                    {
                        "/Registry": "Adobe",
                        "/Ordering": cidsystem_ordering,
                        "/Supplement": 0,
                    }
                ),
                "/FontDescriptor": descriptor,
            }
        )
        if existing_cidtogidmap == "stream":
            descendant["/CIDToGIDMap"] = pdf.make_stream(b"existing map")
        elif existing_cidtogidmap == "identity":
            descendant["/CIDToGIDMap"] = pikepdf.Name("/Identity")
        descendant = pdf.make_indirect(descendant)

        type0 = pdf.make_indirect(
            pikepdf.Dictionary(
                {
                    "/Type": pikepdf.Name("/Font"),
                    "/Subtype": pikepdf.Name("/Type0"),
                    "/BaseFont": pikepdf.Name("/ArialUnicodeMS"),
                    "/Encoding": pikepdf.Name("/Identity-H"),
                    "/DescendantFonts": pikepdf.Array([descendant]),
                }
            )
        )
        page.obj["/Resources"] = pikepdf.Dictionary({"/Font": pikepdf.Dictionary({"/F1": type0})})
        pdf.save(path)
        pdf.close()

    def run_script(self, input_pdf: Path, output_pdf: Path, report_json: Path) -> dict:
        proc = subprocess.run(
            [sys.executable, str(SCRIPT), str(input_pdf), str(output_pdf), "--out", str(report_json)],
            capture_output=True,
            text=True,
            env={**os.environ, "PYTHONPATH": str(APP_DIR)},
        )
        self.assertEqual(proc.returncode, 0, proc.stderr + proc.stdout)
        self.assertTrue(output_pdf.is_file())
        self.assertTrue(report_json.is_file())
        return json.loads(report_json.read_text())

    def descendant_font(self, path: Path):
        pdf = pikepdf.open(path)
        try:
            page = pdf.pages[0]
            font = page.obj["/Resources"]["/Font"]["/F1"]
            descendant = font["/DescendantFonts"][0]
            return pdf, descendant
        except Exception:
            pdf.close()
            raise

    def test_adds_identity_for_embedded_adobe_identity_cidfonttype2_missing_map(self) -> None:
        with tempfile.TemporaryDirectory(prefix="cidtogidmap_add_") as td:
            root = Path(td)
            src = root / "input.pdf"
            dst = root / "output.pdf"
            report_path = root / "report.json"
            self.make_pdf(src)

            report = self.run_script(src, dst, report_path)

            self.assertEqual(report["result"], "FIXED")
            self.assertEqual(report["changed_count"], 1)
            self.assertEqual(report["page_count_before"], 1)
            self.assertEqual(report["page_count_after"], 1)
            self.assertTrue(report["page_boxes_preserved"])

            pdf, descendant = self.descendant_font(dst)
            try:
                self.assertEqual(str(descendant["/CIDToGIDMap"]), "/Identity")
            finally:
                pdf.close()

    def test_does_not_overwrite_existing_cidtogidmap_stream(self) -> None:
        with tempfile.TemporaryDirectory(prefix="cidtogidmap_existing_") as td:
            root = Path(td)
            src = root / "input.pdf"
            dst = root / "output.pdf"
            report_path = root / "report.json"
            self.make_pdf(src, existing_cidtogidmap="stream")

            report = self.run_script(src, dst, report_path)

            self.assertEqual(report["result"], "ALREADY_CORRECT")
            self.assertEqual(report["changed_count"], 0)
            self.assertEqual(report["skipped_existing_cidtogidmap"], 1)

            pdf, descendant = self.descendant_font(dst)
            try:
                self.assertIn("/CIDToGIDMap", descendant)
                self.assertNotEqual(str(descendant["/CIDToGIDMap"]), "/Identity")
            finally:
                pdf.close()

    def test_does_not_modify_non_embedded_cidfonttype2(self) -> None:
        with tempfile.TemporaryDirectory(prefix="cidtogidmap_nonembedded_") as td:
            root = Path(td)
            src = root / "input.pdf"
            dst = root / "output.pdf"
            report_path = root / "report.json"
            self.make_pdf(src, embedded_key=None)

            report = self.run_script(src, dst, report_path)

            self.assertEqual(report["result"], "ALREADY_CORRECT")
            self.assertEqual(report["changed_count"], 0)
            self.assertEqual(report["skipped_not_embedded_fontfile2"], 1)

            pdf, descendant = self.descendant_font(dst)
            try:
                self.assertNotIn("/CIDToGIDMap", descendant)
            finally:
                pdf.close()

    def test_does_not_modify_non_cidfonttype2(self) -> None:
        with tempfile.TemporaryDirectory(prefix="cidtogidmap_type0_") as td:
            root = Path(td)
            src = root / "input.pdf"
            dst = root / "output.pdf"
            report_path = root / "report.json"
            self.make_pdf(src, cidfont_subtype="/CIDFontType0")

            report = self.run_script(src, dst, report_path)

            self.assertEqual(report["result"], "ALREADY_CORRECT")
            self.assertEqual(report["changed_count"], 0)
            self.assertEqual(report["skipped_not_cidfonttype2"], 1)

            pdf, descendant = self.descendant_font(dst)
            try:
                self.assertNotIn("/CIDToGIDMap", descendant)
            finally:
                pdf.close()

    def test_does_not_modify_non_identity_cidsysteminfo(self) -> None:
        with tempfile.TemporaryDirectory(prefix="cidtogidmap_nonidentity_") as td:
            root = Path(td)
            src = root / "input.pdf"
            dst = root / "output.pdf"
            report_path = root / "report.json"
            self.make_pdf(src, cidsystem_ordering="Japan1")

            report = self.run_script(src, dst, report_path)

            self.assertEqual(report["result"], "ALREADY_CORRECT")
            self.assertEqual(report["changed_count"], 0)
            self.assertEqual(report["skipped_non_identity_cidsysteminfo"], 1)

    def test_rule_map_strategy_shape_produces_plan_ready_when_wired(self) -> None:
        with tempfile.TemporaryDirectory(prefix="cidtogidmap_plan_") as td:
            root = Path(td)
            summary_path = root / "summary.json"
            map_path = root / "rule_repair_map.json"
            summary_path.write_text(json.dumps(minimal_verapdf_summary(), indent=2))
            map_path.write_text(
                json.dumps(
                    {
                        "rules": {
                            RULE_ID: {
                                "clause": "7.21.3.2",
                                "description": "Embedded Type 2 CIDFont missing CIDToGIDMap entry in CIDFont dictionary",
                                "manual": False,
                                "strategies": [
                                    {
                                        "strategy": "fix_cidtogidmap_identity",
                                        "repair_script": "tools/repair/fix_cidtogidmap_identity.py",
                                        "repair_order": 9,
                                        "run_last": False,
                                        "args_pattern": "<input.pdf> <output.pdf> [--out results.json]",
                                        "pass_count": 0,
                                        "fail_count": 0,
                                        "pass_rate": 0.0,
                                        "doc_type_stats": [],
                                        "known_failure_modes": [],
                                        "confidence": "EXPECTED",
                                    }
                                ],
                                "resolvability": "repairable_review",
                                "emits_review_artifact": True,
                            }
                        }
                    },
                    indent=2,
                )
            )

            proc = subprocess.run(
                [sys.executable, str(AUDIT_DIR / "lookup_repair_plan.py"), str(summary_path), "--map", str(map_path)],
                capture_output=True,
                text=True,
                env={**os.environ, "PYTHONPATH": str(APP_DIR)},
            )
            self.assertEqual(proc.returncode, 0, proc.stderr + proc.stdout)
            plan = json.loads(proc.stdout)

            self.assertEqual(plan["result"], "PLAN_READY")
            self.assertEqual(plan["hermes_required"], [])
            self.assertEqual(plan["repair_steps"][0]["repair_script"], "tools/repair/fix_cidtogidmap_identity.py")
            self.assertEqual(plan["repair_steps"][0]["rules_addressed"], [RULE_ID])


if __name__ == "__main__":
    unittest.main()
