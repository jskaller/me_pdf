#!/usr/bin/env python3
"""Policy tests for H10A-V veraPDF profile accounting."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from tools.audit.verapdf_profile_accounting import (
    EXPERIMENTAL_DIAGNOSTIC,
    INFORMATIONAL,
    PROHIBITED_FOR_PDFUA1,
    REQUIRED_AUTHORITATIVE,
    SKIPPED_BY_POLICY,
    TERMINAL_DELTA_FAILED,
    TERMINAL_DELTA_VALIDATED,
    TERMINAL_PROFILE_ACCOUNTING_FAILED,
    account_profiles,
    build_delta,
    classify_profile,
)


def _write_xml(path: Path, *, failed: int = 0, passed: int = 1, clause: str = "7.18.4", spec: str = "ISO 14289-1:2014") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    compliant = "true" if failed == 0 else "false"
    path.write_text(
        f'''<?xml version="1.0" encoding="UTF-8"?>
<report><jobs><job><validationReport isCompliant="{compliant}"><details>
<rule specification="{spec}" clause="{clause}" failedChecks="{failed}" passedChecks="{passed}" description="synthetic"/>
</details></validationReport></job></jobs></report>
'''
    )


def _write_parsed(path: Path, failures: dict[str, int]) -> None:
    items = [
        {"rule_id": rule_id, "failures": count, "sources": ["synthetic.xml"]}
        for rule_id, count in failures.items()
    ]
    path.write_text(json.dumps({"result": "FAIL" if items else "PASS", "failures_by_rule": items}))


class VeraPDFProfileClassificationTests(unittest.TestCase):
    def test_pdfua1_required_profile_is_authoritative(self) -> None:
        self.assertEqual(classify_profile("PDF_UA/PDFUA-1.xml"), REQUIRED_AUTHORITATIVE)

    def test_pinned_wcag_machine_profile_is_required_authoritative(self) -> None:
        self.assertEqual(classify_profile("PDF_UA/WCAG-2-2-Machine.xml"), REQUIRED_AUTHORITATIVE)

    def test_pdf20_wcag_machine_profile_is_prohibited_for_pdfua1(self) -> None:
        self.assertEqual(classify_profile("PDF_UA/WCAG-2-2-Machine-PDF20.xml"), PROHIBITED_FOR_PDFUA1)

    def test_pdfua2_profile_is_skipped_unless_explicitly_requested(self) -> None:
        self.assertEqual(classify_profile("PDF_UA/PDFUA-2.xml"), SKIPPED_BY_POLICY)

    def test_iso_profile_is_informational(self) -> None:
        self.assertEqual(classify_profile("PDF_UA/ISO-32000-1-Tagged.xml"), INFORMATIONAL)

    def test_experimental_custom_profile_is_diagnostic_by_default(self) -> None:
        self.assertEqual(classify_profile("Custom/MM-17179-Experimental.xml"), EXPERIMENTAL_DIAGNOSTIC)


class VeraPDFProfileAccountingTests(unittest.TestCase):
    def test_profile_accounting_records_paths_hash_outputs_and_counts(self) -> None:
        with tempfile.TemporaryDirectory(prefix="h10av_accounting_") as td:
            root = Path(td) / "profiles"
            run = Path(td) / "run"
            (root / "PDF_UA").mkdir(parents=True)
            run.mkdir()
            for profile in ["PDFUA-1.xml", "WCAG-2-2-Machine.xml", "ISO-32000-1-Tagged.xml", "WCAG-2-2-Machine-PDF20.xml"]:
                (root / "PDF_UA" / profile).write_text(f"<profile>{profile}</profile>\n")
            (root / "Custom").mkdir()
            (root / "Custom" / "Experimental.xml").write_text("<profile>experimental</profile>\n")
            _write_xml(run / "verapdf_pdfua_ua1.xml", failed=1, passed=4)
            _write_xml(run / "verapdf_wcag_2_2_machine.xml", failed=0, passed=5, clause="1.1.1", spec="WCAG 2.2")
            _write_xml(run / "verapdf_iso_32000_1_tagged.xml", failed=0, passed=3, clause="14.8", spec="ISO 32000-1")

            accounting = account_profiles(root, run, verapdf_bin=Path("/opt/verapdf-greenfield/verapdf"))
            records = {r["profile_id"]: r for r in accounting["profiles"]}

            pdfua = records["PDF_UA/PDFUA-1.xml"]
            self.assertTrue(pdfua["profile_sha256"])
            self.assertTrue(pdfua["was_run"])
            self.assertEqual(pdfua["output_xml"], str(run / "verapdf_pdfua_ua1.xml"))
            self.assertEqual(pdfua["result"], "FAIL")
            self.assertEqual(pdfua["failed_rules"], 1)
            self.assertEqual(pdfua["failed_checks"], 1)
            self.assertIn("--profile", pdfua["command"])
            self.assertEqual(records["PDF_UA/ISO-32000-1-Tagged.xml"]["classification"], INFORMATIONAL)
            self.assertEqual(records["PDF_UA/WCAG-2-2-Machine-PDF20.xml"]["classification"], PROHIBITED_FOR_PDFUA1)
            self.assertEqual(records["Custom/Experimental.xml"]["classification"], EXPERIMENTAL_DIAGNOSTIC)
            self.assertFalse(records["Custom/Experimental.xml"]["verdict_authoritative"])

    def test_missing_required_profile_blocks_profile_accounting(self) -> None:
        with tempfile.TemporaryDirectory(prefix="h10av_missing_") as td:
            root = Path(td) / "profiles"
            before = Path(td) / "before"
            after = Path(td) / "after"
            root.mkdir(); before.mkdir(); after.mkdir()
            _write_parsed(before / "parsed.json", {"PDF/UA-1/7.18.4": 2})
            _write_parsed(after / "parsed.json", {})

            delta = build_delta(root, before, after, before / "parsed.json", after / "parsed.json", "PDF/UA-1/7.18.4")
            self.assertEqual(delta["terminal_state"], TERMINAL_PROFILE_ACCOUNTING_FAILED)
            self.assertIn("PDF_UA/PDFUA-1.xml", delta["required_profiles_missing"])
            self.assertTrue(delta["accounting_blockers"])

    def test_verapdf_summary_alone_is_insufficient_for_compliance_verdict(self) -> None:
        with tempfile.TemporaryDirectory(prefix="h10av_summary_only_") as td:
            root = Path(td) / "profiles"
            before = Path(td) / "before"
            after = Path(td) / "after"
            (root / "PDF_UA").mkdir(parents=True); before.mkdir(); after.mkdir()
            for profile in ["PDFUA-1.xml", "WCAG-2-2-Machine.xml"]:
                (root / "PDF_UA" / profile).write_text("<profile/>\n")
            (before / "verapdf_summary.json").write_text('{"result":"PASS"}')
            (after / "verapdf_summary.json").write_text('{"result":"PASS"}')
            _write_parsed(before / "parsed.json", {"PDF/UA-1/7.18.4": 1})
            _write_parsed(after / "parsed.json", {})

            delta = build_delta(root, before, after, before / "parsed.json", after / "parsed.json", "PDF/UA-1/7.18.4")
            self.assertEqual(delta["terminal_state"], TERMINAL_PROFILE_ACCOUNTING_FAILED)
            self.assertTrue(any("not run" in blocker for blocker in delta["accounting_blockers"]))

    def test_delta_validated_only_when_target_improves_without_authoritative_regression(self) -> None:
        with tempfile.TemporaryDirectory(prefix="h10av_delta_") as td:
            root = Path(td) / "profiles"
            before = Path(td) / "before"
            after = Path(td) / "after"
            (root / "PDF_UA").mkdir(parents=True); before.mkdir(); after.mkdir()
            for profile in ["PDFUA-1.xml", "WCAG-2-2-Machine.xml"]:
                (root / "PDF_UA" / profile).write_text("<profile/>\n")
            _write_xml(before / "verapdf_pdfua_ua1.xml", failed=2)
            _write_xml(before / "verapdf_wcag_2_2_machine.xml", failed=0, clause="1.1.1", spec="WCAG 2.2")
            _write_xml(after / "verapdf_pdfua_ua1.xml", failed=0)
            _write_xml(after / "verapdf_wcag_2_2_machine.xml", failed=0, clause="1.1.1", spec="WCAG 2.2")
            _write_parsed(before / "parsed.json", {"PDF/UA-1/7.18.4": 2})
            _write_parsed(after / "parsed.json", {})

            delta = build_delta(root, before, after, before / "parsed.json", after / "parsed.json", "PDF/UA-1/7.18.4")
            self.assertEqual(delta["terminal_state"], TERMINAL_DELTA_VALIDATED)
            self.assertEqual(delta["target_rule_status"], "CLEARED")
            self.assertFalse(delta["experimental_profile_failures_authoritative"])

    def test_delta_failed_when_new_authoritative_rule_is_introduced(self) -> None:
        with tempfile.TemporaryDirectory(prefix="h10av_regression_") as td:
            root = Path(td) / "profiles"
            before = Path(td) / "before"
            after = Path(td) / "after"
            (root / "PDF_UA").mkdir(parents=True); before.mkdir(); after.mkdir()
            for profile in ["PDFUA-1.xml", "WCAG-2-2-Machine.xml"]:
                (root / "PDF_UA" / profile).write_text("<profile/>\n")
            _write_xml(before / "verapdf_pdfua_ua1.xml", failed=1)
            _write_xml(before / "verapdf_wcag_2_2_machine.xml", failed=0, clause="1.1.1", spec="WCAG 2.2")
            _write_xml(after / "verapdf_pdfua_ua1.xml", failed=0)
            _write_xml(after / "verapdf_wcag_2_2_machine.xml", failed=1, clause="1.1.1", spec="WCAG 2.2")
            _write_parsed(before / "parsed.json", {"PDF/UA-1/7.18.4": 1})
            _write_parsed(after / "parsed.json", {"WCAG-2-2-Machine/1.1.1": 1})

            delta = build_delta(root, before, after, before / "parsed.json", after / "parsed.json", "PDF/UA-1/7.18.4")
            self.assertEqual(delta["terminal_state"], TERMINAL_DELTA_FAILED)
            self.assertIn("WCAG-2-2-Machine/1.1.1", delta["new_rule_ids"])


if __name__ == "__main__":
    unittest.main()
