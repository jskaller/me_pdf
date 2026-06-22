#!/usr/bin/env python3
"""Policy tests for H10C ISO regression review helper."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from tools.audit.verapdf_iso_regression_review import (
    BENIGN_INFORMATIONAL,
    INCONCLUSIVE,
    PROFILE_ACCOUNTING_ARTIFACT,
    STRUCTURAL_SIDE_EFFECT,
    build_review,
)


def _write_iso_xml(path: Path, *, compliant: bool, failed_rules: list[dict] | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    failed_rules = failed_rules or []
    rules = []
    for item in failed_rules:
        contexts = "".join(f'<check object="{ctx}" />' for ctx in item.get("contexts", []))
        rules.append(
            f'<rule specification="{item.get("specification", "ISO 32000-1")}" '
            f'clause="{item.get("clause", "14.8")}" '
            f'failedChecks="{item.get("failed_checks", 1)}" '
            f'passedChecks="{item.get("passed_checks", 0)}" '
            f'description="{item.get("description", "synthetic")}">{contexts}</rule>'
        )
    path.write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<report><jobs><job>'
        f'<validationReport isCompliant="{str(compliant).lower()}"><details>'
        + "".join(rules)
        + '</details></validationReport></job></jobs></report>\n'
    )


def _write_accounting(path: Path, *, result: str, classification: str = "informational", authoritative: bool = False) -> None:
    path.write_text(
        json.dumps(
            {
                "profiles": [
                    {
                        "profile_id": "PDF_UA/ISO-32000-1-Tagged.xml",
                        "classification": classification,
                        "verdict_authoritative": authoritative,
                        "result": result,
                    }
                ]
            }
        )
    )


class ISORegressionReviewTests(unittest.TestCase):
    def test_pass_to_fail_with_struct_parent_context_is_structural_side_effect(self) -> None:
        with tempfile.TemporaryDirectory(prefix="h10c_iso_") as td:
            root = Path(td)
            before = root / "before.xml"
            after = root / "after.xml"
            before_acc = root / "before_accounting.json"
            after_acc = root / "after_accounting.json"
            repair_report = root / "repair.json"
            _write_iso_xml(before, compliant=True)
            _write_iso_xml(
                after,
                compliant=False,
                failed_rules=[
                    {
                        "clause": "14.8",
                        "failed_checks": 1,
                        "description": "StructParent mapping changed",
                        "contexts": ["Widget /StructParent 17 /OBJR"],
                    }
                ],
            )
            _write_accounting(before_acc, result="PASS")
            _write_accounting(after_acc, result="FAIL")
            repair_report.write_text(json.dumps({"target_rule": "PDF/UA-1/7.18.4"}))
            review = build_review(before, after, before_acc, after_acc, repair_report)
        self.assertEqual(review["before_iso_result"], "PASS")
        self.assertEqual(review["after_iso_result"], "FAIL")
        self.assertEqual(review["classification"], STRUCTURAL_SIDE_EFFECT)
        self.assertTrue(review["blocks_metadata_adoption"])
        self.assertTrue(review["blocks_runtime_activation"])
        self.assertTrue(review["correlation_to_struct_parent"])
        self.assertTrue(review["correlation_to_objr"])

    def test_pass_to_fail_without_context_is_inconclusive(self) -> None:
        with tempfile.TemporaryDirectory(prefix="h10c_iso_") as td:
            root = Path(td)
            before = root / "before.xml"
            after = root / "after.xml"
            _write_iso_xml(before, compliant=True)
            _write_iso_xml(
                after,
                compliant=False,
                failed_rules=[{"clause": "14.8", "failed_checks": 1, "description": "generic failure"}],
            )
            review = build_review(before, after)
        self.assertEqual(review["classification"], INCONCLUSIVE)
        self.assertTrue(review["blocks_metadata_adoption"])
        self.assertIn("ISO changed PASS to FAIL", review["recommendation"])

    def test_no_new_or_increased_iso_failures_is_benign_informational(self) -> None:
        with tempfile.TemporaryDirectory(prefix="h10c_iso_") as td:
            root = Path(td)
            before = root / "before.xml"
            after = root / "after.xml"
            _write_iso_xml(before, compliant=True)
            _write_iso_xml(after, compliant=True)
            review = build_review(before, after)
        self.assertEqual(review["classification"], BENIGN_INFORMATIONAL)
        self.assertFalse(review["blocks_metadata_adoption"])
        self.assertTrue(review["blocks_runtime_activation"])

    def test_iso_accounting_must_remain_informational_and_non_authoritative(self) -> None:
        with tempfile.TemporaryDirectory(prefix="h10c_iso_") as td:
            root = Path(td)
            before = root / "before.xml"
            after = root / "after.xml"
            before_acc = root / "before_accounting.json"
            after_acc = root / "after_accounting.json"
            _write_iso_xml(before, compliant=True)
            _write_iso_xml(after, compliant=True)
            _write_accounting(before_acc, result="PASS", classification="required_authoritative", authoritative=True)
            _write_accounting(after_acc, result="PASS")
            review = build_review(before, after, before_acc, after_acc)
        self.assertEqual(review["classification"], PROFILE_ACCOUNTING_ARTIFACT)
        self.assertTrue(review["blocks_metadata_adoption"])
        self.assertTrue(review["blocks_runtime_activation"])

    def test_missing_xml_is_inconclusive_and_blocks_adoption(self) -> None:
        with tempfile.TemporaryDirectory(prefix="h10c_iso_") as td:
            root = Path(td)
            review = build_review(root / "missing-before.xml", root / "missing-after.xml")
        self.assertEqual(review["classification"], INCONCLUSIVE)
        self.assertFalse(review["before_parseable"])
        self.assertFalse(review["after_parseable"])
        self.assertTrue(review["blocks_metadata_adoption"])


if __name__ == "__main__":
    unittest.main()
